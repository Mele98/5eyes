import json
import hashlib
import logging
import math
import random
import time
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

logger = logging.getLogger(__name__)

from sqlalchemy.orm import Session, selectinload

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
from services.calendar_horizon import add_calendar_years, calendar_years_until
from services.goal_semantics import GoalInputError, validate_goal_model_input
from services.cashflow_timeline import (
    SUPPORTED_FREQUENCIES,
    future_value_with_cashflow_series,
    net_cashflow_series,
    normalize_frequency,
    recurring_net_cashflow_series,
    totals_for_year,
)
from services.wealth_cashflows import (
    derive_tax_cashflow,
    derive_wealth_cashflows,
    mortgage_amortization_adjustment_series,
    mortgage_interest_adjustment_series,
)
from services.wealth_position_semantics import (
    canonical_position_type,
    WealthPositionSemanticsError,
    is_direct_real_estate_position,
    is_external_wealth_assignment,
    is_liability_assignment,
    is_mortgage_position,
    mortgage_amortization_mode,
    require_supported_mortgage_amortization,
    require_supported_position_assignment,
)
from services.product_market_data import resolve_market_profile, validate_default_product_market_coverage
from services.planning_horizon import life_expectancy_year_for
from services.jurisdiction.de_seed import (
    DE_DEFAULT_BONDS_DURATION,
    DE_DEFAULT_EQUITIES_GEO,
    DE_DEFAULT_REALESTATE_MARKET,
)
from services.jurisdiction.exceptions import (
    JurisdictionReferenceDataConflictError,
    JurisdictionReferenceDataMissingError,
)
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
from services.risk_assessment_semantics import (
    risk_score_bucket_from_validated_score,
    validate_risk_assessment_model_input,
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


class StaleAllocationInputError(ValueError):
    """Persisted targets no longer match the live strategy inputs.

    This is deliberately more specific than ``ValueError`` so read-only
    monitoring can still evaluate live bucket drift without accidentally
    treating stale goal analytics as current. Strategy/reporting consumers
    must continue to fail closed.
    """

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
    # ``0 == False`` in Python, but 0 bps is a valid explicit hard bound.
    # Reject boolean sentinels by identity without swallowing integer zero.
    if value is None or value == "" or value is False:
        return None
    if isinstance(value, bool):
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
        .strip()
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


def _current_risk_assessment_or_none(
    db: Session,
    mandate_id: str,
    *,
    for_update: bool = False,
    eager_answers: bool = False,
) -> RiskAssessment | None:
    """Resolve an unambiguous current risk-assessment anchor.

    eager_answers=True selectinloads RiskAssessment.answers, analog zu
    list_risk_assessments() -- noetig fuer Aufrufer wie GET .../current,
    deren Response-Model answers serialisiert; die meisten Aufrufer
    (Score-/Budget-Validierung) brauchen answers dagegen nicht und sollen
    diese zusaetzliche Query nicht bezahlen.
    """
    query = db.query(RiskAssessment).filter(
        RiskAssessment.mandate_id == mandate_id,
        RiskAssessment.is_current == 1,
        RiskAssessment.deleted_at.is_(None),
    )
    if eager_answers:
        query = query.options(selectinload(RiskAssessment.answers))
    if for_update:
        query = query.with_for_update()
    candidates = query.all()
    if len(candidates) > 1:
        raise ValueError(
            "Mehrere aktuelle Risikoprofile gefunden; der Score- und "
            "Risikobudget-Anker ist nicht eindeutig."
        )
    return candidates[0] if candidates else None


def _current_target_allocation_or_none(
    db: Session,
    mandate_id: str,
    *,
    for_update: bool = False,
) -> TargetAllocation | None:
    """Resolve one current strategy decision or fail on ambiguous state."""
    query = db.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate_id,
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    candidates = query.all()
    if len(candidates) > 1:
        raise ValueError(
            "Mehrere aktuelle Soll-Allokationen gefunden; der aktive "
            "Strategieentscheid ist nicht eindeutig."
        )
    return candidates[0] if candidates else None


def require_strategy_ready_assessment(db: Session, mandate_id: str) -> RiskAssessment:
    assessment = _current_risk_assessment_or_none(db, mandate_id)
    if not assessment:
        raise ValueError("Bitte zuerst ein aktuelles Risikoprofil speichern.")
    mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
    validate_risk_assessment_model_input(
        assessment,
        mandate_type=getattr(mandate, "mandate_type", None),
    )
    if not risk_assessment_ready_for_strategy(assessment):
        raise ValueError(
            "Risikoprofil unvollstaendig. Bitte Fragebogen vollstaendig ausfuellen und erneut speichern."
        )
    return assessment


def _normalize_preferences(preferences: dict | None) -> dict:
    # Einzige Stelle, an der rohe preferences-dicts (API, Sensitivity, Reload,
    # direkte Service-Aufrufer) auf das AllocationPreferencesPayload-Vokabular
    # validiert werden. Der FastAPI-Router validiert body.preferences zwar
    # bereits, aber alle anderen Aufrufer (Snapshot-Reload, Sensitivity-Analyse,
    # Tests, advisory_report.py) reichten preferences bisher als ungeprueftes
    # dict durch -- ein Tippfehler blieb dort stillschweigend wirkungslos.
    from schemas.allocation import AllocationPreferencesPayload

    # Only an absent value means "use defaults".  Falsey non-objects ([], "")
    # are malformed trust-boundary input and must not collapse to {}.
    validated = AllocationPreferencesPayload.model_validate(
        {} if preferences is None else preferences
    )
    return validated.model_dump()


def _allocation_snapshot_preferences(allocation: TargetAllocation | None) -> dict | None:
    if allocation is None:
        return None
    raw = getattr(allocation, "preferences_json", None)
    # NULL is the sole legacy "no snapshot" representation.  A present but
    # malformed value is damaged persisted model input, not a default request.
    if raw is None:
        return None
    if not str(raw).strip():
        raise ValueError(
            "Persistierte Allocation-Praeferenzen enthalten kein gueltiges JSON."
        )
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Persistierte Allocation-Praeferenzen enthalten kein gueltiges JSON."
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError(
            "Persistierte Allocation-Praeferenzen muessen ein JSON-Objekt sein."
        )
    return parsed


def _merge_mandate_defaults_into_prefs(prefs: dict, mandate) -> dict:
    """Sprint B1 (2026-05-07): persistierte Building-Block-Wahl pro Mandat als
    Fallback in die preferences mergen.

    Wenn der Aufrufer keine expliziten asset_class-/geo-prefs setzt, wird die
    Mandanten-Default-Wahl (default_building_blocks_json) genutzt. Explizite
    prefs ueberschreiben Mandanten-Defaults nicht (UI-Wahl ist authoritativ).
    """
    if mandate is None:
        return prefs
    from services.mandate_preferences import parse_default_building_blocks_json

    defaults = parse_default_building_blocks_json(
        getattr(mandate, "default_building_blocks_json", None),
        jurisdiction=getattr(mandate, "jurisdiction", None),
    )
    if not defaults:
        return prefs
    asset_keys = set(defaults) - {"noEm"}
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
    # ``0 == False`` in Python, but 0 bps is a valid explicit hard bound.
    if value is None or value == "" or value is False:
        return None
    if isinstance(value, bool):
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
    score_x10 = validate_risk_assessment_model_input(assessment)
    # Validierung 2026-06-11 (#AA-9): round-half-up statt Banker's-round() — sonst
    # bricht die Monotonie an .5-Grenzen (45->4 statt 5, 65->6 statt 7) und divergiert
    # vom Profil-Namen-Mapping (risk_scoring._profile_from_score nutzt floor(x+0.5)).
    # int(x+0.5) == floor(x+0.5) fuer positive Scores.
    return risk_score_bucket_from_validated_score(score_x10)


def _default_weights_for_position(position: WealthPosition) -> dict[str, int]:
    canonical_type = canonical_position_type(position.position_type)
    total = (
        int(position.alloc_equities_bps or 0)
        + int(position.alloc_bonds_bps or 0)
        + int(position.alloc_real_estate_bps or 0)
        + int(position.alloc_alternatives_bps or 0)
        + int(position.alloc_liquidity_bps or 0)
    )
    if _norm_text(canonical_type) == "Depot" and total == 10000:
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
    if is_direct_real_estate_position(position.position_type):
        return mapping["Immobilien"].copy()
    return mapping.get(
        _norm_text(canonical_type),
        mapping["Custom"],
    ).copy()


def _convert_position_value_to_target_currency(
    value_rappen: int,
    pos,
    fx_source,
    target_currency: str,
) -> int:
    """Convert an arbitrary position-denominated amount to target currency."""
    raw_amount = int(value_rappen or 0)
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
    except (ValueError, AttributeError) as exc:
        label = str(getattr(pos, "label", "") or "").strip()
        raise ValueError(
            f"Keine gueltige FX-Rate fuer Position '{label or pos_currency}' "
            f"({pos_currency}->{target}); eine stille 1:1-Konvertierung ist "
            "nicht zulaessig."
        ) from exc
    return int(round(raw_amount * float(rate)))


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
    return _convert_position_value_to_target_currency(
        getattr(pos, "current_value_rappen", 0),
        pos,
        fx_source,
        target_currency,
    )


def _effective_fx_rate_signature(
    *,
    fx_source,
    target_currency: str,
    positions: list,
    cashflows: list,
    wealth_inflows: list | None = None,
) -> list[list[object]]:
    """Return the exact conversion factors used by active model inputs."""
    target = str(target_currency or "CHF").upper().strip()
    currencies = {target}
    for row in [*(positions or []), *(cashflows or []), *(wealth_inflows or [])]:
        currency = str(getattr(row, "currency", "") or target).upper().strip()
        currencies.add(currency or target)
    signature: list[list[object]] = []
    for currency in sorted(currencies):
        try:
            rate = float(fx_source.cross_rate(currency, target))
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                f"Keine gueltige FX-Rate fuer {currency}->{target}; der "
                "Projektionskontext kann nicht kanonisch gebildet werden."
            ) from exc
        if not math.isfinite(rate) or rate <= 0.0:
            raise ValueError(
                f"Ungueltige FX-Rate fuer {currency}->{target}: {rate}."
            )
        signature.append([currency, int(round(rate * 100_000_000))])
    return signature


def _validate_active_wealth_position_semantics(positions: list) -> None:
    """Reject legacy/raw rows that bypassed API classification validation."""
    for position in positions or []:
        if getattr(position, "deleted_at", None):
            continue
        if int(getattr(position, "is_active", 1) or 0) != 1:
            continue
        try:
            require_supported_position_assignment(
                getattr(position, "position_type", None),
                getattr(position, "assignment", None),
            )
            require_supported_mortgage_amortization(
                getattr(position, "position_type", None),
                getattr(position, "mortgage_amortization_rappen", 0),
                getattr(position, "mortgage_amortization_type", None),
            )
            if is_direct_real_estate_position(
                getattr(position, "position_type", None)
            ):
                raw_return = getattr(position, "asset_expected_return_bps", None)
                if isinstance(raw_return, bool):
                    raise WealthPositionSemanticsError(
                        "Immobilien-Wertsteigerung muss als Basispunktzahl "
                        "und nicht als Bool-Wert erfasst werden."
                    )
                if raw_return is not None:
                    try:
                        return_bps = int(raw_return)
                    except (TypeError, ValueError) as exc:
                        raise WealthPositionSemanticsError(
                            "Immobilien-Wertsteigerung muss als ganzzahlige "
                            "Basispunktzahl erfasst werden."
                        ) from exc
                    if return_bps <= -10_000 or return_bps > 100_000:
                        raise WealthPositionSemanticsError(
                            "Immobilien-Wertsteigerung muss grösser als -100 % "
                            "und höchstens 1'000 % sein."
                        )
        except WealthPositionSemanticsError as exc:
            from services.optimizer.constraints import OptimizerInputError

            label = str(getattr(position, "label", "") or "").strip()
            prefix = f"Vermögensposition '{label}': " if label else ""
            raise OptimizerInputError(prefix + str(exc)) from exc


def _strictly_active_rows(rows: list, *, label: str) -> list:
    """Validate raw integer activity flags before filtering model inputs.

    SQL filters such as ``is_active == 1`` turn corrupt legacy values into
    invisible rows.  For strategy inputs that is unsafe: a position, cashflow
    or goal with ``is_active=2`` must not silently disappear from the model.
    """
    active_rows = []
    for row in rows or []:
        raw = getattr(row, "is_active", None)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw not in (0, 1):
            row_id = str(getattr(row, "id", "") or "").strip()
            suffix = f" ({row_id})" if row_id else ""
            raise ValueError(
                f"{label}{suffix}: is_active muss exakt 0 oder 1 sein."
            )
        if raw == 1:
            active_rows.append(row)
    return active_rows


def _parse_strict_model_date(value, *, label: str) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: ungueltiges ISO-Datum {value!r}.") from exc


def _validate_active_cashflow_inputs(cashflows: list) -> None:
    """Reject cashflow rows that the timeline would otherwise reinterpret."""
    for cashflow in cashflows or []:
        label = str(getattr(cashflow, "label", "") or "Cashflow").strip()
        cashflow_type = str(getattr(cashflow, "cashflow_type", "") or "").strip()
        if cashflow_type not in {"Income", "Expense"}:
            raise ValueError(
                f"Cashflow '{label}': unbekannter cashflow_type {cashflow_type!r}."
            )
        amount = getattr(cashflow, "amount_rappen", None)
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ValueError(
                f"Cashflow '{label}': amount_rappen muss eine nichtnegative "
                "Ganzzahl sein."
            )
        frequency = normalize_frequency(getattr(cashflow, "frequency", None))
        if frequency not in SUPPORTED_FREQUENCIES:
            raise ValueError(
                f"Cashflow '{label}': unbekannte Frequenz "
                f"{getattr(cashflow, 'frequency', None)!r}."
            )
        nature = str(getattr(cashflow, "nature", "") or "").strip()
        if nature not in {"wiederkehrend", "einmalig"}:
            raise ValueError(
                f"Cashflow '{label}': unbekannte Art {nature!r}."
            )
        inflation_flag = getattr(cashflow, "is_inflation_linked", None)
        if (
            isinstance(inflation_flag, bool)
            or not isinstance(inflation_flag, int)
            or inflation_flag not in (0, 1)
        ):
            raise ValueError(
                f"Cashflow '{label}': is_inflation_linked muss exakt 0 oder 1 sein."
            )
        valid_from = _parse_strict_model_date(
            getattr(cashflow, "valid_from", None),
            label=f"Cashflow '{label}' Startdatum",
        )
        valid_until = _parse_strict_model_date(
            getattr(cashflow, "valid_until", None),
            label=f"Cashflow '{label}' Enddatum",
        )
        if valid_from and valid_until and valid_until < valid_from:
            raise ValueError(
                f"Cashflow '{label}': Enddatum darf nicht vor dem Startdatum liegen."
            )
        if (frequency == "einmalig" or nature == "einmalig") and not (
            valid_from or valid_until
        ):
            raise ValueError(
                f"Cashflow '{label}': einmalige Cashflows benoetigen ein Datum."
            )


_SUPPORTED_GOAL_TYPE_KEYS = frozenset(
    {
        "kapitalerhalt",
        "vermoegensziel",
        "einmalige_ausgabe",
        "wiederkehrende_ausgabe",
        "pensionsausgabe",
        "renditeziel",
        "maximierung",
    }
)


def _goal_type_key_for_runtime(value) -> str:
    return _norm_text(value).strip().lower().replace(" ", "_")


def _validate_active_goal_inputs(goals: list) -> None:
    """Validate goal rows before liability construction can soften them."""
    for goal in goals or []:
        label = str(getattr(goal, "label", "") or "Ziel").strip()
        goal_type = _goal_type_key_for_runtime(getattr(goal, "goal_type", None))
        if goal_type not in _SUPPORTED_GOAL_TYPE_KEYS:
            raise ValueError(
                f"Ziel '{label}': unbekannter Zieltyp "
                f"{getattr(goal, 'goal_type', None)!r}."
            )
        ongoing = getattr(goal, "is_ongoing", None)
        if isinstance(ongoing, bool) or not isinstance(ongoing, int) or ongoing not in (0, 1):
            raise ValueError(
                f"Ziel '{label}': is_ongoing muss exakt 0 oder 1 sein."
            )
        start = _parse_strict_model_date(
            getattr(goal, "start_date", None),
            label=f"Ziel '{label}' Startdatum",
        )
        target = _parse_strict_model_date(
            getattr(goal, "target_date", None),
            label=f"Ziel '{label}' Zieldatum",
        )
        if start and target and target < start:
            raise ValueError(
                f"Ziel '{label}': Zieldatum darf nicht vor dem Startdatum liegen."
            )
        if goal_type in {"wiederkehrende_ausgabe", "pensionsausgabe"}:
            frequency = normalize_frequency(getattr(goal, "frequency", None))
            if frequency not in SUPPORTED_FREQUENCIES or frequency == "einmalig":
                raise ValueError(
                    f"Ziel '{label}': unbekannte oder unzulaessige Frequenz "
                    f"{getattr(goal, 'frequency', None)!r}."
                )
        probability = getattr(goal, "probability_pct", None)
        if probability is not None and (
            isinstance(probability, bool)
            or not isinstance(probability, int)
            or not 0 <= probability <= 100
        ):
            raise ValueError(
                f"Ziel '{label}': probability_pct muss ganzzahlig zwischen 0 und 100 liegen."
            )
        try:
            validate_goal_model_input(goal)
        except GoalInputError as exc:
            raise ValueError(str(exc)) from exc


def _build_external_foundation_projection(
    positions: list,
    *,
    horizon_years: int,
    fx_source=None,
    target_currency: str = "CHF",
) -> dict[str, list[int]]:
    """Project direct property and mortgage principal outside listed-RE CMA.

    Direct-property appreciation is position-specific. Rent is deliberately
    absent here because it already enters the common cashflow series. Direct
    mortgage amortization lowers outstanding debt at the same time as its
    cash outflow lowers financial assets, keeping principal repayment neutral
    for total net wealth.
    """
    horizon = max(0, int(horizon_years or 0))
    _validate_active_wealth_position_semantics(positions)
    property_series = [0] * (horizon + 1)
    liability_series = [0] * (horizon + 1)
    pledged_asset_series = [0] * (horizon + 1)

    for position in positions or []:
        if getattr(position, "deleted_at", None):
            continue
        if int(getattr(position, "is_active", 1) or 0) != 1:
            continue
        position_type = getattr(position, "position_type", "")
        assignment = getattr(position, "assignment", "")
        value = max(
            0,
            _convert_position_amount_to_target_currency(
                position,
                fx_source,
                target_currency,
            ),
        )

        if (
            is_direct_real_estate_position(position_type)
            and is_external_wealth_assignment(assignment)
        ):
            rate_bps = int(
                getattr(position, "asset_expected_return_bps", 0) or 0
            )
            current = value
            property_series[0] += current
            growth_factor = 1.0 + rate_bps / 10000.0
            for year in range(1, horizon + 1):
                current = int(round(current * growth_factor))
                property_series[year] += current
            continue

        if not is_liability_assignment(assignment):
            continue
        is_mortgage = is_mortgage_position(position_type)
        amortization_type = getattr(
            position,
            "mortgage_amortization_type",
            None,
        )
        amortization_mode = (
            mortgage_amortization_mode(amortization_type)
            if is_mortgage
            else "none"
        )
        amortization = 0
        if is_mortgage and amortization_mode in {"direct", "indirect"}:
            amortization = max(
                0,
                _convert_position_value_to_target_currency(
                    getattr(position, "mortgage_amortization_rappen", 0),
                    position,
                    fx_source,
                    target_currency,
                ),
            )
        for year in range(horizon + 1):
            if amortization_mode == "direct":
                outstanding = max(0, value - amortization * year)
            else:
                outstanding = value
            liability_series[year] += outstanding
            if amortization_mode == "indirect":
                # Indirect amortization transfers advisory cash into a pledged
                # pension asset. It does not reduce the mortgage, but it is not
                # consumption in the total-wealth view either.
                pledged_asset_series[year] += min(value, amortization * year)

    return {
        "property_series_rappen": property_series,
        "liability_series_rappen": liability_series,
        "pledged_asset_series_rappen": pledged_asset_series,
    }


