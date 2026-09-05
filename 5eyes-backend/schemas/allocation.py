import math

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal, Optional
from schemas.common import BaseResponse
from services.cma_validation import (
    parse_correlation_matrix_json,
    parse_sub_asset_class_assumptions_json,
    validate_equity_kgv_parameters,
    validate_nelson_siegel_parameters,
)

# Zulaessiges Vokabular fuer AllocationPreferencesPayload.tilts/.bands.
# Sicherheits-Fix (2026-08-03, Berater-Audit "Restriktionen & Tilts"): unbekannte
# Keys/Values wurden bisher STILLSCHWEIGEND ignoriert (kein Fehler, keine Wirkung) --
# ein Tippfehler im Frontend (z.B. "tabacco" statt "tobacco") fuehrte dazu, dass eine
# vom Berater gesetzte Restriktion/Tilt komplett wirkungslos blieb, ohne jede
# Rueckmeldung. Diese Vokabulare sind bewusst dupliziert (statt aus services.*
# importiert), damit schemas/ als reine Leaf-Schicht ohne Abhaengigkeit auf services/
# bleibt; sie muessen synchron gehalten werden mit:
# - services/portfolio_engine_house_matrix.py (Themen-Keys der Tilts, ~Zeile 640)
# - services/portfolio_engine_payload.py (thematic_map + tilt_mode, ~Zeile 813-829)
# - services/portfolio_engine.py:_bucket_key (Bucket-Aliase der Bands, ~Zeile 415-429)
_VALID_TILT_KEYS = frozenset({"fossil", "defense", "tobacco", "alcohol", "gaming", "nuclear"})
_VALID_TILT_VALUES = frozenset({"exclude", "underweight", "neutral", "overweight"})
_VALID_BAND_KEYS = frozenset(
    {
        "equities",
        "bonds",
        "real_estate",
        "alternatives",
        "liquidity",
        "Aktien",
        "Obligationen",
        "Immobilien",
        "Alternative",
        "Liquiditaet",
        "Liquidität",
    }
)

# Restliche Sektionen von AllocationPreferencesPayload -- gleicher Sicherheits-Fix
# wie oben (2026-08, Fortsetzung "Restriktionen & Tilts"): vorher wurden diese
# Sektionen als ungeprueftes dict durchgereicht, ein Tippfehler blieb wirkungslos
# ohne Fehlermeldung. Vokabular muss synchron gehalten werden mit den Konsumenten
# in services/portfolio_engine_house_matrix.py, services/portfolio_engine_payload.py
# und services/portfolio_engine_mc_simulation.py.
_VALID_POLICY_KEYS = frozenset({"esg", "universe", "homeBias", "hedging"})
_VALID_PRODUCT_KEYS = frozenset(
    {"noDerivatives", "noLeverage", "noStructured", "listedOnly", "fundsOnly"}
)
_VALID_LIMITS_KEYS = frozenset(
    {"singlePosition", "singleIssuer", "minReserve", "maxIlliquid"}
)
_VALID_GEO_KEYS = frozenset(
    {"chFocus", "noEm", "hedgingRequired", "chfOnly", "noUsd"}
)
_VALID_ASSET_CLASS_KEYS = frozenset(
    {
        "equitiesGeo",
        "equitiesLargeCap",
        "equitiesSmid",
        "bondsDuration",
        "bondsInvestmentGrade",
        "bondsHighYield",
        "bondsEmerging",
        "realestateMarket",
        "realestateFunds",
        "realestateDirect",
        "altsGold",
        "altsLiquidAlts",
        "altsHedge",
        "altsPe",
        "altsCrypto",
        "liquidityInstrument",
        "liquidityReserveTarget",
    }
)
_VALID_SIMULATION_KEYS = frozenset(
    {
        "horizonYears",
        "stressMultiplier",
        "rebalanceMode",
        "monteCarloRuns",
        "transactionCostBps",
        "crisisMode",
        "crisisStrength",
        "tailRisk",
        "cornishFisher",
    }
)

_VALID_POLICY_VALUES = {
    "esg": frozenset(
        {
            "none",
            "best_in_class",
            "impact",
            "net_zero",
            "esg_integration",
            "negative_screening",
        }
    ),
    "universe": frozenset({"funds_only", "listed_only", "standard", "extended"}),
    "homeBias": frozenset({"ch_focus", "none", "europe_focus", "global"}),
    "hedging": frozenset({"none", "hedged", "chf_only", "risk_budget"}),
}
_VALID_ASSET_CLASS_CHOICES = {
    # CH, backwards-compatible umlaut spelling, and the currently supported
    # DE jurisdiction vocabulary.
    "equitiesGeo": frozenset(
        {
            "Schweiz Fokus",
            "Deutschland Fokus",
            "Global",
            "Europa",
            "Schwellenländer",
            "Schwellenlaender",
        }
    ),
    "bondsDuration": frozenset({"Langfristig", "Kurzfristig", "Gemischt"}),
    "realestateMarket": frozenset({"Schweiz", "Deutschland", "Ausland", "Gemischt"}),
    "liquidityInstrument": frozenset({"Geldmarktfonds", "Kontoguthaben", "Festgeld"}),
}
_ASSET_CLASS_BOOLEAN_KEYS = frozenset(
    {
        "equitiesLargeCap",
        "equitiesSmid",
        "bondsInvestmentGrade",
        "bondsHighYield",
        "bondsEmerging",
        "realestateFunds",
        "realestateDirect",
        "altsGold",
        "altsLiquidAlts",
        "altsHedge",
        "altsPe",
        "altsCrypto",
    }
)
_VALID_REBALANCE_MODES = frozenset(
    {"band", "bands", "calendar", "jaehrlich", "none", "off", "aus"}
)
_VALID_BOOLEAN_SPELLINGS = frozenset(
    {"1", "true", "yes", "on", "0", "false", "no", "off"}
)


def _validate_choice(*, section: str, key: str, value, allowed: frozenset[str]) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(
            f"{section}.{key} hat den ungueltigen Wert {value!r} "
            f"(erlaubt: {sorted(allowed)})"
        )


def _validate_strict_bool(*, section: str, key: str, value) -> None:
    if type(value) is not bool:
        raise ValueError(f"{section}.{key} muss true oder false sein")


def _parse_finite_number(
    *,
    section: str,
    key: str,
    value,
    allow_empty: bool = False,
    percent: bool = False,
    currency: bool = False,
) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_empty:
            return None
        raise ValueError(f"{section}.{key} muss eine Zahl sein")
    if type(value) is bool or not isinstance(value, (int, float, str)):
        raise ValueError(f"{section}.{key} muss eine Zahl sein")
    raw = str(value).strip()
    if currency:
        raw = raw.replace("CHF", "")
    if percent:
        raw = raw.replace("%", "")
    raw = raw.replace("'", "").replace(" ", "").replace(",", ".")
    try:
        parsed = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{section}.{key} muss eine Zahl sein") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{section}.{key} muss eine endliche Zahl sein")
    return parsed


def _validate_number_range(
    *,
    section: str,
    key: str,
    value,
    minimum: float,
    maximum: float | None = None,
    allow_empty: bool = False,
    percent: bool = False,
    currency: bool = False,
) -> None:
    parsed = _parse_finite_number(
        section=section,
        key=key,
        value=value,
        allow_empty=allow_empty,
        percent=percent,
        currency=currency,
    )
    if parsed is None:
        return
    if parsed < minimum or (maximum is not None and parsed > maximum):
        upper = f" und {maximum:g}" if maximum is not None else ""
        raise ValueError(
            f"{section}.{key} muss zwischen {minimum:g}{upper} liegen"
        )


