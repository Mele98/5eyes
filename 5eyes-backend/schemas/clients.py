from datetime import date as _date
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, Literal
from schemas.common import BaseResponse

# FIDLEG-STATE-001 (2026-08-27-Audit, docs/audits/2026-08-27-client-
# classification-and-compliance-state-audit.md): einzige gueltige Werteliste
# fuer die FIDLEG-Kundenklassifikation. Wird sowohl bei der Ersterfassung
# (ClientCreate) als auch beim beleggebundenen Opt-History-Uebergang
# (OptHistoryCreate) verwendet, damit keine der beiden Stellen eine
# abweichende oder freie Klassifikation zulassen kann.
ClientClassification = Literal[
    "Privatkunde", "Professioneller Kunde", "Institutioneller Kunde"
]

# VALID-01 (Audit-Finding, 2026-10-07): einzige gueltige Werteliste der 26
# Schweizer Kantonscodes. Geteilt zwischen ClientCreate und ClientUpdate
# (analog zu ClientClassification oben), damit beide Einstiegspunkte
# denselben Kanton-Freitext-Bug nicht reproduzieren koennen.
SWISS_CANTON_CODES = frozenset({
    "ZH", "BE", "LU", "UR", "SZ", "OW", "NW", "GL", "ZG", "FR",
    "SO", "BS", "BL", "SH", "AR", "AI", "SG", "GR", "AG", "TG",
    "TI", "VD", "VS", "NE", "GE", "JU",
})


def _validate_date_of_birth(value: Optional[str]) -> Optional[str]:
    """VALID-01: Datenqualitaets-Guard, keine strenge Geschaeftsregel --
    lehnt nur klar unplausible Werte ab (kaputtes Datum, Zukunft, Alter
    ausserhalb [0, 120] Jahre). Leer/None bleibt zulaessig (Feld ist optional)."""
    if value is None:
        return value
    raw = value.strip()
    if not raw:
        return value
    try:
        parsed = _date.fromisoformat(raw[:10])
    except ValueError:
        raise ValueError(
            f"date_of_birth ist kein gueltiges ISO-Datum (YYYY-MM-DD): {value!r}"
        )
    today = _date.today()
    if parsed > today:
        raise ValueError("date_of_birth darf nicht in der Zukunft liegen")
    age_years = today.year - parsed.year - (
        (today.month, today.day) < (parsed.month, parsed.day)
    )
    if age_years > 120:
        raise ValueError(
            f"date_of_birth impliziert ein unplausibles Alter von {age_years} Jahren (> 120)"
        )
    if age_years < 0:
        raise ValueError("date_of_birth impliziert ein negatives Alter")
    return value


def _validate_canton(value: Optional[str]) -> Optional[str]:
    """VALID-01: normalisiert auf Grossbuchstaben und lehnt jeden Wert ab,
    der keiner der 26 Schweizer Kantonscodes ist."""
    if value is None:
        return value
    raw = value.strip()
    if not raw:
        return value
    normalized = raw.upper()
    if normalized not in SWISS_CANTON_CODES:
        raise ValueError(
            "canton muss einer der 26 Schweizer Kantonscodes sein "
            f"(z.B. 'ZH'), erhalten: {value!r}"
        )
    return normalized


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
    client_classification: ClientClassification = "Privatkunde"
    is_professional_opt_out: bool = False
    is_qualified_investor: bool = False
    advisor_id: str
    notes: Optional[str] = None
    data_classification: Literal["synthetic", "real"] = "synthetic"

    # VALID-01 (Audit-Finding, 2026-10-07): Datenqualitaets-Guards, siehe
    # _validate_date_of_birth/_validate_canton oben.
    _check_date_of_birth = field_validator("date_of_birth")(_validate_date_of_birth)
    _check_canton = field_validator("canton")(_validate_canton)


