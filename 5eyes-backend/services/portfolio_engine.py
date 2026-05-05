import json
import hashlib
import logging
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

from sqlalchemy.orm import Session

from config import settings
from database import new_uuid
from models.allocation import (
    BuildingBlock,
    CapitalMarketAssumption,
    HouseMatrix,
    OptimizerPolicy,
    TargetAllocation,
)
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.review import (
    PriceHistory,
    Product,
    ProductSuitability,
    RecommendationHolding,
    RecommendationPosition,
    RecommendationRun,
)
from models.wealth import Cashflow, Goal, PlanningAssumption, WealthPosition
from price_updater import latest_price_snapshot, parse_iso_date, summarize_price_quality
from services.cashflow_timeline import (
    future_value_with_cashflow_series,
    net_cashflow_series,
    normalize_frequency,
    recurring_net_cashflow_series,
    totals_for_year,
)
from services.product_market_data import resolve_market_profile, validate_default_product_market_coverage


BUCKET_FIELDS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")
BUCKET_LABELS = {
    "equities": "Aktien",
    "bonds": "Obligationen",
    "real_estate": "Immobilien",
    "alternatives": "Alternative",
    "liquidity": "Liquiditaet",
}
# Maximale strategische Liquiditaetsquote im SAA. Alles darueber wird extern empfohlen.
_SAA_LIQUIDITY_HARD_CAP_BPS: int = 300  # 3% absolutes Maximum
LABEL_TO_BUCKET = {value: key for key, value in BUCKET_LABELS.items()}
GOAL_WEIGHT_BY_RANK = {
    1: 10000,
    2: 5000,
    3: 2500,
    4: 1250,
    5: 625,
}
DEFAULT_POLICY_NAME = "5Eyes V1 Standard"
DEFAULT_CMA_NAME = "5Eyes V1 Hausmeinung"
ALLOWED_HOUSE_MATRIX_PROFILES = ("Kapitalschutz", "Defensiv", "Ausgewogen", "Wachstumsorientiert", "Dynamisch", "Aktien")
ALLOWED_PRODUCT_TYPES = (
    "ETF",
    "Fonds",
    "Einzeltitel",
    "Strukturiertes Produkt",
    "Anleihe",
    "Cash",
    "Immobilienfonds",
    "Alternative Anlage",
    "Sonstiges",
)
ALLOWED_PRODUCT_ASSET_CLASSES = ("Aktien", "Obligationen", "Immobilien", "Alternative", "Liquidität")

DEFAULT_ASSET_RISKY_WEIGHTS_BPS = {
    "equities": 7900,
    "bonds": 2450,
    "real_estate": 5000,
    "alternatives": 6000,
    "liquidity": 0,
}
ASSET_LIQUIDITY_PROFILES = {
    "equities": "T+2 liquide",
    "bonds": "liquide bis mittel",
    "real_estate": "teil- bis illiquide",
    "alternatives": "heterogen / teils illiquide",
    "liquidity": "taeglich verfuegbar",
}
DEFAULT_SIMULATION_HORIZON_YEARS = 10
DEFAULT_SIMULATION_STRESS_MULTIPLIER = 1.0
DEFAULT_MONTE_CARLO_SIMULATIONS = 750
ALLOWED_SIMULATION_REBALANCE_MODES = ("bands", "calendar", "none")
# One-sided transaction cost applied on rebalancing turnover (bid-ask + commission).
# 15 bps is a conservative Swiss institutional blended estimate across all asset classes.
DEFAULT_REBALANCE_TRANSACTION_COST_BPS = 15


@dataclass
class PortfolioSummary:
    amounts_rappen: dict[str, int]
    total_rappen: int


@dataclass
class StoredReferencePrice:
    price_date: str | None
    price_rappen: int | None
    source: str | None = None
    fetched_at: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _today() -> str:
    return date.today().isoformat()


def _parse_bps_percent(value) -> int | None:
    if value in (None, "", False):
        return None
    raw = str(value).replace("%", "").replace("'", "").replace(" ", "").replace(",", ".").strip()
    if not raw:
        return None
    try:
        return int(round(float(raw) * 100))
    except (TypeError, ValueError):
        return None


def _parse_rappen(value) -> int | None:
    if value in (None, "", False):
        return None
    raw = str(value).replace("CHF", "").replace("'", "").replace(" ", "").replace(",", ".").strip()
    if not raw:
        return None
    try:
        return int(round(float(raw) * 100))
    except (TypeError, ValueError):
        return None


def _norm_text(value) -> str:
    return (
        str(value or "")
        .replace("\xe4", "ae")
        .replace("\xf6", "oe")
        .replace("\xfc", "ue")
        .replace("\xc4", "Ae")
        .replace("\xd6", "Oe")
        .replace("\xdc", "Ue")
        .replace("\xdf", "ss")
    )


_REQUIRED_RISK_QUESTION_NUMBERS_FOR_STRATEGY = frozenset((3, 5, 6, 7, 8, 9, 10, 11))


def risk_assessment_ready_for_strategy(assessment: RiskAssessment | None) -> bool:
    if not assessment:
        return False
    if assessment.final_score_x10 is None and assessment.override_score_x10 is None:
        return False
    if assessment.is_overridden and assessment.override_score_x10 is not None:
        return True
    answers = getattr(assessment, "answers", None) or []
    answered_numbers = {
        int(getattr(answer, "question_number", 0) or 0)
        for answer in answers
        if getattr(answer, "answer_label", None)
    }
    return _REQUIRED_RISK_QUESTION_NUMBERS_FOR_STRATEGY.issubset(answered_numbers)


def require_strategy_ready_assessment(db: Session, mandate_id: str) -> RiskAssessment:
    assessment = db.query(RiskAssessment).filter(
        RiskAssessment.mandate_id == mandate_id,
        RiskAssessment.is_current == 1,
        RiskAssessment.deleted_at.is_(None),
    ).first()
    if not assessment:
        raise ValueError("Bitte zuerst ein aktuelles Risikoprofil speichern.")
    if not risk_assessment_ready_for_strategy(assessment):
        raise ValueError(
            "Risikoprofil unvollstaendig. Bitte Fragebogen vollstaendig ausfuellen und erneut speichern."
        )
    return assessment


def _normalize_preferences(preferences: dict | None) -> dict:
    prefs = preferences or {}
    return {
        "policy": prefs.get("policy") or {},
        "tilts": prefs.get("tilts") or {},
        "product": prefs.get("product") or {},
        "limits": prefs.get("limits") or {},
        "geo": prefs.get("geo") or {},
        "assetClasses": prefs.get("assetClasses") or {},
        "bands": prefs.get("bands") or {},
        "simulation": prefs.get("simulation") or {},
    }


def _bucket_key(value: str | None) -> str | None:
    raw = _norm_text(value)
    aliases = {
        "Aktien": "equities",
        "Obligationen": "bonds",
        "Immobilien": "real_estate",
        "Alternative": "alternatives",
        "Liquiditaet": "liquidity",
        "equities": "equities",
        "bonds": "bonds",
        "real_estate": "real_estate",
        "alternatives": "alternatives",
        "liquidity": "liquidity",
    }
    return aliases.get(raw)


def _coerce_band_bps(value) -> int | None:
    if value in (None, "", False):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value if abs(value) > 100 else value * 100))
    raw = str(value).replace("'", "").replace(" ", "").strip()
    if not raw:
        return None
    if "%" in raw:
        return _parse_bps_percent(raw)
    try:
        numeric = float(raw.replace(",", "."))
    except ValueError:
        return None
    return int(round(numeric if abs(numeric) > 100 else numeric * 100))


def _risk_score_bucket(assessment: RiskAssessment) -> int:
    score_x10 = assessment.override_score_x10 if assessment.is_overridden and assessment.override_score_x10 else assessment.final_score_x10
    return max(1, min(10, int(round((score_x10 or 10) / 10))))


def _default_weights_for_position(position: WealthPosition) -> dict[str, int]:
    total = (
        int(position.alloc_equities_bps or 0)
        + int(position.alloc_bonds_bps or 0)
        + int(position.alloc_real_estate_bps or 0)
        + int(position.alloc_alternatives_bps or 0)
        + int(position.alloc_liquidity_bps or 0)
    )
    if total == 10000:
        return {
            "equities": int(position.alloc_equities_bps or 0),
            "bonds": int(position.alloc_bonds_bps or 0),
            "real_estate": int(position.alloc_real_estate_bps or 0),
            "alternatives": int(position.alloc_alternatives_bps or 0),
            "liquidity": int(position.alloc_liquidity_bps or 0),
        }

    mapping = {
        "Depot": {"equities": 6000, "bonds": 2500, "real_estate": 0, "alternatives": 500, "liquidity": 1000},
        "Liquiditaet": {"equities": 0, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 10000},
        "Immobilien": {"equities": 0, "bonds": 0, "real_estate": 10000, "alternatives": 0, "liquidity": 0},
        "Vorsorge": {"equities": 4500, "bonds": 4500, "real_estate": 0, "alternatives": 0, "liquidity": 1000},
        "Alternative": {"equities": 0, "bonds": 0, "real_estate": 0, "alternatives": 10000, "liquidity": 0},
        "Hypothek": {"equities": 0, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 0},
        "Custom": {"equities": 5000, "bonds": 2000, "real_estate": 1000, "alternatives": 500, "liquidity": 1500},
    }
    return mapping.get(_norm_text(position.position_type), mapping["Custom"]).copy()


def _summarize_positions(positions: list[WealthPosition]) -> PortfolioSummary:
    amounts = {key: 0 for key in BUCKET_FIELDS}
    total_rappen = 0
    for pos in positions:
        value_rappen = int(pos.current_value_rappen or 0)
        if value_rappen <= 0:
            continue
        weights = _default_weights_for_position(pos)
        total_rappen += value_rappen
        for key in BUCKET_FIELDS:
            amounts[key] += int(round(value_rappen * weights[key] / 10000))
    return PortfolioSummary(amounts_rappen=amounts, total_rappen=total_rappen)


def _bps(amount_rappen: int, total_rappen: int) -> int:
    if total_rappen <= 0:
        return 0
    return int(round(amount_rappen / total_rappen * 10000))


def _amount_from_weight_bps(total_rappen: int, weight_bps: int) -> int:
    if total_rappen <= 0 or weight_bps <= 0:
        return 0
    return int(round(total_rappen * weight_bps / 10000))


def _current_recommendation_run(db: Session, mandate_id: str) -> RecommendationRun | None:
    current = db.query(RecommendationRun).filter(
        RecommendationRun.mandate_id == mandate_id,
        RecommendationRun.result_status == "Final",
    ).order_by(RecommendationRun.created_at.desc()).first()
    if current:
        return current
    return db.query(RecommendationRun).filter(
        RecommendationRun.mandate_id == mandate_id,
    ).order_by(RecommendationRun.created_at.desc()).first()


def _reference_price_snapshot_for_run(
    db: Session,
    product_ids: list[str],
    run_created_at: str | None,
) -> dict[str, PriceHistory]:
    if not product_ids:
        return {}
    run_anchor = str(run_created_at or "")[:10]
    rows = db.query(PriceHistory).filter(
        PriceHistory.product_id.in_(product_ids),
    ).order_by(
        PriceHistory.product_id.asc(),
        PriceHistory.price_date.desc(),
        PriceHistory.fetched_at.desc(),
    ).all()
    snapshots: dict[str, PriceHistory] = {}
    for row in rows:
        if row.product_id in snapshots:
            continue
        if not run_anchor:
            snapshots[row.product_id] = row
            continue
        if str(row.price_date or "") > run_anchor:
            continue
        snapshots[row.product_id] = row
    return snapshots


def _stored_reference_price_for_position(position: RecommendationPosition) -> StoredReferencePrice | None:
    price_rappen = getattr(position, "reference_price_rappen", None)
    if price_rappen is None:
        return None
    try:
        price_rappen_int = int(price_rappen or 0)
    except (TypeError, ValueError):
        return None
    if price_rappen_int <= 0:
        return None
    return StoredReferencePrice(
        price_date=getattr(position, "reference_price_date", None),
        price_rappen=price_rappen_int,
        source=getattr(position, "reference_price_source", None),
        fetched_at=getattr(position, "reference_price_fetched_at", None),
    )


def _holdings_snapshot_for_run(
    db: Session,
    run_id: str,
    position_ids: list[str],
) -> dict[str, RecommendationHolding]:
    if not position_ids:
        return {}
    rows = db.query(RecommendationHolding).filter(
        RecommendationHolding.run_id == run_id,
        RecommendationHolding.recommendation_position_id.in_(position_ids),
    ).order_by(
        RecommendationHolding.recommendation_position_id.asc(),
        RecommendationHolding.updated_at.desc(),
    ).all()
    holdings: dict[str, RecommendationHolding] = {}
    seen: set[str] = set()
    for row in rows:
        if row.recommendation_position_id in seen:
            continue
        seen.add(row.recommendation_position_id)
        if row.deleted_at is None:
            holdings[row.recommendation_position_id] = row
    return holdings


def _latest_holdings_by_product_for_mandate(
    db: Session,
    mandate_id: str,
) -> dict[str, RecommendationHolding]:
    rows = db.query(RecommendationHolding).join(
        RecommendationRun,
        RecommendationRun.id == RecommendationHolding.run_id,
    ).filter(
        RecommendationRun.mandate_id == mandate_id,
    ).order_by(
        RecommendationHolding.product_id.asc(),
        RecommendationHolding.updated_at.desc(),
    ).all()
    holdings: dict[str, RecommendationHolding] = {}
    seen: set[str] = set()
    for row in rows:
        if row.product_id in seen:
            continue
        seen.add(row.product_id)
        if row.deleted_at is None:
            holdings[row.product_id] = row
    return holdings


def _units_milli_from_amount(amount_rappen: int, reference_price_rappen: int | None) -> int | None:
    if amount_rappen <= 0 or not reference_price_rappen or reference_price_rappen <= 0:
        return None
    return int(round(amount_rappen * 1000 / reference_price_rappen))


def _value_from_units_milli(units_milli: int | None, price_rappen: int | None, fallback_amount_rappen: int = 0) -> int:
    if not units_milli or not price_rappen or price_rappen <= 0:
        return max(0, int(fallback_amount_rappen or 0))
    return max(0, int(round(units_milli * price_rappen / 1000)))


def _canonical_asset_class_label(value: str | None) -> str:
    key = _bucket_key(value)
    return BUCKET_LABELS.get(key or "", str(value or "Unbekannt"))


def _rebalancing_action(delta_weight_bps: int, rebalance_amount_rappen: int, price_available: bool) -> str:
    return _rebalancing_action_meta(delta_weight_bps, rebalance_amount_rappen, price_available)[1]


def _rebalancing_action_meta(delta_weight_bps: int, rebalance_amount_rappen: int, price_available: bool) -> tuple[str, str]:
    if not price_available:
        return "MISSING_PRICE", "Preis fehlt"
    if abs(delta_weight_bps) < 25 and abs(rebalance_amount_rappen) < 5000:
        return "HOLD", "Im Soll"
    if rebalance_amount_rappen > 0:
        return "BUY", "Aufbauen"
    if rebalance_amount_rappen < 0:
        return "SELL", "Reduzieren"
    return "CHECK", "Beobachten"


def _aligned_reference_price(
    reference_price: PriceHistory | StoredReferencePrice | None,
    latest_price: PriceHistory | None,
    lookup_mode: str | None,
) -> tuple[PriceHistory | StoredReferencePrice | None, bool]:
    if not latest_price:
        return reference_price, False
    if not reference_price:
        return latest_price, latest_price is not None

    reference_rappen = int(reference_price.price_rappen or 0)
    latest_rappen = int(latest_price.price_rappen or 0)
    if reference_rappen <= 0 or latest_rappen <= 0:
        return latest_price, True

    ratio = max(reference_rappen, latest_rappen) / max(1, min(reference_rappen, latest_rappen))
    recalibration_threshold = 1.5 if str(lookup_mode or "").strip() in {"proxy", "synthetic_par"} else 3
    if ratio < recalibration_threshold:
        return reference_price, False

    reference_source = str(reference_price.source or "").strip()
    latest_source = str(latest_price.source or "").strip()
    if str(lookup_mode or "").strip() in {"proxy", "synthetic_par"}:
        return latest_price, True
    if reference_source and latest_source and reference_source != latest_source:
        return latest_price, True
    return reference_price, False


def _load_live_rebalancing_sources(
    db: Session,
    run: RecommendationRun,
    recommendation_positions: list[RecommendationPosition],
) -> dict:
    product_ids = [position.product_id for position in recommendation_positions if position.product_id]
    position_ids = [position.id for position in recommendation_positions if position.id]
    if not product_ids:
        return {}
    market_data_quality = summarize_price_quality(db, product_ids)
    return {
        "product_ids": product_ids,
        "position_ids": position_ids,
        "products_by_id": {
            product.id: product
            for product in db.query(Product).filter(Product.id.in_(product_ids)).all()
        },
        "latest_prices": latest_price_snapshot(db, product_ids),
        "reference_prices": _reference_price_snapshot_for_run(db, product_ids, run.created_at),
        "holdings_by_position_id": _holdings_snapshot_for_run(db, run.id, position_ids),
        "holdings_by_product_id": _latest_holdings_by_product_for_mandate(db, run.mandate_id),
        "market_data_quality": market_data_quality,
        "stale_after_days": int(market_data_quality.get("stale_after_days") or 5),
        "today": date.today(),
    }


def _build_live_rebalancing_entry(
    position: RecommendationPosition,
    product: Product,
    holding: RecommendationHolding | None,
    latest_price: PriceHistory | None,
    reference_price: PriceHistory | StoredReferencePrice | None,
    reference_recalibrated: bool,
    target_amount_rappen: int,
    target_weight_bps: int,
    stale_after_days: int,
    today: date,
) -> tuple[dict, dict]:
    latest_price_rappen = int(latest_price.price_rappen or 0) if latest_price else None
    reference_price_date = reference_price.price_date if reference_price else None
    reference_price_rappen = int(reference_price.price_rappen or 0) if reference_price else None
    reference_price_source = getattr(reference_price, "source", None) if reference_price else None
    reference_price_fetched_at = getattr(reference_price, "fetched_at", None) if reference_price else None

    holding_present = False
    holding_source = None
    holding_as_of_date = None
    holding_units_milli = None
    holding_market_value_rappen = None
    holding_avg_cost_price_rappen = None
    holding_depot_bank = None
    holding_custody_account_number = None
    holding_notes = None
    valuation_basis = "implied_from_target"
    current_units_milli = None

    if holding:
        raw_units = int(holding.units_milli or 0)
        raw_market_value = int(holding.market_value_rappen or 0)
        holding_present = raw_units > 0 or raw_market_value > 0
        if holding_present:
            holding_source = str(holding.source or "").strip() or "manual"
            holding_as_of_date = str(holding.as_of_date or "").strip() or None
            holding_units_milli = raw_units if raw_units > 0 else None
            holding_market_value_rappen = raw_market_value if raw_market_value > 0 else None
            holding_avg_cost_price_rappen = int(holding.avg_cost_price_rappen or 0) or None
            holding_depot_bank = str(holding.depot_bank or "").strip() or None
            holding_custody_account_number = str(holding.custody_account_number or "").strip() or None
            holding_notes = str(holding.notes or "").strip() or None
            if holding_avg_cost_price_rappen:
                reference_price_rappen = holding_avg_cost_price_rappen
                reference_price_date = holding_as_of_date or reference_price_date
                reference_recalibrated = False
            if holding_units_milli:
                current_units_milli = holding_units_milli
                valuation_basis = "actual_holding_units"
            else:
                current_units_milli = _units_milli_from_amount(
                    holding_market_value_rappen or 0,
                    latest_price_rappen or reference_price_rappen,
                )
                valuation_basis = "actual_holding_market_value"

    implied_units_milli = _units_milli_from_amount(target_amount_rappen, reference_price_rappen)
    if not current_units_milli:
        current_units_milli = implied_units_milli
        if not holding_present:
            valuation_basis = "implied_from_target"

    reference_value_rappen = _value_from_units_milli(current_units_milli, reference_price_rappen, target_amount_rappen)
    current_market_value_rappen = _value_from_units_milli(
        current_units_milli,
        latest_price_rappen or reference_price_rappen,
        holding_market_value_rappen or reference_value_rappen or target_amount_rappen,
    )

    price_date = parse_iso_date(latest_price.price_date) if latest_price else None
    price_age_days = (today - price_date).days if price_date else None
    price_is_fresh = bool(price_age_days is not None and price_age_days <= stale_after_days)
    price_change_bps = None
    if latest_price_rappen and reference_price_rappen and reference_price_rappen > 0:
        price_change_bps = int(round((latest_price_rappen / reference_price_rappen - 1) * 10000))

    entry = {
        "id": position.id,
        "product_id": product.id,
        "product_name": product.product_name,
        "asset_class": _canonical_asset_class_label(product.asset_class),
        "sub_asset_class": product.sub_asset_class,
        "target_weight_bps": target_weight_bps,
        "target_amount_rappen": target_amount_rappen,
        "reference_price_date": reference_price_date,
        "reference_price_rappen": reference_price_rappen,
        "reference_price_source": reference_price_source,
        "reference_lookup_mode": getattr(position, "reference_lookup_mode", None),
        "reference_price_fetched_at": reference_price_fetched_at,
        "reference_recalibrated": reference_recalibrated,
        "latest_price_date": latest_price.price_date if latest_price else None,
        "latest_price_rappen": latest_price_rappen,
        "price_age_days": price_age_days,
        "price_is_fresh": price_is_fresh if latest_price else None,
        "holding_present": holding_present,
        "holding_source": holding_source,
        "holding_as_of_date": holding_as_of_date,
        "holding_units_milli": holding_units_milli,
        "current_units_milli": current_units_milli,
        "holding_market_value_rappen": holding_market_value_rappen,
        "holding_avg_cost_price_rappen": holding_avg_cost_price_rappen,
        "holding_depot_bank": holding_depot_bank,
        "holding_custody_account_number": holding_custody_account_number,
        "holding_notes": holding_notes,
        "valuation_basis": valuation_basis,
        "implied_units_milli": implied_units_milli,
        "current_market_value_rappen": current_market_value_rappen,
        "price_change_bps": price_change_bps,
    }
    stats = {
        "current_total_value_rappen": current_market_value_rappen,
        "missing_prices_count": 0 if latest_price else 1,
        "stale_positions_count": 1 if latest_price and not price_is_fresh else 0,
        "priced_positions_count": 1 if latest_price else 0,
        "as_of_dates": [latest_price.price_date] if latest_price and latest_price.price_date else [],
        "recalibrated_positions_count": 1 if reference_recalibrated else 0,
        "holding_positions_count": 1 if holding_present else 0,
        "implied_positions_count": 0 if holding_present else 1,
    }
    return entry, stats


def _build_live_bucket_targets(allocation: TargetAllocation) -> dict[str, dict[str, int]]:
    return {
        "Aktien": {
            "target_weight_bps": int(allocation.target_equities_bps or 0),
            "band_min_bps": int(allocation.band_equities_min_bps or 0),
            "band_max_bps": int(allocation.band_equities_max_bps or 0),
        },
        "Obligationen": {
            "target_weight_bps": int(allocation.target_bonds_bps or 0),
            "band_min_bps": int(allocation.band_bonds_min_bps or 0),
            "band_max_bps": int(allocation.band_bonds_max_bps or 0),
        },
        "Immobilien": {
            "target_weight_bps": int(allocation.target_real_estate_bps or 0),
            "band_min_bps": int(allocation.band_real_estate_min_bps or 0),
            "band_max_bps": int(allocation.band_real_estate_max_bps or 0),
        },
        "Alternative": {
            "target_weight_bps": int(allocation.target_alternatives_bps or 0),
            "band_min_bps": int(allocation.band_alternatives_min_bps or 0),
            "band_max_bps": int(allocation.band_alternatives_max_bps or 0),
        },
        "Liquiditaet": {
            "target_weight_bps": int(allocation.target_liquidity_bps or 0),
            "band_min_bps": int(allocation.band_liquidity_min_bps or 0),
            "band_max_bps": int(allocation.band_liquidity_max_bps or 0),
        },
    }


def _build_live_bucket_drifts(
    allocation: TargetAllocation,
    entries: list[dict],
    live_total_value_rappen: int,
) -> tuple[list[dict], list[str], int]:
    bucket_targets = _build_live_bucket_targets(allocation)
    bucket_current_values: defaultdict[str, int] = defaultdict(int)
    for entry in entries:
        bucket_current_values[str(entry["asset_class"])] += int(entry["current_market_value_rappen"] or 0)

    bucket_drifts = []
    breached_asset_classes = []
    total_rebalance_abs_rappen = 0
    for asset_class in ("Aktien", "Obligationen", "Immobilien", "Alternative", "Liquiditaet"):
        config = bucket_targets[asset_class]
        current_value_rappen = int(bucket_current_values.get(asset_class) or 0)
        current_weight_bps = _bps(current_value_rappen, live_total_value_rappen)
        target_weight_bps = int(config["target_weight_bps"])
        target_market_value_rappen = _amount_from_weight_bps(live_total_value_rappen, target_weight_bps)
        rebalance_amount_rappen = target_market_value_rappen - current_value_rappen
        delta_weight_bps = current_weight_bps - target_weight_bps
        min_weight = int(config["band_min_bps"])
        max_weight = int(config["band_max_bps"])
        breach_bps = 0
        if current_weight_bps < min_weight:
            breach_bps = min_weight - current_weight_bps
        elif current_weight_bps > max_weight:
            breach_bps = current_weight_bps - max_weight
        breached = breach_bps > 0
        if breached:
            breached_asset_classes.append(asset_class)
        total_rebalance_abs_rappen += abs(rebalance_amount_rappen)
        bucket_drifts.append(
            {
                "asset_class": asset_class,
                "current_weight_bps": current_weight_bps,
                "target_weight_bps": target_weight_bps,
                "band_min_bps": min_weight,
                "band_max_bps": max_weight,
                "current_market_value_rappen": current_value_rappen,
                "target_market_value_rappen": target_market_value_rappen,
                "delta_weight_bps": delta_weight_bps,
                "rebalance_amount_rappen": rebalance_amount_rappen,
                "breached": breached,
                "breach_bps": breach_bps,
            }
        )
    return bucket_drifts, breached_asset_classes, total_rebalance_abs_rappen


def _build_live_position_drifts(entries: list[dict], live_total_value_rappen: int) -> list[dict]:
    position_drifts = []
    for entry in entries:
        current_weight_bps = _bps(int(entry["current_market_value_rappen"] or 0), live_total_value_rappen)
        rebalance_amount_rappen = _amount_from_weight_bps(live_total_value_rappen, int(entry["target_weight_bps"] or 0)) - int(entry["current_market_value_rappen"] or 0)
        delta_weight_bps = current_weight_bps - int(entry["target_weight_bps"] or 0)
        latest_price_available = entry["latest_price_rappen"] is not None or entry["reference_price_rappen"] is not None
        action_code, action_label = _rebalancing_action_meta(delta_weight_bps, rebalance_amount_rappen, latest_price_available)
        position_drifts.append(
            {
                **entry,
                "current_weight_bps": current_weight_bps,
                "delta_weight_bps": delta_weight_bps,
                "rebalance_amount_rappen": rebalance_amount_rappen,
                "rebalance_action": action_label,
                "rebalance_action_code": action_code,
                "rebalance_action_label": action_label,
            }
        )
    return sorted(position_drifts, key=lambda item: abs(int(item["rebalance_amount_rappen"] or 0)), reverse=True)


def _build_live_action_summary(bucket_drifts: list[dict]) -> list[str]:
    action_summary = []
    for bucket in sorted(bucket_drifts, key=lambda item: abs(int(item["rebalance_amount_rappen"] or 0)), reverse=True):
        if abs(int(bucket["rebalance_amount_rappen"] or 0)) < 5000:
            continue
        direction = "aufbauen" if int(bucket["rebalance_amount_rappen"]) > 0 else "reduzieren"
        amount_chf = int(round(abs(int(bucket["rebalance_amount_rappen"])) / 100))
        band_note = " / Band verletzt" if bucket["breached"] else ""
        action_summary.append(
            f"{bucket['asset_class']} {direction}: ca. CHF {amount_chf:,.0f}{band_note}".replace(",", "'")
        )
    if not action_summary:
        action_summary.append("Live-Bewertung liegt aktuell innerhalb der strategischen Zielbandbreiten.")
    return action_summary