def _validate_integer_range(
    *,
    section: str,
    key: str,
    value,
    minimum: int,
    maximum: int,
) -> None:
    if type(value) is int:
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()
        digits = raw[1:] if raw[:1] in {"+", "-"} else raw
        if not digits or not digits.isdigit():
            raise ValueError(f"{section}.{key} muss eine ganze Zahl sein")
        parsed = int(raw)
    else:
        raise ValueError(f"{section}.{key} muss eine ganze Zahl sein")
    if parsed < minimum or parsed > maximum:
        raise ValueError(
            f"{section}.{key} muss zwischen {minimum} und {maximum} liegen"
        )


class TargetAllocationCreate(BaseModel):
    # SCHEMA-04: bps-Felder auf [0,10000] begrenzt (vorher bare int → negative/
    # absurde Quoten passierten bis zur Summen-/Band-Prüfung bzw. Engine).
    target_equities_bps: int = Field(ge=0, le=10000)
    target_bonds_bps: int = Field(ge=0, le=10000)
    target_real_estate_bps: int = Field(ge=0, le=10000)
    target_alternatives_bps: int = Field(ge=0, le=10000)
    target_liquidity_bps: int = Field(ge=0, le=10000)
    band_equities_min_bps: int = Field(ge=0, le=10000)
    band_equities_max_bps: int = Field(ge=0, le=10000)
    band_bonds_min_bps: int = Field(ge=0, le=10000)
    band_bonds_max_bps: int = Field(ge=0, le=10000)
    band_real_estate_min_bps: int = Field(ge=0, le=10000)
    band_real_estate_max_bps: int = Field(ge=0, le=10000)
    band_alternatives_min_bps: int = Field(ge=0, le=10000)
    band_alternatives_max_bps: int = Field(ge=0, le=10000)
    band_liquidity_min_bps: int = Field(ge=0, le=10000)
    band_liquidity_max_bps: int = Field(ge=0, le=10000)
    risky_fraction_bps: Optional[int] = Field(default=None, ge=0, le=10000)
    based_on_assessment_id: Optional[str] = None
    policy_id: str

    @model_validator(mode="after")
    def validate_alloc(self):
        total = (
            self.target_equities_bps + self.target_bonds_bps
            + self.target_real_estate_bps + self.target_alternatives_bps
            + self.target_liquidity_bps
        )
        if total != 10000:
            raise ValueError(f"Allokation muss 10000 BP ergeben (aktuell: {total})")
        # Band checks
        checks = [
            (self.band_equities_min_bps, self.target_equities_bps, self.band_equities_max_bps, "Aktien"),
            (self.band_bonds_min_bps, self.target_bonds_bps, self.band_bonds_max_bps, "Obligationen"),
            (self.band_real_estate_min_bps, self.target_real_estate_bps, self.band_real_estate_max_bps, "Immobilien"),
            (self.band_alternatives_min_bps, self.target_alternatives_bps, self.band_alternatives_max_bps, "Alternative"),
            (self.band_liquidity_min_bps, self.target_liquidity_bps, self.band_liquidity_max_bps, "Liquidität"),
        ]
        for lo, target, hi, name in checks:
            if lo > hi:
                raise ValueError(f"{name}: Bandbreite ungültig – Min {lo} BP ist grösser als Max {hi} BP")
            if not (lo <= target <= hi):
                raise ValueError(f"{name}: Ziel {target} muss zwischen Min {lo} und Max {hi} liegen")
        return self


class TargetAllocationResponse(BaseResponse):
    id: str
    mandate_id: str
    version: int
    is_current: int
    target_equities_bps: int
    target_bonds_bps: int
    target_real_estate_bps: int
    target_alternatives_bps: int
    target_liquidity_bps: int
    band_equities_min_bps: int
    band_equities_max_bps: int
    band_bonds_min_bps: int
    band_bonds_max_bps: int
    band_real_estate_min_bps: int
    band_real_estate_max_bps: int
    band_alternatives_min_bps: int
    band_alternatives_max_bps: int
    band_liquidity_min_bps: int
    band_liquidity_max_bps: int
    risky_fraction_bps: Optional[int]
    risky_fraction_bps_at_generation: Optional[int] = None
    risk_budget_bps_at_generation: Optional[int] = None
    limiting_factor: Optional[str] = None
    goal_achievability_json: Optional[str] = None
    sub_allocations_json: Optional[str] = None
    effective_constraints_json: Optional[str] = None
    allocation_context_hash: Optional[str] = None
    context_artifacts_required: int = 0
    based_on_assessment_id: Optional[str]
    capital_market_assumptions_id: Optional[str] = None
    # C8 audit anchors
    preferences_json: Optional[str] = None
    input_snapshot_hash: Optional[str] = None
    advisory_wealth_at_generation_rappen: Optional[int] = None
    total_wealth_at_generation_rappen: Optional[int] = None
    reserve_needed_at_generation_rappen: Optional[int] = None
    external_reserve_at_generation_rappen: Optional[int] = None
    # Active allocation decision audit. These fields already exist on the ORM
    # model; declaring them here prevents FastAPI's response_model filtering
    # from hiding the Optimizer panel in the client.
    optimization_method: Optional[str] = None
    optimization_objective_value_milli: Optional[int] = None
    optimization_iterations: Optional[int] = None
    optimization_seed: Optional[int] = None
    optimization_status: Optional[str] = None
    # Phase 6: persistierte Stress-Auswertungen als JSON-String. None bei
    # house_matrix-Modus. FE deserialisiert clientseitig.
    stress_evaluations_json: Optional[str] = None
    # Phase 6.2: persistierter Solver-Reasoning-Trace (JSON-Liste).
    optimizer_reasoning_json: Optional[str] = None
    # V3 Sprint 2.1: Verknuepfung zur optimizer_runs-Zeile (nur stochastic-Modus
    # mit converged Solver). NULL bei house_matrix oder shadow_stochastic.
    optimization_run_id: Optional[str] = None
    shadow_optimization_json: Optional[str] = None
    policy_id: str
    set_by: str
    set_at: str
    approved_by: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str


class OptimizerRunResponse(BaseResponse):
    """V3 Sprint 2: ein einzelner persistierter Solver-Lauf."""
    id: str
    mandate_id: str
    target_allocation_id: Optional[str] = None
    run_at: str
    optimizer_mode: str  # 'shadow_stochastic' | 'stochastic'
    role: str            # 'shadow' | 'active'
    method: str          # 'stochastic' | 'fallback_house_matrix'
    status: str          # converged | converged_robustified | diverged | diverged_infeasible | fallback_house_matrix
    seed: int
    n_paths: int
    n_iterations: int
    n_starts_attempted: int
    objective_value_milli: Optional[int] = None
    weights_bps_json: str
    constraint_violations_json: Optional[str] = None
    reasoning_json: Optional[str] = None
    stress_evaluations_json: Optional[str] = None
    restart_results_json: Optional[str] = None
    robustification_json: Optional[str] = None
    set_by: Optional[str] = None
    created_at: str


