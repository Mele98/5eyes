from pydantic import BaseModel
from typing import Optional, Literal
from schemas.common import BaseResponse


class ClientCreate(BaseModel):
    client_number: str
    salutation: Optional[Literal["Herr", "Frau", "Divers"]] = None
    first_name: str
    last_name: str
    date_of_birth: Optional[str] = None
    investment_horizon_start: Optional[str] = None
    investment_horizon_end: Optional[str] = None
    country_of_residence: str = "CH"
    canton: Optional[str] = None
    civil_status: Optional[str] = None
    profession: Optional[str] = None
    employer: Optional[str] = None
    language: Literal["DE", "FR", "IT", "EN"] = "DE"
    partner_salutation: Optional[str] = None
    partner_first_name: Optional[str] = None
    partner_last_name: Optional[str] = None
    partner_date_of_birth: Optional[str] = None
    partner_profession: Optional[str] = None
    household_type: Literal["Einzelperson", "Paar", "Familie"] = "Einzelperson"
    client_classification: Literal[
        "Privatkunde", "Professioneller Kunde", "Institutioneller Kunde"
    ] = "Privatkunde"
    is_professional_opt_out: bool = False
    is_qualified_investor: bool = False
    advisor_id: str
    notes: Optional[str] = None


class ClientUpdate(BaseModel):
    salutation: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    investment_horizon_start: Optional[str] = None
    investment_horizon_end: Optional[str] = None
    country_of_residence: Optional[str] = None
    canton: Optional[str] = None
    civil_status: Optional[str] = None
    profession: Optional[str] = None
    employer: Optional[str] = None
    language: Optional[str] = None
    partner_salutation: Optional[str] = None
    partner_first_name: Optional[str] = None
    partner_last_name: Optional[str] = None
    partner_date_of_birth: Optional[str] = None
    partner_profession: Optional[str] = None
    household_type: Optional[str] = None
    client_classification: Optional[str] = None
    is_professional_opt_out: Optional[bool] = None
    is_qualified_investor: Optional[bool] = None
    advisor_id: Optional[str] = None
    notes: Optional[str] = None


class ClientResponse(BaseResponse):
    id: str
    client_number: str
    salutation: Optional[str]
    first_name: str
    last_name: str
    date_of_birth: Optional[str]
    investment_horizon_start: Optional[str]
    investment_horizon_end: Optional[str]
    country_of_residence: str
    canton: Optional[str]
    civil_status: Optional[str]
    profession: Optional[str]
    employer: Optional[str]
    language: str
    partner_salutation: Optional[str]
    partner_first_name: Optional[str]
    partner_last_name: Optional[str]
    partner_date_of_birth: Optional[str]
    partner_profession: Optional[str]
    household_type: str
    client_classification: str
    is_professional_opt_out: int
    is_qualified_investor: int
    advisor_id: str
    notes: Optional[str]
    created_at: str
    updated_at: str


class NationalityCreate(BaseModel):
    country_code: str
    is_primary: bool = False


class NationalityResponse(BaseResponse):
    id: str
    client_id: str
    country_code: str
    is_primary: int
    created_at: str


class OptHistoryCreate(BaseModel):
    event_type: str
    from_classification: str
    to_classification: str
    client_requested: bool = True
    notes: Optional[str] = None
    document_id: Optional[str] = None


class OptHistoryResponse(BaseResponse):
    id: str
    client_id: str
    event_type: str
    from_classification: str
    to_classification: str
    client_requested: int
    documented_by: str
    documented_at: str
    notes: Optional[str]
    created_at: str


class WealthSummaryResponse(BaseModel):
    client_id: str
    client_name: str
    client_classification: Optional[str]
    gross_wealth_rappen: int
    liabilities_rappen: int
    net_worth_rappen: int
    advisory_wealth_rappen: int
    # Derived display values (CHF)
    gross_wealth_chf: float
    liabilities_chf: float
    net_worth_chf: float
    advisory_wealth_chf: float


class CashflowSummaryResponse(BaseModel):
    client_id: str
    client_name: str
    summary_year: int
    total_income_rappen: int
    total_expense_rappen: int
    surplus_rappen: int
    total_income_chf: float
    total_expense_chf: float
    surplus_chf: float


class CashflowYearRow(BaseModel):
    year: int
    income_rappen: int
    expense_rappen: int
    net_rappen: int


class CashflowProjectionResponse(BaseModel):
    client_id: str
    start_year: int
    years: list[CashflowYearRow]
