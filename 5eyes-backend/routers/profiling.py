from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload
from datetime import date, datetime, timezone
from types import SimpleNamespace
from database import get_db, new_uuid
from models.users import User
from models.mandates import Mandate
from models.clients import Client
from models.profiling import (
    ClientKnowledge, RiskAssessment, RiskAssessmentAnswer, SuitabilityCheck
)
from schemas.profiling import (
    KnowledgeCreate, KnowledgeResponse,
    RiskAssessmentCreate, RiskAssessmentOverride, RiskAssessmentResponse,
    SuitabilityCheckCreate, SuitabilityCheckResponse,
)
from services.auth import get_client_for_user_or_404, get_current_user, get_mandate_for_user_or_404, require_advisor
from services.audit import log
from services.portfolio_engine import risk_assessment_ready_for_strategy
from services.risk_scoring import canonicalize_horizon_label, compute_scores, profile_for_score_x10

router = APIRouter(tags=["Risikoprofilierung"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _canonical_risk_answer_section(question_number: int | None, question_section: str | None) -> str:
    section = str(question_section or "").strip()
    if section in {"Risikofähigkeit", "Risikobereitschaft"}:
        return section
    qn = int(question_number or 0)
    if qn in (9, 10, 11, 12):
        return "Risikobereitschaft"
    return "Risikofähigkeit"


def _get_mandate_or_404(mandate_id: str, db: Session, current_user: User) -> Mandate:
    return get_mandate_for_user_or_404(mandate_id, db, current_user)


# ── FIDLEG Kenntnisse ──────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/knowledge", response_model=list[KnowledgeResponse])
def list_knowledge(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    get_client_for_user_or_404(client_id, db, current_user)
    return db.query(ClientKnowledge).filter(
        ClientKnowledge.client_id == client_id,
        ClientKnowledge.deleted_at.is_(None)
    ).order_by(ClientKnowledge.valid_from.desc()).all()


@router.post("/clients/{client_id}/knowledge", response_model=KnowledgeResponse, status_code=201)
def create_knowledge(
    client_id: str,
    body: KnowledgeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    client = get_client_for_user_or_404(client_id, db, current_user)
    now = _now()
    today = date.today().isoformat()

    # Supersede previous current
    # Race-Hardening: pessimistic Lock auf den Anchor-Record. Auf Postgres
    # serialisiert das parallele "is_current=0; insert is_current=1"-Wechsel.
    # SQLite ignoriert FOR UPDATE (Single-Writer ohnehin serialisiert).
    prev = db.query(ClientKnowledge).filter(
        ClientKnowledge.client_id == client_id,
        ClientKnowledge.is_current == 1,
        ClientKnowledge.deleted_at.is_(None)
    ).with_for_update().first()
    prev_id = None
    prev_version = 0
    if prev:
        prev.is_current = 0
        prev.valid_to = today
        prev_id = prev.id
        prev_version = prev.version

    knowledge = ClientKnowledge(
        id=new_uuid(),
        client_id=client_id,
        version=prev_version + 1,
        is_current=1,
        valid_from=today,
        supersedes_id=prev_id,
        knowledge_level=body.knowledge_level,
        exp_equities=body.exp_equities,
        exp_bonds=body.exp_bonds,
        exp_funds=body.exp_funds,
        exp_derivatives=body.exp_derivatives,
        exp_alternatives=body.exp_alternatives,
        exp_structured=body.exp_structured,
        confirmed_at=now,
        confirmed_by=current_user.id,
        next_review_at=body.next_review_at,
        created_at=now,
        updated_at=now,
    )
    db.add(knowledge)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="client_knowledge", record_id=knowledge.id, action="CREATE",
        client_id=client_id)
    db.commit()
    db.refresh(knowledge)
    return knowledge


# ── Risikoprofilierung ─────────────────────────────────────────────────────────

@router.get("/mandates/{mandate_id}/risk-assessments", response_model=list[RiskAssessmentResponse])
def list_risk_assessments(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    return db.query(RiskAssessment).options(
        selectinload(RiskAssessment.answers)
    ).filter(
        RiskAssessment.mandate_id == mandate_id,
        RiskAssessment.deleted_at.is_(None)
    ).order_by(RiskAssessment.assessed_at.desc()).all()


@router.get("/mandates/{mandate_id}/risk-assessments/current", response_model=RiskAssessmentResponse)
def get_current_risk_assessment(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    ra = db.query(RiskAssessment).options(
        selectinload(RiskAssessment.answers)
    ).filter(
        RiskAssessment.mandate_id == mandate_id,
        RiskAssessment.is_current == 1,
        RiskAssessment.deleted_at.is_(None)
    ).first()
    if not ra:
        raise HTTPException(status_code=404, detail="Keine aktuelle Risikoprofilierung gefunden")
    return ra


@router.post("/mandates/{mandate_id}/risk-assessments", response_model=RiskAssessmentResponse, status_code=201)
def create_risk_assessment(
    mandate_id: str,
    body: RiskAssessmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    now = _now()
    today = date.today().isoformat()
    horizon_label = canonicalize_horizon_label(body.investment_horizon_label)

    # Compute scores from Fachlogik
    scores = compute_scores(
        q_income_points=body.q_income_points,
        q_obligations_points=body.q_obligations_points,
        q_savings_points=body.q_savings_points,
        q_wealth_points=body.q_wealth_points,
        investment_horizon_label=horizon_label,
        q_investment_goal_points=body.q_investment_goal_points,
        q_risk_preference_points=body.q_risk_preference_points,
        q_risk_behavior_points=body.q_risk_behavior_points,
    )
    final_score_x10 = int(scores.final_score_x10)
    final_profile = str(scores.final_profile)
    if str(mandate.mandate_type or "").strip().upper() == "FZK" and final_score_x10 > 75:
        final_score_x10 = 75
        final_profile = profile_for_score_x10(final_score_x10)

    knowledge_services_json = body.knowledge_services_json if body.knowledge_services_json is not None else "{}"
    knowledge_instruments_json = body.knowledge_instruments_json if body.knowledge_instruments_json is not None else "{}"
    income_sources_json = body.income_sources_json if body.income_sources_json is not None else "[]"
    readiness_probe = SimpleNamespace(
        final_score_x10=final_score_x10,
        override_score_x10=None,
        is_overridden=0,
        knowledge_services_json=knowledge_services_json,
        knowledge_instruments_json=knowledge_instruments_json,
        income_sources_json=income_sources_json,
        answers=[SimpleNamespace(**ans) for ans in (body.answers or [])],
    )
    if not risk_assessment_ready_for_strategy(readiness_probe):
        raise HTTPException(
            status_code=422,
            detail=(
                "Risikoprofil unvollstaendig. Bitte alle bewerteten Fragen "
                "anklicken und das Risikoprofil erneut speichern."
            ),
        )

    # Supersede previous (Race-Hardening, siehe ClientKnowledge oben).
    prev = db.query(RiskAssessment).filter(
        RiskAssessment.mandate_id == mandate_id,
        RiskAssessment.is_current == 1,
        RiskAssessment.deleted_at.is_(None)
    ).with_for_update().first()
    prev_id = None
    prev_version = 0
    if prev:
        prev.is_current = 0
        prev.valid_to = today
        prev_id = prev.id
        prev_version = prev.version

    ra = RiskAssessment(
        id=new_uuid(),
        mandate_id=mandate_id,
        version=prev_version + 1,
        is_current=1,
        valid_from=today,
        supersedes_id=prev_id,
        # Risikofähigkeit
        q_income_points=body.q_income_points,
        q_obligations_points=body.q_obligations_points,
        q_savings_points=body.q_savings_points,
        q_wealth_points=body.q_wealth_points,
        risk_capacity_total=scores.risk_capacity_total,
        risk_capacity_profile=scores.risk_capacity_profile,
        investment_horizon_years=body.investment_horizon_years,
        investment_horizon_label=horizon_label,
        risk_capacity_score_x10=scores.risk_capacity_score_x10,
        # Risikobereitschaft
        q_investment_goal_points=body.q_investment_goal_points,
        q_risk_preference_points=body.q_risk_preference_points,
        q_risk_behavior_points=body.q_risk_behavior_points,
        risk_willingness_total=scores.risk_willingness_total,
        risk_willingness_profile=scores.risk_willingness_profile,
        risk_willingness_score_x10=scores.risk_willingness_score_x10,
        # Final
        final_score_x10=final_score_x10,
        final_profile=final_profile,
        is_overridden=0,
        # Kenntnisse & Erfahrungen (Referenzmodell Eignungspruefung Seite 1) — FE sendet, Backend muss persistieren
        knowledge_services_json=knowledge_services_json,
        knowledge_instruments_json=knowledge_instruments_json,
        income_sources_json=income_sources_json,
        assessed_at=now,
        assessed_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(ra)

    # Store individual answers if provided
    if body.answers:
        for ans in body.answers:
            db.add(RiskAssessmentAnswer(
                id=new_uuid(),
                assessment_id=ra.id,
                question_number=ans.get("question_number"),
                question_section=_canonical_risk_answer_section(
                    ans.get("question_number"),
                    ans.get("question_section"),
                ),
                answer_label=ans.get("answer_label"),
                answer_points=ans.get("answer_points"),
                created_at=now,
            ))

    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="risk_assessments", record_id=ra.id, action="CREATE",
        mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    return db.query(RiskAssessment).options(
        selectinload(RiskAssessment.answers)
    ).filter(RiskAssessment.id == ra.id).one()


@router.post("/mandates/{mandate_id}/risk-assessments/{ra_id}/override",
             response_model=RiskAssessmentResponse)
def override_risk_assessment(
    mandate_id: str,
    ra_id: str,
    body: RiskAssessmentOverride,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    ra = db.query(RiskAssessment).filter(
        RiskAssessment.id == ra_id,
        RiskAssessment.mandate_id == mandate_id,
        RiskAssessment.deleted_at.is_(None)
    ).first()
    if not ra:
        raise HTTPException(status_code=404, detail="Risikoprofilierung nicht gefunden")
    if str(mandate.mandate_type or "").strip().upper() == "FZK" and int(body.override_score_x10 or 0) > 75:
        raise HTTPException(
            status_code=422,
            detail="FZK-Mandat: Override-Score darf 75 nicht überschreiten (FIDLEG)",
        )

    ra.is_overridden = 1
    ra.override_score_x10 = body.override_score_x10
    ra.override_profile = body.override_profile
    ra.override_by = current_user.id
    ra.override_at = _now()
    ra.override_reason = body.override_reason
    ra.override_client_confirmed = 1 if body.override_client_confirmed else 0
    ra.override_warning_delivered = 1 if body.override_warning_delivered else 0
    ra.override_warning_document_id = body.override_warning_document_id

    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="risk_assessments", record_id=ra_id, action="UPDATE",
        field_name="override", new_value=body.override_profile,
        mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    db.refresh(ra)
    return ra


# ── Suitability Checks ─────────────────────────────────────────────────────────

@router.get("/mandates/{mandate_id}/suitability-checks", response_model=list[SuitabilityCheckResponse])
def list_suitability_checks(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    return db.query(SuitabilityCheck).filter(
        SuitabilityCheck.mandate_id == mandate_id
    ).order_by(SuitabilityCheck.checked_at.desc()).all()


@router.post("/mandates/{mandate_id}/suitability-checks",
             response_model=SuitabilityCheckResponse, status_code=201)
def create_suitability_check(
    mandate_id: str,
    body: SuitabilityCheckCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    now = _now()
    check = SuitabilityCheck(
        id=new_uuid(),
        mandate_id=mandate_id,
        client_id=mandate.client_id,
        recommendation_run_id=body.recommendation_run_id,
        advisory_log_id=body.advisory_log_id,
        duty_type=body.duty_type,
        knowledge_assessment_id=body.knowledge_assessment_id,
        risk_assessment_id=body.risk_assessment_id,
        result=body.result,
        result_notes=body.result_notes,
        missing_information_json=body.missing_information_json,
        client_proceeding_despite=1 if body.client_proceeding_despite else 0,
        warning_delivered=1 if body.warning_delivered else 0,
        warning_delivered_at=body.warning_delivered_at,
        client_acknowledged=1 if body.client_acknowledged else 0,
        client_acknowledged_at=body.client_acknowledged_at,
        document_id=body.document_id,
        checked_by=current_user.id,
        checked_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(check)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="suitability_checks", record_id=check.id, action="CREATE",
        mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    db.refresh(check)
    return check