class HouseMatrixResponse(BaseResponse):
    id: str
    policy_id: str
    score_from: int
    score_to: int
    profile_name: str
    liq_min_bps: int
    liq_target_bps: int
    liq_max_bps: int
    bonds_min_bps: int
    bonds_target_bps: int
    bonds_max_bps: int
    equity_min_bps: int
    equity_target_bps: int
    equity_max_bps: int
    real_estate_min_bps: int
    real_estate_target_bps: int
    real_estate_max_bps: int
    alt_min_bps: int
    alt_target_bps: int
    alt_max_bps: int
    equity_minimum_bps: int
    max_risky_fraction_bps: int


# Sprint U-P7 (2026-05-20): Admin-CRUD für OptimizerPolicy + HouseMatrix.
# Foundation für Backtest (Phase 2): Versionierung erlaubt parallele Varianten,
# jeder Edit erzeugt eine neue Policy-Row (Snapshot-fähig).
class HouseMatrixRowInput(BaseModel):
    score_from: int = Field(..., ge=1, le=10)
    score_to: int = Field(..., ge=1, le=10)
    profile_name: str = Field(..., min_length=1, max_length=80)
    liq_min_bps: int = Field(..., ge=0, le=10000)
    liq_target_bps: int = Field(..., ge=0, le=10000)
    liq_max_bps: int = Field(..., ge=0, le=10000)
    bonds_min_bps: int = Field(..., ge=0, le=10000)
    bonds_target_bps: int = Field(..., ge=0, le=10000)
    bonds_max_bps: int = Field(..., ge=0, le=10000)
    equity_min_bps: int = Field(..., ge=0, le=10000)
    equity_target_bps: int = Field(..., ge=0, le=10000)
    equity_max_bps: int = Field(..., ge=0, le=10000)
    real_estate_min_bps: int = Field(..., ge=0, le=10000)
    real_estate_target_bps: int = Field(..., ge=0, le=10000)
    real_estate_max_bps: int = Field(..., ge=0, le=10000)
    alt_min_bps: int = Field(..., ge=0, le=10000)
    alt_target_bps: int = Field(..., ge=0, le=10000)
    alt_max_bps: int = Field(..., ge=0, le=10000)
    equity_minimum_bps: int = Field(0, ge=0, le=10000)
    max_risky_fraction_bps: int = Field(..., ge=0, le=10000)

    @model_validator(mode="after")
    def _validate_bands_and_sum(self):
        if not (1 <= self.score_from <= self.score_to <= 10):
            raise ValueError(f"score_from ({self.score_from}) muss <= score_to ({self.score_to}) und in [1,10] sein")
        target_sum = (
            self.liq_target_bps + self.bonds_target_bps + self.equity_target_bps
            + self.real_estate_target_bps + self.alt_target_bps
        )
        if abs(target_sum - 10000) > 5:  # ±0.05% Toleranz
            raise ValueError(f"Summe Target-Quoten muss 10000 bps (100%) sein, ist {target_sum}")
        for prefix in ("liq", "bonds", "equity", "real_estate", "alt"):
            mn = getattr(self, f"{prefix}_min_bps")
            tg = getattr(self, f"{prefix}_target_bps")
            mx = getattr(self, f"{prefix}_max_bps")
            if not (mn <= tg <= mx):
                raise ValueError(f"{prefix}: min({mn}) <= target({tg}) <= max({mx}) verletzt")
        if self.equity_minimum_bps > self.equity_max_bps:
            raise ValueError(f"equity_minimum_bps ({self.equity_minimum_bps}) darf equity_max_bps ({self.equity_max_bps}) nicht überschreiten")
        return self