def build_live_rebalancing_payload(
    db: Session,
    allocation: TargetAllocation,
    run: RecommendationRun,
    advisory_wealth_rappen: int,
    positions: list[RecommendationPosition] | None = None,
) -> dict | None:
    recommendation_positions = positions or db.query(RecommendationPosition).filter(
        RecommendationPosition.run_id == run.id,
    ).order_by(RecommendationPosition.target_weight_bps.desc()).all()
    if not recommendation_positions:
        return None

    sources = _load_live_rebalancing_sources(db, run, recommendation_positions)
    if not sources:
        return None

    entries: list[dict] = []
    aggregate = {
        "current_total_value_rappen": 0,
        "missing_prices_count": 0,
        "stale_positions_count": 0,
        "priced_positions_count": 0,
        "as_of_dates": [],
        "recalibrated_positions_count": 0,
        "holding_positions_count": 0,
        "implied_positions_count": 0,
    }

    for position in recommendation_positions:
        product = sources["products_by_id"].get(position.product_id)
        if not product:
            continue
        market_profile = resolve_market_profile(product)
        target_weight_bps = int(position.target_weight_bps or 0)
        target_amount_rappen = int(position.target_amount_rappen or 0)
        if target_amount_rappen <= 0:
            target_amount_rappen = _amount_from_weight_bps(advisory_wealth_rappen, target_weight_bps)
        holding = sources["holdings_by_position_id"].get(position.id) or sources["holdings_by_product_id"].get(position.product_id)
        latest_price = sources["latest_prices"].get(product.id)
        reference_price, reference_recalibrated = _aligned_reference_price(
            _stored_reference_price_for_position(position) or sources["reference_prices"].get(product.id),
            latest_price,
            market_profile.get("lookup_mode"),
        )
        entry, stats = _build_live_rebalancing_entry(
            position=position,
            product=product,
            holding=holding,
            latest_price=latest_price,
            reference_price=reference_price,
            reference_recalibrated=reference_recalibrated,
            target_amount_rappen=target_amount_rappen,
            target_weight_bps=target_weight_bps,
            stale_after_days=sources["stale_after_days"],
            today=sources["today"],
        )
        entries.append(entry)
        aggregate["current_total_value_rappen"] += stats["current_total_value_rappen"]
        aggregate["missing_prices_count"] += stats["missing_prices_count"]
        aggregate["stale_positions_count"] += stats["stale_positions_count"]
        aggregate["priced_positions_count"] += stats["priced_positions_count"]
        aggregate["as_of_dates"].extend(stats["as_of_dates"])
        aggregate["recalibrated_positions_count"] += stats["recalibrated_positions_count"]
        aggregate["holding_positions_count"] += stats["holding_positions_count"]
        aggregate["implied_positions_count"] += stats["implied_positions_count"]

    live_total_value_rappen = aggregate["current_total_value_rappen"] or max(
        advisory_wealth_rappen,
        sum(int(item["target_amount_rappen"] or 0) for item in entries),
    )
    if live_total_value_rappen <= 0:
        return None

    bucket_drifts, breached_asset_classes, total_rebalance_abs_rappen = _build_live_bucket_drifts(
        allocation=allocation,
        entries=entries,
        live_total_value_rappen=live_total_value_rappen,
    )
    position_drifts = _build_live_position_drifts(entries, live_total_value_rappen)
    action_summary = _build_live_action_summary(bucket_drifts)

    return {
        "as_of_date": max(aggregate["as_of_dates"]) if aggregate["as_of_dates"] else None,
        "reference_anchor_date": str(run.created_at or "")[:10] or None,
        "methodology": (
            f"Echte Bestandsbasis fuer {aggregate['holding_positions_count']} Position(en); "
            f"{aggregate['implied_positions_count']} Position(en) weiterhin implizit aus Zielbetrag und Referenzpreis zum Run-Zeitpunkt. "
            "Live-Werte aus dem letzten verfuegbaren Preis-Snapshot."
        ) + (" Referenzanker wurden fuer einzelne Proxy-/Synthetic-Positionen auf das aktuelle Preisregime rekalibriert." if aggregate["recalibrated_positions_count"] else ""),
        "live_total_value_rappen": live_total_value_rappen,
        "priced_positions_count": aggregate["priced_positions_count"],
        "stale_positions_count": aggregate["stale_positions_count"],
        "missing_prices_count": aggregate["missing_prices_count"],
        "holding_positions_count": aggregate["holding_positions_count"],
        "implied_positions_count": aggregate["implied_positions_count"],
        "turnover_required_rappen": int(round(total_rebalance_abs_rappen / 2)),
        "breached_asset_classes": breached_asset_classes,
        "action_summary": action_summary,
        "market_data_quality": sources["market_data_quality"],
        "recalibrated_positions_count": aggregate["recalibrated_positions_count"],
        "bucket_drifts": bucket_drifts,
        "position_drifts": position_drifts,
    }


def _building_block_risky_map(db: Session, policy_id: str) -> dict[tuple[str, str], int]:
    rows = db.query(BuildingBlock).filter(
        BuildingBlock.policy_id == policy_id,
        BuildingBlock.is_active == 1,
    ).all()
    return {
        (_norm_text(row.asset_class), _norm_text(row.sub_asset_class)): int(row.risky_fraction_bps or 0)
        for row in rows
    }


def _asset_risky_weight_fallbacks() -> dict[str, int]:
    return DEFAULT_ASSET_RISKY_WEIGHTS_BPS.copy()


def _apply_band_preferences(
    bands: dict | None,
    targets: dict[str, int],
    minimums: dict[str, int],
    maximums: dict[str, int],
    reasoning: list[str],
) -> None:
    if not bands:
        return
    applied = []
    for raw_key, override in bands.items():
        bucket = _bucket_key(raw_key)
        if not bucket or not isinstance(override, dict):
            continue
        minimum = _coerce_band_bps(override.get("min_bps"))
        target = _coerce_band_bps(override.get("target_bps"))
        maximum = _coerce_band_bps(override.get("max_bps"))
        if minimum is not None:
            minimums[bucket] = minimum
        if target is not None:
            targets[bucket] = target
        if maximum is not None:
            maximums[bucket] = maximum
        applied.append(BUCKET_LABELS[bucket])
    if not applied:
        return
    for key in BUCKET_FIELDS:
        values = (minimums[key], targets[key], maximums[key])
        if min(values) < 0 or max(values) > 10000:
            raise ValueError(f"Bandbreiten fuer {BUCKET_LABELS[key]} muessen zwischen 0% und 100% liegen.")
        if not (minimums[key] <= targets[key] <= maximums[key]):
            raise ValueError(
                f"Bandbreiten fuer {BUCKET_LABELS[key]} sind inkonsistent: Min {minimums[key]} / Ziel {targets[key]} / Max {maximums[key]}."
            )
    total = sum(int(targets[key]) for key in BUCKET_FIELDS)
    if total != 10000:
        raise ValueError(f"Mandatsspezifische Zielquoten muessen 100% ergeben (aktuell {total / 100:.2f}%).")
    reasoning.append("Mandatsspezifische Soll-Quoten und Bandbreiten werden als Simulations-Constraint beruecksichtigt.")


def _has_manual_target_overrides(bands: dict | None) -> bool:
    if not isinstance(bands, dict):
        return False
    return any(
        isinstance(override, dict) and _coerce_band_bps(override.get("target_bps")) is not None
        for override in bands.values()
    )


def _rebalance_to_total(targets: dict[str, int], minimums: dict[str, int], maximums: dict[str, int]) -> dict[str, int]:
    adjusted = {key: int(targets[key]) for key in BUCKET_FIELDS}
    for key in BUCKET_FIELDS:
        adjusted[key] = max(minimums[key], min(maximums[key], adjusted[key]))

    def _room_up(name: str) -> int:
        return maximums[name] - adjusted[name]

    def _room_down(name: str) -> int:
        return adjusted[name] - minimums[name]

    current_total = sum(adjusted.values())
    delta = 10000 - current_total
    if delta > 0:
        for key in ("bonds", "liquidity", "equities", "real_estate", "alternatives"):
            if delta <= 0:
                break
            step = min(delta, _room_up(key))
            if step > 0:
                adjusted[key] += step
                delta -= step
    elif delta < 0:
        delta = abs(delta)
        for key in ("equities", "alternatives", "real_estate", "bonds", "liquidity"):
            if delta <= 0:
                break
            step = min(delta, _room_down(key))
            if step > 0:
                adjusted[key] -= step
                delta -= step
    final_total = sum(adjusted.values())
    if final_total != 10000:
        raise ValueError(
            f"Target allocation cannot be normalized to 10000 bps within min/max bounds "
            f"(total={final_total}, targets={adjusted})."
        )
    return adjusted


def _enrich_sub_allocations_with_risk(
    sub_allocations: list[dict],
    risky_map: dict[tuple[str, str], int],
) -> tuple[list[dict], dict[str, int], int]:
    enriched: list[dict] = []
    weighted_totals = {key: 0 for key in BUCKET_FIELDS}
    weight_totals = {key: 0 for key in BUCKET_FIELDS}
    total_risky_fraction_bps = 0
    for sub in sub_allocations:
        bucket = _bucket_key(sub.get("asset_class"))
        if not bucket:
            continue
        risky_fraction_bps = risky_map.get(
            (_norm_text(sub.get("asset_class")), _norm_text(sub.get("sub_asset_class"))),
            _asset_risky_weight_fallbacks().get(bucket, 0),
        )
        weight = int(sub.get("target_weight_bps") or 0)
        weighted_totals[bucket] += int(round(weight * risky_fraction_bps))
        weight_totals[bucket] += weight
        total_risky_fraction_bps += int(round(weight * risky_fraction_bps / 10000))
        enriched.append({**sub, "risky_fraction_bps": int(risky_fraction_bps)})
    asset_risky_weights = _asset_risky_weight_fallbacks()
    for bucket in BUCKET_FIELDS:
        if weight_totals[bucket] > 0:
            asset_risky_weights[bucket] = int(round(weighted_totals[bucket] / weight_totals[bucket]))
    return enriched, asset_risky_weights, total_risky_fraction_bps


def _risk_budget_from_targets(targets: dict[str, int], asset_risky_weights: dict[str, int]) -> int:
    return int(round(sum(int(targets[key]) * int(asset_risky_weights.get(key, 0)) for key in BUCKET_FIELDS) / 10000))


def _enforce_risk_budget(
    targets: dict[str, int],
    minimums: dict[str, int],
    maximums: dict[str, int],
    asset_risky_weights: dict[str, int],
    risk_budget_bps: int,
) -> tuple[dict[str, int], int]:
    adjusted = {key: int(targets[key]) for key in BUCKET_FIELDS}
    current_risk = _risk_budget_from_targets(adjusted, asset_risky_weights)
    loops = 0
    while current_risk > risk_budget_bps and loops < 400:
        loops += 1
        receiver = "bonds" if adjusted["bonds"] < maximums["bonds"] else ("liquidity" if adjusted["liquidity"] < maximums["liquidity"] else None)
        if not receiver:
            break
        receiver_room = maximums[receiver] - adjusted[receiver]
        if receiver_room <= 0:
            break
        donors = [
            key for key in ("equities", "alternatives", "real_estate", "bonds")
            if adjusted[key] > minimums[key] and asset_risky_weights.get(key, 0) > asset_risky_weights.get(receiver, 0)
        ]
        if not donors:
            break
        donor = sorted(
            donors,
            key=lambda key: (asset_risky_weights.get(key, 0), adjusted[key] - minimums[key]),
            reverse=True,
        )[0]
        step = min(100, adjusted[donor] - minimums[donor], receiver_room)
        if step <= 0:
            break
        adjusted[donor] -= step
        adjusted[receiver] += step
        current_risk = _risk_budget_from_targets(adjusted, asset_risky_weights)
    if current_risk > risk_budget_bps:
        overshoot_bps = current_risk - risk_budget_bps
        raise ValueError(
            f"Risikobudget konnte nicht eingehalten werden: "
            f"Ist={current_risk} bps, Limit={risk_budget_bps} bps, "
            f"Überschreitung={overshoot_bps} bps. "
            f"Bitte Mindestquoten der Anlageklassen prüfen oder Kundenprofil korrigieren."
        )
    return adjusted, current_risk


_DEFAULT_CORRELATION_MATRIX: list[list[float]] = [
    # equities  bonds  real_estate  alternatives  liquidity
    [1.00, -0.20,  0.35,  0.20,  0.05],  # equities
    [-0.20,  1.00,  0.10, -0.05,  0.10],  # bonds
    [0.35,  0.10,  1.00,  0.15,  0.05],  # real_estate
    [0.20, -0.05,  0.15,  1.00,  0.00],  # alternatives
    [0.05,  0.10,  0.05,  0.00,  1.00],  # liquidity
]

_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS: dict[str, dict[str, object]] = {
    "Aktien Schweiz": {"asset_class": "Aktien", "expected_return_bps": 620, "expected_volatility_bps": 1450},
    "Aktien Schweiz Small/Mid": {"asset_class": "Aktien", "expected_return_bps": 670, "expected_volatility_bps": 1650},
    "Aktien Global": {"asset_class": "Aktien", "expected_return_bps": 700, "expected_volatility_bps": 1600},
    "Aktien Europa": {"asset_class": "Aktien", "expected_return_bps": 640, "expected_volatility_bps": 1550},
    "Aktien Schwellenlaender": {"asset_class": "Aktien", "expected_return_bps": 760, "expected_volatility_bps": 1900},
    "Thema Verteidigung": {"asset_class": "Aktien", "expected_return_bps": 700, "expected_volatility_bps": 1650},
    "Thema Fossile Energie": {"asset_class": "Aktien", "expected_return_bps": 710, "expected_volatility_bps": 1750},
    "Thema Tabak": {"asset_class": "Aktien", "expected_return_bps": 660, "expected_volatility_bps": 1500},
    "Thema Alkohol": {"asset_class": "Aktien", "expected_return_bps": 650, "expected_volatility_bps": 1450},
    "Thema Gluecksspiel": {"asset_class": "Aktien", "expected_return_bps": 720, "expected_volatility_bps": 1850},
    "Thema Kernenergie": {"asset_class": "Aktien", "expected_return_bps": 680, "expected_volatility_bps": 1600},
    "Obligationen CHF IG": {"asset_class": "Obligationen", "expected_return_bps": 220, "expected_volatility_bps": 350},
    "Obligationen Global Hedged": {"asset_class": "Obligationen", "expected_return_bps": 220, "expected_volatility_bps": 430},
    "Obligationen High Yield": {"asset_class": "Obligationen", "expected_return_bps": 420, "expected_volatility_bps": 950},
    "Obligationen Emerging": {"asset_class": "Obligationen", "expected_return_bps": 400, "expected_volatility_bps": 1100},
    "Immobilien Schweiz": {"asset_class": "Immobilien", "expected_return_bps": 450, "expected_volatility_bps": 820},
    "Immobilien Global": {"asset_class": "Immobilien", "expected_return_bps": 410, "expected_volatility_bps": 980},
    "Gold / Rohstoffe": {"asset_class": "Alternative", "expected_return_bps": 300, "expected_volatility_bps": 1200},
    "Liquid Alternatives": {"asset_class": "Alternative", "expected_return_bps": 320, "expected_volatility_bps": 700},
    "Hedge Funds": {"asset_class": "Alternative", "expected_return_bps": 420, "expected_volatility_bps": 900},
    "Private Equity": {"asset_class": "Alternative", "expected_return_bps": 800, "expected_volatility_bps": 2200},
    "Krypto": {"asset_class": "Alternative", "expected_return_bps": 1200, "expected_volatility_bps": 4500},
    "Geldmarktfonds": {"asset_class": "Liquiditaet", "expected_return_bps": 80, "expected_volatility_bps": 15},
    "Festgeld": {"asset_class": "Liquiditaet", "expected_return_bps": 100, "expected_volatility_bps": 10},
}

_ASSET_CLASS_LABEL_TO_BUCKET = {
    "Aktien": "equities",
    "Obligationen": "bonds",
    "Immobilien": "real_estate",
    "Alternative": "alternatives",
    "Liquiditaet": "liquidity",
}


def _cholesky(matrix: list[list[float]]) -> list[list[float]]:
    """Lower-triangular Cholesky decomposition of a positive-definite matrix.
    Returns L such that L @ L^T == matrix."""
    n = len(matrix)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                L[i][j] = math.sqrt(max(0.0, matrix[i][i] - s))
            else:
                L[i][j] = (matrix[i][j] - s) / L[j][j] if L[j][j] > 1e-12 else 0.0
    return L


def _is_valid_cholesky(L: list[list[float]]) -> bool:
    """Return True if all diagonal entries of L are above numerical threshold.
    A zero diagonal means the input matrix was not positive-definite and the
    decomposition silently zeroed that row/column, producing wrong correlations."""
    return all(L[i][i] > 1e-10 for i in range(len(L)))


def _identity_cholesky(n: int) -> list[list[float]]:
    """Return identity matrix of size n (= uncorrelated assets)."""
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def _build_cholesky_from_cma(cma: CapitalMarketAssumption) -> list[list[float]]:
    """Return lower-triangular Cholesky matrix for the 5 asset classes.
    Uses CMA's correlation_matrix_json when available, else Swiss-market defaults.

    Falls back gracefully if the custom matrix is not positive-definite:
    custom → default Swiss-market → identity (uncorrelated).
    """
    matrix = _DEFAULT_CORRELATION_MATRIX
    used_custom = False
    if cma.correlation_matrix_json:
        try:
            parsed = json.loads(cma.correlation_matrix_json)
            if isinstance(parsed, list) and len(parsed) == 5 and all(len(row) == 5 for row in parsed):
                matrix = [[float(v) for v in row] for row in parsed]
                used_custom = True
        except (ValueError, TypeError, KeyError):
            pass

    L = _cholesky(matrix)

    if not _is_valid_cholesky(L):
        if used_custom:
            logger.warning(
                "Custom correlation matrix is not positive-definite; "
                "falling back to default Swiss-market correlation matrix."
            )
            L = _cholesky(_DEFAULT_CORRELATION_MATRIX)
        if not _is_valid_cholesky(L):
            logger.warning(
                "Default correlation matrix is also degenerate; "
                "using identity matrix (uncorrelated assets) for Monte Carlo."
            )
            L = _identity_cholesky(len(_DEFAULT_CORRELATION_MATRIX))

    return L


def _sub_asset_class_assumption_map(cma: CapitalMarketAssumption) -> dict[str, dict[str, int | str]]:
    assumptions: dict[str, dict[str, int | str]] = {}
    raw_payload = cma.sub_asset_class_assumptions_json or ""
    if raw_payload:
        try:
            parsed = json.loads(raw_payload)
            if isinstance(parsed, dict):
                for sub_asset_class, raw in parsed.items():
                    if not isinstance(raw, dict):
                        continue
                    assumptions[str(sub_asset_class)] = {
                        "asset_class": str(raw.get("asset_class") or _DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS.get(str(sub_asset_class), {}).get("asset_class") or ""),
                        "expected_return_bps": int(raw.get("expected_return_bps") or 0),
                        "expected_volatility_bps": int(raw.get("expected_volatility_bps") or 0),
                    }
        except (TypeError, ValueError, json.JSONDecodeError):
            assumptions = {}

    for sub_asset_class, defaults in _DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS.items():
        item = assumptions.get(sub_asset_class) or {}
        assumptions[sub_asset_class] = {
            "asset_class": str(item.get("asset_class") or defaults["asset_class"]),
            "expected_return_bps": int(item.get("expected_return_bps") or defaults["expected_return_bps"]),
            "expected_volatility_bps": int(item.get("expected_volatility_bps") or defaults["expected_volatility_bps"]),
        }
    return assumptions


def _sub_asset_class_metrics(
    sub_asset_class: str,
    asset_class: str,
    cma: CapitalMarketAssumption,
    fallback_returns: dict[str, int],
    fallback_vols: dict[str, int],
) -> tuple[int, int]:
    assumptions = _sub_asset_class_assumption_map(cma)
    item = assumptions.get(str(sub_asset_class))
    bucket = _ASSET_CLASS_LABEL_TO_BUCKET.get(str(asset_class), "liquidity")
    if item:
        return int(item["expected_return_bps"]), int(item["expected_volatility_bps"])
    return int(fallback_returns[bucket]), int(fallback_vols[bucket])


def _asset_class_expected_metrics(cma: CapitalMarketAssumption) -> tuple[dict[str, int], dict[str, int]]:
    """Reine CMA-Bucket-Defaults. KEIN Mischen mit Sub-Asset-Class-Annahmen.

    C3: Vor dem Fix wurden die Bucket-Returns mit dem ungewichteten Mittel
    aller Sub-Asset-Class-Annahmen ueberschrieben. Damit fuehrte das blosse
    Vorhandensein einer EM-Annahme im CMA-JSON dazu, dass die Equity-Rendite
    insgesamt nach oben gezogen wurde - selbst wenn die tatsaechliche
    Sub-Allocation 0% EM enthielt. Diese Funktion liefert nun nur die
    CMA-Bucket-Felder; tatsaechliche Bucket-Metriken aus Sub-Allocation
    werden ueber _weighted_bucket_metrics() berechnet.
    """
    returns = {
        "equities": int(round(((cma.equity_ch_return_bps or 500) + (cma.equity_intl_return_bps or 650)) / 2)),
        "bonds": int(round(((cma.bonds_chf_ig_return_bps or 180) + (cma.bonds_fx_hedged_return_bps or 220)) / 2)),
        "real_estate": int(cma.real_estate_ch_return_bps or 350),
        "alternatives": int(cma.alternatives_gold_return_bps or 300),
        "liquidity": int(cma.liquidity_return_bps or 80),
    }
    vols = {
        "equities": int(round(((cma.equity_ch_vol_bps or 1200) + (cma.equity_intl_vol_bps or 1450)) / 2)),
        "bonds": int(round(((cma.bonds_chf_ig_vol_bps or 350) + (cma.bonds_fx_hedged_vol_bps or 450)) / 2)),
        "real_estate": int(cma.real_estate_ch_vol_bps or 700),
        "alternatives": int(cma.alternatives_gold_vol_bps or 950),
        "liquidity": int(cma.liquidity_vol_bps or 20),
    }
    return returns, vols


def _weighted_bucket_metrics(
    cma: CapitalMarketAssumption,
    sub_allocations: list[dict] | None,
) -> tuple[dict[str, int], dict[str, int]]:
    """Bucket-Return/Vol gewichtet aus tatsaechlichen Sub-Allocations.

    C3: Pro Bucket wird der gewichtete Mittelwert aus Sub-Asset-Class-
    target_weight_bps und Sub-Asset-Class-CMA-Annahmen gebildet.
    Ohne Sub-Allocations oder fuer einen Bucket ohne Sub-Eintrag wird
    auf die CMA-Bucket-Defaults aus _asset_class_expected_metrics()
    zurueckgegriffen.
    """
    fallback_returns, fallback_vols = _asset_class_expected_metrics(cma)
    if not sub_allocations:
        return fallback_returns, fallback_vols

    assumptions = _sub_asset_class_assumption_map(cma)
    weighted_ret_bps: dict[str, int] = {key: 0 for key in fallback_returns}
    weighted_vol_bps: dict[str, int] = {key: 0 for key in fallback_vols}
    weight_sum: dict[str, int] = {key: 0 for key in fallback_returns}

    for item in sub_allocations:
        asset_class_label = str(item.get("asset_class") or "")
        sub_label = str(item.get("sub_asset_class") or "")
        weight = max(0, int(item.get("target_weight_bps") or 0))
        bucket = _ASSET_CLASS_LABEL_TO_BUCKET.get(asset_class_label)
        if not bucket or weight <= 0:
            continue
        sub = assumptions.get(sub_label)
        if sub:
            ret_bps = int(sub.get("expected_return_bps") or 0)
            vol_bps = int(sub.get("expected_volatility_bps") or 0)
        else:
            ret_bps = fallback_returns[bucket]
            vol_bps = fallback_vols[bucket]
        weighted_ret_bps[bucket] += ret_bps * weight
        weighted_vol_bps[bucket] += vol_bps * weight
        weight_sum[bucket] += weight

    returns = dict(fallback_returns)
    vols = dict(fallback_vols)
    for bucket in fallback_returns:
        if weight_sum[bucket] > 0:
            returns[bucket] = int(round(weighted_ret_bps[bucket] / weight_sum[bucket]))
            vols[bucket] = int(round(weighted_vol_bps[bucket] / weight_sum[bucket]))
    return returns, vols


def _bucket_expected_metrics(
    cma: CapitalMarketAssumption,
    sub_allocations: list[dict] | None = None,
) -> tuple[dict[str, int], dict[str, int]]:
    """Backward-compatible name used by regression tests and older callers."""
    return _weighted_bucket_metrics(cma, sub_allocations)


def _expected_metrics(
    targets: dict[str, int],
    cma: CapitalMarketAssumption,
    sub_allocations: list[dict] | None = None,
) -> dict[str, int]:
    returns, vols = _weighted_bucket_metrics(cma, sub_allocations)
    return {
        "expected_return_bps": int(round(sum(targets[key] * returns[key] for key in BUCKET_FIELDS) / 10000)),
        "expected_volatility_bps": int(round(sum(targets[key] * vols[key] for key in BUCKET_FIELDS) / 10000)),
    }


def _simulation_horizon_years(simulation_prefs: dict | None, goals: list[Goal]) -> int:
    raw = (simulation_prefs or {}).get("horizonYears")
    try:
        requested = int(str(raw).strip()) if raw not in (None, "", False) else DEFAULT_SIMULATION_HORIZON_YEARS
    except (TypeError, ValueError):
        requested = DEFAULT_SIMULATION_HORIZON_YEARS
    goal_horizon = max((int(goal.horizon_years or 0) for goal in goals), default=0)
    return max(7, requested, goal_horizon)


def _simulation_stress_multiplier(simulation_prefs: dict | None) -> float:
    raw = (simulation_prefs or {}).get("stressMultiplier")
    try:
        value = float(str(raw).strip()) if raw not in (None, "", False) else DEFAULT_SIMULATION_STRESS_MULTIPLIER
    except (TypeError, ValueError):
        value = DEFAULT_SIMULATION_STRESS_MULTIPLIER
    return max(0.25, min(2.5, value))


def _simulation_transaction_cost_bps(simulation_prefs: dict | None) -> int:
    raw = (simulation_prefs or {}).get("transactionCostBps")
    try:
        value = int(str(raw).strip()) if raw not in (None, "", False) else DEFAULT_REBALANCE_TRANSACTION_COST_BPS
    except (TypeError, ValueError):
        value = DEFAULT_REBALANCE_TRANSACTION_COST_BPS
    return max(0, min(200, value))


def _simulation_rebalance_mode(simulation_prefs: dict | None) -> str:
    raw = str((simulation_prefs or {}).get("rebalanceMode") or "bands").strip().lower()
    aliases = {
        "band": "bands",
        "bands": "bands",
        "calendar": "calendar",
        "jaehrlich": "calendar",
        "none": "none",
        "off": "none",
        "aus": "none",
    }
    mode = aliases.get(raw, "bands")
    return mode if mode in ALLOWED_SIMULATION_REBALANCE_MODES else "bands"


def _target_bucket_values(total_rappen: int, weights_bps: dict[str, int]) -> dict[str, int]:
    values = {key: 0 for key in BUCKET_FIELDS}
    remaining = int(total_rappen or 0)
    for idx, key in enumerate(BUCKET_FIELDS):
        if idx == len(BUCKET_FIELDS) - 1:
            values[key] = remaining
            break
        amount = int(round(total_rappen * int(weights_bps.get(key, 0)) / 10000))
        values[key] = amount
        remaining -= amount
    return values


def _weights_from_bucket_values(values: dict[str, int]) -> dict[str, int]:
    total = sum(max(0, int(values.get(key, 0))) for key in BUCKET_FIELDS)
    if total <= 0:
        return {key: 0 for key in BUCKET_FIELDS}
    return {
        key: _bps(max(0, int(values.get(key, 0))), total)
        for key in BUCKET_FIELDS
    }


def _apply_cashflow_to_bucket_values(values: dict[str, int], cashflow_rappen: int) -> int:
    """Applies cashflow to bucket values. Returns deficit remainder if buckets are exhausted.

    Positive cashflow lands in liquidity. Negative cashflow draws from buckets in order
    (liquidity, bonds, equities, alternatives, real_estate). If all buckets are zero and
    negative remainder still exists, returns it as positive int so the caller can
    accumulate it as a separate deficit (Lebensluecke). For non-negative input or fully
    funded outflow, returns 0.
    """
    amount = int(cashflow_rappen or 0)
    if amount >= 0:
        values["liquidity"] = int(values.get("liquidity", 0)) + amount
        return 0
    remaining = abs(amount)
    for key in ("liquidity", "bonds", "equities", "alternatives", "real_estate"):
        available = max(0, int(values.get(key, 0)))
        if available <= 0:
            continue
        used = min(available, remaining)
        values[key] = available - used
        remaining -= used
        if remaining <= 0:
            break
    return remaining