def _build_external_goal_funding_series(
    *,
    external_gross_assets_rappen: int,
    external_foundation_projection: dict[str, list[int]],
    inflation_series_bps: list[int],
    horizon_years: int,
) -> list[int]:
    """Build the optimizer's conservative external net-funding path.

    External gross assets retain the established zero-real/CPI convention for
    allocation selection. Liabilities and pledged indirect-amortization assets
    use the exact canonical foundation series, so principal transfers cannot be
    mistaken for consumption in total-scope goals.
    """
    horizon = max(0, int(horizon_years or 0))
    required_length = horizon + 1
    liability_series = list(
        external_foundation_projection.get("liability_series_rappen") or []
    )
    pledged_series = list(
        external_foundation_projection.get("pledged_asset_series_rappen")
        or []
    )
    if (
        len(liability_series) != required_length
        or len(pledged_series) != required_length
    ):
        from services.optimizer.constraints import OptimizerInputError

        raise OptimizerInputError(
            "Die externe Foundation-Serie deckt den Optimizer-Horizont nicht "
            "vollstaendig ab."
        )
    gross_start = max(0, int(external_gross_assets_rappen or 0))
    return [
        int(
            _external_assets_inflation_value(
                gross_start,
                year,
                inflation_series_bps,
            )
            + int(pledged_series[year])
            - int(liability_series[year])
        )
        for year in range(required_length)
    ]


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


# ADR-014 Schritt 8 (2026-08-03, letzter Schritt): House-Matrix/Tilt-Cluster
# (am staerksten verflochten, 24 Namen) extrahiert nach
# services/portfolio_engine_house_matrix.py (0 Zeilen Fachlogik-Aenderung,
# Byte-fuer-Byte-Kopie, per Diff-Skript verifiziert). Diese Extraktion
# schliesst den ADR-014-Split ab: portfolio_engine.py enthaelt danach nur
# noch CORE-Helfer + die 5 Orchestratoren (generate_target_allocation,
# evaluate_goal_sensitivity, build_target_payload_from_allocation,
# build_recommendation_payload_from_run, generate_recommendation_run).
# _apply_goal_and_reserve_tilts ruft weiterhin unveraendert in den
# Reserve-Cluster (_compute_reserve_for_inputs, Schritt 4) hinein -- die
# zentrale Cross-Bucket-Bruecke funktioniert dank Re-Export-Kette
# unveraendert. _house_matrix_or_default/_baseline_target_bands/
# _build_sub_allocations/_enrich_sub_allocations_with_risk/
# _building_block_risky_map werden extern importiert von
# services/backtest_ab.py UND routers/wealth.py (calculate_max_pension_
# spending) -- der zweite Konsument wurde beim Draften dieses Schritts
# gefunden, nicht im urspruenglichen ADR-014 gelistet.
from services.portfolio_engine_house_matrix import (  # noqa: F401,E402
    _apply_band_min_max_overrides,
    _apply_band_preferences,
    _apply_external_exposure_tilts,
    _apply_goal_and_reserve_tilts,
    _apply_illiquid_cap,
    _asset_risky_weight_fallbacks,
    _baseline_target_bands,
    _building_block_risky_map,
    _building_block_rows_for_policy,
    _build_stochastic_sub_allocation_plan,
    _build_sub_allocations,
    _enforce_risk_budget,
    _enrich_sub_allocations_with_risk,
    _growth_goals_for_equity_tilt,
    _has_manual_target_overrides,
    _house_matrix_mid_targets,
    _house_matrix_or_default,
    _normalize_house_matrix_defaults,
    _normalize_splits,
    _materialize_sub_allocation_plan,
    _preference_choice,
    _rebalance_to_total,
    _renditeziel_equity_tilt_bps,
    _risk_budget_from_targets,
    _seed_building_blocks,
    _seed_house_matrix_rows,
    _validate_house_matrix_defaults,
)



















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
    _validate_sub_cma_universe,
    _weighted_bucket_metrics,
)


















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










# 3eyes-Methodik (drei augen.pdf): Illiquiditaet ist eine Eigenschaft des
# Bausteins, kein pauschaler Alternatives-Deckel. Direktimmobilien werden
# bereits ueber das Gesamtvermoegen (extern) gefuehrt und nicht umgeschichtet;
# der einzige illiquide Baustein INNERHALB der handelbaren SAA ist Private Equity.
_ILLIQUID_SUB_ASSET_CLASSES = {"private equity"}














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

    policy_candidates = db.query(OptimizerPolicy).filter(
        OptimizerPolicy.is_current == 1
    ).all()
    if len(policy_candidates) > 1:
        raise JurisdictionReferenceDataConflictError(
            "Mehrere aktuelle OptimizerPolicy-Zeilen gefunden; die "
            "Constraint-Basis ist nicht eindeutig."
        )
    policy = policy_candidates[0] if policy_candidates else None
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
    policy_candidates = db.query(OptimizerPolicy).filter(
        OptimizerPolicy.is_current == 1
    ).all()
    if len(policy_candidates) > 1:
        raise JurisdictionReferenceDataConflictError(
            "Mehrere aktuelle OptimizerPolicy-Zeilen gefunden; die "
            "Constraint-Basis ist nicht eindeutig."
        )
    policy = policy_candidates[0] if policy_candidates else None
    if not policy:
        if settings.app_env == "production":
            raise JurisdictionReferenceDataMissingError(
                "In Produktion fehlen freigegebene OptimizerPolicy-"
                "Referenzdaten. Runtime-Autoseeding ist nicht zulaessig."
            )
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

    try:
        cma = resolve_cma_for_jurisdiction(db, "CH")
    except JurisdictionReferenceDataMissingError:
        cma = None
    if not cma:
        if settings.app_env == "production":
            raise JurisdictionReferenceDataMissingError(
                "In Produktion fehlt eine aktuelle CH-CMA. Runtime-"
                "Autoseeding mit Hausannahmen ist nicht zulaessig."
            )
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


# 2026-08-22 (Live-Fund Holger Mueller, hedgingRequired=true): fuer jede
# unhedged (USD/EUR) Sub-Asset-Class im Default-Katalog braucht es ein CHF-
# gehedgtes Pendant. Ohne das schliesst _product_matches_constraints() in
# services/portfolio_engine_payload.py bei aktivem hedgingRequired ALLE
# unhedged Kandidaten aus -- die Sub-Allokation faellt dann still auf den
# naechstbesten Asset-Class-Fallback zurueck (meist das eine CH-Kernprodukt),
# und die vom Mandat explizit gewuenschte Diversifikation/Themen-Tilts gehen
# verloren, obwohl passende Sub-Asset-Class-Namen technisch existieren.
# Gleiche sub_asset_class wie das unhedged Pendant (Pflicht fuer den
# Exact-Match in generate_recommendation_run()), TER +8..12bps fuer die
# Hedging-Kosten. Geteilte Konstante: sowohl ensure_default_products()
# (Frisch-Installation) als auch ensure_hedged_product_variants() (additiver
# Backfill fuer bereits bestehende Installationen wie Holger Muellers echtes
# Mandat) referenzieren dieselbe Liste, damit beide Pfade nie auseinander
# driften koennen.
HEDGED_PRODUCT_VARIANTS: list[tuple] = [
    ("iShares Core MSCI World UCITS ETF CHF Hedged", "BlackRock", "ETF", "Aktien", "Aktien Global", "CHF", 30, "8", "A"),
    ("Vanguard FTSE Developed Europe ETF CHF Hedged", "Vanguard", "ETF", "Aktien", "Aktien Europa", "CHF", 22, "8", "A"),
    ("iShares Core MSCI EM IMI ETF CHF Hedged", "BlackRock", "ETF", "Aktien", "Aktien Schwellenlaender", "CHF", 30, "8", "BBB"),
    ("VanEck Defense UCITS ETF CHF Hedged", "VanEck", "ETF", "Aktien", "Thema Verteidigung", "CHF", 65, "6", "BBB"),
    ("Energy Select Sector ETF CHF Hedged", "State Street", "ETF", "Aktien", "Thema Fossile Energie", "CHF", 55, "6", "BBB"),
    ("Consumer Staples Tobacco Tilt ETF CHF Hedged", "WisdomTree", "ETF", "Aktien", "Thema Tabak", "CHF", 68, "6", "BBB"),
    ("Roundhill Sports Betting ETF CHF Hedged", "Roundhill", "ETF", "Aktien", "Thema Gluecksspiel", "CHF", 85, "6", "BB"),
    ("VanEck Uranium and Nuclear ETF CHF Hedged", "VanEck", "ETF", "Aktien", "Thema Kernenergie", "CHF", 71, "6", "BBB"),
    ("EM Local Bond Opportunities CHF Hedged", "JPMorgan", "Fonds", "Obligationen", "Obligationen Emerging", "CHF", 72, "6", "BBB"),
    ("iShares Developed Markets Property Yield CHF Hedged", "BlackRock", "ETF", "Immobilien", "Immobilien Global", "CHF", 48, "8", "BBB"),
]


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
        *HEDGED_PRODUCT_VARIANTS,
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
        risk_band = _default_product_risk_band(product)
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


def _default_product_risk_band(product: "Product") -> tuple[int, int]:
    """Suitability-Risikoband fuer den Default-Produktkatalog, gekeyed nach
    sub_asset_class/asset_class -- geteilt zwischen ensure_default_products()
    und ensure_hedged_product_variants(), damit ein CHF-gehedgtes Pendant
    immer dasselbe Risikoband erhaelt wie sein unhedged Original."""
    if product.sub_asset_class in ("Aktien Schwellenlaender", "Thema Verteidigung", "Thema Fossile Energie", "Thema Tabak", "Thema Alkohol", "Thema Gluecksspiel", "Thema Kernenergie"):
        return (6, 10)
    if product.sub_asset_class in ("Private Equity", "Krypto", "Hedge Funds"):
        return (7, 10)
    if product.asset_class == "Aktien":
        return (4, 10)
    if product.asset_class == "Immobilien":
        return (4, 10)
    if product.sub_asset_class == "Obligationen Emerging":
        return (5, 10)
    return (1, 10)


def ensure_hedged_product_variants(db: Session) -> None:
    """Additiver Backfill der CHF-gehedgten Produktvarianten (siehe
    HEDGED_PRODUCT_VARIANTS) fuer bereits bestehende Installationen.

    ensure_default_products() seedet nur, wenn der CH-Katalog komplett leer
    ist (Idempotenz-Check ueber Zeilenzahl) -- auf einer bereits laufenden
    Installation wie einem echten Berater-Desktop laeuft dieser Pfad also
    NIE erneut, selbst wenn HEDGED_PRODUCT_VARIANTS um neue Eintraege
    erweitert wird. Diese Funktion prueft stattdessen JEDEN Eintrag einzeln
    per product_name (analog zum ensure_column()-Muster in database.py) und
    legt nur die tatsaechlich fehlenden Produkte + deren Suitability-Zeile
    an. Sicher bei jedem Start aufzurufen, auch parallel zu
    ensure_default_products() (kein Konflikt, da beide denselben
    product_name-Vertrag nutzen)."""
    existing_names = {
        row[0]
        for row in db.query(Product.product_name).filter(
            Product.product_name.in_([name for name, *_ in HEDGED_PRODUCT_VARIANTS]),
        ).all()
    }
    missing = [entry for entry in HEDGED_PRODUCT_VARIANTS if entry[0] not in existing_names]
    if not missing:
        return
    now = _now()
    created = []
    for name, provider, product_type, asset_class, sub_asset_class, currency, ter_bps, sfdr_class, esg_rating in missing:
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
        risk_band = _default_product_risk_band(product)
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


def _project_estimated_wealth_tax_cashflow(
    mandate: Mandate,
    wealth_rappen: int,
    projection_years: int,
    *,
    start_year: int,
    inflation_series_bps: list[int],
    fx_source,
    target_currency: str,
) -> list[int]:
    """Project the static tax slice replaced by dynamic solver taxation."""
    rows = derive_tax_cashflow(mandate, int(wealth_rappen or 0))
    if not rows:
        return [0] * max(0, int(projection_years))
    return net_cashflow_series(
        rows,
        projection_years,
        start_year=start_year,
        inflation_series_bps=inflation_series_bps,
        fx_source=fx_source,
        target_currency=target_currency,
    )


def _load_allocation_inputs(
    db: Session,
    mandate: Mandate,
    simulation_prefs: dict,
    cma: CapitalMarketAssumption | None = None,
) -> dict:
    # One model-owned FX basis for positions, cashflows and projections.
    # Empty reference data uses the explicit versioned default; malformed,
    # ambiguous or unreadable DB rates fail closed before allocation starts.
    from services.currency.fx_rates import FXRateSource
    fx_source = FXRateSource.from_db_for_model(db)
    target_currency = str(getattr(mandate, "base_currency", "CHF") or "CHF").upper()

    all_position_rows = db.query(WealthPosition).filter(
        WealthPosition.client_id == mandate.client_id,
        WealthPosition.deleted_at.is_(None),
    ).all()
    all_positions = _strictly_active_rows(
        all_position_rows,
        label="Vermoegensposition",
    )
    _validate_active_wealth_position_semantics(all_positions)
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

    cashflow_rows = db.query(Cashflow).filter(
        Cashflow.client_id == mandate.client_id,
        Cashflow.deleted_at.is_(None),
    ).all()
    cashflows = _strictly_active_rows(cashflow_rows, label="Cashflow")
    _validate_active_cashflow_inputs(cashflows)
    # 2026-06-14: vermögensgetriebene Cashflows (Hypothekarzins, Amortisation,
    # Miet-/Zinserträge) auch in die Engine-Projektion/Reserve einspeisen, damit
    # Strategie-Verzehr und Cashflow-Ansicht 1:1 dieselben Posten sehen.
    # Roadmap #39 (2026-08-07): optional geschaetzte Vermoegenssteuer dito.
    derived_wealth_cashflows = derive_wealth_cashflows(all_positions)
    derived_tax_cashflows = derive_tax_cashflow(mandate, total_wealth_rappen)
    cashflows = (
        list(cashflows)
        + derived_wealth_cashflows
        + derived_tax_cashflows
    )
    goal_rows = db.query(Goal).filter(
        Goal.mandate_id == mandate.id,
        Goal.deleted_at.is_(None),
    ).order_by(Goal.rank.asc()).all()
    goals = _strictly_active_rows(goal_rows, label="Ziel")
    _validate_active_goal_inputs(goals)
    # Sprint A1: erwartete Vermoegenszufluesse (Erbschaft, Bonus, Saeule3b, ...)
    wealth_inflows = db.query(WealthInflow).filter(
        WealthInflow.client_id == mandate.client_id,
        WealthInflow.deleted_at.is_(None),
    ).all()
    scoped_wealth_inflows = []
    for inflow in wealth_inflows:
        active = getattr(inflow, "is_active", None)
        if isinstance(active, bool) or not isinstance(active, int) or active not in (0, 1):
            raise ValueError("Vermoegenszufluss: is_active muss exakt 0 oder 1 sein.")
        inflow_mandate_id = getattr(inflow, "mandate_id", None)
        if inflow_mandate_id:
            inflow_mandate = db.query(Mandate).filter(Mandate.id == inflow_mandate_id).first()
            if inflow_mandate is None or inflow_mandate.client_id != mandate.client_id:
                raise ValueError(
                    "Vermoegenszufluss verweist auf ein Mandat eines anderen "
                    "Kunden oder auf ein fehlendes Mandat."
                )
            if inflow_mandate_id != mandate.id:
                continue
        if active == 1:
            scoped_wealth_inflows.append(inflow)
    wealth_inflows = scoped_wealth_inflows
    # fx_source/target_currency bereits weiter oben ermittelt (siehe FX-Fix-
    # Kommentar) -- hier wiederverwendet statt erneut geladen.
    cashflow_totals = totals_for_year(
        cashflows, fx_source=fx_source, target_currency=target_currency,
    )
    projection_years = _simulation_horizon_years(simulation_prefs, goals, mandate)
    external_foundation_projection = _build_external_foundation_projection(
        all_positions,
        horizon_years=projection_years,
        fx_source=fx_source,
        target_currency=target_currency,
    )
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
    # If a dynamic TaxRegime is active, the stochastic scenario engine applies
    # wealth/dividend taxes path by path.  Keep the estimated tax cashflow in
    # the advisory cashflow/reporting view, but remove that same derived line
    # from the solver series to prevent double taxation.
    optimizer_cashflow_projection_series_rappen = list(
        cashflow_projection_series_rappen
    )
    # The static reporting estimate is calculated on total wealth, while the
    # stochastic tax engine only grows and taxes the advised portfolio.  Only
    # remove the advisory share that is actually replaced dynamically; the
    # residual tax attributable to external wealth remains a genuine solver
    # cash outflow.
    tax_projection = _project_estimated_wealth_tax_cashflow(
        mandate,
        advisory_wealth_rappen,
        projection_years,
        start_year=cashflow_totals["year"],
        inflation_series_bps=cf_inflation_series_bps,
        fx_source=fx_source,
        target_currency=target_currency,
    )
    if any(tax_projection):
        optimizer_cashflow_projection_series_rappen = [
            int(total) - int(tax_component)
            for total, tax_component in zip(
                optimizer_cashflow_projection_series_rappen,
                tax_projection,
            )
        ]
    # Advisory cash already grows through the optimizer's CMA liquidity return.
    # Its position-derived account interest is retained in cashflow reporting
    # and reserve calculations, but must not enter the stochastic wealth path a
    # second time. Interest from external/"Anderes Vermoegen" positions stays a
    # genuine contribution because that principal is not grown by the advised
    # portfolio factors.
    embedded_advisory_liquidity_cashflows = [
        cashflow
        for cashflow in derived_wealth_cashflows
        if int(getattr(cashflow, "is_derived", 0) or 0) == 1
        and str(getattr(cashflow, "source", "") or "") == "wealth_position"
        and str(getattr(cashflow, "id", "") or "").startswith(
            "derived:liquidity_interest:"
        )
        and _norm_text(getattr(cashflow, "origin_assignment", None))
        == "Beratungsvermoegen"
    ]
    if embedded_advisory_liquidity_cashflows:
        embedded_interest_projection = net_cashflow_series(
            embedded_advisory_liquidity_cashflows,
            projection_years,
            start_year=cashflow_totals["year"],
            inflation_series_bps=cf_inflation_series_bps,
            fx_source=fx_source,
            target_currency=target_currency,
        )
        optimizer_cashflow_projection_series_rappen = [
            int(total) - int(embedded_component)
            for total, embedded_component in zip(
                optimizer_cashflow_projection_series_rappen,
                embedded_interest_projection,
            )
        ]
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
        optimizer_cashflow_projection_series_rappen = [
            int(cf) + int(infl)
            for cf, infl in zip(
                optimizer_cashflow_projection_series_rappen,
                inflow_projection_series_rappen,
            )
        ]
    # 2026-06-14 (#31): Hypothek-Amortisation/Refinanzierung jahresabhängig in die
    # Projektion einrechnen — direkt: sinkende Zinslast; Refi auf 3% nach Ablauf
    # (Fix) bzw. 5 Jahren (SARON). Additiv auf das Netto-Cashflow-Series; die
    # heutige Cashflow-Ansicht/Summe bleibt unberührt (statischer Posten = Jahr 0).
    _mortgage_interest_adj = mortgage_interest_adjustment_series(
        all_positions,
        projection_years,
        cashflow_totals["year"],
        fx_source=fx_source,
        target_currency=target_currency,
    )
    if any(_mortgage_interest_adj):
        cashflow_projection_series_rappen = [
            int(cf) + int(adj)
            for cf, adj in zip(cashflow_projection_series_rappen, _mortgage_interest_adj)
        ]
        optimizer_cashflow_projection_series_rappen = [
            int(cf) + int(adj)
            for cf, adj in zip(
                optimizer_cashflow_projection_series_rappen,
                _mortgage_interest_adj,
            )
        ]
    _mortgage_amortization_adj = mortgage_amortization_adjustment_series(
        all_positions,
        projection_years,
        fx_source=fx_source,
        target_currency=target_currency,
    )
    if any(_mortgage_amortization_adj):
        cashflow_projection_series_rappen = [
            int(cf) + int(adj)
            for cf, adj in zip(
                cashflow_projection_series_rappen,
                _mortgage_amortization_adj,
            )
        ]
        optimizer_cashflow_projection_series_rappen = [
            int(cf) + int(adj)
            for cf, adj in zip(
                optimizer_cashflow_projection_series_rappen,
                _mortgage_amortization_adj,
            )
        ]
    recurring_cashflow_projection_series_rappen = recurring_net_cashflow_series(
        cashflows,
        projection_years,
        start_year=cashflow_totals["year"],
        inflation_series_bps=cf_inflation_series_bps,
        fx_source=fx_source,
        target_currency=target_currency,
    )
    recurring_cashflow_projection_series_rappen = [
        int(value) + int(interest_adj) + int(amortization_adj)
        for value, interest_adj, amortization_adj in zip(
            recurring_cashflow_projection_series_rappen,
            _mortgage_interest_adj,
            _mortgage_amortization_adj,
        )
    ]
    return {
        "advisory_summary": advisory_summary,
        "total_summary": total_summary,
        "advisory_wealth_rappen": advisory_wealth_rappen,
        "total_wealth_rappen": total_wealth_rappen,
        "total_liabilities_rappen": total_liabilities_rappen,
        "external_foundation_projection": external_foundation_projection,
        # C8: rohe Listen fuer input_snapshot_hash
        "all_positions": all_positions,
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
        "optimizer_cashflow_projection_series_rappen": (
            optimizer_cashflow_projection_series_rappen
        ),
        "optimizer_replaced_tax_projection_series_rappen": tax_projection,
        "cashflow_inflation_series_bps": cf_inflation_series_bps,
        "cashflow_fx_source": fx_source,
        "cashflow_target_currency": target_currency,
        "recurring_cashflow_projection_series_rappen": recurring_cashflow_projection_series_rappen,
        # Sprint A1: erwartete Vermoegenszufluesse, fuer Audit-Trail + FE-Anzeige.
        "wealth_inflows": wealth_inflows,
        "inflow_projection_series_rappen": inflow_projection_series_rappen,
        # Sprint B2: Anderes-Vermoegen-Schloss-Pool (Reserve-Reduktion).
        "unlocked_other_assets_rappen": unlocked_other_assets_rappen,
    }






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
    _synchronize_fallback_optimizer_result,
    _weights_from_targets,
)


