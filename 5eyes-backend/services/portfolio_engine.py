import json
import hashlib
import logging
import math
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import SimpleNamespace

logger = logging.getLogger(__name__)

from sqlalchemy.orm import Session

from config import settings
from database import new_uuid
from models.allocation import (
    BuildingBlock,
    CapitalMarketAssumption,
    HouseMatrix,
    OptimizerPolicy,
    OptimizerRun,
    TargetAllocation,
)
from models.jurisdiction import JurisdictionProfile
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.review import (
    PriceHistory,
    Product,
    ProductSuitability,
    ProductUniverseEntry,
    RecommendationHolding,
    RecommendationPosition,
    RecommendationRun,
)
from models.wealth import Cashflow, Goal, PlanningAssumption, WealthInflow, WealthPosition
from price_updater import latest_price_snapshot, parse_iso_date, summarize_price_quality
from services.allocation_messages import WARN_FALLBACK, classify_messages, format_message
from services.cashflow_timeline import (
    future_value_with_cashflow_series,
    net_cashflow_series,
    normalize_frequency,
    recurring_net_cashflow_series,
    totals_for_year,
)
from services.wealth_cashflows import derive_wealth_cashflows, mortgage_interest_adjustment_series
from services.product_market_data import resolve_market_profile, validate_default_product_market_coverage
from services.planning_horizon import life_expectancy_year_for
from services.jurisdiction.de_seed import (
    DE_DEFAULT_BONDS_DURATION,
    DE_DEFAULT_EQUITIES_GEO,
    DE_DEFAULT_REALESTATE_MARKET,
)
from services.jurisdiction.exceptions import JurisdictionReferenceDataMissingError
from services.jurisdiction.resolve import (
    resolve_building_blocks_for_jurisdiction,
    resolve_cma_for_jurisdiction,
    resolve_home_bias_defaults,
    resolve_mandate_jurisdiction,
)
from services.risk_matrix import (
    RiskBudgetExceeded,
    assert_risk_budget_ok,
    bucket_risky_fraction_bps_from_building_blocks,
    classify_limiting_factor,
    compute_portfolio_risky_fraction_bps,
)


BUCKET_FIELDS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")
BUCKET_LABELS = {
    "equities": "Aktien",
    "bonds": "Obligationen",
    "real_estate": "Immobilien",
    "alternatives": "Alternative",
    "liquidity": "Liquiditaet",
}
# Maximale strategische Liquiditaetsquote im SAA. Alles darueber wird extern empfohlen.
_SAA_LIQUIDITY_HARD_CAP_BPS: int = 300  # 3% Soll-Maximum (Stufe 2 der Eskalation)
_SAA_LIQUIDITY_EMERGENCY_CAP_BPS: int = 1000  # 10% absolutes Maximum (Stufe 3, mit Warnung)

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
# Sprint U-P1 Fix C4: Default-Sample erhoeht von 750 auf 2500. Bei N=750
# liegt der Standardfehler des 5%-Quantils (VaR/CVaR) bei ca. ±1.5 %-Pkt;
# bei N=2500 reduziert er sich auf ~±0.8 %-Pkt — WM-Standard.
DEFAULT_MONTE_CARLO_SIMULATIONS = 2500
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


_REQUIRED_RISK_QUESTION_NUMBERS_FOR_STRATEGY = frozenset(range(1, 12))
_CURRENT_RISK_ANSWER_POINTS = {
    1: {0},
    2: {0},
    3: {0, 1, 2, 3, 4},
    4: {0},
    5: {0, 1, 2, 3, 4},
    6: {0, 3, 6, 9, 12},
    7: {0, 3, 6, 9, 12},
    8: {0},
    9: {1, 2, 3, 4},
    10: {1, 2, 3, 4},
    11: {1, 2, 3, 4},
}
_CURRENT_RISK_HORIZON_LABELS = (
    "bis 2 jahre",
    "2 bis 3 jahre",
    "3 bis 5 jahre",
    "4 bis 5 jahre",
    "5 bis 7 jahre",
    "6 bis 7 jahre",
    "8 bis 11 jahre",
    "mehr als 12 jahre",
)


def _risk_json_field_is_type(raw, expected_type: type) -> bool:
    if raw is None:
        return False
    try:
        return isinstance(json.loads(str(raw)), expected_type)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def _risk_assessment_has_current_schema_markers(assessment: RiskAssessment) -> bool:
    return (
        _risk_json_field_is_type(getattr(assessment, "knowledge_services_json", None), dict)
        and _risk_json_field_is_type(getattr(assessment, "knowledge_instruments_json", None), dict)
        and _risk_json_field_is_type(getattr(assessment, "income_sources_json", None), list)
    )


def _risk_answer_text(answer) -> str:
    return _norm_text(getattr(answer, "answer_label", "")).strip().lower()


def _risk_answer_points(answer) -> int | None:
    try:
        return int(getattr(answer, "answer_points", None))
    except (TypeError, ValueError):
        return None


def _risk_answer_matches_current_questionnaire(question_number: int, answer) -> bool:
    text = _risk_answer_text(answer)
    if not text:
        return False
    points = _risk_answer_points(answer)
    if points not in _CURRENT_RISK_ANSWER_POINTS.get(question_number, set()):
        return False
    if question_number == 1:
        return text.startswith("finanzdienstleistungen:")
    if question_number == 2:
        return text.startswith("finanzinstrumente:")
    if question_number in (3, 5, 6):
        return "chf" in text
    if question_number == 4:
        return text.startswith("herkunft:")
    if question_number == 7:
        return "%" in text
    if question_number == 8:
        return "matrix" in text and any(label in text for label in _CURRENT_RISK_HORIZON_LABELS)
    if question_number == 9:
        return any(marker in text for marker in ("kapital", "kaufkraft", "vermehren", "wachstum"))
    if question_number == 10:
        return "risiko" in text or "wertschwankung" in text or "rendite" in text
    if question_number == 11:
        return "verlust" in text or "verkaufen" in text or "schwankung" in text
    return False


def _risk_assessment_has_current_questionnaire_answers(assessment: RiskAssessment) -> bool:
    answers = getattr(assessment, "answers", None) or []
    answers_by_number = {}
    for answer in answers:
        try:
            question_number = int(getattr(answer, "question_number", 0) or 0)
        except (TypeError, ValueError):
            continue
        if question_number:
            answers_by_number[question_number] = answer
    if not _REQUIRED_RISK_QUESTION_NUMBERS_FOR_STRATEGY.issubset(answers_by_number):
        return False
    return all(
        _risk_answer_matches_current_questionnaire(question_number, answers_by_number[question_number])
        for question_number in _REQUIRED_RISK_QUESTION_NUMBERS_FOR_STRATEGY
    )


def _risk_override_profile_band(score_x10: int) -> int:
    score = max(1, min(10, int(round((score_x10 or 10) / 10))))
    if score <= 2:
        return 0
    if score <= 4:
        return 1
    if score <= 6:
        return 2
    if score <= 8:
        return 3
    if score == 9:
        return 4
    return 5


def _risk_assessment_has_documented_override(assessment: RiskAssessment) -> bool:
    if not getattr(assessment, "is_overridden", 0) or getattr(assessment, "override_score_x10", None) is None:
        return False
    if not str(getattr(assessment, "override_reason", "") or "").strip():
        return False
    try:
        override_score = int(getattr(assessment, "override_score_x10", 0) or 0)
        final_score = int(getattr(assessment, "final_score_x10", 0) or 0)
    except (TypeError, ValueError):
        return False
    if _risk_override_profile_band(override_score) - _risk_override_profile_band(final_score) < 2:
        return True
    return bool(getattr(assessment, "override_client_confirmed", 0)) and bool(
        getattr(assessment, "override_warning_delivered", 0)
    )


def risk_assessment_ready_for_strategy(assessment: RiskAssessment | None) -> bool:
    if not assessment:
        return False
    if assessment.final_score_x10 is None and assessment.override_score_x10 is None:
        return False
    if _risk_assessment_has_documented_override(assessment):
        return True
    return (
        _risk_assessment_has_current_schema_markers(assessment)
        and _risk_assessment_has_current_questionnaire_answers(assessment)
    )


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


def _allocation_snapshot_preferences(allocation: TargetAllocation | None) -> dict | None:
    if allocation is None:
        return None
    raw = getattr(allocation, "preferences_json", None)
    if not raw:
        return None
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _merge_mandate_defaults_into_prefs(prefs: dict, mandate) -> dict:
    """Sprint B1 (2026-05-07): persistierte Building-Block-Wahl pro Mandat als
    Fallback in die preferences mergen.

    Wenn der Aufrufer keine expliziten asset_class-/geo-prefs setzt, wird die
    Mandanten-Default-Wahl (default_building_blocks_json) genutzt. Explizite
    prefs ueberschreiben Mandanten-Defaults nicht (UI-Wahl ist authoritativ).
    """
    if mandate is None:
        return prefs
    raw = getattr(mandate, "default_building_blocks_json", None)
    if not raw:
        return prefs
    try:
        defaults = json.loads(raw)
        if not isinstance(defaults, dict):
            return prefs
    except (TypeError, ValueError):
        return prefs
    asset_keys = {
        "equitiesGeo", "bondsDuration", "realestateMarket",
        "altsGold", "altsLiquidAlts", "altsHedge", "altsPe", "altsCrypto",
        "bondsHighYield", "bondsEmerging", "equitiesSmid",
    }
    geo_keys = {"noEm"}
    asset_classes = dict(prefs.get("assetClasses") or {})
    geo = dict(prefs.get("geo") or {})
    for key, val in defaults.items():
        if key in asset_keys and key not in asset_classes:
            asset_classes[key] = val
        elif key in geo_keys and key not in geo:
            geo[key] = val
    return {**prefs, "assetClasses": asset_classes, "geo": geo}


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
    """3-Magnituden-Heuristik fuer Berater-Eingaben:
    |x| < 1   → fraction (0.05 → 500 bps)
    1 ≤|x|<100→ percent  (50 → 5000 bps)
    |x| ≥ 100 → bps direct (500 → 500)
    int wird immer als bps direkt interpretiert.
    """
    if value in (None, "", False):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        abs_v = abs(value)
        if abs_v < 1:
            return int(round(value * 10000))
        if abs_v < 100:
            return int(round(value * 100))
        return int(round(value))
    raw = str(value).replace("'", "").replace(" ", "").strip()
    if not raw:
        return None
    if "%" in raw:
        return _parse_bps_percent(raw)
    try:
        numeric = float(raw.replace(",", "."))
    except ValueError:
        return None
    abs_v = abs(numeric)
    if abs_v < 1:
        return int(round(numeric * 10000))
    if abs_v < 100:
        return int(round(numeric * 100))
    return int(round(numeric))


def _risk_score_bucket(assessment: RiskAssessment) -> int:
    # Sprint U-P0 Fix H14: explizit Fail wenn keine Bewertung vorhanden,
    # statt silent fallback auf Bucket 1 (Kapitalschutz). Der vorherige
    # Default (`score_x10 or 10` → Bucket 1) konnte unbemerkt extrem
    # konservative Strategien produzieren.
    score_x10 = assessment.override_score_x10 if assessment.is_overridden and assessment.override_score_x10 else assessment.final_score_x10
    if score_x10 is None:
        raise ValueError(
            "Risikoprofil-Score fehlt (final_score_x10 + override_score_x10 sind beide None). "
            "Bitte Risikoprofilierung abschliessen oder Override mit Begruendung setzen."
        )
    # Validierung 2026-06-11 (#AA-9): round-half-up statt Banker's-round() — sonst
    # bricht die Monotonie an .5-Grenzen (45->4 statt 5, 65->6 statt 7) und divergiert
    # vom Profil-Namen-Mapping (risk_scoring._profile_from_score nutzt floor(x+0.5)).
    # int(x+0.5) == floor(x+0.5) fuer positive Scores.
    return max(1, min(10, int(score_x10 / 10 + 0.5)))


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


def _convert_position_amount_to_target_currency(pos, fx_source, target_currency: str) -> int:
    """2026-07-27 (WealthPosition-FX-Fix): konvertiert pos.current_value_rappen
    zu target_currency -- 1:1 nach dem Vorbild von
    services.cashflow_timeline._convert_cf_amount_to_target_currency (Sprint B3).

    Wenn fx_source=None: Backwards-Compat-Pfad -- currency wird ignoriert,
    Betrag bleibt wie ist (alte Behavior, Aufrufer kennt FX nicht).

    Wenn fx_source gesetzt: liest pos.currency (default 'CHF'), konvertiert
    via FXRateSource.cross_rate. Unbekannte Currencies werden defensiv als
    target_currency behandelt (kein Crash).
    """
    raw_amount = int(getattr(pos, "current_value_rappen", 0) or 0)
    if raw_amount == 0 or fx_source is None:
        return raw_amount
    pos_currency = str(getattr(pos, "currency", "") or "CHF").upper().strip()
    if not pos_currency:
        pos_currency = "CHF"
    target = str(target_currency or "CHF").upper().strip()
    if pos_currency == target:
        return raw_amount
    try:
        rate = fx_source.cross_rate(pos_currency, target)
    except (ValueError, AttributeError):
        return raw_amount
    return int(round(raw_amount * float(rate)))


def _summarize_positions(
    positions: list[WealthPosition],
    fx_source=None,
    target_currency: str = "CHF",
) -> PortfolioSummary:
    amounts = {key: 0 for key in BUCKET_FIELDS}
    total_rappen = 0
    for pos in positions:
        value_rappen = _convert_position_amount_to_target_currency(pos, fx_source, target_currency)
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


# ADR-014 Schritt 2 (2026-08-02): Live-Rebalancing-Cluster (Payload-Bau Phase A)
# extrahiert nach services/portfolio_engine_live_rebalancing.py (0 Zeilen
# Fachlogik-Aenderung, Byte-fuer-Byte-Kopie der 17 Funktionskoerper).
# build_live_rebalancing_payload bleibt der oeffentliche Einstiegspunkt fuer
# die 3 Orchestrator-Call-Sites (generate_target_allocation,
# build_target_payload_from_allocation, generate_recommendation_run);
# _latest_holdings_by_product_for_mandate wird zusaetzlich direkt in
# generate_recommendation_run aufgerufen.
from services.portfolio_engine_live_rebalancing import (  # noqa: F401,E402
    _aligned_reference_price,
    _build_live_action_summary,
    _build_live_bucket_drifts,
    _build_live_bucket_targets,
    _build_live_position_drifts,
    _build_live_rebalancing_entry,
    _canonical_asset_class_label,
    _holdings_snapshot_for_run,
    _latest_holdings_by_product_for_mandate,
    _load_live_rebalancing_sources,
    _reference_price_snapshot_for_run,
    _rebalancing_action,
    _rebalancing_action_meta,
    _stored_reference_price_for_position,
    _units_milli_from_amount,
    _value_from_units_milli,
    build_live_rebalancing_payload,
)


