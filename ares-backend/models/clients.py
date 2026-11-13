from sqlalchemy import DDL, CheckConstraint, Column, String, Integer, ForeignKey, event, text
from sqlalchemy.orm import relationship
from database import (
    CLIENT_PII_KEYS_SQLITE_TRIGGERS,
    KYC_CONFIRMATION_APPROVAL_SQLITE_TRIGGERS,
    KYC_CONFIRMATION_SQLITE_TRIGGERS,
    Base,
)


class Client(Base):
    __tablename__ = "clients"

    id = Column(String, primary_key=True)
    # Sprint T1 (2026-06-08): tenant_id fuer 3-Tier-Architektur. Nullable
    # in Stage 9 fuer Backwards-Compat (Default-Tenant 'main' via Migration).
    tenant_id = Column(String, ForeignKey("tenants.id"))
    client_number = Column(String, nullable=False, unique=True)
    salutation = Column(String)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    date_of_birth = Column(String)
    investment_horizon_start = Column(String)
    investment_horizon_end = Column(String)
    country_of_residence = Column(String, nullable=False, default="CH")
    canton = Column(String)
    civil_status = Column(String)
    profession = Column(String)
    employer = Column(String)
    language = Column(String, nullable=False, default="DE")
    partner_salutation = Column(String)
    partner_first_name = Column(String)
    partner_last_name = Column(String)
    partner_date_of_birth = Column(String)
    partner_profession = Column(String)
    household_type = Column(String, nullable=False, default="Einzelperson")
    client_classification = Column(String, nullable=False, default="Privatkunde")
    is_professional_opt_out = Column(Integer, nullable=False, default=0)
    is_qualified_investor = Column(Integer, nullable=False, default=0)
    advisor_id = Column(String, ForeignKey("users.id"), nullable=False)
    notes = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)
    # DSG Art. 32 (Loeschungsanspruch, Sprint 2026-08-15): gesetzt durch
    # Tier-A-Redaktion (services/client_erasure.py; seit H7 C-1 nur ueber den
    # Datenschutz-Workflow /privacy/erasure-cases). Unterscheidet
    # eine echte, irreversible PII-Anonymisierung von einem gewoehnlichen
    # Soft-Delete (deleted_at allein) -- verhindert insbesondere, dass eine
    # spaetere "Undelete"-Funktion (deleted_at=NULL) faelschlich Daten
    # wiederherstellt, die gar nicht mehr existieren. erasure_reason ist
    # die vom Admin dokumentierte Begruendung (FIDLEG-Audit-tauglich,
    # siehe services/override_reason_quality.py).
    erased_at = Column(String)
    erasure_reason = Column(String)

    advisor = relationship("User", back_populates="clients")
    nationalities = relationship("ClientNationality", back_populates="client")
    opt_history = relationship("ClientOptHistory", back_populates="client")
    mandates = relationship("Mandate", back_populates="client")
    wealth_positions = relationship("WealthPosition", back_populates="client")
    cashflows = relationship("Cashflow", back_populates="client")
    # KYC-01 (2026-10-07): GwG Art. 3-6 / GwV-FINMA Sorgfaltspflichten
    # -- siehe ClientDueDiligence/ClientTaxResidency unten.
    due_diligence = relationship(
        "ClientDueDiligence", back_populates="client", uselist=False
    )
    tax_residencies = relationship("ClientTaxResidency", back_populates="client")


class ClientNationality(Base):
    __tablename__ = "client_nationalities"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    country_code = Column(String, nullable=False)
    is_primary = Column(Integer, nullable=False, default=0)
    created_at = Column(String, nullable=False)

    client = relationship("Client", back_populates="nationalities")


