from pydantic import BaseModel, Field, model_validator
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
    # Sprint 4 Phase 3 (2026-05-17): Mortalitaets-Sampling.
    # SCHEMA-06: Geburtsjahr plausibilisiert (1900–2200).
    client_birth_year: Optional[int] = Field(default=None, ge=1900, le=2200)
    client_sex: Optional[Literal["M", "F"]] = None
    use_mortality_simulation: Optional[bool] = False
    # 2026-07-25 (Generalaudit): Phase-0-Gate fehlte fuer Mandate -- analog
    # zu Client/Cashflow/Goal/WealthPosition/WealthInflow nachgezogen.
    data_classification: Literal["synthetic", "real"] = "synthetic"
    # 2026-08-01 (Onboarding): explizites Land fuer dieses Mandat -- fuer
    # Firmen mit Kunden in mehreren Laendern. None = Default aus
    # Tenant.home_jurisdiction (routers/mandates.py::create_mandate), sonst
    # "CH" (Backwards-Compat, siehe models/mandates.py::Mandate.jurisdiction).
    jurisdiction: Optional[str] = None


class MandateUpdate(BaseModel):
    # SCHEMA-05: mandate_type/advisory_language nutzen dieselben Literal-Enums
    # wie Create — vorher freie str, die die Wertelisten bei PATCH umgingen.
    mandate_type: Optional[Literal[
        "Vermögensverwaltung", "Anlageberatung", "Finanzplanung", "Reporting only"
    ]] = None
    status: Optional[Literal["Aktiv", "Inaktiv", "Archiviert"]] = None
    base_currency: Optional[str] = None
    advisory_language: Optional[Literal["DE", "FR", "IT", "EN"]] = None
    depot_bank: Optional[str] = None
    depot_account_number: Optional[str] = None
    closed_at: Optional[str] = None
    # Sprint A3 (2026-05-06): Rentenalter + Lebenserwartung
    # SCHEMA-06: Jahre plausibilisiert (1900–2200) + Reihenfolge-Check unten.
    retirement_year: Optional[int] = Field(default=None, ge=1900, le=2200)
    life_expectancy_year: Optional[int] = Field(default=None, ge=1900, le=2200)
    # Sprint B4 (2026-05-07): Anlageuniversum
    investment_universe: Optional[Literal["Standard", "Alternativ"]] = None
    # Sprint B1 (2026-05-07): Building-Block-Wahl als JSON-String.
    # Erwartete Keys: equitiesGeo, bondsDuration, realestateMarket, altsGold,
    #                 altsLiquidAlts, altsHedge, altsPe, altsCrypto.
    default_building_blocks_json: Optional[str] = None
    # Sprint 4 Phase 3 (2026-05-17): Mortalitaets-Sampling.
    # SCHEMA-06: Geburtsjahr plausibilisiert (1900–2200).
    client_birth_year: Optional[int] = Field(default=None, ge=1900, le=2200)
    client_sex: Optional[Literal["M", "F"]] = None
    use_mortality_simulation: Optional[bool] = None
    # Sprint U-P3 (2026-05-19): Steuersitz fuer tax-aware Allocation-MC.
    # Erwartete Werte z.B. 'CH', 'DE', 'CH-ZH', 'DE-BY' (Pattern matched
    # gegen services.tax.registry). NULL = tax-naiv. tax_overrides_json
    # erlaubt selektive Overrides der TaxConfig-Defaults.
    tax_jurisdiction: Optional[str] = None
    tax_overrides_json: Optional[str] = None
    # Roadmap #39 (Standpunkt 2026-08-07): geschaetzte Vermoegenssteuer als
    # optionale Ausgabe in der Cashflow-Projektion einrechnen. None = keine
    # Aenderung; explizites False/True setzt das Flag. Nutzt tax_jurisdiction
    # oben fuer die Regime-Auflösung (kein zusaetzliches Feld noetig).
    tax_estimate_in_cashflow_enabled: Optional[bool] = None
    # 2026-07-27 (HUD-Konfiguration): JSON-Array von Sektions-Keys aus dem
    # Advisory-Report-Aggregator, die fuer dieses Mandat ausgeblendet werden
    # sollen. NULL = alles sichtbar (Backwards-Compat). Gleiches Muster wie
    # default_building_blocks_json -- roher JSON-String, keine native Liste.
    hidden_report_sections: Optional[str] = None
    # 2026-07-27 (Laender-Skalierung): siehe models/mandates.py. NULL = "CH".
    jurisdiction: Optional[str] = None
    # 2026-07-25 (Generalaudit): siehe MandateCreate.
    data_classification: Optional[Literal["synthetic", "real"]] = None

    @model_validator(mode="after")
    def validate_year_order(self):
        # SCHEMA-06: chronologische Plausibilität nur prüfen, wenn beide Jahre
        # im selben PATCH gesetzt sind (Felder sind einzeln optional).
        if self.client_birth_year is not None and self.retirement_year is not None:
            if self.retirement_year <= self.client_birth_year:
                raise ValueError(
                    f"retirement_year ({self.retirement_year}) muss nach "
                    f"client_birth_year ({self.client_birth_year}) liegen."
                )
        if self.retirement_year is not None and self.life_expectancy_year is not None:
            if self.life_expectancy_year < self.retirement_year:
                raise ValueError(
                    f"life_expectancy_year ({self.life_expectancy_year}) darf nicht "
                    f"vor retirement_year ({self.retirement_year}) liegen."
                )
        if self.client_birth_year is not None and self.life_expectancy_year is not None:
            if self.life_expectancy_year <= self.client_birth_year:
                raise ValueError(
                    f"life_expectancy_year ({self.life_expectancy_year}) muss nach "
                    f"client_birth_year ({self.client_birth_year}) liegen."
                )
        return self


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
    # Sprint 4 Phase 3 (2026-05-17): Mortalitaets-Sampling
    client_birth_year: Optional[int] = None
    client_sex: Optional[str] = None
    use_mortality_simulation: Optional[bool] = False
    # Sprint U-P3 (2026-05-19): Steuersitz fuer tax-aware Allocation
    tax_jurisdiction: Optional[str] = None
    tax_overrides_json: Optional[str] = None
    # Roadmap #39 (Standpunkt 2026-08-07): siehe MandateUpdate.
    tax_estimate_in_cashflow_enabled: Optional[bool] = False
    # 2026-07-27 (HUD-Konfiguration): siehe MandateUpdate.
    hidden_report_sections: Optional[str] = None
    # 2026-07-27 (Laender-Skalierung): siehe MandateUpdate.
    jurisdiction: Optional[str] = None
    created_at: str
    updated_at: str
