from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Literal
from schemas.common import BaseResponse
from services.wealth_position_semantics import (
    require_supported_mortgage_amortization,
    require_supported_position_assignment,
)


# ── Wealth Position ────────────────────────────────────────────────────────────

class WealthPositionCreate(BaseModel):
    label: str
    position_type: Literal[
        "Depot", "Liquidität", "Immobilien", "Vorsorge",
        "Alternative", "Hypothek", "Custom"
    ]
    assignment: Literal["Beratungsvermögen", "Anderes Vermögen", "Verbindlichkeit"] = "Anderes Vermögen"
    # 2026-07-25 (Generalaudit): kein Bounds-Check -- current_value_rappen
    # fliesst direkt in die SAA-/MC-Basis-Aggregation ein. Bounds grosszuegig
    # (bis CHF 100 Mia.), um legitime Grossvermoegen nicht zu blockieren, aber
    # einen Tippfehler (zusaetzliche Nullen) abzufangen. current_value_rappen
    # ist IMMER >=0, auch fuer Hypothek/Verbindlichkeit (Vorzeichen laeuft
    # ueber assignment, siehe services/portfolio_engine.py total_liabilities_rappen).
    current_value_rappen: int = Field(default=0, ge=0, le=10_000_000_000_000)
    currency: str = "CHF"
    valuation_date: Optional[str] = None
    # Depot
    depot_bank: Optional[str] = None
    depot_account_number: Optional[str] = None
    alloc_equities_bps: int = Field(default=0, ge=0)
    alloc_bonds_bps: int = Field(default=0, ge=0)
    alloc_real_estate_bps: int = Field(default=0, ge=0)
    alloc_liquidity_bps: int = Field(default=0, ge=0)
    alloc_alternatives_bps: int = Field(default=0, ge=0)
    # Immobilien
    property_address: Optional[str] = None
    property_zip_city: Optional[str] = None
    property_usage: Optional[str] = None
    # 2026-07-25 (Generalaudit): siehe current_value_rappen.
    property_rental_income_rappen: int = Field(default=0, ge=0, le=10_000_000_000_000)
    property_rental_inflation_linked: int = 0
    # Vorsorge
    pension_type: Optional[str] = None
    pension_institution: Optional[str] = None
    pension_technical_rate_bps: Optional[int] = None
    pension_retirement_age: Optional[int] = None
    pension_payout_form: Optional[str] = None
    pension_wef_possible: bool = False
    # Hypothek
    mortgage_bank: Optional[str] = None
    mortgage_type: Optional[str] = None
    mortgage_interest_rate_bps: Optional[int] = None
    mortgage_maturity_date: Optional[str] = None
    # 2026-07-25 (Generalaudit): siehe current_value_rappen.
    mortgage_amortization_rappen: int = Field(default=0, ge=0, le=10_000_000_000_000)
    mortgage_amortization_type: Optional[str] = None
    mortgage_linked_property_id: Optional[str] = None
    # Alternative
    asset_subtype: Optional[str] = None
    asset_expected_return_bps: Optional[int] = Field(
        default=None,
        gt=-10_000,
        le=100_000,
        strict=True,
    )
    asset_liquidity: Optional[str] = None
    asset_valuation_method: Optional[str] = None
    asset_location: Optional[str] = None
    # Liquidität
    liquidity_instrument: Optional[str] = None
    liquidity_interest_rate_bps: Optional[int] = None
    liquidity_available_from: Optional[str] = None
    # Goal Funding
    is_available_for_goal_funding: bool = False
    goal_funding_method: Optional[str] = None
    notes: Optional[str] = None
    # Phase-0-Datenklassifizierungs-Sperre (services/data_classification.py):
    # bislang FEHLTE dieses Feld auf WealthPositionCreate/-Update -> Pydantic
    # verwarf ein mitgesendetes "data_classification":"real" stillschweigend,
    # bevor der Endpoint es je sah, und enforce_data_classification() wurde nie
    # aufgerufen. Vermoegenspositionen (Depot/Hypothek/Immobilie) waren damit
    # die einzigen sensiblen Datensaetze, die das Phase-0-Gate umgehen konnten.
    data_classification: Literal["synthetic", "real"] = "synthetic"

    @model_validator(mode="after")
    def validate_depot_alloc(self):
        require_supported_position_assignment(
            self.position_type,
            self.assignment,
        )
        require_supported_mortgage_amortization(
            self.position_type,
            self.mortgage_amortization_rappen,
            self.mortgage_amortization_type,
        )
        if self.position_type == "Depot":
            total = (
                self.alloc_equities_bps + self.alloc_bonds_bps
                + self.alloc_real_estate_bps + self.alloc_liquidity_bps
                + self.alloc_alternatives_bps
            )
            if total != 10000:
                raise ValueError(f"Depot Allokation muss 10000 BP ergeben (aktuell: {total})")
        elif any(
            (
                self.alloc_equities_bps,
                self.alloc_bonds_bps,
                self.alloc_real_estate_bps,
                self.alloc_liquidity_bps,
                self.alloc_alternatives_bps,
            )
        ):
            raise ValueError(
                "alloc_*-Felder sind ausschliesslich für Depot-Positionen zulässig."
            )
        if self.position_type == "Hypothek":
            if self.assignment != "Verbindlichkeit":
                raise ValueError("Hypothek muss assignment='Verbindlichkeit' haben")
        return self


