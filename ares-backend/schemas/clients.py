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
    # DSG-ERASURE-APPEND-ONLY-001: vernichtete Kundenschluessel (Crypto-
    # Shredding der versiegelten Freitexte in append-only Evidence) und
    # Altbestand-Zeilen mit Klartext, die ohne Aufweichung der Trigger nicht
    # redigiert werden koennen (Owner-/Legal-Entscheid -- sichtbar gemeldet).
    pii_keys_shredded: int = 0
    unsealed_append_only_rows: dict[str, int] = {}


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


class OptOutCriteria(BaseModel):
    """H8 Luecke 7: Kriterien-Checkliste fuer ein Opting-out nach Art. 5 FIDLEG
    (vermoegende Privatkunden erklaeren, als professionelle Kunden gelten zu
    wollen). Kriterien gemaess Art. 5 Abs. 2 FIDLEG [Compliance pruefen]:
    lit. a Kenntnisse aus Ausbildung/Berufserfahrung UND anrechenbares
    Vermoegen von mindestens CHF 500 000, oder lit. b anrechenbares Vermoegen
    von mindestens CHF 2 Mio. Ares prueft nicht das Vermoegen selbst, sondern
    verlangt die dokumentierte Bestaetigung je Kriterium."""

    basis: Literal["kenntnisse_und_vermoegen_500k", "vermoegen_2mio"]
    eligible_assets_verified: bool
    knowledge_basis: Optional[str] = None
    client_informed_of_protection_loss: bool
    declaration_in_text_form: bool

    @model_validator(mode="after")
    def _validate_checklist(self):
        missing: list[str] = []
        if not self.eligible_assets_verified:
            missing.append("anrechenbares Vermoegen geprueft")
        if not self.client_informed_of_protection_loss:
            missing.append("Aufklaerung ueber den Verlust des Anlegerschutzes")
        if not self.declaration_in_text_form:
            missing.append("Erklaerung des Kunden in Textform")
        if self.basis == "kenntnisse_und_vermoegen_500k" and len((self.knowledge_basis or "").strip()) < 10:
            missing.append("Nachweis der Kenntnisse (Ausbildung/Berufserfahrung, mind. 10 Zeichen)")
        if missing:
            raise ValueError(
                "Opting-out nach Art. 5 FIDLEG unvollstaendig dokumentiert: "
                + "; ".join(missing)
            )
        return self


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
    # H8 Luecke 7 (Art. 5 FIDLEG): Pflicht bei einem Opting-out (Privatkunde
    # -> professionell bzw. Opting-out-Flag -> True), zusammen mit
    # ``document_id`` (Beleg der Erklaerung). Pruefung im Router, weil sie den
    # gespeicherten Ausgangszustand kennen muss.
    opt_out_criteria: Optional[OptOutCriteria] = None
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
    document_id: Optional[str] = None
    opt_out_criteria_json: Optional[str] = None


class ClientDueDiligenceBase(BaseModel):
    pep_status: bool = False
    pep_details: Optional[str] = None
    # H8 C-5: kein Default "ja" mehr. None = unbeantwortet (KYC-Gate rot).
    acting_for_own_account: Optional[bool] = None
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
        if self.acting_for_own_account is False and not (self.beneficial_owner_name or "").strip():
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
    # H8 C-5: None = unbeantwortet (auch Bestandszeilen vor H8).
    acting_for_own_account: Optional[int] = None
    acting_for_own_account_answered: int = 0
    beneficial_owner_name: Optional[str]
    source_of_wealth: Optional[str]
    id_document_type: Optional[str]
    id_document_number: Optional[str]
    id_document_issuing_country: Optional[str]
    id_document_expiry: Optional[str]
    fatca_crs_self_certified: int
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def _hide_unanswered_own_account(self):
        if not self.acting_for_own_account_answered:
            self.acting_for_own_account = None
        return self


# ---------------------------------------------------------------------------
# H8 C-5: GwG-Bestaetigung (Abklaerung im SRO-/Fremdprozess) als Gate.
# ---------------------------------------------------------------------------

def _iso_date(value: str, field: str) -> str:
    try:
        return _date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field} muss ein ISO-Datum (JJJJ-MM-TT) sein") from exc


class KycConfirmationCreate(BaseModel):
    """Bestaetigung, dass die GwG-Abklaerung im Prozess der SRO/AO bzw. im
    Fremdsystem erfolgt ist. Alle fachlichen Felder ohne Vorbelegung --
    insbesondere ``is_pep`` und ``risk_category`` muessen ausdruecklich
    beantwortet werden."""

    mandate_id: Optional[str] = None
    form_type: Literal["A", "K", "S", "T"]
    form_completed_on: str
    external_reference: str
    risk_category: Literal["normal", "erhoeht"]
    is_pep: bool
    next_review_due: str
    note: Optional[str] = None
    data_classification: Literal["synthetic", "real"] = "synthetic"

    @model_validator(mode="after")
    def _validate(self):
        self.form_completed_on = _iso_date(self.form_completed_on, "form_completed_on")
        self.next_review_due = _iso_date(self.next_review_due, "next_review_due")
        if _date.fromisoformat(self.form_completed_on) > _date.today():
            raise ValueError("form_completed_on darf nicht in der Zukunft liegen")
        if self.next_review_due <= self.form_completed_on:
            raise ValueError("next_review_due muss nach form_completed_on liegen")
        if len(self.external_reference.strip()) < 3:
            raise ValueError("external_reference (Referenz im SRO-/Fremdprozess) ist Pflicht")
        self.external_reference = self.external_reference.strip()
        return self


