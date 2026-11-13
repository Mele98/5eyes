import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from datetime import date, datetime, timezone
from types import SimpleNamespace
from database import get_db, new_uuid
from models.users import User
from models.mandates import Mandate
from models.clients import Client
from models.profiling import (
    ClientKnowledge, InvestmentPreferenceDecision, RiskAssessment, RiskAssessmentAnswer,
    RiskOverrideDecision, SuitabilityCheck, current_investment_preference,
)
from models.review import AdvisoryLog
from schemas.profiling import (
    KnowledgeCreate, KnowledgeResponse,
    RiskAssessmentCreate, RiskAssessmentOverride, RiskAssessmentResponse,
    SuitabilityCheckCreate, SuitabilityCheckResponse,
    SustainabilityPreferenceCreate, SustainabilityPreferenceResponse, SustainabilityPreferenceState,
)
from core import sustainability_preference as sp
from core.evidence import evidence_hash
from core.reason_codes import DomainError, ReasonCode
from services.auth import get_client_for_user_or_404, get_current_user, get_mandate_for_user_or_404, require_advisor
from services.audit import log
from services.advisory_report_cache import invalidate_mandate as invalidate_advisory_cache
# Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): Quell-IP fuer FIDLEG-Eignungspruefungs-
# Datensaetze (Risikoprofil, Signatur, Suitability-Check).
from routers.auth import _extract_client_ip
# TEN-COMP-002 Teil 2 (Codex-Audit 2026-08-27, Folgefund zu PR #388):
# create_suitability_check() nahm recommendation_run_id/document_id bisher
# ungeprueft von einem fremden Mandat entgegen -- analog zu
# create_advisory_log_entry() in routers/review.py (Teil 1) werden diese
# beiden Helper hier wiederverwendet (sie sind bereits generisch: db+id+
# mandate_id, kein Router-State).
from routers.review import _get_document_or_404, _get_recommendation_run_or_404, customer_exclusion_options
from services.data_classification import enforce_data_classification
from services.portfolio_engine import (
    _current_risk_assessment_or_none,
    _current_target_allocation_or_none,
    risk_assessment_ready_for_strategy,
    run_exclusion_evidence_status,
)
from services.risk_scoring import canonicalize_horizon_label, compute_scores, profile_for_score_x10
from services.risk_questionnaire_integrity import (
    RiskQuestionnaireIntegrityError,
    validate_standard_submission,
)
from services.risk_capacity_plausibility import audit_if_inconsistent, evaluate_mandate_safely
from services import risk_capacity_evaluation_snapshot as rces
from services.risk_assessment_semantics import (
    OVERRIDE_DOCUMENTATION_RULES_VERSION,
    _optional_capacity_score,
    override_documentation_requirements,
)
from services.risk_override_decision import (
    SCHEMA_VERSION as RISK_OVERRIDE_DECISION_SCHEMA,
    compute_decision_hash,
    decision_snapshot,
)
from services import risk_profile_signoff as signoff_service
from services.pii_vault import PiiVaultError, seal_for_client

router = APIRouter(tags=["Risikoprofilierung"])
_logger = logging.getLogger(__name__)


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
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    enforce_data_classification(body.data_classification)
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
        client_id=client_id, ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(knowledge)
    return knowledge


# ── Risikoprofilierung ─────────────────────────────────────────────────────────

# PRIVACY-001: nach einem Loeschgesuch gesperrte Nachweise sind fuer die
# Beratung nicht mehr lesbar (Sperrarchiv, services/privacy_erasure.py).
_RISK_PROFILE_EVIDENCE = ("risk_profile_evidence",)
_PLAUSIBILITY_EVIDENCE = ("risk_capacity_plausibility_evidence",)


def _assert_privacy_readable(db: Session, mandate_id: str, evidence_types: tuple[str, ...]) -> None:
    from services.privacy_erasure import assert_evidence_readable

    assert_evidence_readable(db, evidence_types=evidence_types, mandate_id=mandate_id)


