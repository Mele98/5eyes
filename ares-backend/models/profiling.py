from sqlalchemy import DDL, CheckConstraint, Column, String, Integer, ForeignKey, Index, event, text
from sqlalchemy.orm import relationship
from database import (
    RISK_OVERRIDE_DECISION_SQLITE_TRIGGERS,
    RISK_PROFILE_SIGNOFF_SQLITE_TRIGGERS,
    Base,
)


class ClientKnowledge(Base):
    __tablename__ = "client_knowledge"

    id = Column(String, primary_key=True)
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Integer, nullable=False, default=1)
    valid_from = Column(String, nullable=False)
    valid_to = Column(String)
    supersedes_id = Column(String, ForeignKey("client_knowledge.id"))
    knowledge_level = Column(String, nullable=False, default="Mittel")
    exp_equities = Column(String, nullable=False, default="Keine")
    exp_bonds = Column(String, nullable=False, default="Keine")
    exp_funds = Column(String, nullable=False, default="Keine")
    exp_derivatives = Column(String, nullable=False, default="Keine")
    exp_alternatives = Column(String, nullable=False, default="Keine")
    exp_structured = Column(String, nullable=False, default="Keine")
    confirmed_at = Column(String, nullable=False)
    confirmed_by = Column(String, ForeignKey("users.id"), nullable=False)
    next_review_at = Column(String)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    client = relationship("Client")
    confirmer = relationship("User")


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    __table_args__ = (
        Index(
            "ux_risk_one_current",
            "mandate_id",
            unique=True,
            sqlite_where=text("is_current = 1 AND deleted_at IS NULL"),
            postgresql_where=text("is_current = 1 AND deleted_at IS NULL"),
        ),
    )

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Integer, nullable=False, default=1)
    valid_from = Column(String, nullable=False)
    valid_to = Column(String)
    supersedes_id = Column(String)
    # Risikofähigkeit
    q_income_points = Column(Integer, nullable=False)
    q_obligations_points = Column(Integer, nullable=False)
    q_savings_points = Column(Integer, nullable=False)
    q_wealth_points = Column(Integer, nullable=False)
    risk_capacity_total = Column(Integer, nullable=False)
    risk_capacity_profile = Column(String, nullable=False)
    investment_horizon_years = Column(Integer, nullable=False)
    investment_horizon_label = Column(String, nullable=False)
    risk_capacity_score_x10 = Column(Integer, nullable=False)
    # Risikobereitschaft
    q_investment_goal_points = Column(Integer, nullable=False)
    q_risk_preference_points = Column(Integer, nullable=False)
    q_risk_behavior_points = Column(Integer, nullable=False)
    risk_willingness_total = Column(Integer, nullable=False)
    risk_willingness_profile = Column(String, nullable=False)
    risk_willingness_score_x10 = Column(Integer, nullable=False)
    # Ergebnis
    final_score_x10 = Column(Integer, nullable=False)
    final_profile = Column(String, nullable=False)
    # Override
    is_overridden = Column(Integer, nullable=False, default=0)
    override_score_x10 = Column(Integer)
    override_profile = Column(String)
    override_by = Column(String, ForeignKey("users.id"))
    override_at = Column(String)
    override_reason = Column(String)
    override_client_confirmed = Column(Integer, default=0)
    override_warning_delivered = Column(Integer, default=0)
    override_warning_document_id = Column(String)
    # RISK-OVERRIDE-WRITE-BOUNDARY-001 Restbefund B (2026-10-19): Pointer auf
    # die aktuell wirksame, append-only RiskOverrideDecisionV1-Zeile (siehe
    # RiskOverrideDecision unten). Die override_*-Felder oben sind nur noch
    # die abgeleitete Projektion dieser Decision; die Evidence jeder frueheren
    # Entscheidung liegt unveraendert in risk_override_decisions. Bewusst
    # ohne FK-Constraint (zirkulaerer Verweis + SQLite-ALTER fuer Alt-DBs).
    # NULL = kein Override oder Altbestand-Override vor diesem Fix.
    override_decision_id = Column(String)
    override_decision_hash = Column(String)
    # Kenntnisse & Erfahrungen - Referenzmodell Eignungspruefung Seite 1 (kein Score, nur Compliance)
    knowledge_services_json = Column(String)    # {"Vermögensverwaltung":{"known":0,"informed":1},...}
    knowledge_instruments_json = Column(String) # {"Anlagefonds":{"known":1,"informed":1},...}
    # Herkunft des Einkommens - Frage 2, rein informativ (kein Score)
    income_sources_json = Column(String)        # ["Berufliche Tätigkeit","Rente"]
    # FIDLEG-Eignungspruefung: Kunden-Signatur des Risikoprofils (2026-07-19).
    # Reine DOKUMENTATION der Kunden-Bestaetigung — aendert NICHT die
    # Eignungs-Konformitaet (is_compliant im Audit). Modell B (Kundenportal:
    # method='portal') oder Fallback A (Berater erfasst: method='advisor_recorded').
    client_signed_at = Column(String)           # ISO-UTC; None = noch nicht signiert
    client_signed_method = Column(String)       # 'portal' | 'advisor_recorded'
    client_signed_ref = Column(String)          # Portal-User-ID bzw. Berater-Notiz
    # RISK-PROFILE-SIGNOFF-001 (Codex-Closure-Review zu PR #657, 2026-10-20):
    # die client_signed_*-Felder oben sind nur noch die Projektion des aktuell
    # gueltigen, append-only RiskProfileSignoffV1 (RiskProfileSignoff unten).
    # signoff_id/_hash zeigen auf genau diesen Snapshot; ein Override/Re-
    # Override setzt Projektion + Pointer im selben Compare-and-Swap zurueck
    # und signoff_status auf 'signature_required' -- der alte Signoff bleibt
    # als historische Evidence unveraendert stehen. 'legacy_unbound' = Alt-
    # signatur vor RiskProfileSignoffV1 (nicht an eine Decision gebunden).
    # Bewusst ohne FK-Constraint (wie override_decision_id).
    signoff_id = Column(String)
    signoff_hash = Column(String)
    signoff_status = Column(String)             # signed | signature_required | legacy_unbound
    assessed_at = Column(String, nullable=False)
    assessed_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    mandate = relationship("Mandate", back_populates="risk_assessments")
    answers = relationship("RiskAssessmentAnswer", back_populates="assessment")
    assessor = relationship("User", foreign_keys=[assessed_by])
    overrider = relationship("User", foreign_keys=[override_by])

    @property
    def signoff_state(self) -> str:
        """Fachlicher Signoff-Zustand (services/risk_profile_signoff.py).

        Codex-Closure-Review PR #662: ``signed`` nur, wenn der Signoff-Nachweis
        noch semantisch zu diesem Assessment passt (sonst
        ``integrity_mismatch``) -- dieselbe Pruefung wie PDFs/Strategie."""
        from services.risk_profile_signoff import verified_signoff_state

        return verified_signoff_state(None, self)