class KycConfirmationApprovalCreate(BaseModel):
    note: Optional[str] = None


class KycConfirmationApprovalResponse(BaseResponse):
    id: str
    confirmation_id: str
    client_id: str
    approved_by: str
    approved_at: str
    note: Optional[str] = None
    approval_hash: str


class KycConfirmationResponse(BaseResponse):
    id: str
    client_id: str
    mandate_id: Optional[str] = None
    process_scope: str
    form_type: str
    form_completed_on: str
    external_reference: str
    risk_category: str
    is_pep: int
    next_review_due: str
    note: Optional[str] = None
    recorded_by: str
    recorded_at: str
    confirmation_hash: str
    requires_second_approval: bool = False
    approval: Optional[KycConfirmationApprovalResponse] = None


# ---------------------------------------------------------------------------
# H8 Luecke 10: Vertretung / Verfuegungsberechtigung (dokumentarisch).
# ---------------------------------------------------------------------------

class ClientRepresentationCreate(BaseModel):
    mandate_id: Optional[str] = None
    representation_type: Literal["vollmacht", "vorsorgeauftrag", "beistandschaft", "gemeinschaftsdepot"]
    representative_name: str
    scope: str
    evidence_reference: str
    effective_from: Optional[str] = None
    effective_until: Optional[str] = None
    disposal_rule: Optional[Literal["einzeln", "gemeinsam"]] = None
    note: Optional[str] = None
    data_classification: Literal["synthetic", "real"] = "synthetic"

    @model_validator(mode="after")
    def _validate(self):
        for name in ("representative_name", "scope", "evidence_reference"):
            value = str(getattr(self, name) or "").strip()
            if len(value) < 2:
                raise ValueError(f"{name} ist Pflicht")
            setattr(self, name, value)
        if self.effective_from:
            self.effective_from = _iso_date(self.effective_from, "effective_from")
        if self.effective_until:
            self.effective_until = _iso_date(self.effective_until, "effective_until")
        if self.effective_from and self.effective_until and self.effective_until < self.effective_from:
            raise ValueError("effective_until liegt vor effective_from")
        # Vorsorgeauftrag (ZGB 363) und Beistandschaft (ZGB 390 ff.) wirken
        # erst ab Validierung bzw. Errichtung durch die KESB: Wirksamkeit Pflicht.
        if self.representation_type in ("vorsorgeauftrag", "beistandschaft") and not self.effective_from:
            raise ValueError(
                "effective_from (Wirksamkeit gemaess KESB-Entscheid) ist bei "
                "Vorsorgeauftrag und Beistandschaft Pflicht"
            )
        if self.representation_type == "gemeinschaftsdepot" and not self.disposal_rule:
            raise ValueError("disposal_rule (einzeln/gemeinsam) ist beim Gemeinschaftsdepot Pflicht")
        if self.representation_type != "gemeinschaftsdepot" and self.disposal_rule:
            raise ValueError("disposal_rule gilt nur fuer das Gemeinschaftsdepot")
        return self


class ClientRepresentationRevoke(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        if len(value.strip()) < 5:
            raise ValueError("Begruendung des Widerrufs (mind. 5 Zeichen) ist Pflicht")
        return value.strip()


class ClientRepresentationResponse(BaseResponse):
    id: str
    client_id: str
    mandate_id: Optional[str] = None
    representation_type: str
    representative_name: str
    scope: str
    evidence_reference: str
    effective_from: Optional[str] = None
    effective_until: Optional[str] = None
    disposal_rule: Optional[str] = None
    note: Optional[str] = None
    recorded_by: str
    recorded_at: str
    revoked_at: Optional[str] = None
    revoked_by: Optional[str] = None
    revocation_reason: Optional[str] = None


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
    # CASHFLOW-TAB-PENSION-PAYOUTS-001: automatischer Vorsorgebezug (3a/FZ/
    # Police) netto nach Kapitalbezugssteuer aus PensionTransferLedgerV1 --
    # NICHT in capital_inflow_rappen, aber in income_rappen/net_rappen.
    pension_payout_rappen: int = 0


class CashflowPensionTransfer(BaseModel):
    year: int
    source_position_id: str
    source_label: str
    pension_type: str
    origin: str
    linked_inflow_id: str | None = None
    gross_withdrawal_rappen: int
    lumpsum_tax_rappen: int
    tax_source: str
    net_advisory_inflow_rappen: int
    currency: str


class CashflowProjectionResponse(BaseModel):
    client_id: str
    start_year: int
    years: list[CashflowYearRow]
    # Ledger-Zeilen im Horizont (auto UND verknuepft) zur Offenlegung.
    pension_transfers: list[CashflowPensionTransfer] = []
    pension_ledger_hash: str | None = None