class OptimizerPolicyCreate(BaseModel):
    policy_name: str = Field(..., min_length=1, max_length=120)
    optimizer_engine: str = "goal_based_v1"
    max_real_estate_bps: int = Field(2000, ge=0, le=10000)
    max_alternatives_bps: int = Field(1000, ge=0, le=10000)
    min_liquidity_bps: int = Field(0, ge=0, le=10000)
    fee_model_json: Optional[str] = None
    notes: Optional[str] = None
    house_matrix_rows: list[HouseMatrixRowInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_score_coverage(self):
        # House-Matrix-Rows müssen Score 1..10 vollständig + ohne Lücken/Overlaps abdecken
        if not self.house_matrix_rows:
            return self  # Leerer Create → fallback auf Default-Seeds beim Backend
        rows = sorted(self.house_matrix_rows, key=lambda r: r.score_from)
        if rows[0].score_from != 1:
            raise ValueError(f"Erste House-Matrix-Row muss score_from=1 haben, ist {rows[0].score_from}")
        if rows[-1].score_to != 10:
            raise ValueError(f"Letzte House-Matrix-Row muss score_to=10 haben, ist {rows[-1].score_to}")
        for prev, curr in zip(rows, rows[1:]):
            if curr.score_from != prev.score_to + 1:
                raise ValueError(
                    f"Score-Lücke/Overlap zwischen score_to={prev.score_to} und nächstem "
                    f"score_from={curr.score_from} (erwarte {prev.score_to + 1})"
                )
        return self


class OptimizerPolicyUpdate(BaseModel):
    """Editiert nur Policy-Level-Felder. House-Matrix-Rows via separatem Endpoint."""
    policy_name: Optional[str] = None
    optimizer_engine: Optional[str] = None
    max_real_estate_bps: Optional[int] = Field(None, ge=0, le=10000)
    max_alternatives_bps: Optional[int] = Field(None, ge=0, le=10000)
    min_liquidity_bps: Optional[int] = Field(None, ge=0, le=10000)
    fee_model_json: Optional[str] = None
    notes: Optional[str] = None


class HouseMatrixRowsReplace(BaseModel):
    """Bulk-Update: ersetzt ALLE Rows einer Policy auf einmal (Atomic)."""
    rows: list[HouseMatrixRowInput] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _validate_score_coverage(self):
        rows = sorted(self.rows, key=lambda r: r.score_from)
        if rows[0].score_from != 1:
            raise ValueError(f"Erste Row muss score_from=1 haben")
        if rows[-1].score_to != 10:
            raise ValueError(f"Letzte Row muss score_to=10 haben")
        for prev, curr in zip(rows, rows[1:]):
            if curr.score_from != prev.score_to + 1:
                raise ValueError(
                    f"Score-Lücke/Overlap zwischen {prev.score_to} und {curr.score_from}"
                )
        return self


class OptimizerPolicyResponse(BaseResponse):
    id: str
    policy_name: str
    version: int
    is_current: int
    valid_from: str
    valid_to: Optional[str] = None
    optimizer_engine: str
    max_real_estate_bps: int
    max_alternatives_bps: int
    min_liquidity_bps: int
    fee_model_json: Optional[str] = None
    notes: Optional[str] = None
    created_by: str
    created_at: str
    updated_at: str


class OptimizerPolicyDetailResponse(OptimizerPolicyResponse):
    house_matrix_rows: list[HouseMatrixResponse] = Field(default_factory=list)


class CapitalMarketAssumptionCreate(BaseModel):
    assumption_set_name: str = "Standard"
    valid_from: str
    valid_until: Optional[str] = None
    bonds_chf_ig_return_bps: Optional[int] = None
    bonds_chf_ig_vol_bps: Optional[int] = None
    bonds_fx_hedged_return_bps: Optional[int] = None
    bonds_fx_hedged_vol_bps: Optional[int] = None
    bonds_hy_return_bps: Optional[int] = None
    bonds_hy_vol_bps: Optional[int] = None
    equity_ch_return_bps: Optional[int] = None
    equity_ch_vol_bps: Optional[int] = None
    equity_intl_return_bps: Optional[int] = None
    equity_intl_vol_bps: Optional[int] = None
    equity_em_return_bps: Optional[int] = None
    equity_em_vol_bps: Optional[int] = None
    real_estate_ch_return_bps: Optional[int] = None
    real_estate_ch_vol_bps: Optional[int] = None
    alternatives_gold_return_bps: Optional[int] = None
    alternatives_gold_vol_bps: Optional[int] = None
    liquidity_return_bps: Optional[int] = None
    liquidity_vol_bps: Optional[int] = None
    inflation_path_json: Optional[str] = None
    correlation_matrix_json: Optional[str] = None
    sub_asset_class_assumptions_json: Optional[str] = None
    # Sprint 6 Phase 2 (2026-05-17): Nelson-Siegel Yield-Curve fuer Bonds.
    # Wenn alle 4 gesetzt: Engine nutzt yield_at(maturity) statt fixe Returns.
    bonds_ns_beta0_bps: Optional[int] = None
    bonds_ns_beta1_bps: Optional[int] = None
    bonds_ns_beta2_bps: Optional[int] = None
    bonds_ns_lambda_x100: Optional[int] = None
    # Sprint 7 (2026-05-17): KGV-Mean-Reversion fuer Equity-Returns.
    # Wenn alle 3 gesetzt: Engine addiert MR-Adjustment auf equity_*_return_bps.
    equity_kgv_current_x10: Optional[int] = None
    equity_kgv_fair_x10: Optional[int] = None
    equity_kgv_alpha_x100: Optional[int] = None
    # Sprint 8 (2026-05-17): Risikopraemien-Modell fuer RE + Alternatives.
    # Wenn gesetzt UND NS-Curve aktiv: re_return = NS.short_rate + premium.
    real_estate_risk_premium_bps: Optional[int] = None
    alternatives_risk_premium_bps: Optional[int] = None
    equities_skewness_bps: Optional[int] = None
    equities_excess_kurt_bps: Optional[int] = None
    bonds_skewness_bps: Optional[int] = None
    bonds_excess_kurt_bps: Optional[int] = None
    real_estate_skewness_bps: Optional[int] = None
    real_estate_excess_kurt_bps: Optional[int] = None
    alternatives_skewness_bps: Optional[int] = None
    alternatives_excess_kurt_bps: Optional[int] = None
    liquidity_skewness_bps: Optional[int] = None
    liquidity_excess_kurt_bps: Optional[int] = None
    source: Optional[str] = "Portfolio Management intern"
    source_date: Optional[str] = None
    notes: Optional[str] = None
    # Jurisdiction-aware CMA fields are writable/versioned model inputs, not
    # response-only metadata. Omitting them here made a partial DE update drop
    # all home-market moments in the next current snapshot.
    status: Optional[Literal[
        "provisional", "data_derived", "committee_approved"
    ]] = None
    source_detail: Optional[str] = None
    computed_at: Optional[str] = None
    computed_by: Optional[str] = None
    equity_home_return_bps: Optional[int] = None
    equity_home_vol_bps: Optional[int] = None
    bonds_home_ig_return_bps: Optional[int] = None
    bonds_home_ig_vol_bps: Optional[int] = None
    real_estate_home_return_bps: Optional[int] = None
    real_estate_home_vol_bps: Optional[int] = None

    @field_validator(
        "bonds_chf_ig_return_bps",
        "bonds_chf_ig_vol_bps",
        "bonds_fx_hedged_return_bps",
        "bonds_fx_hedged_vol_bps",
        "bonds_hy_return_bps",
        "bonds_hy_vol_bps",
        "equity_ch_return_bps",
        "equity_ch_vol_bps",
        "equity_intl_return_bps",
        "equity_intl_vol_bps",
        "equity_em_return_bps",
        "equity_em_vol_bps",
        "real_estate_ch_return_bps",
        "real_estate_ch_vol_bps",
        "alternatives_gold_return_bps",
        "alternatives_gold_vol_bps",
        "liquidity_return_bps",
        "liquidity_vol_bps",
        "equity_home_return_bps",
        "equity_home_vol_bps",
        "bonds_home_ig_return_bps",
        "bonds_home_ig_vol_bps",
        "real_estate_home_return_bps",
        "real_estate_home_vol_bps",
        "real_estate_risk_premium_bps",
        "alternatives_risk_premium_bps",
        "equities_skewness_bps",
        "equities_excess_kurt_bps",
        "bonds_skewness_bps",
        "bonds_excess_kurt_bps",
        "real_estate_skewness_bps",
        "real_estate_excess_kurt_bps",
        "alternatives_skewness_bps",
        "alternatives_excess_kurt_bps",
        "liquidity_skewness_bps",
        "liquidity_excess_kurt_bps",
        mode="before",
    )
    @classmethod
    def _reject_boolean_market_inputs(cls, value):
        if isinstance(value, bool):
            raise ValueError("CMA-Renditen müssen als Basispunkte erfasst werden.")
        return value

    @field_validator(
        "bonds_ns_beta0_bps",
        "bonds_ns_beta1_bps",
        "bonds_ns_beta2_bps",
        "bonds_ns_lambda_x100",
        "equity_kgv_current_x10",
        "equity_kgv_fair_x10",
        "equity_kgv_alpha_x100",
        mode="before",
    )
    @classmethod
    def _reject_boolean_advanced_model_parameters(cls, value):
        if isinstance(value, bool):
            raise ValueError(
                "Advanced-CMA-Modellparameter müssen numerisch skaliert "
                "erfasst werden."
            )
        return value

    @model_validator(mode="after")
    def _validate_cma(self):
        # SCHEMA-03: Volatilitäten dürfen NICHT negativ sein — eine negative Varianz
        # erzeugt in der Kovarianz-/Cholesky-Konstruktion der Monte-Carlo NaN/komplexe
        # Werte (stiller Fehler statt klarer 422). Returns/Prämien dürfen negativ sein.
        _vol_fields = (
            "bonds_chf_ig_vol_bps", "bonds_fx_hedged_vol_bps", "bonds_hy_vol_bps",
            "equity_ch_vol_bps", "equity_intl_vol_bps", "equity_em_vol_bps",
            "real_estate_ch_vol_bps", "alternatives_gold_vol_bps", "liquidity_vol_bps",
            "equity_home_vol_bps", "bonds_home_ig_vol_bps",
            "real_estate_home_vol_bps",
        )
        for f in _vol_fields:
            v = getattr(self, f, None)
            if v is not None and v < 0:
                raise ValueError(f"{f} darf nicht negativ sein (Volatilität >= 0).")
        for field_name in type(self).model_fields:
            if not field_name.endswith("_return_bps"):
                continue
            value = getattr(self, field_name, None)
            if value is not None and value <= -10_000:
                raise ValueError(
                    f"{field_name} muss grösser als -100 % sein."
                )
        if self.valid_until is not None and self.valid_from and self.valid_until < self.valid_from:
            raise ValueError("valid_until darf nicht vor valid_from liegen.")
        # Shared strict parser: missing optional payloads remain valid, while
        # any present malformed/non-finite/non-PSD model input fails before DB
        # persistence. Runtime engines call the exact same parser.
        parse_correlation_matrix_json(self.correlation_matrix_json)
        parse_sub_asset_class_assumptions_json(
            self.sub_asset_class_assumptions_json,
            require_complete=False,
        )
        validate_nelson_siegel_parameters(self)
        validate_equity_kgv_parameters(self)
        return self


class CapitalMarketAssumptionResponse(BaseResponse):
    id: str
    assumption_set_name: str
    version: int
    valid_from: str
    valid_until: Optional[str]
    is_current: int
    bonds_chf_ig_return_bps: Optional[int]
    bonds_chf_ig_vol_bps: Optional[int]
    bonds_fx_hedged_return_bps: Optional[int]
    bonds_fx_hedged_vol_bps: Optional[int]
    bonds_hy_return_bps: Optional[int]
    bonds_hy_vol_bps: Optional[int]
    equity_ch_return_bps: Optional[int]
    equity_ch_vol_bps: Optional[int]
    equity_intl_return_bps: Optional[int]
    equity_intl_vol_bps: Optional[int]
    equity_em_return_bps: Optional[int]
    equity_em_vol_bps: Optional[int]
    real_estate_ch_return_bps: Optional[int]
    real_estate_ch_vol_bps: Optional[int]
    alternatives_gold_return_bps: Optional[int]
    alternatives_gold_vol_bps: Optional[int]
    liquidity_return_bps: Optional[int]
    liquidity_vol_bps: Optional[int]
    inflation_path_json: Optional[str]
    correlation_matrix_json: Optional[str]
    sub_asset_class_assumptions_json: Optional[str]
    # Sprint 6 Phase 2: Nelson-Siegel Yield-Curve fuer Bonds
    bonds_ns_beta0_bps: Optional[int] = None
    bonds_ns_beta1_bps: Optional[int] = None
    bonds_ns_beta2_bps: Optional[int] = None
    bonds_ns_lambda_x100: Optional[int] = None
    # Sprint 7: KGV-Mean-Reversion fuer Equity-Returns
    equity_kgv_current_x10: Optional[int] = None
    equity_kgv_fair_x10: Optional[int] = None
    equity_kgv_alpha_x100: Optional[int] = None
    # Sprint 8: Risikopraemien fuer RE + Alternatives
    real_estate_risk_premium_bps: Optional[int] = None
    alternatives_risk_premium_bps: Optional[int] = None
    equities_skewness_bps: Optional[int] = None
    equities_excess_kurt_bps: Optional[int] = None
    bonds_skewness_bps: Optional[int] = None
    bonds_excess_kurt_bps: Optional[int] = None
    real_estate_skewness_bps: Optional[int] = None
    real_estate_excess_kurt_bps: Optional[int] = None
    alternatives_skewness_bps: Optional[int] = None
    alternatives_excess_kurt_bps: Optional[int] = None
    liquidity_skewness_bps: Optional[int] = None
    liquidity_excess_kurt_bps: Optional[int] = None
    source: Optional[str]
    source_date: Optional[str] = None
    notes: Optional[str]
    created_at: str
    # WP3 (Jurisdiktions-Verwaltung + CMA-Freigabe, 2026-07-31): additive
    # Felder aus WP1 (models/allocation.py::CapitalMarketAssumption), damit
    # /jurisdictions/{code}/cma/compute-candidate und
    # /capital-market-assumptions/{id}/approve die vollstaendige Zeile
    # zurueckgeben koennen. NULL fuer alle Bestands-CH-Zeilen (Backwards-
    # Compat, kein Verhaltens-Change fuer bestehende Response-Konsumenten).
    jurisdiction: Optional[str] = None
    status: Optional[str] = None
    source_detail: Optional[str] = None
    computed_at: Optional[str] = None
    computed_by: Optional[str] = None
    equity_home_return_bps: Optional[int] = None
    equity_home_vol_bps: Optional[int] = None
    bonds_home_ig_return_bps: Optional[int] = None
    bonds_home_ig_vol_bps: Optional[int] = None
    real_estate_home_return_bps: Optional[int] = None
    real_estate_home_vol_bps: Optional[int] = None
    tenant_id: Optional[str] = None


class SubAssetClassAssumptionResponse(BaseModel):
    asset_class: str
    sub_asset_class: str
    expected_return_bps: int
    expected_volatility_bps: int
    source: str


class AllocationBandOverridePayload(BaseModel):
    # extra="forbid": ein Tippfehler im Feldnamen (z.B. "target_bp" statt
    # "target_bps") ueberlebte bisher unbemerkt als wirkungslose Zusatz-Info.
    model_config = ConfigDict(extra="forbid")

    # bps im gueltigen Bereich 0..10000 (0..100%). Ohne diese Guards erreichten
    # negative/ueberzogene/verdrehte Band-Overrides den Optimizer und erzeugten eine
    # unloesbare oder korrupte Restriktion.
    min_bps: Optional[int] = Field(default=None, ge=0, le=10000)
    target_bps: Optional[int] = Field(default=None, ge=0, le=10000)
    max_bps: Optional[int] = Field(default=None, ge=0, le=10000)

    @field_validator("min_bps", "target_bps", "max_bps", mode="before")
    @classmethod
    def validate_strict_bps_type(cls, value):
        if value is not None and type(value) is not int:
            raise ValueError("Band-bps muessen ganze Zahlen sein")
        return value

    @model_validator(mode="after")
    def validate_band_order(self):
        lo, tg, hi = self.min_bps, self.target_bps, self.max_bps
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"min_bps ({lo}) darf max_bps ({hi}) nicht ueberschreiten")
        if tg is not None:
            if lo is not None and tg < lo:
                raise ValueError(f"target_bps ({tg}) darf nicht unter min_bps ({lo}) liegen")
            if hi is not None and tg > hi:
                raise ValueError(f"target_bps ({tg}) darf nicht ueber max_bps ({hi}) liegen")
        return self