def _building_block_risky_map(
    db: Session,
    policy_id: str,
    investment_universe: str | None = None,
    jurisdiction: str | None = "CH",
) -> dict[tuple[str, str], int]:
    """Sprint B4 (2026-05-07): respektiert mandate.investment_universe.

    Wenn ein Universum gewaehlt ist und BuildingBlocks fuer dieses Universum
    existieren, werden NUR diese geladen. Sonst Fallback auf alle aktiven BBs
    (backwards-compat fuer bestehende Mandate ohne explizite Universum-Wahl).

    WP-A (2026-08-01, Risky-Fraction-Gewichtung jurisdiktions-bewusst):
    jurisdiction wird 1:1 an _building_block_rows_for_policy() durchgereicht,
    siehe dort fuer die CH-vs-Nicht-CH-Semantik.
    """
    rows = _building_block_rows_for_policy(db, policy_id, investment_universe, jurisdiction)
    return {
        (_norm_text(row.asset_class), _norm_text(row.sub_asset_class)): int(row.risky_fraction_bps or 0)
        for row in rows
    }


def _building_block_rows_for_policy(
    db: Session,
    policy_id: str,
    investment_universe: str | None = None,
    jurisdiction: str | None = "CH",
) -> list[BuildingBlock]:
    """Laedt die aktiven BuildingBlock-Zeilen einer Policy fuer die
    Risky-Fraction-Gewichtung.

    WP-A (2026-08-01, Risky-Fraction-Gewichtung jurisdiktions-bewusst):
    - jurisdiction in (None, "CH") (Default, Constraint 1 der Welle):
      EXAKT die heutige Query/Fallback-Logik -- KEIN BuildingBlock.jurisdiction-
      Filter, byte-identisch zum Bestandsverhalten (Golden-Snapshot-Beweis).
    - andere jurisdiction: delegiert an
      services.jurisdiction.resolve.resolve_building_blocks_for_jurisdiction(),
      damit die dortige Fail-Fast-Semantik (leeres Ergebnis fuer diese
      Jurisdiktion+Policy -> JurisdictionReferenceDataMissingError statt
      stillschweigend 0 oder — schlimmer — CH+DE gemischte Gewichte) auch
      fuer die tatsaechliche Risky-Fraction-Berechnung gilt, nicht nur fuer
      die bisherige isolierte Validierung in ensure_runtime_reference_data().
    """
    if jurisdiction in (None, "CH"):
        base_query = db.query(BuildingBlock).filter(
            BuildingBlock.policy_id == policy_id,
            BuildingBlock.is_active == 1,
        )
        universe = (investment_universe or "").strip() or None
        rows = []
        if universe:
            rows = base_query.filter(BuildingBlock.universe == universe).all()
        if not rows:
            rows = base_query.all()
        return rows
    return resolve_building_blocks_for_jurisdiction(
        db, policy_id, jurisdiction, investment_universe=investment_universe,
    )


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
    allow_best_effort: bool = False,
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
        if allow_best_effort:
            # Validierung 2026-06-11 (#AA-1): strukturell unerreichbares Budget
            # (Mindestquoten lassen die Risky-Fraction nicht unter den Cap). Statt
            # hart zu werfen die konservativste ERREICHBARE Allokation zurueckgeben;
            # der Aufrufer (letzte Eskalationsstufe) behandelt die Ueberschreitung
            # graceful (Compliance-Warnung) statt die SAA-Generierung abzubrechen.
            return adjusted, current_risk
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
    "Gold / Rohstoffe": {"asset_class": "Alternative", "expected_return_bps": 120, "expected_volatility_bps": 1200},
    "Liquid Alternatives": {"asset_class": "Alternative", "expected_return_bps": 320, "expected_volatility_bps": 700},
    "Hedge Funds": {"asset_class": "Alternative", "expected_return_bps": 420, "expected_volatility_bps": 900},
    "Private Equity": {"asset_class": "Alternative", "expected_return_bps": 650, "expected_volatility_bps": 2200},
    "Krypto": {"asset_class": "Alternative", "expected_return_bps": 800, "expected_volatility_bps": 4500},
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

# WP2 (Engine-Wiring Jurisdiktion, 2026-07-31): der hartcodierte CH-Kontext
# fuer die chf_only-/Hedging-/Home-Bias-Produktfilter (siehe
# _product_matches_constraints, _product_score, _product_is_chf_or_fx_hedged
# und _resolve_jurisdiction_context()). Wird IMMER 1:1 fuer CH verwendet --
# das garantiert, dass die dortigen String-Vergleiche exakt "CHF"/"Schweiz"
# bleiben, unabhaengig von der DB (Constraint 1: CH-Pfad byte-identisch).
_CH_JURISDICTION_CONTEXT: dict[str, str] = {
    "jurisdiction": "CH",
    "home_currency": "CHF",
    "home_equity_label": "Schweiz",
}

# Bekannte Sub-Asset-Class-Label-Praefixe (siehe eq_splits/bond_splits/
# re_splits in _build_sub_allocations sowie services/jurisdiction/de_seed.py)
# -- verwendet von _bare_market_token(), um aus einem vollen Home-Bias-Label
# (z.B. "Aktien Deutschland") das reine Land/Markt-Token ("Deutschland")
# abzuleiten, analog zum CH-Bestandswert "Schweiz" (bare Token, matcht per
# Substring sowohl Aktien- als auch Immobilien-Sub-Klassen in _product_score).
_SUB_ASSET_CLASS_LABEL_PREFIXES = ("Aktien ", "Obligationen ", "Immobilien ")


def _resolve_jurisdiction_context(db: Session, mandate: Mandate, jurisdiction: str | None) -> dict:
    """WP2 (2026-07-31): kleiner, EINMAL pro generate_target_allocation()/
    generate_recommendation_run()-Lauf aufgeloester Kontext fuer die
    chf_only-/Hedging-/Home-Bias-Produktfilter (_product_matches_constraints,
    _product_score, _product_is_chf_or_fx_hedged).

    - jurisdiction in (None, "CH"): IMMER der hartcodierte _CH_JURISDICTION_
      CONTEXT (Constraint 1: CH-Pfad byte-identisch, unabhaengig vom DB-Inhalt).
    - andere jurisdiction: home_currency bevorzugt aus mandate.base_currency
      (die Mandats-Fuehrungswaehrung ist die naheliegendste, bereits
      vorhandene Quelle fuer "in welcher Waehrung ist dieses Mandat zuhause");
      ohne gesetzte base_currency Fallback auf
      JurisdictionProfile.home_currency (Stammdaten-Zeile der Jurisdiktion).
      home_equity_label: bare Markt-Token (siehe _bare_market_token()) aus
      _resolve_home_equity_label() -- z.B. "Deutschland".
    """
    if jurisdiction in (None, "CH"):
        return dict(_CH_JURISDICTION_CONTEXT)

    home_currency = str(getattr(mandate, "base_currency", None) or "").strip().upper()
    if not home_currency:
        profile = db.query(JurisdictionProfile).filter(
            JurisdictionProfile.code == jurisdiction,
        ).first()
        home_currency = str(getattr(profile, "home_currency", None) or "").strip().upper()
    if not home_currency:
        raise JurisdictionReferenceDataMissingError(
            f"Keine Heimwaehrung fuer Jurisdiktion '{jurisdiction}' ermittelbar "
            "(weder mandate.base_currency noch JurisdictionProfile.home_currency gesetzt)."
        )

    home_equity_label = _bare_market_token(_resolve_home_equity_label(db, jurisdiction))

    return {
        "jurisdiction": jurisdiction,
        "home_currency": home_currency,
        "home_equity_label": home_equity_label,
    }


# ADR-014 Schritt 7 (2026-08-02): Payload-Bau Phase B (Goal-Analyse-
# Formatierung + Produktselektion, 30 Namen) extrahiert nach
# services/portfolio_engine_payload.py (0 Zeilen Fachlogik-Aenderung,
# Byte-fuer-Byte-Kopie, per Diff-Skript verifiziert). _growth_goals_for_
# equity_tilt (House-Matrix, noch nicht extrahiert) sowie die Re-Export-
# Bloecke aus Schritt 3 (CMA) und Schritt 5 (MC-Simulation), die physisch
# zwischen diesen Funktionen liegen, bleiben unangetastet -- diese Extraktion
# wurde per AST-Funktions-Span-Analyse durchgefuehrt (nicht per Zeilennummer-
# Heuristik), um genau dieses Verschachtelungs-Risiko sicher zu handhaben.
# _goal_projection_years/_annualize_goal_amount/_parse_iso_date/
# _compute_goal_score/_goal_hardness_key/_goal_target_wealth_rappen werden
# bereits von den Schritten 4 (Reserve) und 5 (MC-Simulation) per Lazy-Import
# zurueckgeholt -- deren Ketten funktionieren nur, wenn ALLE hier gelistet sind.
from services.portfolio_engine_payload import (  # noqa: F401,E402
    _annualize_goal_amount,
    _average_ter_bps,
    _build_asset_class_assumptions,
    _build_bucket_response,
    _build_goal_analysis,
    _build_mandate_score,
    _build_sub_asset_class_assumption_reference,
    _compute_goal_score,
    _expected_death_year_offset_from_mandate,
    _filter_products_by_universe,
    _goal_hardness_key,
    _goal_projection_years,
    _goal_target_wealth_rappen,
    _goal_timing_label,
    _goal_weight,
    _implementation_steps,
    _inflate_real_goal_target_rappen,
    _items_with_known_ter,
    _merge_goal_analysis_with_monte_carlo,
    _missing_ter_positions_count,
    _parse_iso_date,
    _product_descriptor_text,
    _product_is_chf_or_fx_hedged,
    _product_is_derivative,
    _product_is_leveraged,
    _product_is_structured,
    _product_matches_constraints,
    _product_score,
    _ter_coverage_bps,
    _validate_recommendation_concentration_limits,
)



# ADR-014 Schritt 1: _build_total_wealth_allocation nach
# services/portfolio_engine_gesamtvermoegen.py verschoben. Re-Export siehe
# unten (nach _wealth_inflow_series_rappens vormaliger Position).




_GOAL_HARDNESS_MULTIPLIER_BPS = {
    "hart": 20000,
    "primaer": 10000,
    "opportunistisch": 4000,
}






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






# ADR-014 Schritt 3 (2026-08-02): CMA-Verarbeitung extrahiert nach
# services/portfolio_engine_cma.py (0 Zeilen Fachlogik-Aenderung,
# Byte-fuer-Byte-Kopie der 20 Funktionskoerper). _bare_market_token und
# _resolve_home_equity_label werden von _resolve_jurisdiction_context (CORE,
# bleibt hier) direkt aufgerufen -- funktioniert unveraendert dank Re-Export.
# _inflation_path_series wird zusaetzlich direkt importiert von
# routers/clients.py UND routers/wealth.py (calculate_max_pension_spending,
# zusammen mit _expected_metrics/_goal_inflation_series_bps); _weighted_bucket_metrics
# zusaetzlich von services/optimizer/scenario_engine.py -- beide Funde beim
# Draften dieses Schritts gemacht, nicht im urspruenglichen ADR-014 gelistet.
from services.portfolio_engine_cma import (  # noqa: F401,E402
    _apply_cma_market_adjustments,
    _asset_class_expected_metrics,
    _bare_market_token,
    _build_cholesky_from_cma,
    _bucket_expected_metrics,
    _cholesky,
    _cornish_fisher_transform,
    _crisis_stress_matrix,
    _expected_metrics,
    _goal_inflation_series_bps,
    _identity_cholesky,
    _inflation_path_series,
    _is_valid_cholesky,
    _portfolio_volatility_bps,
    _portfolio_weighted_ter_bps,
    _real_series_from_nominal,
    _resolve_home_equity_label,
    _sub_asset_class_assumption_map,
    _sub_asset_class_metrics,
    _weighted_bucket_metrics,
)






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












# ADR-014 Schritt 1: _goal_uses_total_scope + _external_assets_inflation_value
# nach services/portfolio_engine_gesamtvermoegen.py verschoben. Re-Export
# siehe unten (nach _wealth_inflow_series_rappens vormaliger Position).




# ADR-014 Schritt 5 (2026-08-02): MC-Simulation-Cluster (groesster Cluster,
# 28 Funktionen) extrahiert nach services/portfolio_engine_mc_simulation.py
# (0 Zeilen Fachlogik-Aenderung, Byte-fuer-Byte-Kopie, per Diff-Skript gegen
# das Original verifiziert). _goal_projection_years/_annualize_goal_amount/
# _goal_hardness_key (Payload-Bau, bleiben hier) werden von
# _monte_carlo_goal_summary weiterhin per Lazy-Import genutzt.
# _annualized_return_bps hat 0 interne Call-Sites (toter Code, abgeloest
# durch _twr_annualized_bps), bleibt aber im Re-Export fuer 2 Tests, die sie
# direkt importieren.
from services.portfolio_engine_mc_simulation import (  # noqa: F401,E402
    _annualized_return_bps,
    _apply_cashflow_to_bucket_values,
    _build_simulation_payload,
    _conditional_percentile_average,
    _full_goal_duration_years,
    _goal_duration_years,
    _loss_bps,
    _max_drawdown_bps,
    _monte_carlo_goal_summary,
    _monte_carlo_seed,
    _monte_carlo_simulations,
    _percentile,
    _rebalance_bucket_values_to_targets,
    _return_bps,
    _run_allocation_monte_carlo,
    _sequence_of_returns_depletion,
    _simulate_bucket_path,
    _simulation_crisis_strength,
    _simulation_horizon_years,
    _simulation_rebalance_mode,
    _simulation_stress_multiplier,
    _simulation_transaction_cost_bps,
    _simulation_use_tail_risk,
    _stddev_bps,
    _target_bucket_values,
    _twr_annualized_bps,
    _weights_from_bucket_values,
    _year_index_for_goal,
)




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


def _preference_choice(value, fallback: str) -> str:
    """Normalisiert UI- und Legacy-Werte auf die internen ASCII-Vergleiche."""
    raw = value if value not in (None, "") else fallback
    return _norm_text(raw).strip()