def _projection_context_snapshot(
    *,
    mandate: Mandate,
    target_currency: str,
    fx_source,
    positions: list,
    cashflows: list,
    wealth_inflows: list,
    cashflow_inflation_series_bps: list[int] | None,
    goal_inflation_series_bps: list[int],
    cashflow_projection_series_rappen: list[int],
    optimizer_cashflow_projection_series_rappen: list[int],
    external_foundation_projection: dict[str, list[int]],
    external_goal_funding_series_rappen: list[int],
) -> dict:
    """Canonical effective inputs for reporting and total-scope goal paths."""
    normalized_target_currency = str(
        target_currency or "CHF"
    ).upper().strip()
    currencies = {
        str(getattr(row, "currency", None) or normalized_target_currency)
        .upper()
        .strip()
        for row in [*(positions or []), *(cashflows or []), *(wealth_inflows or [])]
    }
    return {
        "target_currency": normalized_target_currency,
        "fx_basis": fx_source.canonical_model_signature(
            currencies,
            target_currency=normalized_target_currency,
        ),
        "fx_signature": _effective_fx_rate_signature(
            fx_source=fx_source,
            target_currency=target_currency,
            positions=positions,
            cashflows=cashflows,
            wealth_inflows=wealth_inflows,
        ),
        "cashflow_inflation_series_bps": [
            int(value) for value in (cashflow_inflation_series_bps or [])
        ],
        "goal_inflation_series_bps": [
            int(value) for value in goal_inflation_series_bps
        ],
        "cashflow_projection_series_rappen": [
            int(value) for value in cashflow_projection_series_rappen
        ],
        "optimizer_cashflow_projection_series_rappen": [
            int(value)
            for value in optimizer_cashflow_projection_series_rappen
        ],
        "external_foundation_projection": {
            key: [int(value) for value in values]
            for key, values in sorted(external_foundation_projection.items())
        },
        "external_goal_funding_series_rappen": [
            int(value) for value in external_goal_funding_series_rappen
        ],
        "mandate_projection_inputs": {
            "jurisdiction": str(
                getattr(mandate, "jurisdiction", None) or "CH"
            ),
            "base_currency": str(
                getattr(mandate, "base_currency", None) or "CHF"
            ),
            "investment_universe": str(
                getattr(mandate, "investment_universe", None) or ""
            ),
            "tax_jurisdiction": str(
                getattr(mandate, "tax_jurisdiction", None) or ""
            ),
            "tax_overrides_json": str(
                getattr(mandate, "tax_overrides_json", None) or ""
            ),
            "tax_estimate_in_cashflow_enabled": int(
                getattr(mandate, "tax_estimate_in_cashflow_enabled", 0) or 0
            ),
            "client_birth_year": int(
                getattr(mandate, "client_birth_year", 0) or 0
            ),
            "client_sex": str(getattr(mandate, "client_sex", None) or ""),
            "use_mortality_simulation": int(
                getattr(mandate, "use_mortality_simulation", 0) or 0
            ),
            "opened_at": str(getattr(mandate, "opened_at", None) or ""),
            "retirement_year": int(
                getattr(mandate, "retirement_year", 0) or 0
            ),
            "life_expectancy_year": int(
                getattr(mandate, "life_expectancy_year", 0) or 0
            ),
        },
    }