class AllocationPreferencesPayload(BaseModel):
    # extra="forbid": ein unbekannter Top-Level-Key blieb bisher stillschweigend
    # wirkungslos liegen (z.B. Tippfehler oder veraltetes Frontend-Feld).
    model_config = ConfigDict(extra="forbid")

    policy: dict = Field(default_factory=dict)
    tilts: dict = Field(default_factory=dict)
    product: dict = Field(default_factory=dict)
    limits: dict = Field(default_factory=dict)
    geo: dict = Field(default_factory=dict)
    assetClasses: dict = Field(default_factory=dict)
    bands: dict[str, AllocationBandOverridePayload] = Field(default_factory=dict)
    simulation: dict = Field(default_factory=dict)

    @field_validator("policy")
    @classmethod
    def validate_policy(cls, value: dict) -> dict:
        for key, item in value.items():
            if key not in _VALID_POLICY_KEYS:
                raise ValueError(
                    f"Unbekannter Policy-Key '{key}' (erlaubt: {sorted(_VALID_POLICY_KEYS)})"
                )
            _validate_choice(
                section="policy",
                key=key,
                value=item,
                allowed=_VALID_POLICY_VALUES[key],
            )
        return value

    @field_validator("tilts")
    @classmethod
    def validate_tilts(cls, value: dict) -> dict:
        for key, mode in value.items():
            if key not in _VALID_TILT_KEYS:
                raise ValueError(
                    f"Unbekannter Tilt-Key '{key}' (erlaubt: {sorted(_VALID_TILT_KEYS)})"
                )
            _validate_choice(
                section="tilts",
                key=key,
                value=mode,
                allowed=_VALID_TILT_VALUES,
            )
        return value

    @field_validator("product")
    @classmethod
    def validate_product(cls, value: dict) -> dict:
        for key, item in value.items():
            if key not in _VALID_PRODUCT_KEYS:
                raise ValueError(
                    f"Unbekannter Product-Key '{key}' (erlaubt: {sorted(_VALID_PRODUCT_KEYS)})"
                )
            _validate_strict_bool(section="product", key=key, value=item)
        return value

    @field_validator("limits")
    @classmethod
    def validate_limits(cls, value: dict) -> dict:
        for key, item in value.items():
            if key not in _VALID_LIMITS_KEYS:
                raise ValueError(
                    f"Unbekannter Limits-Key '{key}' (erlaubt: {sorted(_VALID_LIMITS_KEYS)})"
                )
            if key in {"singlePosition", "singleIssuer", "maxIlliquid"}:
                _validate_number_range(
                    section="limits",
                    key=key,
                    value=item,
                    minimum=0,
                    maximum=100,
                    allow_empty=True,
                    percent=True,
                )
            else:
                _validate_number_range(
                    section="limits",
                    key=key,
                    value=item,
                    minimum=0,
                    allow_empty=True,
                    currency=True,
                )
        return value

    @field_validator("geo")
    @classmethod
    def validate_geo(cls, value: dict) -> dict:
        for key, item in value.items():
            if key not in _VALID_GEO_KEYS:
                raise ValueError(
                    f"Unbekannter Geo-Key '{key}' (erlaubt: {sorted(_VALID_GEO_KEYS)})"
                )
            _validate_strict_bool(section="geo", key=key, value=item)
        return value

    @field_validator("assetClasses")
    @classmethod
    def validate_asset_classes(cls, value: dict) -> dict:
        for key, item in value.items():
            if key not in _VALID_ASSET_CLASS_KEYS:
                raise ValueError(
                    f"Unbekannter AssetClasses-Key '{key}' (erlaubt: {sorted(_VALID_ASSET_CLASS_KEYS)})"
                )
            if key in _ASSET_CLASS_BOOLEAN_KEYS:
                _validate_strict_bool(section="assetClasses", key=key, value=item)
            elif key == "liquidityReserveTarget":
                _validate_number_range(
                    section="assetClasses",
                    key=key,
                    value=item,
                    minimum=0,
                    allow_empty=True,
                    currency=True,
                )
            else:
                _validate_choice(
                    section="assetClasses",
                    key=key,
                    value=item,
                    allowed=_VALID_ASSET_CLASS_CHOICES[key],
                )
        return value

    @field_validator("bands")
    @classmethod
    def validate_band_keys(cls, value: dict) -> dict:
        for key in value:
            if key not in _VALID_BAND_KEYS:
                raise ValueError(
                    f"Unbekannter Bandbreiten-Key '{key}' (erlaubt: {sorted(_VALID_BAND_KEYS)})"
                )
        return value

    @field_validator("simulation")
    @classmethod
    def validate_simulation(cls, value: dict) -> dict:
        for key, item in value.items():
            if key not in _VALID_SIMULATION_KEYS:
                raise ValueError(
                    f"Unbekannter Simulation-Key '{key}' (erlaubt: {sorted(_VALID_SIMULATION_KEYS)})"
                )
            if key == "horizonYears":
                _validate_integer_range(
                    section="simulation",
                    key=key,
                    value=item,
                    minimum=1,
                    maximum=120,
                )
            elif key == "stressMultiplier":
                _validate_number_range(
                    section="simulation",
                    key=key,
                    value=item,
                    minimum=0.25,
                    maximum=2.5,
                )
            elif key == "rebalanceMode":
                _validate_choice(
                    section="simulation",
                    key=key,
                    value=item,
                    allowed=_VALID_REBALANCE_MODES,
                )
            elif key == "monteCarloRuns":
                # The runtime intentionally clamps legacy low/high requests to
                # 250..2500 paths. Preserve that public compatibility while
                # rejecting zero, negative, fractional and absurd payloads.
                _validate_integer_range(
                    section="simulation",
                    key=key,
                    value=item,
                    minimum=1,
                    maximum=1_000_000,
                )
            elif key == "transactionCostBps":
                _validate_integer_range(
                    section="simulation",
                    key=key,
                    value=item,
                    minimum=0,
                    maximum=200,
                )
            elif key in {"crisisMode", "crisisStrength"}:
                if key == "crisisMode" and type(item) is bool:
                    continue
                _validate_number_range(
                    section="simulation",
                    key=key,
                    value=item,
                    minimum=0,
                    maximum=1,
                )
            else:
                if type(item) is bool:
                    continue
                if not isinstance(item, str) or item.strip().lower() not in _VALID_BOOLEAN_SPELLINGS:
                    raise ValueError(
                        f"simulation.{key} muss true/false oder eine bekannte Bool-Schreibweise sein"
                    )
        return value


