"""ELIG-OVERRIDE-CAPTURE-001 -- endpoints to request/approve a product
eligibility override for a draft recommendation run.

Advisor/admin only (``require_advisor``), mandate access via
``get_mandate_for_user_or_404`` (foreign tenant/mandate -> 404). Rows are
only ever inserted; every step is also written to the immutable audit_log.
Logic lives in services/product_eligibility_override.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from database import get_db
from models.mandates import Mandate
from models.review import RecommendationRun
from models.users import User
from services.audit import log
from services.auth import get_mandate_for_user_or_404, require_advisor
from services.product_eligibility_override import (
    MIN_OVERRIDE_REASON_LENGTH,
    OverrideConflict,
    approve_override,
    decision_context,
    override_overview,
    request_override,
)

router = APIRouter(tags=["Empfehlungen"])

_BASE = "/mandates/{mandate_id}/recommendations/{run_id}/eligibility-overrides"


class EligibilityOverrideRequest(BaseModel):
    product_id: str
    reason_text: str
    # Optional optimistic check: the decision_hash the advisor saw.
    expected_decision_hash: str | None = None

    @field_validator("reason_text")
    @classmethod
    def _reason_required(cls, value: str) -> str:
        value = (value or "").strip()
        if len(value) < MIN_OVERRIDE_REASON_LENGTH:
            raise ValueError(
                f"Begruendung ist Pflicht (mindestens {MIN_OVERRIDE_REASON_LENGTH} Zeichen)."
            )
        return value


def _context(mandate_id: str, run_id: str, db: Session, current_user: User):
    mandate = get_mandate_for_user_or_404(mandate_id, db, current_user)
    run = db.query(RecommendationRun).filter(
        RecommendationRun.id == run_id,
        RecommendationRun.mandate_id == mandate_id,
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Empfehlung nicht gefunden")
    try:
        return decision_context(db, mandate, run)
    except OverrideConflict as exc:
        raise HTTPException(status_code=409, detail={"reason_code": exc.code, "message": exc.message})


def _row_out(row) -> dict:
    return {
        "id": row.id,
        "product_id": row.product_id,
        "rule_id": row.rule_id,
        "requested_by": row.requested_by,
        "approved_by": row.approved_by or None,
        "reason_text": row.reason_text,
        "valid_from": row.valid_from,
        "expires_at": row.expires_at,
        "evidence_hash": row.evidence_hash,
        "created_at": row.created_at,
        "state": "valid" if row.approved_by else "pending",
    }


def _conflict(exc: OverrideConflict) -> HTTPException:
    return HTTPException(status_code=409, detail={"reason_code": exc.code, "message": exc.message})


@router.get(_BASE)
def list_eligibility_overrides(
    mandate_id: str, run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    ctx = _context(mandate_id, run_id, db, current_user)
    return {"run_id": run_id, "items": override_overview(db, ctx)}


@router.post(_BASE, status_code=201)
def request_eligibility_override(
    mandate_id: str, run_id: str,
    body: EligibilityOverrideRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    db.query(Mandate).filter(Mandate.id == mandate_id).with_for_update().first()
    ctx = _context(mandate_id, run_id, db, current_user)
    try:
        row = request_override(
            db, ctx, product_id=body.product_id, reason_text=body.reason_text,
            requested_by=current_user.id, expected_decision_hash=body.expected_decision_hash,
        )
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except OverrideConflict as exc:
        db.rollback()
        raise _conflict(exc)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="product_eligibility_overrides", record_id=row.id, action="INSERT",
        new_value=f"requested;run={run_id};product={row.product_id};rule={row.rule_id};"
                  f"evidence_hash={row.evidence_hash};reason={row.reason_text}",
        mandate_id=mandate_id)
    db.commit()
    return _row_out(row)


@router.post(_BASE + "/{override_id}/approve", status_code=201)
def approve_eligibility_override(
    mandate_id: str, run_id: str, override_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    db.query(Mandate).filter(Mandate.id == mandate_id).with_for_update().first()
    ctx = _context(mandate_id, run_id, db, current_user)
    try:
        row = approve_override(db, ctx, override_id=override_id, approver_id=current_user.id)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except OverrideConflict as exc:
        db.rollback()
        raise _conflict(exc)
    log(db, user_id=current_user.id, user_name=current_user.full_name,
        table_name="product_eligibility_overrides", record_id=row.id, action="INSERT",
        new_value=f"approved;request={override_id};run={run_id};product={row.product_id};"
                  f"rule={row.rule_id};expires_at={row.expires_at};evidence_hash={row.evidence_hash}",
        mandate_id=mandate_id)
    db.commit()
    return _row_out(row)