def _build_sub_allocations(
    targets: dict[str, int],
    preferences: dict,
    jurisdiction: str = "CH",
    db: Session | None = None,
) -> list[dict]:
    """Baut die Sub-Allokation (Sub-Asset-Class-Gewichte) aus Bucket-Targets +
    Anlagepraeferenzen.

    WP2 (Engine-Wiring Jurisdiktion, 2026-07-31): jurisdiction in (None, "CH")
    verwendet unveraendert die hartcodierten CH-Home-Bias-Splits (Constraint 1:
    CH-Pfad byte-identisch). Fuer andere jurisdiction kommen die Home-Bias-
    Splits stattdessen aus resolve_home_bias_defaults() (services/jurisdiction/
    resolve.py) -- dafuer wird zusaetzlich ein db-Parameter benoetigt (siehe
    ValueError unten, falls db fehlt).

    Die generischen Filter (geo_prefs.noEm, overweight_tilts, bondsHighYield/
    Emerging) operieren auf den literalen Sub-Asset-Class-Labels "Aktien
    Schwellenlaender" / "Aktien Global" / "Obligationen High Yield" /
    "Obligationen Emerging" -- diese Labels sind laut services/jurisdiction/
    de_seed.py bewusst IDENTISCH fuer CH und DE (nur die Heimmarkt-Labels
    "Aktien Schweiz"/"Obligationen CHF IG"/"Obligationen Global Hedged"/
    "Immobilien Schweiz" wurden fuer DE uebersetzt) -- die Filter bleiben also
    OHNE Aenderung generisch fuer beide Jurisdiktionen anwendbar. Die zwei
    Stellen, die tatsaechlich ein CH-spezifisches Heimmarkt-Label hartcodieren
    (equities_smid-Satellit "Aktien Schweiz", IG-Bond-Filter "Obligationen CHF
    IG"/"Obligationen Global Hedged") werden daher pro Jurisdiktion getrennt
    aufgebaut (siehe Kommentare unten).
    """
    prefs = _normalize_preferences(preferences)
    asset_prefs = prefs["assetClasses"]
    geo_prefs = prefs["geo"]
    tilts = prefs["tilts"]
    sub_allocations: list[dict] = []
    is_ch = jurisdiction in (None, "CH")
    if not is_ch and db is None:
        raise ValueError(
            "_build_sub_allocations() braucht fuer jurisdiction != 'CH' einen "
            "db-Parameter (fuer resolve_home_bias_defaults())."
        )

    def _flag_enabled(name: str, default: bool = False) -> bool:
        value = asset_prefs.get(name)
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() not in ("", "0", "false", "nein", "no", "off")
        return bool(value)

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

    equities_large_cap = _flag_enabled("equitiesLargeCap", True)
    equities_smid = _flag_enabled("equitiesSmid", False)
    if targets["equities"] > 0 and not equities_large_cap:
        if equities_smid:
            raise ValueError(
                "Anlagepraeferenzen nicht umsetzbar: Aktien Large Cap ist ausgeschaltet, "
                "aber das aktuelle strategische Universum enthaelt nur einen Small-/Mid-Cap-Satelliten. "
                "Bitte Large Cap aktivieren oder ein vollstaendiges Small-/Mid-Cap-Universum hinterlegen."
            )
        raise ValueError(
            "Anlagepraeferenzen unvollstaendig: Bei Aktien muss mindestens ein Segment aktiv sein."
        )

    if is_ch:
        equities_geo = _preference_choice(asset_prefs.get("equitiesGeo"), "Schweiz Fokus")
        if geo_prefs.get("noEm") and equities_geo == "Schwellenlaender":
            raise ValueError(
                "Anlagepraeferenzen widerspruechlich: Schwellenlaender-Fokus ist gewaehlt, "
                "aber Kein EM-Exposure ist aktiv."
            )
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
        if equities_smid:
            for idx, item in enumerate(eq_splits):
                if item[0] == "Aktien Schweiz":
                    eq_splits[idx] = (item[0], max(0, item[1] - 1000), item[2])
                    eq_splits.append(("Aktien Schweiz Small/Mid", 1000, "Mandatierter Small-/Mid-Cap-Baustein"))
                    break
    else:
        # Nicht-CH (WP2, 2026-07-31): Home-Bias-Splits kommen 1:1 aus
        # resolve_home_bias_defaults() (services/jurisdiction/resolve.py) --
        # KEINE erfundenen Zahlen, siehe services/jurisdiction/de_seed.py fuer
        # die DE-Seed-Werte (mechanische CH-Spiegelung, is_provisional=1).
        equities_geo = _preference_choice(asset_prefs.get("equitiesGeo"), DE_DEFAULT_EQUITIES_GEO)
        if geo_prefs.get("noEm") and equities_geo == "Schwellenlaender":
            raise ValueError(
                "Anlagepraeferenzen widerspruechlich: Schwellenlaender-Fokus ist gewaehlt, "
                "aber Kein EM-Exposure ist aktiv."
            )
        eq_splits = list(resolve_home_bias_defaults(db, jurisdiction, "equitiesGeo", equities_geo))
        # Heimmarkt-Label fuer den Small/Mid-Satelliten unten: staerkstes Label
        # der equitiesGeo-DEFAULT-Variante (siehe _resolve_home_equity_label()
        # Docstring fuer die Begruendung dieser pragmatischen Wahl).
        home_equity_label = _resolve_home_equity_label(db, jurisdiction)
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
        if equities_smid:
            for idx, item in enumerate(eq_splits):
                if item[0] == home_equity_label:
                    eq_splits[idx] = (item[0], max(0, item[1] - 1000), item[2])
                    eq_splits.append((f"{home_equity_label} Small/Mid", 1000, "Mandatierter Small-/Mid-Cap-Baustein"))
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
        # #AA-7 Fix (2026-06-12): eq_splits leben im Per-Bucket-Raum (sie summieren
        # zu 10000 und werden in _append_split renormalisiert). Der Theme-Tilt muss
        # daher relativ zu 10000 statt zur Portfolio-Aktienquote targets["equities"]
        # definiert werden — sonst haengt die EFFEKTIVE Themen-Gewichtung von der
        # Aktienquote des Risikoprofils ab (eq=8000 -> ~12%, eq=2000 -> ~3%), statt
        # konsistent zu sein. Cap 1200 (= 12% des Aktien-Buckets) bleibt die Obergrenze.
        theme_total = min(int(round(10000 * 0.15)), 1200)
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

    if geo_prefs.get("noEm") and asset_prefs.get("bondsEmerging"):
        raise ValueError(
            "Anlagepraeferenzen widerspruechlich: Obligationen Emerging Markets ist aktiv, "
            "aber Kein EM-Exposure ist aktiv."
        )
    if is_ch:
        bonds_duration = _preference_choice(asset_prefs.get("bondsDuration"), "Langfristig")
        if bonds_duration == "Kurzfristig":
            bond_splits = [("Obligationen CHF IG", 7000, "Kurzfristige CHF-Qualitaet"), ("Obligationen Global Hedged", 2500, "Ergaenzende Diversifikation"), ("Obligationen High Yield", 300, "Renditebeimischung"), ("Obligationen Emerging", 200, "Diversifikation")]
        elif bonds_duration == "Gemischt":
            bond_splits = [("Obligationen CHF IG", 6000, "Gemischter CHF-Kern"), ("Obligationen Global Hedged", 3000, "Globale Diversifikation"), ("Obligationen High Yield", 500, "Renditebeimischung"), ("Obligationen Emerging", 500, "Diversifikation")]
        else:
            bond_splits = [("Obligationen CHF IG", 5500, "Langfristiger CHF-Kern"), ("Obligationen Global Hedged", 3500, "Globale Diversifikation"), ("Obligationen High Yield", 500, "Renditebeimischung"), ("Obligationen Emerging", 500, "Diversifikation")]
        if not _flag_enabled("bondsInvestmentGrade", True):
            bond_splits = [item for item in bond_splits if item[0] not in ("Obligationen CHF IG", "Obligationen Global Hedged")]
    else:
        # Nicht-CH (WP2, 2026-07-31): siehe eq_splits-Kommentar oben. Fuer den
        # bondsInvestmentGrade-Filter gibt es KEIN generisches, jurisdiktions-
        # unabhaengiges Home-IG-Label (die DE-Labels "Obligationen EUR IG"/
        # "Obligationen Global EUR-Hedged" unterscheiden sich bewusst von den
        # CH-Labels). Generalisierung (dokumentierte, pragmatische Wahl): die
        # beiden NICHT-Home-Sleeves "Obligationen High Yield"/"Obligationen
        # Emerging" sind laut de_seed.py IMMER identisch benannt -- daher wird
        # bondsInvestmentGrade=aus stattdessen als "behalte nur HY/EM-Sleeves"
        # ausgedrueckt (Komplement derselben Filterwirkung wie im CH-Zweig).
        bonds_duration = _preference_choice(asset_prefs.get("bondsDuration"), DE_DEFAULT_BONDS_DURATION)
        bond_splits = list(resolve_home_bias_defaults(db, jurisdiction, "bondsDuration", bonds_duration))
        if not _flag_enabled("bondsInvestmentGrade", True):
            bond_splits = [
                item for item in bond_splits
                if item[0] in ("Obligationen High Yield", "Obligationen Emerging")
            ]
    if not _flag_enabled("bondsHighYield", False):
        bond_splits = [item for item in bond_splits if item[0] != "Obligationen High Yield"]
    if not _flag_enabled("bondsEmerging", False) or geo_prefs.get("noEm"):
        bond_splits = [item for item in bond_splits if item[0] != "Obligationen Emerging"]
    if targets["bonds"] > 0 and not bond_splits:
        raise ValueError(
            "Anlagepraeferenzen unvollstaendig: Die Obligationen-Auswahl schliesst alle "
            "umsetzbaren Segmente aus. Bitte Investment Grade, High Yield oder Emerging Markets aktivieren."
        )
    _append_split("Obligationen", targets["bonds"], bond_splits)

    realestate_funds = _flag_enabled("realestateFunds", True)
    realestate_direct = _flag_enabled("realestateDirect", False)
    if targets["real_estate"] > 0:
        if not realestate_funds and not realestate_direct:
            raise ValueError(
                "Anlagepraeferenzen unvollstaendig: Bei Immobilien muss Fonds/REIT oder Direkt aktiv sein."
            )
        if realestate_direct and not realestate_funds:
            raise ValueError(
                "Anlagepraeferenzen nicht umsetzbar: Direktimmobilien-only kann im aktuellen "
                "produktiven Beratungsuniversum nicht als handelbare Zielallokation umgesetzt werden."
            )

    if is_ch:
        realestate_market = _preference_choice(asset_prefs.get("realestateMarket"), "Schweiz")
        if realestate_market == "Ausland":
            re_splits = [("Immobilien Global", 7000, "Auslandsfokus fuer Immobilien"), ("Immobilien Schweiz", 3000, "Heimmarkt-Stabilisator")]
        elif realestate_market == "Gemischt":
            re_splits = [("Immobilien Schweiz", 5000, "Gemischter Immobilienbaustein"), ("Immobilien Global", 5000, "Gemischter Immobilienbaustein")]
        else:
            re_splits = [("Immobilien Schweiz", 8000, "Schweizer Immobilienfokus"), ("Immobilien Global", 2000, "Ergaenzende Diversifikation")]
    else:
        # Nicht-CH (WP2, 2026-07-31): siehe eq_splits-Kommentar oben.
        realestate_market = _preference_choice(asset_prefs.get("realestateMarket"), DE_DEFAULT_REALESTATE_MARKET)
        re_splits = list(resolve_home_bias_defaults(db, jurisdiction, "realestateMarket", realestate_market))
    if realestate_direct:
        re_splits = [
            (label, bps, rationale + "; Direktimmobilien werden ueber das Gesamtvermoegen beruecksichtigt")
            for label, bps, rationale in re_splits
        ]
    _append_split("Immobilien", targets["real_estate"], re_splits)

    alt_splits = []
    explicit_alt_keys = {"altsGold", "altsLiquidAlts", "altsHedge", "altsPe", "altsCrypto"}.intersection(asset_prefs.keys())
    if _flag_enabled("altsGold", False):
        alt_splits.append(("Gold / Rohstoffe", 4000, "Stabilisierender Sachwertbaustein"))
    if _flag_enabled("altsLiquidAlts", False):
        alt_splits.append(("Liquid Alternatives", 2000, "Diversifizierende Alternative"))
    if _flag_enabled("altsHedge", False):
        alt_splits.append(("Hedge Funds", 1500, "Alternative Renditequelle"))
    if _flag_enabled("altsPe", False):
        alt_splits.append(("Private Equity", 1500, "Illiquider Wachstumsbaustein"))
    if _flag_enabled("altsCrypto", False):
        alt_splits.append(("Krypto", 1000, "Satellit gemaess Mandatsvorgabe"))
    if not alt_splits:
        if targets["alternatives"] > 0 and explicit_alt_keys:
            raise ValueError(
                "Anlagepraeferenzen unvollstaendig: Bei Alternativen Anlagen muss mindestens "
                "ein Instrument aktiv sein."
            )
        alt_splits.append(("Gold / Rohstoffe", 10000, "Standardbaustein fuer Alternative Anlagen"))
    _append_split("Alternative", targets["alternatives"], alt_splits)

    liquidity_label = asset_prefs.get("liquidityInstrument") or "Geldmarktfonds"
    _append_split("Liquiditaet", targets["liquidity"], [(liquidity_label, 10000, "Liquiditaetsreserve gemaess Mandatsvorgabe")])
    return sub_allocations


# 3eyes-Methodik (drei augen.pdf): Illiquiditaet ist eine Eigenschaft des
# Bausteins, kein pauschaler Alternatives-Deckel. Direktimmobilien werden
# bereits ueber das Gesamtvermoegen (extern) gefuehrt und nicht umgeschichtet;
# der einzige illiquide Baustein INNERHALB der handelbaren SAA ist Private Equity.
_ILLIQUID_SUB_ASSET_CLASSES = {"private equity"}