def _compute_input_snapshot_hash(
    *,
    advisory_positions: list,
    all_positions: list | None = None,
    cashflows: list,
    goals: list,
    advisory_wealth_rappen: int,
    total_wealth_rappen: int,
    wealth_inflows: list | None = None,
    projection_context: dict | None = None,
    snapshot_version: str | None = None,
) -> str:
    """C8: Hash der StrategyContext-Inputs (active records only).

    Aenderungen an aktiven WealthPositions, Cashflows oder Goals fuehren
    zu einem neuen Hash. Soft-deleted oder is_active=0 Records sind
    explizit ausgeschlossen, damit sie keine Drift erzeugen.
    """
    def _pos_v1(p) -> tuple:
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

    def _pos_v2(p) -> tuple:
        return _pos_v1(p) + (
            str(getattr(p, "currency", "") or ""),
            str(getattr(p, "valuation_date", "") or ""),
            int(getattr(p, "property_rental_income_rappen", 0) or 0),
            int(getattr(p, "property_rental_inflation_linked", 0) or 0),
            int(getattr(p, "asset_expected_return_bps", 0) or 0),
            int(getattr(p, "liquidity_interest_rate_bps", 0) or 0),
            int(getattr(p, "mortgage_interest_rate_bps", 0) or 0),
            int(getattr(p, "mortgage_amortization_rappen", 0) or 0),
            str(getattr(p, "mortgage_amortization_type", "") or ""),
            str(getattr(p, "mortgage_type", "") or ""),
            str(getattr(p, "mortgage_maturity_date", "") or ""),
            str(getattr(p, "mortgage_linked_property_id", "") or ""),
            int(getattr(p, "is_available_for_goal_funding", 0) or 0),
        )

    def _cf_v1(c) -> tuple:
        return (
            str(getattr(c, "id", "") or ""),
            str(getattr(c, "cashflow_type", "") or ""),
            int(getattr(c, "amount_rappen", 0) or 0),
            str(getattr(c, "frequency", "") or ""),
            str(getattr(c, "nature", "") or ""),
            str(getattr(c, "valid_from", "") or ""),
            str(getattr(c, "valid_until", "") or ""),
        )

    def _cf_v2(c) -> tuple:
        return _cf_v1(c) + (
            str(getattr(c, "currency", "") or ""),
            int(getattr(c, "is_inflation_linked", 0) or 0),
            int(getattr(c, "gross_amount_rappen", 0) or 0),
            int(getattr(c, "tax_amount_rappen", 0) or 0),
            str(getattr(c, "timing_precision", "") or ""),
            str(getattr(c, "source", "") or ""),
            str(getattr(c, "origin_position_id", "") or ""),
            str(getattr(c, "origin_assignment", "") or ""),
        )

    def _goal_v1(g) -> tuple:
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

    def _goal_v2(g) -> tuple:
        return _goal_v1(g) + (
            str(getattr(g, "goal_scope", "") or ""),
            str(getattr(g, "value_mode", "") or ""),
            int(getattr(g, "probability_pct", 0) or 0),
            int(getattr(g, "success_probability_min_x100", 0) or 0),
            int(getattr(g, "is_inflation_linked", 0) or 0),
            int(getattr(g, "duration_years", 0) or 0),
        )

    def _nullable_int(value) -> int | None:
        return None if value is None else int(value)

    def _goal_v4(g) -> dict[str, str | int | None]:
        """Canonical strategy input, excluding display/audit-only metadata.

        Unlike the historical tuple encoders, this intentionally preserves
        ``None`` for nullable fields.  Several goal defaults distinguish NULL
        from an explicit zero (notably conditional probability), so collapsing
        both values would leave an objective-relevant mutation unhashed.
        """
        return {
            "id": str(getattr(g, "id", "") or ""),
            "mandate_id": str(getattr(g, "mandate_id", "") or ""),
            "client_id": str(getattr(g, "client_id", "") or ""),
            "goal_family": str(getattr(g, "goal_family", "") or ""),
            "goal_type": str(getattr(g, "goal_type", "") or ""),
            "label": str(getattr(g, "label", "") or ""),
            "rank": _nullable_int(getattr(g, "rank", None)),
            "weight_bps": _nullable_int(getattr(g, "weight_bps", None)),
            "goal_scope": str(getattr(g, "goal_scope", "") or ""),
            "value_mode": str(getattr(g, "value_mode", "") or ""),
            "target_amount_rappen": _nullable_int(
                getattr(g, "target_amount_rappen", None)
            ),
            "target_wealth_rappen": _nullable_int(
                getattr(g, "target_wealth_rappen", None)
            ),
            "target_return_bps": _nullable_int(
                getattr(g, "target_return_bps", None)
            ),
            "success_probability_min_x100": _nullable_int(
                getattr(g, "success_probability_min_x100", None)
            ),
            "start_date": str(getattr(g, "start_date", "") or ""),
            "horizon_years": _nullable_int(
                getattr(g, "horizon_years", None)
            ),
            "target_date": str(getattr(g, "target_date", "") or ""),
            "is_ongoing": _nullable_int(getattr(g, "is_ongoing", None)),
            "frequency": str(getattr(g, "frequency", "") or ""),
            "hardness": str(getattr(g, "hardness", "") or ""),
            "probability_pct": _nullable_int(
                getattr(g, "probability_pct", None)
            ),
            "pension_pillar": str(
                getattr(g, "pension_pillar", "") or ""
            ),
            "linked_position_id": str(
                getattr(g, "linked_position_id", "") or ""
            ),
            "is_active": _nullable_int(getattr(g, "is_active", None)),
        }

    def _wealth_inflow_v3(inflow) -> tuple:
        return (
            str(getattr(inflow, "id", "") or ""),
            str(getattr(inflow, "mandate_id", "") or ""),
            str(getattr(inflow, "source_type", "") or ""),
            int(getattr(inflow, "amount_rappen", 0) or 0),
            int(getattr(inflow, "expected_year", 0) or 0),
            int(getattr(inflow, "is_recurring", 0) or 0),
            str(getattr(inflow, "frequency", "") or ""),
            int(getattr(inflow, "duration_years", 0) or 0),
            str(getattr(inflow, "value_mode", "") or ""),
        )

    use_v2 = all_positions is not None
    positions = all_positions if use_v2 else advisory_positions
    position_encoder = _pos_v2 if use_v2 else _pos_v1
    cashflow_encoder = _cf_v2 if use_v2 else _cf_v1
    has_projection_context = use_v2 and projection_context is not None
    effective_snapshot_version = snapshot_version
    if has_projection_context and effective_snapshot_version is None:
        effective_snapshot_version = "strategy_inputs_v4_complete_goals"
    if effective_snapshot_version is not None and (
        not has_projection_context
        or effective_snapshot_version
        not in {
            "strategy_inputs_v3_projection_context",
            "strategy_inputs_v4_complete_goals",
        }
    ):
        raise ValueError("Unbekannte oder unvollstaendige Snapshot-Version.")
    goal_encoder = (
        _goal_v4
        if effective_snapshot_version == "strategy_inputs_v4_complete_goals"
        else (_goal_v2 if use_v2 else _goal_v1)
    )

    payload_data = {
            "advisory_wealth_rappen": int(advisory_wealth_rappen or 0),
            "total_wealth_rappen": int(total_wealth_rappen or 0),
            "positions": sorted(position_encoder(p) for p in positions),
            "cashflows": sorted(cashflow_encoder(c) for c in cashflows),
            "goals": sorted(
                (goal_encoder(g) for g in goals),
                key=(
                    (lambda item: (str(item.get("id") or ""), json.dumps(item, sort_keys=True)))
                    if goal_encoder is _goal_v4
                    else None
                ),
            ),
    }
    if has_projection_context:
        payload_data.update({
            "snapshot_version": effective_snapshot_version,
            "wealth_inflows": sorted(
                _wealth_inflow_v3(inflow)
                for inflow in (wealth_inflows or [])
            ),
            "projection_context": projection_context,
        })
    elif use_v2:
        payload_data["snapshot_version"] = "strategy_inputs_v2_foundation"
    payload = json.dumps(
        payload_data,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_allocation_model_basis(
    *,
    optimizer_mode: str,
    optimizer_result,
    allocation: TargetAllocation | None,
    monte_carlo: dict,
    simulation_prefs: dict | None,
    mandate: Mandate,
    stored_optimization_basis: dict | None = None,
    reporting_tax_cashflow_present: bool | None = None,
) -> dict[str, dict]:
    """Describe decision and implementation models as two explicit views.

    The stochastic optimizer selects the allocation under a constant-weight
    decision model.  The reporting Monte Carlo then projects implementation
    behaviour (drift, optional rebalancing and transaction costs).  They may
    legitimately produce different goal probabilities, so the API must never
    present them as an unlabeled single methodology.
    """
    context = getattr(optimizer_result, "context", None)
    stored_method = (
        getattr(allocation, "optimization_method", None)
        if allocation is not None
        else None
    )
    active_method = str(
        getattr(optimizer_result, "method", None)
        or stored_method
        or ("house_matrix" if optimizer_mode == "house_matrix" else optimizer_mode)
    )
    # A status/method string alone is not proof that a stochastic context ever
    # existed. In particular, an import/startup failure can produce an audited
    # House fallback with ``context=None`` and no stochastic analytics.
    has_stochastic_basis = context is not None
    legacy_stochastic = bool(
        context is None
        and stored_optimization_basis is None
        and allocation is not None
        and stored_method == "stochastic"
    )
    legacy_shadow = bool(
        context is None
        and stored_optimization_basis is None
        and allocation is not None
        and stored_method is None
        and getattr(allocation, "shadow_optimization_json", None)
    )
    if has_stochastic_basis and optimizer_mode == "shadow_stochastic":
        optimization_basis_id = "stochastic_shadow_candidate_v2"
        optimization_purpose = "candidate_comparison"
    elif has_stochastic_basis:
        optimization_basis_id = "stochastic_decision_v2"
        optimization_purpose = "allocation_selection"
    elif legacy_stochastic:
        optimization_basis_id = "stochastic_legacy_unverified_v0"
        optimization_purpose = "historical_provenance_unverified"
    elif legacy_shadow:
        optimization_basis_id = "stochastic_shadow_legacy_unverified_v0"
        optimization_purpose = "historical_provenance_unverified"
    elif active_method == "fallback_house_matrix":
        optimization_basis_id = "house_matrix_fallback_v1"
        optimization_purpose = "controlled_fallback"
    else:
        optimization_basis_id = "house_matrix_policy_v1"
        optimization_purpose = "allocation_selection"
    optimizer_seed = getattr(optimizer_result, "seed", None)
    if optimizer_seed is None and allocation is not None:
        optimizer_seed = getattr(allocation, "optimization_seed", None)
    optimizer_n_paths = (
        int(getattr(context, "n_paths", 0) or 0)
        if context is not None
        else int(getattr(optimizer_result, "n_paths", 0) or 0)
    )
    optimizer_horizon = (
        int(getattr(context, "horizon_years", 0) or 0)
        if context is not None
        else int(monte_carlo.get("horizon_years", 0) or 0)
    )
    tax_regime = getattr(context, "tax_regime", None) if context is not None else None
    dividend_yields = (
        getattr(context, "dividend_yield_bps_per_bucket", None)
        if context is not None
        else None
    )
    has_dividend_tax_input = bool(
        dividend_yields is not None
        and any(float(value or 0) != 0.0 for value in dividend_yields)
    )
    has_effective_tax_component = bool(
        tax_regime is not None
        and (
            bool(getattr(tax_regime, "supports_wealth_tax", False))
            or has_dividend_tax_input
        )
    )
    legacy_context_unknown = legacy_stochastic or legacy_shadow
    reporting_tail = bool(_simulation_use_tail_risk(simulation_prefs))

    optimization_basis = {
            "basis_id": optimization_basis_id,
            "purpose": optimization_purpose,
            "active_method": active_method,
            "portfolio_dynamics": (
                "annual_constant_weight"
                if has_stochastic_basis
                else (
                    "historical_context_unavailable"
                    if legacy_context_unknown
                    else "policy_matrix"
                )
            ),
            "return_measure": "gross_twr_pre_transaction_cost",
            "liquidity_yield": (
                "cma_total_return"
                if has_stochastic_basis
                else (
                    "historical_context_unavailable"
                    if legacy_context_unknown
                    else "not_applicable"
                )
            ),
            "tail_model": (
                "bounded_cornish_fisher_moment_calibrated_v2"
                if has_stochastic_basis
                else (
                    "historical_context_unavailable"
                    if legacy_context_unknown
                    else "not_applicable"
                )
            ),
            "importance_sampling": bool(
                context is not None
                and getattr(context, "scenario_weights", None) is not None
            ),
            "transaction_cost_bps": 0,
            "seed": int(optimizer_seed) if optimizer_seed is not None else None,
            "n_paths": optimizer_n_paths or None,
            "horizon_years": optimizer_horizon or None,
            "tax_basis": (
                f"median_rate_{type(tax_regime).__name__}"
                if has_effective_tax_component
                else (
                    f"none_effective_{type(tax_regime).__name__}"
                    if tax_regime is not None
                    else (
                        "historical_context_unavailable"
                        if legacy_context_unknown
                        else "none"
                    )
                )
            ),
            "liability_basis": (
                "goal_liability_paths"
                if has_stochastic_basis
                else (
                    "historical_context_unavailable"
                    if legacy_context_unknown
                    else "policy_only"
                )
            ),
            "real_estate_return_basis": (
                "listed_real_estate_total_return_including_distributions_v1"
            ),
            "cma_mean_semantics": "arithmetic_expected_total_return_v1",
            "return_moment_mapping": (
                "arithmetic_mean_and_volatility_preserved_v2"
            ),
            "tail_calibration": (
                "bounded_cornish_fisher_gauss_hermite_v2"
            ),
            "foundation_model_version": "external_foundation_v2",
            "external_property_goal_basis": (
                "inflation_zero_real_plus_exact_liability_and_pledged_transfer_v2"
            ),
            "indirect_amortization_treatment": "pledged_asset_transfer_v1",
            "direct_real_estate_scope": "external_total_wealth",
            "external_rent_treatment": "cashflow_only",
        }
    if stored_optimization_basis is not None:
        if not isinstance(stored_optimization_basis, dict):
            raise ValueError(
                "Persistierte Optimizer-Modellbasis muss ein Objekt sein."
            )
        # This snapshot is part of effective_constraints_json and therefore of
        # allocation_context_hash. Returning it verbatim keeps persisted goal
        # probabilities tied to the exact model that produced them.
        optimization_basis = dict(stored_optimization_basis)

    return {
        "optimization": optimization_basis,
        "reporting": {
            "basis_id": "implementation_projection_v2",
            "purpose": "post_selection_projection",
            "portfolio_dynamics": _simulation_rebalance_mode(simulation_prefs),
            "return_measure": "gross_twr_pre_rebalancing_cost",
            "transaction_cost_bps": int(
                _simulation_transaction_cost_bps(simulation_prefs)
            ),
            "liquidity_yield": "zero_bucket_plus_position_interest_cashflow",
            "real_estate_return_basis": (
                "listed_real_estate_total_return_including_distributions_v1"
            ),
            "cma_mean_semantics": "arithmetic_expected_total_return_v1",
            "return_moment_mapping": (
                "arithmetic_mean_and_volatility_preserved_v2"
            ),
            "tail_calibration": (
                "bounded_cornish_fisher_gauss_hermite_v2"
                if reporting_tail
                else "not_applicable"
            ),
            "foundation_model_version": "external_foundation_v2",
            "total_scope_goal_basis": "exact_total_projection_path_v2",
            "indirect_amortization_treatment": "pledged_asset_transfer_v1",
            "direct_real_estate_scope": "external_total_wealth",
            "external_rent_treatment": "cashflow_only",
            "direct_real_estate_return_basis": (
                "position_price_appreciation_plus_explicit_rent_v2"
            ),
            "tail_model": (
                "bounded_cornish_fisher_moment_calibrated_v2"
                if reporting_tail
                else "lognormal_arithmetic_moments_v2"
            ),
            "stress_multiplier": float(
                _simulation_stress_multiplier(simulation_prefs)
            ),
            "crisis_strength": float(
                _simulation_crisis_strength(simulation_prefs)
            ),
            "seed": int(monte_carlo.get("seed", 0) or 0),
            "n_paths": int(monte_carlo.get("simulations", 0) or 0),
            "horizon_years": int(monte_carlo.get("horizon_years", 0) or 0),
            "tax_basis": (
                "estimated_wealth_tax_cashflow"
                if bool(reporting_tax_cashflow_present)
                else "configured_cashflows"
            ),
        },
    }


def _strategy_drift_warnings(
    allocation: TargetAllocation,
    *,
    assessment,
    cma,
    current_input_snapshot_hash: str | tuple[str, ...] | None = None,
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
    if isinstance(current_input_snapshot_hash, str):
        accepted_current_hashes = {current_input_snapshot_hash}
    else:
        accepted_current_hashes = {
            str(value)
            for value in (current_input_snapshot_hash or ())
            if value
        }
    if (
        stored_hash
        and accepted_current_hashes
        and stored_hash not in accepted_current_hashes
    ):
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
    # Activated mortality/tax components are economic model inputs. Validate
    # them before reference-data selection or any House/solver branch so a
    # corrupt raw row can never silently turn the feature off.
    from services.mandate_model_inputs import validate_mandate_model_inputs

    validate_mandate_model_inputs(mandate)
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
    external_foundation_projection = inputs[
        "external_foundation_projection"
    ]
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
    optimizer_cashflow_projection_series_rappen = inputs.get(
        "optimizer_cashflow_projection_series_rappen",
        cashflow_projection_series_rappen,
    )
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
    # Sicherheits-Fix (2026-08-03, Berater-Audit "Restriktionen & Tilts", Befund 4):
    # mehrere unabhaengige Tilt-Mechanismen (Exposure-Anrechnung, Renditeziel,
    # Wachstums-Cashflow) koennen sich gegenseitig ganz oder teilweise aufheben --
    # jeder einzelne ist fachlich legitim, aber ohne den NETTO-Effekt wusste der
    # Berater nicht, dass z.B. ein reduzierender und ein erhoehender Tilt sich
    # gegenseitig neutralisiert haben. Baseline VOR allen Tilts fuer den
    # Netto-Effekt-Reasoning-Satz unten.
    targets_before_tilts = dict(targets)
    _apply_external_exposure_tilts(targets, minimums, maximums, total_summary, house_matrix, manual_target_override, reasoning)
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

    # `_load_allocation_inputs` initially replaces the dynamic-tax slice for
    # the full advisory pool. A reserve outside the SAA is not part of the
    # simulated initial wealth, so its tax must remain in the cashflow series
    # just like tax on other external assets. Rebase the removed slice to the
    # exact investable amount before the stochastic context is built.
    initially_replaced_tax_projection = list(
        inputs.get("optimizer_replaced_tax_projection_series_rappen") or []
    )
    if initially_replaced_tax_projection:
        effective_tax_projection = _project_estimated_wealth_tax_cashflow(
            mandate,
            investable_advisory_wealth_rappen,
            len(optimizer_cashflow_projection_series_rappen),
            start_year=cashflow_totals["year"],
            inflation_series_bps=list(
                inputs.get("cashflow_inflation_series_bps") or []
            ),
            fx_source=inputs.get("cashflow_fx_source"),
            target_currency=str(
                inputs.get("cashflow_target_currency")
                or getattr(mandate, "base_currency", None)
                or "CHF"
            ),
        )
        optimizer_cashflow_projection_series_rappen = [
            int(current) + int(initial_tax) - int(effective_tax)
            for current, initial_tax, effective_tax in zip(
                optimizer_cashflow_projection_series_rappen,
                initially_replaced_tax_projection,
                effective_tax_projection,
            )
        ]

    goal_inflation_series_bps = _goal_inflation_series_bps(
        cma,
        len(cashflow_projection_series_rappen),
        cashflow_totals["year"],
        planning_inflation_bps=_current_planning_inflation_bps(db, mandate),
    )
    external_goal_funding_series_rappen = (
        _build_external_goal_funding_series(
            external_gross_assets_rappen=max(
                0,
                int(total_summary.total_rappen)
                - int(advisory_summary.total_rappen),
            ),
            external_foundation_projection=external_foundation_projection,
            inflation_series_bps=goal_inflation_series_bps,
            horizon_years=len(cashflow_projection_series_rappen),
        )
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
    # The stochastic model always works on its own candidate state. In shadow
    # mode none of its reserve floors, illiquidity-derived caps or rebalances
    # may mutate the active House allocation/bands.
    optimizer_targets = dict(targets)
    optimizer_minimums = dict(minimums)
    optimizer_maximums = dict(maximums)
    optimizer_plan_reasoning = reasoning if apply_stochastic else []
    if run_stochastic:
        from services.optimizer.constraints import (
            MAX_ALTERNATIVES,
            MAX_REAL_ESTATE,
            MIN_LIQUIDITY,
            OptimizerInputError,
        )

        global_caps_bps = {
            "real_estate": int(round(MAX_REAL_ESTATE * 10000)),
            "alternatives": int(round(MAX_ALTERNATIVES * 10000)),
        }
        for bucket, cap_bps in global_caps_bps.items():
            if int(optimizer_minimums[bucket]) > cap_bps:
                raise OptimizerInputError(
                    f"Die Mindestquote fuer {bucket} ueberschreitet die "
                    f"globale Obergrenze ({optimizer_minimums[bucket]} > "
                    f"{cap_bps} bps)."
                )
            optimizer_maximums[bucket] = min(
                int(optimizer_maximums[bucket]), cap_bps
            )
        global_liquidity_floor_bps = int(round(MIN_LIQUIDITY * 10000))
        if int(optimizer_maximums["liquidity"]) < global_liquidity_floor_bps:
            raise OptimizerInputError(
                "Die Liquiditaets-Obergrenze liegt unter der globalen "
                f"Mindestquote ({optimizer_maximums['liquidity']} < "
                f"{global_liquidity_floor_bps} bps)."
            )
        optimizer_minimums["liquidity"] = max(
            int(optimizer_minimums["liquidity"]),
            global_liquidity_floor_bps,
        )
        optimizer_targets = _rebalance_to_total(
            optimizer_targets,
            optimizer_minimums,
            optimizer_maximums,
        )
    reserve_floor_bps = 0
    # Reserve ist im deterministischen Pfad bereits in die Zielquote getiltet.
    # Im finalen stochastischen Modell muss dieselbe Information als harte
    # Untergrenze ankommen; ein blosses Start-Target kann vom Solver vollstaendig
    # ueberschrieben werden. Die Quote bleibt auf dem bestehenden SAA-Ceiling
    # (und damit auf der bisherigen Fachsemantik) begrenzt.
    if (
        run_stochastic
        and investable_advisory_wealth_rappen > 0
        and reserve_needed_rappen > 0
    ):
        # ``external_reserve_rappen`` is carved out before the SAA is applied.
        # The internal reserve remains capped at 3% of the original advisory
        # wealth, but its normalized weight must use the actually investable
        # denominator. Otherwise the carve-out silently underfunds liquidity.
        saa_reserve_rappen = min(
            int(reserve_needed_rappen),
            int(round(
                advisory_wealth_rappen
                * _SAA_LIQUIDITY_HARD_CAP_BPS
                / 10000
            )),
        )
        reserve_floor_bps = min(
            10000,
            (
                int(saa_reserve_rappen) * 10000
                + int(investable_advisory_wealth_rappen)
                - 1
            )
            // int(investable_advisory_wealth_rappen),
        )
        explicit_liquidity_max = None
        for raw_key, override in (prefs["bands"] or {}).items():
            if _bucket_key(raw_key) != "liquidity" or not isinstance(override, dict):
                continue
            explicit_liquidity_max = _coerce_band_bps(override.get("max_bps"))
            if explicit_liquidity_max is not None:
                break
        if (
            explicit_liquidity_max is not None
            and reserve_floor_bps > int(explicit_liquidity_max)
        ):
            from services.optimizer.constraints import OptimizerInputError

            raise OptimizerInputError(
                "Die explizite Liquiditaets-Obergrenze ist mit der zwingend "
                "vorzuhaltenden internen Reserve nicht vereinbar."
            )
        # A House cap expressed on the original advisory base may need a small
        # normalization lift after the external reserve carve-out. This is not
        # an economic cap relaxation; the CHF reserve remains unchanged.
        optimizer_maximums["liquidity"] = max(
            int(optimizer_maximums["liquidity"]), int(reserve_floor_bps)
        )
        optimizer_minimums["liquidity"] = max(
            int(optimizer_minimums["liquidity"]), int(reserve_floor_bps)
        )
        if int(optimizer_targets["liquidity"]) < int(optimizer_minimums["liquidity"]):
            optimizer_targets["liquidity"] = int(optimizer_minimums["liquidity"])
            optimizer_targets = _rebalance_to_total(
                optimizer_targets,
                optimizer_minimums,
                optimizer_maximums,
            )
        optimizer_plan_reasoning.append(
            "Die innerhalb der SAA zu haltende Zielreserve ist eine harte "
            "Liquiditaets-Untergrenze des stochastischen Modells und wird "
            "auf dem effektiv investierbaren Vermoegen normiert."
        )

    # 3eyes-konform: Illiquiditaet wird auf Baustein-Ebene (Private Equity)
    # gedeckelt, nicht pauschal auf der ganzen Alternatives-Quote.
    max_illiquid_bps = _parse_bps_percent(prefs["limits"].get("maxIlliquid"))

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
    _validate_sub_cma_universe(
        cma,
        {
            str(getattr(row, "sub_asset_class", "") or "")
            for row in _building_block_rows_for_policy(
                db, policy.id, None, jurisdiction
            )
        },
    )
    risky_map = _building_block_risky_map(
        db,
        policy.id,
        getattr(mandate, "investment_universe", None),
        jurisdiction,
    )

    # Ein kanonischer, fuer alle zulaessigen Bucket-Gewichte harter
    # Sub-Allokationsplan ist die gemeinsame Quelle fuer Solver-CMA,
    # Risky-Fractions und die spaeter materialisierte Zielallokation.
    optimizer_sub_allocation_plan: list[dict] | None = None
    optimizer_risky_fraction_per_bucket: dict[str, float] | None = None
    optimizer_effective_maximums: dict[str, int] | None = None
    if run_stochastic:
        optimizer_sub_allocation_plan, optimizer_effective_maximums = (
            _build_stochastic_sub_allocation_plan(
                targets=optimizer_targets,
                minimums=optimizer_minimums,
                maximums=optimizer_maximums,
                preferences=prefs,
                max_illiquid_bps=max_illiquid_bps,
                reasoning=optimizer_plan_reasoning,
                jurisdiction=jurisdiction,
                db=db,
            )
        )
        optimizer_maximums.update(optimizer_effective_maximums)
        optimizer_targets = _rebalance_to_total(
            optimizer_targets,
            optimizer_minimums,
            optimizer_maximums,
        )
        (
            optimizer_sub_allocation_plan,
            optimizer_asset_risky_weights,
            _optimizer_plan_risky_total_unused,
        ) = _enrich_sub_allocations_with_risk(
            optimizer_sub_allocation_plan,
            risky_map,
        )
        optimizer_risky_fraction_per_bucket = {
            bucket: int(optimizer_asset_risky_weights[bucket]) / 10000.0
            for bucket in BUCKET_FIELDS
        }

    house_targets_before_optimizer = dict(optimizer_targets)
    effective_bounds_bps = {
        bucket: (
            int(optimizer_minimums[bucket]),
            int(optimizer_maximums[bucket]),
        )
        for bucket in BUCKET_FIELDS
    }

    optimizer_result = _run_stochastic_optimizer_pass(
        optimizer_mode=optimizer_mode,
        apply_targets=apply_stochastic,
        cma=cma,
        goals=goals,
        house_matrix=house_matrix,
        assessment=assessment,
        advisory_wealth_rappen=investable_advisory_wealth_rappen,
        cashflow_projection_series_rappen=(
            optimizer_cashflow_projection_series_rappen
        ),
        inflation_series_bps=goal_inflation_series_bps,
        targets=optimizer_targets,
        minimums=optimizer_minimums,
        maximums=optimizer_maximums,
        reasoning=reasoning,
        building_blocks_rows=_building_block_rows,
        sub_allocations=optimizer_sub_allocation_plan,
        risky_fraction_per_bucket=optimizer_risky_fraction_per_bucket,
        effective_bounds_bps=effective_bounds_bps,
        external_wealth_rappen=max(
            0, int(total_wealth_rappen) - int(advisory_wealth_rappen)
        ),
        external_wealth_series_rappen=(
            external_goal_funding_series_rappen
        ),
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
    if apply_stochastic:
        # Candidate state becomes active only in production stochastic mode.
        # If the solver fell back, this is still the exact hard-constrained
        # House candidate evaluated in the stochastic context.
        targets = optimizer_targets
        minimums = optimizer_minimums
        maximums = optimizer_maximums

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
        # Sicherheits-Fix (2026-08-03): die Empfaenger-Seite (equities) war
        # bisher NICHT gegen die aktuelle Maximalgrenze geprueft -- eine vom
        # Berater gesetzte Bandbreiten-Restriktion auf equities konnte durch
        # diesen Tilt unbemerkt ueberschritten werden (live reproduziert).
        # Symmetrisch zu den Spender-Bedingungen oben (bonds/liquidity
        # Mindestabstand), hier der Empfaenger-Hoechstabstand.
        and maximums["equities"] - targets["equities"] >= 150
    ):
        targets["equities"] += 150
        targets["bonds"] -= 100
        targets["liquidity"] -= 50
        reasoning.append("Positiver laufender Cashflow und langfristige Wachstumsziele ermoeglichen einen moderaten Equity-Tilt.")

    if not optimizer_replaced_targets:
        tilt_deltas_bps = {
            bucket: targets[bucket] - targets_before_tilts[bucket]
            for bucket in targets_before_tilts
            if targets[bucket] != targets_before_tilts[bucket]
        }
        if tilt_deltas_bps:
            delta_text = ", ".join(
                f"{BUCKET_LABELS.get(bucket, bucket)} {delta:+d} bps"
                for bucket, delta in sorted(tilt_deltas_bps.items())
            )
            reasoning.append(
                f"Netto-Effekt aller Exposure-Tilts (Anrechnung Gesamtvermoegen, "
                f"Rendite-/Zielhorizont, Wachstums-Cashflow) gegenueber der "
                f"House-Matrix-Baseline: {delta_text}. Einzelne Tilts koennen sich "
                f"dabei teilweise oder vollstaendig aufheben."
            )

    targets_before_final_rebalance = dict(targets)
    targets = _rebalance_to_total(targets, minimums, maximums)
    if optimizer_replaced_targets and targets != targets_before_final_rebalance:
        # A validated stochastic candidate is immutable.  A downstream
        # "repair" would mean that optimizer, analytics and persisted output
        # no longer describe the same allocation.
        from services.optimizer.constraints import OptimizerInputError

        raise OptimizerInputError(
            "Der validierte stochastische Kandidat musste nachtraeglich "
            "rebalanciert werden; die Allocation wird aus Konsistenzgruenden "
            "nicht persistiert."
        )
    if apply_stochastic and optimizer_sub_allocation_plan is not None:
        sub_allocations = _materialize_sub_allocation_plan(
            optimizer_sub_allocation_plan,
            targets,
        )
    else:
        sub_allocations = _build_sub_allocations(
            targets, prefs, jurisdiction=jurisdiction, db=db
        )
        sub_allocations, targets = _apply_illiquid_cap(sub_allocations, targets, max_illiquid_bps, reasoning, maximums=maximums)
    sub_allocations, asset_risky_weights, risky_fraction_total_bps = _enrich_sub_allocations_with_risk(sub_allocations, risky_map)
    realized_risky_bps = risky_fraction_total_bps  # Validierung 2026-06-11 (#AA-1/#AA-3): sub-allocation-gewichtet (konsistent zur Enforcement-Cascade), statt ungewichtetem BB-Bucket-Mittel
    risk_budget_fallback = False
    try:
        assert_risk_budget_ok(realized_risky_bps, risk_budget_bps, slack_bps=0)
    except RiskBudgetExceeded:
        risk_budget_fallback = True
        risk_budget_asset_weights = (
            optimizer_asset_risky_weights
            if optimizer_mode == "stochastic"
            and optimizer_sub_allocation_plan is not None
            else bucket_risky_fraction_bps_from_building_blocks(
                _building_block_rows
            )
        )
        targets, minimums, maximums = _house_matrix_mid_targets(house_matrix, policy)
        # Sicherheits-Fix (2026-08-03, Berater-Audit "Restriktionen & Tilts"):
        # _house_matrix_mid_targets() ersetzt minimums/maximums komplett durch
        # die Haus-Matrix-Defaults -- eine bereits weiter oben erfolgreich per
        # _apply_band_preferences() angewendete Mandats-Restriktion (z.B.
        # "Aktien max. 20%") ging dadurch beim Risikobudget-Fallback
        # stillschweigend verloren (live reproduziert: Berater-Maximum 2000
        # bps, Endresultat 3500 bps, KEINE Warnung). Die harten Grenzen
        # (min_bps/max_bps) werden hier wiederhergestellt -- OHNE die
        # Summe-10000-Validierung von _apply_band_preferences erneut
        # auszufuehren, da ein target_bps-Override, der gegen die
        # URSPRUENGLICHE Baseline exakt aufging, gegen die NEUE
        # Haus-Matrix-Mitte-Baseline eine andere (dann faelschlich als
        # invalide erkannte) Summe ergeben kann. Der nachfolgende
        # _rebalance_to_total()-Aufruf bringt targets unter Beachtung dieser
        # wiederhergestellten Grenzen wieder auf 10000 bps.
        if optimizer_mode == "stochastic":
            # A House fallback is a replacement candidate inside the exact
            # stochastic run context, never an escape hatch from mandate
            # constraints.  Restore the complete pre-solver constraint set
            # (manual bands, reserve floor, policy caps and maxIlliquid-derived
            # Alternatives cap) atomically.
            minimums = {
                bucket: int(effective_bounds_bps[bucket][0])
                for bucket in BUCKET_FIELDS
            }
            maximums = {
                bucket: int(effective_bounds_bps[bucket][1])
                for bucket in BUCKET_FIELDS
            }
            bands_restored = bool(prefs["bands"])
        else:
            bands_restored = _apply_band_min_max_overrides(
                prefs["bands"], minimums, maximums
            )
        if bands_restored:
            reasoning.append(
                "Risikobudget-Fallback: die automatische Ziel-Allokation wurde auf die "
                "Bandbreiten-Mitte des Risikoprofils zurueckgesetzt; Ihre manuell gesetzten "
                "Mindest-/Maximalgrenzen bleiben dabei in Kraft (die genaue Ziel-Allokation "
                "kann sich innerhalb dieser Grenzen verschieben)."
            )
        targets = _rebalance_to_total(targets, minimums, maximums)
        if optimizer_mode == "stochastic" and optimizer_sub_allocation_plan is not None:
            sub_allocations = _materialize_sub_allocation_plan(
                optimizer_sub_allocation_plan, targets
            )
        else:
            sub_allocations = _build_sub_allocations(
                targets, prefs, jurisdiction=jurisdiction, db=db
            )
            sub_allocations, targets = _apply_illiquid_cap(
                sub_allocations,
                targets,
                max_illiquid_bps,
                reasoning,
                maximums=maximums,
            )
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
                if optimizer_mode == "stochastic":
                    from services.optimizer.constraints import OptimizerInputError

                    raise OptimizerInputError(
                        "Der House-Matrix-Fallback kann das im stochastischen "
                        "Run-Context harte Risikobudget innerhalb der effektiven "
                        "Mandatsgrenzen nicht einhalten. Es wird keine fachlich "
                        "ungueltige Empfehlung persistiert."
                    )
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
            if optimizer_mode == "stochastic" and optimizer_sub_allocation_plan is not None:
                sub_allocations = _materialize_sub_allocation_plan(
                    optimizer_sub_allocation_plan, targets
                )
            else:
                sub_allocations = _build_sub_allocations(
                    targets, prefs, jurisdiction=jurisdiction, db=db
                )
                sub_allocations, targets = _apply_illiquid_cap(
                    sub_allocations,
                    targets,
                    max_illiquid_bps,
                    reasoning,
                    maximums=maximums,
                )
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
    if (
        optimizer_mode == "stochastic"
        and optimizer_result is not None
        and (not optimizer_replaced_targets or risk_budget_fallback)
    ):
        optimizer_result = _synchronize_fallback_optimizer_result(
            optimizer_result,
            targets,
            force_fallback=bool(risk_budget_fallback),
        )
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
        external_foundation_projection=external_foundation_projection,
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
        expected_death_year_offset=_expected_death_year_offset_from_mandate(
            mandate
        ),
        advisory_path_series_rappen=simulation["target_mix_series_rappen"],
        total_path_series_rappen=simulation[
            "total_mix_target_series_rappen"
        ],
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
        external_foundation_projection=external_foundation_projection,
    )
    model_basis = _build_allocation_model_basis(
        optimizer_mode=optimizer_mode,
        optimizer_result=optimizer_result,
        allocation=None,
        monte_carlo=monte_carlo,
        simulation_prefs=prefs["simulation"],
        mandate=mandate,
        reporting_tax_cashflow_present=any(
            str(getattr(cashflow, "source", "") or "") == "tax_estimate"
            for cashflow in cashflows
        ),
    )
    monte_carlo["model_basis"] = dict(model_basis["reporting"])
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
    previous_current = _current_target_allocation_or_none(
        db,
        mandate.id,
        for_update=True,
    )
    previous_version = 0
    if previous_current:
        previous_current.is_current = 0
        previous_version = int(previous_current.version or 0)
        # The database-level partial unique index is immediate.  Persist the
        # old anchor transition before the replacement TargetAllocation is
        # added later in this unit of work.
        db.flush()

    # C8: Audit-Anker zur Reproduzierbarkeit + spaeteren Drift-Erkennung.
    preferences_json_snapshot = json.dumps(prefs, sort_keys=True, default=str)
    projection_context_snapshot = _projection_context_snapshot(
        mandate=mandate,
        target_currency=str(inputs["cashflow_target_currency"]),
        fx_source=inputs["cashflow_fx_source"],
        positions=inputs["all_positions"],
        cashflows=cashflows,
        wealth_inflows=inputs["wealth_inflows"],
        cashflow_inflation_series_bps=inputs.get(
            "cashflow_inflation_series_bps"
        ),
        goal_inflation_series_bps=goal_inflation_series_bps,
        cashflow_projection_series_rappen=cashflow_projection_series_rappen,
        optimizer_cashflow_projection_series_rappen=(
            optimizer_cashflow_projection_series_rappen
        ),
        external_foundation_projection=external_foundation_projection,
        external_goal_funding_series_rappen=(
            external_goal_funding_series_rappen
        ),
    )
    input_snapshot_hash = _compute_input_snapshot_hash(
        advisory_positions=inputs["advisory_positions"],
        all_positions=inputs["all_positions"],
        cashflows=cashflows,
        goals=goals,
        advisory_wealth_rappen=advisory_wealth_rappen,
        total_wealth_rappen=total_wealth_rappen,
        wealth_inflows=inputs["wealth_inflows"],
        projection_context=projection_context_snapshot,
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

    sub_allocations_json = json.dumps(
        sub_allocations,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    effective_constraints_payload = {
        "engine_version": "stochastic_core_v2",
        "bounds_bps": {
            bucket: [int(minimums[bucket]), int(maximums[bucket])]
            for bucket in BUCKET_FIELDS
        },
        "risk_budget_bps": int(risk_budget_bps),
        "risky_fraction_per_bucket_bps": {
            bucket: int(asset_risky_weights.get(bucket, 0) or 0)
            for bucket in BUCKET_FIELDS
        },
        "reserve_floor_bps": int(reserve_floor_bps),
        "max_illiquid_bps": (
            int(max_illiquid_bps) if max_illiquid_bps is not None else None
        ),
        "active_method": str(
            optimizer_audit.get("optimization_method") or "house_matrix"
        ),
        "active_status": str(
            optimizer_audit.get("optimization_status") or "house_matrix"
        ),
        # Immutable snapshot for the probabilities persisted alongside this
        # allocation. Reconstructing these fields from today's settings would
        # silently change seed/path/tax/IS disclosures on reload.
        "optimization_model_basis": dict(model_basis["optimization"]),
    }
    effective_constraints_json = json.dumps(
        effective_constraints_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    allocation_context_payload = {
        "engine_version": "stochastic_core_v2",
        "policy_id": str(policy.id),
        "cma_id": str(cma.id),
        "assessment_id": str(assessment.id),
        "input_snapshot_hash": str(input_snapshot_hash),
        "preferences_json": preferences_json_snapshot,
        "targets_bps": {bucket: int(targets[bucket]) for bucket in BUCKET_FIELDS},
        "sub_allocations": sub_allocations,
        "effective_constraints": effective_constraints_payload,
        "optimization_seed": optimizer_audit.get("optimization_seed"),
    }
    allocation_context_hash = hashlib.sha256(
        json.dumps(
            allocation_context_payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()

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
        sub_allocations_json=sub_allocations_json,
        effective_constraints_json=effective_constraints_json,
        allocation_context_hash=allocation_context_hash,
        context_artifacts_required=1,
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
        direct_property_rappen=external_foundation_projection[
            "property_series_rappen"
        ][0],
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
        "goal_achievability_basis_id": model_basis["optimization"]["basis_id"],
        "goal_analysis_basis_id": model_basis["reporting"]["basis_id"],
        "model_basis": model_basis,
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


def _verified_persisted_allocation_context(
    allocation: TargetAllocation,
    *,
    targets: dict[str, int],
    minimums: dict[str, int],
    maximums: dict[str, int],
) -> tuple[list[dict] | None, dict | None]:
    """Load decision artifacts only after structural, semantic, and hash checks.

    All three artifact columns are an atomic unit.  ``NULL`` in all three
    columns identifies a genuine legacy allocation; every other incomplete
    state is an integrity error.  Keeping this verification in one helper is
    important because both payload reconstruction and sensitivity analysis
    consume the stored optimizer context.
    """
    raw_sub_allocations = getattr(allocation, "sub_allocations_json", None)
    raw_constraints = getattr(allocation, "effective_constraints_json", None)
    stored_context_hash = getattr(allocation, "allocation_context_hash", None)
    artifact_values = (
        raw_sub_allocations,
        raw_constraints,
        stored_context_hash,
    )
    if all(value is None for value in artifact_values):
        if int(getattr(allocation, "context_artifacts_required", 0) or 0) == 1:
            raise ValueError(
                "Persistierter Allocation-Context fehlt vollstaendig, obwohl "
                "diese Engine-Allokation unveraenderliche Artefakte verlangt."
            )
        return None, None
    if not all(
        isinstance(value, str) and bool(value.strip())
        for value in artifact_values
    ):
        raise ValueError(
            "Persistierter Allocation-Context ist partiell oder unvollstaendig; "
            "Sub-Allokationen, Constraints und Hash muessen gemeinsam vorliegen."
        )

    try:
        parsed_sub_allocations = json.loads(raw_sub_allocations)
        if not isinstance(parsed_sub_allocations, list) or not all(
            isinstance(row, dict) for row in parsed_sub_allocations
        ):
            raise ValueError("sub_allocations_json must contain a list of objects")
        bucket_totals = {bucket: 0 for bucket in BUCKET_FIELDS}
        for row in parsed_sub_allocations:
            bucket = _bucket_key(row.get("asset_class"))
            weight = int(row.get("target_weight_bps") or 0)
            if bucket not in bucket_totals or weight < 0:
                raise ValueError("unknown bucket or negative sub-allocation weight")
            bucket_totals[bucket] += weight
        if bucket_totals != targets or sum(bucket_totals.values()) != 10000:
            raise ValueError(
                "stored sub-allocation does not reconcile to stored bucket weights"
            )
        stored_sub_allocations = [dict(row) for row in parsed_sub_allocations]
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Persistierte Sub-Allokationen sind ungueltig oder nicht "
            "mit den Bucket-Zielen abstimmbar."
        ) from exc

    try:
        stored_constraints = json.loads(raw_constraints)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Persistierte effektive Allocation-Constraints sind ungueltig."
        ) from exc
    if not isinstance(stored_constraints, dict):
        raise ValueError(
            "Persistierte effektive Allocation-Constraints muessen ein Objekt sein."
        )

    stored_bounds = stored_constraints.get("bounds_bps")
    expected_bounds = {
        bucket: [int(minimums[bucket]), int(maximums[bucket])]
        for bucket in BUCKET_FIELDS
    }
    if stored_bounds != expected_bounds:
        raise ValueError(
            "Persistierte Constraint-Bounds widersprechen den typisierten "
            "Bandspalten der TargetAllocation."
        )
    typed_risk_budget = getattr(
        allocation, "risk_budget_bps_at_generation", None
    )
    if (
        typed_risk_budget is None
        or stored_constraints.get("risk_budget_bps") != int(typed_risk_budget)
    ):
        raise ValueError(
            "Persistiertes Risikobudget widerspricht der typisierten "
            "TargetAllocation-Spalte."
        )
    expected_method = str(
        getattr(allocation, "optimization_method", None) or "house_matrix"
    )
    expected_status = str(
        getattr(allocation, "optimization_status", None) or "house_matrix"
    )
    if str(stored_constraints.get("active_method")) != expected_method:
        raise ValueError(
            "Persistierte aktive Optimierungsmethode widerspricht der "
            "TargetAllocation-Spalte."
        )
    if str(stored_constraints.get("active_status")) != expected_status:
        raise ValueError(
            "Persistierter aktiver Optimierungsstatus widerspricht der "
            "TargetAllocation-Spalte."
        )
    stored_optimization_basis = stored_constraints.get(
        "optimization_model_basis"
    )
    if stored_optimization_basis is not None:
        if not isinstance(stored_optimization_basis, dict):
            raise ValueError(
                "Persistierte Optimizer-Modellbasis muss ein Objekt sein."
            )
        is_shadow_candidate = str(
            stored_optimization_basis.get("basis_id")
        ) in {
            "stochastic_shadow_candidate_v1",
            "stochastic_shadow_candidate_v2",
        }
        if (
            not is_shadow_candidate
            and str(stored_optimization_basis.get("active_method"))
            != expected_method
        ):
            raise ValueError(
                "Persistierte Optimizer-Modellbasis widerspricht der aktiven "
                "TargetAllocation-Methode."
            )

    # Recompute the exact bucket coefficients exclusively from the stored
    # canonical rows. The helper prioritizes each row's persisted risk
    # coefficient, so current BuildingBlocks cannot alter history.
    (
        _verified_rows,
        verified_bucket_risk_bps,
        verified_total_risky_bps,
    ) = _enrich_sub_allocations_with_risk(stored_sub_allocations, {})
    stored_bucket_risk_bps = stored_constraints.get(
        "risky_fraction_per_bucket_bps"
    )
    expected_bucket_risk_bps = {
        bucket: int(verified_bucket_risk_bps[bucket])
        for bucket in BUCKET_FIELDS
    }
    if stored_bucket_risk_bps != expected_bucket_risk_bps:
        raise ValueError(
            "Persistierte Bucket-Risikokoeffizienten widersprechen dem "
            "kanonischen Sub-Allokationsplan."
        )
    typed_total_risky_bps = getattr(
        allocation, "risky_fraction_bps_at_generation", None
    )
    if (
        typed_total_risky_bps is None
        or int(typed_total_risky_bps) != int(verified_total_risky_bps)
    ):
        raise ValueError(
            "Persistierte Portfolio-Risky-Fraction widerspricht dem "
            "gehashten Allocation-Context."
        )

    stored_engine_version = str(
        stored_constraints.get("engine_version") or ""
    )
    if stored_engine_version not in {
        "stochastic_core_v1",
        "stochastic_core_v2",
    }:
        raise ValueError(
            "Persistierte Allocation-Engine-Version ist unbekannt oder fehlt."
        )

    persisted_context_payload = {
        "engine_version": stored_engine_version,
        "policy_id": str(allocation.policy_id),
        "cma_id": str(allocation.capital_market_assumptions_id),
        "assessment_id": str(allocation.based_on_assessment_id),
        "input_snapshot_hash": str(allocation.input_snapshot_hash),
        "preferences_json": allocation.preferences_json,
        "targets_bps": {
            bucket: int(targets[bucket]) for bucket in BUCKET_FIELDS
        },
        "sub_allocations": stored_sub_allocations,
        "effective_constraints": stored_constraints,
        "optimization_seed": getattr(allocation, "optimization_seed", None),
    }
    recomputed_context_hash = hashlib.sha256(
        json.dumps(
            persisted_context_payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    if recomputed_context_hash != str(stored_context_hash):
        raise ValueError(
            "Allocation-Context-Hash stimmt nicht mit den persistierten "
            "Entscheidungsartefakten ueberein."
        )
    return stored_sub_allocations, stored_constraints


def evaluate_goal_sensitivity(
    db: Session,
    mandate: Mandate,
    user_id: str,
    goal_id: str,
    target_delta_pct: int,
    horizon_delta_years: int = 0,
) -> dict:
    """Live-Sensitivity: ein Goal gegen aktuelle Modellinputs reoptimieren.

    ``horizon_delta_years`` wird typabhaengig angewendet: Beginn und Ende
    wiederkehrender Ausgaben verschieben sich gemeinsam (Dauer bleibt
    erhalten); bei Renditezielen verschiebt sich der Solver-Horizont.

    Laeuft den Solver zweimal mit identischem Seed:
      1. Baseline mit unveraenderten Goal-Werten
      2. Modifiziert: target_amount * (1+delta/100) UND horizon ± horizon_delta_years

    Identischer Seed -> identischer gemeinsamer Szenario-Praefix. Dies ist
    bewusst eine Live-Reoptimierung mit aktuellen CMA/Goals/Cashflows und den
    persistierten harten Allocation-Constraints, kein historischer Replay.

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
    # Same complete, strategy-ready contract as the primary Generate path.
    # Sensitivity is a solver run, not a preview that may invent score 10.
    assessment = require_strategy_ready_assessment(db, mandate.id)

    inputs = _load_allocation_inputs(db, mandate, simulation_prefs={}, cma=cma)
    _assert_allocation_has_basis(
        int(inputs["advisory_wealth_rappen"]),
        int(inputs["recurring_income_rappen"]),
        int(inputs["recurring_expense_rappen"]),
        int(inputs["capital_inflow_rappen"]),
        int(inputs["capital_outflow_rappen"]),
    )
    goals = inputs["goals"]
    target_goal = next(
        (g for g in goals if g.id == goal_id and g.mandate_id == mandate.id),
        None,
    )
    if target_goal is None:
        raise ValueError(f"Goal {goal_id} nicht gefunden im Mandanten {mandate.id}.")

    def _shift_iso_year(value: str | None, delta: int) -> str | None:
        parsed = _parse_iso_date(value)
        if parsed is None or not delta:
            return value
        return add_calendar_years(parsed, int(delta)).isoformat()

    def _modified_goal_state(
        active_goals: list,
        active_target_goal,
        baseline_solver_horizon: int,
    ) -> dict:
        def _goal_required_horizon(
            goal,
            *,
            preserve_open_ended_baseline: bool = True,
        ) -> int:
            """Earliest horizon that still represents this goal completely."""
            candidates = [max(1, int(getattr(goal, "horizon_years", 0) or 1))]
            target_date = _parse_iso_date(getattr(goal, "target_date", None))
            if target_date is not None:
                candidates.append(max(1, calendar_years_until(target_date)))
            if (
                preserve_open_ended_baseline
                and int(getattr(goal, "is_ongoing", 0) or 0)
                and target_date is None
            ):
                # An open-ended liability was part of the baseline horizon and
                # cannot be shortened by perturbing a different return goal.
                candidates.append(int(baseline_solver_horizon))
            return max(candidates)

        baseline_amount = int(active_target_goal.target_amount_rappen or 0)
        baseline_wealth = int(active_target_goal.target_wealth_rappen or 0)
        baseline_return_bps = int(active_target_goal.target_return_bps or 0)
        factor = 1.0 + (target_delta_pct / 100.0)
        new_amount = int(round(baseline_amount * factor))
        new_wealth = int(round(baseline_wealth * factor))
        new_return_bps = int(round(baseline_return_bps * factor))
        original_horizon = active_target_goal.horizon_years
        original_target_date = active_target_goal.target_date
        original_start_date = active_target_goal.start_date
        new_horizon = original_horizon
        new_target_date = original_target_date
        new_start_date = original_start_date
        if horizon_delta_years and original_horizon is not None:
            new_horizon = max(
                1,
                int(original_horizon) + int(horizon_delta_years),
            )

        goal_type = _norm_text(active_target_goal.goal_type)
        if horizon_delta_years:
            # A date-only wealth, one-time or return goal derives its model
            # horizon from target_date.  Shifting only horizon_years made the
            # requested counterfactual a no-op whenever that nullable field
            # was absent.  Move every explicit evaluation/end date; recurring
            # goals additionally move their start below so their duration is
            # preserved.
            new_target_date = _shift_iso_year(
                original_target_date,
                horizon_delta_years,
            )
            if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe"):
                new_start_date = _shift_iso_year(
                    original_start_date,
                    horizon_delta_years,
                )

        is_open_ended_stream = (
            goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe")
            and int(getattr(active_target_goal, "is_ongoing", 0) or 0)
            and not original_target_date
        )
        if horizon_delta_years and is_open_ended_stream and new_start_date:
            # ``target_date=None`` means "until the evaluation horizon".  A
            # sensitivity shift must move that implicit end together with the
            # start.  Merely changing the run horizon is insufficient when an
            # unrelated goal pins the overall run at the old end: the shifted
            # pension would then gain/lose payment years. Materialize an
            # ephemeral end date for the counterfactual only; the ORM row and
            # persisted goal remain open-ended.
            original_start = _parse_iso_date(original_start_date)
            shifted_start = _parse_iso_date(new_start_date)
            if original_start is not None and shifted_start is not None:
                original_start_index = max(
                    1,
                    calendar_years_until(original_start),
                )
                stream_duration = max(
                    1,
                    int(baseline_solver_horizon)
                    - int(original_start_index)
                    + 1,
                )
                new_target_date = add_calendar_years(
                    shifted_start,
                    stream_duration - 1,
                ).isoformat()
            elif goal_type != "Renditeziel":
                new_target_date = _shift_iso_year(
                    original_target_date,
                    horizon_delta_years,
                )

        modified_goal_data = {
            column.name: getattr(active_target_goal, column.name)
            for column in Goal.__table__.columns
        }
        modified_goal_data.update({
            "target_amount_rappen": new_amount,
            "target_wealth_rappen": new_wealth,
            "target_return_bps": new_return_bps,
            "horizon_years": new_horizon,
            "target_date": new_target_date,
            "start_date": new_start_date,
        })
        modified_goal = SimpleNamespace(**modified_goal_data)
        modified_goal_horizon = _goal_required_horizon(
            modified_goal,
            preserve_open_ended_baseline=False,
        )
        if is_open_ended_stream:
            # Preserve the implicit duration of an open-ended stream in both
            # directions.  The target goal itself must not first re-add the
            # old baseline floor, otherwise a negative shift moves its start
            # earlier while leaving the end fixed and creates extra payments.
            modified_goal_horizon = max(
                int(modified_goal_horizon),
                int(baseline_solver_horizon) + int(horizon_delta_years),
            )
        modified_goals = [
            modified_goal
            if str(goal.id) == str(active_target_goal.id)
            else goal
            for goal in active_goals
        ]
        unaffected_goal_horizon = max(
            (
                _goal_required_horizon(goal)
                for goal in active_goals
                if str(goal.id) != str(active_target_goal.id)
            ),
            default=1,
        )
        # Recompute only genuinely independent model floors. Calling
        # _simulation_horizon_years without an explicit override would add
        # the generic 10-year default again. For a negative shift of the
        # very goal that established that default, this would move the start
        # while pinning the end and invent extra pension payments. The
        # implementation minimum (7 years) and an explicit/lifecycle-derived
        # life-expectancy end remain real independent floors; unaffected goals
        # are already represented by unaffected_goal_horizon above.
        life_year = life_expectancy_year_for(mandate=mandate)
        life_horizon = (
            max(0, int(life_year) - date.today().year + 1)
            if life_year is not None
            else 0
        )
        unaffected_model_horizon = max(7, int(life_horizon))
        modified_run_horizon = max(
            1,
            int(modified_goal_horizon),
            int(unaffected_goal_horizon),
            int(unaffected_model_horizon),
        )
        return {
            "baseline_amount": baseline_amount,
            "baseline_wealth": baseline_wealth,
            "baseline_return_bps": baseline_return_bps,
            "new_amount": new_amount,
            "new_wealth": new_wealth,
            "new_return_bps": new_return_bps,
            "original_horizon": original_horizon,
            "new_horizon": new_horizon,
            "goal_type": goal_type,
            "modified_goals": modified_goals,
            "modified_run_horizon": modified_run_horizon,
        }

    natural_cashflow_series = list(
        inputs.get(
            "optimizer_cashflow_projection_series_rappen",
            inputs["cashflow_projection_series_rappen"],
        )
    )
    baseline_solver_horizon = max(
        10,
        int(len(natural_cashflow_series) or 10),
    )
    goal_state = _modified_goal_state(
        goals,
        target_goal,
        baseline_solver_horizon,
    )
    projection_horizon = max(
        baseline_solver_horizon,
        int(goal_state["modified_run_horizon"]),
    )
    if len(natural_cashflow_series) < projection_horizon:
        # Re-project recurring cashflows, inflation, tax, FX and foundation to
        # the longest compared horizon. Padding a shorter series with zero
        # would turn a horizon change into a hidden cashflow change.
        inputs = _load_allocation_inputs(
            db,
            mandate,
            simulation_prefs={"horizonYears": projection_horizon},
            cma=cma,
        )
        goals = inputs["goals"]
        target_goal = next(
            (
                goal
                for goal in goals
                if str(goal.id) == str(goal_id)
                and str(goal.mandate_id) == str(mandate.id)
            ),
            None,
        )
        if target_goal is None:
            raise ValueError(
                f"Goal {goal_id} nicht gefunden im Mandanten {mandate.id}."
            )
        goal_state = _modified_goal_state(
            goals,
            target_goal,
            baseline_solver_horizon,
        )

    advisory_wealth_rappen = inputs["advisory_wealth_rappen"]
    cashflow_projection_series_rappen = inputs.get(
        "optimizer_cashflow_projection_series_rappen",
        inputs["cashflow_projection_series_rappen"],
    )
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
    horizon = baseline_solver_horizon

    building_blocks_rows = _building_block_rows_for_policy(
        db,
        policy.id,
        getattr(mandate, "investment_universe", None),
        jurisdiction,
    )
    _validate_sub_cma_universe(
        cma,
        {
            str(getattr(row, "sub_asset_class", "") or "")
            for row in _building_block_rows_for_policy(
                db, policy.id, None, jurisdiction
            )
        },
    )

    from services.optimizer.constraints import (
        MAX_ALTERNATIVES,
        MAX_REAL_ESTATE,
        MIN_LIQUIDITY,
        OptimizerInputError,
        bands_from_house_matrix_row,
        bucket_risky_fractions_from_building_blocks,
        build_bounds,
    )
    from services.optimizer.solver import deterministic_seed, run_solver

    # Live counterfactual: current model inputs, but the active decision's
    # immutable sub-mix and hard constraints. This avoids silently changing
    # policy while remaining explicit that this is not a historic replay.
    current_allocation = _current_target_allocation_or_none(db, mandate.id)
    rf_per_bucket = None
    sensitivity_sub_allocations = None
    sensitivity_effective_bounds = None
    sensitivity_risk_budget_bps = int(house_matrix.max_risky_fraction_bps)
    sensitivity_response_constraint_basis = "current_house_matrix"
    sensitivity_hash_constraint_source = "current_house_matrix"
    sensitivity_external_wealth = max(
        0,
        int(inputs["total_wealth_rappen"])
        - int(inputs["advisory_wealth_rappen"]),
    )
    if current_allocation is not None:
        allocation_targets = {
            bucket: int(getattr(current_allocation, f"target_{bucket}_bps"))
            for bucket in BUCKET_FIELDS
        }
        allocation_minimums = {
            bucket: int(
                getattr(current_allocation, f"band_{bucket}_min_bps") or 0
            )
            for bucket in BUCKET_FIELDS
        }
        allocation_maximums = {
            bucket: int(
                getattr(current_allocation, f"band_{bucket}_max_bps") or 0
            )
            for bucket in BUCKET_FIELDS
        }
        (
            sensitivity_sub_allocations,
            verified_constraints,
        ) = _verified_persisted_allocation_context(
            current_allocation,
            targets=allocation_targets,
            minimums=allocation_minimums,
            maximums=allocation_maximums,
        )
        if verified_constraints is not None:
            raw_bounds = verified_constraints["bounds_bps"]
            sensitivity_effective_bounds = {
                bucket: (
                    int(raw_bounds[bucket][0]),
                    int(raw_bounds[bucket][1]),
                )
                for bucket in BUCKET_FIELDS
            }
            raw_risky = verified_constraints[
                "risky_fraction_per_bucket_bps"
            ]
            rf_per_bucket = {
                bucket: int(raw_risky[bucket]) / 10000.0
                for bucket in BUCKET_FIELDS
            }
            sensitivity_risk_budget_bps = int(
                verified_constraints["risk_budget_bps"]
            )
            sensitivity_response_constraint_basis = (
                "persisted_active_allocation_context"
            )
            sensitivity_hash_constraint_source = (
                "persisted_effective_context"
            )

    # Sensitivity is a live counterfactual. Recompute the strategy base from
    # today's wealth, goals and cashflows; only the active decision's canonical
    # sub-mix and hard constraints remain persisted inputs.
    sensitivity_prefs = _normalize_preferences(
        _allocation_snapshot_preferences(current_allocation)
        if current_allocation is not None
        else None
    )
    sensitivity_prefs = _merge_mandate_defaults_into_prefs(
        sensitivity_prefs, mandate
    )
    sensitivity_external_reserve: int
    if current_allocation is None:
        # There is no immutable allocation artifact to reuse yet. Build the
        # exact stochastic candidate context used by Generate instead of
        # degrading to an unweighted building-block average. The sequence is
        # deliberately kept identical: House/policy bands -> mandate prefs ->
        # exposure/goal/reserve tilts -> global caps/floor -> reserve floor ->
        # maxIlliquid canonical sub-mix -> exact per-bucket risky fractions.
        live_targets, live_minimums, live_maximums = _baseline_target_bands(
            house_matrix,
            policy,
        )
        live_reasoning: list[str] = []
        _apply_band_preferences(
            sensitivity_prefs["bands"],
            live_targets,
            live_minimums,
            live_maximums,
            live_reasoning,
        )
        live_manual_target_override = _has_manual_target_overrides(
            sensitivity_prefs["bands"]
        )
        _apply_external_exposure_tilts(
            live_targets,
            live_minimums,
            live_maximums,
            inputs["total_summary"],
            house_matrix,
            live_manual_target_override,
            live_reasoning,
        )
        live_reserve_needed, sensitivity_external_reserve = (
            _apply_goal_and_reserve_tilts(
                targets=live_targets,
                minimums=live_minimums,
                maximums=live_maximums,
                goals=goals,
                limits_prefs=sensitivity_prefs["limits"],
                asset_class_prefs=sensitivity_prefs["assetClasses"],
                recurring_net_cashflow_rappen=int(
                    inputs["recurring_net_cashflow_rappen"]
                ),
                recurring_cashflow_projection_series_rappen=list(
                    inputs["recurring_cashflow_projection_series_rappen"]
                ),
                advisory_wealth_rappen=int(inputs["advisory_wealth_rappen"]),
                reasoning=live_reasoning,
                unlocked_other_assets_rappen=int(
                    inputs.get("unlocked_other_assets_rappen") or 0
                ),
                inflow_projection_series_rappen=list(
                    inputs.get("inflow_projection_series_rappen") or []
                ),
            )
        )

        global_caps_bps = {
            "real_estate": int(round(MAX_REAL_ESTATE * 10000)),
            "alternatives": int(round(MAX_ALTERNATIVES * 10000)),
        }
        for bucket, cap_bps in global_caps_bps.items():
            if int(live_minimums[bucket]) > cap_bps:
                raise OptimizerInputError(
                    f"Die Mindestquote fuer {bucket} ueberschreitet die "
                    f"globale Obergrenze ({live_minimums[bucket]} > "
                    f"{cap_bps} bps)."
                )
            live_maximums[bucket] = min(
                int(live_maximums[bucket]),
                cap_bps,
            )
        global_liquidity_floor_bps = int(round(MIN_LIQUIDITY * 10000))
        if int(live_maximums["liquidity"]) < global_liquidity_floor_bps:
            raise OptimizerInputError(
                "Die Liquiditaets-Obergrenze liegt unter der globalen "
                f"Mindestquote ({live_maximums['liquidity']} < "
                f"{global_liquidity_floor_bps} bps)."
            )
        live_minimums["liquidity"] = max(
            int(live_minimums["liquidity"]),
            global_liquidity_floor_bps,
        )
        live_targets = _rebalance_to_total(
            live_targets,
            live_minimums,
            live_maximums,
        )

        live_investable_wealth = _investable_advisory_wealth_rappen(
            int(inputs["advisory_wealth_rappen"]),
            sensitivity_external_reserve,
        )
        if live_investable_wealth > 0 and live_reserve_needed > 0:
            saa_reserve_rappen = min(
                int(live_reserve_needed),
                int(round(
                    int(inputs["advisory_wealth_rappen"])
                    * _SAA_LIQUIDITY_HARD_CAP_BPS
                    / 10000
                )),
            )
            reserve_floor_bps = min(
                10000,
                (
                    int(saa_reserve_rappen) * 10000
                    + int(live_investable_wealth)
                    - 1
                )
                // int(live_investable_wealth),
            )
            explicit_liquidity_max = None
            for raw_key, override in (
                sensitivity_prefs["bands"] or {}
            ).items():
                if (
                    _bucket_key(raw_key) != "liquidity"
                    or not isinstance(override, dict)
                ):
                    continue
                explicit_liquidity_max = _coerce_band_bps(
                    override.get("max_bps")
                )
                if explicit_liquidity_max is not None:
                    break
            if (
                explicit_liquidity_max is not None
                and reserve_floor_bps > int(explicit_liquidity_max)
            ):
                raise OptimizerInputError(
                    "Die explizite Liquiditaets-Obergrenze ist mit der "
                    "zwingend vorzuhaltenden internen Reserve nicht "
                    "vereinbar."
                )
            live_maximums["liquidity"] = max(
                int(live_maximums["liquidity"]),
                int(reserve_floor_bps),
            )
            live_minimums["liquidity"] = max(
                int(live_minimums["liquidity"]),
                int(reserve_floor_bps),
            )
            if int(live_targets["liquidity"]) < int(
                live_minimums["liquidity"]
            ):
                live_targets["liquidity"] = int(
                    live_minimums["liquidity"]
                )
                live_targets = _rebalance_to_total(
                    live_targets,
                    live_minimums,
                    live_maximums,
                )

        live_max_illiquid_bps = _parse_bps_percent(
            sensitivity_prefs["limits"].get("maxIlliquid")
        )
        sensitivity_sub_allocations, live_effective_maximums = (
            _build_stochastic_sub_allocation_plan(
                targets=live_targets,
                minimums=live_minimums,
                maximums=live_maximums,
                preferences=sensitivity_prefs,
                max_illiquid_bps=live_max_illiquid_bps,
                reasoning=live_reasoning,
                jurisdiction=jurisdiction,
                db=db,
            )
        )
        live_maximums.update(live_effective_maximums)
        live_targets = _rebalance_to_total(
            live_targets,
            live_minimums,
            live_maximums,
        )
        live_risky_map = _building_block_risky_map(
            db,
            policy.id,
            getattr(mandate, "investment_universe", None),
            jurisdiction,
        )
        (
            sensitivity_sub_allocations,
            live_asset_risky_weights,
            _live_risky_total_unused,
        ) = _enrich_sub_allocations_with_risk(
            sensitivity_sub_allocations,
            live_risky_map,
        )
        rf_per_bucket = {
            bucket: int(live_asset_risky_weights[bucket]) / 10000.0
            for bucket in BUCKET_FIELDS
        }
        sensitivity_effective_bounds = {
            bucket: (
                int(live_minimums[bucket]),
                int(live_maximums[bucket]),
            )
            for bucket in BUCKET_FIELDS
        }
        sensitivity_response_constraint_basis = (
            "live_canonical_stochastic_context"
        )
        sensitivity_hash_constraint_source = (
            "live_canonical_stochastic_context"
        )
    else:
        sensitivity_liquidity_ceiling_bps = min(
            int(
                (
                    sensitivity_effective_bounds or {}
                ).get("liquidity", (0, 0))[1]
                or getattr(house_matrix, "liq_max_bps", 0)
                or _SAA_LIQUIDITY_HARD_CAP_BPS
            ),
            _SAA_LIQUIDITY_HARD_CAP_BPS,
        )
        _sensitivity_reserve_needed, sensitivity_external_reserve = (
            _compute_reserve_for_inputs(
                goals=goals,
                limits_prefs=sensitivity_prefs["limits"],
                asset_class_prefs=sensitivity_prefs["assetClasses"],
                recurring_net_cashflow_rappen=int(
                    inputs["recurring_net_cashflow_rappen"]
                ),
                recurring_cashflow_projection_series_rappen=list(
                    inputs["recurring_cashflow_projection_series_rappen"]
                ),
                advisory_wealth_rappen=int(
                    inputs["advisory_wealth_rappen"]
                ),
                saa_liquidity_ceiling_bps=(
                    sensitivity_liquidity_ceiling_bps
                ),
                reasoning=None,
                unlocked_other_assets_rappen=int(
                    inputs.get("unlocked_other_assets_rappen") or 0
                ),
                inflow_projection_series_rappen=list(
                    inputs.get("inflow_projection_series_rappen") or []
                ),
            )
        )
        if sensitivity_effective_bounds is None:
            # Genuine legacy allocation without persisted stochastic context.
            # This path remains explicit and strict: malformed BB data fails
            # the analysis instead of being swallowed and treated as None.
            rf_per_bucket = bucket_risky_fractions_from_building_blocks(
                building_blocks_rows
            )
    advisory_wealth_rappen = _investable_advisory_wealth_rappen(
        int(inputs["advisory_wealth_rappen"]),
        sensitivity_external_reserve,
    )
    sensitivity_external_wealth = max(
        0,
        int(inputs["total_wealth_rappen"])
        - int(inputs["advisory_wealth_rappen"]),
    )
    initially_replaced_sensitivity_tax = list(
        inputs.get("optimizer_replaced_tax_projection_series_rappen") or []
    )
    if initially_replaced_sensitivity_tax:
        effective_sensitivity_tax = _project_estimated_wealth_tax_cashflow(
            mandate,
            advisory_wealth_rappen,
            len(cashflow_projection_series_rappen),
            start_year=cashflow_totals["year"],
            inflation_series_bps=list(
                inputs.get("cashflow_inflation_series_bps") or []
            ),
            fx_source=inputs.get("cashflow_fx_source"),
            target_currency=str(inputs.get("cashflow_target_currency") or "CHF"),
        )
        cashflow_projection_series_rappen = [
            int(current) + int(initial_tax) - int(effective_tax)
            for current, initial_tax, effective_tax in zip(
                cashflow_projection_series_rappen,
                initially_replaced_sensitivity_tax,
                effective_sensitivity_tax,
            )
        ]

    sensitivity_tax_kwargs = _build_tax_solver_kwargs(mandate)
    from services.mandate_model_inputs import (
        MandateModelInputError,
        mortality_solver_kwargs_from_mandate,
    )
    from services.optimizer.constraints import OptimizerInputError

    try:
        sensitivity_mortality_kwargs = mortality_solver_kwargs_from_mandate(
            mandate
        )
    except MandateModelInputError as exc:
        raise OptimizerInputError(str(exc)) from exc

    # Pin den Seed: identisch fuer baseline + modified, damit Scenarios gleich
    # sind und das objektive Delta nur vom Goal-Shift kommt.
    cma_id = getattr(cma, "id", "no-cma")
    goal_ids = "|".join(str(getattr(g, "id", "?")) for g in goals)
    pinned_seed = deterministic_seed(
        cma_id, goal_ids, score_x10, horizon, _OPTIMIZER_N_PATHS_DEFAULT,
        "sensitivity", target_goal.id, target_delta_pct, horizon_delta_years,
    )

    def _external_series_for_horizon(run_horizon: int) -> list[int]:
        foundation = _build_external_foundation_projection(
            inputs["all_positions"],
            horizon_years=run_horizon,
            fx_source=inputs.get("cashflow_fx_source"),
            target_currency=str(inputs.get("cashflow_target_currency") or "CHF"),
        )
        return _build_external_goal_funding_series(
            external_gross_assets_rappen=max(
                0,
                int(inputs["total_summary"].total_rappen)
                - int(inputs["advisory_summary"].total_rappen),
            ),
            external_foundation_projection=foundation,
            inflation_series_bps=inflation_series_bps,
            horizon_years=run_horizon,
        )

    baseline_amount = int(goal_state["baseline_amount"])
    baseline_wealth = int(goal_state["baseline_wealth"])
    baseline_return_bps = int(goal_state["baseline_return_bps"])
    new_amount = int(goal_state["new_amount"])
    new_wealth = int(goal_state["new_wealth"])
    new_return_bps = int(goal_state["new_return_bps"])
    original_horizon = goal_state["original_horizon"]
    new_horizon = goal_state["new_horizon"]
    modified_goals = list(goal_state["modified_goals"])
    modified_run_horizon = int(goal_state["modified_run_horizon"])

    external_series_cache: dict[int, list[int]] = {}

    def _cached_external_series(run_horizon: int) -> list[int]:
        normalized_horizon = int(run_horizon)
        if normalized_horizon not in external_series_cache:
            external_series_cache[normalized_horizon] = (
                _external_series_for_horizon(normalized_horizon)
            )
        return external_series_cache[normalized_horizon]

    baseline_external_series = _cached_external_series(horizon)
    modified_external_series = _cached_external_series(modified_run_horizon)

    def _canonical_scalar(value):
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(
                    "Sensitivity-Modellkontext enthaelt NaN/Infinity."
                )
            return value
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, dict):
            return {
                str(key): _canonical_scalar(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, (list, tuple)):
            return [_canonical_scalar(item) for item in value]
        if hasattr(value, "tolist"):
            return _canonical_scalar(value.tolist())
        state = getattr(value, "__dict__", None)
        if isinstance(state, dict):
            return {
                "class": f"{type(value).__module__}.{type(value).__qualname__}",
                "state": _canonical_scalar({
                    key: item
                    for key, item in state.items()
                    if not str(key).startswith("_")
                }),
            }
        return str(value)

    cma_snapshot = {
        column.name: _canonical_scalar(getattr(cma, column.name))
        for column in CapitalMarketAssumption.__table__.columns
    }

    def _goal_snapshot(goal) -> dict:
        return {
            column.name: _canonical_scalar(getattr(goal, column.name, None))
            for column in Goal.__table__.columns
        }

    sensitivity_target_currency = str(
        inputs.get("cashflow_target_currency") or "CHF"
    ).upper().strip()
    sensitivity_currencies = {
        str(getattr(row, "currency", None) or sensitivity_target_currency)
        .upper()
        .strip()
        for row in [
            *(inputs.get("all_positions") or []),
            *(inputs.get("cashflows") or []),
            *(inputs.get("wealth_inflows") or []),
        ]
    }
    sensitivity_fx_basis = inputs[
        "cashflow_fx_source"
    ].canonical_model_signature(
        sensitivity_currencies,
        target_currency=sensitivity_target_currency,
    )
    if sensitivity_effective_bounds is None:
        sensitivity_solver_bounds_for_hash = {
            bucket: [
                int(round(lower * 10000)),
                int(round(upper * 10000)),
            ]
            for bucket, (lower, upper) in zip(
                BUCKET_FIELDS,
                build_bounds(bands_from_house_matrix_row(house_matrix)),
            )
        }
    else:
        sensitivity_solver_bounds_for_hash = {
            bucket: [int(bounds[0]), int(bounds[1])]
            for bucket, bounds in sensitivity_effective_bounds.items()
        }

    def _model_input_hash(
        context_goals: list,
        *,
        run_horizon: int,
        external_series: list[int],
    ) -> str:
        payload = {
            "version": "sensitivity_live_context_v3_complete",
            "cma": cma_snapshot,
            "seed": int(pinned_seed),
            "scenario_horizon_years": int(projection_horizon),
            "horizon_years": int(run_horizon),
            "n_paths": int(_OPTIMIZER_N_PATHS_DEFAULT),
            "score_x10": int(score_x10),
            "advisory_wealth_rappen": int(advisory_wealth_rappen),
            "external_wealth_rappen": int(sensitivity_external_wealth),
            "cashflow_series_rappen": [
                int(value)
                for value in cashflow_projection_series_rappen[:run_horizon]
            ],
            "inflation_series_bps": [
                int(value) for value in inflation_series_bps[:run_horizon]
            ],
            "external_wealth_series_rappen": [
                int(value) for value in external_series
            ],
            "goals": sorted(
                (_goal_snapshot(goal) for goal in context_goals),
                key=lambda row: str(row.get("id") or ""),
            ),
            "effective_bounds_bps": sensitivity_effective_bounds,
            "solver_bounds_bps": sensitivity_solver_bounds_for_hash,
            "constraint_source": sensitivity_hash_constraint_source,
            "risky_fraction_per_bucket": rf_per_bucket,
            "risk_budget_bps": int(sensitivity_risk_budget_bps),
            "sub_allocations": sensitivity_sub_allocations,
            "tax_context": _canonical_scalar(sensitivity_tax_kwargs),
            "mortality_context": _canonical_scalar(
                sensitivity_mortality_kwargs
            ),
            "fx_basis": sensitivity_fx_basis,
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

    baseline_model_input_hash = _model_input_hash(
        goals,
        run_horizon=horizon,
        external_series=baseline_external_series,
    )
    modified_model_input_hash = _model_input_hash(
        modified_goals,
        run_horizon=modified_run_horizon,
        external_series=modified_external_series,
    )

    def _solve(
        context_goals: list,
        *,
        run_horizon: int,
        external_series: list[int],
    ):
        return run_solver(
            cma=cma,
            goals=context_goals,
            house_matrix_row=house_matrix,
            score_x10=score_x10,
            advisory_wealth_rappen=advisory_wealth_rappen,
            cashflow_series_rappen=(
                cashflow_projection_series_rappen[:run_horizon]
            ),
            external_wealth_rappen=sensitivity_external_wealth,
            external_wealth_series_rappen=external_series,
            horizon_years=run_horizon,
            scenario_horizon_years=projection_horizon,
            n_paths=_OPTIMIZER_N_PATHS_DEFAULT,
            seed=pinned_seed,
            inflation_series_bps=inflation_series_bps[:run_horizon],
            risky_fraction_per_bucket=rf_per_bucket,
            max_risky_fraction_bps=sensitivity_risk_budget_bps,
            sub_allocations=sensitivity_sub_allocations,
            effective_bounds_bps=sensitivity_effective_bounds,
            **sensitivity_mortality_kwargs,
            **sensitivity_tax_kwargs,
        )

    baseline_result = _solve(
        goals,
        run_horizon=horizon,
        external_series=baseline_external_series,
    )
    modified_result = _solve(
        modified_goals,
        run_horizon=modified_run_horizon,
        external_series=modified_external_series,
    )

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

    primary_baseline = baseline_amount or baseline_wealth or baseline_return_bps
    primary_new = (
        new_amount
        if baseline_amount
        else (new_wealth if baseline_wealth else new_return_bps)
    )

    return {
        "goal_id": target_goal.id,
        "delta_pct": int(target_delta_pct),
        # Sprint U-P5 Fix H9: horizon-Delta exponiert
        "horizon_delta_years": int(horizon_delta_years),
        "horizon_years_baseline": int(original_horizon) if original_horizon is not None else None,
        "horizon_years_new": int(new_horizon) if new_horizon is not None else None,
        "solver_horizon_years_baseline": int(horizon),
        "solver_horizon_years_new": int(modified_run_horizon),
        "analysis_basis": (
            "live_reoptimization_common_scenarios_current_inputs_v3"
        ),
        "allocation_context_hash": (
            str(getattr(current_allocation, "allocation_context_hash", "") or "")
            or None
        ),
        "live_model_input_hash": baseline_model_input_hash,
        "baseline_model_input_hash": baseline_model_input_hash,
        "modified_model_input_hash": modified_model_input_hash,
        "scenario_pairing_basis": (
            "same_seed_same_max_horizon_cube_exact_path_prefix_v1"
        ),
        "fx_basis": sensitivity_fx_basis,
        "capital_market_assumptions_id": str(cma_id),
        "solver_seed": int(pinned_seed),
        "wealth_basis": (
            "live_current_investable_advisory_after_recomputed_reserve"
        ),
        "constraint_basis": sensitivity_response_constraint_basis,
        "external_foundation_basis": (
            "live_cpi_gross_assets_exact_liability_and_pledged_transfer_v2"
        ),
        "target_amount_rappen_baseline": int(primary_baseline),
        "target_amount_rappen_new": int(primary_new),
        "target_return_bps_baseline": int(baseline_return_bps),
        "target_return_bps_new": int(new_return_bps),
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
    current_cma_for_drift = cma
    modern_context = int(
        getattr(allocation, "context_artifacts_required", 0) or 0
    ) == 1
    if modern_context and str(getattr(allocation, "policy_id", "") or "") != str(
        getattr(policy, "id", "") or ""
    ):
        raise ValueError(
            "Die Soll-Allokation und die geladene Optimizer-Policy haben "
            "unterschiedliche Snapshot-Anker."
        )
    if modern_context and str(
        getattr(allocation, "based_on_assessment_id", "") or ""
    ) != str(getattr(assessment, "id", "") or ""):
        raise ValueError(
            "Die Soll-Allokation basiert nicht auf dem aktuellen "
            "Risikoprofil; bitte Strategie neu berechnen."
        )
    # Identitaets-/Anker-Pruefung (oben) muss vor der Inhalts-Validierung
    # laufen: ein falsch zugeordnetes Assessment-Objekt soll als "falsches
    # Risikoprofil" erkannt werden, nicht an einer zufaellig fehlenden
    # final_score_x10 auf diesem Fremdobjekt scheitern.
    validate_risk_assessment_model_input(
        assessment,
        mandate_type=getattr(mandate, "mandate_type", None),
    )
    snapshot_cma_id = str(
        getattr(allocation, "capital_market_assumptions_id", "") or ""
    ).strip()
    if (
        modern_context and not snapshot_cma_id
    ):
        raise ValueError(
            "Die moderne Soll-Allokation besitzt keinen unveraenderlichen "
            "CMA-Snapshot-Anker; aktuelle Ersatzannahmen sind unzulaessig."
        )
    if snapshot_cma_id:
        snapshot_cma = db.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == snapshot_cma_id,
            CapitalMarketAssumption.deleted_at.is_(None),
        ).first()
        if snapshot_cma is None:
            raise ValueError(
                "Die von der Soll-Allokation referenzierte CMA ist nicht mehr "
                "verfuegbar; eine Analyse mit aktuellen Ersatzannahmen ist "
                "unzulässig. Bitte Strategie neu berechnen."
            )
        cma = snapshot_cma

    prefs = _normalize_preferences(
        preferences if preferences is not None else _allocation_snapshot_preferences(allocation)
    )
    # Sprint B1: Mandanten-Default-Building-Blocks als Fallback (rebuild path).
    prefs = _merge_mandate_defaults_into_prefs(prefs, mandate)
    # WP2 (Engine-Wiring Jurisdiktion, 2026-07-31): siehe generate_target_allocation.
    jurisdiction = resolve_mandate_jurisdiction(mandate)
    score_bucket = _risk_score_bucket(assessment)
    house_matrix = _house_matrix_or_default(db, policy, score_bucket)
    # Rebuild uses the same fail-closed, versioned FX source as generation.
    from services.currency.fx_rates import FXRateSource
    fx_source = FXRateSource.from_db_for_model(db)
    target_currency = str(getattr(mandate, "base_currency", "CHF") or "CHF").upper()

    all_position_rows = db.query(WealthPosition).filter(
        WealthPosition.client_id == mandate.client_id,
        WealthPosition.deleted_at.is_(None),
    ).all()
    all_positions = _strictly_active_rows(
        all_position_rows,
        label="Vermoegensposition",
    )
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
    _validate_active_wealth_position_semantics(all_positions)
    # Sprint B2: Anderes-Vermoegen-Schloss-Pool fuer Reserve-Reduktion (rebuild path).
    unlocked_other_assets_rappen = sum(
        _convert_position_amount_to_target_currency(pos, fx_source, target_currency)
        for pos in all_positions
        if int(getattr(pos, "is_available_for_goal_funding", 0) or 0) == 1
        and _norm_text(getattr(pos, "assignment", "")) == "Anderes Vermoegen"
    )

    cashflow_rows = db.query(Cashflow).filter(
        Cashflow.client_id == mandate.client_id,
        Cashflow.deleted_at.is_(None),
    ).all()
    cashflows = _strictly_active_rows(cashflow_rows, label="Cashflow")
    _validate_active_cashflow_inputs(cashflows)
    # 2026-06-14: vermögensgetriebene Cashflows (Hypothekarzins, Amortisation,
    # Miet-/Zinserträge) AUCH im Rebuild-/Recommendation-Pfad einspeisen — sonst
    # rechnete build_target_payload_from_allocation mit unvollständigen Cashflows
    # (inkonsistent zu _load_allocation_inputs). Reserve/Empfehlung sehen damit
    # dieselben Cashflows wie Cashflow-Ansicht und Engine-Projektion.
    # Roadmap #39 (2026-08-07): optional geschaetzte Vermoegenssteuer dito.
    rebuild_derived_wealth_cashflows = derive_wealth_cashflows(all_positions)
    rebuild_derived_tax_cashflows = derive_tax_cashflow(mandate, total_wealth_rappen)
    cashflows = (
        list(cashflows)
        + rebuild_derived_wealth_cashflows
        + rebuild_derived_tax_cashflows
    )

    goal_rows = db.query(Goal).filter(
        Goal.mandate_id == mandate.id,
        Goal.deleted_at.is_(None),
    ).order_by(Goal.rank.asc()).all()
    goals = _strictly_active_rows(goal_rows, label="Ziel")
    _validate_active_goal_inputs(goals)
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
    external_foundation_projection = _build_external_foundation_projection(
        all_positions,
        horizon_years=projection_years,
        fx_source=fx_source,
        target_currency=target_currency,
    )
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
    # Fail closed: ein Query-/Schemafehler darf nicht als "keine Zufluesse"
    # erscheinen. Sonst koennte ein Reload alte Zielgewichte mit einer
    # unvollstaendigen Live-Projektion publizieren und deren Provenienz nicht
    # mehr belegen.
    rebuild_wealth_inflows = db.query(WealthInflow).filter(
        WealthInflow.client_id == mandate.client_id,
        WealthInflow.deleted_at.is_(None),
    ).all()
    scoped_rebuild_inflows = []
    for inflow in rebuild_wealth_inflows:
        active = getattr(inflow, "is_active", None)
        if isinstance(active, bool) or not isinstance(active, int) or active not in (0, 1):
            raise ValueError("Vermoegenszufluss: is_active muss exakt 0 oder 1 sein.")
        inflow_mandate_id = getattr(inflow, "mandate_id", None)
        if inflow_mandate_id:
            inflow_mandate = db.query(Mandate).filter(Mandate.id == inflow_mandate_id).first()
            if inflow_mandate is None or inflow_mandate.client_id != mandate.client_id:
                raise ValueError(
                    "Vermoegenszufluss verweist auf ein Mandat eines anderen "
                    "Kunden oder auf ein fehlendes Mandat."
                )
            if inflow_mandate_id != mandate.id:
                continue
        if active == 1:
            scoped_rebuild_inflows.append(inflow)
    rebuild_wealth_inflows = scoped_rebuild_inflows
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
        all_positions,
        projection_years,
        cashflow_totals["year"],
        fx_source=fx_source,
        target_currency=target_currency,
    )
    if any(_mortgage_interest_adj):
        cashflow_projection_series_rappen = [
            int(cf) + int(adj)
            for cf, adj in zip(cashflow_projection_series_rappen, _mortgage_interest_adj)
        ]
    _mortgage_amortization_adj = mortgage_amortization_adjustment_series(
        all_positions,
        projection_years,
        fx_source=fx_source,
        target_currency=target_currency,
    )
    if any(_mortgage_amortization_adj):
        cashflow_projection_series_rappen = [
            int(cf) + int(adj)
            for cf, adj in zip(
                cashflow_projection_series_rappen,
                _mortgage_amortization_adj,
            )
        ]

    recurring_cashflow_projection_series_rappen = [
        int(value) + int(interest_adj) + int(amortization_adj)
        for value, interest_adj, amortization_adj in zip(
            recurring_cashflow_projection_series_rappen,
            _mortgage_interest_adj,
            _mortgage_amortization_adj,
        )
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
    stored_sub_allocations, _stored_constraints = (
        _verified_persisted_allocation_context(
            allocation,
            targets=targets,
            minimums=minimums,
            maximums=maximums,
        )
    )
    normalized_legacy_liquidity = False
    saa_liq_ceil_bps = min(
        int(maximums["liquidity"] or house_matrix.liq_max_bps or _SAA_LIQUIDITY_HARD_CAP_BPS),
        _SAA_LIQUIDITY_HARD_CAP_BPS,
    )
    if stored_sub_allocations is None and targets["liquidity"] > saa_liq_ceil_bps:
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
    _validate_sub_cma_universe(
        cma,
        {
            str(getattr(row, "sub_asset_class", "") or "")
            for row in _building_block_rows_for_policy(
                db, policy.id, None, jurisdiction
            )
        },
    )
    risky_map = _building_block_risky_map(db, policy.id, getattr(mandate, "investment_universe", None), jurisdiction)
    if stored_sub_allocations is not None:
        # Preserve the exact BuildingBlock risk coefficients from generation.
        # Current reference data is only a fallback for legacy rows that did
        # not carry the coefficient yet.
        persisted_risky_map = {
            (
                _norm_text(row.get("asset_class")),
                _norm_text(row.get("sub_asset_class")),
            ): int(row.get("risky_fraction_bps") or 0)
            for row in stored_sub_allocations
            if row.get("risky_fraction_bps") is not None
        }
        sub_allocations = stored_sub_allocations
        effective_risky_map = {**risky_map, **persisted_risky_map}
    else:
        sub_allocations = _build_sub_allocations(
            targets, prefs, jurisdiction=jurisdiction, db=db
        )
        effective_risky_map = risky_map
    sub_allocations, asset_risky_weights, risky_fraction_total_bps = (
        _enrich_sub_allocations_with_risk(
            sub_allocations, effective_risky_map
        )
    )
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
    external_goal_funding_series_rappen = (
        _build_external_goal_funding_series(
            external_gross_assets_rappen=max(
                0,
                int(total_summary.total_rappen)
                - int(advisory_summary.total_rappen),
            ),
            external_foundation_projection=external_foundation_projection,
            inflation_series_bps=goal_inflation_series_bps,
            horizon_years=len(cashflow_projection_series_rappen),
        )
    )
    rebuild_optimizer_cashflow_projection_series_rappen = list(
        cashflow_projection_series_rappen
    )
    rebuild_effective_tax_projection = _project_estimated_wealth_tax_cashflow(
        mandate,
        investable_advisory_wealth_rappen,
        len(cashflow_projection_series_rappen),
        start_year=cashflow_totals["year"],
        inflation_series_bps=cf_inflation_series_bps,
        fx_source=fx_source,
        target_currency=target_currency,
    )
    rebuild_optimizer_cashflow_projection_series_rappen = [
        int(value) - int(tax_component)
        for value, tax_component in zip(
            rebuild_optimizer_cashflow_projection_series_rappen,
            rebuild_effective_tax_projection,
        )
    ]
    rebuild_advisory_liquidity_cashflows = [
        cashflow
        for cashflow in rebuild_derived_wealth_cashflows
        if int(getattr(cashflow, "is_derived", 0) or 0) == 1
        and str(getattr(cashflow, "source", "") or "")
        == "wealth_position"
        and str(getattr(cashflow, "id", "") or "").startswith(
            "derived:liquidity_interest:"
        )
        and _norm_text(getattr(cashflow, "origin_assignment", None))
        == "Beratungsvermoegen"
    ]
    if rebuild_advisory_liquidity_cashflows:
        rebuild_embedded_interest_projection = net_cashflow_series(
            rebuild_advisory_liquidity_cashflows,
            len(cashflow_projection_series_rappen),
            start_year=cashflow_totals["year"],
            inflation_series_bps=cf_inflation_series_bps,
            fx_source=fx_source,
            target_currency=target_currency,
        )
        rebuild_optimizer_cashflow_projection_series_rappen = [
            int(value) - int(embedded_interest)
            for value, embedded_interest in zip(
                rebuild_optimizer_cashflow_projection_series_rappen,
                rebuild_embedded_interest_projection,
            )
        ]

    # A persisted allocation owns its targets.  Reporting, however, is rebuilt
    # from the live database.  Therefore the input anchor must be checked
    # *before* any deterministic or stochastic analysis is produced; otherwise
    # callers could receive old targets next to newly calculated goal paths.
    current_projection_context = _projection_context_snapshot(
        mandate=mandate,
        target_currency=target_currency,
        fx_source=fx_source,
        positions=all_positions,
        cashflows=cashflows,
        wealth_inflows=rebuild_wealth_inflows,
        cashflow_inflation_series_bps=cf_inflation_series_bps,
        goal_inflation_series_bps=goal_inflation_series_bps,
        cashflow_projection_series_rappen=cashflow_projection_series_rappen,
        optimizer_cashflow_projection_series_rappen=(
            rebuild_optimizer_cashflow_projection_series_rappen
        ),
        external_foundation_projection=external_foundation_projection,
        external_goal_funding_series_rappen=(
            external_goal_funding_series_rappen
        ),
    )
    current_snapshot_hash = _compute_input_snapshot_hash(
        advisory_positions=advisory_positions,
        all_positions=all_positions,
        cashflows=cashflows,
        goals=goals,
        advisory_wealth_rappen=advisory_wealth_rappen,
        total_wealth_rappen=total_wealth_rappen,
        wealth_inflows=rebuild_wealth_inflows,
        projection_context=current_projection_context,
    )
    legacy_projection_context = dict(current_projection_context)
    legacy_projection_context.pop("fx_basis", None)
    current_projection_v3_snapshot_hash = _compute_input_snapshot_hash(
        advisory_positions=advisory_positions,
        all_positions=all_positions,
        cashflows=cashflows,
        goals=goals,
        advisory_wealth_rappen=advisory_wealth_rappen,
        total_wealth_rappen=total_wealth_rappen,
        wealth_inflows=rebuild_wealth_inflows,
        projection_context=legacy_projection_context,
        snapshot_version="strategy_inputs_v3_projection_context",
    )
    current_foundation_snapshot_hash = _compute_input_snapshot_hash(
        advisory_positions=advisory_positions,
        all_positions=all_positions,
        cashflows=cashflows,
        goals=goals,
        advisory_wealth_rappen=advisory_wealth_rappen,
        total_wealth_rappen=total_wealth_rappen,
    )
    current_legacy_snapshot_hash = _compute_input_snapshot_hash(
        advisory_positions=advisory_positions,
        cashflows=cashflows,
        goals=goals,
        advisory_wealth_rappen=advisory_wealth_rappen,
        total_wealth_rappen=total_wealth_rappen,
    )
    accepted_current_snapshot_hashes = (
        current_snapshot_hash,
        current_projection_v3_snapshot_hash,
        current_foundation_snapshot_hash,
        current_legacy_snapshot_hash,
    )
    stored_input_snapshot_hash = str(
        getattr(allocation, "input_snapshot_hash", None) or ""
    )
    if (
        stored_input_snapshot_hash
        and stored_input_snapshot_hash not in accepted_current_snapshot_hashes
    ):
        raise StaleAllocationInputError(
            "Die gespeicherte Soll-Allokation ist veraltet: Vermoegen, "
            "Cashflows oder Ziele haben sich seit der Berechnung geaendert. "
            "Bitte Strategie neu berechnen; alte Targets werden nicht mit "
            "einer aktuellen Analyse kombiniert."
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
        external_foundation_projection=external_foundation_projection,
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
        expected_death_year_offset=_expected_death_year_offset_from_mandate(
            mandate
        ),
        advisory_path_series_rappen=simulation["target_mix_series_rappen"],
        total_path_series_rappen=simulation[
            "total_mix_target_series_rappen"
        ],
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
        external_foundation_projection=external_foundation_projection,
    )
    stored_optimizer_mode = str(
        getattr(allocation, "optimization_method", None) or "house_matrix"
    )
    model_basis = _build_allocation_model_basis(
        optimizer_mode=stored_optimizer_mode,
        optimizer_result=None,
        allocation=allocation,
        monte_carlo=monte_carlo,
        simulation_prefs=prefs["simulation"],
        mandate=mandate,
        stored_optimization_basis=(
            (_stored_constraints or {}).get("optimization_model_basis")
        ),
        reporting_tax_cashflow_present=any(
            str(getattr(cashflow, "source", "") or "") == "tax_estimate"
            for cashflow in cashflows
        ),
    )
    monte_carlo["model_basis"] = dict(model_basis["reporting"])
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
        # Mega-Audit (2026-08-04): fx_source/target_currency (oben in dieser
        # Funktion bereits fuer die WealthPosition-FX-Konvertierung
        # aufgesetzt) auch hier durchreichen, damit Preise aus PriceHistory
        # (in product.currency, z.B. USD) korrekt auf die Mandats-
        # Basiswaehrung umgerechnet werden -- vorher wurde jede
        # Fremdwaehrungsposition unkonvertiert bewertet (siehe
        # services.portfolio_engine_live_rebalancing._convert_price_rappen_to_target_currency).
        live_rebalancing = build_live_rebalancing_payload(
            db=db,
            allocation=allocation,
            run=current_run,
            advisory_wealth_rappen=investable_advisory_wealth_rappen,
            fx_source=fx_source,
            target_currency=target_currency,
        )
    current_preferences_json = json.dumps(prefs, sort_keys=True, default=str)
    drift_warnings = _strategy_drift_warnings(
        allocation,
        assessment=assessment,
        cma=current_cma_for_drift,
        current_input_snapshot_hash=accepted_current_snapshot_hashes,
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
        direct_property_rappen=external_foundation_projection[
            "property_series_rappen"
        ][0],
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
        "goal_achievability_basis_id": model_basis["optimization"]["basis_id"],
        "goal_analysis_basis_id": model_basis["reporting"]["basis_id"],
        "model_basis": model_basis,
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
    current_policy, current_cma = ensure_runtime_reference_data(
        db, user_id, jurisdiction=jurisdiction, tenant_id=getattr(mandate, "tenant_id", None) or None,
    )

    allocation = None
    if run.target_allocation_id:
        allocation = db.query(TargetAllocation).filter(
            TargetAllocation.id == run.target_allocation_id,
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.deleted_at.is_(None),
        ).first()
        if allocation is None:
            raise ValueError(
                "Die im RecommendationRun verankerte Soll-Allokation fehlt "
                "oder ist geloescht; ein Austausch durch die aktuelle "
                "Allokation ist unzulaessig."
            )
    else:
        allocation = _current_target_allocation_or_none(db, mandate.id)
    if not allocation:
        raise ValueError("Keine aktuelle Soll-Allokation fuer dieses Mandat gefunden.")

    assessment_id = str(getattr(run, "assessment_id", "") or "").strip()
    if assessment_id:
        assessment = db.query(RiskAssessment).filter(
            RiskAssessment.id == assessment_id,
            RiskAssessment.mandate_id == mandate.id,
            RiskAssessment.deleted_at.is_(None),
        ).first()
    else:
        assessment = _current_risk_assessment_or_none(db, mandate.id)
    if not assessment:
        raise ValueError("Der RecommendationRun referenziert kein gueltiges Risikoprofil.")

    policy_id = str(getattr(run, "policy_id", "") or allocation.policy_id or "").strip()
    if policy_id != str(allocation.policy_id):
        raise ValueError("RecommendationRun und Soll-Allokation referenzieren verschiedene Policies.")
    policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_id).first()
    if policy is None:
        raise ValueError("Die im RecommendationRun verankerte Optimizer Policy fehlt.")

    allocation_cma_id = str(
        getattr(allocation, "capital_market_assumptions_id", "") or ""
    ).strip()
    run_cma_id = str(
        getattr(run, "capital_market_assumptions_id", "") or allocation_cma_id
    ).strip()
    if allocation_cma_id and run_cma_id != allocation_cma_id:
        raise ValueError("RecommendationRun und Soll-Allokation referenzieren verschiedene CMA.")
    if run_cma_id:
        cma = db.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == run_cma_id,
        ).first()
        if cma is None:
            raise ValueError("Die im RecommendationRun verankerte CMA fehlt.")
    elif getattr(allocation, "input_snapshot_hash", None):
        raise ValueError("Ein modern verankerter RecommendationRun benoetigt eine CMA-ID.")
    else:
        cma = current_cma
    allocation_assessment_id = str(
        getattr(allocation, "based_on_assessment_id", "") or ""
    ).strip()
    if allocation_assessment_id and allocation_assessment_id != str(assessment.id):
        raise ValueError(
            "RecommendationRun und Soll-Allokation referenzieren verschiedene "
            "Risikoprofile."
        )

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
        # Mega-Audit (2026-08-04): fx_source/target_currency ergaenzt, damit
        # Preise aus PriceHistory (in product.currency, z.B. USD) korrekt auf
        # die Mandats-Basiswaehrung umgerechnet werden -- siehe
        # services.portfolio_engine_live_rebalancing._convert_price_rappen_to_target_currency.
        # Diese Funktion hat (anders als build_target_payload_from_allocation)
        # keine eigene fx_source-Herleitung -- frisch aufgesetzt.
        from services.currency.fx_rates import FXRateSource
        _brpfr_fx_source = FXRateSource.from_db_for_model(db)
        _brpfr_target_currency = str(getattr(mandate, "base_currency", "CHF") or "CHF").upper()
        live_rebalancing = build_live_rebalancing_payload(
            db=db,
            allocation=allocation,
            run=run,
            advisory_wealth_rappen=investable_advisory_wealth_rappen,
            positions=positions,
            fx_source=_brpfr_fx_source,
            target_currency=_brpfr_target_currency,
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
    # 2026-08-22 (hedgingRequired-Katalogluecke): additiver Backfill, laeuft
    # unabhaengig davon ob ensure_default_products() oben tatsaechlich
    # geseedet hat (der ist idempotent pro-Produkt, nicht "Katalog leer?").
    # Gleiche Jurisdiktions-Gate wie ensure_default_products() -- die
    # HEDGED_PRODUCT_VARIANTS sind CH-spezifische Sub-Asset-Class-Namen.
    if jurisdiction in (None, "CH"):
        ensure_hedged_product_variants(db)
    prefs = _normalize_preferences(preferences)
    policy, cma = ensure_runtime_reference_data(
        db, user_id, jurisdiction=jurisdiction, tenant_id=getattr(mandate, "tenant_id", None) or None,
    )
    jurisdiction_ctx = _resolve_jurisdiction_context(db, mandate, jurisdiction)
    assessment = _current_risk_assessment_or_none(db, mandate.id)
    if not assessment:
        raise ValueError("Bitte zuerst ein aktuelles Risikoprofil speichern.")

    allocation = None
    if target_allocation_id:
        allocation = db.query(TargetAllocation).filter(
            TargetAllocation.id == target_allocation_id,
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.deleted_at.is_(None),
        ).first()
        if allocation is None:
            raise ValueError(
                "Die explizit angeforderte Soll-Allokation wurde nicht gefunden, "
                "gehoert nicht zu diesem Mandat oder ist geloescht."
            )
        if int(getattr(allocation, "is_current", 0) or 0) != 1:
            raise ValueError(
                "Aus einer veralteten Soll-Allokation darf keine neue Empfehlung "
                "erzeugt werden."
            )
    else:
        allocation = _current_target_allocation_or_none(db, mandate.id)
    if allocation:
        allocation_policy = db.query(OptimizerPolicy).filter(
            OptimizerPolicy.id == allocation.policy_id,
        ).first()
        if (
            allocation_policy is None
            or int(getattr(allocation_policy, "is_current", 0) or 0) != 1
        ):
            raise ValueError(
                "Die Soll-Allokation referenziert keine aktuelle Optimizer Policy; "
                "bitte Strategie neu berechnen."
            )
        policy = allocation_policy

        allocation_cma_id = str(
            getattr(allocation, "capital_market_assumptions_id", "") or ""
        ).strip()
        if allocation_cma_id:
            allocation_cma = db.query(CapitalMarketAssumption).filter(
                CapitalMarketAssumption.id == allocation_cma_id,
            ).first()
            if allocation_cma is None:
                raise ValueError(
                    "Die von der Soll-Allokation referenzierte CMA ist nicht mehr "
                    "verfuegbar; bitte Strategie neu berechnen."
                )
            cma = allocation_cma
        elif getattr(allocation, "input_snapshot_hash", None):
            raise ValueError(
                "Eine modern verankerte Soll-Allokation ohne CMA-Referenz ist "
                "inkonsistent; bitte Strategie neu berechnen."
            )
        based_on_assessment_id = str(
            getattr(allocation, "based_on_assessment_id", "") or ""
        ).strip()
        if based_on_assessment_id and based_on_assessment_id != str(assessment.id):
            raise ValueError(
                "Die Soll-Allokation basiert auf einem anderen Risikoprofil; "
                "bitte Strategie neu berechnen."
            )
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
        policy = db.query(OptimizerPolicy).filter(
            OptimizerPolicy.id == allocation.policy_id,
        ).one()
        if getattr(allocation, "capital_market_assumptions_id", None):
            cma = db.query(CapitalMarketAssumption).filter(
                CapitalMarketAssumption.id
                == allocation.capital_market_assumptions_id,
            ).one()

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

    # Mega-Audit (2026-08-04): fx_source/target_currency ergaenzt, siehe
    # Kommentar am generate_target_allocation-Aufruf-Pendant weiter oben in
    # dieser Datei.
    from services.currency.fx_rates import FXRateSource
    _run_fx_source = FXRateSource.from_db_for_model(db)
    _run_target_currency = str(getattr(mandate, "base_currency", "CHF") or "CHF").upper()
    live_rebalancing = build_live_rebalancing_payload(
        db=db,
        allocation=allocation,
        run=run,
        advisory_wealth_rappen=investable_advisory_wealth_rappen,
        fx_source=_run_fx_source,
        target_currency=_run_target_currency,
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