class WealthPositionUpdate(BaseModel):
    label: Optional[str] = None
    assignment: Optional[str] = None
    current_value_rappen: Optional[int] = Field(default=None, ge=0, le=10_000_000_000_000)
    valuation_date: Optional[str] = None
    depot_bank: Optional[str] = None
    depot_account_number: Optional[str] = None
    alloc_equities_bps: Optional[int] = None
    alloc_bonds_bps: Optional[int] = None
    alloc_real_estate_bps: Optional[int] = None
    alloc_liquidity_bps: Optional[int] = None
    alloc_alternatives_bps: Optional[int] = None
    property_address: Optional[str] = None
    property_zip_city: Optional[str] = None
    property_usage: Optional[str] = None
    property_rental_income_rappen: Optional[int] = Field(default=None, ge=0, le=10_000_000_000_000)
    property_rental_inflation_linked: Optional[int] = None
    pension_type: Optional[str] = None
    pension_institution: Optional[str] = None
    pension_technical_rate_bps: Optional[int] = None
    pension_retirement_age: Optional[int] = None
    pension_payout_form: Optional[str] = None
    pension_wef_possible: Optional[bool] = None
    mortgage_bank: Optional[str] = None
    mortgage_type: Optional[str] = None
    mortgage_interest_rate_bps: Optional[int] = None
    mortgage_maturity_date: Optional[str] = None
    mortgage_amortization_rappen: Optional[int] = Field(default=None, ge=0, le=10_000_000_000_000)
    mortgage_amortization_type: Optional[str] = None
    mortgage_linked_property_id: Optional[str] = None
    asset_subtype: Optional[str] = None
    asset_expected_return_bps: Optional[int] = Field(
        default=None,
        gt=-10_000,
        le=100_000,
        strict=True,
    )
    asset_liquidity: Optional[str] = None
    asset_valuation_method: Optional[str] = None
    asset_location: Optional[str] = None
    liquidity_instrument: Optional[str] = None
    liquidity_interest_rate_bps: Optional[int] = None
    liquidity_available_from: Optional[str] = None
    is_available_for_goal_funding: Optional[bool] = None
    goal_funding_method: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    data_classification: Optional[Literal["synthetic", "real"]] = None


