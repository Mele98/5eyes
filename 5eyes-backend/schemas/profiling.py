from pydantic import BaseModel, model_validator
from typing import Optional, Literal
from schemas.common import BaseResponse
from services.risk_scoring import profile_for_score_x10


# ── Knowledge ──────────────────────────────────────────────────────────────────

EXP_OPTIONS = Literal["Keine", "< 2 Jahre", "2–5 Jahre", "> 5 Jahre"]

class KnowledgeCreate(BaseModel):
    knowledge_level: Literal["Keine", "Gering", "Mittel", "Hoch"] = "Mittel"
    exp_equities: EXP_OPTIONS = "Keine"
    exp_bonds: EXP_OPTIONS = "Keine"
    exp_funds: EXP_OPTIONS = "Keine"
    exp_derivatives: EXP_OPTIONS = "Keine"
    exp_alternatives: EXP_OPTIONS = "Keine"
    exp_structured: EXP_OPTIONS = "Keine"
    next_review_at: Optional[str] = None


class KnowledgeResponse(BaseResponse):
    id: str
    client_id: str
    version: int
    is_current: int
    valid_from: str
    valid_to: Optional[str]
    knowledge_level: str
    exp_equities: str
    exp_bonds: str
    exp_funds: str
    exp_derivatives: str
    exp_alternatives: str
    exp_structured: str
    confirmed_at: str
    confirmed_by: str
    next_review_at: Optional[str]
    created_at: str


# ── Risk Assessment ────────────────────────────────────────────────────────────

class RiskAssessmentCreate(BaseModel):
    # Risikofähigkeit
    q_income_points: int        # 0–4
    q_obligations_points: int   # 0–4
    q_savings_points: int       # 0–12
    q_wealth_points: int        # 0–12
    investment_horizon_label: Literal[
        "Bis 2 Jahre", "2 bis 3 Jahre", "4 bis 5 Jahre",
        "6 bis 7 Jahre", "8 bis 11 Jahre", "Mehr als 12 Jahre",
        "0 bis 4 Jahre", "5 bis 7 Jahre", "12 Jahre und mehr",
        "1 bis 3 Jahre", "3 bis 5 Jahre", "5 bis 10 Jahre", "10 Jahre und mehr"
    ]
    investment_horizon_years: int
    # Risikobereitschaft
    q_investment_goal_points: int   # 1–4
    q_risk_preference_points: int   # 1–4
    q_risk_behavior_points: int     # 1–4
    # Answers for full documentation
    answers: Optional[list[dict]] = None
    # Kenntnisse & Erfahrungen (SwissLife W305.03 Seite 1) - optional, kein Score
    knowledge_services_json: Optional[str] = None
    knowledge_instruments_json: Optional[str] = None
    income_sources_json: Optional[str] = None

    @model_validator(mode="after")
    def validate_points(self):
        assert 0 <= self.q_income_points <= 4, "q_income_points muss zwischen 0 und 4 liegen"
        assert 0 <= self.q_obligations_points <= 4
        assert 0 <= self.q_savings_points <= 12
        assert 0 <= self.q_wealth_points <= 12
        assert 1 <= self.q_investment_goal_points <= 4
        assert 1 <= self.q_risk_preference_points <= 4
        assert 1 <= self.q_risk_behavior_points <= 4
        return self


class RiskAssessmentOverride(BaseModel):
    override_score_x10: int
    override_profile: Literal[
        "Kapitalschutz", "Defensiv", "Ausgewogen",
        "Wachstumsorientiert", "Dynamisch", "Aktien"
    ]
    override_reason: str  # NOT NULL per FIDLEG
    override_client_confirmed: bool = False
    override_warning_delivered: bool = False
    override_warning_document_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_override_score(self):
        assert 10 <= self.override_score_x10 <= 100, \
            "override_score_x10 muss zwischen 10 (Score 1) und 100 (Score 10) liegen"
        expected_profile = profile_for_score_x10(self.override_score_x10)
        if expected_profile != self.override_profile:
            raise ValueError(
                f"override_score_x10={self.override_score_x10} ergibt Profil "
                f"'{expected_profile}', nicht '{self.override_profile}'. "
                "Bitte Score und Profil konsistent setzen."
            )
        return self


class RiskAssessmentAnswerResponse(BaseResponse):
    id: str
    question_number: int
    question_section: str
    answer_label: str
    answer_points: int
    created_at: str


class RiskAssessmentResponse(BaseResponse):
    id: str
    mandate_id: str
    version: int
    is_current: int
    valid_from: str
    # Risikofähigkeit
    q_income_points: int
    q_obligations_points: int
    q_savings_points: int
    q_wealth_points: int
    risk_capacity_total: int
    risk_capacity_profile: str
    investment_horizon_years: int
    investment_horizon_label: str
    risk_capacity_score_x10: int
    # Risikobereitschaft
    q_investment_goal_points: int
    q_risk_preference_points: int
    q_risk_behavior_points: int
    risk_willingness_total: int
    risk_willingness_profile: str
    risk_willingness_score_x10: int
    # Ergebnis
    final_score_x10: int
    final_profile: str
    # Override
    is_overridden: int
    override_score_x10: Optional[int]
    override_profile: Optional[str]
    override_at: Optional[str]
    override_reason: Optional[str]
    override_client_confirmed: Optional[int]
    override_warning_delivered: Optional[int]
    assessed_at: str
    assessed_by: str
    created_at: str
    answers: list[RiskAssessmentAnswerResponse] = []
    knowledge_services_json: Optional[str] = None
    knowledge_instruments_json: Optional[str] = None
    income_sources_json: Optional[str] = None


# ── Suitability Check ──────────────────────────────────────────────────────────

class SuitabilityCheckCreate(BaseModel):
    duty_type: Literal["Eignungsprüfung", "Angemessenheitsprüfung", "Keine Prüfung"]
    knowledge_assessment_id: Optional[str] = None
    risk_assessment_id: Optional[str] = None
    result: Literal[
        "Geeignet", "Nicht geeignet", "Angemessen",
        "Nicht angemessen", "Unvollständige Information", "Geeignet mit Einschränkung"
    ]
    result_notes: Optional[str] = None
    missing_information_json: Optional[str] = None
    client_proceeding_despite: bool = False
    warning_delivered: bool = False
    warning_delivered_at: Optional[str] = None
    client_acknowledged: bool = False
    client_acknowledged_at: Optional[str] = None
    document_id: Optional[str] = None
    recommendation_run_id: Optional[str] = None
    advisory_log_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_warning(self):
        if self.client_proceeding_despite and not self.warning_delivered:
            raise ValueError("Wenn Kunde trotzdem fortfährt, muss warning_delivered=True sein")
        if self.warning_delivered and not self.warning_delivered_at:
            raise ValueError("warning_delivered_at ist Pflicht wenn warning_delivered=True")
        return self


class SuitabilityCheckResponse(BaseResponse):
    id: str
    mandate_id: str
    client_id: str
    duty_type: str
    result: str
    result_notes: Optional[str]
    client_proceeding_despite: int
    warning_delivered: int
    warning_delivered_at: Optional[str]
    client_acknowledged: int
    checked_by: str
    checked_at: str
    created_at: str