@router.get("/mandates/{mandate_id}/risk-assessments", response_model=list[RiskAssessmentResponse])
def list_risk_assessments(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    _assert_privacy_readable(db, mandate_id, _RISK_PROFILE_EVIDENCE)
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
    _assert_privacy_readable(db, mandate_id, _RISK_PROFILE_EVIDENCE)
    try:
        ra = _current_risk_assessment_or_none(db, mandate_id, eager_answers=True)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not ra:
        raise HTTPException(status_code=404, detail="Keine aktuelle Risikoprofilierung gefunden")
    return ra


@router.get("/mandates/{mandate_id}/risk-capacity-plausibility")
def get_risk_capacity_plausibility(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """RISK-CAPACITY-PLAUSIBILITY-001: Fragebogen-Angaben zur Risikofaehigkeit
    gegen die erfassten Finanzdaten. Reiner Hinweis -- aendert das Profil nicht,
    blockiert nichts."""
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    _assert_privacy_readable(db, mandate_id, _RISK_PROFILE_EVIDENCE + _PLAUSIBILITY_EVIDENCE)
    try:
        ra = _current_risk_assessment_or_none(db, mandate_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not ra:
        raise HTTPException(status_code=404, detail="Keine aktuelle Risikoprofilierung gefunden")
    captured: dict = {}
    result = evaluate_mandate_safely(db, mandate, ra, capture=captured)
    # RISK-CAPACITY-EVALUATION-SNAPSHOT-001: zuletzt gebundene Evidenz +
    # "neu zu pruefen", wenn sie nicht mehr der aktuellen Datenlage entspricht.
    if isinstance(result, dict):
        result["bound_evaluation"] = rces.bound_evaluation_status(
            db, mandate, rces.live_evaluation(db, mandate, ra, result=result, captured=captured),
        )
    return result


@router.get("/mandates/{mandate_id}/risk-capacity-plausibility/evaluations")
def list_risk_capacity_plausibility_evaluations(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """RISK-CAPACITY-EVALUATION-SNAPSHOT-001: gebundene, unveraenderliche
    Bewertungen (neueste zuerst) mit Replay (Hash, Regel-Nachrechnung,
    Aktualitaet). Betragsfrei; die Zeilen werden nie ueberschrieben."""
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    _assert_privacy_readable(db, mandate_id, _RISK_PROFILE_EVIDENCE + _PLAUSIBILITY_EVIDENCE)
    try:
        ra = _current_risk_assessment_or_none(db, mandate_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    live = rces.live_evaluation(db, mandate, ra)
    return {
        "schema_version": rces.SCHEMA_VERSION,
        "current_risk_assessment_id": live["assessment_id"],
        "evaluations": [
            rces.replay_snapshot(row, mandate, live) for row in rces.list_snapshots(db, mandate)
        ],
    }


@router.post("/mandates/{mandate_id}/risk-assessments", response_model=RiskAssessmentResponse, status_code=201)
def create_risk_assessment(
    mandate_id: str,
    body: RiskAssessmentCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    enforce_data_classification(body.data_classification)
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
    # O-1/O-2: nur Antworten aus dem Standard-Fragebogen; der Server leitet die
    # Punkte selbst aus den gewaehlten Optionen ab und lehnt Abweichungen ab
    # (kein stilles Korrigieren).
    try:
        validate_standard_submission(body)
    except RiskQuestionnaireIntegrityError as exc:
        raise HTTPException(status_code=422, detail=exc.as_detail()) from exc

    # Supersede previous (Race-Hardening, siehe ClientKnowledge oben).
    try:
        prev = _current_risk_assessment_or_none(
            db,
            mandate_id,
            for_update=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    prev_id = None
    prev_version = 0
    if prev:
        prev.is_current = 0
        prev.valid_to = today
        prev_id = prev.id
        prev_version = prev.version
        # Partial unique indexes are checked immediately.  Flush the old
        # RiskAssessment anchor first so SQLAlchemy cannot order the new
        # INSERT ahead of the superseding UPDATE within one unit of work.
        db.flush()

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

    # Store individual answers if provided. Unausgefuellte/leere Antwortzeilen
    # ueberspringen: das FE sendet teils nicht angeklickte (Zusatz-)Fragen mit
    # NULL-Werten mit. Die Spalten question_number/answer_label/answer_points sind
    # NOT NULL -> sonst IntegrityError -> 500 ("Interner Serverfehler") beim
    # Speichern. Konsistent mit dem Vollstaendigkeits-Gate, das solche
    # unvollstaendigen Antworten ohnehin ignoriert.
    if body.answers:
        for ans in body.answers:
            question_number = ans.get("question_number")
            answer_label = ans.get("answer_label")
            answer_points = ans.get("answer_points")
            if question_number is None or answer_points is None:
                continue
            if answer_label is None or not str(answer_label).strip():
                continue
            db.add(RiskAssessmentAnswer(
                id=new_uuid(),
                assessment_id=ra.id,
                question_number=question_number,
                question_section=_canonical_risk_answer_section(
                    question_number,
                    ans.get("question_section"),
                ),
                answer_label=answer_label,
                answer_points=answer_points,
                created_at=now,
            ))

    # CON-001 (Codex-Audit 2026-08-25): with_for_update() oben serialisiert
    # zwei parallele Create-Aufrufe korrekt unter Postgres, ist aber unter
    # SQLite ein stiller No-Op (SQLAlchemy-Dialekt unterstuetzt FOR UPDATE
    # dort nicht) -- zwei nahezu gleichzeitige Requests koennen den
    # Partial-Unique-Index (genau ein is_current=1 pro Mandat) trotzdem
    # treffen. Der Verlierer bekam bisher einen rohen IntegrityError -> 500
    # statt eines sauberen 409. log() unten fuehrt selbst eine Query aus,
    # die einen Autoflush der noch ausstehenden INSERT ausloesen kann --
    # der try-Block muss deshalb log() mit umfassen, nicht nur commit().
    try:
        log(db, user_id=current_user.id, user_name=current_user.full_name,
            table_name="risk_assessments", record_id=ra.id, action="CREATE",
            mandate_id=mandate_id, client_id=mandate.client_id,
            ip_address=_extract_client_ip(request))
        # RISK-CAPACITY-PLAUSIBILITY-001: Widerspruch Fragebogen <-> erfasste
        # Finanzdaten wird protokolliert (aendert das Profil nicht).
        # RISK-CAPACITY-EVALUATION-SNAPSHOT-001: dieselbe Bewertung wird als
        # unveraenderliche Evidenz an das gespeicherte Profil gebunden.
        captured: dict = {}
        plausibility = evaluate_mandate_safely(db, mandate, ra, capture=captured)
        rces.record_snapshot(
            db, mandate, ra, plausibility, captured, actor=current_user,
            binding_context=rces.CONTEXT_RISK_ASSESSMENT_SAVED, binding_record_id=ra.id,
        )
        audit_if_inconsistent(
            db, plausibility,
            user=current_user, table_name="risk_assessments", record_id=ra.id,
            mandate=mandate, ip_address=_extract_client_ip(request),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # RISK-PROFILE-SCHEMA-PARITY-001: eine CHECK-Verletzung ist ein
        # Schema-Defekt, kein paralleles Speichern -- nicht als 409 melden.
        if _is_check_violation(exc):
            _logger.error("Risikoprofil verletzt CHECK-Constraint: %s", exc.orig)
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "RISK_PROFILE_CHECK_VIOLATION",
                    "message": "Das Risikoprofil passt nicht zum Datenbankschema dieser Installation. Bitte den Support kontaktieren.",
                },
            ) from exc
        raise HTTPException(
            status_code=409,
            detail="Ein anderes Risikoprofil wurde gleichzeitig gespeichert -- bitte Seite neu laden und erneut versuchen.",
        )
    invalidate_advisory_cache(mandate_id)
    return db.query(RiskAssessment).options(
        selectinload(RiskAssessment.answers)
    ).filter(RiskAssessment.id == ra.id).one()


def _is_check_violation(exc: IntegrityError) -> bool:
    """CHECK-Verletzung (SQLite-Meldung bzw. PostgreSQL SQLSTATE 23514 mit Constraint-Namen)."""
    orig = getattr(exc, "orig", None)
    if "CHECK constraint failed" in str(orig):
        return True
    diag = getattr(orig, "diag", None)
    return getattr(orig, "pgcode", None) == "23514" and bool(getattr(diag, "constraint_name", None))


@router.post("/mandates/{mandate_id}/risk-assessments/{ra_id}/override",
             response_model=RiskAssessmentResponse)
def override_risk_assessment(
    mandate_id: str,
    ra_id: str,
    body: RiskAssessmentOverride,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    # RISK-OVERRIDE-WRITE-BOUNDARY-001 Restbefund A (Codex-Closure-Review zu
    # PR #646): Row-Lock (PostgreSQL; unter SQLite serialisiert der
    # Datei-Lock beim Schreiben) + Current-Gate. Eine historische Version ist
    # unveraenderliche Evidence -- sie wird nie in-place uebersteuert.
    ra = db.query(RiskAssessment).filter(
        RiskAssessment.id == ra_id,
        RiskAssessment.mandate_id == mandate_id,
        RiskAssessment.deleted_at.is_(None)
    ).with_for_update().first()
    if not ra:
        raise HTTPException(status_code=404, detail="Risikoprofilierung nicht gefunden")
    if int(ra.is_current or 0) != 1:
        current = db.query(RiskAssessment.id).filter(
            RiskAssessment.mandate_id == mandate_id,
            RiskAssessment.is_current == 1,
            RiskAssessment.deleted_at.is_(None),
        ).first()
        _override_conflict(
            "RISK_ASSESSMENT_NOT_CURRENT",
            "Nur das aktuelle Risikoprofil kann uebersteuert werden; diese Version "
            "ist historisch. Bitte die aktuelle Version laden.",
            assessment_id=ra.id,
            current_assessment_id=current[0] if current else None,
        )
    if (
        body.expected_assessment_version is not None
        and int(body.expected_assessment_version) != int(ra.version or 0)
    ):
        _override_conflict(
            "RISK_ASSESSMENT_VERSION_CONFLICT",
            "Das Risikoprofil wurde inzwischen neu erfasst -- bitte Seite neu laden.",
            assessment_id=ra.id,
            current_assessment_version=int(ra.version or 0),
        )
    if (
        "expected_override_decision_id" in body.model_fields_set
        and body.expected_override_decision_id != ra.override_decision_id
    ):
        _override_conflict(
            "RISK_OVERRIDE_DECISION_CONFLICT",
            "Der Override wurde inzwischen von jemand anderem geaendert -- bitte "
            "Seite neu laden und erneut entscheiden.",
            assessment_id=ra.id,
            current_override_decision_id=ra.override_decision_id,
        )
    legacy_snapshot = _legacy_remediation_precheck(ra, body)
    if str(mandate.mandate_type or "").strip().upper() == "FZK" and int(body.override_score_x10 or 0) > 75:
        raise HTTPException(
            status_code=422,
            detail="FZK-Mandat: Override-Score darf 75 (= 7.5/10) nicht überschreiten (FIDLEG).",
        )
    # RISK-OVERRIDE-WRITE-BOUNDARY-001: dieselbe Regel wie Strategie-Gate und
    # Domain-Validierung, VOR jeder Mutation -- ein unvollstaendig
    # dokumentierter Override wird nie persistiert (422, kein Audit-Log).
    basis_final = int(ra.final_score_x10 or 0)
    basis_capacity = _optional_capacity_score(ra)
    needs_confirmation, needs_warning = override_documentation_requirements(
        final_score_x10=basis_final,
        override_score_x10=int(body.override_score_x10),
        risk_capacity_score_x10=basis_capacity,
    )
    if needs_confirmation and not body.override_client_confirmed:
        raise HTTPException(
            status_code=422,
            detail="Ein Override nach oben erfordert die dokumentierte Bestaetigung des ausdruecklichen Kundenwunsches.",
        )
    if needs_warning and not body.override_warning_delivered:
        raise HTTPException(
            status_code=422,
            detail=(
                "Ein Override ueber die Risikofaehigkeit oder um mindestens zwei "
                "Profilbaender nach oben erfordert einen dokumentierten Warnhinweis."
            ),
        )

    # Restbefund B: append-only RiskOverrideDecisionV1, gebunden an die
    # validierte Basis und die damals effektiven Requirements.
    now = _now()
    previous_decision_id = ra.override_decision_id
    assessment_version = int(ra.version or 0)
    # DSG-ERASURE-APPEND-ONLY-001: die append-only Decision (und damit der
    # Audit-Snapshot) traegt die Begruendung nur versiegelt (Crypto-Shredding
    # bei DSG-Art.-32-Loeschung, services/pii_vault.py); die veraenderbare
    # Projektion am Assessment bleibt lesbar (PDF/Monolith) und wird von der
    # Erasure redigiert. Fail-closed VOR jeder Mutation.
    try:
        sealed_reason = seal_for_client(db, mandate.client_id, body.override_reason)
    except PiiVaultError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    sequence_no = int(
        db.query(func.max(RiskOverrideDecision.sequence_no))
        .filter(RiskOverrideDecision.assessment_id == ra.id)
        .scalar() or 0
    ) + 1
    decision = RiskOverrideDecision(
        id=new_uuid(),
        schema_version=RISK_OVERRIDE_DECISION_SCHEMA,
        assessment_id=ra.id,
        mandate_id=mandate_id,
        client_id=mandate.client_id,
        # PG-002 (Codex-Closure-Review PR #662): Mandant aus dem validierten
        # Mandat; Teil des V2-Hashes, DB-Trigger prueft/erzwingt ihn.
        tenant_id=mandate.tenant_id,
        assessment_version=assessment_version,
        sequence_no=sequence_no,
        previous_decision_id=previous_decision_id,
        basis_final_score_x10=basis_final,
        basis_final_profile=ra.final_profile,
        basis_capacity_score_x10=basis_capacity,
        basis_willingness_score_x10=ra.risk_willingness_score_x10,
        requested_score_x10=int(body.override_score_x10),
        requested_profile=body.override_profile,
        reason=sealed_reason,
        client_confirmed=1 if body.override_client_confirmed else 0,
        warning_delivered=1 if body.override_warning_delivered else 0,
        warning_document_id=body.override_warning_document_id,
        required_client_confirmation=1 if needs_confirmation else 0,
        required_warning=1 if needs_warning else 0,
        actor_id=current_user.id,
        decided_at=now,
        rules_version=OVERRIDE_DOCUMENTATION_RULES_VERSION,
        created_at=now,
    )
    decision.decision_hash = compute_decision_hash(decision)

    # Compare-and-Swap: is_current, Version und bisheriger Decision-Pointer
    # werden unmittelbar beim Schreiben erneut geprueft. Hat sich die Basis
    # seit dem Laden geaendert (neue Assessment-Version, paralleler
    # Re-Override, Loeschung), trifft das UPDATE keine Zeile -> 409.
    pointer_filter = (
        RiskAssessment.override_decision_id.is_(None)
        if previous_decision_id is None
        else RiskAssessment.override_decision_id == previous_decision_id
    )
    updated = db.query(RiskAssessment).filter(
        RiskAssessment.id == ra.id,
        RiskAssessment.mandate_id == mandate_id,
        RiskAssessment.deleted_at.is_(None),
        RiskAssessment.is_current == 1,
        RiskAssessment.version == assessment_version,
        pointer_filter,
    ).update({
        RiskAssessment.is_overridden: 1,
        RiskAssessment.override_score_x10: decision.requested_score_x10,
        RiskAssessment.override_profile: decision.requested_profile,
        RiskAssessment.override_by: current_user.id,
        RiskAssessment.override_at: now,
        RiskAssessment.override_reason: body.override_reason,
        RiskAssessment.override_client_confirmed: decision.client_confirmed,
        RiskAssessment.override_warning_delivered: decision.warning_delivered,
        RiskAssessment.override_warning_document_id: decision.warning_document_id,
        RiskAssessment.override_decision_id: decision.id,
        RiskAssessment.override_decision_hash: decision.decision_hash,
        RiskAssessment.updated_at: now,
        # RISK-PROFILE-SIGNOFF-001 Restbefund A: im SELBEN CAS wird eine
        # vorhandene Signatur ungueltig -- sie galt dem frueheren wirksamen
        # Profil. Der alte RiskProfileSignoffV1 bleibt append-only stehen.
        **{
            getattr(RiskAssessment, column): value
            for column, value in signoff_service.invalidation_values(now).items()
        },
    }, synchronize_session=False)
    if updated != 1:
        db.rollback()
        _override_conflict(
            "RISK_OVERRIDE_CONCURRENT_MODIFICATION",
            "Das Risikoprofil wurde waehrend der Speicherung geaendert -- bitte "
            "Seite neu laden und erneut versuchen.",
            assessment_id=ra_id,
        )

    try:
        db.add(decision)
        # Audit-Log: replaybarer Snapshot inkl. Decision-ID/-Hash statt nur
        # des Profilnamens.
        override_audit = decision_snapshot(decision)
        if legacy_snapshot is not None:
            override_audit["audit_reason"] = LEGACY_REMEDIATION
        log(db, user_id=current_user.id, user_name=current_user.full_name,
            table_name="risk_assessments", record_id=ra_id, action="UPDATE",
            field_name="override",
            new_value=json.dumps(override_audit, ensure_ascii=False),
            mandate_id=mandate_id, client_id=mandate.client_id,
            ip_address=_extract_client_ip(request))
        if legacy_snapshot is not None:
            # RISK-OVERRIDE-LEGACY-REMEDIATION-001: Altwerte replaybar neben
            # der neuen Decision -- die Decision selbst traegt den heutigen
            # Zeitstempel (keine Rueckdatierung auf legacy_override_at).
            log(db, user_id=current_user.id, user_name=current_user.full_name,
                table_name="risk_assessments", record_id=ra_id, action="UPDATE",
                field_name=LEGACY_REMEDIATION,
                new_value=json.dumps({
                    "audit_reason": LEGACY_REMEDIATION,
                    "decision_id": decision.id,
                    "decision_hash": decision.decision_hash,
                    "decided_at": decision.decided_at,
                    **legacy_snapshot,
                }, ensure_ascii=False),
                mandate_id=mandate_id, client_id=mandate.client_id,
                ip_address=_extract_client_ip(request))
        # Signoff-Invalidierung replaybar: bisherige (Alt-)Signatur + neue
        # Decision, Status signature_required.
        if signoff_service.had_signature(ra):
            log(db, user_id=current_user.id, user_name=current_user.full_name,
                table_name="risk_assessments", record_id=ra_id, action="UPDATE",
                field_name="client_signed_invalidated",
                new_value=signoff_service.invalidation_audit_value(
                    ra, decision_id=decision.id, decision_hash=decision.decision_hash,
                    db=db, client_id=mandate.client_id,
                ),
                mandate_id=mandate_id, client_id=mandate.client_id,
                ip_address=_extract_client_ip(request))
        db.commit()
    except IntegrityError:
        # Paralleler Append mit derselben sequence_no (ux_risk_override_
        # decision_sequence) -- genau ein Gewinner, der Verlierer bekommt 409.
        db.rollback()
        _override_conflict(
            "RISK_OVERRIDE_CONCURRENT_MODIFICATION",
            "Ein anderer Override wurde gleichzeitig gespeichert -- bitte Seite "
            "neu laden und erneut entscheiden.",
            assessment_id=ra_id,
        )
    db.refresh(ra)
    invalidate_advisory_cache(mandate_id)
    return ra


LEGACY_REMEDIATION = "legacy_remediation"


def _legacy_remediation_precheck(ra: RiskAssessment, body: RiskAssessmentOverride) -> dict | None:
    """RISK-OVERRIDE-LEGACY-REMEDIATION-001: Vorpruefung VOR jeder Mutation.

    Nur ein echter Altbestand-Override (is_overridden=1, kein Decision-
    Pointer) darf remediiert werden (sonst 409); die Remediation bestaetigt
    denselben Score (eine Aenderung ist ein normaler Override, sonst 422).
    Liefert die Altwerte fuer den Audit-Eintrag, None ohne Remediation."""
    if body.remediation != LEGACY_REMEDIATION:
        return None
    if int(ra.is_overridden or 0) != 1 or ra.override_score_x10 is None or ra.override_decision_id:
        _override_conflict(
            "RISK_OVERRIDE_NOT_LEGACY",
            "Kein Override aus dem Altbestand ohne Decision-Nachweis -- eine "
            "Altbestand-Bestaetigung ist hier nicht moeglich. Bitte Seite neu laden.",
            assessment_id=ra.id,
            current_override_decision_id=ra.override_decision_id,
        )
    if int(body.override_score_x10) != int(ra.override_score_x10):
        raise HTTPException(
            status_code=422,
            detail=(
                "Die Altbestand-Bestaetigung uebernimmt den bestehenden Override-Score "
                f"({int(ra.override_score_x10)}). Fuer einen anderen Score bitte einen "
                "normalen Override erfassen."
            ),
        )
    return {
        "legacy_override_score_x10": int(ra.override_score_x10),
        "legacy_override_profile": ra.override_profile,
        "legacy_override_reason": ra.override_reason,
        "legacy_override_client_confirmed": int(ra.override_client_confirmed or 0),
        "legacy_override_warning_delivered": int(ra.override_warning_delivered or 0),
        "legacy_override_warning_document_id": ra.override_warning_document_id,
        "legacy_override_by": ra.override_by,
        "legacy_override_at": ra.override_at,
    }


def _override_conflict(reason_code: str, message: str, **context) -> None:
    raise HTTPException(
        status_code=409,
        detail={"reason_code": reason_code, "message": message, **context},
    )


class RiskProfileSignRequest(BaseModel):
    note: str | None = None
    # RISK-PROFILE-SIGNOFF-001: optionale Erwartungswerte (Optimistic
    # Concurrency wie beim Override) + optional das signierte Dokument.
    expected_assessment_version: int | None = None
    expected_override_decision_id: str | None = None
    expected_signoff_id: str | None = None
    document_id: str | None = None


@router.post("/mandates/{mandate_id}/risk-profile/sign")
def sign_risk_profile(
    mandate_id: str,
    request: Request,
    body: RiskProfileSignRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    """FIDLEG-Eignungspruefung: Berater erfasst die Bestaetigung des aktuellen
    Risikoprofils (Fallback A, Methode 'advisor_recorded' = Beweisniveau
    'advisor_attested', KEINE elektronische Kundensignatur). Reine
    DOKUMENTATION -- aendert die Eignungs-Konformitaet (Audit is_compliant)
    NICHT.

    RISK-PROFILE-SIGNOFF-001: schreibt einen append-only RiskProfileSignoffV1,
    gebunden an Assessment-Version, wirksames Profil und die verifizierte
    Override-Decision (oder 'no_override'). Nicht verifizierbare Decision,
    veraltete Erwartungswerte oder ein paralleler Override -> 409 vor jeder
    Wirkung."""
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    body = body or RiskProfileSignRequest()
    fields = body.model_fields_set
    result = signoff_service.record_signoff(
        db,
        mandate=mandate,
        actor=current_user,
        method=signoff_service.METHOD_ADVISOR,
        note=body.note,
        ip_address=_extract_client_ip(request),
        document_id=body.document_id,
        expected_assessment_version=body.expected_assessment_version,
        expect_override_decision="expected_override_decision_id" in fields,
        expected_override_decision_id=body.expected_override_decision_id,
        expect_signoff="expected_signoff_id" in fields,
        expected_signoff_id=body.expected_signoff_id,
    )
    invalidate_advisory_cache(mandate_id)
    return result


# ── Suitability Checks ─────────────────────────────────────────────────────────

# TEN-COMP-002 Teil 2 (Codex-Audit 2026-08-27): dieselbe Bugklasse wie in
# routers/review.py::create_advisory_log_entry (Teil 1, PR #388) -- eine
# Geeignetheitspruefung konnte bisher recommendation_run_id, advisory_log_id,
# knowledge_assessment_id, risk_assessment_id und document_id eines FREMDEN
# Mandats referenzieren (jeder Berater mit >=2 Mandaten, auch auf einer
# einzelnen SQLite-Installation ohne Tenant-Konzept). Jede angegebene ID wird
# jetzt vor dem Anlegen gegen dasselbe Mandat (bzw. bei knowledge_assessment_id
# gegen denselben Client, siehe ClientKnowledge-Docstring in models/profiling.py)
# geprueft. recommendation_run_id/document_id nutzen die bereits generischen
# Helper aus routers/review.py; fuer advisory_log_id/risk_assessment_id/
# knowledge_assessment_id gibt es dort keine passenden Helper -- lokale
# Mirrors nach demselben Muster (404, kein 403, um Existenz nicht zu leaken).

def _get_advisory_log_or_404(mandate_id: str, log_id: str, db: Session) -> AdvisoryLog:
    entry = db.query(AdvisoryLog).filter(
        AdvisoryLog.id == log_id,
        AdvisoryLog.mandate_id == mandate_id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Beratungsprotokoll-Eintrag nicht gefunden")
    return entry


def _risk_assessment_documents_knowledge(assessment: RiskAssessment | None) -> bool:
    """ELIG-KNOWLEDGE-001: True wenn das Risikoprofil mindestens einen
    Instrument-Eintrag mit dokumentierter Kenntnis oder Aufklaerung traegt."""
    if assessment is None:
        return False
    try:
        instruments = json.loads(assessment.knowledge_instruments_json or "{}")
    except (TypeError, ValueError):
        return False
    if not isinstance(instruments, dict):
        return False
    return any(
        isinstance(entry, dict) and (entry.get("known") or entry.get("informed"))
        for entry in instruments.values()
    )


def _get_risk_assessment_or_404(mandate_id: str, assessment_id: str, db: Session) -> RiskAssessment:
    assessment = db.query(RiskAssessment).filter(
        RiskAssessment.id == assessment_id,
        RiskAssessment.mandate_id == mandate_id,
        RiskAssessment.deleted_at.is_(None),
    ).first()
    if not assessment:
        raise HTTPException(status_code=404, detail="Risikoprofil nicht gefunden")
    return assessment


def _get_knowledge_assessment_or_404(client_id: str, knowledge_id: str, db: Session) -> ClientKnowledge:
    # ClientKnowledge haengt am Client, nicht am Mandat (ein Client kann
    # mehrere Mandate haben) -- Scoping daher gegen mandate.client_id statt
    # mandate_id, sonst wuerde eine legitime Kenntnis-Erfassung desselben
    # Kunden unter einem anderen seiner Mandate faelschlich abgelehnt.
    knowledge = db.query(ClientKnowledge).filter(
        ClientKnowledge.id == knowledge_id,
        ClientKnowledge.client_id == client_id,
        ClientKnowledge.deleted_at.is_(None),
    ).first()
    if not knowledge:
        raise HTTPException(status_code=404, detail="Kenntnisse & Erfahrungen-Erfassung nicht gefunden")
    return knowledge


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
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    enforce_data_classification(body.data_classification)
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    now = _now()
    # TEN-COMP-002 Teil 2: Evidence-Anker muessen alle zum SELBEN Mandat
    # (bzw. Client, bei knowledge_assessment_id) gehoeren -- siehe Kommentar
    # oberhalb der Helper-Funktionen.
    if body.recommendation_run_id:
        _get_recommendation_run_or_404(mandate_id, body.recommendation_run_id, db, current_user)
    if body.advisory_log_id:
        _get_advisory_log_or_404(mandate_id, body.advisory_log_id, db)
    if body.knowledge_assessment_id:
        _get_knowledge_assessment_or_404(mandate.client_id, body.knowledge_assessment_id, db)
    risk_anchor = (
        _get_risk_assessment_or_404(mandate_id, body.risk_assessment_id, db)
        if body.risk_assessment_id else None
    )
    if (
        body.result == "Angemessen"
        and not body.knowledge_assessment_id
        and not _risk_assessment_documents_knowledge(risk_anchor)
    ):
        # ELIG-KNOWLEDGE-001: ein Risikoprofil ist nur dann Kenntnis-Anker,
        # wenn es tatsaechlich dokumentierte Kenntnisse/Erfahrungen enthaelt.
        raise HTTPException(status_code=422, detail=(
            "Positives Angemessenheits-Ergebnis ohne Kenntnis-Nachweis: das "
            "referenzierte Risikoprofil enthaelt keine dokumentierten "
            "Kenntnisse & Erfahrungen. Kenntnisse erfassen oder das Ergebnis "
            "'Unvollständige Information' waehlen."
        ))
    if body.document_id:
        _get_document_or_404(mandate_id, body.document_id, db)
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
        mandate_id=mandate_id, client_id=mandate.client_id,
        ip_address=_extract_client_ip(request))
    db.commit()
    db.refresh(check)
    invalidate_advisory_cache(mandate_id)
    return check


# ── E2a Nachhaltigkeitspraeferenzen im Risikoprofil-Flow (Dok. 106) ──────────
# Kundenfragebogen direkt nach dem Risikoprofil. Versioniert je Mandat
# (append-only InvestmentPreferenceDecisionV1), Texte/Ableitung aus
# core/sustainability_preference.py, Zustand aus
# services/recommendation_release_gate.py::preference_state. Keine Engine-Wirkung und kein
# Einfluss auf Risikoscore, Ziele, Monte-Carlo oder Allokation (Mutationstest).
# Ausschlusswuensche nur, wenn sie belegt erfuellbar sind (E2b: Abdeckung im
# aktiven Produktuniversum, sonst 422 fail-closed); Wirkung nur als Untergrenze
# der Strategiebausteine (Fachvertrag E2b).
_SUITABILITY_EVIDENCE = ("suitability_evidence",)


def _exclusion_options(db: Session, mandate: Mandate) -> list[dict]:
    """E2b: waehlbar nur mit belegter Abdeckung im aktiven Produktuniversum
    (routers/review.py::customer_exclusion_options); sonst ausgegraut mit Grund."""
    return customer_exclusion_options(db, mandate)


def _allocation_floor(db: Session, mandate: Mandate, row) -> dict:
    """E2b / N-888-01: haelt die aktuelle Soll-Allokation die Ausschluesse ein?"""
    try:
        ta = _current_target_allocation_or_none(db, mandate.id)
    except ValueError:
        ta = None
    decision = None if row is None else {
        "id": row.id, "exclusions_json": row.exclusions_json, "decision_hash": row.decision_hash,
    }
    floor = sp.evaluate_floor(decision, getattr(ta, "preferences_json", None), has_strategy=ta is not None)
    # N-901-02: gezeigter Lauf (Final vor Draft), heute neu bewertet.
    run_id = None if ta is None else db.execute(
        text(sp.CURRENT_RUN_SQL), {"mandate_id": mandate.id, "target_allocation_id": ta.id},
    ).scalar()
    floor["evidence"] = run_exclusion_evidence_status(db, mandate, run_id)
    return floor


def _sustainability_response(row: InvestmentPreferenceDecision, floor: dict | None = None) -> SustainabilityPreferenceResponse:
    try:
        exclusions = list(json.loads(row.exclusions_json or "[]"))
    except (TypeError, ValueError) as exc:
        raise DomainError(
            ReasonCode.SUSTAINABILITY_PREFERENCE_UNREADABLE,
            "Gespeicherte Nachhaltigkeitspräferenz ist nicht lesbar.",
            http_status=409,
        ) from exc
    return SustainabilityPreferenceResponse(
        id=row.id,
        schema_version=row.schema_version,
        mandate_id=row.mandate_id,
        sequence_no=int(row.sequence_no),
        supersedes_id=row.supersedes_id,
        questionnaire_version=row.questionnaire_version,
        definition_hash=row.definition_hash,
        derivation_version=row.derivation_version,
        response_status=row.response_status,
        esg_relevance=row.esg_relevance,
        esg_characteristic=row.esg_characteristic,
        exclusions=exclusions,
        preference_waived=bool(row.preference_waived),
        profile_code=row.profile_code,
        profile_text=sp.PROFILE_TEXTS.get(row.profile_code, ""),
        limit_texts=sp.limit_texts(row.profile_code) + sp.exclusion_limit_texts(
            exclusions, (floor or {}).get("status"), (floor or {}).get("evidence"),
        ),
        information_acknowledged=bool(row.information_acknowledged),
        client_confirmed=bool(row.client_confirmed),
        capture_channel=row.capture_channel,
        mandate_type_at_capture=row.mandate_type_at_capture,
        review_policy_version=row.review_policy_version,
        review_policy_months=int(row.review_policy_months),
        review_due_on=row.review_due_on,
        captured_by=row.captured_by,
        captured_at=row.captured_at,
        decision_hash=row.decision_hash,
    )


def _row_fields(row: InvestmentPreferenceDecision) -> dict:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _preference_state(db: Session, mandate: Mandate, *, decision=None) -> dict:
    """Ein Zustand (core/sustainability_preference.py::load_state), dieselbe
    Logik wie Gates und PDF (services/recommendation_release_gate.py)."""
    return sp.load_state(
        lambda sql, params: db.execute(text(sql), params).mappings().first(),
        lambda sql, params: db.execute(text(sql), params).scalar(),
        evidence_hash,
        mandate_id=mandate.id,
        tenant_id=getattr(mandate, "tenant_id", None),
        mandate_type=mandate.mandate_type,
        today_iso=date.today().isoformat(),
        decision=decision,
        decision_loaded=True,
    )


def _sustainability_state(db: Session, mandate: Mandate) -> SustainabilityPreferenceState:
    rows = (
        db.query(InvestmentPreferenceDecision)
        .filter(InvestmentPreferenceDecision.mandate_id == mandate.id)
        .order_by(InvestmentPreferenceDecision.sequence_no.desc())
        .all()
    )
    floor = _allocation_floor(db, mandate, rows[0] if rows else None)
    floor_decision = {"exclusions_json": rows[0].exclusions_json} if rows else None
    history = [_sustainability_response(row, floor if index == 0 else None) for index, row in enumerate(rows)]
    current = history[0] if history else None
    info = _preference_state(db, mandate, decision=_row_fields(rows[0]) if rows else None)
    status = sp.review_status(current.review_due_on if current else None, date.today().isoformat())
    return SustainabilityPreferenceState(
        current=current,
        history=history,
        state=info["state"],
        state_label=info["label"],
        answer_state=info["answer_state"],
        stale_reasons=list(info["stale_reasons"]),
        state_notice=info["notice"],
        review_status=status,
        review_notice=sp.review_due_text(current.review_due_on) if status == sp.REVIEW_DUE else None,
        review_policy_months=info["review_months"],
        review_policy_label=sp.review_policy_label(info["review_months"]),
        waiver_allowed=str(mandate.mandate_type or "") == sp.WAIVER_MANDATE_TYPE,
        exclusion_options=_exclusion_options(db, mandate),
        document_binding=info["binding"],
        allocation_floor_status=floor["status"],
        allocation_floor_themes=list(floor.get("themes") or ()),
        allocation_stale_notice=sp.floor_stale_notice(floor) or (
            sp.run_evidence_message(floor_decision, "recommendation")
            if floor.get("evidence") == sp.RUN_EVIDENCE_MISSING else None
        ),
    )


@router.get("/sustainability-preferences/definition")
def get_sustainability_preference_definition(current_user: User = Depends(get_current_user)):
    """Versionierte Fragebogen-Definition (Texte, Optionen, Ableitung) mit
    Definitions-Hash. Die Anzeigetexte sind Entwurf (Compliance-Freigabe offen)."""
    return {**sp.definition(), "definition_hash": sp.definition_hash()}


@router.get(
    "/mandates/{mandate_id}/sustainability-preferences",
    response_model=SustainabilityPreferenceState,
)
def get_sustainability_preferences(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aktuelle Nachhaltigkeitspraeferenz, Historie (neueste zuerst),
    Pflichtzustand und anbietbare Ausschlusswuensche."""
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    _assert_privacy_readable(db, mandate_id, _SUITABILITY_EVIDENCE)
    return _sustainability_state(db, mandate)


def _sustainability_error(message: str, code=ReasonCode.SUSTAINABILITY_PREFERENCE_INVALID, status=422,
                          detail: str | None = None):
    return DomainError(code, message, http_status=status, extra={"detail": detail} if detail else None)


def _validated_waiver(body: SustainabilityPreferenceCreate, mandate: Mandate) -> str | None:
    reason = str(body.waiver_reason or "").strip()
    if not body.preference_waived:
        if reason:
            raise _sustainability_error("Begründung nur bei dokumentiertem Verzicht.",
                                        ReasonCode.SUSTAINABILITY_WAIVER_INVALID)
        return None
    if str(mandate.mandate_type or "") != sp.WAIVER_MANDATE_TYPE:
        raise _sustainability_error(sp.WAIVER_NOT_ALLOWED_TEXT, ReasonCode.SUSTAINABILITY_WAIVER_NOT_ALLOWED, 409)
    if body.esg_relevance != sp.RELEVANCE_YES:
        raise _sustainability_error("Ein Verzicht setzt Frage 1 = «Ja» voraus.",
                                    ReasonCode.SUSTAINABILITY_WAIVER_INVALID)
    if len(reason) < sp.WAIVER_REASON_MIN_LENGTH:
        raise _sustainability_error(
            f"Begründung des Verzichts: mindestens {sp.WAIVER_REASON_MIN_LENGTH} Zeichen.",
            ReasonCode.SUSTAINABILITY_WAIVER_INVALID,
        )
    return reason


def _assert_exclusions_offerable(db: Session, mandate: Mandate, exclusions: list) -> None:
    """Nur Erfuellbares anbieten (serverseitig, fail-closed)."""
    if not exclusions:
        return
    # N-901-03: die gewaehlten Ausschluesse muessen ZUSAMMEN am selben Produkt
    # erfuellbar sein (plus die Restriktionen der aktuellen Strategie).
    options = {o["key"]: o for o in customer_exclusion_options(db, mandate, exclusions)}
    blocked = [key for key in exclusions if not options.get(key, {}).get("available")]
    if blocked:
        labels = ", ".join(sp.exclusion_labels(blocked))
        reasons = "; ".join(
            f"{sp.EXCLUSION_LABELS[key]}: {options.get(key, {}).get('reason') or sp.EXCLUSION_LOCKED_REASON}"
            for key in blocked
        )
        raise _sustainability_error(
            f"Ausschluss nicht wählbar ({labels}). Einstellung: Frage 3. "
            "Bitte abwählen oder belegte Produkte ins Produktuniversum aufnehmen.",
            ReasonCode.SUSTAINABILITY_OPTION_NOT_OFFERABLE,
            detail=reasons,
        )


@router.post(
    "/mandates/{mandate_id}/sustainability-preferences",
    response_model=SustainabilityPreferenceState,
    status_code=201,
)
def create_sustainability_preference(
    mandate_id: str,
    body: SustainabilityPreferenceCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    """Neue Version der Nachhaltigkeitspraeferenz (append-only)."""
    enforce_data_classification(body.data_classification)
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    if body.questionnaire_version != sp.QUESTIONNAIRE_VERSION or body.definition_hash != sp.definition_hash():
        raise _sustainability_error(
            "Der Fragebogen wurde inzwischen geändert. Bitte die Maske neu laden und erneut erfassen.",
            ReasonCode.SUSTAINABILITY_DEFINITION_OUTDATED, 409,
        )
    try:
        profile_code = sp.derive_profile(body.response_status, body.esg_relevance, body.esg_characteristic)
        exclusions = sp.normalize_exclusions(body.exclusions)
    except ValueError as exc:
        raise _sustainability_error(str(exc)) from exc
    is_yes = body.esg_relevance == sp.RELEVANCE_YES
    if exclusions and not is_yes:
        raise _sustainability_error("Ausschlusswünsche setzen Frage 1 = «Ja» voraus.")
    waiver_reason = _validated_waiver(body, mandate)
    if waiver_reason and exclusions:
        raise _sustainability_error(
            "Verzicht und Ausschlusswünsche schliessen sich aus. Bitte eines davon abwählen.",
            ReasonCode.SUSTAINABILITY_WAIVER_INVALID,
        )
    if is_yes and not body.information_acknowledged:
        raise _sustainability_error(
            "Bitte die Kenntnisnahme der Information dokumentieren.",
            ReasonCode.SUSTAINABILITY_INFORMATION_REQUIRED,
        )
    if not is_yes and body.information_acknowledged:
        raise _sustainability_error("Die Kenntnisnahme gehört nur zur Antwort «Ja».")
    # N-888-03: ohne Bestaetigung der Kundin bzw. des Kunden keine Erfassung.
    if not body.client_confirmed:
        raise _sustainability_error(
            "Bitte die Bestätigung der Angaben durch die Kundin bzw. den Kunden dokumentieren.",
            ReasonCode.SUSTAINABILITY_CONFIRMATION_REQUIRED,
        )
    _assert_exclusions_offerable(db, mandate, exclusions)
    previous = current_investment_preference(db, mandate.id)
    if (previous.id if previous else None) != body.expected_current_id:
        raise _sustainability_error(
            "Die Nachhaltigkeitspräferenz wurde inzwischen geändert. Bitte neu laden.",
            ReasonCode.SUSTAINABILITY_PREFERENCE_CONFLICT, 409,
        )
    sealed = None
    if waiver_reason:
        try:
            sealed = seal_for_client(db, mandate.client_id, waiver_reason)
        except PiiVaultError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    now = _now()
    months = _preference_state(db, mandate)["review_months"]
    row = InvestmentPreferenceDecision(
        id=new_uuid(),
        schema_version=sp.SCHEMA_VERSION,
        tenant_id=getattr(mandate, "tenant_id", None),
        mandate_id=mandate.id,
        client_id=mandate.client_id,
        sequence_no=(int(previous.sequence_no) + 1) if previous else 1,
        supersedes_id=previous.id if previous else None,
        questionnaire_version=sp.QUESTIONNAIRE_VERSION,
        definition_hash=sp.definition_hash(),
        derivation_version=sp.DERIVATION_VERSION,
        response_status=body.response_status,
        esg_relevance=body.esg_relevance,
        esg_characteristic=body.esg_characteristic,
        exclusions_json=json.dumps(exclusions),
        preference_waived=1 if waiver_reason else 0,
        waiver_reason_sealed=sealed,
        profile_code=profile_code,
        information_acknowledged=1 if is_yes else 0,
        client_confirmed=1,
        capture_channel=body.capture_channel,
        mandate_type_at_capture=mandate.mandate_type,
        review_policy_version=sp.REVIEW_POLICY_VERSION,
        review_policy_months=months,
        review_due_on=sp.add_months_iso(now[:10], months),
        captured_by=current_user.id,
        captured_at=now,
        created_at=now,
    )
    fields = _row_fields(row)
    row.decision_hash = evidence_hash(sp.decision_snapshot(fields))
    db.add(row)
    try:
        db.flush()
        log(db, user_id=current_user.id, user_name=current_user.full_name,
            table_name="investment_preference_decisions", record_id=row.id, action="CREATE",
            new_value=json.dumps({
                "state": sp.base_state(fields),
                "profile_code": profile_code, "sequence_no": row.sequence_no,
                "decision_hash": row.decision_hash, "capture_channel": row.capture_channel,
            }, sort_keys=True),
            mandate_id=mandate.id, client_id=mandate.client_id,
            ip_address=_extract_client_ip(request))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _sustainability_error(
            "Die Nachhaltigkeitspräferenz wurde gleichzeitig geändert. Bitte neu laden.",
            ReasonCode.SUSTAINABILITY_PREFERENCE_CONFLICT, 409,
        ) from exc
    invalidate_advisory_cache(mandate.id)
    return _sustainability_state(db, mandate)