class WealthPositionResponse(BaseResponse):
    id: str
    client_id: str
    label: str
    position_type: str
    assignment: str
    current_value_rappen: int
    currency: str
    valuation_date: Optional[str]
    depot_bank: Optional[str]
    depot_account_number: Optional[str]
    alloc_equities_bps: int
    alloc_bonds_bps: int
    alloc_real_estate_bps: int
    alloc_liquidity_bps: int
    alloc_alternatives_bps: int
    property_address: Optional[str]
    property_zip_city: Optional[str]
    property_usage: Optional[str]
    property_rental_income_rappen: int
    property_rental_inflation_linked: int = 0
    pension_type: Optional[str]

    @field_validator("property_rental_inflation_linked", mode="before")
    @classmethod
    def _inflation_linked_none_to_zero(cls, v):
        # WP-500-Fix (2026-07-01): Belt-and-Suspenders. Diese Spalte wurde in einer
        # frühen Migration ohne Backfill zugefügt -> Bestandszeilen NULL. Der Feld-
        # Default (=0) greift NUR bei FEHLENDEM Wert, nicht bei present-None; ein
        # einziges NULL liess `/wealth-positions` (response_model=list[...]) mit 500
        # fehlschlagen und riss die GESAMTE Positionsliste im Frontend weg. None
        # defensiv auf 0 (Modell-Default) mappen. Die eigentliche Reparatur macht
        # der idempotente DB-Backfill in database.ensure_runtime_columns.
        return 0 if v is None else v
    pension_institution: Optional[str]
    pension_retirement_age: Optional[int]
    pension_payout_form: Optional[str]
    pension_wef_possible: int
    mortgage_bank: Optional[str]
    mortgage_type: Optional[str]
    mortgage_interest_rate_bps: Optional[int]
    mortgage_maturity_date: Optional[str]
    mortgage_amortization_rappen: int
    mortgage_amortization_type: Optional[str]
    mortgage_linked_property_id: Optional[str]
    asset_subtype: Optional[str]
    asset_expected_return_bps: Optional[int]
    asset_liquidity: Optional[str]
    asset_valuation_method: Optional[str]
    liquidity_instrument: Optional[str]
    liquidity_interest_rate_bps: Optional[int]
    is_available_for_goal_funding: int
    goal_funding_method: Optional[str]
    notes: Optional[str]
    is_active: int
    created_at: str
    updated_at: str


# ── Cashflow ───────────────────────────────────────────────────────────────────

# 2026-07-25 (Generalaudit, Wave 12): frequency war ein freier String (fuer
# Alias-Toleranz, z.B. "monthly"/"jaehrlich"/"annual" -- absichtlich KEIN
# strikter Literal, siehe services.cashflow_timeline.normalize_frequency).
# Ein unerkannter Wert (Tippfehler wie "monatlic") fiel bisher aber NICHT
# dort auf, sondern erst tief in annual_amount_for_year() -> months_per_
# occurrence-Lookup, wo er STILL auf 12 Monate/jaehrlich zurueckfaellt --
# ein Kunde mit tatsaechlich monatlichem Cashflow bekaeme eine um Faktor 12
# zu niedrige Jahresprojektion, ohne jede Fehlermeldung. Fix: dieselbe
# Normalisierungsfunktion hier am API-Rand aufrufen und ablehnen, wenn sie
# NICHT auf einen der 4 bekannten kanonischen Werte abbildet -- zero Risiko
# einer abweichenden Logik (identische Funktion, kein Duplikat).
def _validate_frequency_field(frequency: str) -> None:
    from services.cashflow_timeline import normalize_frequency

    normalized = normalize_frequency(frequency)
    if normalized not in {"monatlich", "quartalsweise", "halbjährlich", "jährlich", "einmalig"}:
        raise ValueError(
            f"Unbekannte frequency {frequency!r} -- erlaubt sind u.a. "
            "'monatlich', 'quartalsweise', 'halbjährlich', 'jährlich', 'einmalig' "
            "(auch englische Varianten wie 'monthly'/'annually')."
        )


class CashflowCreate(BaseModel):
    cashflow_type: Literal["Income", "Expense"]
    label: str
    # amount_rappen ist der BETRAG (Magnitude); die Richtung ergibt sich aus
    # cashflow_type. Negativ wuerde das Vorzeichen in der Projektion still kippen.
    amount_rappen: int = Field(ge=0)
    gross_amount_rappen: Optional[int] = None
    tax_amount_rappen: Optional[int] = None
    timing_precision: Optional[str] = None
    currency: str = "CHF"
    frequency: str = "jährlich"
    nature: Literal["wiederkehrend", "einmalig"] = "wiederkehrend"
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    is_inflation_linked: bool = False
    notes: Optional[str] = None
    data_classification: Literal["synthetic", "real"] = "synthetic"

    @model_validator(mode="after")
    def validate_frequency_recognized(self):
        _validate_frequency_field(self.frequency)
        return self