class ClientOptHistory(Base):
    __tablename__ = "client_opt_history"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    event_type = Column(String, nullable=False)
    from_classification = Column(String, nullable=False)
    to_classification = Column(String, nullable=False)
    client_requested = Column(Integer, nullable=False, default=1)
    documented_by = Column(String, ForeignKey("users.id"), nullable=False)
    documented_at = Column(String, nullable=False)
    document_id = Column(String)
    notes = Column(String)
    created_at = Column(String, nullable=False)
    # DUAL-STACK-01-Nachtrag (2026-10-07): is_professional_opt_out/
    # is_qualified_investor hatten -- nach dem FIDLEG-STATE-001-Fix, der den
    # allgemeinen Client-PUT fuer diese Felder sperrte -- GAR KEINEN
    # gueltigen Aenderungspfad mehr (der Opt-History-Router transitionierte
    # bis dahin ausschliesslich client_classification). Diese vier Spalten
    # erfassen optionale Flag-Uebergaenge in DERSELBEN append-only, beleg-
    # gebundenen History-Zeile wie die Klassifikation -- NULL = diese
    # Transition hat das jeweilige Flag nicht veraendert (reine
    # Klassifikations-Aenderung ohne Flag-Wechsel bleibt moeglich).
    from_professional_opt_out = Column(Integer)
    to_professional_opt_out = Column(Integer)
    from_qualified_investor = Column(Integer)
    to_qualified_investor = Column(Integer)
    # H8 Luecke 7 (Art. 5 FIDLEG): Kriterien-Checkliste eines Opting-out
    # (Privatkunde -> Professioneller Kunde), kanonisches JSON. NULL bei
    # Uebergaengen ohne Opting-out und bei Altzeilen vor H8.
    opt_out_criteria_json = Column(String)

    client = relationship("Client", back_populates="opt_history")


class ClientDueDiligence(Base):
    """KYC-01 (Audit-Finding, 2026-10-07): GwG Art. 3-6 / GwV-FINMA
    Sorgfaltspflichten -- bislang hatte das Datenmodell KEINE Felder fuer
    PEP-Status, wirtschaftliche Berechtigung, Herkunft des Vermoegens,
    ID-Dokument-Verifikation oder FATCA/CRS-Selbstauskunft. 1:1 mit
    Client (eine Zeile pro Kunde, siehe ``client_id`` UNIQUE), analog zum
    bestehenden ClientNationality/ClientOptHistory-Stil in diesem File.
    """
    __tablename__ = "client_due_diligence"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False, unique=True)
    # GwG Art. 3-6 / GwV-FINMA Sorgfaltspflichten.
    pep_status = Column(Integer, nullable=False, default=0)  # 1 = Politically Exposed Person
    pep_details = Column(String)  # Freitext: Funktion/Zeitraum, nur wenn pep_status=1
    # H8 C-5: kein Default "handelt auf eigene Rechnung" mehr. Der Rohwert ist
    # nur gueltig, wenn ``acting_for_own_account_answered`` = 1; unbeantwortet
    # wird 0 gespeichert (nie die guenstigere Annahme) und das KYC-Gate ist rot.
    acting_for_own_account = Column(Integer, nullable=False, default=0)  # 0 = handelt fuer Dritte (wirtschaftlich Berechtigter)
    # 1 = vom Berater ausdruecklich beantwortet. Bestandszeilen (vor H8 mit
    # vorbelegtem "ja") erhalten 0 = "Bestaetigung fehlt", bis neu erfasst.
    acting_for_own_account_answered = Column(
        Integer, nullable=False, default=0, server_default=text("0"),
    )
    beneficial_owner_name = Column(String)  # Pflicht wenn acting_for_own_account=0
    source_of_wealth = Column(String)  # Freitext: Herkunft des Vermoegens (Erbschaft, Erwerbseinkommen, Unternehmensverkauf, ...)
    id_document_type = Column(String)  # z.B. "Pass", "ID-Karte", "Fuehrerausweis"
    id_document_number = Column(String)
    id_document_issuing_country = Column(String)
    id_document_expiry = Column(String)  # ISO-Datum
    fatca_crs_self_certified = Column(Integer, nullable=False, default=0)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    client = relationship("Client", back_populates="due_diligence", uselist=False)


