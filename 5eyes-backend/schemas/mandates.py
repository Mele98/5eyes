from pydantic import BaseModel
from typing import Optional, Literal
from schemas.common import BaseResponse


class MandateCreate(BaseModel):
    mandate_number: str
    mandate_type: Literal[
        "Vermögensverwaltung", "Anlageberatung", "Finanzplanung", "Reporting only"
    ] = "Anlageberatung"
    base_currency: str = "CHF"
    advisory_language: Literal["DE", "FR", "IT", "EN"] = "DE"
    depot_bank: Optional[str] = None
    depot_account_number: Optional[str] = None
    opened_at: Optional[str] = None


class MandateUpdate(BaseModel):
    mandate_type: Optional[str] = None
    status: Optional[Literal["Aktiv", "Inaktiv", "Archiviert"]] = None
    base_currency: Optional[str] = None
    advisory_language: Optional[str] = None
    depot_bank: Optional[str] = None
    depot_account_number: Optional[str] = None
    closed_at: Optional[str] = None
    # Sprint A3 (2026-05-06): Rentenalter + Lebenserwartung
    retirement_year: Optional[int] = None
    life_expectancy_year: Optional[int] = None


class MandateResponse(BaseResponse):
    id: str
    client_id: str
    mandate_number: str
    mandate_type: str
    status: str
    base_currency: str
    advisory_language: str
    depot_bank: Optional[str]
    depot_account_number: Optional[str]
    opened_at: str
    closed_at: Optional[str]
    retirement_year: Optional[int] = None
    life_expectancy_year: Optional[int] = None
    created_at: str
    updated_at: str