class BuildingBlockResponse(BaseResponse):
    id: str
    policy_id: str
    asset_class: str
    sub_asset_class: str
    universe: str
    advisory: int
    risky_fraction_bps: int
    contribution_standard_bps: Optional[int]
    contribution_alternative_bps: Optional[int]
    is_active: int
    created_at: str
    updated_at: str
    # REF-BASIS-001 (Codex-Audit 2026-09-05): additives Feld, damit
    # GET /building-blocks/current sichtbar macht, ob eine Zeile eine
    # geteilte (jurisdiction=None) oder laenderspezifische Referenzzeile ist
    # -- identisches Nullable-Pattern wie CapitalMarketAssumptionResponse.jurisdiction.
    jurisdiction: Optional[str] = None


class TargetAllocationGenerateRequest(BaseModel):
    preferences: Optional[AllocationPreferencesPayload] = None


# Phase 6: Sensitivity-Analyse fuer ein einzelnes Goal.
# OD-FE-2: nur 5 diskrete Stufen, +/-20% in 5%-Schritten = {-20,-10,0,10,20}.
_ALLOWED_SENSITIVITY_DELTAS = (-20, -10, 0, 10, 20)


class AllocationSensitivityRequest(BaseModel):
    goal_id: str
    target_delta_pct: int
    # Sprint U-P5 Fix H9: Horizon-Delta optional (Backwards-Compat: 0)
    horizon_delta_years: int = 0

    @model_validator(mode="after")
    def validate_delta(self):
        if self.target_delta_pct not in _ALLOWED_SENSITIVITY_DELTAS:
            allowed = ", ".join(str(d) for d in _ALLOWED_SENSITIVITY_DELTAS)
            raise ValueError(
                f"target_delta_pct muss einer von [{allowed}] sein "
                f"(erhalten: {self.target_delta_pct})"
            )
        if self.horizon_delta_years < -10 or self.horizon_delta_years > 10:
            raise ValueError(
                f"horizon_delta_years muss in [-10, +10] sein "
                f"(erhalten: {self.horizon_delta_years})"
            )
        return self