class RiskOverrideDecision(Base):
    """RiskOverrideDecisionV1 -- unveraenderlicher Nachweis EINER Override-
    Entscheidung (RISK-OVERRIDE-WRITE-BOUNDARY-001, Restbefund B).

    Jeder Override und jeder Re-Override schreibt genau eine neue Zeile; eine
    Korrektur ist immer eine neue Zeile (previous_decision_id verkettet), nie
    ein UPDATE. Append-only per Schema: KEIN updated_at, KEIN deleted_at;
    SQLite- (Trigger unten) und PostgreSQL-Trigger (Alembic-Revision
    c4e9a7d2b815) verbieten UPDATE/DELETE.

    Gebunden werden die Basis, gegen die validiert wurde (Assessment-Version,
    final/capacity/willingness-Score), die Anfrage, die damals effektiven
    Requirements samt Regelversion -- ein spaeterer Policywechsel deutet alte
    Entscheidungen dadurch nicht rueckwirkend um -- und ein SHA-256 ueber den
    kanonischen Snapshot (services/risk_override_decision.py).

    Kein FK auf risk_assessments/mandates (Muster audit_log), damit der
    Foundation-/Demo-Purge funktioniert und die Zeilen danach stehen bleiben.

    (assessment_id, sequence_no) ist eindeutig: zwei parallele Appends auf
    denselben Stand koennen nicht beide gewinnen.
    """

    __tablename__ = "risk_override_decisions"
    __table_args__ = (
        Index(
            "ux_risk_override_decision_sequence",
            "assessment_id",
            "sequence_no",
            unique=True,
        ),
        Index("ix_risk_override_decisions_mandate", "mandate_id"),
        Index("ix_risk_override_decisions_tenant_id", "tenant_id"),
    )

    id = Column(String, primary_key=True)
    schema_version = Column(String, nullable=False, default="RiskOverrideDecisionV1")
    # CIO-Entscheid 2026-10-19: wie audit_log KEIN harter Fremdschluessel auf
    # risk_assessments/mandates -- die Referenz ist eine indizierte Spalte.
    # Ein Foundation-/Demo-Purge loescht Assessment und Mandat, die Decision-
    # Zeilen bleiben als unveraenderlicher Nachweis stehen (wie audit_log).
    assessment_id = Column(String, nullable=False)
    mandate_id = Column(String, nullable=False)
    client_id = Column(String)
    # PG-002 (Codex-Closure-Review PR #662): Mandant aus dem Mandat abgeleitet
    # (services/risk_evidence_tenant_boundary.py), ab Schema V2 im Hash.
    # NULL nur fuer quarantaenierten Altbestand ohne ableitbares Mandat.
    tenant_id = Column(String)
    assessment_version = Column(Integer, nullable=False)
    sequence_no = Column(Integer, nullable=False)
    previous_decision_id = Column(String)
    basis_final_score_x10 = Column(Integer, nullable=False)
    basis_final_profile = Column(String)
    basis_capacity_score_x10 = Column(Integer)
    basis_willingness_score_x10 = Column(Integer)
    requested_score_x10 = Column(Integer, nullable=False)
    requested_profile = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    client_confirmed = Column(Integer, nullable=False, default=0)
    warning_delivered = Column(Integer, nullable=False, default=0)
    warning_document_id = Column(String)
    required_client_confirmation = Column(Integer, nullable=False, default=0)
    required_warning = Column(Integer, nullable=False, default=0)
    actor_id = Column(String, ForeignKey("users.id"), nullable=False)
    decided_at = Column(String, nullable=False)
    rules_version = Column(String, nullable=False)
    decision_hash = Column(String(64), nullable=False)
    created_at = Column(String, nullable=False)


