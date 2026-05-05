from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import date, datetime, timezone
from database import get_db, new_uuid
from models.users import User
from models.mandates import Mandate
from models.allocation import TargetAllocation, OptimizerPolicy, CapitalMarketAssumption, HouseMatrix, BuildingBlock
from schemas.allocation import (
    TargetAllocationCreate, TargetAllocationResponse,
    HouseMatrixResponse,
    CapitalMarketAssumptionCreate, CapitalMarketAssumptionResponse,
    TargetAllocationGenerateRequest, TargetAllocationGenerateResponse,
    BuildingBlockResponse,
)
from services.auth import get_current_user, get_mandate_for_user_or_404, require_advisor, require_admin
from services.audit import log
from services.portfolio_engine import (
    build_target_payload_from_allocation,
    generate_target_allocation,
    require_strategy_ready_assessment,
)
from services.review_engine import refresh_system_review_triggers

router = APIRouter(tags=["Allokation"])


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _get_mandate_or_404(mandate_id: str, db: Session, current_user: User) -> Mandate:
    return get_mandate_for_user_or_404(mandate_id, db, current_user)


def _get_runtime_reference_data_or_404(db: Session) -> tuple[OptimizerPolicy, CapitalMarketAssumption]:
    policy = db.query(OptimizerPolicy).filter(
        OptimizerPolicy.is_current == 1,
    ).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Keine aktive Optimizer Policy")
    cma = db.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.is_current == 1,
        CapitalMarketAssumption.deleted_at.is_(None),
    ).first()
    if not cma:
        raise HTTPException(status_code=404, detail="Keine Kapitalmarktannahmen")
    return policy, cma


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
    try:
        assessment = require_strategy_ready_assessment(db, mandate_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    policy, cma = _get_runtime_reference_data_or_404(db)
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
    # Validate policy exists
    policy = db.query(OptimizerPolicy).filter(
        OptimizerPolicy.id == body.policy_id,
        OptimizerPolicy.is_current == 1,
    ).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Optimizer Policy nicht gefunden")
    try:
        assessment = require_strategy_ready_assessment(db, mandate_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _, cma = _get_runtime_reference_data_or_404(db)
    payload = body.model_dump()
    payload["based_on_assessment_id"] = assessment.id
    payload["capital_market_assumptions_id"] = cma.id
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
    payload = body.model_dump(exclude_unset=True)
    cma_values = payload
    if prev:
        cma_values = {
            "assumption_set_name": prev.assumption_set_name,
            "valid_from": prev.valid_from,
            "valid_until": prev.valid_until,
            "bonds_chf_ig_return_bps": prev.bonds_chf_ig_return_bps,
            "bonds_chf_ig_vol_bps": prev.bonds_chf_ig_vol_bps,
            "bonds_fx_hedged_return_bps": prev.bonds_fx_hedged_return_bps,
            "bonds_fx_hedged_vol_bps": prev.bonds_fx_hedged_vol_bps,
            "bonds_hy_return_bps": prev.bonds_hy_return_bps,
            "bonds_hy_vol_bps": prev.bonds_hy_vol_bps,
            "equity_ch_return_bps": prev.equity_ch_return_bps,
            "equity_ch_vol_bps": prev.equity_ch_vol_bps,
            "equity_intl_return_bps": prev.equity_intl_return_bps,
            "equity_intl_vol_bps": prev.equity_intl_vol_bps,
            "equity_em_return_bps": prev.equity_em_return_bps,
            "equity_em_vol_bps": prev.equity_em_vol_bps,
            "real_estate_ch_return_bps": prev.real_estate_ch_return_bps,
            "real_estate_ch_vol_bps": prev.real_estate_ch_vol_bps,
            "alternatives_gold_return_bps": prev.alternatives_gold_return_bps,
            "alternatives_gold_vol_bps": prev.alternatives_gold_vol_bps,
            "liquidity_return_bps": prev.liquidity_return_bps,
            "liquidity_vol_bps": prev.liquidity_vol_bps,
            "inflation_path_json": prev.inflation_path_json,
            "correlation_matrix_json": prev.correlation_matrix_json,
            "sub_asset_class_assumptions_json": prev.sub_asset_class_assumptions_json,
            "source": prev.source,
            "notes": prev.notes,
        }
        cma_values.update(payload)
    cma = CapitalMarketAssumption(
        id=new_uuid(),
        version=prev_version + 1,
        is_current=1,
        created_by=current_user.id,
        created_at=now,
        updated_at=now,
        **cma_values
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
    refresh_system_review_triggers(db, mandate, current_user.id, allocation_payload=result)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="target_allocations", record_id=result["target_allocation"].id, action="CREATE",
        mandate_id=mandate_id, client_id=mandate.client_id)
    db.commit()
    db.refresh(result["target_allocation"])
    return result