class CashflowUpdate(BaseModel):
    cashflow_type: Optional[Literal["Income", "Expense"]] = None
    label: Optional[str] = None
    amount_rappen: Optional[int] = Field(default=None, ge=0)
    gross_amount_rappen: Optional[int] = None
    tax_amount_rappen: Optional[int] = None
    timing_precision: Optional[str] = None
    currency: Optional[str] = None
    frequency: Optional[str] = None
    nature: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    is_inflation_linked: Optional[bool] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    data_classification: Optional[Literal["synthetic", "real"]] = None

    @model_validator(mode="after")
    def validate_frequency_recognized(self):
        if self.frequency is not None:
            _validate_frequency_field(self.frequency)
        return self


class CashflowResponse(BaseResponse):
    id: str
    client_id: str
    cashflow_type: str
    label: str
    amount_rappen: int
    gross_amount_rappen: Optional[int]
    tax_amount_rappen: Optional[int]
    timing_precision: Optional[str]
    currency: str
    frequency: str
    nature: str
    valid_from: Optional[str]
    valid_until: Optional[str]
    is_inflation_linked: int
    notes: Optional[str]
    is_active: int
    created_at: str
    updated_at: str


# ── Max-Pension-Spending Rechner (Sprint A2, 2026-05-06) ───────────────────────


class MaxPensionSpendingRequest(BaseModel):
    retirement_year: int = Field(..., ge=1900, le=2200)
    life_expectancy_year: int = Field(..., ge=1900, le=2200)
    value_mode: Literal["nominal", "real"] = "real"
    safety_margin_pct: int = Field(0, ge=0, le=50)  # zusaetzlicher Discount in %

    @model_validator(mode="after")
    def _check_years(self):
        if self.life_expectancy_year <= self.retirement_year:
            raise ValueError("life_expectancy_year muss nach retirement_year liegen")
        return self


class MaxPensionSpendingResponse(BaseModel):
    max_monthly_chf_rappen: int
    max_annual_chf_rappen: int
    retirement_year: int
    life_expectancy_year: int
    years_in_retirement: int
    value_mode: str
    expected_return_bps: int
    expected_volatility_bps: int
    real_return_bps: int  # realer Modell-Medianwert aus CMA-Momenten
    inflation_bps: int
    advisory_wealth_rappen: int
    safety_margin_pct: int
    reasoning: list[str]


# ── WealthInflow (Sprint A1, 2026-05-06) ───────────────────────────────────────

WEALTH_INFLOW_SOURCE_TYPES = ("Erbschaft", "Bonus", "Saeule3b", "Verkaufserloes", "Andere")


class WealthInflowCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=200)
    source_type: Literal["Erbschaft", "Bonus", "Saeule3b", "Verkaufserloes", "Andere"]
    amount_rappen: int = Field(..., gt=0)
    expected_year: int = Field(..., ge=1900, le=2200)
    is_recurring: int = Field(0, ge=0, le=1)
    frequency: Optional[Literal["einmalig", "jaehrlich", "monatlich"]] = None
    duration_years: Optional[int] = Field(None, ge=1, le=99)
    value_mode: Literal["nominal", "real"] = "nominal"
    mandate_id: Optional[str] = None
    notes: Optional[str] = None
    # rls-3 (2026-07-23): Phase-0-Gate (enforce_data_classification) fehlte fuer
    # Wealth-Inflows komplett -- analog zu Cashflow/Goal/Wealth-Position nachgezogen.
    data_classification: Literal["synthetic", "real"] = "synthetic"

    @model_validator(mode="after")
    def _validate_recurring(self):
        if self.is_recurring:
            if not self.frequency or self.frequency == "einmalig":
                raise ValueError("is_recurring=1 erfordert frequency 'jaehrlich' oder 'monatlich'")
            if not self.duration_years:
                raise ValueError("is_recurring=1 erfordert duration_years")
        else:
            if self.frequency not in (None, "einmalig"):
                raise ValueError(
                    "is_recurring=0 erlaubt nur frequency 'einmalig' oder leer"
                )
            if self.duration_years is not None:
                raise ValueError("is_recurring=0 erlaubt keine duration_years")
        return self


class WealthInflowUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=200)
    source_type: Optional[Literal["Erbschaft", "Bonus", "Saeule3b", "Verkaufserloes", "Andere"]] = None
    amount_rappen: Optional[int] = Field(None, gt=0)
    expected_year: Optional[int] = Field(None, ge=1900, le=2200)
    is_recurring: Optional[int] = Field(None, ge=0, le=1)
    frequency: Optional[Literal["einmalig", "jaehrlich", "monatlich"]] = None
    duration_years: Optional[int] = Field(None, ge=1, le=99)
    value_mode: Optional[Literal["nominal", "real"]] = None
    notes: Optional[str] = None
    is_active: Optional[int] = Field(None, ge=0, le=1)
    # rls-3 (2026-07-23): siehe WealthInflowCreate.
    data_classification: Optional[Literal["synthetic", "real"]] = None


class WealthInflowResponse(BaseResponse):
    id: str
    client_id: str
    mandate_id: Optional[str]
    label: str
    source_type: str
    amount_rappen: int
    expected_year: int
    is_recurring: int
    frequency: Optional[str]
    duration_years: Optional[int]
    value_mode: str
    notes: Optional[str]
    is_active: int
    created_at: str
    updated_at: str


# ── Goal ───────────────────────────────────────────────────────────────────────

GOAL_FAMILY_TYPE_MAP = {
    "Vermögen": ["Kapitalerhalt", "Vermögensziel", "Vermoegensziel"],
    "Cashflow": ["Einmalige_Ausgabe", "Wiederkehrende_Ausgabe", "Pensionsausgabe"],
    "Rendite": ["Renditeziel"],
    "Maximierung": ["Maximierung"],
}


def _goal_type_key(value: str | None) -> str:
    raw = str(value or "").strip().lower().replace(" ", "_")
    return (
        raw.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("Ã¤", "ae")
        .replace("Ã¶", "oe")
        .replace("Ã¼", "ue")
    )


