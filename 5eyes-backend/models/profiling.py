from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


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
    # Kenntnisse & Erfahrungen - SwissLife W305.03 Seite 1 (kein Score, nur Compliance)
    knowledge_services_json = Column(String)    # {"Vermögensverwaltung":{"known":0,"informed":1},...}
    knowledge_instruments_json = Column(String) # {"Anlagefonds":{"known":1,"informed":1},...}
    # Herkunft des Einkommens - Frage 2, rein informativ (kein Score)
    income_sources_json = Column(String)        # ["Berufliche Tätigkeit","Rente"]
    assessed_at = Column(String, nullable=False)
    assessed_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    deleted_at = Column(String)

    mandate = relationship("Mandate", back_populates="risk_assessments")
    answers = relationship("RiskAssessmentAnswer", back_populates="assessment")
    assessor = relationship("User", foreign_keys=[assessed_by])
    overrider = relationship("User", foreign_keys=[override_by])


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