def _rebalance_bucket_values_to_targets(values: dict[str, int], targets: dict[str, int]) -> tuple[dict[str, int], int]:
    total = sum(max(0, int(values.get(key, 0))) for key in BUCKET_FIELDS)
    target_values = _target_bucket_values(total, targets)
    turnover = int(round(sum(abs(int(target_values[key]) - int(values.get(key, 0))) for key in BUCKET_FIELDS) / 2))
    return target_values, turnover


def _inflation_path_series(cma: CapitalMarketAssumption, years: int, start_year: int) -> list[int]:
    try:
        raw_path = json.loads(cma.inflation_path_json or "{}")
    except json.JSONDecodeError:
        raw_path = {}
    normalized: dict[int, int] = {}
    for raw_year, raw_value in (raw_path or {}).items():
        try:
            year = int(str(raw_year).strip())
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        normalized[year] = value
    fallback = normalized[max(normalized)] if normalized else 70
    series: list[int] = []
    for offset in range(max(0, years)):
        year = start_year + offset
        if year in normalized:
            fallback = normalized[year]
        series.append(int(fallback))
    return series


def _real_series_from_nominal(series_rappen: list[int], inflation_series_bps: list[int]) -> list[int]:
    if not series_rappen:
        return []
    real = [int(series_rappen[0])]
    inflation_factor = 1.0
    for idx in range(1, len(series_rappen)):
        inflation_bps = inflation_series_bps[idx - 1] if idx - 1 < len(inflation_series_bps) else (
            inflation_series_bps[-1] if inflation_series_bps else 0
        )
        inflation_factor *= 1 + (inflation_bps / 10000)
        real.append(int(round(series_rappen[idx] / max(inflation_factor, 0.0001))))
    return real


def _simulate_bucket_path(
    *,
    start_values: dict[str, int],
    returns_by_asset: dict[str, int],
    cashflow_series_rappen: list[int],
    targets: dict[str, int],
    minimums: dict[str, int],
    maximums: dict[str, int],
    start_year: int,
    rebalance_mode: str,
    transaction_cost_bps: int = 0,
    initial_deficit_rappen: int = 0,
) -> tuple[list[int], list[dict]]:
    values = {key: max(0, int(start_values.get(key, 0))) for key in BUCKET_FIELDS}
    # Z8-W2: Lebensluecke wird als positiver Schuldenstand mitgefuehrt.
    # initial_deficit_rappen erlaubt es, externe Verbindlichkeiten (Hypothek etc.)
    # in die Total-Pfad-Simulation einzubringen; sie wachsen nicht mit, weil
    # Schuldzinsen ohnehin als recurring expense in cashflow_series_rappen liegen.
    accumulated_deficit = max(0, int(initial_deficit_rappen or 0))
    totals = [sum(values.values()) - accumulated_deficit]
    events: list[dict] = []
    for offset, contribution in enumerate(cashflow_series_rappen):
        year = start_year + offset
        for key in BUCKET_FIELDS:
            values[key] = int(round(max(0, values[key]) * (1 + (int(returns_by_asset.get(key, 0)) / 10000))))
        deficit_rest = _apply_cashflow_to_bucket_values(values, int(contribution or 0))
        accumulated_deficit += deficit_rest
        weights = _weights_from_bucket_values(values)
        breached = [
            BUCKET_LABELS[key]
            for key in BUCKET_FIELDS
            if weights[key] < int(minimums.get(key, 0)) or weights[key] > int(maximums.get(key, 0))
        ]
        should_rebalance = False
        note = ""
        if rebalance_mode == "calendar":
            should_rebalance = sum(values.values()) > 0
            note = "Kalender-Rebalancing auf strategische Sollgewichte."
        elif rebalance_mode == "bands" and breached:
            should_rebalance = True
            note = "Bandbreiten-Rebalancing wegen Drift ausserhalb der Zielbaender."
        if should_rebalance:
            values, turnover = _rebalance_bucket_values_to_targets(values, targets)
            if transaction_cost_bps > 0 and turnover > 0:
                cost_rappen = int(round(turnover * transaction_cost_bps / 10000))
                total_after = max(1, sum(values.values()))
                for key in BUCKET_FIELDS:
                    values[key] = max(0, int(round(
                        values[key] * (1 - cost_rappen / total_after)
                    )))
            if turnover > 0 or breached:
                events.append(
                    {
                        "year": year,
                        "mode": rebalance_mode,
                        "breached_buckets": breached,
                        "turnover_rappen": turnover,
                        "notes": note,
                    }
                )
        # Z8-W2: Asset-Buckets bleiben physisch >= 0; akkumulierter Defizit
        # (Lebensluecke) macht totals negativ wenn Vermoegen aufgezehrt ist.
        totals.append(sum(max(0, int(values.get(key, 0))) for key in BUCKET_FIELDS) - accumulated_deficit)
    return totals, events


def _build_asset_class_assumptions(
    *,
    current_amounts: dict[str, int],
    advisory_wealth_rappen: int,
    targets: dict[str, int],
    asset_risky_weights: dict[str, int],
    cma: CapitalMarketAssumption,
    sub_allocations: list[dict] | None = None,
) -> list[dict]:
    # C3: Bucket-Metriken aus tatsaechlicher Sub-Allocation-Gewichtung,
    # nicht aus ungewichtetem Sub-Annahmen-Mittel.
    returns, vols = _weighted_bucket_metrics(cma, sub_allocations)
    assumptions = []
    for key in BUCKET_FIELDS:
        assumptions.append(
            {
                "asset_class": BUCKET_LABELS[key],
                "current_weight_bps": _bps(int(current_amounts.get(key, 0)), advisory_wealth_rappen),
                "target_weight_bps": int(targets.get(key, 0)),
                "risky_fraction_bps": int(asset_risky_weights.get(key, 0)),
                "expected_return_bps": int(returns.get(key, 0)),
                "expected_volatility_bps": int(vols.get(key, 0)),
                "liquidity_profile": ASSET_LIQUIDITY_PROFILES.get(key, "n/a"),
                "market_data_role": "Live-Preise fuer Drift / Bewertung, manuelle CMA fuer Strategie",
            }
        )
    return assumptions


def _build_sub_asset_class_assumption_reference(
    sub_allocations: list[dict],
    cma: CapitalMarketAssumption,
) -> list[dict]:
    returns, vols = _asset_class_expected_metrics(cma)
    assumption_map = _sub_asset_class_assumption_map(cma)
    seen: set[tuple[str, str]] = set()
    items: list[dict] = []
    for item in sub_allocations:
        asset_class = str(item.get("asset_class") or "")
        sub_asset_class = str(item.get("sub_asset_class") or "")
        if not asset_class or not sub_asset_class:
            continue
        marker = (asset_class, sub_asset_class)
        if marker in seen:
            continue
        seen.add(marker)
        expected_return_bps, expected_volatility_bps = _sub_asset_class_metrics(
            sub_asset_class,
            asset_class,
            cma,
            returns,
            vols,
        )
        items.append(
            {
                "asset_class": asset_class,
                "sub_asset_class": sub_asset_class,
                "expected_return_bps": expected_return_bps,
                "expected_volatility_bps": expected_volatility_bps,
                "source": "CMA Sub-Asset-Class" if sub_asset_class in assumption_map else "Asset-Class fallback",
            }
        )
    return items


def _build_simulation_payload(
    *,
    advisory_summary: PortfolioSummary,
    cashflow_projection_series_rappen: list[int],
    cma: CapitalMarketAssumption,
    targets: dict[str, int],
    minimums: dict[str, int],
    maximums: dict[str, int],
    start_year: int,
    simulation_prefs: dict | None,
    sub_allocations: list[dict] | None = None,
    target_total_rappen: int | None = None,
    total_summary: PortfolioSummary | None = None,
    total_liabilities_rappen: int = 0,
) -> dict:
    horizon_years = max(1, len(cashflow_projection_series_rappen))
    stress_multiplier = _simulation_stress_multiplier(simulation_prefs)
    rebalance_mode = _simulation_rebalance_mode(simulation_prefs)
    transaction_cost_bps = _simulation_transaction_cost_bps(simulation_prefs)
    # C3: gewichtete Bucket-Metriken aus Sub-Allocation, falls vorhanden.
    returns, vols = _weighted_bucket_metrics(cma, sub_allocations)
    target_start_total = int(target_total_rappen if target_total_rappen is not None else advisory_summary.total_rappen)
    target_values = _target_bucket_values(target_start_total, targets)
    # Z8-W2 Phase 2: Total-Pfad nutzt Asset-Buckets aus Gesamtvermoegen,
    # Liabilities werden als initial_deficit eingebracht. Schuldzinsen
    # liegen ohnehin als recurring expense im cashflow_series.
    total_liabilities_rappen = max(0, int(total_liabilities_rappen or 0))
    downside_returns = {
        key: int(max(-9500, round(returns[key] - vols[key] * stress_multiplier)))
        for key in BUCKET_FIELDS
    }
    upside_returns = {
        key: int(round(returns[key] + vols[key] * stress_multiplier))
        for key in BUCKET_FIELDS
    }
    current_series, _ = _simulate_bucket_path(
        start_values=advisory_summary.amounts_rappen,
        returns_by_asset=returns,
        cashflow_series_rappen=cashflow_projection_series_rappen,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        start_year=start_year,
        rebalance_mode="none",
        transaction_cost_bps=0,
    )
    target_series, rebalance_events = _simulate_bucket_path(
        start_values=target_values,
        returns_by_asset=returns,
        cashflow_series_rappen=cashflow_projection_series_rappen,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        start_year=start_year,
        rebalance_mode=rebalance_mode,
        transaction_cost_bps=transaction_cost_bps,
    )
    downside_series, _ = _simulate_bucket_path(
        start_values=target_values,
        returns_by_asset=downside_returns,
        cashflow_series_rappen=cashflow_projection_series_rappen,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        start_year=start_year,
        rebalance_mode=rebalance_mode,
        transaction_cost_bps=transaction_cost_bps,
    )
    upside_series, _ = _simulate_bucket_path(
        start_values=target_values,
        returns_by_asset=upside_returns,
        cashflow_series_rappen=cashflow_projection_series_rappen,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        start_year=start_year,
        rebalance_mode=rebalance_mode,
        transaction_cost_bps=transaction_cost_bps,
    )
    # Z8-W2 Phase 2: Total-Vermoegens-Pfad. IST = Total-Asset-Buckets ohne Rebalancing,
    # SOLL = Total-Buckets so verteilt wie Strategie es vorschreibt. Beide tragen
    # initial_deficit (Liabilities) als Schuldenstand mit, sodass die Series das
    # echte Reinvermoegen zeigt.
    if total_summary is not None:
        total_target_start = max(0, int(total_summary.total_rappen) - total_liabilities_rappen)
        total_target_values = _target_bucket_values(total_target_start, targets)
        total_current_series, _ = _simulate_bucket_path(
            start_values=total_summary.amounts_rappen,
            returns_by_asset=returns,
            cashflow_series_rappen=cashflow_projection_series_rappen,
            targets=targets,
            minimums=minimums,
            maximums=maximums,
            start_year=start_year,
            rebalance_mode="none",
            transaction_cost_bps=0,
            initial_deficit_rappen=total_liabilities_rappen,
        )
        total_target_series, _ = _simulate_bucket_path(
            start_values=total_target_values,
            returns_by_asset=returns,
            cashflow_series_rappen=cashflow_projection_series_rappen,
            targets=targets,
            minimums=minimums,
            maximums=maximums,
            start_year=start_year,
            rebalance_mode=rebalance_mode,
            transaction_cost_bps=transaction_cost_bps,
            initial_deficit_rappen=0,  # Liabilities werden bereits in target_start abgezogen
        )
    else:
        total_current_series = []
        total_target_series = []
    inflation_series_bps = _inflation_path_series(cma, horizon_years, start_year)
    return {
        "horizon_years": horizon_years,
        "start_year": start_year,
        "year_labels": [start_year + offset for offset in range(horizon_years + 1)],
        "rebalance_mode": rebalance_mode,
        "stress_multiplier": stress_multiplier,
        "current_mix_series_rappen": current_series,
        "target_mix_series_rappen": target_series,
        "total_mix_current_series_rappen": total_current_series,
        "total_mix_target_series_rappen": total_target_series,
        "downside_series_rappen": downside_series,
        "upside_series_rappen": upside_series,
        "real_target_series_rappen": _real_series_from_nominal(target_series, inflation_series_bps),
        "inflation_series_bps": inflation_series_bps,
        "rebalancing_events": rebalance_events,
    }


_GOAL_HARDNESS_MULTIPLIER_BPS = {
    "hart": 20000,
    "primaer": 10000,
    "opportunistisch": 4000,
}


def _goal_hardness_key(goal: Goal | None) -> str:
    raw = _norm_text(getattr(goal, "hardness", None) or "Primaer").strip().lower()
    if raw == "hart":
        return "hart"
    if raw == "opportunistisch":
        return "opportunistisch"
    return "primaer"


def _goal_weight(goal: Goal) -> int:
    base = int(goal.weight_bps) if goal.weight_bps else GOAL_WEIGHT_BY_RANK.get(int(goal.rank or 5), 312)
    multiplier = _GOAL_HARDNESS_MULTIPLIER_BPS.get(_goal_hardness_key(goal), 10000)
    return int(round(base * multiplier / 10000))


# B5: Hardness-abhaengige Gewichtung von Wahrscheinlichkeit vs. Magnitude.
# Hart: success_rate dominiert (Mindestleistung muss eingehalten werden).
# Opportunistisch: funded_ratio dominiert (Magnitude wichtiger als Schwellwert).
# Primaer: balanciert.
# Quellen: Brunel (2003), Das/Markowitz/Scheid/Statman (2010), Vanguard 2015.
_GOAL_SCORE_ALPHA = {
    "hart": 0.8,
    "primaer": 0.5,
    "opportunistisch": 0.2,
}


def _build_mandate_score(goal_analysis: list[dict]) -> dict:
    """B6: Mandate-Aggregation aus goal_analysis.

    Liefert ZWEI Aggregate (PK-konsistent, ASIP §3.2):
    - weighted_score: gewichteter Mittelwert aller goal_scores nach
      weight_bps * hardness_multiplier_bps. Strategie-Sicht. None wenn
      keine Goals.
    - weakest_hard_score: min(score) ueber Goals mit hardness=Hart.
      Compliance-Sicht. None wenn keine harten Goals.

    Methodisch: Mandate haben oft heterogene Goals (PK-Pflicht vs.
    ueberobligatorisch vs. Reisefonds). Pure Aggregation maskiert harte
    Verfehlungen; daher beide Sichten parallel.
    """
    if not goal_analysis:
        return {
            "weighted_score": None,
            "weakest_hard_score": None,
            "weakest_hard_goal_id": None,
            "method": "weighted_avg + weakest_hard_min",
        }

    # weighted: weight_bps * hardness multiplier
    weighted_sum = 0.0
    weight_sum = 0.0
    for item in goal_analysis:
        score = float(item.get("achievement_score") or 0)
        base_weight = max(0, int(item.get("weight_bps") or 0))
        hardness_raw = str(item.get("hardness") or "Primaer").strip().lower()
        if hardness_raw == "hart":
            hardness_key = "hart"
        elif hardness_raw == "opportunistisch":
            hardness_key = "opportunistisch"
        else:
            hardness_key = "primaer"
        multiplier = _GOAL_HARDNESS_MULTIPLIER_BPS.get(hardness_key, 10000)
        effective_weight = base_weight * multiplier
        weighted_sum += score * effective_weight
        weight_sum += effective_weight
    weighted_score = int(round(weighted_sum / weight_sum)) if weight_sum > 0 else None

    # weakest hard
    hard_goals = [
        item for item in goal_analysis
        if str(item.get("hardness") or "").strip().lower() == "hart"
    ]
    if hard_goals:
        worst = min(hard_goals, key=lambda x: int(x.get("achievement_score") or 0))
        weakest_hard_score = int(worst.get("achievement_score") or 0)
        weakest_hard_goal_id = worst.get("goal_id")
    else:
        weakest_hard_score = None
        weakest_hard_goal_id = None

    return {
        "weighted_score": weighted_score,
        "weakest_hard_score": weakest_hard_score,
        "weakest_hard_goal_id": weakest_hard_goal_id,
        "method": "weighted_avg + weakest_hard_min",
    }


def _compute_goal_score(
    *,
    success_rate_pct: int,
    funded_ratio_pct: int,
    hardness_key: str,
) -> int:
    """B5 zentrale Score-Formel:
    score = alpha * success_rate_pct + (1 - alpha) * funded_ratio_pct
    mit alpha aus _GOAL_SCORE_ALPHA[hardness_key], default primaer.

    Beide Inputs werden auf [0, 100] geclampt; Ergebnis liegt damit in [0, 100].
    """
    alpha = _GOAL_SCORE_ALPHA.get(hardness_key, _GOAL_SCORE_ALPHA["primaer"])
    sr = max(0, min(100, int(success_rate_pct)))
    fr = max(0, min(100, int(funded_ratio_pct)))
    raw = alpha * sr + (1.0 - alpha) * fr
    return int(round(max(0.0, min(100.0, raw))))


def _goal_inflation_series_bps(
    cma: CapitalMarketAssumption,
    horizon_years: int,
    start_year: int,
    planning_inflation_bps: int | None = None,
) -> list[int]:
    years = max(1, int(horizon_years or 1))
    if planning_inflation_bps is not None:
        return [int(planning_inflation_bps)] * years
    return _inflation_path_series(cma, years, start_year)


def _inflate_real_goal_target_rappen(target_rappen: int, years: int, inflation_series_bps: list[int] | None) -> int:
    target = max(1, int(target_rappen or 0))
    factor = 1.0
    series = list(inflation_series_bps or [150])
    last_bps = int(series[-1] if series else 150)
    for idx in range(max(0, int(years or 0))):
        infl_bps = int(series[idx]) if idx < len(series) else last_bps
        factor *= 1 + (infl_bps / 10000)
    return int(round(target * factor))


def _goal_target_wealth_rappen(goal: Goal, years: int, inflation_series_bps: list[int] | None) -> int:
    nominal_target = max(1, int(goal.target_wealth_rappen or 0))
    if str(getattr(goal, "value_mode", "nominal") or "nominal").strip().lower() != "real":
        return nominal_target
    return _inflate_real_goal_target_rappen(nominal_target, years, inflation_series_bps)


def _growth_goals_for_equity_tilt(goals: list[Goal]) -> list[Goal]:
    has_hard_protection_goal = any(
        _goal_hardness_key(goal) == "hart"
        and _norm_text(goal.goal_type) in (
            "Kapitalerhalt",
            "Vermoegensziel",
            "Pensionsausgabe",
            "Wiederkehrende_Ausgabe",
        )
        for goal in goals
    )
    eligible = []
    for goal in goals:
        goal_type = _norm_text(goal.goal_type)
        hardness_key = _goal_hardness_key(goal)
        if hardness_key == "opportunistisch":
            continue
        if goal_type in ("Vermoegensziel", "Maximierung"):
            eligible.append(goal)
            continue
        if goal_type == "Renditeziel" and not has_hard_protection_goal:
            eligible.append(goal)
    return eligible