def _apply_illiquid_cap(
    sub_allocations: list[dict],
    targets: dict[str, int],
    max_illiquid_bps: int | None,
    reasoning: list[str],
) -> tuple[list[dict], dict[str, int]]:
    """Deckelt den ECHT illiquiden Anteil (Private Equity) auf max_illiquid_bps.

    Methodik-konform (3eyes): nur der illiquide Baustein wird reduziert, nicht
    die ganze Alternatives-Quote. Der freiwerdende Anteil wird primaer innerhalb
    der Alternativen zu liquiden Sleeves (Gold, Liquid Alts, ...) verschoben — die
    Alternatives-Quote bleibt dann unveraendert, nur ihre Zusammensetzung wird
    liquider. Gibt es keinen liquiden Alt-Sleeve, wandert der Rest in die Liquiditaet.
    """
    if max_illiquid_bps is None:
        return sub_allocations, targets
    illiquid = [
        sub for sub in sub_allocations
        if _norm_text(sub.get("sub_asset_class")).strip().lower() in _ILLIQUID_SUB_ASSET_CLASSES
    ]
    illiquid_bps = sum(int(sub.get("target_weight_bps") or 0) for sub in illiquid)
    if illiquid_bps <= max_illiquid_bps or illiquid_bps <= 0:
        return sub_allocations, targets

    freed = 0
    scale = max_illiquid_bps / illiquid_bps
    for sub in illiquid:
        old = int(sub.get("target_weight_bps") or 0)
        new = int(round(old * scale))
        freed += old - new
        sub["target_weight_bps"] = new
    if freed <= 0:
        return sub_allocations, targets

    liquid_alts = [
        sub for sub in sub_allocations
        if _norm_text(sub.get("asset_class")) == _norm_text("Alternative")
        and _norm_text(sub.get("sub_asset_class")).strip().lower() not in _ILLIQUID_SUB_ASSET_CLASSES
    ]
    if liquid_alts:
        # Innerhalb der Alternativen umschichten: PE -> liquide Sleeves. Alternatives-Quote bleibt.
        receiver = max(liquid_alts, key=lambda s: int(s.get("target_weight_bps") or 0))
        receiver["target_weight_bps"] = int(receiver.get("target_weight_bps") or 0) + freed
        reasoning.append(
            "Mandatsgrenze fuer illiquide Anlagen: Private Equity gedeckelt, "
            "freiwerdender Anteil innerhalb der Alternativen zu liquiden Bausteinen verschoben."
        )
    else:
        # Kein liquider Alt-Sleeve vorhanden -> raus aus Alternativen in die Liquiditaet.
        targets["alternatives"] = max(0, int(targets["alternatives"]) - freed)
        targets["liquidity"] = int(targets["liquidity"]) + freed
        liq_sub = next(
            (s for s in sub_allocations if _norm_text(s.get("asset_class")) == _norm_text("Liquiditaet")),
            None,
        )
        if liq_sub is not None:
            liq_sub["target_weight_bps"] = int(liq_sub.get("target_weight_bps") or 0) + freed
        else:
            sub_allocations.append({
                "asset_class": "Liquiditaet",
                "sub_asset_class": "Geldmarktfonds",
                "target_weight_bps": freed,
                "rationale": "Liquiditaetsreserve nach Deckelung illiquider Anlagen",
            })
        reasoning.append(
            "Mandatsgrenze fuer illiquide Anlagen: Private Equity gedeckelt, "
            "freiwerdender Anteil in die Liquiditaet umgeschichtet (kein liquider Alternativ-Baustein aktiv)."
        )
    return sub_allocations, targets


def _house_matrix_or_default(db: Session, policy: OptimizerPolicy, score_bucket: int) -> HouseMatrix:
    hm = db.query(HouseMatrix).filter(
        HouseMatrix.policy_id == policy.id,
        HouseMatrix.score_from <= score_bucket,
        HouseMatrix.score_to >= score_bucket,
        HouseMatrix.is_active == 1,
    ).first()
    if hm:
        return hm
    raise ValueError(f"HouseMatrix unvollstaendig fuer Score {score_bucket}")


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


def ensure_runtime_reference_data(
    db: Session,
    user_id: str,
    jurisdiction: str = "CH",
    tenant_id: str | None = None,
) -> tuple[OptimizerPolicy, CapitalMarketAssumption]:
    """Stellt Policy/House-Matrix/BuildingBlocks/CMA fuer die Engine bereit.

    WP2 (Engine-Wiring Jurisdiktion, 2026-07-31):
    - jurisdiction in (None, "CH"): EXAKT das heutige Verhalten (siehe
      _ensure_runtime_reference_data_ch()) -- seedet die CH-Default-Policy/
      -House-Matrix/-BuildingBlocks/-CMA, falls noch nicht vorhanden
      (Constraint 1: CH-Pfad byte-identisch).
    - andere jurisdiction: es wird bewusst NICHTS geseedet (kein
      automatischer CH-Fondskatalog/-CMA fuer eine neue Jurisdiktion).
      policy bleibt die globale, jurisdiktionsunabhaengige OptimizerPolicy
      (es gibt in dieser Ausbaustufe keine jurisdiktionseigene Policy/
      House-Matrix -- explizit ausserhalb des Scopes dieses Arbeitspakets,
      siehe Abschlussbericht). Existiert noch keine globale Policy (z.B.
      weil noch nie ein CH-Mandat verarbeitet wurde), ist das ein
      Bootstrap-Fehler, den wir NICHT mit einer erfundenen Policy
      uebertuenchen. cma kommt aus resolve_cma_for_jurisdiction()
      (require_committee_approved=False -- die Provisorik-Kennzeichnung
      erfolgt separat, siehe generate_recommendation_run()::
      provisional_data_warning). resolve_building_blocks_for_jurisdiction()
      wird zusaetzlich als Fail-Fast-Validierung aufgerufen (wirft
      JurisdictionReferenceDataMissingError, wenn fuer diese Jurisdiktion+
      Policy keine BuildingBlock-Referenzzeilen existieren) -- ihr
      Rueckgabewert ist NICHT Teil der Rueckgabe dieser Funktion.

      WP-A (2026-08-01, Risky-Fraction-Gewichtung jurisdiktions-bewusst):
      _building_block_rows_for_policy()/_building_block_risky_map() (die
      eigentlichen Konsumenten fuer die Risky-Fraction-Gewichtung) filtern
      inzwischen selbst nach jurisdiction (delegieren fuer Nicht-CH an genau
      dieselbe resolve_building_blocks_for_jurisdiction()) -- die Validierung
      hier ist also auf dem Happy-Path redundant geworden. Sie bleibt trotzdem
      bewusst stehen (Wahl statt Entfernen, siehe WP-A-Spec): sie feuert
      fruehestmoeglich, BEVOR House-Matrix/Strategie-Readiness/Cashflow-Laden
      etc. ueberhaupt laufen, und mehrere Aufrufer von
      build_target_payload_from_allocation() (z.B. routers/allocation.py
      GET-Reload-Pfad) rufen ensure_runtime_reference_data() ohne jurisdiction
      auf (Default "CH", ausserhalb des Scopes dieses Arbeitspakets) -- ohne
      diese frueh feuernde Kopie waere fuer NEUE, noch unvalidierte
      Code-Pfade kein Fail-Fast garantiert. Entfernen erschien deshalb
      riskanter als die (bewusste, harmlose) Doppelvalidierung.
    """
    if jurisdiction in (None, "CH"):
        return _ensure_runtime_reference_data_ch(db, user_id)

    policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
    if policy is None:
        raise JurisdictionReferenceDataMissingError(
            "Keine globale OptimizerPolicy vorhanden -- fuer Jurisdiktion "
            f"'{jurisdiction}' kann ensure_runtime_reference_data() keine eigene "
            "Policy erzeugen (policy bleibt in dieser Ausbaustufe die globale, "
            "jurisdiktionsunabhaengige Policy; siehe WP2-Doku)."
        )
    cma = resolve_cma_for_jurisdiction(
        db, jurisdiction, require_committee_approved=False, tenant_id=tenant_id,
    )
    resolve_building_blocks_for_jurisdiction(db, policy.id, jurisdiction, investment_universe=None)
    return policy, cma


