from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


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
    # POST /clients/{id}/erase (services/client_erasure.py). Unterscheidet
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
    # KYC-01 (2026-10-07): GwG Art. 3-6 / FINMA-RS 2016/7 Sorgfaltspflichten
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

    client = relationship("Client", back_populates="opt_history")


class ClientDueDiligence(Base):
    """KYC-01 (Audit-Finding, 2026-10-07): GwG Art. 3-6 / FINMA-RS 2016/7
    Sorgfaltspflichten -- bislang hatte das Datenmodell KEINE Felder fuer
    PEP-Status, wirtschaftliche Berechtigung, Herkunft des Vermoegens,
    ID-Dokument-Verifikation oder FATCA/CRS-Selbstauskunft. 1:1 mit
    Client (eine Zeile pro Kunde, siehe ``client_id`` UNIQUE), analog zum
    bestehenden ClientNationality/ClientOptHistory-Stil in diesem File.
    """
    __tablename__ = "client_due_diligence"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False, unique=True)
    # GwG Art. 3-6 / FINMA-RS 2016/7 Sorgfaltspflichten.
    pep_status = Column(Integer, nullable=False, default=0)  # 1 = Politically Exposed Person
    pep_details = Column(String)  # Freitext: Funktion/Zeitraum, nur wenn pep_status=1
    acting_for_own_account = Column(Integer, nullable=False, default=1)  # 0 = handelt fuer Dritte (wirtschaftlich Berechtigter)
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