class ClientTaxResidency(Base):
    """FATCA/CRS: ein Client kann MEHRERE steuerliche Ansaessigkeiten haben
    (analog ClientNationality fuer Staatsangehoerigkeiten)."""
    __tablename__ = "client_tax_residencies"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    country_code = Column(String, nullable=False)
    tax_id_number = Column(String)  # nullable: manche Laender vergeben keine TIN
    is_primary = Column(Integer, nullable=False, default=0)
    created_at = Column(String, nullable=False)

    client = relationship("Client", back_populates="tax_residencies")


class ClientPiiKey(Base):
    """DSG-ERASURE-APPEND-ONLY-001 (2026-10-21): Schluessel pro Kunde fuer das
    Crypto-Shredding der Freitexte in append-only Evidence-Tabellen
    (risk_override_decisions.reason, risk_profile_signoffs.note und die
    zugehoerigen audit_log-Snapshots), siehe services/pii_vault.py.

    Shred-only: die DSG-Art.-32-Erasure setzt key_material auf NULL und
    shredded_at; ein Trigger verbietet jedes andere UPDATE (kein Ersetzen,
    kein Wiederbeleben) und jedes DELETE (der Tombstone belegt die
    Vernichtung und haelt seal_for_client() fuer geloeschte Kunden
    fail-closed). Kein FK auf clients (Purge-fest wie audit_log).
    """

    __tablename__ = "client_pii_keys"
    __table_args__ = (
        CheckConstraint(
            "(key_material IS NULL) = (shredded_at IS NOT NULL)",
            name="ck_client_pii_keys_shredded",
        ),
    )

    client_id = Column(String, primary_key=True)
    key_id = Column(String, nullable=False, unique=True)
    key_material = Column(String)
    created_at = Column(String, nullable=False)
    shredded_at = Column(String)


for _trigger_ddl in CLIENT_PII_KEYS_SQLITE_TRIGGERS:
    event.listen(
        ClientPiiKey.__table__,
        "after_create",
        DDL(_trigger_ddl).execute_if(dialect="sqlite"),
    )


# ---------------------------------------------------------------------------
# H8 C-5 (Compliance-Audit 2026-11-07, Luecke 5): GwG-Sorgfaltspflichten.
#
# Abgrenzung: Die GwG-Abklaerung (Identifizierung, Feststellung des
# wirtschaftlich Berechtigten mit Formular A/K/S/T, Risikokategorisierung,
# besondere Abklaerungen) erfolgt im Prozess der Selbstregulierungs- bzw.
# Aufsichtsorganisation oder in einem Fremdsystem. Ares fuehrt diese
# Abklaerung NICHT, sondern erfasst je Kunde eine Pflicht-Bestaetigung, dass
# sie erfolgt ist (welches Formular, Datum, Referenz, Risikokategorie, PEP,
# naechste Aktualisierung). Diese Bestaetigung ist ein Gate vor Finalisierung
# und Vertragsunterzeichnung. Bestandskunden ohne Bestaetigung sind nicht
# still erfuellt, sondern "Bestaetigung fehlt".
#
# Append-only (Trigger SQLite/PostgreSQL): eine Korrektur ist eine neue
# Bestaetigung; es gilt die juengste. Kein FK auf clients/mandates
# (Purge-fest wie audit_log), nur die Akteure verweisen auf users.
# ---------------------------------------------------------------------------

KYC_PROCESS_EXTERNAL = "sro_oder_fremdprozess"
KYC_FORM_TYPES = ("A", "K", "S", "T")
KYC_RISK_NORMAL = "normal"
KYC_RISK_ELEVATED = "erhoeht"
KYC_RISK_CATEGORIES = (KYC_RISK_NORMAL, KYC_RISK_ELEVATED)


