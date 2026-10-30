"""PRIVACY-001: API fuer Aufbewahrungsmatrix, Legal/Privacy-Rollen, Legal
Holds und Loeschvorgaenge (services/privacy_erasure.py).

Produktivaktivierung ist BLOCKED: ohne genehmigte Matrixzeilen bleibt jeder
Loeschvorgang "Entscheid ausstehend". ``GET /privacy/status`` sagt das
ausdruecklich, statt einen funktionierenden Ablauf vorzutaeuschen.

Mandantentrennung: jede Zeile traegt ``tenant_id``; Zugriffe auf IDs fremder
Mandanten enden als 404. Kunden werden ueber denselben tenant-gefilterten
Lookup wie die bestehende DSG-Art.-32-Loeschung aufgeloest.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models.privacy import (
    PrivacyErasureCase,
    PrivacyErasureDisposition,
    PrivacyLegalHold,
    PrivacyRetentionPolicy,
    PrivacyRoleDesignation,
)
from models.users import User
from services import privacy_erasure as pe
from services import privacy_erasure_inventory as inv
from services.audit import log
from services.auth import (
    extract_client_ip,
    get_client_for_erasure_or_404,
    get_current_user,
    require_admin,
    user_tenant_id,
)

router = APIRouter(prefix="/privacy", tags=["Datenschutz"])

PRODUCTION_ACTIVATION = "BLOCKED"


class PolicyProposal(BaseModel):
    evidence_type: str
    data_category: str = "*"
    disposition: str
    matrix: dict[str, Any]
    legal_basis: Optional[str] = None
    retention_trigger: Optional[str] = None
    retention_months: Optional[int] = Field(default=None, ge=1)


class RoleGrant(BaseModel):
    user_id: str
    privacy_role: str


class LegalHoldProposal(BaseModel):
    client_id: str
    case_reference: str = Field(min_length=1)
    legal_reason: str = Field(min_length=1)
    scope: list[str]
    review_date: str
    expires_at: Optional[str] = None


class LegalHoldExtension(BaseModel):
    review_date: str
    expires_at: Optional[str] = None


class ErasureCaseOpen(BaseModel):
    client_id: str
    relationship_end_date: Optional[str] = None


def _tenant(user: User) -> str:
    return user_tenant_id(user)


def _own(record, user: User):
    if record is None or record.tenant_id != _tenant(user):
        raise HTTPException(status_code=404, detail="Nicht gefunden")
    return record


def _client_in_scope(client_id: str, db: Session, user: User) -> None:
    client = get_client_for_erasure_or_404(client_id, db, user)
    if client.tenant_id != _tenant(user):
        raise HTTPException(status_code=404, detail="Kunde nicht gefunden")


def _audit(db: Session, user: User, request: Request, *, table: str, record_id: str, action: str,
           new_value: dict[str, Any], client_id: str | None = None) -> None:
    log(db, user_id=user.id, user_name=user.full_name, table_name=table, record_id=record_id,
        action=action, client_id=client_id, new_value=json.dumps(new_value, sort_keys=True),
        ip_address=extract_client_ip(request))


def _policy_out(policy: PrivacyRetentionPolicy) -> dict[str, Any]:
    return {
        "id": policy.id, "evidence_type": policy.evidence_type, "data_category": policy.data_category,
        "version": policy.version, "status": policy.status, "disposition": policy.disposition,
        "legal_basis": policy.legal_basis, "retention_trigger": policy.retention_trigger,
        "retention_months": policy.retention_months, "matrix": json.loads(policy.matrix_json),
        "policy_hash": policy.policy_hash, "proposed_by": policy.proposed_by,
        "proposed_at": policy.proposed_at, "approved_by": policy.approved_by,
        "approved_at": policy.approved_at, "retired_at": policy.retired_at,
        "approval_problems": pe.policy_approval_problems(policy) if policy.status == "PROPOSED" else [],
    }


def _hold_out(hold: PrivacyLegalHold) -> dict[str, Any]:
    return {
        "id": hold.id, "client_id": hold.client_id, "case_reference": hold.case_reference,
        "legal_reason": hold.legal_reason, "scope": json.loads(hold.scope_json), "status": hold.status,
        "set_by": hold.set_by, "approved_by": hold.approved_by, "approved_at": hold.approved_at,
        "review_date": hold.review_date, "expires_at": hold.expires_at,
        "extension_count": hold.extension_count, "released_by": hold.released_by,
        "released_at": hold.released_at,
    }


def _case_out(db: Session, case: PrivacyErasureCase) -> dict[str, Any]:
    lines = (
        db.query(PrivacyErasureDisposition)
        .filter(PrivacyErasureDisposition.case_id == case.id)
        .order_by(PrivacyErasureDisposition.table_name, PrivacyErasureDisposition.data_category)
        .all()
    )
    pending = sum(1 for line in lines if line.decision_status == "DECISION_PENDING")
    return {
        "id": case.id, "client_id": case.client_id, "status": case.status,
        "status_label": "Entscheid ausstehend" if case.status == "DECISION_PENDING" else case.status,
        "decisions_pending": pending, "inventory_version": case.inventory_version,
        "relationship_end_date": case.relationship_end_date, "opened_by": case.opened_by,
        "opened_at": case.opened_at, "executed_by": case.executed_by, "executed_at": case.executed_at,
        "receipt": json.loads(case.receipt_json) if case.receipt_json else None,
        "receipt_sha256": case.receipt_sha256,
        "production_activation": PRODUCTION_ACTIVATION,
        "lines": [
            {
                "id": line.id, "table": line.table_name, "data_category": line.data_category,
                "evidence_type": line.evidence_type, "method": line.method, "row_count": line.row_count,
                "rows_digest": line.rows_digest, "decision_status": line.decision_status,
                "disposition": line.disposition, "policy_id": line.policy_id,
                "legal_hold_id": line.legal_hold_id, "legal_basis": line.legal_basis,
                "retention_trigger": line.retention_trigger, "retain_until": line.retain_until,
                "failure_code": line.failure_code,
            }
            for line in lines
        ],
    }


# ── Status ─────────────────────────────────────────────────────────────────────

@router.get("/status")
def privacy_status(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    tenant_id = _tenant(current_user)
    approved = {
        (row.evidence_type, row.data_category)
        for row in db.query(PrivacyRetentionPolicy).filter(
            PrivacyRetentionPolicy.tenant_id == tenant_id, PrivacyRetentionPolicy.status == "APPROVED",
        )
    }
    missing = sorted(et for et in inv.EVIDENCE_TYPES if not any(key[0] == et for key in approved))
    return {
        "production_activation": PRODUCTION_ACTIVATION,
        "matrix_complete": not missing,
        "evidence_types_without_approved_policy": missing,
        "inventory_version": inv.INVENTORY_VERSION,
        "message": (
            "Aufbewahrungsmatrix ist nicht durch Legal/Datenschutz freigegeben. Loeschgesuche "
            "bleiben 'Entscheid ausstehend'; es wird weder automatisch geloescht noch "
            "unbegrenzt aufbewahrt."
        ) if missing else (
            "Matrix fuer alle Nachweisarten genehmigt. Produktivaktivierung bleibt bis zur "
            "Freigabe blockiert."
        ),
    }


# ── Rollen ─────────────────────────────────────────────────────────────────────

@router.get("/roles")
def list_roles(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    rows = db.query(PrivacyRoleDesignation).filter(
        PrivacyRoleDesignation.tenant_id == _tenant(current_user),
    ).order_by(PrivacyRoleDesignation.granted_at).all()
    return [
        {"id": r.id, "user_id": r.user_id, "privacy_role": r.privacy_role, "granted_by": r.granted_by,
         "granted_at": r.granted_at, "revoked_by": r.revoked_by, "revoked_at": r.revoked_at}
        for r in rows
    ]


@router.post("/roles", status_code=201)
def grant_role(body: RoleGrant, request: Request, db: Session = Depends(get_db),
               current_user: User = Depends(require_admin)):
    designation = pe.grant_privacy_role(
        db, tenant_id=_tenant(current_user), user_id=body.user_id, privacy_role=body.privacy_role,
        granted_by=current_user.id,
    )
    _audit(db, current_user, request, table="privacy_role_designations", record_id=designation.id,
           action="CREATE", new_value={"user_id": body.user_id, "privacy_role": body.privacy_role})
    db.commit()
    return {"id": designation.id, "user_id": designation.user_id, "privacy_role": designation.privacy_role}


@router.delete("/roles/{designation_id}")
def revoke_role(designation_id: str, request: Request, db: Session = Depends(get_db),
                current_user: User = Depends(require_admin)):
    _own(db.get(PrivacyRoleDesignation, designation_id), current_user)
    designation = pe.revoke_privacy_role(db, designation_id=designation_id, revoked_by=current_user.id)
    _audit(db, current_user, request, table="privacy_role_designations", record_id=designation.id,
           action="DELETE", new_value={"revoked_at": designation.revoked_at})
    db.commit()
    return {"id": designation.id, "revoked_at": designation.revoked_at}


# ── Aufbewahrungsmatrix ────────────────────────────────────────────────────────

@router.get("/policies")
def list_policies(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    rows = db.query(PrivacyRetentionPolicy).filter(
        PrivacyRetentionPolicy.tenant_id == _tenant(current_user),
    ).order_by(PrivacyRetentionPolicy.evidence_type, PrivacyRetentionPolicy.data_category,
               PrivacyRetentionPolicy.version).all()
    return [_policy_out(row) for row in rows]


@router.post("/policies", status_code=201)
def propose_policy(body: PolicyProposal, request: Request, db: Session = Depends(get_db),
                   current_user: User = Depends(require_admin)):
    policy = pe.propose_policy(
        db, tenant_id=_tenant(current_user), evidence_type=body.evidence_type,
        data_category=body.data_category, disposition=body.disposition, matrix=body.matrix,
        proposed_by=current_user.id, legal_basis=body.legal_basis,
        retention_trigger=body.retention_trigger, retention_months=body.retention_months,
    )
    _audit(db, current_user, request, table="privacy_retention_policies", record_id=policy.id,
           action="CREATE", new_value={"status": policy.status, "policy_hash": policy.policy_hash})
    db.commit()
    return _policy_out(policy)


@router.post("/policies/{policy_id}/approve")
def approve_policy(policy_id: str, request: Request, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    _own(db.get(PrivacyRetentionPolicy, policy_id), current_user)
    policy = pe.approve_policy(db, policy_id=policy_id, approved_by=current_user.id)
    _audit(db, current_user, request, table="privacy_retention_policies", record_id=policy.id,
           action="APPROVE", new_value={"status": policy.status, "policy_hash": policy.policy_hash})
    db.commit()
    return _policy_out(policy)


# ── Legal Hold ─────────────────────────────────────────────────────────────────

@router.get("/legal-holds")
def list_legal_holds(client_id: Optional[str] = None, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    pe._require_privacy_officer(db, tenant_id=_tenant(current_user), user_id=current_user.id,
                                action="Legal-Hold-Einsicht")
    query = db.query(PrivacyLegalHold).filter(PrivacyLegalHold.tenant_id == _tenant(current_user))
    if client_id:
        query = query.filter(PrivacyLegalHold.client_id == client_id)
    return [_hold_out(row) for row in query.order_by(PrivacyLegalHold.created_at).all()]


@router.post("/legal-holds", status_code=201)
def propose_legal_hold(body: LegalHoldProposal, request: Request, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    _client_in_scope(body.client_id, db, current_user)
    hold = pe.create_legal_hold(
        db, client_id=body.client_id, case_reference=body.case_reference, legal_reason=body.legal_reason,
        scope=body.scope, review_date=body.review_date, expires_at=body.expires_at, set_by=current_user.id,
    )
    _audit(db, current_user, request, table="privacy_legal_holds", record_id=hold.id, action="CREATE",
           client_id=hold.client_id, new_value={"status": hold.status, "scope": json.loads(hold.scope_json)})
    db.commit()
    return _hold_out(hold)


@router.post("/legal-holds/{hold_id}/approve")
def approve_legal_hold(hold_id: str, request: Request, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    _own(db.get(PrivacyLegalHold, hold_id), current_user)
    hold = pe.approve_legal_hold(db, hold_id=hold_id, approved_by=current_user.id)
    _audit(db, current_user, request, table="privacy_legal_holds", record_id=hold.id, action="APPROVE",
           client_id=hold.client_id, new_value={"status": hold.status})
    db.commit()
    return _hold_out(hold)


@router.post("/legal-holds/{hold_id}/extend")
def extend_legal_hold(hold_id: str, body: LegalHoldExtension, request: Request,
                      db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _own(db.get(PrivacyLegalHold, hold_id), current_user)
    hold = pe.extend_legal_hold(db, hold_id=hold_id, review_date=body.review_date,
                                expires_at=body.expires_at, actor=current_user.id)
    _audit(db, current_user, request, table="privacy_legal_holds", record_id=hold.id, action="UPDATE",
           client_id=hold.client_id,
           new_value={"review_date": hold.review_date, "expires_at": hold.expires_at,
                      "extension_count": hold.extension_count})
    db.commit()
    return _hold_out(hold)


@router.post("/legal-holds/{hold_id}/release")
def release_legal_hold(hold_id: str, request: Request, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    _own(db.get(PrivacyLegalHold, hold_id), current_user)
    hold = pe.release_legal_hold(db, hold_id=hold_id, actor=current_user.id)
    _audit(db, current_user, request, table="privacy_legal_holds", record_id=hold.id, action="UPDATE",
           client_id=hold.client_id, new_value={"status": hold.status})
    db.commit()
    return _hold_out(hold)


# ── Loeschvorgaenge ────────────────────────────────────────────────────────────

@router.post("/erasure-cases", status_code=201)
def open_erasure_case(body: ErasureCaseOpen, request: Request, db: Session = Depends(get_db),
                      current_user: User = Depends(require_admin)):
    _client_in_scope(body.client_id, db, current_user)
    case = pe.open_erasure_case(db, client_id=body.client_id, opened_by=current_user.id,
                                relationship_end_date=body.relationship_end_date)
    _audit(db, current_user, request, table="privacy_erasure_cases", record_id=case.id, action="CREATE",
           client_id=case.client_id, new_value={"status": case.status})
    db.commit()
    return _case_out(db, case)


@router.get("/erasure-cases/{case_id}")
def get_erasure_case(case_id: str, db: Session = Depends(get_db),
                     current_user: User = Depends(require_admin)):
    return _case_out(db, _own(db.get(PrivacyErasureCase, case_id), current_user))


@router.post("/erasure-cases/{case_id}/refresh")
def refresh_erasure_case(case_id: str, db: Session = Depends(get_db),
                         current_user: User = Depends(require_admin)):
    _own(db.get(PrivacyErasureCase, case_id), current_user)
    case = pe.refresh_erasure_case(db, case_id=case_id)
    db.commit()
    return _case_out(db, case)


@router.post("/erasure-cases/{case_id}/execute")
def execute_erasure_case(case_id: str, request: Request, db: Session = Depends(get_db),
                         current_user: User = Depends(require_admin)):
    _own(db.get(PrivacyErasureCase, case_id), current_user)
    try:
        case = pe.execute_erasure_case(db, case_id=case_id, executed_by=current_user.id)
    except HTTPException:
        db.rollback()
        raise
    _audit(db, current_user, request, table="privacy_erasure_cases", record_id=case.id, action="UPDATE",
           client_id=case.client_id,
           new_value={"status": case.status, "receipt_sha256": case.receipt_sha256})
    db.commit()
    return _case_out(db, case)


@router.post("/retention-expiry")
def run_retention_expiry(request: Request, db: Session = Depends(get_db),
                         current_user: User = Depends(require_admin)):
    result = pe.process_retention_expiry(db, tenant_id=_tenant(current_user))
    _audit(db, current_user, request, table="privacy_erasure_dispositions", record_id="retention-expiry",
           action="UPDATE", new_value={"disposal_due": result["disposal_due"], "disposed": result["disposed"],
                                       "keys_shredded": len(result["keys_shredded_clients"])})
    db.commit()
    return result