class AllocationSensitivityResponse(BaseModel):
    goal_id: str
    delta_pct: int
    analysis_basis: str = (
        "live_reoptimization_common_scenarios_current_inputs_v3"
    )
    allocation_context_hash: Optional[str] = None
    live_model_input_hash: Optional[str] = None
    baseline_model_input_hash: Optional[str] = None
    modified_model_input_hash: Optional[str] = None
    scenario_pairing_basis: Optional[str] = None
    fx_basis: Optional[dict] = None
    capital_market_assumptions_id: Optional[str] = None
    solver_seed: Optional[int] = None
    wealth_basis: Optional[str] = None
    constraint_basis: Optional[str] = None
    external_foundation_basis: Optional[str] = None
    # Sprint U-P5 Fix H9: Horizon-Delta exponiert
    horizon_delta_years: int = 0
    horizon_years_baseline: Optional[int] = None
    horizon_years_new: Optional[int] = None
    solver_horizon_years_baseline: Optional[int] = None
    solver_horizon_years_new: Optional[int] = None
    target_amount_rappen_baseline: int
    target_amount_rappen_new: int
    target_return_bps_baseline: Optional[int] = None
    target_return_bps_new: Optional[int] = None
    objective_value_milli_baseline: Optional[int]
    objective_value_milli_new: Optional[int]
    delta_objective_pct: Optional[float]
    weights_bps_baseline: dict[str, int]
    weights_bps_new: dict[str, int]
    status_baseline: str
    status_new: str


class AllocationBucketResponse(BaseModel):
    asset_class: str
    current_weight_bps: int
    current_amount_rappen: int
    target_weight_bps: int
    target_amount_rappen: int
    delta_weight_bps: int
    band_min_bps: int
    band_max_bps: int


class AllocationSubBucketResponse(BaseModel):
    asset_class: str
    sub_asset_class: str
    target_weight_bps: int
    within_bucket_weight_bps: Optional[int] = None
    risky_fraction_bps: Optional[int] = None
    rationale: str


class AssetClassAssumptionResponse(BaseModel):
    asset_class: str
    current_weight_bps: int
    target_weight_bps: int
    risky_fraction_bps: int
    expected_return_bps: int
    expected_volatility_bps: int
    liquidity_profile: str
    market_data_role: str


class AllocationSimulationEventResponse(BaseModel):
    year: int
    mode: str
    breached_buckets: list[str]
    turnover_rappen: int
    notes: str


class AllocationSimulationResponse(BaseModel):
    horizon_years: int
    start_year: int
    year_labels: list[int]
    rebalance_mode: str
    stress_multiplier: float
    current_mix_series_rappen: list[int]
    target_mix_series_rappen: list[int]
    downside_series_rappen: list[int]
    upside_series_rappen: list[int]
    real_target_series_rappen: list[int]
    inflation_series_bps: list[int]
    rebalancing_events: list[AllocationSimulationEventResponse]


class GoalAnalysisResponse(BaseModel):
    goal_id: str
    label: str
    goal_type: str
    goal_scope: str
    value_mode: Optional[str] = None
    hardness: Optional[str] = None
    rank: int
    weight_bps: int
    target_amount_rappen: int
    target_wealth_rappen: Optional[int] = None
    target_return_bps: Optional[int] = None
    projected_value_rappen: int
    achievement_score: int
    status: str
    start_date: Optional[str] = None
    target_date: Optional[str] = None
    horizon_years: Optional[int] = None
    is_ongoing: Optional[int] = None
    frequency: Optional[str] = None
    timing_label: Optional[str] = None
    success_rate_pct: Optional[int] = None
    path_success_rate_pct: Optional[int] = None
    funded_ratio_p50: Optional[float] = None
    median_achievement_pct: Optional[int] = None
    pessimistic_shortfall_rappen: Optional[int] = None
    evaluation_note: Optional[str] = None
    projected_value_p10_rappen: Optional[int] = None
    projected_value_p50_rappen: Optional[int] = None
    projected_value_p90_rappen: Optional[int] = None


class MonteCarloGoalSummaryResponse(BaseModel):
    goal_id: str
    label: str
    years: int
    success_rate_pct: int
    funded_ratio_p50: float
    median_achievement_pct: int
    pessimistic_shortfall_rappen: int
    projected_value_p10_rappen: int
    projected_value_p50_rappen: int
    projected_value_p90_rappen: int
    score: int
    evaluation_note: Optional[str] = None


class MonteCarloResponse(BaseModel):
    model_basis: dict = Field(default_factory=dict)
    simulations: int
    seed: int
    horizon_years: int
    start_year: int
    year_labels: list[int]
    current_p10_series_rappen: list[int]
    current_p50_series_rappen: list[int]
    current_p90_series_rappen: list[int]
    target_p10_series_rappen: list[int]
    target_p50_series_rappen: list[int]
    target_p90_series_rappen: list[int]
    # F23: Total-Vermoegen-Pfade (Gesamtvermoegen inkl. Liabilities). Leer wenn
    # der Aufrufer kein total_summary uebergibt; ansonsten parallel zu den
    # advisory-Pfaden mit gleicher Zeitachse.
    total_current_p10_series_rappen: list[int] = Field(default_factory=list)
    total_current_p50_series_rappen: list[int] = Field(default_factory=list)
    total_current_p90_series_rappen: list[int] = Field(default_factory=list)
    total_target_p10_series_rappen: list[int] = Field(default_factory=list)
    total_target_p50_series_rappen: list[int] = Field(default_factory=list)
    total_target_p90_series_rappen: list[int] = Field(default_factory=list)
    current_annualized_return_p50_bps: int
    target_annualized_return_p50_bps: int
    target_var_95_1y_bps: int
    target_cvar_95_1y_bps: int
    target_loss_probability_1y_pct: int
    target_max_drawdown_p50_bps: int
    target_max_drawdown_p95_bps: int
    target_downside_probability_pct: int
    goal_summaries: list[MonteCarloGoalSummaryResponse]
    current_goal_summaries: list[MonteCarloGoalSummaryResponse] = Field(default_factory=list)


class LiveRebalancingPositionResponse(BaseModel):
    id: str
    product_id: str
    product_name: str
    asset_class: str
    sub_asset_class: Optional[str] = None
    target_weight_bps: int
    target_amount_rappen: int
    current_weight_bps: int
    current_market_value_rappen: int
    delta_weight_bps: int
    rebalance_amount_rappen: int
    reference_price_date: Optional[str] = None
    reference_price_rappen: Optional[int] = None
    reference_recalibrated: bool = False
    latest_price_date: Optional[str] = None
    latest_price_rappen: Optional[int] = None
    price_change_bps: Optional[int] = None
    holding_present: bool = False
    holding_source: Optional[str] = None
    holding_as_of_date: Optional[str] = None
    holding_units_milli: Optional[int] = None
    current_units_milli: Optional[int] = None
    holding_market_value_rappen: Optional[int] = None
    holding_avg_cost_price_rappen: Optional[int] = None
    holding_depot_bank: Optional[str] = None
    holding_custody_account_number: Optional[str] = None
    holding_notes: Optional[str] = None
    valuation_basis: Optional[str] = None
    implied_units_milli: Optional[int] = None
    price_age_days: Optional[int] = None
    price_is_fresh: Optional[bool] = None
    rebalance_action: str
    rebalance_action_code: str
    rebalance_action_label: str