class ClientUpdate(BaseModel):
    # SCHEMA-05: Update nutzt dieselben Literal-Enums wie Create — vorher waren
    # salutation/language/household_type/client_classification freie str und
    # umgingen die FIDLEG-Wertelisten bei PATCH.
    #
    # FIDLEG-STATE-001 (2026-08-27-Audit): client_classification,
    # is_professional_opt_out und is_qualified_investor sind hier bewusst
    # NICHT mehr vorhanden. Vorher konnte der allgemeine Client-PUT diese
    # rechtlich bedeutsamen Felder ohne Beleg, Konsistenzpruefung und ohne
    # jede Audit-Spur (history_rows=0) direkt umschreiben. Eine Aenderung
    # dieser Felder muss ab sofort ausschliesslich ueber den beleggebundenen,
    # append-only Uebergang POST /clients/{id}/opt-history laufen (siehe
    # add_opt_history in routers/clients.py). Ein Client, der diese Felder
    # trotzdem im PUT-Body mitschickt, bekommt keinen Fehler (Pydantic
    # ignoriert unbekannte Felder), aber der Wert wird schlicht nicht
    # angewendet -- das entspricht der im Audit-Fixvertrag vorgesehenen
    # Option "in ClientUpdate ausdruecklich unveraenderbar machen".
    salutation: Optional[Literal["Herr", "Frau", "Divers"]] = None
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
    language: Optional[Literal["DE", "FR", "IT", "EN"]] = None
    partner_salutation: Optional[str] = None
    partner_first_name: Optional[str] = None
    partner_last_name: Optional[str] = None
    partner_date_of_birth: Optional[str] = None
    partner_profession: Optional[str] = None
    household_type: Optional[Literal["Einzelperson", "Paar", "Familie"]] = None
    advisor_id: Optional[str] = None
    notes: Optional[str] = None
    data_classification: Optional[Literal["synthetic", "real"]] = None

    # VALID-01 (Audit-Finding, 2026-10-07): dieselben Datenqualitaets-Guards
    # wie ClientCreate -- siehe _validate_date_of_birth/_validate_canton oben.
    _check_date_of_birth = field_validator("date_of_birth")(_validate_date_of_birth)
    _check_canton = field_validator("canton")(_validate_canton)


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


class ClientErasureRequest(BaseModel):
    """DSG Art. 32 -- Pflichtbegruendung fuer eine Loeschungs-/Erasure-
    Anfrage. Wiederverwendet dieselbe Qualitaets-Pruefung wie
    Risikoprofil-Overrides (min. 20 Zeichen, keine Floskel, >=3
    bedeutungsvolle Worte) -- eine so folgenreiche, irreversible Aktion
    verdient dieselbe FIDLEG-Audit-Tauglichkeit wie ein Profil-Override.
    """
    reason: str

    @model_validator(mode="after")
    def _validate_reason_quality(self):
        from services.override_reason_quality import validate_override_reason_quality
        validate_override_reason_quality(self.reason)
        return self


class ClientErasureResponse(BaseModel):
    status: str
    client_id: str
    mandate_ids: list[str]
    redacted: dict[str, int]
    erased_at: str


class NationalityCreate(BaseModel):
    country_code: str
    is_primary: bool = False
    # DATA-CLASSIFICATION-GATE-COVERAGE-002 (Kontrollrunde 2026-09-24):
    # Phase-0-Gate fehlte fuer Client-Nationalitaeten -- echte Personendaten,
    # identisches Muster wie create_client/create_knowledge.
    data_classification: Literal["synthetic", "real"] = "synthetic"


class NationalityResponse(BaseResponse):
    id: str
    client_id: str
    country_code: str
    is_primary: int
    created_at: str


class OptHistoryCreate(BaseModel):
    # FIDLEG-STATE-001 (2026-08-27-Audit): from_classification/
    # to_classification waren zuvor freie Strings -- der Router setzte
    # to_classification ungeprueft auf den Client (reproduziert:
    # `BROKEN-CLASS` ausserhalb jedes Enums), und from_classification wurde
    # nie gegen den tatsaechlichen Clientzustand geprueft. Beide sind jetzt
    # auf dieselbe FIDLEG-Werteliste wie Client.client_classification
    # typisiert (422 bei ungueltigem Wert); die zusaetzliche Pruefung, dass
    # from_classification mit dem aktuell gespeicherten Zustand des Clients
    # uebereinstimmt (stale/falscher Ausgangszustand -> 409), erfolgt im
    # Router (routers/clients.py::add_opt_history), da sie den DB-Zustand
    # kennen muss.
    event_type: str
    from_classification: ClientClassification
    to_classification: ClientClassification
    client_requested: bool = True
    notes: Optional[str] = None
    document_id: Optional[str] = None
    # DUAL-STACK-01-Nachtrag (2026-10-07): is_professional_opt_out/
    # is_qualified_investor hatten nach dem FIDLEG-STATE-001-Fix KEINEN
    # gueltigen Aenderungspfad mehr (ClientUpdate schliesst sie bewusst aus,
    # der Opt-History-Router transitionierte bis dahin ausschliesslich
    # client_classification). Optional = None bedeutet "diese Transition
    # aendert dieses Flag nicht" -- eine reine Reklassifikation ohne
    # Flag-Wechsel bleibt moeglich, ebenso eine reine Flag-Aenderung ohne
    # Klassifikationswechsel (from_classification == to_classification).
    # Die serverseitige Pruefung, dass der jeweilige from_*-Wert mit dem
    # tatsaechlichen Clientzustand uebereinstimmt (409 bei Stale-Zustand),
    # erfolgt -- analog zu from_classification -- im Router.
    from_professional_opt_out: Optional[bool] = None
    to_professional_opt_out: Optional[bool] = None
    from_qualified_investor: Optional[bool] = None
    to_qualified_investor: Optional[bool] = None
    # DATA-CLASSIFICATION-GATE-COVERAGE-002 (Kontrollrunde 2026-09-24):
    # Phase-0-Gate fehlte fuer Opt-History -- enthaelt Freitext (notes) und
    # dokumentiert eine echte Klassifikations-Aenderung des Kunden.
    data_classification: Literal["synthetic", "real"] = "synthetic"


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
    from_professional_opt_out: Optional[int] = None
    to_professional_opt_out: Optional[int] = None
    from_qualified_investor: Optional[int] = None
    to_qualified_investor: Optional[int] = None