def _parse_iso_date(value) -> date | None:
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _goal_projection_years(goal: Goal) -> int:
    target_date = _parse_iso_date(goal.target_date)
    start_date = _parse_iso_date(goal.start_date)
    anchor = target_date or (
        start_date if _norm_text(goal.goal_type) in ("Wiederkehrende_Ausgabe", "Pensionsausgabe") else None
    )
    if anchor:
        delta_days = (anchor - date.today()).days
        if delta_days <= 0:
            return 1
        return max(1, int((delta_days + 364) // 365))
    return max(1, int(goal.horizon_years or 1))


def _annualize_goal_amount(goal: Goal) -> int:
    amount = int(goal.target_amount_rappen or 0)
    frequency = normalize_frequency(goal.frequency)
    if frequency == "monatlich":
        return amount * 12
    if frequency == "quartalsweise":
        return amount * 4
    if frequency in ("halbjaehrlich", "halbjährlich"):
        return amount * 2
    return amount


def _goal_timing_label(goal: Goal, years: int) -> str:
    goal_type = _norm_text(goal.goal_type)
    if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe"):
        parts = []
        if goal.frequency:
            parts.append(normalize_frequency(goal.frequency))
        if goal.start_date:
            parts.append(f"ab {goal.start_date}")
        if goal.is_ongoing:
            parts.append("laufend")
        elif goal.target_date:
            parts.append(f"bis {goal.target_date}")
        elif years:
            parts.append(f"Horizont {years} J.")
        return " | ".join(parts) if parts else f"Horizont {years} J."
    if goal_type == "Einmalige_Ausgabe" and goal.start_date:
        return f"am {goal.start_date}"
    if goal.target_date:
        return f"bis {goal.target_date}"
    return f"Horizont {years} J."


def _goal_reserve_for_goal(goal: Goal) -> int:
    """Zielbezogene Liquiditaetsreserve fuer Spending-Goals.

    C5: Vor dem Fix wurde im Goal-Scoring der globale reserve_needed_rappen
    (Maximum aller reserve_candidates) als 'available' verwendet, wodurch
    ein grosses Ziel kleinere automatisch auf 'On Track' hob. Hier
    spiegeln wir die ohnehin schon in _apply_goal_and_reserve_tilts
    angewandte zielbezogene Logik (years<=3: 100%, 4-7: 50%, >7: 0%)
    zentral wider, damit das Scoring konsistent zur Reserve-Empfehlung
    bleibt.
    """
    goal_type = _norm_text(goal.goal_type)
    if goal_type not in ("Einmalige_Ausgabe", "Wiederkehrende_Ausgabe", "Pensionsausgabe"):
        return 0
    target_amount = (
        _annualize_goal_amount(goal)
        if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe")
        else int(goal.target_amount_rappen or 0)
    )
    years = _goal_projection_years(goal)
    if years <= 3:
        return target_amount
    if years <= 7:
        return int(round(target_amount * 0.5))
    return 0


def _build_goal_analysis(
    goals: list[Goal],
    advisory_wealth_rappen: int,
    total_wealth_rappen: int,
    cashflow_projection_series_rappen: list[int],
    inflation_series_bps: list[int],
    expected_return_bps: int,
    reserve_needed_rappen: int,
    policy: OptimizerPolicy,
) -> list[dict]:
    analysis = []
    for goal in sorted(goals, key=lambda g: (int(g.rank or 999), g.label or "")):
        years = _goal_projection_years(goal)
        # B4: Goals werden IMMER gegen advisory_wealth bewertet, weil die
        # Strategie nur das Beratungsvermoegen optimiert. External Assets
        # (Eigenheim etc.) werden nicht hochgerechnet, weil ihre Wachstums-
        # annahme fragil und nicht strategie-relevant ist (PK-konsistent,
        # ASIP §3.2). Bisheriger Skalierungs-Pfad mit allow_other_assets_for_goals
        # erzeugte Drift zwischen deterministischer und MC-Bewertung.
        investable_base = advisory_wealth_rappen
        projection_years = max(1, years or 1)
        contribution_series = list(cashflow_projection_series_rappen[:projection_years])
        if len(contribution_series) < projection_years:
            contribution_series.extend([0] * (projection_years - len(contribution_series)))
        projected_rappen = future_value_with_cashflow_series(
            investable_base,
            contribution_series,
            expected_return_bps,
        )
        target_rappen = 0
        goal_type = _norm_text(goal.goal_type)
        hardness_key = _goal_hardness_key(goal)
        # B5: Score = alpha * success_rate_pct + (1-alpha) * funded_ratio_pct
        # Deterministisch ist success_rate binaer (entweder erreicht oder nicht).
        # MC liefert echte success_rate via _monte_carlo_goal_summary.
        if goal_type == "Renditeziel":
            target_rappen = projected_rappen
            target_return = max(1, int(goal.target_return_bps or 1))
            funded_ratio_pct = int(round(min(200, max(-100, expected_return_bps / target_return * 100))))
            success_rate_pct = 100 if expected_return_bps >= int(goal.target_return_bps or 0) else 0
            score = _compute_goal_score(
                success_rate_pct=success_rate_pct,
                funded_ratio_pct=funded_ratio_pct,
                hardness_key=hardness_key,
            )
        elif goal_type in ("Kapitalerhalt", "Vermoegensziel"):
            target_rappen = _goal_target_wealth_rappen(goal, years, inflation_series_bps)
            denominator = max(1, target_rappen)
            funded_ratio_pct = int(round(min(200, max(-100, projected_rappen / denominator * 100))))
            success_rate_pct = 100 if projected_rappen >= target_rappen else 0
            score = _compute_goal_score(
                success_rate_pct=success_rate_pct,
                funded_ratio_pct=funded_ratio_pct,
                hardness_key=hardness_key,
            )
        else:
            target_rappen = _annualize_goal_amount(goal) if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe") else int(goal.target_amount_rappen or 0)
            # C5: zielbezogene Reserve statt globaler reserve_needed_rappen,
            # damit ein grosses Ziel kleinere Ziele nicht unbeabsichtigt
            # auf 'On Track' hebt.
            available = _goal_reserve_for_goal(goal) if years <= 3 else projected_rappen
            denominator = max(1, target_rappen)
            funded_ratio_pct = int(round(min(200, max(-100, available / denominator * 100))))
            success_rate_pct = 100 if available >= target_rappen else 0
            score = _compute_goal_score(
                success_rate_pct=success_rate_pct,
                funded_ratio_pct=funded_ratio_pct,
                hardness_key=hardness_key,
            )
        status = "On Track" if score >= 70 else ("Pruefen" if score >= 45 else "Gefaehrdet")
        analysis.append(
            {
                "goal_id": goal.id,
                "label": goal.label,
                "goal_type": goal.goal_type,
                "goal_scope": goal.goal_scope,
                "value_mode": getattr(goal, "value_mode", "nominal") or "nominal",
                "hardness": getattr(goal, "hardness", None),
                "rank": int(goal.rank or 0),
                "weight_bps": _goal_weight(goal),
                "target_amount_rappen": target_rappen,
                "target_wealth_rappen": int(goal.target_wealth_rappen) if goal.target_wealth_rappen is not None else None,
                "target_return_bps": int(goal.target_return_bps) if goal.target_return_bps is not None else None,
                "projected_value_rappen": projected_rappen,
                "achievement_score": score,
                "status": status,
                "start_date": goal.start_date,
                "target_date": goal.target_date,
                "horizon_years": years,
                "is_ongoing": int(goal.is_ongoing or 0),
                "frequency": goal.frequency,
                "timing_label": _goal_timing_label(goal, years),
            }
        )
    return analysis


def _monte_carlo_simulations(simulation_prefs: dict | None) -> int:
    raw = (simulation_prefs or {}).get("monteCarloRuns")
    try:
        value = int(str(raw).strip()) if raw not in (None, "", False) else DEFAULT_MONTE_CARLO_SIMULATIONS
    except (TypeError, ValueError):
        value = DEFAULT_MONTE_CARLO_SIMULATIONS
    return max(250, min(2500, value))


def _monte_carlo_seed(*parts) -> int:
    payload = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _percentile(values: list[int | float], quantile: float) -> int:
    if not values:
        return 0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return int(round(ordered[0]))
    q = max(0.0, min(1.0, float(quantile)))
    index = q * (len(ordered) - 1)
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return int(round(ordered[lower]))
    weight = index - lower
    value = ordered[lower] * (1 - weight) + ordered[upper] * weight
    return int(round(value))


def _annualized_return_bps(start_value: int, end_value: int, years: int) -> int:
    if years <= 0 or start_value <= 0 or end_value <= 0:
        return 0
    return int(round((math.pow(end_value / start_value, 1 / years) - 1) * 10000))


def _return_bps(start_value: int, end_value: int) -> int:
    if start_value <= 0 or end_value <= 0:
        return -10000 if end_value <= 0 else 0
    return int(round((end_value / start_value - 1) * 10000))


def _loss_bps(start_value: int, end_value: int) -> int:
    return max(0, -_return_bps(start_value, end_value))


def _conditional_percentile_average(values: list[int | float], quantile: float, *, upper_tail: bool = False) -> int:
    if not values:
        return 0
    threshold = _percentile(values, quantile)
    if upper_tail:
        tail = [float(value) for value in values if float(value) >= float(threshold)]
    else:
        tail = [float(value) for value in values if float(value) <= float(threshold)]
    if not tail:
        return int(threshold)
    return int(round(sum(tail) / len(tail)))


def _max_drawdown_bps(path_values: list[int]) -> int:
    peak = 0
    max_drawdown = 0
    for raw_value in path_values:
        value = max(0, int(raw_value or 0))
        peak = max(peak, value)
        if peak <= 0:
            continue
        drawdown = int(round((peak - value) / peak * 10000))
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return max_drawdown


def _year_index_for_goal(goal: Goal, start_year: int, horizon_years: int) -> int:
    years = _goal_projection_years(goal)
    return max(1, min(int(years or 1), int(horizon_years)))


def _full_goal_duration_years(goal: Goal) -> int:
    start_date = _parse_iso_date(goal.start_date)
    target_date = _parse_iso_date(goal.target_date)
    if start_date and target_date and target_date >= start_date:
        return max(1, target_date.year - start_date.year + 1)
    return 1


def _goal_duration_years(goal: Goal, start_year: int, horizon_years: int) -> int:
    start_date = _parse_iso_date(goal.start_date)
    target_date = _parse_iso_date(goal.target_date)
    if start_date and target_date and target_date >= start_date:
        sim_end_year = int(start_year) + int(horizon_years)
        overlap_start = max(start_date.year, int(start_year))
        overlap_end = min(target_date.year, sim_end_year)
        return max(0, overlap_end - overlap_start + 1)
    if int(goal.is_ongoing or 0):
        anchor = max(start_year, start_date.year if start_date else start_year)
        return max(1, horizon_years - (anchor - start_year))
    return 1


def _monte_carlo_goal_summary(
    goal: Goal,
    *,
    path_values_by_year: list[list[int]],
    annualized_return_samples_bps: list[int],
    inflation_series_bps: list[int],
    advisory_wealth_rappen: int,
    total_wealth_rappen: int,
    start_year: int,
    horizon_years: int,
    policy: OptimizerPolicy,
) -> dict:
    index = _year_index_for_goal(goal, start_year, horizon_years)
    # B4: MC-Pfade sind advisory-only. Keine Skalierung mehr (frueher
    # _goal_base_scale x total/advisory) - das war methodisch falsch,
    # weil External Assets nicht wie Aktien wachsen. Goal wird gegen
    # advisory_path bewertet, konsistent zu _build_goal_analysis.
    scaled_values = list(path_values_by_year[index])
    p10 = _percentile(scaled_values, 0.10)
    p50 = _percentile(scaled_values, 0.50)
    p90 = _percentile(scaled_values, 0.90)
    goal_type = _norm_text(goal.goal_type)
    hardness_key = _goal_hardness_key(goal)
    evaluation_note = None

    # B5: Score = alpha * success_rate_pct + (1-alpha) * funded_ratio_pct
    # Pro Goal-Typ: success_rate_pct (binaer/MC) und funded_ratio_pct als
    # einheitliche Inputs in _compute_goal_score.
    if goal_type == "Renditeziel":
        target = int(goal.target_return_bps or 0)
        success_rate_pct = int(round(sum(1 for sample in annualized_return_samples_bps if sample >= target) / max(1, len(annualized_return_samples_bps)) * 100))
        funded_ratio_p50 = float(p50 / max(1, advisory_wealth_rappen))
        median_return = _percentile(annualized_return_samples_bps, 0.50) if annualized_return_samples_bps else 0
        funded_ratio_pct = 100 if target <= 0 else max(0, min(200, int(round(median_return / target * 100))))
        score = _compute_goal_score(
            success_rate_pct=success_rate_pct,
            funded_ratio_pct=funded_ratio_pct,
            hardness_key=hardness_key,
        )
    elif goal_type in ("Einmalige_Ausgabe", "Wiederkehrende_Ausgabe", "Pensionsausgabe"):
        target = _annualize_goal_amount(goal)
        if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe"):
            full_duration = _full_goal_duration_years(goal)
            duration = _goal_duration_years(goal, start_year, horizon_years)
            if duration <= 0:
                target = max(1, int(target))
                success_rate_pct = 0
                funded_ratio_p50 = 0.0
                score = 0
                evaluation_note = f"Ziel liegt ausserhalb des aktuellen Simulationshorizonts (Horizont: {horizon_years} Jahre)."
            else:
                target *= duration
                target = max(1, int(target))
                success_rate_pct = int(round(sum(1 for value in scaled_values if value >= target) / max(1, len(scaled_values)) * 100))
                funded_ratio_p50 = round(p50 / target, 4)
                funded_ratio_pct = max(0, min(200, int(round(funded_ratio_p50 * 100))))
                score = _compute_goal_score(
                    success_rate_pct=success_rate_pct,
                    funded_ratio_pct=funded_ratio_pct,
                    hardness_key=hardness_key,
                )
                if duration < full_duration:
                    evaluation_note = f"Bewertet fuer {duration} von {full_duration} Jahren (Simulationshorizont: {horizon_years} Jahre)."
        else:
            target = max(1, int(target))
            success_rate_pct = int(round(sum(1 for value in scaled_values if value >= target) / max(1, len(scaled_values)) * 100))
            funded_ratio_p50 = round(p50 / target, 4)
            funded_ratio_pct = max(0, min(200, int(round(funded_ratio_p50 * 100))))
            score = _compute_goal_score(
                success_rate_pct=success_rate_pct,
                funded_ratio_pct=funded_ratio_pct,
                hardness_key=hardness_key,
            )
    elif goal_type in ("Kapitalerhalt", "Vermoegensziel"):
        target = _goal_target_wealth_rappen(goal, index, inflation_series_bps)
        success_rate_pct = int(round(sum(1 for value in scaled_values if value >= target) / max(1, len(scaled_values)) * 100))
        funded_ratio_p50 = round(p50 / target, 4)
        funded_ratio_pct = max(0, min(200, int(round(funded_ratio_p50 * 100))))
        score = _compute_goal_score(
            success_rate_pct=success_rate_pct,
            funded_ratio_pct=funded_ratio_pct,
            hardness_key=hardness_key,
        )
    elif goal_type == "Maximierung":
        target = max(1, advisory_wealth_rappen)
        success_rate_pct = 100
        funded_ratio_p50 = round(p50 / target, 4)
        score = 100
    else:
        target = max(1, advisory_wealth_rappen)
        success_rate_pct = 100
        funded_ratio_p50 = round(p50 / target, 4)
        score = max(0, min(100, int(round((_percentile(annualized_return_samples_bps, 0.50) / 100))))) if annualized_return_samples_bps else 50

    return {
        "goal_id": goal.id,
        "label": goal.label,
        "years": index,
        "success_rate_pct": success_rate_pct,
        "funded_ratio_p50": funded_ratio_p50,
        "projected_value_p10_rappen": p10,
        "projected_value_p50_rappen": p50,
        "projected_value_p90_rappen": p90,
        "score": max(0, min(100, score)),
        "evaluation_note": evaluation_note,
    }


def _run_allocation_monte_carlo(
    *,
    advisory_summary: PortfolioSummary,
    cashflow_projection_series_rappen: list[int],
    goal_inflation_series_bps: list[int],
    targets: dict[str, int],
    minimums: dict[str, int],
    maximums: dict[str, int],
    cma: CapitalMarketAssumption,
    goals: list[Goal],
    advisory_wealth_rappen: int,
    total_wealth_rappen: int,
    policy: OptimizerPolicy,
    mandate_id: str,
    simulation_prefs: dict | None,
    start_year: int,
    sub_allocations: list[dict] | None = None,
    target_total_rappen: int | None = None,
    total_summary: "PortfolioSummary | None" = None,
    total_liabilities_rappen: int = 0,
) -> dict:
    horizon_years = max(1, len(cashflow_projection_series_rappen))
    simulations = _monte_carlo_simulations(simulation_prefs)
    stress_multiplier = _simulation_stress_multiplier(simulation_prefs)
    rebalance_mode = _simulation_rebalance_mode(simulation_prefs)
    # C3: gewichtete Bucket-Metriken aus Sub-Allocation.
    returns, vols = _weighted_bucket_metrics(cma, sub_allocations)
    chol = _build_cholesky_from_cma(cma)
    n_assets = len(BUCKET_FIELDS)
    transaction_cost_bps = _simulation_transaction_cost_bps(simulation_prefs)
    target_start_total = int(target_total_rappen if target_total_rappen is not None else advisory_summary.total_rappen)
    target_start_values = _target_bucket_values(target_start_total, targets)
    # C3: Sub-Allocation in den MC-Seed aufnehmen, damit Aenderungen der
    # tatsaechlichen Sub-Verteilung (z.B. EM-Tilt aktiviert) zu einer
    # neuen, deterministisch reproduzierbaren Pfadschar fuehren.
    sub_alloc_signature = json.dumps(
        sorted(
            [
                (
                    str(item.get("asset_class") or ""),
                    str(item.get("sub_asset_class") or ""),
                    int(item.get("target_weight_bps") or 0),
                )
                for item in (sub_allocations or [])
            ]
        ),
        sort_keys=True,
    )
    seed = _monte_carlo_seed(
        mandate_id,
        cma.id,
        horizon_years,
        simulations,
        stress_multiplier,
        rebalance_mode,
        json.dumps(targets, sort_keys=True),
        sub_alloc_signature,
        transaction_cost_bps,
        cma.correlation_matrix_json or "",
    )
    rng = random.Random(seed)

    current_by_year: list[list[int]] = [[] for _ in range(horizon_years + 1)]
    target_by_year: list[list[int]] = [[] for _ in range(horizon_years + 1)]
    # F23: Total-Vermoegen-Pfade in MC parallel zu advisory. Liabilities werden
    # als initial deficit auf den IST-Total getragen; SOLL-Total bekommt sie
    # bereits beim Start abgezogen. Wenn total_summary fehlt, bleiben die Listen
    # leer und der Caller bekommt [] zurueck.
    total_current_by_year: list[list[int]] = [[] for _ in range(horizon_years + 1)]
    total_target_by_year: list[list[int]] = [[] for _ in range(horizon_years + 1)]
    total_liabilities_rappen = max(0, int(total_liabilities_rappen or 0))
    if total_summary is not None:
        total_target_start = max(0, int(total_summary.total_rappen) - total_liabilities_rappen)
        total_target_start_values = _target_bucket_values(total_target_start, targets)
    else:
        total_target_start = 0
        total_target_start_values = {key: 0 for key in BUCKET_FIELDS}
    current_annualized_returns: list[int] = []
    target_annualized_returns: list[int] = []
    target_year_one_returns: list[int] = []
    target_year_one_losses: list[int] = []
    target_max_drawdowns: list[int] = []

    for _ in range(simulations):
        current_values = {key: max(0, int(advisory_summary.amounts_rappen.get(key, 0))) for key in BUCKET_FIELDS}
        target_values = {key: max(0, int(target_start_values.get(key, 0))) for key in BUCKET_FIELDS}
        # W2.5: Lebensluecke pro Simulation als positiver Schuldenstand mitgefuehrt,
        # parallel zur deterministischen _simulate_bucket_path-Logik. Wenn Cashflow
        # mehr Vermoegen abzieht als vorhanden, akkumuliert der Rest hier und macht
        # den Pfad-Total negativ (Vermoegen aufgezehrt).
        current_deficit = 0
        target_deficit = 0
        # F23: parallele Total-Pfade. IST traegt Liabilities ab Start, SOLL hat
        # sie schon im total_target_start abgezogen.
        if total_summary is not None:
            total_current_values = {key: max(0, int(total_summary.amounts_rappen.get(key, 0))) for key in BUCKET_FIELDS}
            total_target_values = {key: max(0, int(total_target_start_values.get(key, 0))) for key in BUCKET_FIELDS}
            total_current_deficit = total_liabilities_rappen
            total_target_deficit = 0
            total_current_by_year[0].append(sum(total_current_values.values()) - total_current_deficit)
            total_target_by_year[0].append(sum(total_target_values.values()) - total_target_deficit)
        else:
            total_current_values = None
            total_target_values = None
            total_current_deficit = 0
            total_target_deficit = 0
        current_by_year[0].append(sum(current_values.values()) - current_deficit)
        target_by_year[0].append(sum(target_values.values()) - target_deficit)

        current_start = max(1, sum(current_values.values()))
        target_start = max(1, sum(target_values.values()))

        for year_index, contribution in enumerate(cashflow_projection_series_rappen, start=1):
            # Draw n_assets independent standard normals, then correlate via Cholesky: Z = L * W
            indep = [rng.gauss(0.0, 1.0) for _ in range(n_assets)]
            corr = [sum(chol[i][j] * indep[j] for j in range(i + 1)) for i in range(n_assets)]
            for idx, key in enumerate(BUCKET_FIELDS):
                mu = returns[key] / 10000
                sigma = vols[key] / 10000 * stress_multiplier
                mu_ln = mu - 0.5 * sigma * sigma  # Itô correction: E[exp(X)] = exp(mu) preserves arithmetic mean
                growth_factor = math.exp(mu_ln + sigma * corr[idx])
                current_values[key] = int(round(max(0, current_values[key]) * growth_factor))
                target_values[key] = int(round(max(0, target_values[key]) * growth_factor))
                if total_current_values is not None:
                    total_current_values[key] = int(round(max(0, total_current_values[key]) * growth_factor))
                    total_target_values[key] = int(round(max(0, total_target_values[key]) * growth_factor))

            current_deficit += _apply_cashflow_to_bucket_values(current_values, int(contribution or 0))
            target_deficit += _apply_cashflow_to_bucket_values(target_values, int(contribution or 0))
            if total_current_values is not None:
                total_current_deficit += _apply_cashflow_to_bucket_values(total_current_values, int(contribution or 0))
                total_target_deficit += _apply_cashflow_to_bucket_values(total_target_values, int(contribution or 0))

            if rebalance_mode in ("bands", "calendar"):
                target_weights = _weights_from_bucket_values(target_values)
                breached = [
                    key for key in BUCKET_FIELDS
                    if target_weights[key] < int(minimums.get(key, 0)) or target_weights[key] > int(maximums.get(key, 0))
                ]
                if rebalance_mode == "calendar" or breached:
                    target_values, rebal_turnover = _rebalance_bucket_values_to_targets(target_values, targets)
                    if transaction_cost_bps > 0 and rebal_turnover > 0:
                        # Deduct transaction cost from portfolio proportionally across all buckets
                        cost_rappen = int(round(rebal_turnover * transaction_cost_bps / 10000))
                        total_after = max(1, sum(target_values.values()))
                        for key in BUCKET_FIELDS:
                            target_values[key] = max(0, int(round(
                                target_values[key] * (1 - cost_rappen / total_after)
                            )))
                if total_target_values is not None:
                    total_target_weights = _weights_from_bucket_values(total_target_values)
                    total_breached = [
                        key for key in BUCKET_FIELDS
                        if total_target_weights[key] < int(minimums.get(key, 0)) or total_target_weights[key] > int(maximums.get(key, 0))
                    ]
                    if rebalance_mode == "calendar" or total_breached:
                        total_target_values, total_rebal_turnover = _rebalance_bucket_values_to_targets(total_target_values, targets)
                        if transaction_cost_bps > 0 and total_rebal_turnover > 0:
                            cost_rappen = int(round(total_rebal_turnover * transaction_cost_bps / 10000))
                            total_after = max(1, sum(total_target_values.values()))
                            for key in BUCKET_FIELDS:
                                total_target_values[key] = max(0, int(round(
                                    total_target_values[key] * (1 - cost_rappen / total_after)
                                )))

            current_by_year[year_index].append(sum(current_values.values()) - current_deficit)
            target_by_year[year_index].append(sum(target_values.values()) - target_deficit)
            if total_current_values is not None:
                total_current_by_year[year_index].append(sum(total_current_values.values()) - total_current_deficit)
                total_target_by_year[year_index].append(sum(total_target_values.values()) - total_target_deficit)

        current_annualized_returns.append(_annualized_return_bps(current_start, current_by_year[-1][-1], horizon_years))
        target_annualized_returns.append(_annualized_return_bps(target_start, target_by_year[-1][-1], horizon_years))
        if len(target_by_year) > 1 and target_by_year[1]:
            year_one_return = _return_bps(target_start, target_by_year[1][-1])
            target_year_one_returns.append(year_one_return)
            target_year_one_losses.append(_loss_bps(target_start, target_by_year[1][-1]))
        target_path = [values[-1] for values in target_by_year if values]
        target_max_drawdowns.append(_max_drawdown_bps(target_path))

    goal_summaries = [
        _monte_carlo_goal_summary(
            goal,
            path_values_by_year=target_by_year,
            annualized_return_samples_bps=target_annualized_returns,
            inflation_series_bps=goal_inflation_series_bps,
            advisory_wealth_rappen=advisory_wealth_rappen,
            total_wealth_rappen=total_wealth_rappen,
            start_year=start_year,
            horizon_years=horizon_years,
            policy=policy,
        )
        for goal in goals
    ]

    target_terminal_values = target_by_year[-1]
    downside_probability_pct = int(round(sum(1 for value in target_terminal_values if value < target_start_total) / max(1, len(target_terminal_values)) * 100))

    has_total_paths = total_summary is not None and total_current_by_year[0]
    return {
        "simulations": simulations,
        "seed": seed,
        "horizon_years": horizon_years,
        "start_year": start_year,
        "year_labels": [start_year + offset for offset in range(horizon_years + 1)],
        "current_p10_series_rappen": [_percentile(values, 0.10) for values in current_by_year],
        "current_p50_series_rappen": [_percentile(values, 0.50) for values in current_by_year],
        "current_p90_series_rappen": [_percentile(values, 0.90) for values in current_by_year],
        "target_p10_series_rappen": [_percentile(values, 0.10) for values in target_by_year],
        "target_p50_series_rappen": [_percentile(values, 0.50) for values in target_by_year],
        "target_p90_series_rappen": [_percentile(values, 0.90) for values in target_by_year],
        # F23: Total-Vermoegen-Pfade (Gesamtvermoegen, Liabilities mit Lebensluecke).
        # Leer wenn der Aufrufer kein total_summary uebergeben hat.
        "total_current_p10_series_rappen": (
            [_percentile(values, 0.10) for values in total_current_by_year] if has_total_paths else []
        ),
        "total_current_p50_series_rappen": (
            [_percentile(values, 0.50) for values in total_current_by_year] if has_total_paths else []
        ),
        "total_current_p90_series_rappen": (
            [_percentile(values, 0.90) for values in total_current_by_year] if has_total_paths else []
        ),
        "total_target_p10_series_rappen": (
            [_percentile(values, 0.10) for values in total_target_by_year] if has_total_paths else []
        ),
        "total_target_p50_series_rappen": (
            [_percentile(values, 0.50) for values in total_target_by_year] if has_total_paths else []
        ),
        "total_target_p90_series_rappen": (
            [_percentile(values, 0.90) for values in total_target_by_year] if has_total_paths else []
        ),
        "current_annualized_return_p50_bps": _percentile(current_annualized_returns, 0.50),
        "target_annualized_return_p50_bps": _percentile(target_annualized_returns, 0.50),
        "target_var_95_1y_bps": _percentile(target_year_one_losses, 0.95),
        "target_cvar_95_1y_bps": _conditional_percentile_average(target_year_one_losses, 0.95, upper_tail=True),
        "target_loss_probability_1y_pct": int(round(sum(1 for value in target_year_one_returns if value < 0) / max(1, len(target_year_one_returns)) * 100)),
        "target_max_drawdown_p50_bps": _percentile(target_max_drawdowns, 0.50),
        "target_max_drawdown_p95_bps": _percentile(target_max_drawdowns, 0.95),
        "target_downside_probability_pct": downside_probability_pct,
        "goal_summaries": goal_summaries,
    }


def _merge_goal_analysis_with_monte_carlo(goal_analysis: list[dict], monte_carlo: dict | None) -> list[dict]:
    if not monte_carlo:
        return goal_analysis
    summaries = {
        item["goal_id"]: item
        for item in (monte_carlo.get("goal_summaries") or [])
        if item.get("goal_id")
    }
    merged = []
    for item in goal_analysis:
        summary = summaries.get(item.get("goal_id"))
        if not summary:
            merged.append(item)
            continue
        merged.append(
            {
                **item,
                "achievement_score": int(summary.get("score", item.get("achievement_score") or 0)),
                "status": "On Track" if int(summary.get("score", 0)) >= 70 else ("Pruefen" if int(summary.get("score", 0)) >= 45 else "Gefaehrdet"),
                "path_success_rate_pct": int(summary.get("success_rate_pct") or 0),
                "funded_ratio_p50": float(summary.get("funded_ratio_p50") or 0),
                "projected_value_p10_rappen": int(summary.get("projected_value_p10_rappen") or 0),
                "projected_value_p50_rappen": int(summary.get("projected_value_p50_rappen") or 0),
                "projected_value_p90_rappen": int(summary.get("projected_value_p90_rappen") or 0),
                "projected_value_rappen": int(summary.get("projected_value_p50_rappen") or item.get("projected_value_rappen") or 0),
                "evaluation_note": summary.get("evaluation_note") or item.get("evaluation_note"),
            }
        )
    return merged


def _normalize_splits(
    splits: list[tuple[str, int, str]],
) -> list[tuple[str, int, str]]:
    """Skaliert Sub-Asset-Class-Splits proportional auf Summe 10000.

    C4: Vor dem Fix wurde nach Filterung (z.B. !bondsHighYield, !noEm)
    der Rest dem letzten Eintrag zugeschlagen ('letzter bekommt
    remainder'), was diesen unbeabsichtigt uebergewichtete. Hier
    skalieren wir proportional, der Rundungsrest geht an den
    groessten Eintrag (stabil und reproduzierbar).
    """
    if not splits:
        return []
    total = sum(int(bps) for _, bps, _ in splits)
    if total == 10000 or total <= 0:
        return list(splits)
    scaled: list[tuple[str, int, str]] = []
    accumulated = 0
    for label, bps, rationale in splits:
        new_bps = int(round(int(bps) * 10000 / total))
        scaled.append((label, new_bps, rationale))
        accumulated += new_bps
    delta = 10000 - accumulated
    if delta != 0 and scaled:
        idx_max = max(range(len(scaled)), key=lambda i: scaled[i][1])
        label, bps, rationale = scaled[idx_max]
        scaled[idx_max] = (label, bps + delta, rationale)
    return scaled


def _build_sub_allocations(targets: dict[str, int], preferences: dict) -> list[dict]:
    prefs = _normalize_preferences(preferences)
    asset_prefs = prefs["assetClasses"]
    geo_prefs = prefs["geo"]
    tilts = prefs["tilts"]
    sub_allocations: list[dict] = []

    def _append_split(asset_class: str, bucket_weight: int, splits: list[tuple[str, int, str]]):
        if bucket_weight <= 0 or not splits:
            return
        # C4: Splits auf Summe 10000 normalisieren bevor verteilt wird,
        # damit Filter (HY/EM raus etc.) keine Uebergewichtung des
        # letzten Eintrags erzeugen.
        normalized = _normalize_splits(splits)
        remaining = bucket_weight
        for idx, (label, split_bps, rationale) in enumerate(normalized):
            if idx == len(normalized) - 1:
                weight = remaining
            else:
                weight = int(round(bucket_weight * split_bps / 10000))
                remaining -= weight
            if weight <= 0:
                continue
            sub_allocations.append(
                {
                    "asset_class": asset_class,
                    "sub_asset_class": label,
                    "target_weight_bps": weight,
                    "rationale": rationale,
                }
            )

    equities_geo = asset_prefs.get("equitiesGeo") or "Schweiz Fokus"
    if equities_geo == "Global":
        eq_splits = [("Aktien Global", 6500, "Globaler Kernbaustein"), ("Aktien Schweiz", 1500, "Heimmarkt-Anker"), ("Aktien Europa", 1000, "Europa-Diversifikation"), ("Aktien Schwellenlaender", 1000, "Wachstumsbaustein")]
    elif equities_geo == "Europa":
        eq_splits = [("Aktien Europa", 4000, "Europa-Fokus gemaess Mandat"), ("Aktien Global", 2500, "Globaler Kernbaustein"), ("Aktien Schweiz", 2500, "Heimmarkt-Anker"), ("Aktien Schwellenlaender", 1000, "Wachstumsbaustein")]
    elif equities_geo == "Schwellenlaender":
        eq_splits = [("Aktien Global", 4000, "Globaler Kernbaustein"), ("Aktien Schweiz", 2000, "Heimmarkt-Anker"), ("Aktien Europa", 1500, "Europa-Diversifikation"), ("Aktien Schwellenlaender", 2500, "Mandatierter EM-Fokus")]
    else:
        eq_splits = [("Aktien Schweiz", 4500, "Mandatierter Schweiz-Fokus"), ("Aktien Global", 4000, "Globaler Kernbaustein"), ("Aktien Europa", 1000, "Europa-Diversifikation"), ("Aktien Schwellenlaender", 500, "Wachstumsbaustein")]
    if geo_prefs.get("noEm"):
        remainder = 0
        filtered = []
        for label, split_bps, rationale in eq_splits:
            if label == "Aktien Schwellenlaender":
                remainder += split_bps
            else:
                filtered.append((label, split_bps, rationale))
        if filtered and remainder:
            label, split_bps, rationale = filtered[0]
            filtered[0] = (label, split_bps + remainder, rationale + "; EM ausgeschlossen")
        eq_splits = filtered
    if asset_prefs.get("equitiesSmid"):
        for idx, item in enumerate(eq_splits):
            if item[0] == "Aktien Schweiz":
                eq_splits[idx] = (item[0], max(0, item[1] - 1000), item[2])
                eq_splits.append(("Aktien Schweiz Small/Mid", 1000, "Mandatierter Small-/Mid-Cap-Baustein"))
                break

    overweight_tilts = [key for key, value in tilts.items() if value == "overweight"]
    if overweight_tilts and targets["equities"] > 0:
        theme_map = {
            "defense": "Thema Verteidigung",
            "fossil": "Thema Fossile Energie",
            "tobacco": "Thema Tabak",
            "alcohol": "Thema Alkohol",
            "gaming": "Thema Gluecksspiel",
            "nuclear": "Thema Kernenergie",
        }
        theme_total = min(int(round(targets["equities"] * 0.15)), 1200)
        if theme_total > 0:
            slice_per_theme = max(100, int(round(theme_total / len(overweight_tilts))))
            for idx, item in enumerate(eq_splits):
                if item[0] == "Aktien Global":
                    reduction = min(item[1], slice_per_theme * len(overweight_tilts))
                    eq_splits[idx] = (item[0], item[1] - reduction, item[2] + "; Kernbaustein zugunsten thematischer Tilts reduziert")
                    break
            for tilt in overweight_tilts:
                label = theme_map.get(tilt)
                if label:
                    eq_splits.append((label, slice_per_theme, "Positiver Tilt gemaess Mandatsvorgabe"))

    _append_split("Aktien", targets["equities"], eq_splits)

    bonds_duration = asset_prefs.get("bondsDuration") or "Langfristig"
    if bonds_duration == "Kurzfristig":
        bond_splits = [("Obligationen CHF IG", 7000, "Kurzfristige CHF-Qualitaet"), ("Obligationen Global Hedged", 2500, "Ergaenzende Diversifikation"), ("Obligationen High Yield", 300, "Renditebeimischung"), ("Obligationen Emerging", 200, "Diversifikation")]
    elif bonds_duration == "Gemischt":
        bond_splits = [("Obligationen CHF IG", 6000, "Gemischter CHF-Kern"), ("Obligationen Global Hedged", 3000, "Globale Diversifikation"), ("Obligationen High Yield", 500, "Renditebeimischung"), ("Obligationen Emerging", 500, "Diversifikation")]
    else:
        bond_splits = [("Obligationen CHF IG", 5500, "Langfristiger CHF-Kern"), ("Obligationen Global Hedged", 3500, "Globale Diversifikation"), ("Obligationen High Yield", 500, "Renditebeimischung"), ("Obligationen Emerging", 500, "Diversifikation")]
    if not asset_prefs.get("bondsHighYield"):
        bond_splits = [item for item in bond_splits if item[0] != "Obligationen High Yield"]
    if not asset_prefs.get("bondsEmerging") or geo_prefs.get("noEm"):
        bond_splits = [item for item in bond_splits if item[0] != "Obligationen Emerging"]
    _append_split("Obligationen", targets["bonds"], bond_splits)

    realestate_market = asset_prefs.get("realestateMarket") or "Schweiz"
    if realestate_market == "Ausland":
        re_splits = [("Immobilien Global", 7000, "Auslandsfokus fuer Immobilien"), ("Immobilien Schweiz", 3000, "Heimmarkt-Stabilisator")]
    elif realestate_market == "Gemischt":
        re_splits = [("Immobilien Schweiz", 5000, "Gemischter Immobilienbaustein"), ("Immobilien Global", 5000, "Gemischter Immobilienbaustein")]
    else:
        re_splits = [("Immobilien Schweiz", 8000, "Schweizer Immobilienfokus"), ("Immobilien Global", 2000, "Ergaenzende Diversifikation")]
    _append_split("Immobilien", targets["real_estate"], re_splits)

    alt_splits = []
    if asset_prefs.get("altsGold"):
        alt_splits.append(("Gold / Rohstoffe", 4000, "Stabilisierender Sachwertbaustein"))
    if asset_prefs.get("altsLiquidAlts"):
        alt_splits.append(("Liquid Alternatives", 2000, "Diversifizierende Alternative"))
    if asset_prefs.get("altsHedge"):
        alt_splits.append(("Hedge Funds", 1500, "Alternative Renditequelle"))
    if asset_prefs.get("altsPe"):
        alt_splits.append(("Private Equity", 1500, "Illiquider Wachstumsbaustein"))
    if asset_prefs.get("altsCrypto"):
        alt_splits.append(("Krypto", 1000, "Satellit gemaess Mandatsvorgabe"))
    if not alt_splits:
        alt_splits.append(("Gold / Rohstoffe", 10000, "Standardbaustein fuer Alternative Anlagen"))
    _append_split("Alternative", targets["alternatives"], alt_splits)

    liquidity_label = asset_prefs.get("liquidityInstrument") or "Geldmarktfonds"
    _append_split("Liquiditaet", targets["liquidity"], [(liquidity_label, 10000, "Liquiditaetsreserve gemaess Mandatsvorgabe")])
    return sub_allocations


def _house_matrix_or_default(db: Session, policy: OptimizerPolicy, score_bucket: int) -> HouseMatrix:
    hm = db.query(HouseMatrix).filter(
        HouseMatrix.policy_id == policy.id,
        HouseMatrix.score_from <= score_bucket,
        HouseMatrix.score_to >= score_bucket,
        HouseMatrix.is_active == 1,
    ).first()
    if hm:
        return hm
    raise ValueError(f"Keine House-Matrix fuer Score {score_bucket} vorhanden")


def _validate_house_matrix_defaults(defaults: list[tuple]) -> None:
    covered_scores: list[int] = []
    for entry in defaults:
        (
            score_from,
            score_to,
            profile_name,
            liq_min,
            liq_target,
            liq_max,
            bonds_min,
            bonds_target,
            bonds_max,
            eq_min,
            eq_target,
            eq_max,
            re_min,
            re_target,
            re_max,
            alt_min,
            alt_target,
            alt_max,
            risky,
            equity_floor,
        ) = entry
        if profile_name not in ALLOWED_HOUSE_MATRIX_PROFILES:
            raise ValueError(f"Unzulaessiger House-Matrix-Profilname: {profile_name}.")
        if score_from > score_to:
            raise ValueError(f"Ungueltige Score-Range fuer {profile_name}: {score_from}-{score_to}.")
        covered_scores.extend(range(score_from, score_to + 1))
        target_total = liq_target + bonds_target + eq_target + re_target + alt_target
        if target_total != 10000:
            raise ValueError(f"House-Matrix-Targets fuer {profile_name} ({score_from}-{score_to}) summieren sich auf {target_total} statt 10000 Bps.")
        if not 0 <= risky <= 10000:
            raise ValueError(
                f"House-Matrix-Risky-Fraction fuer {profile_name} ({score_from}-{score_to}) liegt ausserhalb von 0-10000 Bps."
            )
        bounds = (
            ("Liquiditaet", liq_min, liq_target, liq_max),
            ("Obligationen", bonds_min, bonds_target, bonds_max),
            ("Aktien", eq_min, eq_target, eq_max),
            ("Immobilien", re_min, re_target, re_max),
            ("Alternative", alt_min, alt_target, alt_max),
        )
        for label, minimum, target, maximum in bounds:
            if not minimum <= target <= maximum:
                raise ValueError(
                    f"House-Matrix-Band verletzt fuer {profile_name} ({score_from}-{score_to}) in {label}: {minimum}/{target}/{maximum}."
                )
        if equity_floor and not (eq_min <= equity_floor <= eq_max):
            raise ValueError(
                f"House-Matrix-Aktienminimum fuer {profile_name} ({score_from}-{score_to}) ist ausserhalb des Bandes: {equity_floor}."
            )
    if sorted(covered_scores) != list(range(1, 11)):
        raise ValueError("House-Matrix-Defaults muessen jeden Score von 1 bis 10 genau einmal abdecken.")


def _normalize_house_matrix_defaults(defaults: list[tuple]) -> list[tuple]:
    normalized: list[tuple] = []
    for entry in defaults:
        values = list(entry)
        target_indexes = {
            "liquidity": 4,
            "bonds": 7,
            "equities": 10,
            "real_estate": 13,
            "alternatives": 16,
        }
        max_indexes = {
            "liquidity": 5,
            "bonds": 8,
            "equities": 11,
            "real_estate": 14,
            "alternatives": 17,
        }
        total = sum(int(values[index]) for index in target_indexes.values())
        delta = 10000 - total
        if delta != 0:
            # Fachtabellen koennen gerundete Prozentsaetze enthalten; die Runtime braucht dennoch exakt 100%.
            for bucket in ("liquidity", "bonds", "alternatives", "real_estate", "equities"):
                target_idx = target_indexes[bucket]
                max_idx = max_indexes[bucket]
                room = int(values[max_idx]) - int(values[target_idx])
                if delta > 0 and room <= 0:
                    continue
                if delta < 0 and int(values[target_idx]) <= 0:
                    continue
                step = delta
                if delta > 0:
                    step = min(delta, room)
                else:
                    step = max(delta, -int(values[target_idx]))
                if step == 0:
                    continue
                values[target_idx] = int(values[target_idx]) + int(step)
                delta -= int(step)
                if delta == 0:
                    break
        if delta != 0:
            raise ValueError(
                f"House-Matrix-Defaults fuer {values[2]} ({values[0]}-{values[1]}) koennen nicht auf 10000 Bps normalisiert werden."
            )
        normalized.append(tuple(values))
    return normalized


def _seed_house_matrix_rows(db: Session, policy_id: str, defaults: list[tuple], now: str) -> None:
    for (
        score_from,
        score_to,
        profile_name,
        liq_min,
        liq_target,
        liq_max,
        bonds_min,
        bonds_target,
        bonds_max,
        eq_min,
        eq_target,
        eq_max,
        re_min,
        re_target,
        re_max,
        alt_min,
        alt_target,
        alt_max,
        risky,
        equity_floor,
    ) in defaults:
        db.add(
            HouseMatrix(
                id=new_uuid(),
                policy_id=policy_id,
                score_from=score_from,
                score_to=score_to,
                profile_name=profile_name,
                liq_min_bps=liq_min,
                liq_target_bps=liq_target,
                liq_max_bps=liq_max,
                bonds_min_bps=bonds_min,
                bonds_target_bps=bonds_target,
                bonds_max_bps=bonds_max,
                equity_min_bps=eq_min,
                equity_target_bps=eq_target,
                equity_max_bps=eq_max,
                real_estate_min_bps=re_min,
                real_estate_target_bps=re_target,
                real_estate_max_bps=re_max,
                alt_min_bps=alt_min,
                alt_target_bps=alt_target,
                alt_max_bps=alt_max,
                equity_minimum_bps=equity_floor,
                max_risky_fraction_bps=risky,
                is_active=1,
                created_at=now,
                updated_at=now,
            )
        )


def _seed_building_blocks(db: Session, policy_id: str, building_blocks: list[tuple], now: str) -> None:
    for asset_class, sub_asset_class, risky_fraction in building_blocks:
        db.add(
            BuildingBlock(
                id=new_uuid(),
                policy_id=policy_id,
                asset_class=asset_class,
                sub_asset_class=sub_asset_class,
                universe="Standard",
                advisory=1,
                risky_fraction_bps=risky_fraction,
                contribution_standard_bps=risky_fraction,
                contribution_alternative_bps=risky_fraction,
                is_active=1,
                created_at=now,
                updated_at=now,
            )
        )


def _validate_default_products(defaults: list[tuple]) -> None:
    for name, provider, product_type, asset_class, sub_asset_class, currency, ter_bps, sfdr_class, esg_rating in defaults:
        if product_type not in ALLOWED_PRODUCT_TYPES:
            raise ValueError(f"Unzulaessiger Produkt-Typ fuer {name}: {product_type}.")
        if asset_class not in ALLOWED_PRODUCT_ASSET_CLASSES:
            raise ValueError(f"Unzulaessige Asset-Klasse fuer {name}: {asset_class}.")
        if currency and len(str(currency)) != 3:
            raise ValueError(f"Unzulaessige Waehrung fuer {name}: {currency}.")
        if sfdr_class and sfdr_class not in ("6", "8", "9"):
            raise ValueError(f"Unzulaessige SFDR-Klasse fuer {name}: {sfdr_class}.")
        if ter_bps is not None and int(ter_bps) < 0:
            raise ValueError(f"Negativer TER fuer {name}: {ter_bps}.")


def ensure_runtime_reference_data(db: Session, user_id: str) -> tuple[OptimizerPolicy, CapitalMarketAssumption]:
    now = _now()
    today = _today()
    defaults = _normalize_house_matrix_defaults([
        (1, 2, "Kapitalschutz", 0, 300, 800, 6500, 7500, 8500, 500, 1200, 2000, 0, 500, 1000, 0, 500, 500, 2000, 0),
        (3, 4, "Defensiv", 0, 200, 500, 5000, 6000, 7000, 1500, 2500, 3000, 500, 1000, 1500, 0, 300, 800, 4000, 0),
        (5, 6, "Ausgewogen", 0, 200, 300, 2500, 3500, 4500, 4000, 4800, 5500, 500, 1000, 1500, 300, 500, 800, 6000, 0),
        (7, 8, "Wachstumsorientiert", 0, 150, 200, 1000, 1600, 2500, 6000, 6800, 7500, 500, 800, 1200, 300, 600, 1000, 8000, 6000),
        (9, 9, "Dynamisch", 0, 100, 200, 500, 800, 1500, 7500, 8000, 8500, 300, 700, 1000, 200, 400, 600, 9000, 7500),
        (10, 10, "Aktien", 0, 100, 200, 0, 200, 500, 8500, 9000, 9500, 200, 500, 800, 0, 200, 500, 10000, 8500),
    ])
    building_blocks = [
        ("Aktien", "Aktien Schweiz", 7000),
        ("Aktien", "Aktien Schweiz Small/Mid", 8000),
        ("Aktien", "Aktien Global", 8000),
        ("Aktien", "Aktien Europa", 8000),
        ("Aktien", "Aktien Schwellenlaender", 10000),
        ("Aktien", "Thema Verteidigung", 9000),
        ("Aktien", "Thema Fossile Energie", 9000),
        ("Aktien", "Thema Tabak", 9000),
        ("Aktien", "Thema Alkohol", 9000),
        ("Aktien", "Thema Gluecksspiel", 9000),
        ("Aktien", "Thema Kernenergie", 9000),
        ("Obligationen", "Obligationen CHF IG", 2000),
        ("Obligationen", "Obligationen Global Hedged", 2500),
        ("Obligationen", "Obligationen High Yield", 5000),
        ("Obligationen", "Obligationen Emerging", 4000),
        ("Immobilien", "Immobilien Schweiz", 5000),
        ("Immobilien", "Immobilien Global", 7000),
        ("Alternative", "Gold / Rohstoffe", 8000),
        ("Alternative", "Liquid Alternatives", 4000),
        ("Alternative", "Hedge Funds", 6000),
        ("Alternative", "Private Equity", 10000),
        ("Alternative", "Krypto", 10000),
        ("Liquiditaet", "Geldmarktfonds", 0),
        ("Liquiditaet", "Kontoguthaben", 0),
        ("Liquiditaet", "Festgeld", 0),
    ]
    _validate_house_matrix_defaults(defaults)
    policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
    if not policy:
        policy = OptimizerPolicy(
            id=new_uuid(),
            policy_name=DEFAULT_POLICY_NAME,
            version=1,
            is_current=1,
            valid_from=today,
            optimizer_engine="goal_based_v1",
            max_real_estate_bps=2000,
            max_alternatives_bps=1000,
            min_liquidity_bps=0,
            allow_other_assets_for_goals=1,
            fee_model_json=json.dumps({"default_advisory_fee_bps": 75}),
            notes="Automatisch erzeugte V1-Standard-Policy",
            created_by=user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(policy)
        db.flush()
        _validate_house_matrix_defaults(defaults)
        _seed_house_matrix_rows(db, policy.id, defaults, now)
        _seed_building_blocks(db, policy.id, building_blocks, now)

    cma = db.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.is_current == 1,
        CapitalMarketAssumption.deleted_at.is_(None),
    ).first()
    if not cma:
        cma = CapitalMarketAssumption(
            id=new_uuid(),
            assumption_set_name=DEFAULT_CMA_NAME,
            version=1,
            valid_from=today,
            is_current=1,
            bonds_chf_ig_return_bps=220,
            bonds_chf_ig_vol_bps=350,
            bonds_fx_hedged_return_bps=220,
            bonds_fx_hedged_vol_bps=430,
            bonds_hy_return_bps=420,
            bonds_hy_vol_bps=950,
            equity_ch_return_bps=620,
            equity_ch_vol_bps=1450,
            equity_intl_return_bps=700,
            equity_intl_vol_bps=1600,
            equity_em_return_bps=760,
            equity_em_vol_bps=1900,
            real_estate_ch_return_bps=450,
            real_estate_ch_vol_bps=820,
            alternatives_gold_return_bps=300,
            alternatives_gold_vol_bps=1200,
            liquidity_return_bps=80,
            liquidity_vol_bps=15,
            inflation_path_json=json.dumps({
                "2026": 50,
                "2027": 70,
                "2028": 60,
                "2029": 50,
                "2030": 60,
                "2031": 70,
                "2032": 70,
                "2033": 70,
                "2034": 70,
                "2035": 70,
                "2036": 70,
                "2037": 80,
                "2038": 90,
                "2039": 100,
                "2040": 110,
            }),
            sub_asset_class_assumptions_json=json.dumps(_DEFAULT_SUB_ASSET_CLASS_ASSUMPTIONS),
            source="5Eyes Default Runtime",
            notes="Automatisch erzeugte Default-CMA fuer V1-Engine",
            created_by=user_id,
            created_at=now,
            updated_at=now,
        )
        db.add(cma)

    db.flush()
    return policy, cma


def ensure_default_products(db: Session) -> None:
    active_products = db.query(Product).filter(Product.is_active == 1, Product.deleted_at.is_(None)).count()
    if active_products:
        return
    now = _now()
    defaults = [
        ("iShares Core SPI ETF", "BlackRock", "ETF", "Aktien", "Aktien Schweiz", "CHF", 10, "8", "A"),
        ("SPDR Swiss Small Cap ETF", "State Street", "ETF", "Aktien", "Aktien Schweiz Small/Mid", "CHF", 35, "8", "BBB"),
        ("iShares Core MSCI World UCITS ETF", "BlackRock", "ETF", "Aktien", "Aktien Global", "USD", 20, "8", "A"),
        ("Vanguard FTSE Developed Europe ETF", "Vanguard", "ETF", "Aktien", "Aktien Europa", "EUR", 12, "8", "A"),
        ("iShares Core MSCI EM IMI ETF", "BlackRock", "ETF", "Aktien", "Aktien Schwellenlaender", "USD", 18, "8", "BBB"),
        ("VanEck Defense UCITS ETF", "VanEck", "ETF", "Aktien", "Thema Verteidigung", "USD", 55, "6", "BBB"),
        ("Energy Select Sector ETF", "State Street", "ETF", "Aktien", "Thema Fossile Energie", "USD", 45, "6", "BBB"),
        ("Consumer Staples Tobacco Tilt ETF", "WisdomTree", "ETF", "Aktien", "Thema Tabak", "USD", 58, "6", "BBB"),
        ("Global Beverage Leaders ETF", "Amundi", "ETF", "Aktien", "Thema Alkohol", "EUR", 42, "6", "BBB"),
        ("Roundhill Sports Betting ETF", "Roundhill", "ETF", "Aktien", "Thema Gluecksspiel", "USD", 75, "6", "BB"),
        ("VanEck Uranium and Nuclear ETF", "VanEck", "ETF", "Aktien", "Thema Kernenergie", "USD", 61, "6", "BBB"),
        ("Swisscanto Bond CHF", "Swisscanto", "Fonds", "Obligationen", "Obligationen CHF IG", "CHF", 32, "8", "A"),
        ("iShares Global Aggregate Bond CHF Hedged", "BlackRock", "ETF", "Obligationen", "Obligationen Global Hedged", "CHF", 10, "8", "A"),
        ("PIMCO High Yield Fund", "PIMCO", "Fonds", "Obligationen", "Obligationen High Yield", "CHF", 55, "6", "BBB"),
        ("EM Local Bond Opportunities", "JPMorgan", "Fonds", "Obligationen", "Obligationen Emerging", "USD", 62, "6", "BBB"),
        ("Swisscanto Real Estate Fund", "Swisscanto", "Immobilienfonds", "Immobilien", "Immobilien Schweiz", "CHF", 52, "8", "A"),
        ("iShares Developed Markets Property Yield", "BlackRock", "ETF", "Immobilien", "Immobilien Global", "USD", 38, "8", "BBB"),
        ("ZKB Gold ETF", "ZKB", "ETF", "Alternative", "Gold / Rohstoffe", "CHF", 40, "8", "A"),
        ("JPM Global Macro Opportunities", "JPMorgan", "Fonds", "Alternative", "Liquid Alternatives", "CHF", 90, "8", "BBB"),
        ("Man AHL TargetRisk", "Man Group", "Fonds", "Alternative", "Hedge Funds", "USD", 145, "6", "BB"),
        ("Partners Group Listed PE", "Partners Group", "Fonds", "Alternative", "Private Equity", "CHF", 165, "6", "BB"),
        ("21Shares Core Bitcoin ETP", "21Shares", "ETF", "Alternative", "Krypto", "USD", 125, "6", "BB"),
        ("UBS Geldmarktfonds CHF", "UBS", "Fonds", "Liquidität", "Geldmarktfonds", "CHF", 8, "8", "A"),
        ("Kontoguthaben CHF", "Hausbank", "Cash", "Liquidität", "Kontoguthaben", "CHF", 0, None, None),
        ("Festgeld CHF 12M", "Hausbank", "Cash", "Liquidität", "Festgeld", "CHF", 0, None, None),
    ]
    _validate_default_products(defaults)
    validate_default_product_market_coverage([name for name, *_ in defaults])
    created = []
    for name, provider, product_type, asset_class, sub_asset_class, currency, ter_bps, sfdr_class, esg_rating in defaults:
        product = Product(
            id=new_uuid(),
            product_name=name,
            provider=provider,
            product_type=product_type,
            asset_class=asset_class,
            sub_asset_class=sub_asset_class,
            currency=currency,
            ter_bps=ter_bps,
            sfdr_class=sfdr_class,
            esg_rating=esg_rating,
            is_active=1,
            created_at=now,
            updated_at=now,
        )
        db.add(product)
        created.append(product)
    db.flush()
    for product in created:
        risk_band = (1, 10)
        if product.sub_asset_class in ("Aktien Schwellenlaender", "Thema Verteidigung", "Thema Fossile Energie", "Thema Tabak", "Thema Alkohol", "Thema Gluecksspiel", "Thema Kernenergie"):
            risk_band = (6, 10)
        elif product.sub_asset_class in ("Private Equity", "Krypto", "Hedge Funds"):
            risk_band = (7, 10)
        elif product.asset_class == "Aktien":
            risk_band = (4, 10)
        elif product.asset_class == "Immobilien":
            risk_band = (4, 10)
        elif product.sub_asset_class == "Obligationen Emerging":
            risk_band = (5, 10)
        db.add(
            ProductSuitability(
                id=new_uuid(),
                product_id=product.id,
                profile_from=risk_band[0],
                profile_to=risk_band[1],
                advisory_allowed=1,
                discretionary_allowed=1,
                requires_appropriateness=0,
                requires_override=0,
                max_position_bps=2500 if product.asset_class == "Aktien" else 4000,
                created_at=now,
                updated_at=now,
            )
        )
    db.flush()


def _load_allocation_inputs(
    db: Session,
    mandate: Mandate,
    simulation_prefs: dict,
    cma: CapitalMarketAssumption | None = None,
) -> dict:
    all_positions = db.query(WealthPosition).filter(
        WealthPosition.client_id == mandate.client_id,
        WealthPosition.deleted_at.is_(None),
        WealthPosition.is_active == 1,
    ).all()
    advisory_positions = [pos for pos in all_positions if _norm_text(pos.assignment) == "Beratungsvermoegen"]
    asset_positions_total = [pos for pos in all_positions if _norm_text(pos.assignment) != "Verbindlichkeit"]
    liability_positions = [pos for pos in all_positions if _norm_text(pos.assignment) == "Verbindlichkeit"]
    advisory_summary = _summarize_positions(advisory_positions)
    total_summary = _summarize_positions(asset_positions_total)
    advisory_wealth_rappen = advisory_summary.total_rappen
    total_liabilities_rappen = sum(int(pos.current_value_rappen or 0) for pos in liability_positions)
    total_wealth_rappen = max(0, total_summary.total_rappen - total_liabilities_rappen)

    cashflows = db.query(Cashflow).filter(
        Cashflow.client_id == mandate.client_id,
        Cashflow.deleted_at.is_(None),
        Cashflow.is_active == 1,
    ).all()
    goals = db.query(Goal).filter(
        Goal.mandate_id == mandate.id,
        Goal.deleted_at.is_(None),
        Goal.is_active == 1,
    ).order_by(Goal.rank.asc()).all()
    cashflow_totals = totals_for_year(cashflows)
    projection_years = _simulation_horizon_years(simulation_prefs, goals)
    # B1: Cashflow-Series respektieren is_inflation_linked + CMA-Inflations-Pfad.
    # AHV/Lohn/Miete (linked=1) wachsen jaehrlich; Bonus/Erbschaft (linked=0) bleiben nominal.
    cf_inflation_series_bps = (
        _inflation_path_series(cma, projection_years, cashflow_totals["year"])
        if cma is not None else None
    )
    cashflow_projection_series_rappen = net_cashflow_series(
        cashflows,
        projection_years,
        start_year=cashflow_totals["year"],
        inflation_series_bps=cf_inflation_series_bps,
    )
    recurring_cashflow_projection_series_rappen = recurring_net_cashflow_series(
        cashflows,
        projection_years,
        start_year=cashflow_totals["year"],
        inflation_series_bps=cf_inflation_series_bps,
    )
    return {
        "advisory_summary": advisory_summary,
        "total_summary": total_summary,
        "advisory_wealth_rappen": advisory_wealth_rappen,
        "total_wealth_rappen": total_wealth_rappen,
        "total_liabilities_rappen": total_liabilities_rappen,
        # C8: rohe Listen fuer input_snapshot_hash
        "advisory_positions": advisory_positions,
        "asset_positions_total": asset_positions_total,
        "liability_positions": liability_positions,
        "cashflows": cashflows,
        "goals": goals,
        "cashflow_totals": cashflow_totals,
        "annual_inflows": cashflow_totals["income_rappen"],
        "annual_outflows": cashflow_totals["expense_rappen"],
        "recurring_income_rappen": cashflow_totals["recurring_income_rappen"],
        "recurring_expense_rappen": cashflow_totals["recurring_expense_rappen"],
        "capital_inflow_rappen": cashflow_totals["capital_inflow_rappen"],
        "capital_outflow_rappen": cashflow_totals["capital_outflow_rappen"],
        "recurring_net_cashflow_rappen": cashflow_totals["recurring_income_rappen"] - cashflow_totals["recurring_expense_rappen"],
        "capital_net_cashflow_rappen": cashflow_totals["capital_inflow_rappen"] - cashflow_totals["capital_outflow_rappen"],
        "annual_net_cashflow_rappen": cashflow_totals["net_rappen"],
        "cashflow_projection_series_rappen": cashflow_projection_series_rappen,
        "recurring_cashflow_projection_series_rappen": recurring_cashflow_projection_series_rappen,
    }


def _baseline_target_bands(house_matrix: HouseMatrix, policy: OptimizerPolicy) -> tuple[dict, dict, dict]:
    targets = {
        "equities": int(house_matrix.equity_target_bps),
        "bonds": int(house_matrix.bonds_target_bps),
        "real_estate": int(house_matrix.real_estate_target_bps),
        "alternatives": int(house_matrix.alt_target_bps),
        "liquidity": int(house_matrix.liq_target_bps),
    }
    minimums = {
        "equities": max(int(house_matrix.equity_min_bps), int(house_matrix.equity_minimum_bps or 0)),
        "bonds": int(house_matrix.bonds_min_bps),
        "real_estate": int(house_matrix.real_estate_min_bps),
        "alternatives": int(house_matrix.alt_min_bps),
        "liquidity": max(int(house_matrix.liq_min_bps), int(policy.min_liquidity_bps or 0)),
    }
    maximums = {
        "equities": int(house_matrix.equity_max_bps),
        "bonds": int(house_matrix.bonds_max_bps),
        "real_estate": min(int(house_matrix.real_estate_max_bps), int(policy.max_real_estate_bps or 10000)),
        "alternatives": min(int(house_matrix.alt_max_bps), int(policy.max_alternatives_bps or 10000)),
        "liquidity": int(house_matrix.liq_max_bps),
    }
    return targets, minimums, maximums


def _current_planning_inflation_bps(db: Session, mandate: Mandate) -> int | None:
    planning = (
        db.query(PlanningAssumption)
        .filter(
            PlanningAssumption.mandate_id == mandate.id,
            PlanningAssumption.deleted_at.is_(None),
            PlanningAssumption.is_current == 1,
        )
        .order_by(PlanningAssumption.valid_from.desc(), PlanningAssumption.created_at.desc())
        .first()
    )
    if planning and planning.inflation_assumption_bps is not None:
        return int(planning.inflation_assumption_bps)
    return None


def _apply_external_exposure_tilts(
    targets: dict,
    minimums: dict,
    total_summary,
    house_matrix: HouseMatrix,
    manual_target_override: bool,
    reasoning: list[str],
) -> None:
    if manual_target_override:
        return

    external_real_estate_bps = _bps(total_summary.amounts_rappen["real_estate"], max(1, total_summary.total_rappen))
    if external_real_estate_bps > 3000:
        reduction = min(500, int(round((external_real_estate_bps - 3000) * 0.25)))
        targets["real_estate"] = max(minimums["real_estate"], targets["real_estate"] - reduction)
        reasoning.append("Das hohe Immobilien-Exposure im Gesamtvermoegen reduziert den Immobilienanteil im Beratungsvermoegen.")

    external_equity_bps = _bps(total_summary.amounts_rappen["equities"], max(1, total_summary.total_rappen))
    if external_equity_bps > 5000:
        reduction = min(400, int(round((external_equity_bps - 5000) * 0.2)))
        targets["equities"] = max(int(house_matrix.equity_minimum_bps or minimums["equities"]), targets["equities"] - reduction)
        targets["bonds"] = min(int(house_matrix.bonds_max_bps), targets["bonds"] + reduction)
        reasoning.append("Bereits bestehende Aktienexposures im Gesamtvermoegen werden auf die Advisory-Strategie angerechnet.")


def _compute_reserve_for_inputs(
    *,
    goals: list[Goal],
    limits_prefs: dict,
    asset_class_prefs: dict,
    recurring_net_cashflow_rappen: int,
    recurring_cashflow_projection_series_rappen: list[int],
    advisory_wealth_rappen: int,
    saa_liquidity_ceiling_bps: int,
    reasoning: list[str] | None = None,
) -> tuple[int, int]:
    """C7 StrategyContext: Single Source of Truth fuer Reserve-Berechnung.

    Wird sowohl von ``_apply_goal_and_reserve_tilts`` (generate-Pfad)
    als auch von ``build_target_payload_from_allocation`` (rebuild-Pfad)
    aufgerufen, damit Reserve-Logik nicht zwischen Generierung und
    Wiederaufbau driften kann. Liefert (reserve_needed, external_reserve).

    ``reasoning`` ist optional: wenn vorhanden, werden Erklaerungstexte
    fuer den Berater angehaengt; sonst nur Zahlen berechnet.
    """
    reserve_candidates: list[int] = [0]
    manual_reserve = _parse_rappen(limits_prefs.get("minReserve"))
    liquidity_target = _parse_rappen(asset_class_prefs.get("liquidityReserveTarget"))
    if manual_reserve:
        reserve_candidates.append(manual_reserve)
    if liquidity_target:
        reserve_candidates.append(liquidity_target)

    near_term_cashflow_series = [int(value or 0) for value in (recurring_cashflow_projection_series_rappen or [])[:3]]
    near_term_shortfall_rappen = max(0, -sum(near_term_cashflow_series))
    if near_term_shortfall_rappen > 0:
        reserve_candidates.append(near_term_shortfall_rappen)
        if reasoning is not None:
            reasoning.append("Zeitlich datierte Netto-Cashflows erhoehen die erforderliche Liquiditaetsreserve fuer die naechsten Jahre.")
    elif recurring_net_cashflow_rappen < 0:
        reserve_candidates.append(abs(recurring_net_cashflow_rappen) * 3)
        if reasoning is not None:
            reasoning.append("Negativer laufender Netto-Cashflow erhoeht die erforderliche Liquiditaetsreserve.")

    for goal in goals:
        years = _goal_projection_years(goal)
        goal_type = _norm_text(goal.goal_type)
        if goal_type in ("Einmalige_Ausgabe", "Wiederkehrende_Ausgabe", "Pensionsausgabe"):
            target_amount = (
                _annualize_goal_amount(goal)
                if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe")
                else int(goal.target_amount_rappen or 0)
            )
            if years <= 3:
                reserve_candidates.append(target_amount)
                if reasoning is not None:
                    reasoning.append(f"Das Ziel '{goal.label}' wird als kurzfristiger Liquiditaetsbedarf beruecksichtigt.")
            elif years <= 7:
                reserve_candidates.append(int(round(target_amount * 0.5)))

    reserve_needed_rappen = max(reserve_candidates)
    external_reserve_rappen = 0
    if reserve_needed_rappen <= 0 or advisory_wealth_rappen <= 0:
        return reserve_needed_rappen, 0

    uncapped_required_liquidity_bps = _bps(reserve_needed_rappen, advisory_wealth_rappen)
    if uncapped_required_liquidity_bps > saa_liquidity_ceiling_bps:
        saa_reserve_rappen = int(round(saa_liquidity_ceiling_bps * advisory_wealth_rappen / 10000))
        external_reserve_rappen = max(0, reserve_needed_rappen - saa_reserve_rappen)
        if reasoning is not None and external_reserve_rappen > 0:
            chf_external = external_reserve_rappen // 100
            reasoning.append(
                f"Ein Liquiditaetsbedarf von CHF {chf_external:,} wird als externe Reserve ausserhalb "
                f"des Beratungsmandats empfohlen. Die SAA-Liquiditaet bleibt auf {saa_liquidity_ceiling_bps / 100:.1f}%."
            )

    return reserve_needed_rappen, external_reserve_rappen


def _apply_goal_and_reserve_tilts(
    targets: dict,
    minimums: dict,
    maximums: dict,
    goals: list[Goal],
    limits_prefs: dict,
    asset_class_prefs: dict,
    recurring_net_cashflow_rappen: int,
    recurring_cashflow_projection_series_rappen: list[int],
    advisory_wealth_rappen: int,
    reasoning: list[str],
) -> tuple[int, int]:
    # C7: Reserve-Berechnung wird zentral in _compute_reserve_for_inputs gehandelt
    # (StrategyContext-Konsolidierung), Goal-Tilts auf Bandbreiten passieren hier.
    saa_liq_ceiling_bps: int = min(int(maximums["liquidity"]), _SAA_LIQUIDITY_HARD_CAP_BPS)
    reserve_needed_rappen, external_reserve_rappen = _compute_reserve_for_inputs(
        goals=goals,
        limits_prefs=limits_prefs,
        asset_class_prefs=asset_class_prefs,
        recurring_net_cashflow_rappen=recurring_net_cashflow_rappen,
        recurring_cashflow_projection_series_rappen=recurring_cashflow_projection_series_rappen,
        advisory_wealth_rappen=advisory_wealth_rappen,
        saa_liquidity_ceiling_bps=saa_liq_ceiling_bps,
        reasoning=reasoning,
    )
    # Goal-spezifische Bandbreiten-Tilts (Reduktion Aktien fuer kurze Vermoegensziele)
    for goal in goals:
        years = _goal_projection_years(goal)
        goal_type = _norm_text(goal.goal_type)
        if goal_type in ("Kapitalerhalt", "Vermoegensziel") and years <= 5:
            eq_reduction = min(200, max(0, targets["equities"] - minimums["equities"]))
            if eq_reduction > 0:
                targets["equities"] -= eq_reduction
                targets["liquidity"] += eq_reduction // 2
                targets["bonds"] += eq_reduction - eq_reduction // 2
                reasoning.append(f"Das Vermoegensziel '{goal.label}' mit kurzem Horizont reduziert den Aktienanteil leicht.")

    if advisory_wealth_rappen <= 0 or reserve_needed_rappen <= 0:
        return reserve_needed_rappen, 0

    # Auch fuer Tilt-Logik: capped_bps berechnen
    uncapped_required_liquidity_bps = _bps(reserve_needed_rappen, advisory_wealth_rappen)
    saa_required_bps = min(uncapped_required_liquidity_bps, saa_liq_ceiling_bps)

    if saa_required_bps <= targets["liquidity"]:
        return reserve_needed_rappen, external_reserve_rappen

    shift = saa_required_bps - targets["liquidity"]
    remaining = max(0, shift)
    for donor in ("bonds", "equities", "alternatives", "real_estate"):
        if remaining <= 0:
            break
        donor_floor = minimums[donor]
        available = max(0, targets[donor] - donor_floor)
        step = min(remaining, available)
        if step <= 0:
            continue
        targets[donor] -= step
        remaining -= step

    funded = shift - remaining
    if funded > 0:
        targets["liquidity"] += funded
        reasoning.append("Die strategische Liquiditaetsquote wird aus der Zielallokation finanziert.")
    return reserve_needed_rappen, external_reserve_rappen


def _investable_advisory_wealth_rappen(advisory_wealth_rappen: int, external_reserve_rappen: int) -> int:
    return max(0, int(advisory_wealth_rappen or 0) - max(0, int(external_reserve_rappen or 0)))


# ============================================================================
# Optimizer-Integration (Phase 4 Spec 2026-05-05)
# ============================================================================

# OWNER-DECISION OD-3 (bestaetigt): N=2000 Pfade Default. Mit Antithetic = 4000 effektiv.
_OPTIMIZER_N_PATHS_DEFAULT = 2000

# Cap fuer Audit-Speicherung (objective in milli-units). Squared-Shortfall in
# rappen^2 kann fuer pathologische Szenarien >9.2e18 werden -> SQLite INTEGER
# overflow. Wir clampen.
_OPTIMIZER_OBJECTIVE_MILLI_CAP = 9_000_000_000_000_000_000


def _assessment_score_x10(assessment) -> int:
    """0-100 Score-Wert aus Assessment, konsistent zu _risk_score_bucket-Logik."""
    raw = (
        assessment.override_score_x10
        if getattr(assessment, "is_overridden", 0) and assessment.override_score_x10 is not None
        else getattr(assessment, "final_score_x10", None)
    )
    if raw is None:
        raw = 10
    return max(0, min(100, int(raw)))


def _run_stochastic_optimizer_pass(
    *,
    optimizer_mode: str,
    cma,
    goals: list,
    house_matrix,
    assessment,
    advisory_wealth_rappen: int,
    cashflow_projection_series_rappen: list[int],
    inflation_series_bps: list[int],
    targets: dict[str, int],  # mutable: wird in-place ueberschrieben bei converged
    minimums: dict[str, int],
    maximums: dict[str, int],
    reasoning: list[str],
    building_blocks_rows: list | None = None,
):
    """Wenn optimizer_mode='stochastic': Solver aufrufen, targets ersetzen.

    Returns OptimizerResult oder None (wenn Modus != stochastic, oder Solver
    crashed). Bei status='converged' wird targets in-place ueberschrieben mit
    den Solver-Output-bps. Bei diverged/fallback bleibt House-Matrix-Default.
    """
    if optimizer_mode != "stochastic":
        return None

    try:
        from services.optimizer.constraints import (
            bucket_risky_fractions_from_building_blocks,
        )
        from services.optimizer.solver import run_solver
    except ImportError as exc:
        logger.warning("Stochastic optimizer module not importable: %s", exc)
        reasoning.append(
            "Stochastic Optimizer-Modul nicht verfuegbar — House-Matrix-Default bleibt."
        )
        return None

    score_x10 = _assessment_score_x10(assessment)
    horizon = max(10, int(len(cashflow_projection_series_rappen) or 10))
    # Phase 5.1: Risky-Fractions aus BuildingBlock-DB statt fester Defaults.
    # Genauer pro Mandant weil unterschiedliche Policies unterschiedliche
    # Sub-Asset-Klassen-Werte haben koennen (z.B. EM-Aktien ein/aus).
    rf_per_bucket = None
    if building_blocks_rows is not None:
        try:
            rf_per_bucket = bucket_risky_fractions_from_building_blocks(building_blocks_rows)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Risky-fraction extraction failed: %s", exc)
            rf_per_bucket = None

    try:
        result = run_solver(
            cma=cma,
            goals=list(goals),
            house_matrix_row=house_matrix,
            score_x10=score_x10,
            advisory_wealth_rappen=advisory_wealth_rappen,
            cashflow_series_rappen=cashflow_projection_series_rappen,
            horizon_years=horizon,
            n_paths=_OPTIMIZER_N_PATHS_DEFAULT,
            inflation_series_bps=inflation_series_bps,
            risky_fraction_per_bucket=rf_per_bucket,
        )
    except Exception as exc:  # noqa: BLE001 - never crash allocation flow
        logger.warning("Stochastic optimizer crashed: %s", exc, exc_info=True)
        reasoning.append(
            f"Stochastic Optimizer Fehler ({type(exc).__name__}) — "
            "House-Matrix-Default bleibt aktiv."
        )
        return None

    if result.status == "converged":
        # In-place: ersetze House-Matrix-Default-Targets mit Solver-Output.
        # Bands (minimums/maximums) bleiben unveraendert, weil Solver sie
        # respektiert hat.
        for bucket, bps in result.weights_bps.items():
            targets[bucket] = int(bps)
        reasoning.append(
            f"Stochastic Optimizer (Mulvey-light, {result.n_starts_attempted} "
            f"Multi-Starts, {result.iterations} Iter): konvergiert."
        )
        if result.reasoning:
            reasoning.append(result.reasoning[0])
    else:
        reasoning.append(
            f"Stochastic Optimizer Status='{result.status}'. "
            "House-Matrix-Default bleibt aktiv."
        )

    return result


def _optimizer_audit_fields(optimizer_result) -> dict:
    """Extrahiert die Audit-Anchor-Felder fuer TargetAllocation. Returns {} wenn None."""
    if optimizer_result is None:
        return {}
    obj_milli_raw = optimizer_result.objective_value
    if obj_milli_raw == float("inf") or obj_milli_raw != obj_milli_raw:  # NaN check
        obj_milli = None
    else:
        scaled = obj_milli_raw * 1000.0
        if scaled > _OPTIMIZER_OBJECTIVE_MILLI_CAP:
            obj_milli = _OPTIMIZER_OBJECTIVE_MILLI_CAP
        elif scaled < -_OPTIMIZER_OBJECTIVE_MILLI_CAP:
            obj_milli = -_OPTIMIZER_OBJECTIVE_MILLI_CAP
        else:
            obj_milli = int(round(scaled))
    return {
        "optimization_method": optimizer_result.method,
        "optimization_objective_value_milli": obj_milli,
        "optimization_iterations": int(optimizer_result.iterations or 0),
        "optimization_seed": int(optimizer_result.seed or 0),
        "optimization_status": optimizer_result.status,
    }


def _compute_input_snapshot_hash(
    *,
    advisory_positions: list,
    cashflows: list,
    goals: list,
    advisory_wealth_rappen: int,
    total_wealth_rappen: int,
) -> str:
    """C8: Hash der StrategyContext-Inputs (active records only).

    Aenderungen an aktiven WealthPositions, Cashflows oder Goals fuehren
    zu einem neuen Hash. Soft-deleted oder is_active=0 Records sind
    explizit ausgeschlossen, damit sie keine Drift erzeugen.
    """
    def _pos(p) -> tuple:
        return (
            str(getattr(p, "id", "") or ""),
            int(getattr(p, "current_value_rappen", 0) or 0),
            str(getattr(p, "assignment", "") or ""),
            str(getattr(p, "position_type", "") or ""),
            int(getattr(p, "alloc_equities_bps", 0) or 0),
            int(getattr(p, "alloc_bonds_bps", 0) or 0),
            int(getattr(p, "alloc_real_estate_bps", 0) or 0),
            int(getattr(p, "alloc_liquidity_bps", 0) or 0),
            int(getattr(p, "alloc_alternatives_bps", 0) or 0),
            str(getattr(p, "property_usage", "") or ""),
        )

    def _cf(c) -> tuple:
        return (
            str(getattr(c, "id", "") or ""),
            str(getattr(c, "cashflow_type", "") or ""),
            int(getattr(c, "amount_rappen", 0) or 0),
            str(getattr(c, "frequency", "") or ""),
            str(getattr(c, "nature", "") or ""),
            str(getattr(c, "valid_from", "") or ""),
            str(getattr(c, "valid_until", "") or ""),
        )

    def _goal(g) -> tuple:
        return (
            str(getattr(g, "id", "") or ""),
            str(getattr(g, "goal_type", "") or ""),
            int(getattr(g, "target_amount_rappen", 0) or 0),
            int(getattr(g, "target_wealth_rappen", 0) or 0),
            int(getattr(g, "target_return_bps", 0) or 0),
            str(getattr(g, "start_date", "") or ""),
            str(getattr(g, "target_date", "") or ""),
            int(getattr(g, "horizon_years", 0) or 0),
            int(getattr(g, "is_ongoing", 0) or 0),
            str(getattr(g, "frequency", "") or ""),
            str(getattr(g, "hardness", "") or ""),
            int(getattr(g, "rank", 0) or 0),
        )

    payload = json.dumps(
        {
            "advisory_wealth_rappen": int(advisory_wealth_rappen or 0),
            "total_wealth_rappen": int(total_wealth_rappen or 0),
            "positions": sorted(_pos(p) for p in advisory_positions),
            "cashflows": sorted(_cf(c) for c in cashflows),
            "goals": sorted(_goal(g) for g in goals),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _strategy_drift_warnings(
    allocation: TargetAllocation,
    *,
    assessment,
    cma,
    current_input_snapshot_hash: str | None = None,
    current_preferences_json: str | None = None,
    current_advisory_wealth_rappen: int | None = None,
    current_external_reserve_rappen: int | None = None,
) -> list[str]:
    """C8 zentrale Drift-Warnings. Liefert Liste von Hinweistexten fuer
    abweichende oder fehlende Audit-Anker. Aufrufer fuegt sie in reasoning
    oder warnings ein.

    Legacy-Kompatibilitaet: Allocations vor C8 (Anker NULL) erhalten einen
    'incomplete anchors' Hinweis, ueberschreiben aber keine Drift-Logik.
    """
    msgs: list[str] = []
    # Assessment-Drift
    if allocation.based_on_assessment_id and allocation.based_on_assessment_id != assessment.id:
        msgs.append(
            "Hinweis: Diese Soll-Allokation basiert auf einem frueheren Risikoprofil. "
            "Bitte Strategie neu berechnen, bevor sie umgesetzt wird."
        )
    # CMA-Drift
    if allocation.capital_market_assumptions_id and allocation.capital_market_assumptions_id != cma.id:
        msgs.append(
            "Hinweis: Die Kapitalmarktannahmen (CMA) haben sich seit Erstellung dieser "
            "Soll-Allokation geaendert. Erwartete Rendite, Volatilitaet und Pfadsimulation "
            "nutzen die aktuelle CMA - die gespeicherten Bandbreiten basieren auf der "
            "frueheren. Bitte Strategie neu berechnen."
        )
    # Input-Snapshot-Drift (Wealth/Cashflow/Goals)
    stored_hash = getattr(allocation, "input_snapshot_hash", None)
    if stored_hash and current_input_snapshot_hash and stored_hash != current_input_snapshot_hash:
        msgs.append(
            "Hinweis: Vermoegen, Cashflows oder Ziele haben sich seit Erstellung dieser "
            "Soll-Allokation geaendert. Strategie neu berechnen, damit Reserve, Targets "
            "und Pfadsimulation auf den aktuellen Inputs basieren."
        )
    # Preferences-Drift
    stored_prefs = getattr(allocation, "preferences_json", None)
    if stored_prefs and current_preferences_json and stored_prefs != current_preferences_json:
        msgs.append(
            "Hinweis: Mandatspraeferenzen (Bandbreiten, Tilts, Geo, Reserve-Vorgabe) "
            "haben sich seit Erstellung dieser Soll-Allokation geaendert. Bitte neu "
            "berechnen."
        )
    # Reserve-Drift (materielle Aenderung > 1k CHF)
    stored_reserve = getattr(allocation, "external_reserve_at_generation_rappen", None)
    if stored_reserve is not None and current_external_reserve_rappen is not None:
        if abs(int(stored_reserve or 0) - int(current_external_reserve_rappen or 0)) > 100_000:
            msgs.append(
                "Hinweis: Der empfohlene externe Reservebedarf hat sich gegenueber dem "
                "Generierungszeitpunkt um mehr als CHF 1'000 veraendert. Strategie ggf. "
                "neu berechnen."
            )
    # Legacy ohne Anker
    has_legacy = (
        not getattr(allocation, "based_on_assessment_id", None)
        or not getattr(allocation, "capital_market_assumptions_id", None)
        or not stored_hash
    )
    if has_legacy:
        msgs.append(
            "Hinweis: Diese Soll-Allokation stammt aus einer Phase ohne vollstaendige "
            "Audit-Anker. Bitte bei Gelegenheit neu berechnen, damit eine spaetere "
            "Reproduktion dieser Strategie moeglich ist."
        )
    return msgs


# --------------------------------------------------------------------------
# Compat-Wrapper aus rp-ueberarbeitung — Tests in test_portfolio_engine_regressions
# importieren diese Namen direkt. Audit-master/Optimizer haben die zentrale
# Logik in _compute_reserve_for_inputs + _strategy_drift_warnings konsolidiert.
# --------------------------------------------------------------------------
def _compute_reserve_requirements(
    *,
    goals,
    limits_prefs,
    asset_class_prefs,
    recurring_net_cashflow_rappen,
    recurring_cashflow_projection_series_rappen,
    advisory_wealth_rappen,
    saa_liq_ceiling_bps,
    reasoning=None,
):
    return _compute_reserve_for_inputs(
        goals=goals,
        limits_prefs=limits_prefs,
        asset_class_prefs=asset_class_prefs,
        recurring_net_cashflow_rappen=recurring_net_cashflow_rappen,
        recurring_cashflow_projection_series_rappen=recurring_cashflow_projection_series_rappen,
        advisory_wealth_rappen=advisory_wealth_rappen,
        saa_liquidity_ceiling_bps=saa_liq_ceiling_bps,
        reasoning=reasoning,
    )


def _target_allocation_reserve_warnings(allocation, *, external_reserve_rappen):
    stored = getattr(allocation, "external_reserve_at_generation_rappen", None)
    if stored is None:
        return []
    stored_chf = int(stored or 0) // 100
    new_chf = int(external_reserve_rappen or 0) // 100
    if stored_chf == new_chf:
        return []
    fmt = lambda n: f"{n:,}".replace(",", "'")
    return [
        "Externer Reservebedarf hat sich seit Allocation-Erstellung geaendert "
        f"(alt: CHF {fmt(stored_chf)}, neu: CHF {fmt(new_chf)}). "
        "Bitte Strategie neu berechnen."
    ]


def _target_allocation_context_warnings(allocation, assessment, cma):
    msgs: list[str] = []
    a_id = getattr(assessment, "id", None)
    c_id = getattr(cma, "id", None)
    if (
        getattr(allocation, "based_on_assessment_id", None)
        and allocation.based_on_assessment_id != a_id
    ):
        msgs.append(
            "Hinweis: Aktuelle Soll-Allokation basiert auf einem frueheren "
            "Risikoprofil. Bitte Strategie neu berechnen."
        )
    if (
        getattr(allocation, "capital_market_assumptions_id", None)
        and allocation.capital_market_assumptions_id != c_id
    ):
        msgs.append(
            "Hinweis: Kapitalmarktannahmen haben sich seit Allocation-Erstellung "
            "geaendert. Bitte Strategie neu berechnen."
        )
    return msgs


def _build_bucket_response(
    target_allocation: TargetAllocation,
    current_amounts: dict,
    advisory_wealth_rappen: int,
    target_total_rappen: int | None = None,
) -> list[dict]:
    target_base_rappen = int(target_total_rappen if target_total_rappen is not None else advisory_wealth_rappen)
    label_map = {
        "equities": (BUCKET_LABELS["equities"], target_allocation.target_equities_bps, target_allocation.band_equities_min_bps, target_allocation.band_equities_max_bps),
        "bonds": (BUCKET_LABELS["bonds"], target_allocation.target_bonds_bps, target_allocation.band_bonds_min_bps, target_allocation.band_bonds_max_bps),
        "real_estate": (BUCKET_LABELS["real_estate"], target_allocation.target_real_estate_bps, target_allocation.band_real_estate_min_bps, target_allocation.band_real_estate_max_bps),
        "alternatives": (BUCKET_LABELS["alternatives"], target_allocation.target_alternatives_bps, target_allocation.band_alternatives_min_bps, target_allocation.band_alternatives_max_bps),
        "liquidity": (BUCKET_LABELS["liquidity"], target_allocation.target_liquidity_bps, target_allocation.band_liquidity_min_bps, target_allocation.band_liquidity_max_bps),
    }
    bucket_response = []
    for key in BUCKET_FIELDS:
        label, target_bps, min_bps, max_bps = label_map[key]
        current_amount = current_amounts[key]
        current_bps = _bps(current_amount, advisory_wealth_rappen)
        bucket_response.append(
            {
                "asset_class": label,
                "current_weight_bps": current_bps,
                "current_amount_rappen": current_amount,
                "target_weight_bps": int(target_bps),
                "target_amount_rappen": int(round(target_base_rappen * target_bps / 10000)) if target_base_rappen else 0,
                "delta_weight_bps": int(target_bps) - current_bps,
                "band_min_bps": int(min_bps),
                "band_max_bps": int(max_bps),
            }
        )
    return bucket_response


def generate_target_allocation(
    db: Session,
    mandate: Mandate,
    user_id: str,
    preferences: dict | None,
) -> dict:
    now = _now()
    policy, cma = ensure_runtime_reference_data(db, user_id)
    assessment = db.query(RiskAssessment).filter(
        RiskAssessment.mandate_id == mandate.id,
        RiskAssessment.is_current == 1,
        RiskAssessment.deleted_at.is_(None),
    ).first()
    if not assessment:
        raise ValueError("Bitte zuerst ein aktuelles Risikoprofil speichern.")

    prefs = _normalize_preferences(preferences)
    score_bucket = _risk_score_bucket(assessment)
    house_matrix = _house_matrix_or_default(db, policy, score_bucket)
    manual_target_override = _has_manual_target_overrides(prefs["bands"])
    inputs = _load_allocation_inputs(db, mandate, prefs["simulation"], cma=cma)
    advisory_summary = inputs["advisory_summary"]
    total_summary = inputs["total_summary"]
    advisory_wealth_rappen = inputs["advisory_wealth_rappen"]
    total_wealth_rappen = inputs["total_wealth_rappen"]
    total_liabilities_rappen = inputs["total_liabilities_rappen"]
    cashflows = inputs["cashflows"]
    goals = inputs["goals"]
    cashflow_totals = inputs["cashflow_totals"]
    annual_inflows = inputs["annual_inflows"]
    annual_outflows = inputs["annual_outflows"]
    recurring_income_rappen = inputs["recurring_income_rappen"]
    recurring_expense_rappen = inputs["recurring_expense_rappen"]
    capital_inflow_rappen = inputs["capital_inflow_rappen"]
    capital_outflow_rappen = inputs["capital_outflow_rappen"]
    recurring_net_cashflow_rappen = inputs["recurring_net_cashflow_rappen"]
    capital_net_cashflow_rappen = inputs["capital_net_cashflow_rappen"]
    annual_net_cashflow_rappen = inputs["annual_net_cashflow_rappen"]
    cashflow_projection_series_rappen = inputs["cashflow_projection_series_rappen"]
    recurring_cashflow_projection_series_rappen = inputs["recurring_cashflow_projection_series_rappen"]
    targets, minimums, maximums = _baseline_target_bands(house_matrix, policy)
    reasoning = [
        f"Ausgangspunkt ist die House Matrix fuer Score {score_bucket} ({house_matrix.profile_name}).",
        f"Das Risikoprofil deckelt die Risky Fraction auf {house_matrix.max_risky_fraction_bps / 100:.0f}%.",
    ]
    if len(set(cashflow_projection_series_rappen[:min(len(cashflow_projection_series_rappen), 7)])) > 1:
        reasoning.append("Zeitlich datierte Cashflows werden jahresgenau in die Liquiditaets- und Zielprojektion einbezogen.")
    _apply_band_preferences(prefs["bands"], targets, minimums, maximums, reasoning)
    if manual_target_override:
        reasoning.append("Explizit gesetzte Soll-Quoten uebersteuern automatische Exposure-Tilts; harte Risiko- und Liquiditaetsregeln bleiben aktiv.")
    _apply_external_exposure_tilts(targets, minimums, total_summary, house_matrix, manual_target_override, reasoning)
    reserve_needed_rappen, external_reserve_rappen = _apply_goal_and_reserve_tilts(
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        goals=goals,
        limits_prefs=prefs["limits"],
        asset_class_prefs=prefs["assetClasses"],
        recurring_net_cashflow_rappen=recurring_net_cashflow_rappen,
        recurring_cashflow_projection_series_rappen=recurring_cashflow_projection_series_rappen,
        advisory_wealth_rappen=advisory_wealth_rappen,
        reasoning=reasoning,
    )
    investable_advisory_wealth_rappen = _investable_advisory_wealth_rappen(advisory_wealth_rappen, external_reserve_rappen)

    goal_inflation_series_bps = _goal_inflation_series_bps(
        cma,
        len(cashflow_projection_series_rappen),
        cashflow_totals["year"],
        planning_inflation_bps=_current_planning_inflation_bps(db, mandate),
    )

    # Phase 4: Stochastic Optimizer (opt-in via OPTIMIZER_MODE=stochastic).
    # Wenn der Solver konvergiert, ersetzt er die House-Matrix-Default-Targets
    # mit der Mulvey/Ziemba-light optimierten Allocation. Die nachfolgenden
    # Tilts (growth_goals, max_illiquid) werden dann uebersprungen, weil der
    # Solver die Goals direkt optimiert und alle Constraints respektiert.
    # Phase 5.1: Building-Block-Aware Risky-Fractions fuer Solver
    _building_block_rows = db.query(BuildingBlock).filter(
        BuildingBlock.policy_id == policy.id,
        BuildingBlock.is_active == 1,
    ).all() if settings.optimizer_mode == "stochastic" else None

    optimizer_result = _run_stochastic_optimizer_pass(
        optimizer_mode=settings.optimizer_mode,
        cma=cma,
        goals=goals,
        house_matrix=house_matrix,
        assessment=assessment,
        advisory_wealth_rappen=investable_advisory_wealth_rappen,
        cashflow_projection_series_rappen=cashflow_projection_series_rappen,
        inflation_series_bps=goal_inflation_series_bps,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        reasoning=reasoning,
        building_blocks_rows=_building_block_rows,
    )
    optimizer_replaced_targets = (
        optimizer_result is not None and optimizer_result.status == "converged"
    )

    growth_goals = _growth_goals_for_equity_tilt(goals)
    if (
        not optimizer_replaced_targets
        and not manual_target_override
        and recurring_net_cashflow_rappen > 0
        and growth_goals
        and score_bucket >= 7
        and reserve_needed_rappen == 0
        and targets["bonds"] - minimums["bonds"] >= 100
        and targets["liquidity"] - minimums["liquidity"] >= 50
    ):
        targets["equities"] += 150
        targets["bonds"] -= 100
        targets["liquidity"] -= 50
        reasoning.append("Positiver laufender Cashflow und langfristige Wachstumsziele ermoeglichen einen moderaten Equity-Tilt.")

    max_illiquid_bps = _parse_bps_percent(prefs["limits"].get("maxIlliquid"))
    if max_illiquid_bps is not None:
        maximums["alternatives"] = min(maximums["alternatives"], max_illiquid_bps)
        if not optimizer_replaced_targets and targets["alternatives"] > maximums["alternatives"]:
            overflow = targets["alternatives"] - maximums["alternatives"]
            targets["alternatives"] = maximums["alternatives"]
            targets["bonds"] += int(round(overflow * 0.6))
            targets["liquidity"] += overflow - int(round(overflow * 0.6))
            reasoning.append("Die Mandatsgrenze fuer illiquide Anlagen deckelt den Alternatives-Anteil.")

    targets = _rebalance_to_total(targets, minimums, maximums)
    risky_map = _building_block_risky_map(db, policy.id)
    sub_allocations = _build_sub_allocations(targets, prefs)
    sub_allocations, asset_risky_weights, risky_fraction_total_bps = _enrich_sub_allocations_with_risk(sub_allocations, risky_map)
    if risky_fraction_total_bps > int(house_matrix.max_risky_fraction_bps):
        targets, risky_fraction_total_bps = _enforce_risk_budget(
            targets=targets,
            minimums=minimums,
            maximums=maximums,
            asset_risky_weights=asset_risky_weights,
            risk_budget_bps=int(house_matrix.max_risky_fraction_bps),
        )
        targets = _rebalance_to_total(targets, minimums, maximums)
        sub_allocations = _build_sub_allocations(targets, prefs)
        sub_allocations, asset_risky_weights, risky_fraction_total_bps = _enrich_sub_allocations_with_risk(sub_allocations, risky_map)
        reasoning.append("Die Risky Fraction wird subanlagenbasiert gegen das Risikobudget des Profils ausgerichtet.")
    # C3: gewichtete Bucket-Metriken aus Sub-Allocation in alle nachgelagerten
    # Berechnungen weiterreichen.
    metrics = _expected_metrics(targets, cma, sub_allocations)
    goal_analysis = _build_goal_analysis(
        goals=goals,
        advisory_wealth_rappen=investable_advisory_wealth_rappen,
        total_wealth_rappen=total_wealth_rappen,
        cashflow_projection_series_rappen=cashflow_projection_series_rappen,
        inflation_series_bps=goal_inflation_series_bps,
        expected_return_bps=metrics["expected_return_bps"],
        reserve_needed_rappen=reserve_needed_rappen,
        policy=policy,
    )
    asset_class_assumptions = _build_asset_class_assumptions(
        current_amounts=advisory_summary.amounts_rappen,
        advisory_wealth_rappen=advisory_wealth_rappen,
        targets=targets,
        asset_risky_weights=asset_risky_weights,
        cma=cma,
        sub_allocations=sub_allocations,
    )
    sub_asset_class_assumptions_reference = _build_sub_asset_class_assumption_reference(
        sub_allocations,
        cma,
    )
    simulation = _build_simulation_payload(
        advisory_summary=advisory_summary,
        cashflow_projection_series_rappen=cashflow_projection_series_rappen,
        cma=cma,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        start_year=cashflow_totals["year"],
        simulation_prefs=prefs["simulation"],
        sub_allocations=sub_allocations,
        target_total_rappen=investable_advisory_wealth_rappen,
        total_summary=total_summary,
        total_liabilities_rappen=total_liabilities_rappen,
    )
    monte_carlo = _run_allocation_monte_carlo(
        advisory_summary=advisory_summary,
        cashflow_projection_series_rappen=cashflow_projection_series_rappen,
        goal_inflation_series_bps=goal_inflation_series_bps,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        cma=cma,
        goals=goals,
        advisory_wealth_rappen=advisory_wealth_rappen,
        total_wealth_rappen=total_wealth_rappen,
        policy=policy,
        mandate_id=mandate.id,
        simulation_prefs=prefs["simulation"],
        start_year=cashflow_totals["year"],
        sub_allocations=sub_allocations,
        target_total_rappen=investable_advisory_wealth_rappen,
        total_summary=total_summary,
        total_liabilities_rappen=total_liabilities_rappen,
    )
    goal_analysis = _merge_goal_analysis_with_monte_carlo(goal_analysis, monte_carlo)
    reasoning.append("Eine Pfadsimulation mit normalverteilten Jahresrenditen quantifiziert Zielwahrscheinlichkeit, Verlustband und Rebalancing-Risiko.")

    # Race-Hardening: pessimistic Lock, damit parallele
    # generate_target_allocation-Calls keine doppelten is_current=1 Records
    # produzieren (postgres-ready; SQLite serialisiert eh).
    previous_current = db.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate.id,
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None),
    ).with_for_update().first()
    previous_version = 0
    if previous_current:
        previous_current.is_current = 0
        previous_version = int(previous_current.version or 0)

    # C8: Audit-Anker zur Reproduzierbarkeit + spaeteren Drift-Erkennung.
    preferences_json_snapshot = json.dumps(prefs, sort_keys=True, default=str)
    input_snapshot_hash = _compute_input_snapshot_hash(
        advisory_positions=inputs["advisory_positions"],
        cashflows=cashflows,
        goals=goals,
        advisory_wealth_rappen=advisory_wealth_rappen,
        total_wealth_rappen=total_wealth_rappen,
    )

    optimizer_audit = _optimizer_audit_fields(optimizer_result)
    # Phase 6: Stress-Eval als JSON persistieren, damit /current/payload sie
    # ohne erneuten Solver-Lauf liefern kann.
    stress_evaluations_json: str | None = None
    if optimizer_result is not None and optimizer_result.stress_evaluations:
        try:
            stress_evaluations_json = json.dumps(
                optimizer_result.stress_evaluations,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Stress-eval JSON-serialization failed: %s", exc)
            stress_evaluations_json = None
    # Phase 6.2: Solver-Reasoning persistieren, damit das Reasoning im
    # /current/payload-Pfad identisch zu /generate erscheint. Nur die
    # optimizer-spezifischen Zeilen - generische House-Matrix-Saetze und
    # dynamische Drift-Warnings werden im Read-Pfad frisch berechnet.
    optimizer_reasoning_json: str | None = None
    if optimizer_result is not None and optimizer_result.reasoning:
        try:
            optimizer_reasoning_json = json.dumps(
                list(optimizer_result.reasoning),
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Optimizer-reasoning JSON-serialization failed: %s", exc)
            optimizer_reasoning_json = None
    target_allocation = TargetAllocation(
        id=new_uuid(),
        mandate_id=mandate.id,
        version=previous_version + 1,
        is_current=1,
        target_equities_bps=targets["equities"],
        target_bonds_bps=targets["bonds"],
        target_real_estate_bps=targets["real_estate"],
        target_alternatives_bps=targets["alternatives"],
        target_liquidity_bps=targets["liquidity"],
        band_equities_min_bps=minimums["equities"],
        band_equities_max_bps=maximums["equities"],
        band_bonds_min_bps=minimums["bonds"],
        band_bonds_max_bps=maximums["bonds"],
        band_real_estate_min_bps=minimums["real_estate"],
        band_real_estate_max_bps=maximums["real_estate"],
        band_alternatives_min_bps=minimums["alternatives"],
        band_alternatives_max_bps=maximums["alternatives"],
        band_liquidity_min_bps=minimums["liquidity"],
        band_liquidity_max_bps=maximums["liquidity"],
        risky_fraction_bps=risky_fraction_total_bps,
        based_on_assessment_id=assessment.id,
        capital_market_assumptions_id=cma.id,
        # C8 audit anchors
        preferences_json=preferences_json_snapshot,
        input_snapshot_hash=input_snapshot_hash,
        advisory_wealth_at_generation_rappen=advisory_wealth_rappen,
        total_wealth_at_generation_rappen=total_wealth_rappen,
        reserve_needed_at_generation_rappen=reserve_needed_rappen,
        external_reserve_at_generation_rappen=external_reserve_rappen,
        # Phase 4 Optimizer-Audit-Anchor (None wenn house_matrix-Modus)
        optimization_method=optimizer_audit.get("optimization_method"),
        optimization_objective_value_milli=optimizer_audit.get("optimization_objective_value_milli"),
        optimization_iterations=optimizer_audit.get("optimization_iterations"),
        optimization_seed=optimizer_audit.get("optimization_seed"),
        optimization_status=optimizer_audit.get("optimization_status"),
        stress_evaluations_json=stress_evaluations_json,
        optimizer_reasoning_json=optimizer_reasoning_json,
        policy_id=policy.id,
        set_by=user_id,
        set_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(target_allocation)
    db.flush()

    current_amounts = advisory_summary.amounts_rappen
    bucket_response = _build_bucket_response(
        target_allocation,
        current_amounts,
        advisory_wealth_rappen,
        target_total_rappen=investable_advisory_wealth_rappen,
    )

    return {
        "target_allocation": target_allocation,
        "policy": policy,
        "capital_market_assumptions": cma,
        "risk_assessment": assessment,
        "house_matrix_profile": house_matrix.profile_name,
        "score_bucket": score_bucket,
        "advisory_wealth_rappen": advisory_wealth_rappen,
        "investable_advisory_wealth_rappen": investable_advisory_wealth_rappen,
        "strategy_base_rappen": investable_advisory_wealth_rappen,
        "total_wealth_rappen": total_wealth_rappen,
        "recurring_income_rappen": recurring_income_rappen,
        "recurring_expense_rappen": recurring_expense_rappen,
        "capital_inflow_rappen": capital_inflow_rappen,
        "capital_outflow_rappen": capital_outflow_rappen,
        "recurring_net_cashflow_rappen": recurring_net_cashflow_rappen,
        "capital_net_cashflow_rappen": capital_net_cashflow_rappen,
        "annual_net_cashflow_rappen": annual_net_cashflow_rappen,
        "cashflow_projection_series_rappen": cashflow_projection_series_rappen,
        "recurring_cashflow_projection_series_rappen": recurring_cashflow_projection_series_rappen,
        "reserve_needed_rappen": reserve_needed_rappen,
        "external_reserve_rappen": external_reserve_rappen,
        "risk_budget_bps": int(house_matrix.max_risky_fraction_bps),
        "risky_fraction_total_bps": risky_fraction_total_bps,
        "risky_fraction_headroom_bps": int(house_matrix.max_risky_fraction_bps) - int(risky_fraction_total_bps),
        "asset_class_risky_weights_bps": asset_risky_weights,
        "expected_return_bps": metrics["expected_return_bps"],
        "expected_volatility_bps": metrics["expected_volatility_bps"],
        "capital_market_assumption_set": cma.assumption_set_name,
        "capital_market_source": cma.source,
        "reasoning": reasoning,
        "buckets": bucket_response,
        "sub_allocations": sub_allocations,
        "asset_class_assumptions": asset_class_assumptions,
        "sub_asset_class_assumptions_reference": sub_asset_class_assumptions_reference,
        "simulation": simulation,
        "monte_carlo": monte_carlo,
        "goal_analysis": goal_analysis,
        "mandate_score": _build_mandate_score(goal_analysis),
        # Phase 6: Stress-Auswertungen fuer FE-Optimizer-Panel. None wenn
        # house_matrix-Modus oder Solver-Fallback.
        "stress_evaluations": (
            optimizer_result.stress_evaluations if optimizer_result is not None else None
        ),
    }


def evaluate_goal_sensitivity(
    db: Session,
    mandate: Mandate,
    user_id: str,
    goal_id: str,
    target_delta_pct: int,
) -> dict:
    """Phase 6 FE-Sensitivity-Analyse: ein einzelnes Goal um ±delta% verschieben.

    Laeuft den Solver zweimal mit identischem Seed:
      1. Baseline mit unveraendertem Goal-Target
      2. Modifiziert: target_amount_rappen oder target_wealth_rappen * (1+delta/100)

    Identischer Seed -> identische Scenarios -> sauberes Apples-to-Apples-Delta.

    Raises ValueError bei:
      - settings.optimizer_mode != 'stochastic'
      - kein Risikoprofil
      - goal_id gehoert nicht zum Mandanten / nicht aktiv
      - target_delta_pct nicht in {-20,-10,0,10,20} (eigentlich vom Schema
        validiert, hier nochmals defensiv)
    """
    if settings.optimizer_mode != "stochastic":
        raise ValueError(
            "Sensitivity-Analyse erfordert OPTIMIZER_MODE=stochastic."
        )
    if target_delta_pct not in (-20, -10, 0, 10, 20):
        raise ValueError(
            f"target_delta_pct {target_delta_pct} ungueltig "
            "(erlaubt: -20, -10, 0, 10, 20)."
        )

    policy, cma = ensure_runtime_reference_data(db, user_id)
    assessment = db.query(RiskAssessment).filter(
        RiskAssessment.mandate_id == mandate.id,
        RiskAssessment.is_current == 1,
        RiskAssessment.deleted_at.is_(None),
    ).first()
    if not assessment:
        raise ValueError("Bitte zuerst ein aktuelles Risikoprofil speichern.")

    inputs = _load_allocation_inputs(db, mandate, simulation_prefs={}, cma=cma)
    goals = inputs["goals"]
    target_goal = next(
        (g for g in goals if g.id == goal_id and g.mandate_id == mandate.id),
        None,
    )
    if target_goal is None:
        raise ValueError(f"Goal {goal_id} nicht gefunden im Mandanten {mandate.id}.")

    advisory_wealth_rappen = inputs["advisory_wealth_rappen"]
    cashflow_projection_series_rappen = inputs["cashflow_projection_series_rappen"]
    cashflow_totals = inputs["cashflow_totals"]
    inflation_series_bps = _goal_inflation_series_bps(
        cma,
        len(cashflow_projection_series_rappen),
        cashflow_totals["year"],
        planning_inflation_bps=_current_planning_inflation_bps(db, mandate),
    )

    score_bucket = _risk_score_bucket(assessment)
    house_matrix = _house_matrix_or_default(db, policy, score_bucket)
    score_x10 = _assessment_score_x10(assessment)
    horizon = max(10, int(len(cashflow_projection_series_rappen) or 10))

    building_blocks_rows = db.query(BuildingBlock).filter(
        BuildingBlock.policy_id == policy.id,
        BuildingBlock.is_active == 1,
    ).all()

    from services.optimizer.constraints import (
        bucket_risky_fractions_from_building_blocks,
    )
    from services.optimizer.solver import deterministic_seed, run_solver

    rf_per_bucket = None
    try:
        rf_per_bucket = bucket_risky_fractions_from_building_blocks(building_blocks_rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sensitivity: risky-fraction extraction failed: %s", exc)

    # Pin den Seed: identisch fuer baseline + modified, damit Scenarios gleich
    # sind und das objektive Delta nur vom Goal-Shift kommt.
    cma_id = getattr(cma, "id", "no-cma")
    goal_ids = "|".join(str(getattr(g, "id", "?")) for g in goals)
    pinned_seed = deterministic_seed(
        cma_id, goal_ids, score_x10, horizon, _OPTIMIZER_N_PATHS_DEFAULT,
        "sensitivity", target_goal.id, target_delta_pct,
    )

    def _solve(_goals: list):
        return run_solver(
            cma=cma,
            goals=_goals,
            house_matrix_row=house_matrix,
            score_x10=score_x10,
            advisory_wealth_rappen=advisory_wealth_rappen,
            cashflow_series_rappen=cashflow_projection_series_rappen,
            horizon_years=horizon,
            n_paths=_OPTIMIZER_N_PATHS_DEFAULT,
            seed=pinned_seed,
            inflation_series_bps=inflation_series_bps,
            risky_fraction_per_bucket=rf_per_bucket,
        )

    # ---- Baseline ----
    baseline_amount = int(target_goal.target_amount_rappen or 0)
    baseline_wealth = int(target_goal.target_wealth_rappen or 0)
    baseline_result = _solve(goals)

    # ---- Modified ----
    factor = 1.0 + (target_delta_pct / 100.0)
    new_amount = int(round(baseline_amount * factor))
    new_wealth = int(round(baseline_wealth * factor))
    original_amount = target_goal.target_amount_rappen
    original_wealth = target_goal.target_wealth_rappen
    try:
        target_goal.target_amount_rappen = new_amount
        target_goal.target_wealth_rappen = new_wealth
        modified_result = _solve(goals)
    finally:
        # Reset to ensure DB-side state isn't accidentally persisted by caller.
        target_goal.target_amount_rappen = original_amount
        target_goal.target_wealth_rappen = original_wealth

    def _obj_milli(value: float) -> int | None:
        if value == float("inf") or value != value:  # NaN
            return None
        scaled = value * 1000.0
        if scaled > _OPTIMIZER_OBJECTIVE_MILLI_CAP:
            return _OPTIMIZER_OBJECTIVE_MILLI_CAP
        if scaled < -_OPTIMIZER_OBJECTIVE_MILLI_CAP:
            return -_OPTIMIZER_OBJECTIVE_MILLI_CAP
        return int(round(scaled))

    obj_base = _obj_milli(baseline_result.objective_value)
    obj_new = _obj_milli(modified_result.objective_value)
    delta_pct: float | None = None
    if obj_base is not None and obj_new is not None and obj_base != 0:
        delta_pct = round((obj_new - obj_base) / abs(obj_base) * 100.0, 2)

    primary_baseline = baseline_amount or baseline_wealth
    primary_new = new_amount if baseline_amount else new_wealth

    return {
        "goal_id": target_goal.id,
        "delta_pct": int(target_delta_pct),
        "target_amount_rappen_baseline": int(primary_baseline),
        "target_amount_rappen_new": int(primary_new),
        "objective_value_milli_baseline": obj_base,
        "objective_value_milli_new": obj_new,
        "delta_objective_pct": delta_pct,
        "weights_bps_baseline": dict(baseline_result.weights_bps),
        "weights_bps_new": dict(modified_result.weights_bps),
        "status_baseline": baseline_result.status,
        "status_new": modified_result.status,
    }


def build_target_payload_from_allocation(
    db: Session,
    mandate: Mandate,
    allocation: TargetAllocation,
    policy: OptimizerPolicy,
    cma: CapitalMarketAssumption,
    assessment: RiskAssessment,
    preferences: dict | None,
) -> dict:
    prefs = _normalize_preferences(preferences)
    score_bucket = _risk_score_bucket(assessment)
    house_matrix = _house_matrix_or_default(db, policy, score_bucket)
    all_positions = db.query(WealthPosition).filter(
        WealthPosition.client_id == mandate.client_id,
        WealthPosition.deleted_at.is_(None),
        WealthPosition.is_active == 1,
    ).all()
    advisory_positions = [pos for pos in all_positions if _norm_text(pos.assignment) == "Beratungsvermoegen"]
    asset_positions_total = [pos for pos in all_positions if _norm_text(pos.assignment) != "Verbindlichkeit"]
    liability_positions = [pos for pos in all_positions if _norm_text(pos.assignment) == "Verbindlichkeit"]
    advisory_summary = _summarize_positions(advisory_positions)
    total_summary = _summarize_positions(asset_positions_total)
    advisory_wealth_rappen = advisory_summary.total_rappen
    total_liabilities_rappen = sum(int(pos.current_value_rappen or 0) for pos in liability_positions)
    total_wealth_rappen = max(0, total_summary.total_rappen - total_liabilities_rappen)

    cashflows = db.query(Cashflow).filter(
        Cashflow.client_id == mandate.client_id,
        Cashflow.deleted_at.is_(None),
        Cashflow.is_active == 1,
    ).all()

    goals = db.query(Goal).filter(
        Goal.mandate_id == mandate.id,
        Goal.deleted_at.is_(None),
        Goal.is_active == 1,
    ).order_by(Goal.rank.asc()).all()
    cashflow_totals = totals_for_year(cashflows)
    recurring_income_rappen = cashflow_totals["recurring_income_rappen"]
    recurring_expense_rappen = cashflow_totals["recurring_expense_rappen"]
    capital_inflow_rappen = cashflow_totals["capital_inflow_rappen"]
    capital_outflow_rappen = cashflow_totals["capital_outflow_rappen"]
    recurring_net_cashflow_rappen = recurring_income_rappen - recurring_expense_rappen
    capital_net_cashflow_rappen = capital_inflow_rappen - capital_outflow_rappen
    annual_net_cashflow_rappen = cashflow_totals["net_rappen"]
    projection_years = _simulation_horizon_years(prefs["simulation"], goals)
    # B1: Cashflow-Series mit CMA-Inflations-Pfad (siehe _load_allocation_inputs).
    cf_inflation_series_bps = _inflation_path_series(cma, projection_years, cashflow_totals["year"])
    cashflow_projection_series_rappen = net_cashflow_series(
        cashflows,
        projection_years,
        start_year=cashflow_totals["year"],
        inflation_series_bps=cf_inflation_series_bps,
    )
    recurring_cashflow_projection_series_rappen = recurring_net_cashflow_series(
        cashflows,
        projection_years,
        start_year=cashflow_totals["year"],
        inflation_series_bps=cf_inflation_series_bps,
    )

    minimums = {
        "equities": int(allocation.band_equities_min_bps or 0),
        "bonds": int(allocation.band_bonds_min_bps or 0),
        "real_estate": int(allocation.band_real_estate_min_bps or 0),
        "alternatives": int(allocation.band_alternatives_min_bps or 0),
        "liquidity": int(allocation.band_liquidity_min_bps or 0),
    }
    maximums = {
        "equities": int(allocation.band_equities_max_bps or 0),
        "bonds": int(allocation.band_bonds_max_bps or 0),
        "real_estate": int(allocation.band_real_estate_max_bps or 0),
        "alternatives": int(allocation.band_alternatives_max_bps or 0),
        "liquidity": int(allocation.band_liquidity_max_bps or 0),
    }
    targets = {
        "equities": int(allocation.target_equities_bps),
        "bonds": int(allocation.target_bonds_bps),
        "real_estate": int(allocation.target_real_estate_bps),
        "alternatives": int(allocation.target_alternatives_bps),
        "liquidity": int(allocation.target_liquidity_bps),
    }
    normalized_legacy_liquidity = False
    saa_liq_ceil_bps = min(
        int(maximums["liquidity"] or house_matrix.liq_max_bps or _SAA_LIQUIDITY_HARD_CAP_BPS),
        _SAA_LIQUIDITY_HARD_CAP_BPS,
    )
    if targets["liquidity"] > saa_liq_ceil_bps:
        normalized_legacy_liquidity = True
        minimums["liquidity"] = min(int(minimums["liquidity"]), saa_liq_ceil_bps)
        targets["liquidity"] = saa_liq_ceil_bps
        maximums["liquidity"] = saa_liq_ceil_bps
        targets = _rebalance_to_total(targets, minimums, maximums)

    risky_map = _building_block_risky_map(db, policy.id)
    sub_allocations = _build_sub_allocations(targets, prefs)
    sub_allocations, asset_risky_weights, risky_fraction_total_bps = _enrich_sub_allocations_with_risk(sub_allocations, risky_map)
    # C3: gewichtete Bucket-Metriken aus Sub-Allocation.
    metrics = _expected_metrics(targets, cma, sub_allocations)
    # C7: Reserve-Berechnung zentral via _compute_reserve_for_inputs - identisch
    # zum generate-Pfad, damit Reserve nicht zwischen Generieren und Wiederaufbau driftet.
    reserve_needed_rappen, external_reserve_rappen = _compute_reserve_for_inputs(
        goals=goals,
        limits_prefs=prefs["limits"],
        asset_class_prefs=prefs["assetClasses"],
        recurring_net_cashflow_rappen=recurring_net_cashflow_rappen,
        recurring_cashflow_projection_series_rappen=recurring_cashflow_projection_series_rappen,
        advisory_wealth_rappen=advisory_wealth_rappen,
        saa_liquidity_ceiling_bps=saa_liq_ceil_bps,
        reasoning=None,
    )
    investable_advisory_wealth_rappen = _investable_advisory_wealth_rappen(advisory_wealth_rappen, external_reserve_rappen)
    goal_inflation_series_bps = _goal_inflation_series_bps(
        cma,
        len(cashflow_projection_series_rappen),
        cashflow_totals["year"],
        planning_inflation_bps=_current_planning_inflation_bps(db, mandate),
    )
    goal_analysis = _build_goal_analysis(
        goals=goals,
        advisory_wealth_rappen=investable_advisory_wealth_rappen,
        total_wealth_rappen=total_wealth_rappen,
        cashflow_projection_series_rappen=cashflow_projection_series_rappen,
        inflation_series_bps=goal_inflation_series_bps,
        expected_return_bps=metrics["expected_return_bps"],
        reserve_needed_rappen=reserve_needed_rappen,
        policy=policy,
    )
    asset_class_assumptions = _build_asset_class_assumptions(
        current_amounts=advisory_summary.amounts_rappen,
        advisory_wealth_rappen=advisory_wealth_rappen,
        targets=targets,
        asset_risky_weights=asset_risky_weights,
        cma=cma,
        sub_allocations=sub_allocations,
    )
    sub_asset_class_assumptions_reference = _build_sub_asset_class_assumption_reference(
        sub_allocations,
        cma,
    )
    simulation = _build_simulation_payload(
        advisory_summary=advisory_summary,
        cashflow_projection_series_rappen=cashflow_projection_series_rappen,
        cma=cma,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        start_year=cashflow_totals["year"],
        simulation_prefs=prefs["simulation"],
        sub_allocations=sub_allocations,
        target_total_rappen=investable_advisory_wealth_rappen,
        total_summary=total_summary,
        total_liabilities_rappen=total_liabilities_rappen,
    )
    monte_carlo = _run_allocation_monte_carlo(
        advisory_summary=advisory_summary,
        cashflow_projection_series_rappen=cashflow_projection_series_rappen,
        goal_inflation_series_bps=goal_inflation_series_bps,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        cma=cma,
        goals=goals,
        advisory_wealth_rappen=advisory_wealth_rappen,
        total_wealth_rappen=total_wealth_rappen,
        policy=policy,
        mandate_id=mandate.id,
        simulation_prefs=prefs["simulation"],
        start_year=cashflow_totals["year"],
        sub_allocations=sub_allocations,
        target_total_rappen=investable_advisory_wealth_rappen,
        total_summary=total_summary,
        total_liabilities_rappen=total_liabilities_rappen,
    )
    goal_analysis = _merge_goal_analysis_with_monte_carlo(goal_analysis, monte_carlo)
    bucket_response = []
    current_amounts = advisory_summary.amounts_rappen
    label_map = {
        "equities": ("Aktien", targets["equities"], minimums["equities"], maximums["equities"]),
        "bonds": ("Obligationen", targets["bonds"], minimums["bonds"], maximums["bonds"]),
        "real_estate": ("Immobilien", targets["real_estate"], minimums["real_estate"], maximums["real_estate"]),
        "alternatives": ("Alternative", targets["alternatives"], minimums["alternatives"], maximums["alternatives"]),
        "liquidity": ("Liquiditaet", targets["liquidity"], minimums["liquidity"], maximums["liquidity"]),
    }
    for key in BUCKET_FIELDS:
        label, target_bps, min_bps, max_bps = label_map[key]
        current_amount = current_amounts[key]
        current_bps = _bps(current_amount, advisory_wealth_rappen)
        bucket_response.append(
            {
                "asset_class": label,
                "current_weight_bps": current_bps,
                "current_amount_rappen": current_amount,
                "target_weight_bps": int(target_bps),
                "target_amount_rappen": int(round(investable_advisory_wealth_rappen * target_bps / 10000)) if investable_advisory_wealth_rappen else 0,
                "delta_weight_bps": int(target_bps) - current_bps,
                "band_min_bps": int(min_bps),
                "band_max_bps": int(max_bps),
            }
        )
    live_rebalancing = None
    current_run = _current_recommendation_run(db, mandate.id)
    if current_run and not normalized_legacy_liquidity:
        # C6: Live-Rebalancing nutzt investierbare Basis (Beratungsvermoegen
        # abzueglich externer Reserve), konsistent mit target_amount_rappen.
        live_rebalancing = build_live_rebalancing_payload(
            db=db,
            allocation=allocation,
            run=current_run,
            advisory_wealth_rappen=investable_advisory_wealth_rappen,
        )
    # C8: aktueller input snapshot fuer Drift-Vergleich.
    current_snapshot_hash = _compute_input_snapshot_hash(
        advisory_positions=advisory_positions,
        cashflows=cashflows,
        goals=goals,
        advisory_wealth_rappen=advisory_wealth_rappen,
        total_wealth_rappen=total_wealth_rappen,
    )
    current_preferences_json = json.dumps(prefs, sort_keys=True, default=str)
    drift_warnings = _strategy_drift_warnings(
        allocation,
        assessment=assessment,
        cma=cma,
        current_input_snapshot_hash=current_snapshot_hash,
        current_preferences_json=current_preferences_json,
        current_advisory_wealth_rappen=advisory_wealth_rappen,
        current_external_reserve_rappen=external_reserve_rappen,
    )
    # Phase 6: persistierte Stress-Auswertungen aus der Allocation deserialisieren.
    # NULL bei pre-Optimizer-Allocations oder house_matrix-Modus.
    stress_evaluations: dict | None = None
    raw_stress = getattr(allocation, "stress_evaluations_json", None)
    if raw_stress:
        try:
            parsed = json.loads(raw_stress)
            if isinstance(parsed, dict):
                stress_evaluations = parsed
        except (TypeError, ValueError) as exc:
            logger.warning(
                "Stored stress_evaluations_json invalid for allocation %s: %s",
                getattr(allocation, "id", "?"), exc,
            )
    # Phase 6.2: persistierten Solver-Reasoning-Trace deserialisieren.
    persisted_optimizer_reasoning: list[str] = []
    raw_reasoning = getattr(allocation, "optimizer_reasoning_json", None)
    if raw_reasoning:
        try:
            parsed_reasoning = json.loads(raw_reasoning)
            if isinstance(parsed_reasoning, list):
                persisted_optimizer_reasoning = [
                    str(item) for item in parsed_reasoning if item
                ]
        except (TypeError, ValueError) as exc:
            logger.warning(
                "Stored optimizer_reasoning_json invalid for allocation %s: %s",
                getattr(allocation, "id", "?"), exc,
            )
    return {
        "target_allocation": allocation,
        "policy": policy,
        "capital_market_assumptions": cma,
        "risk_assessment": assessment,
        "house_matrix_profile": house_matrix.profile_name,
        "score_bucket": score_bucket,
        "advisory_wealth_rappen": advisory_wealth_rappen,
        "investable_advisory_wealth_rappen": investable_advisory_wealth_rappen,
        "strategy_base_rappen": investable_advisory_wealth_rappen,
        "total_wealth_rappen": total_wealth_rappen,
        "recurring_income_rappen": recurring_income_rappen,
        "recurring_expense_rappen": recurring_expense_rappen,
        "capital_inflow_rappen": capital_inflow_rappen,
        "capital_outflow_rappen": capital_outflow_rappen,
        "recurring_net_cashflow_rappen": recurring_net_cashflow_rappen,
        "capital_net_cashflow_rappen": capital_net_cashflow_rappen,
        "annual_net_cashflow_rappen": annual_net_cashflow_rappen,
        "cashflow_projection_series_rappen": cashflow_projection_series_rappen,
        "recurring_cashflow_projection_series_rappen": recurring_cashflow_projection_series_rappen,
        "reserve_needed_rappen": reserve_needed_rappen,
        "external_reserve_rappen": external_reserve_rappen,
        "risk_budget_bps": int(house_matrix.max_risky_fraction_bps or 0),
        "risky_fraction_total_bps": risky_fraction_total_bps,
        "risky_fraction_headroom_bps": int(house_matrix.max_risky_fraction_bps or 0) - int(risky_fraction_total_bps),
        "asset_class_risky_weights_bps": asset_risky_weights,
        "expected_return_bps": metrics["expected_return_bps"],
        "expected_volatility_bps": metrics["expected_volatility_bps"],
        "capital_market_assumption_set": cma.assumption_set_name,
        "capital_market_source": cma.source,
        "reasoning": (
            [
                "Verwendet die bestehende aktuelle Soll-Allokation.",
                "Die Projektion wird zusaetzlich ueber normalverteilte Jahresrenditen als Pfadsimulation verdichtet.",
            ]
            + (
                [
                    "Eine fruehere hohe Liquiditaetsquote wird nach heutiger Policy als externe Reserve interpretiert und fuer die Anzeige auf die strategische SAA-Liquiditaet gekappt."
                ]
                if normalized_legacy_liquidity
                else []
            )
            # Phase 6.2: persistiertes Solver-Reasoning anhaengen, damit das
            # FE-Optimizer-Panel beim Reload den vollen Iter-/Stress-Trace
            # zeigt (nicht nur die generischen 2 Saetze oben).
            + persisted_optimizer_reasoning
            # C8: zentrale Drift-Warnings (Assessment, CMA, Inputs, Preferences,
            # Reserve, Legacy-Anker). Konsolidiert ehemalige inline F2-/F3-Logik.
            + drift_warnings
        ),
        "buckets": bucket_response,
        "sub_allocations": sub_allocations,
        "asset_class_assumptions": asset_class_assumptions,
        "sub_asset_class_assumptions_reference": sub_asset_class_assumptions_reference,
        "simulation": simulation,
        "monte_carlo": monte_carlo,
        "goal_analysis": goal_analysis,
        "live_rebalancing": live_rebalancing,
        "stress_evaluations": stress_evaluations,
    }


def build_recommendation_payload_from_run(
    db: Session,
    mandate: Mandate,
    run: RecommendationRun,
    user_id: str,
    preferences: dict | None,
) -> dict:
    policy, cma = ensure_runtime_reference_data(db, user_id)
    assessment = db.query(RiskAssessment).filter(
        RiskAssessment.mandate_id == mandate.id,
        RiskAssessment.is_current == 1,
        RiskAssessment.deleted_at.is_(None),
    ).first()
    if not assessment:
        raise ValueError("Bitte zuerst ein aktuelles Risikoprofil speichern.")

    allocation = None
    if run.target_allocation_id:
        allocation = db.query(TargetAllocation).filter(
            TargetAllocation.id == run.target_allocation_id,
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.deleted_at.is_(None),
        ).first()
    if not allocation:
        allocation = db.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        ).first()
    if not allocation:
        raise ValueError("Keine aktuelle Soll-Allokation fuer dieses Mandat gefunden.")

    target_payload = build_target_payload_from_allocation(
        db=db,
        mandate=mandate,
        allocation=allocation,
        policy=policy,
        cma=cma,
        assessment=assessment,
        preferences=preferences,
    )
    advisory_wealth_rappen = int(target_payload["advisory_wealth_rappen"] or 0)
    investable_advisory_wealth_rappen = int(target_payload.get("investable_advisory_wealth_rappen") or advisory_wealth_rappen)
    positions = db.query(RecommendationPosition).filter(
        RecommendationPosition.run_id == run.id,
    ).order_by(RecommendationPosition.target_weight_bps.desc()).all()
    product_ids = [position.product_id for position in positions if position.product_id]
    latest_prices = latest_price_snapshot(db, product_ids)
    market_data_quality = summarize_price_quality(db, product_ids)
    payload_target_map = {
        str(item.get("asset_class") or ""): int(item.get("target_weight_bps") or 0)
        for item in (target_payload.get("buckets") or [])
    }
    raw_target_map = {
        BUCKET_LABELS["equities"]: int(allocation.target_equities_bps or 0),
        BUCKET_LABELS["bonds"]: int(allocation.target_bonds_bps or 0),
        BUCKET_LABELS["real_estate"]: int(allocation.target_real_estate_bps or 0),
        BUCKET_LABELS["alternatives"]: int(allocation.target_alternatives_bps or 0),
        BUCKET_LABELS["liquidity"]: int(allocation.target_liquidity_bps or 0),
    }
    stale_recommendation_targets = any(
        int(payload_target_map.get(label, raw_target)) != int(raw_target)
        for label, raw_target in raw_target_map.items()
    )
    live_rebalancing = None
    if not stale_recommendation_targets:
        live_rebalancing = build_live_rebalancing_payload(
            db=db,
            allocation=allocation,
            run=run,
            advisory_wealth_rappen=investable_advisory_wealth_rappen,
            positions=positions,
        )
    live_positions_by_id = {
        item["id"]: item for item in ((live_rebalancing or {}).get("position_drifts") or [])
    }
    today = date.today()
    products_by_id = {}
    if product_ids:
        products_by_id = {
            product.id: product
            for product in db.query(Product).filter(Product.id.in_(product_ids)).all()
        }

    warnings: list[str] = []
    if stale_recommendation_targets:
        warnings.append(
            "Die gespeicherte Empfehlung basiert auf einer frueheren Soll-Allokation. "
            "Bitte Empfehlung neu berechnen, bevor Umsetzung oder Rebalancing beurteilt werden."
        )
    positions_payload = []
    for position in positions:
        product = products_by_id.get(position.product_id)
        if not product:
            warnings.append(f"Produkt {position.product_id} fuer die gespeicherte Empfehlung ist nicht mehr verfuegbar.")
            continue
        market_profile = resolve_market_profile(product)
        latest_price = latest_prices.get(product.id)
        price_date = parse_iso_date(latest_price.price_date) if latest_price else None
        price_age_days = (today - price_date).days if price_date else None
        price_is_fresh = bool(price_age_days is not None and price_age_days <= int(market_data_quality.get("stale_after_days") or 5))
        live_position = live_positions_by_id.get(position.id) or {}
        positions_payload.append(
            {
                "id": position.id,
                "run_id": run.id,
                "product_id": product.id,
                "product_name": product.product_name,
                "provider": product.provider,
                "isin": product.isin or market_profile.get("isin"),
                "symbol": product.symbol or market_profile.get("symbol"),
                "figi": product.figi,
                "exchange_code": product.exchange_code,
                "mapping_provider": product.mapping_provider,
                "mapping_resolved_at": product.mapping_resolved_at,
                "reference_data_provider": product.reference_data_provider,
                "reference_data_refreshed_at": product.reference_data_refreshed_at,
                "lookup_symbol": market_profile.get("lookup_symbol"),
                "lookup_mode": market_profile.get("lookup_mode"),
                "pricing_note": market_profile.get("pricing_note"),
                "product_type": product.product_type,
                "asset_class": product.asset_class,
                "sub_asset_class": product.sub_asset_class,
                "source_sub_asset_classes": [],
                "currency": product.currency,
                "ter_bps": product.ter_bps,
                "target_weight_bps": int(position.target_weight_bps or 0),
                "target_amount_rappen": int(position.target_amount_rappen or 0),
                "rationale": position.rationale,
                "reference_price_date": live_position.get("reference_price_date") or position.reference_price_date,
                "reference_price_rappen": live_position.get("reference_price_rappen") or position.reference_price_rappen,
                "reference_price_source": position.reference_price_source,
                "reference_lookup_mode": position.reference_lookup_mode,
                "reference_price_fetched_at": position.reference_price_fetched_at,
                "reference_recalibrated": live_position.get("reference_recalibrated"),
                "latest_price_date": latest_price.price_date if latest_price else None,
                "latest_price_rappen": int(latest_price.price_rappen or 0) if latest_price else None,
                "price_source": latest_price.source if latest_price else None,
                "price_age_days": price_age_days,
                "price_is_fresh": price_is_fresh if latest_price else None,
                "holding_present": bool(live_position.get("holding_present")),
                "holding_source": live_position.get("holding_source"),
                "holding_as_of_date": live_position.get("holding_as_of_date"),
                "holding_units_milli": live_position.get("holding_units_milli"),
                "current_units_milli": live_position.get("current_units_milli"),
                "holding_market_value_rappen": live_position.get("holding_market_value_rappen"),
                "holding_avg_cost_price_rappen": live_position.get("holding_avg_cost_price_rappen"),
                "holding_depot_bank": live_position.get("holding_depot_bank"),
                "holding_custody_account_number": live_position.get("holding_custody_account_number"),
                "holding_notes": live_position.get("holding_notes"),
                "valuation_basis": live_position.get("valuation_basis"),
                "implied_units_milli": live_position.get("implied_units_milli"),
                "current_market_value_rappen": live_position.get("current_market_value_rappen"),
                "current_weight_bps": live_position.get("current_weight_bps"),
                "delta_weight_bps": live_position.get("delta_weight_bps"),
                "rebalance_amount_rappen": live_position.get("rebalance_amount_rappen"),
                "price_change_bps": live_position.get("price_change_bps"),
                "rebalance_action": live_position.get("rebalance_action"),
                "rebalance_action_code": live_position.get("rebalance_action_code"),
                "rebalance_action_label": live_position.get("rebalance_action_label"),
            }
        )

    avg_ter_bps = _average_ter_bps(positions_payload)
    missing_ter_count = _missing_ter_positions_count(positions_payload)
    ter_coverage_bps = _ter_coverage_bps(positions_payload)
    if missing_ter_count:
        warnings.append(
            f"TER fehlt fuer {missing_ter_count} Position(en); Durchschnittskosten basieren nur auf bekannter TER-Abdeckung."
        )
    return {
        "run": run,
        "positions": positions_payload,
        "warnings": warnings,
        "implementation_steps": _implementation_steps(target_payload["buckets"], investable_advisory_wealth_rappen),
        "advisory_wealth_rappen": advisory_wealth_rappen,
        "investable_advisory_wealth_rappen": investable_advisory_wealth_rappen,
        "expected_return_bps": int(target_payload["expected_return_bps"]),
        "expected_volatility_bps": int(target_payload["expected_volatility_bps"]),
        "average_ter_bps": avg_ter_bps,
        "average_ter_coverage_bps": ter_coverage_bps,
        "missing_ter_positions_count": missing_ter_count,
        "target_allocation_id": allocation.id,
        "context_status": "current",
        "market_data_quality": market_data_quality,
        "live_rebalancing": live_rebalancing,
    }


def _product_matches_constraints(product: Product, prefs: dict, score_bucket: int) -> bool:
    product_prefs = prefs["product"]
    geo_prefs = prefs["geo"]
    policy_prefs = prefs["policy"]
    asset_class = _norm_text(product.asset_class)
    if product_prefs.get("fundsOnly") and asset_class != "Liquiditaet" and product.product_type not in ("ETF", "Fonds", "Immobilienfonds"):
        return False
    if product_prefs.get("listedOnly") and asset_class != "Liquiditaet" and product.product_type not in ("ETF", "Einzeltitel", "Anleihe"):
        return False
    if geo_prefs.get("chfOnly") and product.currency != "CHF":
        return False
    if geo_prefs.get("noUsd") and product.currency == "USD":
        return False
    if policy_prefs.get("esg") in ("best_in_class", "impact", "net_zero") and asset_class != "Liquiditaet":
        if str(product.sfdr_class or "") not in ("8", "9"):
            return False
    if product.suitability:
        allowed = [
            rule for rule in product.suitability
            if int(rule.profile_from or 1) <= score_bucket <= int(rule.profile_to or 10) and int(rule.advisory_allowed or 0) == 1
        ]
        return bool(allowed)
    return True


def _product_score(product: Product, sub_asset_class: str, prefs: dict) -> int:
    score = 1000
    score -= int(product.ter_bps or 0)
    if product.currency == "CHF":
        score += 40
    if product.sub_asset_class == sub_asset_class:
        score += 200
    elif _norm_text(product.asset_class) in ("Aktien", "Obligationen", "Immobilien", "Alternative", "Liquiditaet"):
        score += 50
    policy_prefs = prefs["policy"]
    geo_prefs = prefs["geo"]
    tilts = prefs["tilts"]
    if policy_prefs.get("homeBias") == "ch_focus" and ("Schweiz" in (product.sub_asset_class or "") or product.currency == "CHF"):
        score += 35
    if geo_prefs.get("hedgingRequired") and "Hedged" in str(product.sub_asset_class or ""):
        score += 20
    if str(product.sfdr_class or "") in ("8", "9"):
        score += 25
    thematic_map = {
        "Thema Fossile Energie": "fossil",
        "Thema Verteidigung": "defense",
        "Thema Tabak": "tobacco",
        "Thema Alkohol": "alcohol",
        "Thema Gluecksspiel": "gaming",
        "Thema Kernenergie": "nuclear",
    }
    thematic_key = thematic_map.get(sub_asset_class)
    if thematic_key:
        tilt_mode = tilts.get(thematic_key)
        if tilt_mode == "exclude":
            return -10000
        if tilt_mode == "underweight":
            score -= 150
        if tilt_mode == "overweight":
            score += 250
    return score


def _items_with_known_ter(items: list[dict]) -> list[dict]:
    return [item for item in items if item.get("ter_bps") is not None]


def _average_ter_bps(items: list[dict]) -> int:
    known = _items_with_known_ter(items)
    total_weight = sum(int(item.get("target_weight_bps") or 0) for item in known)
    if total_weight <= 0:
        return 0
    weighted_ter = sum(int(item.get("ter_bps") or 0) * int(item.get("target_weight_bps") or 0) for item in known)
    return int(round(weighted_ter / total_weight))


def _ter_coverage_bps(items: list[dict]) -> int:
    total_weight = sum(int(item.get("target_weight_bps") or 0) for item in items)
    if total_weight <= 0:
        return 0
    known_weight = sum(int(item.get("target_weight_bps") or 0) for item in _items_with_known_ter(items))
    return max(0, min(10000, int(round(known_weight / total_weight * 10000))))


def _missing_ter_positions_count(items: list[dict]) -> int:
    return sum(1 for item in items if item.get("ter_bps") is None)


def _implementation_steps(buckets: list[dict], target_total_rappen: int) -> list[str]:
    steps = []
    def amount_delta_rappen(item: dict) -> int:
        if item.get("target_amount_rappen") is not None and item.get("current_amount_rappen") is not None:
            return int(item.get("target_amount_rappen") or 0) - int(item.get("current_amount_rappen") or 0)
        return int(round(target_total_rappen * int(item.get("delta_weight_bps") or 0) / 10000))

    for bucket in sorted(buckets, key=lambda item: abs(amount_delta_rappen(item)), reverse=True):
        if abs(int(bucket["delta_weight_bps"])) < 100:
            continue
        delta_rappen = amount_delta_rappen(bucket)
        amount = int(round(abs(delta_rappen) / 100))
        direction = "aufbauen" if delta_rappen > 0 else "reduzieren"
        steps.append(f"{bucket['asset_class']} {direction}: ca. CHF {amount:,.0f}".replace(",", "'"))
    if not steps:
        steps.append("Aktuelle Allokation liegt bereits weitgehend in den Zielbandbreiten.")
    return steps


def generate_recommendation_run(
    db: Session,
    mandate: Mandate,
    user_id: str,
    preferences: dict | None,
    target_allocation_id: str | None = None,
    run_type: str = "Optimizer",
    depot_bank: str | None = None,
) -> dict:
    ensure_default_products(db)
    prefs = _normalize_preferences(preferences)
    policy, cma = ensure_runtime_reference_data(db, user_id)
    assessment = db.query(RiskAssessment).filter(
        RiskAssessment.mandate_id == mandate.id,
        RiskAssessment.is_current == 1,
        RiskAssessment.deleted_at.is_(None),
    ).first()
    if not assessment:
        raise ValueError("Bitte zuerst ein aktuelles Risikoprofil speichern.")

    allocation = None
    if target_allocation_id:
        allocation = db.query(TargetAllocation).filter(
            TargetAllocation.id == target_allocation_id,
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.deleted_at.is_(None),
        ).first()
    if not allocation:
        allocation = db.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        ).first()
    if allocation:
        target_payload = build_target_payload_from_allocation(
            db=db,
            mandate=mandate,
            allocation=allocation,
            policy=policy,
            cma=cma,
            assessment=assessment,
            preferences=preferences,
        )
    else:
        target_payload = generate_target_allocation(db=db, mandate=mandate, user_id=user_id, preferences=preferences)
        allocation = target_payload["target_allocation"]

    previous_holdings_by_product = _latest_holdings_by_product_for_mandate(db, mandate.id)

    now = _now()
    run = RecommendationRun(
        id=new_uuid(),
        mandate_id=mandate.id,
        client_id=mandate.client_id,
        assessment_id=assessment.id,
        target_allocation_id=allocation.id,
        policy_id=policy.id,
        capital_market_assumptions_id=cma.id,
        run_type=run_type,
        objective_summary="TBI V1 - strategische Soll-Allokation mit produktiver Titelselektion",
        optimizer_version=policy.optimizer_engine,
        weighting_regime="Ranked-Weight",
        fee_assumptions_json=policy.fee_model_json,
        other_assets_included=1,
        result_status="Draft",
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    db.flush()

    score_bucket = _risk_score_bucket(assessment)
    products = db.query(Product).filter(Product.deleted_at.is_(None), Product.is_active == 1).all()
    sub_allocations = target_payload["sub_allocations"]
    advisory_wealth_rappen = int(target_payload["advisory_wealth_rappen"] or 0)
    investable_advisory_wealth_rappen = int(target_payload.get("investable_advisory_wealth_rappen") or advisory_wealth_rappen)
    warnings = []
    positions_payload = []
    aggregated_positions: dict[str, dict] = {}

    for sub in sub_allocations:
        matching = [product for product in products if _product_matches_constraints(product, prefs, score_bucket)]
        exact = [product for product in matching if str(product.sub_asset_class or "") == str(sub["sub_asset_class"])]
        used_fallback = False
        candidates = exact
        if not candidates:
            candidates = [product for product in matching if _norm_text(product.asset_class) == _norm_text(sub["asset_class"])]
            used_fallback = bool(candidates)
        if not candidates:
            warnings.append(f"Kein passendes Produkt fuer {sub['sub_asset_class']} gefunden.")
            continue
        ranked = sorted(candidates, key=lambda product: _product_score(product, sub["sub_asset_class"], prefs), reverse=True)
        best = ranked[0]
        target_amount = int(round(investable_advisory_wealth_rappen * int(sub["target_weight_bps"]) / 10000))
        rationale = sub["rationale"]
        if used_fallback:
            rationale = rationale + f"; Fallback aus {sub['sub_asset_class']}, da keine geeignete exakte Produktabdeckung verfuegbar war"
            warnings.append(f"{sub['sub_asset_class']}: exakte Produktumsetzung nicht moeglich, Core-Fallback verwendet.")
        if depot_bank:
            rationale = rationale + f"; Umsetzung ueber {depot_bank}"
        existing = aggregated_positions.get(best.id)
        if existing:
            existing["target_weight_bps"] += int(sub["target_weight_bps"])
            existing["target_amount_rappen"] += target_amount
            if sub["sub_asset_class"] not in existing["source_sub_asset_classes"]:
                existing["source_sub_asset_classes"].append(sub["sub_asset_class"])
            if rationale not in existing["rationales"]:
                existing["rationales"].append(rationale)
        else:
            aggregated_positions[best.id] = {
                "product": best,
                "target_weight_bps": int(sub["target_weight_bps"]),
                "target_amount_rappen": target_amount,
                "source_sub_asset_classes": [sub["sub_asset_class"]],
                "rationales": [rationale],
            }

    latest_prices = latest_price_snapshot(db, list(aggregated_positions.keys()))
    market_data_quality = summarize_price_quality(db, list(aggregated_positions.keys()))
    today = date.today()

    for entry in aggregated_positions.values():
        best = entry["product"]
        source_subs = [label for label in entry["source_sub_asset_classes"] if label]
        rationale = " | ".join(entry["rationales"])
        latest_price = latest_prices.get(best.id)
        market_profile = resolve_market_profile(best)
        position = RecommendationPosition(
            id=new_uuid(),
            run_id=run.id,
            product_id=best.id,
            target_weight_bps=int(entry["target_weight_bps"]),
            target_amount_rappen=int(entry["target_amount_rappen"]),
            reference_price_rappen=int(latest_price.price_rappen or 0) if latest_price else None,
            reference_price_date=latest_price.price_date if latest_price else None,
            reference_price_source=latest_price.source if latest_price else None,
            reference_lookup_mode=market_profile.get("lookup_mode"),
            reference_price_fetched_at=latest_price.fetched_at if latest_price else None,
            rationale=rationale,
            created_at=now,
            updated_at=now,
        )
        db.add(position)
        db.flush()
        carried_holding = previous_holdings_by_product.get(best.id)
        if carried_holding:
            db.add(
                RecommendationHolding(
                    id=new_uuid(),
                    run_id=run.id,
                    recommendation_position_id=position.id,
                    product_id=best.id,
                    depot_bank=carried_holding.depot_bank,
                    custody_account_number=carried_holding.custody_account_number,
                    as_of_date=carried_holding.as_of_date,
                    units_milli=carried_holding.units_milli,
                    market_value_rappen=carried_holding.market_value_rappen,
                    avg_cost_price_rappen=carried_holding.avg_cost_price_rappen,
                    source=carried_holding.source,
                    notes=carried_holding.notes,
                    created_at=now,
                    updated_at=now,
                )
            )
        price_date = parse_iso_date(latest_price.price_date) if latest_price else None
        price_age_days = (today - price_date).days if price_date else None
        price_is_fresh = bool(price_age_days is not None and price_age_days <= int(market_data_quality.get("stale_after_days") or 5))
        positions_payload.append(
            {
                "id": position.id,
                "run_id": run.id,
                "product_id": best.id,
                "product_name": best.product_name,
                "provider": best.provider,
                "isin": best.isin or market_profile.get("isin"),
                "symbol": best.symbol or market_profile.get("symbol"),
                "figi": best.figi,
                "exchange_code": best.exchange_code,
                "mapping_provider": best.mapping_provider,
                "mapping_resolved_at": best.mapping_resolved_at,
                "reference_data_provider": best.reference_data_provider,
                "reference_data_refreshed_at": best.reference_data_refreshed_at,
                "lookup_symbol": market_profile.get("lookup_symbol"),
                "lookup_mode": market_profile.get("lookup_mode"),
                "pricing_note": market_profile.get("pricing_note"),
                "product_type": best.product_type,
                "asset_class": best.asset_class,
                "sub_asset_class": best.sub_asset_class,
                "source_sub_asset_classes": source_subs,
                "currency": best.currency,
                "ter_bps": best.ter_bps,
                "target_weight_bps": position.target_weight_bps,
                "target_amount_rappen": position.target_amount_rappen,
                "rationale": position.rationale,
                "reference_price_date": position.reference_price_date,
                "reference_price_rappen": position.reference_price_rappen,
                "reference_price_source": position.reference_price_source,
                "reference_lookup_mode": position.reference_lookup_mode,
                "reference_price_fetched_at": position.reference_price_fetched_at,
                "reference_recalibrated": None,
                "latest_price_date": latest_price.price_date if latest_price else None,
                "latest_price_rappen": int(latest_price.price_rappen or 0) if latest_price else None,
                "price_source": latest_price.source if latest_price else None,
                "price_age_days": price_age_days,
                "price_is_fresh": price_is_fresh if latest_price else None,
                "holding_present": False,
                "holding_source": None,
                "holding_as_of_date": None,
                "holding_units_milli": None,
                "current_units_milli": None,
                "holding_market_value_rappen": None,
                "holding_avg_cost_price_rappen": None,
                "holding_depot_bank": None,
                "holding_custody_account_number": None,
                "holding_notes": None,
                "valuation_basis": None,
                "implied_units_milli": None,
                "current_market_value_rappen": None,
                "current_weight_bps": None,
                "delta_weight_bps": None,
                "rebalance_amount_rappen": None,
                "price_change_bps": None,
                "rebalance_action": None,
                "rebalance_action_code": None,
                "rebalance_action_label": None,
            }
        )

    live_rebalancing = build_live_rebalancing_payload(
        db=db,
        allocation=allocation,
        run=run,
        advisory_wealth_rappen=investable_advisory_wealth_rappen,
    )
    live_positions_by_id = {
        item["id"]: item for item in ((live_rebalancing or {}).get("position_drifts") or [])
    }
    for item in positions_payload:
        live_position = live_positions_by_id.get(item["id"]) or {}
        if not live_position:
            continue
        item["reference_price_date"] = live_position.get("reference_price_date")
        item["reference_price_rappen"] = live_position.get("reference_price_rappen")
        item["reference_recalibrated"] = live_position.get("reference_recalibrated")
        item["holding_present"] = bool(live_position.get("holding_present"))
        item["holding_source"] = live_position.get("holding_source")
        item["holding_as_of_date"] = live_position.get("holding_as_of_date")
        item["holding_units_milli"] = live_position.get("holding_units_milli")
        item["current_units_milli"] = live_position.get("current_units_milli")
        item["holding_market_value_rappen"] = live_position.get("holding_market_value_rappen")
        item["holding_avg_cost_price_rappen"] = live_position.get("holding_avg_cost_price_rappen")
        item["holding_depot_bank"] = live_position.get("holding_depot_bank")
        item["holding_custody_account_number"] = live_position.get("holding_custody_account_number")
        item["holding_notes"] = live_position.get("holding_notes")
        item["valuation_basis"] = live_position.get("valuation_basis")
        item["implied_units_milli"] = live_position.get("implied_units_milli")
        item["current_market_value_rappen"] = live_position.get("current_market_value_rappen")
        item["current_weight_bps"] = live_position.get("current_weight_bps")
        item["delta_weight_bps"] = live_position.get("delta_weight_bps")
        item["rebalance_amount_rappen"] = live_position.get("rebalance_amount_rappen")
        item["price_change_bps"] = live_position.get("price_change_bps")
        item["rebalance_action"] = live_position.get("rebalance_action")
        item["rebalance_action_code"] = live_position.get("rebalance_action_code")
        item["rebalance_action_label"] = live_position.get("rebalance_action_label")

    avg_ter_bps = _average_ter_bps(positions_payload)
    missing_ter_count = _missing_ter_positions_count(positions_payload)
    ter_coverage_bps = _ter_coverage_bps(positions_payload)
    if missing_ter_count:
        warnings.append(
            f"TER fehlt fuer {missing_ter_count} Position(en); Durchschnittskosten basieren nur auf bekannter TER-Abdeckung."
        )
    return {
        "run": run,
        "positions": positions_payload,
        "warnings": warnings,
        "implementation_steps": _implementation_steps(target_payload["buckets"], investable_advisory_wealth_rappen),
        "advisory_wealth_rappen": advisory_wealth_rappen,
        "investable_advisory_wealth_rappen": investable_advisory_wealth_rappen,
        "expected_return_bps": int(target_payload["expected_return_bps"]),
        "expected_volatility_bps": int(target_payload["expected_volatility_bps"]),
        "average_ter_bps": avg_ter_bps,
        "average_ter_coverage_bps": ter_coverage_bps,
        "missing_ter_positions_count": missing_ter_count,
        "target_allocation_id": allocation.id,
        "context_status": "draft_current",
        "market_data_quality": market_data_quality,
        "live_rebalancing": live_rebalancing,
    }