class KycConfirmation(Base):
    __tablename__ = "kyc_confirmations"

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    client_id = Column(String, nullable=False)
    mandate_id = Column(String)
    process_scope = Column(String, nullable=False)
    form_type = Column(String, nullable=False)
    form_completed_on = Column(String, nullable=False)
    external_reference = Column(String, nullable=False)
    risk_category = Column(String, nullable=False)
    is_pep = Column(Integer, nullable=False)
    # N-890-12: Identifizierung der Vertragspartei (GwG Art. 3) ausdruecklich.
    identification_confirmed = Column(Integer, nullable=False)
    identification_date = Column(String, nullable=False)
    next_review_due = Column(String, nullable=False)
    # N-890-03: bei der Erfassung festgehalten -- PEP, erhoehtes Risiko ODER
    # Herabstufung gegenueber der zuletzt wirksamen Bestaetigung.
    requires_second_approval = Column(Integer, nullable=False)
    note = Column(String)
    recorded_by = Column(String, ForeignKey("users.id"), nullable=False)
    recorded_at = Column(String, nullable=False)
    confirmation_hash = Column(String, nullable=False)


class KycConfirmationApproval(Base):
    """Freigabe einer KYC-Bestaetigung durch eine zweite Person (Vier-Augen),
    Pflicht bei PEP oder erhoehtem Risiko. Append-only; hoechstens eine je
    Bestaetigung (UNIQUE)."""

    __tablename__ = "kyc_confirmation_approvals"

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    confirmation_id = Column(String, nullable=False, unique=True)
    client_id = Column(String, nullable=False)
    approved_by = Column(String, ForeignKey("users.id"), nullable=False)
    approved_at = Column(String, nullable=False)
    note = Column(String)
    approval_hash = Column(String, nullable=False)


# ---------------------------------------------------------------------------
# H8 Luecke 10 (ZGB): Vertretung und Verfuegungsberechtigung, dokumentarisch.
# Vollmacht (OR 32 ff.), Vorsorgeauftrag (ZGB 360 ff.), Beistandschaft
# (ZGB 390 ff.), Gemeinschaftsdepot. Kein Gate -- Hinweis im
# Beratungsprotokoll-PDF. Widerruf statt Loeschen (revoked_*), jede Aenderung
# im Audit-Log.
# ---------------------------------------------------------------------------

REPRESENTATION_POWER_OF_ATTORNEY = "vollmacht"
REPRESENTATION_ADVANCE_DIRECTIVE = "vorsorgeauftrag"
REPRESENTATION_DEPUTYSHIP = "beistandschaft"
REPRESENTATION_JOINT_ACCOUNT = "gemeinschaftsdepot"
REPRESENTATION_TYPES = (
    REPRESENTATION_POWER_OF_ATTORNEY,
    REPRESENTATION_ADVANCE_DIRECTIVE,
    REPRESENTATION_DEPUTYSHIP,
    REPRESENTATION_JOINT_ACCOUNT,
)
JOINT_DISPOSAL_RULES = ("einzeln", "gemeinsam")


class ClientRepresentation(Base):
    __tablename__ = "client_representations"

    id = Column(String, primary_key=True)
    tenant_id = Column(String)
    client_id = Column(String, nullable=False)
    mandate_id = Column(String)
    representation_type = Column(String, nullable=False)
    representative_name = Column(String, nullable=False)
    scope = Column(String, nullable=False)
    evidence_reference = Column(String, nullable=False)
    effective_from = Column(String)
    effective_until = Column(String)
    disposal_rule = Column(String)
    note = Column(String)
    recorded_by = Column(String, ForeignKey("users.id"), nullable=False)
    recorded_at = Column(String, nullable=False)
    revoked_at = Column(String)
    revoked_by = Column(String)
    revocation_reason = Column(String)


for _model, _ddls in (
    (KycConfirmation, KYC_CONFIRMATION_SQLITE_TRIGGERS),
    (KycConfirmationApproval, KYC_CONFIRMATION_APPROVAL_SQLITE_TRIGGERS),
):
    for _trigger_ddl in _ddls:
        event.listen(
            _model.__table__,
            "after_create",
            DDL(_trigger_ddl).execute_if(dialect="sqlite"),
        )