class LiveRebalancingBucketResponse(BaseModel):
    asset_class: str
    current_weight_bps: int
    target_weight_bps: int
    band_min_bps: int
    band_max_bps: int
    current_market_value_rappen: int
    target_market_value_rappen: int
    delta_weight_bps: int
    rebalance_amount_rappen: int
    breached: bool
    breach_bps: int


class LiveRebalancingResponse(BaseModel):
    as_of_date: Optional[str] = None
    reference_anchor_date: Optional[str] = None
    methodology: str
    live_total_value_rappen: int
    priced_positions_count: int
    stale_positions_count: int
    missing_prices_count: int
    holding_positions_count: int = 0
    implied_positions_count: int = 0
    recalibrated_positions_count: int = 0
    turnover_required_rappen: int
    breached_asset_classes: list[str]
    action_summary: list[str]
    market_data_quality: dict = Field(default_factory=dict)
    bucket_drifts: list[LiveRebalancingBucketResponse]
    position_drifts: list[LiveRebalancingPositionResponse]


class OptimizerConstraintResponse(BaseModel):
    """V3 Sprint 1d (Plan §6): strukturierter Constraint-Slack pro Constraint.

    Nur in shadow_stochastic / stochastic Modus befuellt; sonst leere Liste.
    """
    code: str
    label: str
    value_bps: int
    limit_bps: int
    slack_bps: int
    is_binding: bool
    is_violated: bool


class OptimizerGoalDriverResponse(BaseModel):
    """V3 Sprint 1d (Plan §6): Goal-Driver fuer 'welches Ziel treibt den Solver'.

    weighted_objective_contribution_milli ist objective_contribution * 1000
    (gleiche Skalierung wie optimization_objective_value_milli auf der TA).
    rank ist der 1-basierte Rang in absteigender Sortierung (1 = groesster Treiber).
    Nur in shadow_stochastic / stochastic Modus befuellt; sonst leere Liste.
    """
    goal_id: str
    label: str
    target_kind: str
    hardness_key: str
    weight_bps: int
    weighted_objective_contribution_milli: Optional[int] = None
    rank: int


class AllocationMethodCandidateResponse(BaseModel):
    method: str
    role: str  # "active" | "shadow"
    status: Optional[str] = None
    weights_bps: dict[str, int]
    objective_value_milli: Optional[int] = None
    terminal_wealth_p10_rappen: Optional[int] = None
    terminal_wealth_p50_rappen: Optional[int] = None
    terminal_wealth_p90_rappen: Optional[int] = None
    feasible: Optional[bool] = None
    constraint_violations: list[str] = Field(default_factory=list)


class AllocationMethodComparisonResponse(BaseModel):
    """V3 Sprint 1 Shadow-Stochastic: Methodenvergleich House Matrix vs. Solver.

    Wird nur befuellt, wenn settings.optimizer_mode == 'shadow_stochastic'.
    objective_value_milli_* und objective_delta_pct sind nur dann gesetzt, wenn
    beide Methoden Apples-to-Apples unter demselben Context bewertet wurden
    (Sprint 1b/Commit 3 — siehe V3-Codeplan §5.6).
    """
    active_method: str
    shadow_method: Optional[str] = None
    shadow_status: Optional[str] = None
    active_weights_bps: dict[str, int]
    shadow_weights_bps: Optional[dict[str, int]] = None
    weight_deltas_bps: dict[str, int] = Field(default_factory=dict)
    objective_value_milli_active: Optional[int] = None
    objective_value_milli_shadow: Optional[int] = None
    objective_delta_pct: Optional[float] = None
    advisory_note: str
    candidates: list[AllocationMethodCandidateResponse] = Field(default_factory=list)


class TargetAllocationGenerateResponse(BaseModel):
    target_allocation: TargetAllocationResponse
    house_matrix_profile: str
    score_bucket: int
    advisory_wealth_rappen: int
    investable_advisory_wealth_rappen: Optional[int] = None
    # Phase 6 FE-Optimizer-Panel: Stress-Auswertungen aus dem Solver (Phase 5.2).
    # Schluessel: scenario_name -> dict mit end_wealth_rappen,
    # min_year_wealth_rappen, max_drawdown_bps. None wenn House-Matrix-Modus
    # oder Solver gefallback ist.
    stress_evaluations: Optional[dict] = None
    # V3 Sprint 1: Methodenvergleich House Matrix vs. Shadow Stochastic.
    # Nur befuellt im 'shadow_stochastic' Modus; sonst None.
    allocation_method_comparison: Optional[AllocationMethodComparisonResponse] = None
    # V3 Sprint 1d (Plan §5.3 / §6): Strukturierte Constraint-Slacks der aktiven
    # Allocation. Nur befuellt wenn Solver lief (shadow_stochastic / stochastic);
    # sonst leere Liste. 'is_binding' / 'is_violated' macht fuer den Berater
    # sichtbar, welche Leitplanke wirklich begrenzt.
    optimizer_constraints: list[OptimizerConstraintResponse] = Field(default_factory=list)
    # V3 Sprint 1d (Plan §5.4 / §6): Goal-Driver-Liste fuer 'welches Ziel treibt
    # den Shortfall'. Sortiert absteigend nach weighted_objective_contribution_milli.
    # Nur befuellt wenn Solver lief; sonst leere Liste.
    optimizer_goal_drivers: list[OptimizerGoalDriverResponse] = Field(default_factory=list)
    # C6: explizit benannte Basis fuer Target-/Sim-/MC-Berechnung
    # (= Beratungsvermoegen abzueglich externer Reserve).
    strategy_base_rappen: Optional[int] = None
    total_wealth_rappen: int
    recurring_income_rappen: int = 0
    recurring_expense_rappen: int = 0
    capital_inflow_rappen: int = 0
    capital_outflow_rappen: int = 0
    recurring_net_cashflow_rappen: int = 0
    capital_net_cashflow_rappen: int = 0
    annual_net_cashflow_rappen: int
    cashflow_projection_series_rappen: list[int]
    recurring_cashflow_projection_series_rappen: list[int] = Field(default_factory=list)
    reserve_needed_rappen: int
    external_reserve_rappen: int = 0
    risk_budget_bps: int
    risky_fraction_total_bps: int
    risky_fraction_headroom_bps: int
    limiting_factor: Optional[str] = None
    goal_achievability: list[dict] = Field(default_factory=list)
    goal_achievability_basis_id: Optional[str] = None
    goal_analysis_basis_id: str = "implementation_projection_v2"
    model_basis: dict = Field(default_factory=dict)
    messages: list[dict] = Field(default_factory=list)
    asset_class_risky_weights_bps: dict[str, int]
    expected_return_bps: int
    expected_volatility_bps: int
    capital_market_assumption_set: Optional[str] = None
    capital_market_source: Optional[str] = None
    reasoning: list[str]
    buckets: list[AllocationBucketResponse]
    sub_allocations: list[AllocationSubBucketResponse]
    asset_class_assumptions: list[AssetClassAssumptionResponse]
    sub_asset_class_assumptions_reference: list[SubAssetClassAssumptionResponse]
    simulation: AllocationSimulationResponse
    monte_carlo: MonteCarloResponse
    goal_analysis: list[GoalAnalysisResponse]
    current_goal_analysis: list[GoalAnalysisResponse] = Field(default_factory=list)
    live_rebalancing: Optional[LiveRebalancingResponse] = None