class ClientDueDiligenceBase(BaseModel):
    pep_status: bool = False
    pep_details: Optional[str] = None
    acting_for_own_account: bool = True
    beneficial_owner_name: Optional[str] = None
    source_of_wealth: Optional[str] = None
    id_document_type: Optional[str] = None
    id_document_number: Optional[str] = None
    id_document_issuing_country: Optional[str] = None
    id_document_expiry: Optional[str] = None
    fatca_crs_self_certified: bool = False

    @model_validator(mode="after")
    def _validate_beneficial_owner(self):
        # GwG Art. 4: handelt der Kunde fuer einen Dritten (wirtschaftlich
        # Berechtigten), MUSS dessen Identitaet festgehalten werden. Anders
        # als pep_details (optional, kann spaeter ergaenzt werden) ist das
        # hier eine gesetzliche Pflichtangabe -- siehe Design-Vorgabe.
        if not self.acting_for_own_account and not (self.beneficial_owner_name or "").strip():
            raise ValueError(
                "beneficial_owner_name ist Pflicht, wenn acting_for_own_account=False "
                "(GwG Art. 4: wirtschaftlich Berechtigter muss festgehalten werden)"
            )
        return self


class ClientDueDiligenceCreate(ClientDueDiligenceBase):
    # DATA-CLASSIFICATION-GATE (Phase-0-Gate): identisches Muster wie
    # NationalityCreate/OptHistoryCreate -- GwG-Sorgfaltspflichtdaten sind
    # ebenso echte Personendaten.
    data_classification: Literal["synthetic", "real"] = "synthetic"


class ClientDueDiligenceUpdate(ClientDueDiligenceBase):
    data_classification: Literal["synthetic", "real"] = "synthetic"


class ClientDueDiligenceResponse(BaseResponse):
    id: str
    client_id: str
    pep_status: int
    pep_details: Optional[str]
    acting_for_own_account: int
    beneficial_owner_name: Optional[str]
    source_of_wealth: Optional[str]
    id_document_type: Optional[str]
    id_document_number: Optional[str]
    id_document_issuing_country: Optional[str]
    id_document_expiry: Optional[str]
    fatca_crs_self_certified: int
    created_at: str
    updated_at: str


class ClientTaxResidencyCreate(BaseModel):
    country_code: str
    tax_id_number: Optional[str] = None
    is_primary: bool = False
    data_classification: Literal["synthetic", "real"] = "synthetic"


class ClientTaxResidencyResponse(BaseResponse):
    id: str
    client_id: str
    country_code: str
    tax_id_number: Optional[str]
    is_primary: int
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
    recurring_income_rappen: int = 0
    capital_inflow_rappen: int = 0
    total_income_rappen: int
    recurring_expense_rappen: int = 0
    capital_outflow_rappen: int = 0
    total_expense_rappen: int
    recurring_net_rappen: int = 0
    capital_net_rappen: int = 0
    surplus_rappen: int
    total_income_chf: float
    total_expense_chf: float
    surplus_chf: float


class CashflowYearRow(BaseModel):
    year: int
    recurring_income_rappen: int = 0
    capital_inflow_rappen: int = 0
    income_rappen: int
    recurring_expense_rappen: int = 0
    capital_outflow_rappen: int = 0
    expense_rappen: int
    net_rappen: int


class CashflowProjectionResponse(BaseModel):
    client_id: str
    start_year: int
    years: list[CashflowYearRow]