def _goal_hardness_key(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    return (
        raw.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("Ã¤", "ae")
        .replace("Ã¶", "oe")
        .replace("Ã¼", "ue")
    )


def _has_value(value) -> bool:
    return value not in (None, "")


def _raise_field_not_allowed(field: str, goal_type: str) -> None:
    raise ValueError(f"Feld '{field}' ist für Zieltyp '{goal_type}' nicht erlaubt")


def _apply_goal_success_probability_default(goal) -> None:
    if getattr(goal, "success_probability_min_x100", None) is not None:
        return
    key = _goal_type_key(getattr(goal, "goal_type", None))
    if key == "renditeziel":
        goal.success_probability_min_x100 = 5000
    elif key in {"kapitalerhalt", "vermoegensziel", "einmalige_ausgabe", "wiederkehrende_ausgabe", "pensionsausgabe"}:
        goal.success_probability_min_x100 = 8000


def _validate_goal_field_isolation(goal, *, require_targets: bool) -> None:
    goal_type = str(getattr(goal, "goal_type", "") or "")
    key = _goal_type_key(goal_type)
    hardness = _goal_hardness_key(getattr(goal, "hardness", None))
    if hardness and hardness not in {"hart", "primaer", "opportunistisch"}:
        raise ValueError("hardness muss 'Hart', 'Primär' oder 'Opportunistisch' sein")

    def forbid(*fields: str) -> None:
        for field in fields:
            if _has_value(getattr(goal, field, None)):
                _raise_field_not_allowed(field, goal_type)

    # Positivitaets-Guard fuer Ziel-BETRAEGE: ein gesetzter target_amount/target_wealth
    # muss > 0 sein (negativer/0-Zielwert verzerrt Zielerreichung/Monte-Carlo still).
    # target_return_bps hat bereits einen eigenen "positive Zielrendite"-Guard im
    # Renditeziel-Zweig; die Praesenz-Pflicht je Zieltyp bleibt unten.
    for _pf in ("target_amount_rappen", "target_wealth_rappen"):
        _pv = getattr(goal, _pf, None)
        if _has_value(_pv) and int(_pv) <= 0:
            raise ValueError(f"{_pf} muss groesser als 0 sein")

    if key == "renditeziel":
        forbid("target_amount_rappen", "target_wealth_rappen", "frequency")
        if hardness == "hart":
            raise ValueError(
                "Renditeziel darf nicht als 'hart' definiert werden. "
                "Echte Bedarfsziele (Entnahme/Mindestvermögen) sind hart."
            )
        if require_targets and not _has_value(getattr(goal, "target_return_bps", None)):
            raise ValueError("Renditeziel benötigt target_return_bps")
    elif key == "einmalige_ausgabe":
        forbid("target_return_bps", "target_wealth_rappen", "frequency")
        if require_targets and not _has_value(getattr(goal, "target_amount_rappen", None)):
            raise ValueError("Einmalige_Ausgabe benötigt target_amount_rappen")
        if require_targets and not (_has_value(getattr(goal, "target_date", None)) or _has_value(getattr(goal, "horizon_years", None))):
            raise ValueError("Einmalige_Ausgabe benötigt target_date oder horizon_years")
    elif key in {"wiederkehrende_ausgabe", "pensionsausgabe"}:
        forbid("target_return_bps", "target_wealth_rappen")
        if require_targets and not _has_value(getattr(goal, "frequency", None)):
            raise ValueError("Cashflow-Ziel benötigt frequency")
        if _has_value(getattr(goal, "frequency", None)):
            _validate_frequency_field(getattr(goal, "frequency", None))
            from services.cashflow_timeline import normalize_frequency

            if normalize_frequency(getattr(goal, "frequency", None)) == "einmalig":
                raise ValueError(
                    "Wiederkehrende und Pensions-Ziele erlauben keine "
                    "einmalige Frequenz"
                )
    elif key in {"kapitalerhalt", "vermoegensziel"}:
        forbid("target_return_bps", "target_amount_rappen", "frequency")
        if require_targets and not _has_value(getattr(goal, "target_wealth_rappen", None)):
            raise ValueError("Vermögensziel benötigt target_wealth_rappen")
        if require_targets and not (_has_value(getattr(goal, "target_date", None)) or _has_value(getattr(goal, "horizon_years", None))):
            raise ValueError("Vermögensziel benötigt target_date oder horizon_years")
    elif key == "maximierung":
        forbid("target_amount_rappen", "target_wealth_rappen", "target_return_bps", "target_date", "frequency")


class GoalCreate(BaseModel):
    goal_family: Literal["Vermögen", "Cashflow", "Rendite", "Maximierung"]
    goal_type: Literal[
        "Kapitalerhalt", "Vermögensziel", "Vermoegensziel",
        "Einmalige_Ausgabe", "Wiederkehrende_Ausgabe", "Pensionsausgabe",
        "Renditeziel", "Maximierung"
    ]
    label: str
    rank: int = Field(ge=1)
    weight_bps: Optional[int] = None
    goal_scope: Literal["Beratungsvermögen", "Gesamtvermögen"] = "Beratungsvermögen"
    value_mode: Literal["nominal", "real"] = "nominal"
    target_amount_rappen: Optional[int] = None
    target_wealth_rappen: Optional[int] = None
    target_return_bps: Optional[int] = None
    success_probability_min_x100: Optional[int] = Field(default=None, ge=0, le=10000)
    start_date: Optional[str] = None
    horizon_years: Optional[int] = None
    target_date: Optional[str] = None
    is_ongoing: bool = False
    frequency: Optional[str] = None
    hardness: str = "Primär"
    # Sprint B6: Eintrittswahrscheinlichkeit (0-100). Default 100 = sicher eintretend.
    probability_pct: int = Field(default=100, ge=0, le=100)
    # Sprint B3: Vorsorge-Saeule fuer Pensionsausgabe-Goals. Optional.
    pension_pillar: Optional[Literal["AHV", "BVG", "3a", "1e", "FZG"]] = None
    linked_position_id: Optional[str] = None
    notes: Optional[str] = None
    data_classification: Literal["synthetic", "real"] = "synthetic"

    @model_validator(mode="after")
    def validate_family_type(self):
        allowed = GOAL_FAMILY_TYPE_MAP.get(self.goal_family, [])
        if self.goal_type not in allowed:
            raise ValueError(
                f"goal_type '{self.goal_type}' ist nicht erlaubt für goal_family '{self.goal_family}'. "
                f"Erlaubt: {allowed}"
            )
        _apply_goal_success_probability_default(self)
        _validate_goal_field_isolation(self, require_targets=True)
        return self


class GoalUpdate(BaseModel):
    goal_family: Optional[str] = None
    goal_type: Optional[str] = None
    label: Optional[str] = None
    rank: Optional[int] = None
    weight_bps: Optional[int] = None
    goal_scope: Optional[str] = None
    value_mode: Optional[str] = None
    target_amount_rappen: Optional[int] = None
    target_wealth_rappen: Optional[int] = None
    target_return_bps: Optional[int] = None
    success_probability_min_x100: Optional[int] = Field(default=None, ge=0, le=10000)
    start_date: Optional[str] = None
    horizon_years: Optional[int] = None
    target_date: Optional[str] = None
    is_ongoing: Optional[bool] = None
    frequency: Optional[str] = None
    hardness: Optional[str] = None
    probability_pct: Optional[int] = Field(default=None, ge=0, le=100)
    pension_pillar: Optional[Literal["AHV", "BVG", "3a", "1e", "FZG"]] = None
    linked_position_id: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    data_classification: Optional[Literal["synthetic", "real"]] = None

    @model_validator(mode="after")
    def validate_goal_update_fields(self):
        if self.goal_type is not None:
            _validate_goal_field_isolation(self, require_targets=False)
        return self


class GoalResponse(BaseResponse):
    id: str
    mandate_id: str
    client_id: str
    goal_family: str
    goal_type: str
    label: str
    rank: int
    weight_bps: Optional[int]
    goal_scope: str
    value_mode: str
    target_amount_rappen: Optional[int]
    target_wealth_rappen: Optional[int]
    target_return_bps: Optional[int]
    success_probability_min_x100: Optional[int] = None
    start_date: Optional[str]
    horizon_years: Optional[int]
    target_date: Optional[str]
    is_ongoing: int
    frequency: Optional[str]
    hardness: str
    probability_pct: Optional[int] = None
    pension_pillar: Optional[str] = None
    linked_position_id: Optional[str]
    notes: Optional[str]
    is_active: int
    achievement_score: Optional[int]
    last_scored_at: Optional[str]
    created_at: str
    updated_at: str


# ── Planning Assumptions ───────────────────────────────────────────────────────

class PlanningAssumptionCreate(BaseModel):
    # 2026-07-25 (Generalaudit, Wave 13): kein Bounds-Check -- diese Felder
    # fliessen direkt in die MC-Simulation/Ziel-Projektion JEDES Berichts
    # fuer dieses Mandat ein. Ein Tippfehler (negatives/absurdes Alter oder
    # eine Inflation von z.B. -500%) wird unbemerkt persistiert. Bounds
    # grosszuegig, um legitime Stress-Test-Szenarien nicht zu blockieren.
    retirement_age_primary: Optional[int] = Field(default=None, ge=40, le=100)
    retirement_age_partner: Optional[int] = Field(default=None, ge=40, le=100)
    life_expectancy_primary: Optional[int] = Field(default=None, ge=40, le=120)
    life_expectancy_partner: Optional[int] = Field(default=None, ge=40, le=120)
    inflation_assumption_bps: Optional[int] = Field(default=None, ge=-1000, le=3000)
    pension_indexation_bps: Optional[int] = Field(default=None, ge=-1000, le=3000)
    notes: Optional[str] = None
    # sec-f4 (2026-08-02): Phase-0-Gate (enforce_data_classification) fehlte fuer
    # Planning-Assumptions komplett -- analog zu Wealth-Inflow/Cashflow/Goal
    # nachgezogen. PlanningAssumption-Model hat keine data_classification-Spalte,
    # Feld dient nur der Enforcement und wird vor dem Persistieren gepoppt.
    data_classification: Literal["synthetic", "real"] = "synthetic"


class PlanningAssumptionResponse(BaseResponse):
    id: str
    mandate_id: str
    version: int
    is_current: int
    valid_from: str
    retirement_age_primary: Optional[int]
    retirement_age_partner: Optional[int]
    life_expectancy_primary: Optional[int]
    life_expectancy_partner: Optional[int]
    inflation_assumption_bps: Optional[int]
    pension_indexation_bps: Optional[int]
    notes: Optional[str]
    created_at: str
    updated_at: str
