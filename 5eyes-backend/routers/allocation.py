from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime, timezone
from database import get_db, new_uuid
from models.users import User
from models.mandates import Mandate
from models.allocation import TargetAllocation, OptimizerPolicy, CapitalMarketAssumption, HouseMatrix, BuildingBlock
from models.profiling import RiskAssessment
from schemas.allocation import (
    TargetAllocationCreate, TargetAllocationResponse,
    HouseMatrixResponse,
    CapitalMarketAssumptionCreate, CapitalMarketAssumptionResponse,
    TargetAllocationGenerateRequest, TargetAllocationGenerateResponse,
    BuildingBlockResponse,
    AllocationSensitivityRequest, AllocationSensitivityResponse,
)
from services.auth import get_current_user, get_mandate_for_user_or_404, require_advisor, require_admin
from services.audit import log
from services.portfolio_engine import (
    build_target_payload_from_allocation,
    ensure_runtime_reference_data,
    evaluate_goal_sensitivity,
    generate_target_allocation,
    require_strategy_ready_assessment,
)
from services.review_engine import refresh_system_review_triggers

router = APIRouter(tags=["Allokation"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _get_mandate_or_404(mandate_id: str, db: Session, current_user: User) -> Mandate:
    return get_mandate_for_user_or_404(mandate_id, db, current_user)


@router.get("/mandates/{mandate_id}/target-allocation/current",
            response_model=TargetAllocationResponse)
def get_current_allocation(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    _get_mandate_or_404(mandate_id, db, current_user)
    ta = db.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate_id,
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None)
    ).first()
    if not ta:
        raise HTTPException(status_code=404, detail="Keine Soll-Allokation gefunden")
    return ta


@router.get("/mandates/{mandate_id}/target-allocation/current/payload",
            response_model=TargetAllocationGenerateResponse)
def get_current_allocation_payload(
    mandate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    ta = db.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate_id,
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None)
    ).first()
    if not ta:
        raise HTTPException(status_code=404, detail="Keine Soll-Allokation gefunden")
    assessment = db.query(RiskAssessment).filter(
        RiskAssessment.mandate_id == mandate_id,
        RiskAssessment.is_current == 1,
        RiskAssessment.deleted_at.is_(None),
    ).first()
    if not assessment:
        raise HTTPException(status_code=409, detail="Bitte zuerst ein aktuelles Risikoprofil speichern.")
    policy, cma = ensure_runtime_reference_data(db, current_user.id)
    return build_target_payload_from_allocation(
        db=db,
        mandate=mandate,
        allocation=ta,
        policy=policy,
        cma=cma,
        assessment=assessment,
        preferences=None,
    )


@router.post("/mandates/{mandate_id}/target-allocation",
             response_model=TargetAllocationResponse, status_code=201)
def create_target_allocation(
    mandate_id: str,
    body: TargetAllocationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    # FIDLEG: jede gespeicherte Soll-Allokation muss auf einer strategie-fertigen
    # Risikoprofilierung beruhen. Direktes POST darf das nicht umgehen.
    try:
        assessment = require_strategy_ready_assessment(db, mandate_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if body.based_on_assessment_id and body.based_on_assessment_id != assessment.id:
        raise HTTPException(status_code=422, detail=(
            "based_on_assessment_id muss auf das aktuelle Risikoprofil zeigen "
            f"(erwartet {assessment.id})."
        ))
    # Policy: nur aktuelle akzeptieren.
    policy = db.query(OptimizerPolicy).filter(
        OptimizerPolicy.id == body.policy_id,
        OptimizerPolicy.is_current == 1,
    ).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Optimizer Policy nicht gefunden oder nicht aktuell")
    now = _now()
    # Supersede previous
    prev = db.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate_id,
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None)
    ).first()
    prev_version = 0
    if prev:
        prev.is_current = 0
        prev_version = prev.version
    payload = body.model_dump()
    if not payload.get("based_on_assessment_id"):
        payload["based_on_assessment_id"] = assessment.id
    ta = TargetAllocation(
        id=new_uuid(),
        mandate_id=mandate_id,
        version=prev_version + 1,
        is_current=1,
        set_by=current_user.id,
        set_at=now,
        created_at=now,
        updated_at=now,
        **payload
    )
    db.add(ta)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="target_allocations", record_id=ta.id, action="CREATE",
        mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    db.refresh(ta)
    return ta


