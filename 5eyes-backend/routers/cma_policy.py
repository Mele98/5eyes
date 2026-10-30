"""CMA_POLICY-Workflow-Endpunkte (CMA-001).

Lesen: interne Rollen (require_reference_data_reader). Schreiben und alle
Zustandsuebergaenge: Portfolio Management (require_portfolio_management).
Fachwerte kommen ausschliesslich aus dem Request -- der Server erfindet
nichts. Fehler: 422 bei ungueltigem Inhalt, 409 bei unzulaessigem
Uebergang oder Vier-Augen-Verstoss.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from models.cma_policy import CmaPolicy
from models.users import User
from routers.auth import _extract_client_ip
from schemas.cma_policy import (
    CmaPolicyApprovalOut,
    CmaPolicyComponentOut,
    CmaPolicyComponentsReplace,
    CmaPolicyCreate,
    CmaPolicyDecision,
    CmaPolicyModelStatus,
    CmaPolicyOut,
)
from services import cma_policy as svc
from services.audit import log
from services.auth import require_portfolio_management, require_reference_data_reader

router = APIRouter(prefix="/cma-policies", tags=["CMA-Policy"])


def _out(db: Session, policy: CmaPolicy) -> CmaPolicyOut:
    result = CmaPolicyOut.model_validate(policy)
    result.components = [
        CmaPolicyComponentOut.model_validate(row) for row in svc.components_of(db, policy)
    ]
    result.approvals = [
        CmaPolicyApprovalOut.model_validate(row) for row in svc.approvals_of(db, policy)
    ]
    return result


def _get_or_404(db: Session, policy_row_id: str) -> CmaPolicy:
    policy = db.query(CmaPolicy).filter(CmaPolicy.id == policy_row_id).first()
    if policy is None:
        raise HTTPException(status_code=404, detail="CMA-Policy nicht gefunden")
    return policy


def _run(db: Session, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except svc.CmaPolicyError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except svc.CmaPolicyConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _audit(db: Session, user: User, request: Request, policy: CmaPolicy, action: str, field: str) -> None:
    log(db, user_id=user.id, user_name=user.full_name, table_name="cma_policies",
        record_id=policy.id, action=action, field_name=field, new_value=policy.status,
        ip_address=_extract_client_ip(request))


@router.get("/model-status", response_model=CmaPolicyModelStatus)
def get_model_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_reference_data_reader),
):
    enforced = svc.policy_model_enforced(db)
    return CmaPolicyModelStatus(
        enforced=enforced,
        explanation=(
            "Neue Finalisierungen verlangen eine aktive, gültige CMA-Policy."
            if enforced
            else "Noch keine CMA-Policy aktiviert: das Modell ist vorhanden, "
            "das Finalisierungs-Gate ist bis zur ersten Aktivierung nicht scharf."
        ),
    )


@router.get("", response_model=list[CmaPolicyOut])
def list_policies(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_reference_data_reader),
):
    rows = db.query(CmaPolicy).order_by(CmaPolicy.policy_id, CmaPolicy.version).all()
    return [_out(db, row) for row in rows]


@router.get("/{policy_row_id}", response_model=CmaPolicyOut)
def get_policy(
    policy_row_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_reference_data_reader),
):
    return _out(db, _get_or_404(db, policy_row_id))


@router.post("", response_model=CmaPolicyOut, status_code=201)
def create_policy(
    body: CmaPolicyCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_portfolio_management),
):
    data = body.model_dump(exclude={"sources", "components"})
    if body.sources:
        data["sources_json"] = body.sources
    data["components"] = [c.model_dump() for c in body.components]
    policy = _run(db, svc.create_draft, db, current_user.id, data)
    _audit(db, current_user, request, policy, "CREATE", "cma_policy")
    db.commit()
    return _out(db, policy)


@router.put("/{policy_row_id}/components", response_model=CmaPolicyOut)
def replace_components(
    policy_row_id: str,
    body: CmaPolicyComponentsReplace,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_portfolio_management),
):
    policy = _get_or_404(db, policy_row_id)
    _run(db, svc.replace_components, db, policy, [c.model_dump() for c in body.components])
    _audit(db, current_user, request, policy, "UPDATE", "components")
    db.commit()
    return _out(db, policy)


@router.post("/{policy_row_id}/validate", response_model=CmaPolicyOut)
def validate_policy(
    policy_row_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_portfolio_management),
):
    policy = _get_or_404(db, policy_row_id)
    _run(db, svc.validate_policy, db, policy, current_user.id)
    _audit(db, current_user, request, policy, "UPDATE", "status")
    db.commit()
    return _out(db, policy)


@router.post("/{policy_row_id}/approve", response_model=CmaPolicyOut)
def approve_policy(
    policy_row_id: str,
    body: CmaPolicyDecision,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_portfolio_management),
):
    policy = _get_or_404(db, policy_row_id)
    _run(db, svc.approve_policy, db, policy, current_user.id, body.rationale)
    _audit(db, current_user, request, policy, "APPROVE", "status")
    db.commit()
    return _out(db, policy)


@router.post("/{policy_row_id}/activate", response_model=CmaPolicyOut)
def activate_policy(
    policy_row_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_portfolio_management),
):
    policy = _get_or_404(db, policy_row_id)
    _run(db, svc.activate_policy, db, policy, current_user.id)
    _audit(db, current_user, request, policy, "ACTIVATE", "status")
    db.commit()
    return _out(db, policy)


@router.post("/{policy_row_id}/retire", response_model=CmaPolicyOut)
def retire_policy(
    policy_row_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_portfolio_management),
):
    policy = _get_or_404(db, policy_row_id)
    _run(db, svc.retire_policy, db, policy)
    _audit(db, current_user, request, policy, "UPDATE", "status")
    db.commit()
    return _out(db, policy)


@router.post("/{policy_row_id}/revoke", response_model=CmaPolicyOut)
def revoke_policy(
    policy_row_id: str,
    body: CmaPolicyDecision,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_portfolio_management),
):
    policy = _get_or_404(db, policy_row_id)
    _run(db, svc.revoke_policy, db, policy, current_user.id, body.rationale)
    _audit(db, current_user, request, policy, "UPDATE", "status")
    db.commit()
    return _out(db, policy)
