from pydantic import BaseModel
from typing import Optional, Literal
from schemas.common import BaseResponse


INVESTMENT_UNIVERSE_OPTIONS = ("Standard", "Alternativ")

# Sprint B1 (2026-05-07): Building-Block-Wahl-Optionen pro Anlageklasse.
EQUITIES_GEO_OPTIONS = ("Schweiz Fokus", "Global", "Europa", "Schwellenlaender")
BONDS_DURATION_OPTIONS = ("Langfristig", "Kurzfristig", "Gemischt")
REALESTATE_MARKET_OPTIONS = ("Schweiz", "Ausland", "Gemischt")


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
    # Sprint B4 (2026-05-07): Anlageuniversum-Wahl bei Mandat-Erstellung.
    investment_universe: Optional[Literal["Standard", "Alternativ"]] = "Standard"


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
    # Sprint B4 (2026-05-07): Anlageuniversum
    investment_universe: Optional[Literal["Standard", "Alternativ"]] = None
    # Sprint B1 (2026-05-07): Building-Block-Wahl als JSON-String.
    # Erwartete Keys: equitiesGeo, bondsDuration, realestateMarket, altsGold,
    #                 altsLiquidAlts, altsHedge, altsPe, altsCrypto.
    default_building_blocks_json: Optional[str] = None


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
    investment_universe: Optional[str] = "Standard"
    default_building_blocks_json: Optional[str] = None
    created_at: str
    updated_at: str