@router.get("/house-matrix/{score}", response_model=HouseMatrixResponse)
def get_house_matrix_for_score(
    score: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get house matrix band for a given risk score (1–10)."""
    if not 1 <= score <= 10:
        raise HTTPException(status_code=400, detail="Score muss zwischen 1 und 10 liegen")
    # Get current policy
    policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Keine aktive Optimizer Policy gefunden")
    hm = db.query(HouseMatrix).filter(
        HouseMatrix.policy_id == policy.id,
        HouseMatrix.score_from <= score,
        HouseMatrix.score_to >= score,
        HouseMatrix.is_active == 1
    ).first()
    if not hm:
        raise HTTPException(status_code=404, detail=f"Kein House Matrix Eintrag für Score {score}")
    return hm


@router.get("/optimizer-policies/current")
def get_current_policy(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Keine aktive Optimizer Policy gefunden")
    return policy


@router.get("/building-blocks/current", response_model=list[BuildingBlockResponse])
def get_current_building_blocks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Keine aktive Optimizer Policy gefunden")
    return db.query(BuildingBlock).filter(
        BuildingBlock.policy_id == policy.id,
        BuildingBlock.is_active == 1,
    ).order_by(BuildingBlock.asset_class.asc(), BuildingBlock.sub_asset_class.asc()).all()


@router.get("/capital-market-assumptions/current",
            response_model=CapitalMarketAssumptionResponse)
def get_current_cma(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cma = db.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.is_current == 1,
        CapitalMarketAssumption.deleted_at.is_(None)
    ).first()
    if not cma:
        raise HTTPException(status_code=404, detail="Keine Kapitalmarktannahmen gefunden")
    return cma


@router.put("/capital-market-assumptions",
            response_model=CapitalMarketAssumptionResponse)
def update_cma(
    body: CapitalMarketAssumptionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Admin only — update capital market assumptions (creates new version)."""
    now = _now()
    # Archive previous
    prev = db.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.is_current == 1,
        CapitalMarketAssumption.deleted_at.is_(None)
    ).first()
    prev_version = 0
    if prev:
        prev.is_current = 0
        prev_version = prev.version
    cma = CapitalMarketAssumption(
        id=new_uuid(),
        version=prev_version + 1,
        is_current=1,
        created_by=current_user.id,
        created_at=now,
        updated_at=now,
        **body.model_dump()
    )
    db.add(cma)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="capital_market_assumptions", record_id=cma.id, action="CREATE")
    db.commit()
    db.refresh(cma)
    return cma


@router.post("/mandates/{mandate_id}/target-allocation/generate",
             response_model=TargetAllocationGenerateResponse)
def generate_target_allocation_endpoint(
    mandate_id: str,
    body: TargetAllocationGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor)
):
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    try:
        result = generate_target_allocation(
            db=db,
            mandate=mandate,
            user_id=current_user.id,
            preferences=body.preferences.model_dump() if body.preferences else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    refresh_system_review_triggers(db, mandate, current_user.id)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="target_allocations", record_id=result["target_allocation"].id, action="CREATE",
        mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    db.refresh(result["target_allocation"])
    return result


@router.post("/mandates/{mandate_id}/target-allocation/sensitivity",
             response_model=AllocationSensitivityResponse)
def goal_target_sensitivity(
    mandate_id: str,
    body: AllocationSensitivityRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    """Phase 6 FE-Optimizer-Panel: ein einzelnes Goal um delta_pct verschieben
    und neuen Solver-Lauf zurueckliefern (mit gepinntem Seed = identische
    Scenarios = sauberes Apples-to-Apples-Delta).

    Gibt 409 wenn OPTIMIZER_MODE != 'stochastic' oder kein Risikoprofil.
    Gibt 404 wenn Goal nicht zum Mandanten gehoert.

    FINMA-Trace: jeder Aufruf wird als SENSITIVITY-Eintrag im AuditLog
    persistiert (mandate, goal, delta).
    """
    mandate = _get_mandate_or_404(mandate_id, db, current_user)
    try:
        result = evaluate_goal_sensitivity(
            db=db,
            mandate=mandate,
            user_id=current_user.id,
            goal_id=body.goal_id,
            target_delta_pct=body.target_delta_pct,
        )
    except ValueError as exc:
        msg = str(exc)
        if "nicht gefunden" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=409, detail=msg)
    # Phase 6.3: AuditLog-Eintrag fuer FINMA-Trace. record_id = goal_id, weil
    # die Sensitivity sich auf ein konkretes Goal bezieht; new_value = delta_pct
    # damit forensisch nachvollziehbar ist welche Schieber bewegt wurden.
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="goals", record_id=body.goal_id, action="SENSITIVITY",
        new_value=str(body.target_delta_pct),
        mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    return result
