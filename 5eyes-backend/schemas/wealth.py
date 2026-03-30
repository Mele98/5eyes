from pydantic import BaseModel, model_validator
from typing import Optional, Literal
from schemas.common import BaseResponse


# ── Wealth Position ────────────────────────────────────────────────────────────

class WealthPositionCreate(BaseModel):
    label: str
    position_type: Literal[
        "Depot", "Liquidität", "Immobilien", "Vorsorge",
        "Alternative", "Hypothek", "Custom"
    ]
    assignment: Literal["Beratungsvermögen", "Anderes Vermögen", "Verbindlichkeit"] = "Anderes Vermögen"
    current_value_rappen: int = 0
    currency: str = "CHF"
    valuation_date: Optional[str] = None
    # Depot
    depot_bank: Optional[str] = None
    depot_account_number: Optional[str] = None
    alloc_equities_bps: int = 0
    alloc_bonds_bps: int = 0
    alloc_real_estate_bps: int = 0
    alloc_liquidity_bps: int = 0
    alloc_alternatives_bps: int = 0
    # Immobilien
    property_address: Optional[str] = None
    property_zip_city: Optional[str] = None
    property_usage: Optional[str] = None
    property_rental_income_rappen: int = 0
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
    mortgage_amortization_rappen: int = 0
    mortgage_amortization_type: Optional[str] = None
    mortgage_linked_property_id: Optional[str] = None
    # Alternative
    asset_subtype: Optional[str] = None
    asset_expected_return_bps: Optional[int] = None
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

    @model_validator(mode="after")
    def validate_depot_alloc(self):
        if self.position_type == "Depot":
            total = (
                self.alloc_equities_bps + self.alloc_bonds_bps
                + self.alloc_real_estate_bps + self.alloc_liquidity_bps
                + self.alloc_alternatives_bps
            )
            if total != 10000:
                raise ValueError(f"Depot Allokation muss 10000 BP ergeben (aktuell: {total})")
        if self.position_type == "Hypothek":
            if self.assignment != "Verbindlichkeit":
                raise ValueError("Hypothek muss assignment='Verbindlichkeit' haben")
        return self


class WealthPositionUpdate(BaseModel):
    label: Optional[str] = None
    assignment: Optional[str] = None
    current_value_rappen: Optional[int] = None
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
    property_rental_income_rappen: Optional[int] = None
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
    mortgage_amortization_rappen: Optional[int] = None
    mortgage_amortization_type: Optional[str] = None
    mortgage_linked_property_id: Optional[str] = None
    asset_subtype: Optional[str] = None
    asset_expected_return_bps: Optional[int] = None
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
    pension_type: Optional[str]
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

class CashflowCreate(BaseModel):
    cashflow_type: Literal["Income", "Expense"]
    label: str
    amount_rappen: int
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


class CashflowUpdate(BaseModel):
    label: Optional[str] = None
    amount_rappen: Optional[int] = None
    gross_amount_rappen: Optional[int] = None
    tax_amount_rappen: Optional[int] = None
    timing_precision: Optional[str] = None
    frequency: Optional[str] = None
    nature: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    is_inflation_linked: Optional[bool] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


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


# ── Goal ───────────────────────────────────────────────────────────────────────

GOAL_FAMILY_TYPE_MAP = {
    "Vermögen": ["Kapitalerhalt", "Vermögensziel"],
    "Cashflow": ["Einmalige_Ausgabe", "Wiederkehrende_Ausgabe", "Pensionsausgabe"],
    "Rendite": ["Renditeziel"],
    "Maximierung": ["Maximierung"],
}


class GoalCreate(BaseModel):
    goal_family: Literal["Vermögen", "Cashflow", "Rendite", "Maximierung"]
    goal_type: Literal[
        "Kapitalerhalt", "Vermögensziel",
        "Einmalige_Ausgabe", "Wiederkehrende_Ausgabe", "Pensionsausgabe",
        "Renditeziel", "Maximierung"
    ]
    label: str
    rank: int
    weight_bps: Optional[int] = None
    goal_scope: Literal["Beratungsvermögen", "Gesamtvermögen"] = "Beratungsvermögen"
    value_mode: Literal["nominal", "real"] = "nominal"
    target_amount_rappen: Optional[int] = None
    target_wealth_rappen: Optional[int] = None
    target_return_bps: Optional[int] = None
    start_date: Optional[str] = None
    horizon_years: Optional[int] = None
    target_date: Optional[str] = None
    is_ongoing: bool = False
    frequency: Optional[str] = None
    hardness: Literal["Hart", "Primär", "Opportunistisch"] = "Primär"
    linked_position_id: Optional[str] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_family_type(self):
        allowed = GOAL_FAMILY_TYPE_MAP.get(self.goal_family, [])
        if self.goal_type not in allowed:
            raise ValueError(
                f"goal_type '{self.goal_type}' ist nicht erlaubt für goal_family '{self.goal_family}'. "
                f"Erlaubt: {allowed}"
            )
        # Strict field isolation
        if self.goal_type == "Renditeziel":
            if self.target_amount_rappen is not None or self.target_wealth_rappen is not None:
                raise ValueError("Renditeziel darf kein target_amount_rappen oder target_wealth_rappen haben")
            if self.target_return_bps is None:
                raise ValueError("Renditeziel benötigt target_return_bps")
        elif self.goal_type in ("Einmalige_Ausgabe", "Wiederkehrende_Ausgabe", "Pensionsausgabe"):
            if self.target_return_bps is not None or self.target_wealth_rappen is not None:
                raise ValueError("Cashflow-Ziel darf kein target_return_bps oder target_wealth_rappen haben")
            if self.target_amount_rappen is None:
                raise ValueError("Cashflow-Ziel benötigt target_amount_rappen")
        elif self.goal_type in ("Kapitalerhalt", "Vermögensziel"):
            if self.target_return_bps is not None or self.target_amount_rappen is not None:
                raise ValueError("Vermögensziel darf kein target_return_bps oder target_amount_rappen haben")
            if self.target_wealth_rappen is None:
                raise ValueError("Vermögensziel benötigt target_wealth_rappen")
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
    start_date: Optional[str] = None
    horizon_years: Optional[int] = None
    target_date: Optional[str] = None
    is_ongoing: Optional[bool] = None
    frequency: Optional[str] = None
    hardness: Optional[str] = None
    linked_position_id: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


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
    start_date: Optional[str]
    horizon_years: Optional[int]
    target_date: Optional[str]
    is_ongoing: int
    frequency: Optional[str]
    hardness: str
    linked_position_id: Optional[str]
    notes: Optional[str]
    is_active: int
    achievement_score: Optional[int]
    last_scored_at: Optional[str]
    created_at: str
    updated_at: str


# ── Planning Assumptions ───────────────────────────────────────────────────────

class PlanningAssumptionCreate(BaseModel):
    retirement_age_primary: Optional[int] = None
    retirement_age_partner: Optional[int] = None
    life_expectancy_primary: Optional[int] = None
    life_expectancy_partner: Optional[int] = None
    inflation_assumption_bps: Optional[int] = None
    pension_indexation_bps: Optional[int] = None
    notes: Optional[str] = None


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