for _trigger_ddl in RISK_OVERRIDE_DECISION_SQLITE_TRIGGERS:
    event.listen(
        RiskOverrideDecision.__table__,
        "after_create",
        DDL(_trigger_ddl).execute_if(dialect="sqlite"),
    )


class RiskProfileSignoff(Base):
    """RiskProfileSignoffV1 -- unveraenderlicher Nachweis EINER Signatur des
    Risikoprofils (RISK-PROFILE-SIGNOFF-001, Codex-Closure-Review zu PR #657).

    Gebunden werden Assessment-Version, wirksamer Score/Profil, die zum
    Signaturzeitpunkt verifizierte Override-Decision (ID + Hash) bzw.
    ausdruecklich ``override_binding='no_override'``, ein Hash ueber die
    Fragebogen-Inputs, optional das signierte Dokument (ID + Hash), Akteur,
    Methode + Beweisniveau (``advisor_attested`` = Berater hat die
    Bestaetigung erfasst, KEINE elektronische Kundensignatur;
    ``client_portal`` = Kunde selbst im Portal), Zeitpunkt, Regelversion und
    ein SHA-256 ueber den kanonischen Snapshot.

    Append-only: KEIN updated_at/deleted_at, UPDATE/DELETE per Trigger
    verboten (SQLite unten, PostgreSQL Alembic d7b3f1a9c2e4). Wie
    risk_override_decisions KEIN FK auf risk_assessments/mandates
    (Purge-fest). (assessment_id, sequence_no) eindeutig.
    """

    __tablename__ = "risk_profile_signoffs"
    __table_args__ = (
        Index(
            "ux_risk_profile_signoff_sequence",
            "assessment_id",
            "sequence_no",
            unique=True,
        ),
        Index("ix_risk_profile_signoffs_mandate", "mandate_id"),
        Index("ix_risk_profile_signoffs_tenant_id", "tenant_id"),
        CheckConstraint(
            "override_binding IN ('decision','no_override')",
            name="ck_risk_profile_signoff_binding",
        ),
        CheckConstraint(
            "(override_binding = 'decision' AND override_decision_id IS NOT NULL "
            "AND override_decision_hash IS NOT NULL) OR (override_binding = 'no_override' "
            "AND override_decision_id IS NULL AND override_decision_hash IS NULL)",
            name="ck_risk_profile_signoff_binding_refs",
        ),
        CheckConstraint(
            "method IN ('advisor_recorded','portal')",
            name="ck_risk_profile_signoff_method",
        ),
        CheckConstraint(
            "evidence_level IN ('advisor_attested','client_portal')",
            name="ck_risk_profile_signoff_evidence",
        ),
    )

    id = Column(String, primary_key=True)
    schema_version = Column(String, nullable=False, default="RiskProfileSignoffV1")
    assessment_id = Column(String, nullable=False)
    mandate_id = Column(String, nullable=False)
    client_id = Column(String)
    # PG-002 (Codex-Closure-Review PR #662): siehe RiskOverrideDecision.tenant_id.
    tenant_id = Column(String)
    assessment_version = Column(Integer, nullable=False)
    sequence_no = Column(Integer, nullable=False)
    previous_signoff_id = Column(String)
    effective_score_x10 = Column(Integer, nullable=False)
    effective_profile = Column(String, nullable=False)
    final_score_x10 = Column(Integer, nullable=False)
    final_profile = Column(String)
    is_overridden = Column(Integer, nullable=False, default=0)
    override_binding = Column(String, nullable=False)
    override_decision_id = Column(String)
    override_decision_hash = Column(String)
    override_rules_version = Column(String)
    assessment_input_hash = Column(String, nullable=False)
    document_id = Column(String)
    document_hash = Column(String)
    method = Column(String, nullable=False)
    evidence_level = Column(String, nullable=False)
    actor_id = Column(String, ForeignKey("users.id"), nullable=False)
    actor_role = Column(String)
    note = Column(String)
    signed_at = Column(String, nullable=False)
    rules_version = Column(String, nullable=False)
    signoff_hash = Column(String(64), nullable=False)
    created_at = Column(String, nullable=False)