def _ensure_runtime_reference_data_ch(db: Session, user_id: str) -> tuple[OptimizerPolicy, CapitalMarketAssumption]:
    now = _now()
    today = _today()
    # max_risky_fraction_bps pro Profil (ASIP-Konvention, U-P23.2/3, 2026-05-26):
    #   Kapitalschutz 3000 (=30%, ASIP-Obergrenze „Sicherheit/Kapitalschutz")
    #   Defensiv      4500 (=45%, ASIP-Obergrenze „Defensiv")
    #   Ausgewogen    6000 / Wachstum 8000 / Dynamisch 9000 / Aktien 10000
    # Konsistenz-Test in tests/test_house_matrix_risk_budget_consistency.py:
    # die Mid-Allocation jedes Profils × BB.risky_fraction_bps darf NIE
    # den Cap überschreiten, sonst triggert der Engine-Fallback den
    # Liquiditäts-Cascade (siehe _SAA_LIQUIDITY_HARD_CAP_BPS-Block).
    defaults = _normalize_house_matrix_defaults([
        (1, 2, "Kapitalschutz", 0, 300, 800, 6500, 7500, 8500, 500, 1200, 2000, 0, 500, 2000, 0, 500, 500, 3000, 0),
        (3, 4, "Defensiv", 0, 200, 500, 5000, 6000, 7000, 1500, 2500, 3000, 500, 1000, 2000, 0, 300, 800, 4500, 0),
        (5, 6, "Ausgewogen", 0, 200, 300, 2500, 3500, 4500, 4000, 4800, 5500, 500, 1000, 2000, 300, 500, 800, 6000, 0),
        (7, 8, "Wachstumsorientiert", 0, 150, 200, 1000, 1600, 2500, 6000, 6800, 7500, 500, 800, 2000, 300, 600, 1000, 8000, 6000),
        (9, 9, "Dynamisch", 0, 100, 200, 500, 800, 1500, 7500, 8000, 8500, 300, 700, 2000, 200, 400, 600, 9000, 7500),
        (10, 10, "Aktien", 0, 100, 200, 0, 200, 500, 8500, 9000, 9500, 200, 500, 2000, 0, 200, 500, 10000, 8500),
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
            # 2026-06-18 konservativ (User "immer tieferer Wert"): Gold hat langfristig
            # ~0% Realrendite -> nominale Annahme von 3.0% auf 1.2% gesenkt.
            alternatives_gold_return_bps=120,
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


def ensure_default_products(db: Session, jurisdiction: str = "CH") -> None:
    """WP2 (Engine-Wiring Jurisdiktion, 2026-07-31): der bestehende CH-
    Fondskatalog-Seed wird NUR fuer jurisdiction in (None, "CH") ausgefuehrt
    (Constraint 1: CH-Pfad byte-identisch). Fuer andere jurisdiction wird
    bewusst NICHTS geseedet -- Fonds kommen fuer Nicht-CH ausschliesslich
    ueber ProductUniverseEntry (siehe _filter_products_by_universe())."""
    if jurisdiction not in (None, "CH"):
        return
    # 2026-08-01 (Cross-Jurisdiktions-Leck-Fix): der Idempotenz-Check muss
    # CH-spezifisch sein (Product.jurisdiction in (None,"CH")), NICHT "gibt
    # es irgendein aktives Produkt in der gesamten Installation" -- sonst
    # wuerde der CH-Katalog NIE geseedet, wenn zuvor bereits Nicht-CH-
    # Produkte (z.B. via Deutschland-Anbindung) angelegt wurden, und ein
    # CH-Mandat faende danach ueberhaupt keine passenden Produkte mehr.
    active_ch_products = db.query(Product).filter(
        Product.is_active == 1,
        Product.deleted_at.is_(None),
        (Product.jurisdiction.is_(None)) | (Product.jurisdiction == "CH"),
    ).count()
    if active_ch_products:
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


# ADR-014 Schritt 1 (2026-08-02): Gesamtvermoegen-Cluster extrahiert nach
# services/portfolio_engine_gesamtvermoegen.py (0 Zeilen Fachlogik-Aenderung,
# Byte-fuer-Byte-Kopie der 4 Funktionskoerper). Re-Export haelt alle
# bestehenden Importe unveraendert funktionsfaehig -- insbesondere
# services/advisory_report.py und routers/clients.py importieren
# _wealth_inflow_series_rappen direkt per `from services.portfolio_engine
# import ...`, ohne dass dort etwas geaendert werden musste.
from services.portfolio_engine_gesamtvermoegen import (  # noqa: F401,E402
    _build_total_wealth_allocation,
    _external_assets_inflation_value,
    _goal_uses_total_scope,
    _wealth_inflow_series_rappen,
)


def _load_allocation_inputs(
    db: Session,
    mandate: Mandate,
    simulation_prefs: dict,
    cma: CapitalMarketAssumption | None = None,
) -> dict:
    # Sprint B3 (2026-06-07): Multi-Currency-Conversion via FXRateSource.
    # mandate.base_currency ist das Ziel (typisch CHF). Cashflows in
    # USD/EUR/GBP etc. werden zum aktuellen FX-Kurs konvertiert. Bei
    # FX-Lade-Fehler defensiver Fallback auf Default-Rates (kein Crash).
    # 2026-07-24 (Generalaudit): Fallback war fx_source=None -> keine
    # Konvertierung mehr (Rohbetrag), obwohl FXRateSource.from_db() selbst
    # schon auf Default-Rates faellt statt zu raisen -- dieser aeussere
    # except greift praktisch nie, aber FXRateSource() ist die konsistentere
    # Wahl falls doch (Naeherung statt komplettes Ignorieren der Waehrung).
    # 2026-07-27 (WealthPosition-FX-Fix): Setup nach oben verschoben, damit
    # auch _summarize_positions (Vermoegenspositionen) dieselbe FX-Quelle
    # nutzen kann -- vorher wurde NUR Cashflows konvertiert, Vermoegens-
    # positionen in Fremdwaehrung flossen unkonvertiert in die SAA-/MC-Basis.
    from services.currency.fx_rates import FXRateSource
    fx_source = None
    try:
        fx_source = FXRateSource.from_db(db)
    except Exception:
        fx_source = FXRateSource()
    target_currency = str(getattr(mandate, "base_currency", "CHF") or "CHF").upper()

    all_positions = db.query(WealthPosition).filter(
        WealthPosition.client_id == mandate.client_id,
        WealthPosition.deleted_at.is_(None),
        WealthPosition.is_active == 1,
    ).all()
    advisory_positions = [pos for pos in all_positions if _norm_text(pos.assignment) == "Beratungsvermoegen"]
    asset_positions_total = [pos for pos in all_positions if _norm_text(pos.assignment) != "Verbindlichkeit"]
    liability_positions = [pos for pos in all_positions if _norm_text(pos.assignment) == "Verbindlichkeit"]
    advisory_summary = _summarize_positions(advisory_positions, fx_source=fx_source, target_currency=target_currency)
    total_summary = _summarize_positions(asset_positions_total, fx_source=fx_source, target_currency=target_currency)
    advisory_wealth_rappen = advisory_summary.total_rappen
    total_liabilities_rappen = sum(
        _convert_position_amount_to_target_currency(pos, fx_source, target_currency)
        for pos in liability_positions
    )
    total_wealth_rappen = max(0, total_summary.total_rappen - total_liabilities_rappen)
    # Sprint B2 (2026-05-07): Anderes-Vermoegen-Schloss-Mechanismus.
    # is_available_for_goal_funding=1 erlaubt der Position, zur Reserve-Deckung
    # herangezogen zu werden (liquid: Verkauf, illiquid: Belehnung @ 100% LTV).
    unlocked_other_assets_rappen = sum(
        _convert_position_amount_to_target_currency(pos, fx_source, target_currency)
        for pos in all_positions
        if int(getattr(pos, "is_available_for_goal_funding", 0) or 0) == 1
        and _norm_text(getattr(pos, "assignment", "")) == "Anderes Vermoegen"
    )

    cashflows = db.query(Cashflow).filter(
        Cashflow.client_id == mandate.client_id,
        Cashflow.deleted_at.is_(None),
        Cashflow.is_active == 1,
    ).all()
    # 2026-06-14: vermögensgetriebene Cashflows (Hypothekarzins, Amortisation,
    # Miet-/Zinserträge) auch in die Engine-Projektion/Reserve einspeisen, damit
    # Strategie-Verzehr und Cashflow-Ansicht 1:1 dieselben Posten sehen.
    cashflows = list(cashflows) + derive_wealth_cashflows(all_positions)
    goals = db.query(Goal).filter(
        Goal.mandate_id == mandate.id,
        Goal.deleted_at.is_(None),
        Goal.is_active == 1,
    ).order_by(Goal.rank.asc()).all()
    # Sprint A1: erwartete Vermoegenszufluesse (Erbschaft, Bonus, Saeule3b, ...)
    wealth_inflows = db.query(WealthInflow).filter(
        WealthInflow.client_id == mandate.client_id,
        WealthInflow.deleted_at.is_(None),
        WealthInflow.is_active == 1,
    ).all()
    # Mandate-spezifische Inflows nur fuer dieses Mandat; client-weite (mandate_id=None) immer dabei.
    wealth_inflows = [
        infl for infl in wealth_inflows
        if not getattr(infl, "mandate_id", None) or infl.mandate_id == mandate.id
    ]
    # fx_source/target_currency bereits weiter oben ermittelt (siehe FX-Fix-
    # Kommentar) -- hier wiederverwendet statt erneut geladen.
    cashflow_totals = totals_for_year(
        cashflows, fx_source=fx_source, target_currency=target_currency,
    )
    projection_years = _simulation_horizon_years(simulation_prefs, goals, mandate)
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
        fx_source=fx_source,
        target_currency=target_currency,
    )
    # Sprint A1: Inflows als positive Beitraege addieren. Dadurch sehen alle
    # downstream-Konsumer (MC, Goal-Analysis, Reserve) die Erbschaft/Bonus.
    inflow_projection_series_rappen = _wealth_inflow_series_rappen(
        wealth_inflows, projection_years, cashflow_totals["year"], cf_inflation_series_bps,
    )
    if any(inflow_projection_series_rappen):
        cashflow_projection_series_rappen = [
            int(cf) + int(infl)
            for cf, infl in zip(cashflow_projection_series_rappen, inflow_projection_series_rappen)
        ]
    # 2026-06-14 (#31): Hypothek-Amortisation/Refinanzierung jahresabhängig in die
    # Projektion einrechnen — direkt: sinkende Zinslast; Refi auf 3% nach Ablauf
    # (Fix) bzw. 5 Jahren (SARON). Additiv auf das Netto-Cashflow-Series; die
    # heutige Cashflow-Ansicht/Summe bleibt unberührt (statischer Posten = Jahr 0).
    _mortgage_interest_adj = mortgage_interest_adjustment_series(
        all_positions, projection_years, cashflow_totals["year"],
    )
    if any(_mortgage_interest_adj):
        cashflow_projection_series_rappen = [
            int(cf) + int(adj)
            for cf, adj in zip(cashflow_projection_series_rappen, _mortgage_interest_adj)
        ]
    recurring_cashflow_projection_series_rappen = recurring_net_cashflow_series(
        cashflows,
        projection_years,
        start_year=cashflow_totals["year"],
        inflation_series_bps=cf_inflation_series_bps,
        fx_source=fx_source,
        target_currency=target_currency,
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
        # Sprint A1: erwartete Vermoegenszufluesse, fuer Audit-Trail + FE-Anzeige.
        "wealth_inflows": wealth_inflows,
        "inflow_projection_series_rappen": inflow_projection_series_rappen,
        # Sprint B2: Anderes-Vermoegen-Schloss-Pool (Reserve-Reduktion).
        "unlocked_other_assets_rappen": unlocked_other_assets_rappen,
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


def _house_matrix_mid_targets(house_matrix: HouseMatrix, policy: OptimizerPolicy) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    _targets, minimums, maximums = _baseline_target_bands(house_matrix, policy)
    midpoint_targets = {
        bucket: int(round((int(minimums[bucket]) + int(maximums[bucket])) / 2))
        for bucket in BUCKET_FIELDS
    }
    return _rebalance_to_total(midpoint_targets, minimums, maximums), minimums, maximums


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


def _renditeziel_equity_tilt_bps(
    *,
    target_return_bps: int,
    current_equity_bps: int,
    min_equity_bps: int,
    max_equity_bps: int,
) -> int:
    """Sprint 2026-06-08 Option C: Equity-Tilt fuer Renditeziel-Goals.

    Returns signed delta in bps:
    - positiv = Equity-Erhoehung (Wachstums-Tilt fuer hohes Target)
    - negativ = Equity-Reduktion (Defensiv-Tilt fuer niedriges Target)
    - 0 = kein Tilt

    Logik (target in bps):
    - target < 250 bps (< 2.5% p.a.): Defensiv-Tilt von max 150 bps
    - target 250-400: kein Tilt (Standard-Bereich)
    - target 400-600: Wachstums-Tilt von max 150 bps
    - target > 600: Wachstums-Tilt von max 200 bps

    Resultat wird automatisch an die House-Matrix-Bandbreiten geclippt:
    - Equity-Erhoehung max = max_equity_bps - current_equity_bps (room nach oben)
    - Equity-Reduktion max = current_equity_bps - min_equity_bps (room nach unten)

    Strategietreue gewahrt: Tilt verlaesst NIE die Bandbreiten des Risikoprofils.
    """
    if target_return_bps <= 0:
        return 0

    # Raw Tilt-Magnitude basierend auf Target
    if target_return_bps < 250:
        raw_tilt = -150  # defensiver Tilt
    elif target_return_bps < 400:
        raw_tilt = 0  # Standard-Bereich, kein Tilt
    elif target_return_bps < 600:
        raw_tilt = 150  # leichter Wachstums-Tilt
    else:
        raw_tilt = 200  # staerkerer Wachstums-Tilt

    if raw_tilt == 0:
        return 0

    if raw_tilt > 0:
        # Wachstums-Tilt: clippen auf room nach oben
        room_up = max(0, int(max_equity_bps) - int(current_equity_bps))
        return min(raw_tilt, room_up)
    # Defensiv-Tilt: clippen auf room nach unten
    room_down = max(0, int(current_equity_bps) - int(min_equity_bps))
    return -min(abs(raw_tilt), room_down)


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
    unlocked_other_assets_rappen: int = 0,
    inflow_projection_series_rappen: list[int] | None = None,
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
        unlocked_other_assets_rappen=unlocked_other_assets_rappen,
        inflow_projection_series_rappen=inflow_projection_series_rappen,
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

    # Sprint 2026-06-08 Option C: Goal-Tilt fuer Renditeziele.
    # SAA bleibt Risikoprofil-bound (FINMA/Strategietreue), aber innerhalb der
    # House-Matrix-Bandbreiten reagiert sie auf das Renditeziel-Target:
    # - Niedriges Target (<2.5%): leichte Aktien-Reduktion (Kapitalerhalt-Tilt)
    # - Mittleres Target (2.5-4%): kein Tilt (Standard)
    # - Hohes Target (>4%): leichte Aktien-Erhoehung (Wachstums-Tilt)
    # Max ±200 bps pro Goal, immer geclippt an den Bandbreiten (min/max).
    # Opportunistische Renditeziele tilten NICHT (Hardness-Filter, ADR-konform).
    for goal in goals:
        goal_type = _norm_text(goal.goal_type)
        if goal_type != "Renditeziel":
            continue
        hardness = _norm_text(goal.hardness).lower()
        # ADR: nur Primaer-Renditeziele tilten (Hart wird im Frontend geblockt;
        # Opportunistisch ist nicht-tilt-wuerdig per Anlagephilosophie).
        if hardness not in ("primaer", "primary"):
            continue
        target_bps = int(getattr(goal, "target_return_bps", None) or 0)
        if target_bps <= 0:
            continue
        eq_shift = _renditeziel_equity_tilt_bps(
            target_return_bps=target_bps,
            current_equity_bps=int(targets.get("equities", 0)),
            min_equity_bps=int(minimums.get("equities", 0)),
            max_equity_bps=int(maximums.get("equities", 10000)),
        )
        if eq_shift == 0:
            continue
        if eq_shift > 0:
            # Wachstums-Tilt: Equity hoch, Bonds runter
            bonds_floor = int(minimums.get("bonds", 0))
            bonds_available = max(0, int(targets.get("bonds", 0)) - bonds_floor)
            eq_shift_capped = min(eq_shift, bonds_available)
            if eq_shift_capped > 0:
                targets["equities"] += eq_shift_capped
                targets["bonds"] -= eq_shift_capped
                reasoning.append(
                    f"Renditeziel '{goal.label}' ({target_bps/100:.2f}% p.a.) "
                    f"hebt den Aktienanteil um {eq_shift_capped} bps an (innerhalb der "
                    f"Bandbreiten, Strategietreue gewahrt)."
                )
        else:
            # Defensiver Tilt: Equity runter, Bonds hoch
            shift_abs = abs(eq_shift)
            bonds_ceiling = int(maximums.get("bonds", 10000))
            bonds_room = max(0, bonds_ceiling - int(targets.get("bonds", 0)))
            shift_capped = min(shift_abs, bonds_room)
            if shift_capped > 0:
                targets["equities"] -= shift_capped
                targets["bonds"] += shift_capped
                reasoning.append(
                    f"Renditeziel '{goal.label}' ({target_bps/100:.2f}% p.a.) "
                    f"senkt den Aktienanteil um {shift_capped} bps zugunsten Bonds "
                    f"(innerhalb der Bandbreiten)."
                )

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


# ADR-014 Schritt 6 (2026-08-02): Optimizer-Integration extrahiert nach
# services/portfolio_engine_optimizer_integration.py (0 Zeilen Fachlogik-
# Aenderung, Byte-fuer-Byte-Kopie der 14 Funktionskoerper, per Diff-Skript
# verifiziert). evaluate_goal_sensitivity und generate_target_allocation
# (Orchestratoren, bleiben hier) rufen diese Namen weiterhin unveraendert
# auf. Kein externer Nicht-Test-Konsument gefunden (exhaustiv geprueft).
from services.portfolio_engine_optimizer_integration import (  # noqa: F401,E402
    _allocation_comparison_note,
    _assessment_score_x10,
    _build_allocation_method_comparison,
    _build_optimizer_explainability,
    _build_shadow_comparison_with_evaluations,
    _build_shadow_optimization_payload,
    _build_tax_solver_kwargs,
    _driving_goal_id_from_achievability,
    _objective_to_milli,
    _optimizer_audit_fields,
    _optimizer_status_is_converged,
    _persist_optimizer_run,
    _run_stochastic_optimizer_pass,
    _weights_from_targets,
)


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


# ADR-014 Schritt 4 (2026-08-02): Reserve-Cluster extrahiert nach
# services/portfolio_engine_reserve.py (0 Zeilen Fachlogik-Aenderung,
# Byte-fuer-Byte-Kopie). _goal_projection_years/_annualize_goal_amount
# bleiben in portfolio_engine.py (echte 4-Cluster-Verflechtung: Reserve,
# Payload-Bau, MC-Simulation, House-Matrix/Tilt) und werden vom neuen Modul
# per Lazy-Import zurueckgeholt. _goal_hardness_key ist KEINE
# Reserve-Abhaengigkeit (ADR-014s Behauptung war falsch, siehe Modul-
# Docstring von portfolio_engine_reserve.py) und bleibt unberuehrt hier.
from services.portfolio_engine_reserve import (  # noqa: F401,E402
    _compute_reserve_for_inputs,
    _compute_reserve_requirements,
    _goal_is_conditional,
    _goal_pension_pillar,
    _goal_pension_state_funded,
    _goal_probability_factor,
    _goal_reserve_for_goal,
    _reserve_bucket_mode_time_bucket,
    _reserve_decay_factor,
    _reserve_decay_mode_smooth,
    _time_bucket_label,
    _time_bucket_reserve_factor,
    PENSION_PILLARS,
    PENSION_PILLAR_STATE_FUNDED,
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




def _assert_allocation_has_basis(
    advisory_wealth_rappen: int,
    recurring_income_rappen: int,
    recurring_expense_rappen: int,
    capital_inflow_rappen: int,
    capital_outflow_rappen: int,
) -> None:
    """Guard (User-Anweisung 2026-06-23): Ohne jede Datenbasis ist keine seriöse Asset-
    Allocation möglich — sonst zeigt die SOLL-%-Torte ein Vermögen vor, das es nicht gibt.

    Regel:
    - Beratungsvermögen > 0  → erlaubt.
    - Beratungsvermögen == 0 ABER Cashflows erfasst → erlaubt (Vermögensaufbau via Sparquote,
      "Strategie vor Geldfluss").
    - Weder Beratungsvermögen NOCH Cashflows (gar keine Daten) → ValueError (Endpoint → 409).
    """
    has_cashflow = bool(
        recurring_income_rappen
        or recurring_expense_rappen
        or capital_inflow_rappen
        or capital_outflow_rappen
    )
    if advisory_wealth_rappen <= 0 and not has_cashflow:
        raise ValueError(
            "Keine Vermögensbasis: Dieses Mandat hat weder Beratungsvermögen noch Cashflows. "
            "Bitte zuerst Vermögenspositionen oder Cashflows (Vermögensaufbau) erfassen — "
            "ohne Datenbasis ist keine Asset-Allocation möglich."
        )


def generate_target_allocation(
    db: Session,
    mandate: Mandate,
    user_id: str,
    preferences: dict | None,
) -> dict:
    now = _now()
    # WP2 (Engine-Wiring Jurisdiktion, 2026-07-31): einmal pro Lauf aufgeloest,
    # an ensure_runtime_reference_data()/_build_sub_allocations() durchgereicht.
    jurisdiction = resolve_mandate_jurisdiction(mandate)
    policy, cma = ensure_runtime_reference_data(
        db, user_id, jurisdiction=jurisdiction, tenant_id=getattr(mandate, "tenant_id", None) or None,
    )
    # rp-ueberarbeitung: Strategie-Readiness-Gate (Knowledge-/Erfahrungs-Antworten
    # vollstaendig). Audit-Master hatte den Check nur in den Routern; durch das
    # Aufrufen hier ist er auch fuer direkte Service-Aufrufe wirksam.
    assessment = require_strategy_ready_assessment(db, mandate.id)

    prefs = _normalize_preferences(preferences)
    # Sprint B1: Mandanten-Default-Building-Blocks als Fallback in prefs.
    prefs = _merge_mandate_defaults_into_prefs(prefs, mandate)
    score_bucket = _risk_score_bucket(assessment)
    house_matrix = _house_matrix_or_default(db, policy, score_bucket)
    risk_budget_bps = int(house_matrix.max_risky_fraction_bps)
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
    # Datenbasis-Guard: kein Beratungsvermögen UND keine Cashflows → keine Allocation (409).
    _assert_allocation_has_basis(
        advisory_wealth_rappen,
        recurring_income_rappen,
        recurring_expense_rappen,
        capital_inflow_rappen,
        capital_outflow_rappen,
    )
    targets, minimums, maximums = _baseline_target_bands(house_matrix, policy)
    reasoning = [
        f"Ausgangspunkt ist die House Matrix fuer Score {score_bucket} ({house_matrix.profile_name}).",
        f"Das Risikoprofil deckelt die Risky Fraction auf {risk_budget_bps / 100:.0f}%.",
    ]
    warnings: list[dict] = []
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
        unlocked_other_assets_rappen=int(inputs.get("unlocked_other_assets_rappen") or 0),
        # Sprint U-P2 Fix H11: Wealth-Inflows in Reserve berücksichtigen
        inflow_projection_series_rappen=inputs.get("inflow_projection_series_rappen"),
    )
    investable_advisory_wealth_rappen = _investable_advisory_wealth_rappen(advisory_wealth_rappen, external_reserve_rappen)

    goal_inflation_series_bps = _goal_inflation_series_bps(
        cma,
        len(cashflow_projection_series_rappen),
        cashflow_totals["year"],
        planning_inflation_bps=_current_planning_inflation_bps(db, mandate),
    )

    # Phase 4 / V3 Sprint 1: Stochastic Optimizer.
    # Modi:
    # - 'stochastic': Solver konvergiert -> ersetzt House-Matrix-Default-Targets;
    #   nachfolgende Tilts werden uebersprungen.
    # - 'shadow_stochastic': Solver laeuft, House-Matrix bleibt aktive Allokation;
    #   Solver-Result wird nur als Methodenvergleich im Response geliefert. Audit-
    #   Felder und Stress-JSON werden NICHT auf der TargetAllocation persistiert.
    # - sonst: Solver wird nicht aufgerufen.
    optimizer_mode = settings.optimizer_mode
    run_stochastic = optimizer_mode in {"stochastic", "shadow_stochastic"}
    apply_stochastic = optimizer_mode == "stochastic"
    house_targets_before_optimizer = dict(targets)
    # Phase 5.1: Building-Block-Aware Risky-Fractions fuer Solver
    # WP-A (2026-08-01): jurisdiction durchgereicht, damit ein DE-Mandat NUR
    # aus DE-spezifischen BuildingBlock-Zeilen gewichtet wird, nicht aus dem
    # gemischten CH+DE-Bestand derselben policy_id.
    _building_block_rows = _building_block_rows_for_policy(
        db,
        policy.id,
        getattr(mandate, "investment_universe", None),
        jurisdiction,
    )

    optimizer_result = _run_stochastic_optimizer_pass(
        optimizer_mode=optimizer_mode,
        apply_targets=apply_stochastic,
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
        mandate=mandate,  # Sprint 4 Phase 3: BFS-Mortalitaets-Felder
    )
    # Strikt: Tilts duerfen nur uebersprungen werden, wenn die Targets
    # tatsaechlich vom Solver ersetzt wurden (also nur im 'stochastic' Modus,
    # nicht in 'shadow_stochastic'). Sonst lief der Solver nur fuer Vergleich.
    optimizer_replaced_targets = (
        apply_stochastic
        and optimizer_result is not None
        and _optimizer_status_is_converged(optimizer_result.status)
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

    # 3eyes-konform: Illiquiditaet wird auf Baustein-Ebene (Private Equity) gedeckelt,
    # nicht pauschal auf der ganzen Alternatives-Quote (Gold/Liquid Alts sind liquide).
    # Direktimmobilien laufen ohnehin extern ueber das Gesamtvermoegen.
    max_illiquid_bps = _parse_bps_percent(prefs["limits"].get("maxIlliquid"))

    targets = _rebalance_to_total(targets, minimums, maximums)
    risky_map = _building_block_risky_map(db, policy.id, getattr(mandate, "investment_universe", None), jurisdiction)
    sub_allocations = _build_sub_allocations(targets, prefs, jurisdiction=jurisdiction, db=db)
    if not optimizer_replaced_targets:
        sub_allocations, targets = _apply_illiquid_cap(sub_allocations, targets, max_illiquid_bps, reasoning)
    sub_allocations, asset_risky_weights, risky_fraction_total_bps = _enrich_sub_allocations_with_risk(sub_allocations, risky_map)
    realized_risky_bps = risky_fraction_total_bps  # Validierung 2026-06-11 (#AA-1/#AA-3): sub-allocation-gewichtet (konsistent zur Enforcement-Cascade), statt ungewichtetem BB-Bucket-Mittel
    risk_budget_fallback = False
    try:
        assert_risk_budget_ok(realized_risky_bps, risk_budget_bps, slack_bps=0)
    except RiskBudgetExceeded:
        risk_budget_fallback = True
        risk_budget_asset_weights = bucket_risky_fraction_bps_from_building_blocks(_building_block_rows)
        targets, minimums, maximums = _house_matrix_mid_targets(house_matrix, policy)
        targets = _rebalance_to_total(targets, minimums, maximums)
        sub_allocations = _build_sub_allocations(targets, prefs, jurisdiction=jurisdiction, db=db)
        sub_allocations, targets = _apply_illiquid_cap(sub_allocations, targets, max_illiquid_bps, reasoning)
        sub_allocations, asset_risky_weights, risky_fraction_total_bps = _enrich_sub_allocations_with_risk(sub_allocations, risky_map)
        realized_risky_bps = risky_fraction_total_bps  # Validierung 2026-06-11 (#AA-1): sub-allocation-gewichtet (konsistent zur Enforcement-Cascade via asset_risky_weights), statt ungewichtetem BB-Bucket-Mittel
        try:
            assert_risk_budget_ok(realized_risky_bps, risk_budget_bps, slack_bps=0)
        except RiskBudgetExceeded:
            # U-P23.1 (2026-05-25): 2-Stufen-Eskalation statt brutalem
            # Liquid-Push auf 100%. Der vorherige Code öffnete sofort
            # `maximums["liquidity"] = 10000` und brachte Defensiv-Mandate
            # auf 10% SAA-Liquidität (Bug-Report vom Berater).
            #
            # Neue Eskalation:
            #   Stufe 1: Versuch mit HouseMatrix-Bandbreiten unverändert
            #   Stufe 2: bei Fail → Cap auf SAA-Hard-Cap (3%)
            #   Stufe 3: bei Fail → Cap auf konservatives Sicherheits-
            #            Maximum (10%) mit Warning + Reasoning-Trail
            #   Stufe 4: bei Fail → echte ValueError propagieren
            try:
                targets, risky_fraction_total_bps = _enforce_risk_budget(
                    targets=targets,
                    minimums=minimums,
                    maximums=maximums,
                    asset_risky_weights=risk_budget_asset_weights,
                    risk_budget_bps=risk_budget_bps,
                )
            except ValueError:
                # Stufe 2: Cap auf SAA-Hard-Cap (3%)
                hard_capped = max(
                    int(maximums.get("liquidity", 0) or 0),
                    int(_SAA_LIQUIDITY_HARD_CAP_BPS),
                )
                maximums = {**maximums, "liquidity": hard_capped}
                try:
                    targets, risky_fraction_total_bps = _enforce_risk_budget(
                        targets=targets,
                        minimums=minimums,
                        maximums=maximums,
                        asset_risky_weights=risk_budget_asset_weights,
                        risk_budget_bps=risk_budget_bps,
                    )
                except ValueError:
                    # Stufe 3: erweitertes Sicherheits-Maximum (10%) +
                    # explizite Warnung. Compliance-Notiz im Reasoning-
                    # Trail damit der Berater sieht warum die SAA über
                    # dem Hard-Cap ist.
                    expanded_max = max(hard_capped, _SAA_LIQUIDITY_EMERGENCY_CAP_BPS)
                    maximums = {**maximums, "liquidity": expanded_max}
                    # Validierung 2026-06-11 (#AA-1): letzte Eskalationsstufe gibt die
                    # konservativste ERREICHBARE Allokation zurueck (allow_best_effort)
                    # statt hart zu werfen, falls das Budget strukturell unerreichbar ist.
                    targets, risky_fraction_total_bps = _enforce_risk_budget(
                        targets=targets,
                        minimums=minimums,
                        maximums=maximums,
                        asset_risky_weights=risk_budget_asset_weights,
                        risk_budget_bps=risk_budget_bps,
                        allow_best_effort=True,
                    )
                    warnings.append(format_message(WARN_FALLBACK))
                    reasoning.append(
                        "Liquiditätsanteil über dem SAA-Hard-Cap (3 %): "
                        "das Risikoprofil-Budget liesse sich anders nicht "
                        "einhalten. Bitte Risikoprofil oder Goal-Struktur "
                        "im Beratungsgespräch prüfen."
                    )
            targets = _rebalance_to_total(targets, minimums, maximums)
            sub_allocations = _build_sub_allocations(targets, prefs, jurisdiction=jurisdiction, db=db)
            sub_allocations, targets = _apply_illiquid_cap(sub_allocations, targets, max_illiquid_bps, reasoning)
            sub_allocations, asset_risky_weights, risky_fraction_total_bps = _enrich_sub_allocations_with_risk(sub_allocations, risky_map)
            realized_risky_bps = risky_fraction_total_bps  # Validierung 2026-06-11 (#AA-1): sub-allocation-gewichtet (konsistent zur Enforcement-Cascade via asset_risky_weights), statt ungewichtetem BB-Bucket-Mittel
            if int(realized_risky_bps) > int(risk_budget_bps):
                # Validierung 2026-06-11 (#AA-1): strukturell unerreichbares Budget
                # (Bausteine + Pflicht-Bandbreiten lassen die Risky-Fraction nicht unter
                # den Cap — z.B. Kapitalschutz: Bonds-Floor 65% × Bonds-Risky dominiert).
                # Frueher: hartes RiskBudgetExceeded -> 500, Berater bekam KEINE Strategie
                # fuer das konservativste Profil. Jetzt: konservativste erreichbare
                # Allokation behalten + klare Compliance-Warnung (Design-Absicht "Berater
                # alarmieren", aber ohne Crash). WARN_FALLBACK wird unten angefuegt.
                reasoning.append(
                    f"Das Risikoprofil-Budget ({risk_budget_bps / 100:.0f} %) ist mit den "
                    f"aktuellen Bausteinen und Pflicht-Bandbreiten strukturell nicht "
                    f"vollstaendig erreichbar (konservativst moeglich: "
                    f"{int(realized_risky_bps) / 100:.1f} %). Die konservativste zulaessige "
                    f"Allokation wurde gewaehlt; bitte Risikoprofil oder Bausteine im "
                    f"Beratungsgespraech pruefen."
                )
            else:
                assert_risk_budget_ok(realized_risky_bps, risk_budget_bps, slack_bps=0)
        warnings.append(format_message(WARN_FALLBACK))
        reasoning.append("Die aktive Allokation wurde auf die Bandbreiten-Mitte des Risikoprofils zurueckgesetzt, weil das Risikobudget strikt limitiert.")
    risky_fraction_total_bps = int(realized_risky_bps)
    goal_achievability = list(getattr(optimizer_result, "goal_achievability", ()) or [])
    optimization_status_for_limits = "fallback_house_matrix" if risk_budget_fallback else getattr(optimizer_result, "status", None)
    limiting_factor = classify_limiting_factor(
        allocation_bps=targets,
        risky_fraction=risky_fraction_total_bps,
        max_risky_fraction=risk_budget_bps,
        min_liquidity_bps=minimums["liquidity"],
        bands={bucket: (minimums[bucket], maximums[bucket]) for bucket in BUCKET_FIELDS},
        achievability=goal_achievability,
        optimization_status=optimization_status_for_limits,
    )
    if not goal_achievability and risky_fraction_total_bps >= risk_budget_bps - 50:
        limiting_factor = "risikoprofil"
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
        # Sprint U-P5 Fix H12: Mortality-Cutoff
        expected_death_year_offset=_expected_death_year_offset_from_mandate(mandate),
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
    current_goal_analysis = _merge_goal_analysis_with_monte_carlo(
        goal_analysis,
        monte_carlo,
        summaries_key="current_goal_summaries",
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

    # V3 Sprint 1: Audit-/Stress-/Reasoning-Persistenz nur im 'stochastic' Modus.
    # Im 'shadow_stochastic' bleibt die TargetAllocation House-Matrix-basiert,
    # und Solver-Felder duerfen nicht so aussehen, als seien sie aktiv.
    # Im 'stochastic' Modus persistieren wir auch bei diverged/fallback, damit
    # der Audit-Trail (seed, status, iterations) erklaert, warum der Solver
    # nicht angewendet wurde.
    persist_optimizer_audit = optimizer_mode == "stochastic" and optimizer_result is not None
    optimizer_audit = _optimizer_audit_fields(optimizer_result) if persist_optimizer_audit else {}
    if risk_budget_fallback:
        optimizer_audit = {
            **optimizer_audit,
            "optimization_method": "fallback_house_matrix",
            "optimization_status": "fallback_house_matrix",
        }
    goal_achievability_json: str | None = None
    if goal_achievability:
        try:
            goal_achievability_json = json.dumps(
                goal_achievability,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Goal-achievability JSON-serialization failed: %s", exc)
            goal_achievability_json = None
    message_context = SimpleNamespace(
        limiting_factor=limiting_factor,
        optimization_status=optimization_status_for_limits,
        risky_fraction_bps_at_generation=risky_fraction_total_bps,
        risk_budget_bps_at_generation=risk_budget_bps,
    )
    messages = classify_messages(
        message_context,
        goal_achievability,
        optimization_status_for_limits,
        mandate,
        assessment,
    )
    # Phase 6: Stress-Eval als JSON persistieren, damit /current/payload sie
    # ohne erneuten Solver-Lauf liefern kann. Nur im stochastic-Modus.
    stress_evaluations_json: str | None = None
    if (
        optimizer_mode == "stochastic"
        and optimizer_result is not None
        and optimizer_result.stress_evaluations
    ):
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
    # Nur im stochastic-Modus: Shadow-Reasoning gehoert nicht in eine
    # House-Matrix-TargetAllocation.
    optimizer_reasoning_json: str | None = None
    if (
        optimizer_mode == "stochastic"
        and optimizer_result is not None
        and (optimizer_result.reasoning or messages)
    ):
        try:
            trace_payload = {
                "binding_constraints": [],
                "driving_goal_id": _driving_goal_id_from_achievability(goal_achievability),
                "limiting_factor": limiting_factor,
                "achievability": goal_achievability,
                "messages": messages,
            }
            reasoning_payload = list(optimizer_result.reasoning)
            if goal_achievability or limiting_factor or messages:
                reasoning_payload.append(trace_payload)
            optimizer_reasoning_json = json.dumps(
                reasoning_payload,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Optimizer-reasoning JSON-serialization failed: %s", exc)
            optimizer_reasoning_json = None

    active_weights_bps = _weights_from_targets(targets)
    allocation_method_comparison = _build_shadow_comparison_with_evaluations(
        optimizer_mode=optimizer_mode,
        optimizer_result=optimizer_result,
        active_weights_bps=active_weights_bps,
        cma=cma,
        goals=goals,
        house_matrix_row=house_matrix,
        assessment=assessment,
        advisory_wealth_rappen=investable_advisory_wealth_rappen,
        cashflow_projection_series_rappen=cashflow_projection_series_rappen,
        inflation_series_bps=goal_inflation_series_bps,
        building_blocks_rows=_building_block_rows,
    )
    optimizer_constraints, optimizer_goal_drivers = _build_optimizer_explainability(
        optimizer_mode=optimizer_mode,
        optimizer_result=optimizer_result,
        active_weights_bps=active_weights_bps,
        cma=cma,
        goals=goals,
        house_matrix_row=house_matrix,
        assessment=assessment,
        advisory_wealth_rappen=investable_advisory_wealth_rappen,
        cashflow_projection_series_rappen=cashflow_projection_series_rappen,
        inflation_series_bps=goal_inflation_series_bps,
        building_blocks_rows=_building_block_rows,
    )
    shadow_optimization_payload = _build_shadow_optimization_payload(
        optimizer_mode=optimizer_mode,
        optimizer_result=optimizer_result,
        active_weights_bps=active_weights_bps,
        active_risky_fraction_bps=risky_fraction_total_bps,
        risk_budget_bps=risk_budget_bps,
        minimums=minimums,
        maximums=maximums,
        building_blocks_rows=_building_block_rows,
        mandate=mandate,
        assessment=assessment,
        comparison=allocation_method_comparison,
        constraints=optimizer_constraints,
        goal_drivers=optimizer_goal_drivers,
    )
    shadow_optimization_json: str | None = None
    if shadow_optimization_payload:
        try:
            shadow_optimization_json = json.dumps(
                shadow_optimization_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Shadow-optimization JSON-serialization failed: %s", exc)
            shadow_optimization_json = None

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
        risky_fraction_bps_at_generation=risky_fraction_total_bps,
        risk_budget_bps_at_generation=risk_budget_bps,
        limiting_factor=limiting_factor,
        goal_achievability_json=goal_achievability_json,
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
        shadow_optimization_json=shadow_optimization_json,
        # AR-2 (FIDLEG-Report): MC-Risiko-KPIs auf Beratungsvermoegens-Ebene
        # (target_*, NICHT total_*) persistieren, damit _build_key_metrics sie
        # ausweisen kann statt "—". Defensiv: fehlt ein Key -> None. Einheit bps.
        mc_exp_vol_bps=monte_carlo.get("target_volatility_1y_bps"),
        mc_exp_return_bps=monte_carlo.get("target_annualized_return_p50_bps"),
        mc_max_drawdown_bps=monte_carlo.get("target_max_drawdown_p50_bps"),
        mc_var_95_bps=monte_carlo.get("target_var_95_1y_bps"),
        policy_id=policy.id,
        set_by=user_id,
        set_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(target_allocation)
    db.flush()

    # V3 Sprint 2: persistierter Audit-Trail aller Solver-Laufe.
    persisted_run = _persist_optimizer_run(
        db,
        mandate_id=mandate.id,
        target_allocation_id=target_allocation.id,
        optimizer_mode=optimizer_mode,
        optimizer_result=optimizer_result,
        user_id=user_id,
        now=now,
    )
    # V3 Sprint 2.1: Verknuepfung herstellen — nur fuer 'active'-Runs (also
    # stochastic-Modus, in dem der Solver tatsaechlich die TA produziert hat).
    # Im shadow_stochastic-Modus bleibt optimization_run_id NULL, weil die
    # TA House-Matrix-basiert ist.
    if persisted_run is not None and persisted_run.role == "active":
        db.flush()  # ensure persisted_run.id ist gesetzt
        target_allocation.optimization_run_id = persisted_run.id

    current_amounts = advisory_summary.amounts_rappen
    bucket_response = _build_bucket_response(
        target_allocation,
        current_amounts,
        advisory_wealth_rappen,
        target_total_rappen=investable_advisory_wealth_rappen,
    )

    total_allocation_payload = _build_total_wealth_allocation(
        total_summary, total_liabilities_rappen, total_wealth_rappen,
        {
            "equities": int(getattr(target_allocation, "target_equities_bps", 0) or 0),
            "bonds": int(getattr(target_allocation, "target_bonds_bps", 0) or 0),
            "real_estate": int(getattr(target_allocation, "target_real_estate_bps", 0) or 0),
            "alternatives": int(getattr(target_allocation, "target_alternatives_bps", 0) or 0),
            "liquidity": int(getattr(target_allocation, "target_liquidity_bps", 0) or 0),
        },
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
        # Gesamtvermögens-Allokation (IST+SOLL) mit Immobilie als fixem Fundament.
        # Rein additiv/anzeigeseitig — Optimizer/Reserve/Ziele unberührt (2026-07-13).
        "total_allocation": total_allocation_payload,
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
        "risk_budget_bps": risk_budget_bps,
        "risky_fraction_total_bps": risky_fraction_total_bps,
        "risky_fraction_headroom_bps": risk_budget_bps - int(risky_fraction_total_bps),
        "limiting_factor": limiting_factor,
        "goal_achievability": goal_achievability,
        "messages": messages,
        "warnings": warnings,
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
        "current_goal_analysis": current_goal_analysis,
        "mandate_score": _build_mandate_score(goal_analysis),
        # Phase 6: Stress-Auswertungen fuer FE-Optimizer-Panel.
        # V3 Sprint 1: Im Shadow-Modus nicht im Top-Level stress_evaluations
        # (das gehoert zur aktiven TargetAllocation = House Matrix).
        # Shadow-Stress wird ggf. in allocation_method_comparison gehaengt.
        "stress_evaluations": (
            optimizer_result.stress_evaluations
            if (optimizer_mode == "stochastic" and optimizer_result is not None)
            else None
        ),
        "allocation_method_comparison": allocation_method_comparison,
        # V3 Sprint 1d: Constraint Slacks + Goal Drivers fuer die aktive
        # Allocation. Leere Listen wenn der Solver nicht lief.
        "optimizer_constraints": optimizer_constraints,
        "optimizer_goal_drivers": optimizer_goal_drivers,
    }


def evaluate_goal_sensitivity(
    db: Session,
    mandate: Mandate,
    user_id: str,
    goal_id: str,
    target_delta_pct: int,
    horizon_delta_years: int = 0,
) -> dict:
    """Phase 6 FE-Sensitivity-Analyse: ein einzelnes Goal um ±delta% verschieben.

    Sprint U-P5 Fix H9: zusaetzlich horizon_delta_years — perturbiert den
    Goal-Horizont (target_date verschiebt sich um N Jahre, horizon_years
    wird angepasst). Damit kann der Berater fragen: "Was wenn der Klient
    5 Jahre frueher in Rente geht?".

    Laeuft den Solver zweimal mit identischem Seed:
      1. Baseline mit unveraenderten Goal-Werten
      2. Modifiziert: target_amount * (1+delta/100) UND horizon ± horizon_delta_years

    Identischer Seed -> identische Scenarios -> sauberes Apples-to-Apples-Delta.

    Raises ValueError bei:
      - settings.optimizer_mode nicht in {'stochastic', 'shadow_stochastic'}
      - kein Risikoprofil
      - goal_id gehoert nicht zum Mandanten / nicht aktiv
      - target_delta_pct nicht in {-20,-10,0,10,20}
      - horizon_delta_years nicht in [-10, +10] (entspricht Berater-UI-Slider)
    """
    if settings.optimizer_mode not in {"stochastic", "shadow_stochastic"}:
        raise ValueError(
            "Sensitivity-Analyse erfordert OPTIMIZER_MODE=stochastic oder shadow_stochastic."
        )
    if target_delta_pct not in (-20, -10, 0, 10, 20):
        raise ValueError(
            f"target_delta_pct {target_delta_pct} ungueltig "
            "(erlaubt: -20, -10, 0, 10, 20)."
        )
    if horizon_delta_years < -10 or horizon_delta_years > 10:
        raise ValueError(
            f"horizon_delta_years {horizon_delta_years} ungueltig "
            "(erlaubt: -10..+10)."
        )

    jurisdiction = resolve_mandate_jurisdiction(mandate)
    policy, cma = ensure_runtime_reference_data(
        db, user_id, jurisdiction=jurisdiction, tenant_id=getattr(mandate, "tenant_id", None) or None,
    )
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
        "sensitivity", target_goal.id, target_delta_pct, horizon_delta_years,
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
            max_risky_fraction_bps=int(house_matrix.max_risky_fraction_bps),
        )

    # ---- Baseline ----
    baseline_amount = int(target_goal.target_amount_rappen or 0)
    baseline_wealth = int(target_goal.target_wealth_rappen or 0)
    baseline_result = _solve(goals)

    # ---- Modified ----
    # Sprint U-P5 Fix H9: target-amount + horizon perturbieren
    factor = 1.0 + (target_delta_pct / 100.0)
    new_amount = int(round(baseline_amount * factor))
    new_wealth = int(round(baseline_wealth * factor))
    original_amount = target_goal.target_amount_rappen
    original_wealth = target_goal.target_wealth_rappen
    original_horizon = target_goal.horizon_years
    original_target_date = target_goal.target_date
    new_horizon = original_horizon
    new_target_date = original_target_date
    if horizon_delta_years and original_horizon is not None:
        new_horizon = max(1, int(original_horizon) + int(horizon_delta_years))
    if horizon_delta_years and original_target_date:
        try:
            from datetime import date as _date2
            parts = str(original_target_date).split("-")
            if len(parts) >= 1 and parts[0].isdigit():
                shifted_year = int(parts[0]) + int(horizon_delta_years)
                tail = "-".join(parts[1:]) if len(parts) > 1 else "01-01"
                new_target_date = f"{shifted_year}-{tail}"
        except Exception:
            new_target_date = original_target_date
    try:
        target_goal.target_amount_rappen = new_amount
        target_goal.target_wealth_rappen = new_wealth
        if horizon_delta_years:
            target_goal.horizon_years = new_horizon
            target_goal.target_date = new_target_date
        modified_result = _solve(goals)
    finally:
        # Reset to ensure DB-side state isn't accidentally persisted by caller.
        target_goal.target_amount_rappen = original_amount
        target_goal.target_wealth_rappen = original_wealth
        target_goal.horizon_years = original_horizon
        target_goal.target_date = original_target_date

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
        # Sprint U-P5 Fix H9: horizon-Delta exponiert
        "horizon_delta_years": int(horizon_delta_years),
        "horizon_years_baseline": int(original_horizon) if original_horizon is not None else None,
        "horizon_years_new": int(new_horizon) if new_horizon is not None else None,
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
    prefs = _normalize_preferences(
        preferences if preferences is not None else _allocation_snapshot_preferences(allocation)
    )
    # Sprint B1: Mandanten-Default-Building-Blocks als Fallback (rebuild path).
    prefs = _merge_mandate_defaults_into_prefs(prefs, mandate)
    # WP2 (Engine-Wiring Jurisdiktion, 2026-07-31): siehe generate_target_allocation.
    jurisdiction = resolve_mandate_jurisdiction(mandate)
    score_bucket = _risk_score_bucket(assessment)
    house_matrix = _house_matrix_or_default(db, policy, score_bucket)
    # Sprint B3 (2026-06-07): Multi-Currency-Conversion (siehe _load_allocation_inputs).
    # 2026-07-24 (Generalaudit): siehe _load_allocation_inputs -- Fallback auf
    # FXRateSource() statt None, konsistent zum dortigen Fix.
    # 2026-07-27 (WealthPosition-FX-Fix): Setup nach oben verschoben, damit
    # auch _summarize_positions dieselbe FX-Quelle nutzen kann (siehe
    # _load_allocation_inputs fuer die ausfuehrliche Begruendung).
    from services.currency.fx_rates import FXRateSource
    fx_source = None
    try:
        fx_source = FXRateSource.from_db(db)
    except Exception:
        fx_source = FXRateSource()
    target_currency = str(getattr(mandate, "base_currency", "CHF") or "CHF").upper()

    all_positions = db.query(WealthPosition).filter(
        WealthPosition.client_id == mandate.client_id,
        WealthPosition.deleted_at.is_(None),
        WealthPosition.is_active == 1,
    ).all()
    advisory_positions = [pos for pos in all_positions if _norm_text(pos.assignment) == "Beratungsvermoegen"]
    asset_positions_total = [pos for pos in all_positions if _norm_text(pos.assignment) != "Verbindlichkeit"]
    liability_positions = [pos for pos in all_positions if _norm_text(pos.assignment) == "Verbindlichkeit"]
    advisory_summary = _summarize_positions(advisory_positions, fx_source=fx_source, target_currency=target_currency)
    total_summary = _summarize_positions(asset_positions_total, fx_source=fx_source, target_currency=target_currency)
    advisory_wealth_rappen = advisory_summary.total_rappen
    total_liabilities_rappen = sum(
        _convert_position_amount_to_target_currency(pos, fx_source, target_currency)
        for pos in liability_positions
    )
    total_wealth_rappen = max(0, total_summary.total_rappen - total_liabilities_rappen)
    # Sprint B2: Anderes-Vermoegen-Schloss-Pool fuer Reserve-Reduktion (rebuild path).
    unlocked_other_assets_rappen = sum(
        _convert_position_amount_to_target_currency(pos, fx_source, target_currency)
        for pos in all_positions
        if int(getattr(pos, "is_available_for_goal_funding", 0) or 0) == 1
        and _norm_text(getattr(pos, "assignment", "")) == "Anderes Vermoegen"
    )

    cashflows = db.query(Cashflow).filter(
        Cashflow.client_id == mandate.client_id,
        Cashflow.deleted_at.is_(None),
        Cashflow.is_active == 1,
    ).all()
    # 2026-06-14: vermögensgetriebene Cashflows (Hypothekarzins, Amortisation,
    # Miet-/Zinserträge) AUCH im Rebuild-/Recommendation-Pfad einspeisen — sonst
    # rechnete build_target_payload_from_allocation mit unvollständigen Cashflows
    # (inkonsistent zu _load_allocation_inputs). Reserve/Empfehlung sehen damit
    # dieselben Cashflows wie Cashflow-Ansicht und Engine-Projektion.
    cashflows = list(cashflows) + derive_wealth_cashflows(all_positions)

    goals = db.query(Goal).filter(
        Goal.mandate_id == mandate.id,
        Goal.deleted_at.is_(None),
        Goal.is_active == 1,
    ).order_by(Goal.rank.asc()).all()
    cashflow_totals = totals_for_year(
        cashflows, fx_source=fx_source, target_currency=target_currency,
    )
    recurring_income_rappen = cashflow_totals["recurring_income_rappen"]
    recurring_expense_rappen = cashflow_totals["recurring_expense_rappen"]
    capital_inflow_rappen = cashflow_totals["capital_inflow_rappen"]
    capital_outflow_rappen = cashflow_totals["capital_outflow_rappen"]
    recurring_net_cashflow_rappen = recurring_income_rappen - recurring_expense_rappen
    capital_net_cashflow_rappen = capital_inflow_rappen - capital_outflow_rappen
    annual_net_cashflow_rappen = cashflow_totals["net_rappen"]
    projection_years = _simulation_horizon_years(prefs["simulation"], goals, mandate)
    # B1: Cashflow-Series mit CMA-Inflations-Pfad (siehe _load_allocation_inputs).
    cf_inflation_series_bps = _inflation_path_series(cma, projection_years, cashflow_totals["year"])
    cashflow_projection_series_rappen = net_cashflow_series(
        cashflows,
        projection_years,
        start_year=cashflow_totals["year"],
        inflation_series_bps=cf_inflation_series_bps,
        fx_source=fx_source,
        target_currency=target_currency,
    )
    recurring_cashflow_projection_series_rappen = recurring_net_cashflow_series(
        cashflows,
        projection_years,
        start_year=cashflow_totals["year"],
        inflation_series_bps=cf_inflation_series_bps,
        fx_source=fx_source,
        target_currency=target_currency,
    )
    # Sprint U-P2 Fix H11: WealthInflows im rebuild-Pfad auch laden,
    # damit Reserve konsistent zum generate-Pfad rechnet.
    try:
        from models.wealth import WealthInflow as _WealthInflow
        rebuild_wealth_inflows = db.query(_WealthInflow).filter(
            _WealthInflow.client_id == mandate.client_id,
            _WealthInflow.deleted_at.is_(None),
            _WealthInflow.is_active == 1,
        ).all()
    except Exception:
        rebuild_wealth_inflows = []
    inflow_projection_series_rappen = _wealth_inflow_series_rappen(
        rebuild_wealth_inflows, projection_years, cashflow_totals["year"], cf_inflation_series_bps,
    )
    # ebenso wie generate-Pfad: Inflows in cashflow_projection einrechnen
    if any(inflow_projection_series_rappen):
        cashflow_projection_series_rappen = [
            int(cf) + int(infl)
            for cf, infl in zip(cashflow_projection_series_rappen, inflow_projection_series_rappen)
        ]
    # 2026-06-14 (#31): Hypothek-Amortisation/Refinanzierung jahresabhängig in die
    # Projektion einrechnen — direkt: sinkende Zinslast; Refi auf 3% nach Ablauf
    # (Fix) bzw. 5 Jahren (SARON). Additiv auf das Netto-Cashflow-Series; die
    # heutige Cashflow-Ansicht/Summe bleibt unberührt (statischer Posten = Jahr 0).
    _mortgage_interest_adj = mortgage_interest_adjustment_series(
        all_positions, projection_years, cashflow_totals["year"],
    )
    if any(_mortgage_interest_adj):
        cashflow_projection_series_rappen = [
            int(cf) + int(adj)
            for cf, adj in zip(cashflow_projection_series_rappen, _mortgage_interest_adj)
        ]

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

    # WP-A (2026-08-01): jurisdiction durchgereicht (siehe generate_target_allocation).
    building_block_rows = _building_block_rows_for_policy(
        db,
        policy.id,
        getattr(mandate, "investment_universe", None),
        jurisdiction,
    )
    risky_map = _building_block_risky_map(db, policy.id, getattr(mandate, "investment_universe", None), jurisdiction)
    sub_allocations = _build_sub_allocations(targets, prefs, jurisdiction=jurisdiction, db=db)
    sub_allocations, asset_risky_weights, risky_fraction_total_bps = _enrich_sub_allocations_with_risk(sub_allocations, risky_map)
    persisted_risky_bps = getattr(allocation, "risky_fraction_bps_at_generation", None)
    if persisted_risky_bps is not None:
        risky_fraction_total_bps = int(persisted_risky_bps)
    else:
        risky_fraction_total_bps = compute_portfolio_risky_fraction_bps(targets, building_block_rows)
    risk_budget_bps = int(
        getattr(allocation, "risk_budget_bps_at_generation", None)
        if getattr(allocation, "risk_budget_bps_at_generation", None) is not None
        else int(house_matrix.max_risky_fraction_bps or 0)
    )
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
        unlocked_other_assets_rappen=unlocked_other_assets_rappen,
        # Sprint U-P2 Fix H11: Wealth-Inflows in Reserve berücksichtigen (rebuild-Pfad)
        inflow_projection_series_rappen=inflow_projection_series_rappen,
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
        # Sprint U-P5 Fix H12: Mortality-Cutoff
        expected_death_year_offset=_expected_death_year_offset_from_mandate(mandate),
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
    current_goal_analysis = _merge_goal_analysis_with_monte_carlo(
        goal_analysis,
        monte_carlo,
        summaries_key="current_goal_summaries",
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
    persisted_messages: list[dict] = []
    raw_reasoning = getattr(allocation, "optimizer_reasoning_json", None)
    if raw_reasoning:
        try:
            parsed_reasoning = json.loads(raw_reasoning)
            if isinstance(parsed_reasoning, list):
                for item in parsed_reasoning:
                    if isinstance(item, str) and item:
                        persisted_optimizer_reasoning.append(item)
                    elif isinstance(item, dict):
                        lf = item.get("limiting_factor")
                        driving = item.get("driving_goal_id")
                        if lf or driving:
                            persisted_optimizer_reasoning.append(
                                f"Stage-3 Trace: limiting_factor={lf or '-'}, driving_goal_id={driving or '-'}."
                            )
                        raw_messages = item.get("messages")
                        if isinstance(raw_messages, list):
                            persisted_messages = [
                                msg for msg in raw_messages if isinstance(msg, dict)
                            ]
        except (TypeError, ValueError) as exc:
            logger.warning(
                "Stored optimizer_reasoning_json invalid for allocation %s: %s",
                getattr(allocation, "id", "?"), exc,
            )
    goal_achievability: list[dict] = []
    raw_goal_achievability = getattr(allocation, "goal_achievability_json", None)
    if raw_goal_achievability:
        try:
            parsed_achievability = json.loads(raw_goal_achievability)
            if isinstance(parsed_achievability, list):
                goal_achievability = [
                    item for item in parsed_achievability if isinstance(item, dict)
                ]
        except (TypeError, ValueError) as exc:
            logger.warning(
                "Stored goal_achievability_json invalid for allocation %s: %s",
                getattr(allocation, "id", "?"), exc,
            )
    messages = persisted_messages or classify_messages(
        allocation,
        goal_achievability,
        getattr(allocation, "optimization_status", None),
        mandate,
        assessment,
    )
    total_allocation_payload = _build_total_wealth_allocation(
        total_summary, total_liabilities_rappen, total_wealth_rappen, targets,
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
        # Gesamtvermögens-Allokation (IST+SOLL) mit Immobilie als fixem Fundament.
        # Rein additiv/anzeigeseitig — Optimizer/Reserve/Ziele unberührt (2026-07-13).
        "total_allocation": total_allocation_payload,
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
        "risk_budget_bps": risk_budget_bps,
        "risky_fraction_total_bps": risky_fraction_total_bps,
        "risky_fraction_headroom_bps": risk_budget_bps - int(risky_fraction_total_bps),
        "limiting_factor": getattr(allocation, "limiting_factor", None),
        "goal_achievability": goal_achievability,
        "messages": messages,
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
        "current_goal_analysis": current_goal_analysis,
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
    jurisdiction = resolve_mandate_jurisdiction(mandate)
    policy, cma = ensure_runtime_reference_data(
        db, user_id, jurisdiction=jurisdiction, tenant_id=getattr(mandate, "tenant_id", None) or None,
    )
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






























def generate_recommendation_run(
    db: Session,
    mandate: Mandate,
    user_id: str,
    preferences: dict | None,
    target_allocation_id: str | None = None,
    run_type: str = "Optimizer",
    depot_bank: str | None = None,
) -> dict:
    # WP2 (Engine-Wiring Jurisdiktion, 2026-07-31): einmal pro Lauf aufgeloest.
    jurisdiction = resolve_mandate_jurisdiction(mandate)
    ensure_default_products(db, jurisdiction=jurisdiction)
    prefs = _normalize_preferences(preferences)
    policy, cma = ensure_runtime_reference_data(
        db, user_id, jurisdiction=jurisdiction, tenant_id=getattr(mandate, "tenant_id", None) or None,
    )
    jurisdiction_ctx = _resolve_jurisdiction_context(db, mandate, jurisdiction)
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

    # WP2 (Engine-Wiring Jurisdiktion, 2026-07-31, Aufgabe 6): fuer Nicht-CH-
    # Jurisdiktionen ohne IC-Freigabe (cma.status != "committee_approved")
    # wird ein sichtbarer Provisorik-Hinweis auf dem Run persistiert (NIE
    # stillschweigend, siehe Constraint 3). Fuer CH bleibt das Feld IMMER
    # NULL (unveraendertes Verhalten, kein neuer Status-Pflichtfeld-Zwang
    # auf dem CH-Bestand).
    provisional_data_warning = None
    if jurisdiction not in (None, "CH") and getattr(cma, "status", None) != "committee_approved":
        provisional_data_warning = json.dumps({
            "jurisdiction": jurisdiction,
            "cma_status": getattr(cma, "status", None),
            "message": (
                f"Kapitalmarktannahmen fuer Jurisdiktion '{jurisdiction}' sind noch nicht "
                "vom Investment Committee freigegeben (status="
                f"{getattr(cma, 'status', None)!r}). Diese Empfehlung ist PROVISORISCH und "
                "darf ohne IC-Freigabe nicht als finales Kundendokument verwendet werden."
            ),
        }, ensure_ascii=False)

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
        provisional_data_warning=provisional_data_warning,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    db.flush()

    score_bucket = _risk_score_bucket(assessment)
    products = db.query(Product).filter(Product.deleted_at.is_(None), Product.is_active == 1).all()
    products = _filter_products_by_universe(db, mandate, products)
    sub_allocations = target_payload["sub_allocations"]
    advisory_wealth_rappen = int(target_payload["advisory_wealth_rappen"] or 0)
    investable_advisory_wealth_rappen = int(target_payload.get("investable_advisory_wealth_rappen") or advisory_wealth_rappen)
    warnings = []
    positions_payload = []
    aggregated_positions: dict[str, dict] = {}
    # Sprint 14 Phase 4 F6: fehlende Sub-Klassen sammeln statt still continue
    # → wir wollen NICHT, dass die Summe der Positionen unbemerkt <100% liegt.
    missing_sub_classes: list[dict] = []

    for sub in sub_allocations:
        matching = [
            product for product in products
            if _product_matches_constraints(product, prefs, score_bucket, jurisdiction_ctx=jurisdiction_ctx)
        ]
        exact = [product for product in matching if str(product.sub_asset_class or "") == str(sub["sub_asset_class"])]
        used_fallback = False
        used_suitability_override = False
        candidates = exact
        if not candidates:
            candidates = [product for product in matching if _norm_text(product.asset_class) == _norm_text(sub["asset_class"])]
            used_fallback = bool(candidates)
        if not candidates:
            relaxed_matching = [
                product
                for product in products
                if _product_matches_constraints(
                    product, prefs, score_bucket, ignore_suitability=True, jurisdiction_ctx=jurisdiction_ctx,
                )
            ]
            candidates = [
                product for product in relaxed_matching
                if str(product.sub_asset_class or "") == str(sub["sub_asset_class"])
            ]
            if not candidates:
                candidates = [
                    product for product in relaxed_matching
                    if _norm_text(product.asset_class) == _norm_text(sub["asset_class"])
                ]
                used_fallback = bool(candidates)
            used_suitability_override = bool(candidates)
        if not candidates:
            warnings.append(f"Kein passendes Produkt fuer {sub['sub_asset_class']} gefunden.")
            missing_sub_classes.append({
                "sub_asset_class": str(sub["sub_asset_class"]),
                "asset_class": str(sub["asset_class"]),
                "target_weight_bps": int(sub["target_weight_bps"]),
            })
            continue
        ranked = sorted(
            candidates,
            key=lambda product: _product_score(product, sub["sub_asset_class"], prefs, jurisdiction_ctx=jurisdiction_ctx),
            reverse=True,
        )
        best = ranked[0]
        target_amount = int(round(investable_advisory_wealth_rappen * int(sub["target_weight_bps"]) / 10000))
        rationale = sub["rationale"]
        if used_fallback:
            rationale = rationale + f"; Fallback aus {sub['sub_asset_class']}, da keine geeignete exakte Produktabdeckung verfuegbar war"
            warnings.append(f"{sub['sub_asset_class']}: exakte Produktumsetzung nicht moeglich, Core-Fallback verwendet.")
        if used_suitability_override:
            rationale = rationale + "; Produkt-Suitability ausserhalb Standardband, Beratung/Override dokumentieren"
            warnings.append(
                f"{sub['sub_asset_class']}: Produkt-Suitability liegt ausserhalb des Standard-Risikobands; "
                "Empfehlung nur mit dokumentierter Beratung/Override verwenden."
            )
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

    # Sprint 14 Phase 4 F6: harter Fail wenn Sub-Klassen nicht gefuellt werden konnten.
    # Vorher: stilles continue → Summe der Target-Weights konnte unter 100% liegen
    # ohne dass der Berater es bemerkte. Jetzt: ValueError mit konkreter Liste.
    if missing_sub_classes:
        total_missing_bps = sum(item["target_weight_bps"] for item in missing_sub_classes)
        # Toleranz: bis 50 bps (0.5%) Lücke darf "still" durchlaufen (z.B. einzelne
        # exotische Sub-Class mit 0 Allokation). Alles darüber ist ein echter Fehler.
        if total_missing_bps > 50:
            details = ", ".join(
                f"{item['sub_asset_class']} ({item['target_weight_bps']/100:.1f}%)"
                for item in missing_sub_classes
            )
            raise ValueError(
                f"Produktselektion unvollstaendig: kein passendes Produkt fuer "
                f"{len(missing_sub_classes)} Sub-Klassen ({details}). "
                f"Gesamt-Luecke: {total_missing_bps/100:.1f}%. "
                f"Bitte Produktuniversum erweitern oder Restriktionen "
                f"(chf_only, hedgingRequired, noStructured, noLeverage, ESG) lockern."
            )

    _validate_recommendation_concentration_limits(aggregated_positions, prefs)

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