for _trigger_ddl in RISK_PROFILE_SIGNOFF_SQLITE_TRIGGERS:
    event.listen(
        RiskProfileSignoff.__table__,
        "after_create",
        DDL(_trigger_ddl).execute_if(dialect="sqlite"),
    )

# PG-002: Mandanten-/Kombinationsschutz beim INSERT (nach create_all, wenn
# mandates und risk_assessments sicher existieren).
from services import risk_evidence_tenant_boundary as _retb  # noqa: E402

event.listen(Base.metadata, "after_create", _retb.create_sqlite_guards_after_metadata_create)


class RiskAssessmentAnswer(Base):
    __tablename__ = "risk_assessment_answers"

    id = Column(String, primary_key=True)
    assessment_id = Column(String, ForeignKey("risk_assessments.id"), nullable=False)
    question_number = Column(Integer, nullable=False)
    question_section = Column(String, nullable=False)
    answer_label = Column(String, nullable=False)
    answer_points = Column(Integer, nullable=False)
    created_at = Column(String, nullable=False)

    assessment = relationship("RiskAssessment", back_populates="answers")


class SuitabilityCheck(Base):
    __tablename__ = "suitability_checks"

    id = Column(String, primary_key=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    client_id = Column(String, nullable=False)
    recommendation_run_id = Column(String)
    advisory_log_id = Column(String)
    duty_type = Column(String, nullable=False)
    knowledge_assessment_id = Column(String)
    risk_assessment_id = Column(String)
    result = Column(String, nullable=False)
    result_notes = Column(String)
    missing_information_json = Column(String)
    client_proceeding_despite = Column(Integer, nullable=False, default=0)
    warning_delivered = Column(Integer, nullable=False, default=0)
    warning_delivered_at = Column(String)
    client_acknowledged = Column(Integer, nullable=False, default=0)
    client_acknowledged_at = Column(String)
    document_id = Column(String)
    checked_by = Column(String, ForeignKey("users.id"), nullable=False)
    checked_at = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    mandate = relationship("Mandate", back_populates="suitability_checks")
    checker = relationship("User")
