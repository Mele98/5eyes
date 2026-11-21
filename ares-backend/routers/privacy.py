"""PRIVACY-001: API fuer Aufbewahrungsmatrix, Legal/Privacy-Rollen, Legal
Holds und Loeschvorgaenge (services/privacy_erasure.py).

H10 (DSG-Technikaudit 2026-11-11): Bearbeitungsverzeichnis und Angaben des
Verantwortlichen (C-DSG-01) ueber services/dsg_governance.py.

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

import database as _database
from database import get_db
from models.privacy import (
    PrivacyErasureCase,
    PrivacyErasureDisposition,
    PrivacyLegalHold,
    PrivacyRetentionPolicy,
    PrivacyRoleDesignation,
    OutboundProcessingEvent,
    OutboundTransferDailyCount,
    PrivacySecurityIncident,
    PrivacySecurityIncidentEvent,
    PrivacySubjectRequest,
    PrivacySubjectRequestEvent,
)
from models.users import User
from services import dsg_governance as gov
from services import privacy_erasure as pe
from core.reason_codes import DomainError, ReasonCode
from core.db_integrity import raise_if_check_violation
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


class BaselineProposal(BaseModel):
    matrix: dict[str, Any] = Field(default_factory=dict)


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
    # H10 (Verhaltensprobe 9051): Tier 1 fuehrt Kunden mit tenant_id NULL; wie
    # bei den Benutzern gilt NULL = Mandant "main" (user_tenant_id).
    if (client.tenant_id or "main") != _tenant(user):
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
    missing = sorted(et for et in gov.EVIDENCE_TYPES if not any(key[0] == et for key in approved))
    return {
        **gov.subject_requests.status_counts(db, tenant_id),
        "incident_gate_blocked": gov.incident_gate(db, tenant_id)["blocked"],
        "production_activation": PRODUCTION_ACTIVATION,
        "matrix_complete": not missing,
        "evidence_types_without_approved_policy": missing,
        "inventory_version": gov.ERASURE_INVENTORY_VERSION,
        "retention_baseline_version": pe.RETENTION_BASELINE_VERSION,
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


@router.post("/policies/baseline", status_code=201)
def propose_retention_baseline(body: BaselineProposal, request: Request, db: Session = Depends(get_db),
                               current_user: User = Depends(require_admin)):
    """H7 C-6: Aufbewahrungsmatrix aus der gesetzlichen Vorlage vorschlagen
    (10 Jahre ab Beziehungsende nach GwG Art. 7 Abs. 3 / OR 127, Vertrag und
    Belege OR 958f). Legt nur PROPOSED-Zeilen an (fehlende Nachweisarten);
    Betreiberangaben im Body, Genehmigung weiterhin im Vier-Augen-Prinzip."""
    created = pe.propose_retention_baseline(
        db, tenant_id=_tenant(current_user), proposed_by=current_user.id, operator_matrix=body.matrix,
    )
    for policy in created:
        _audit(db, current_user, request, table="privacy_retention_policies", record_id=policy.id,
               action="CREATE", new_value={"status": policy.status, "policy_hash": policy.policy_hash,
                                           "baseline_version": pe.RETENTION_BASELINE_VERSION})
    db.commit()
    return [_policy_out(policy) for policy in created]


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


# ── H10 C-DSG-01: Bearbeitungsverzeichnis und Angaben des Verantwortlichen ─────

class OwnerValueUpdate(BaseModel):
    value: str = Field(min_length=1, max_length=gov.OWNER_VALUE_MAX_LENGTH)


@router.get("/processing-register")
def get_processing_register(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Verzeichnis der Bearbeitungstaetigkeiten mit Vollstaendigkeitspruefung
    und dem Stand der Owner-Felder dieses Mandanten."""
    return gov.register_view(db, _tenant(current_user))


@router.get("/processing-register/export")
def export_processing_register(request: Request, db: Session = Depends(get_db),
                               current_user: User = Depends(require_admin)):
    """Maschinenlesbarer Export (JSON) mit Inhalts-Hash; offene Owner-Felder
    bleiben als ``OPEN`` sichtbar (``customer_output_ready``)."""
    document = gov.register_export(db, _tenant(current_user))
    _audit(db, current_user, request, table="privacy_owner_values", record_id="processing-register",
           action="EXPORT", new_value={"register_version": document["register_version"],
                                       "export_sha256": document["export_sha256"]})
    db.commit()
    return document


@router.get("/owner-fields")
def list_owner_fields(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    return gov.owner_field_status(db, _tenant(current_user))


@router.put("/owner-fields/{field_key}")
def set_owner_field(field_key: str, body: OwnerValueUpdate, request: Request, db: Session = Depends(get_db),
                    current_user: User = Depends(require_admin)):
    row, old_value = gov.set_owner_value(
        db, tenant_id=_tenant(current_user), field_key=field_key, value=body.value, actor_id=current_user.id,
    )
    log(db, user_id=current_user.id, user_name=current_user.full_name, table_name="privacy_owner_values",
        record_id=row.id, action="UPDATE", field_name=field_key, old_value=old_value, new_value=row.value,
        ip_address=extract_client_ip(request))
    db.commit()
    gov.refresh_egress_confirmations(db, _tenant(current_user))
    return {"field_key": row.field_key, "value": row.value, "revision": row.revision,
            "status": row.status, "confirmed_by": row.confirmed_by, "confirmed_at": row.confirmed_at}


# ── H10 C-DSG-02: Betroffenenanfragen ──────────────────────────────────────────

class SubjectRequestOpen(BaseModel):
    client_id: str
    request_type: str
    received_at: str
    received_channel: str
    requester_relation: str = "SELF"
    request_summary: Optional[str] = Field(default=None, max_length=4000)


class SubjectRequestIdentity(BaseModel):
    outcome: str
    method: str
    evidence_reference: Optional[str] = Field(default=None, max_length=2000)
    failure_reason: Optional[str] = Field(default=None, max_length=2000)


class SubjectRequestExtension(BaseModel):
    extended_due_at: str
    reason: Optional[str] = Field(default=None, max_length=2000)
    notified_at: str


class SubjectRequestDecision(BaseModel):
    decision: str
    reason: Optional[str] = Field(default=None, max_length=4000)
    scope: list[str] = Field(default_factory=list)


class SubjectRequestAction(BaseModel):
    completion_note: Optional[str] = Field(default=None, max_length=4000)
    erasure_case_id: Optional[str] = None


class SubjectRequestDelivery(BaseModel):
    delivered_at: str
    delivery_channel: str
    delivery_reference: Optional[str] = Field(default=None, max_length=2000)


class SubjectRequestWithdrawal(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=2000)


def _require_case_operator(db: Session, user: User) -> None:
    """Administration oder benannte Legal-/Datenschutzperson des Mandanten."""
    if user.role in ("admin", "super_admin"):
        return
    if pe.active_privacy_roles(db, tenant_id=_tenant(user), user_id=user.id):
        return
    raise HTTPException(status_code=403, detail={
        "code": "PRIVACY_ROLE_REQUIRED",
        "message": "Datenschutzfaelle bearbeiten nur Administration oder benannte Legal-/Datenschutzpersonen",
    })


def _subject_request(db: Session, request_id: str, user: User) -> PrivacySubjectRequest:
    _require_case_operator(db, user)
    return _own(db.get(PrivacySubjectRequest, request_id), user)


def _commit_case(db: Session, *steps) -> None:
    """Optimistische Sperre (row_version) + eindeutige Ereignis-Laufnummer:
    von zwei gleichzeitigen Schritten wirkt genau einer, der andere 409.
    ``steps`` (Audit, Ereignis) laufen in derselben Absicherung, weil schon ihr
    Flush die Versionspruefung ausloesen kann."""
    try:
        for step in steps:
            step()
        db.commit()
    except (StaleDataError, IntegrityError) as exc:
        db.rollback()
        raise_if_check_violation(exc)
        raise DomainError(
            ReasonCode.PRIVACY_CASE_CONCURRENT_UPDATE,
            "Der Fall wurde gleichzeitig geaendert; bitte neu laden und erneut ausfuehren", http_status=409,
        ) from exc


def _subject_event(db: Session, user: User, case: PrivacySubjectRequest, step: str,
                   extra: Optional[dict[str, Any]] = None) -> None:
    gov.case_events.append_event(db, PrivacySubjectRequestEvent, tenant_id=case.tenant_id, case_id=case.id,
                                 event_type=step, actor_id=user.id,
                                 payload={"status": case.status, **(extra or {})})


def _subject_request_out(db: Session, case: PrivacySubjectRequest) -> dict[str, Any]:
    out = gov.subject_requests.case_out(case)
    out["events"] = gov.case_events.events_out(db, PrivacySubjectRequestEvent, case.id)
    out["events_chain_ok"] = not gov.case_events.chain_problems(db, PrivacySubjectRequestEvent, case.id)
    return out


def _subject_request_step(db: Session, user: User, request: Request, case: PrivacySubjectRequest,
                          step: str, extra: Optional[dict[str, Any]] = None):
    _commit_case(
        db,
        lambda: _audit(db, user, request, table="privacy_subject_requests", record_id=case.id, action="UPDATE",
                       client_id=case.client_id, new_value={"step": step, "status": case.status, **(extra or {})}),
        lambda: _subject_event(db, user, case, step, extra),
    )
    return _subject_request_out(db, case)


@router.get("/subject-requests")
def list_subject_requests(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _require_case_operator(db, current_user)
    return [gov.subject_requests.case_out(case)
            for case in gov.subject_requests.list_requests(db, _tenant(current_user))]


@router.post("/subject-requests", status_code=201)
def open_subject_request(body: SubjectRequestOpen, request: Request, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    _require_case_operator(db, current_user)
    _client_in_scope(body.client_id, db, current_user)
    case = gov.subject_requests.open_request(
        db, tenant_id=_tenant(current_user), client_id=body.client_id, request_type=body.request_type,
        received_at=body.received_at, received_channel=body.received_channel,
        requester_relation=body.requester_relation, request_summary=body.request_summary,
        opened_by=current_user.id,
        deadline_days=gov.owner_values(db, _tenant(current_user)).get(gov.subject_requests.DEADLINE_POLICY_FIELD),
    )
    _audit(db, current_user, request, table="privacy_subject_requests", record_id=case.id, action="CREATE",
           client_id=case.client_id, new_value={"request_type": case.request_type, "due_at": case.due_at})
    _subject_event(db, current_user, case, "received", {"request_type": case.request_type, "due_at": case.due_at})
    _commit_case(db)
    return _subject_request_out(db, case)


@router.get("/subject-requests/{request_id}")
def get_subject_request(request_id: str, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    return _subject_request_out(db, _subject_request(db, request_id, current_user))


@router.post("/subject-requests/{request_id}/identity")
def verify_subject_request_identity(request_id: str, body: SubjectRequestIdentity, request: Request,
                                    db: Session = Depends(get_db),
                                    current_user: User = Depends(get_current_user)):
    case = gov.subject_requests.verify_identity(
        db, _subject_request(db, request_id, current_user), outcome=body.outcome, method=body.method,
        evidence_reference=body.evidence_reference, failure_reason=body.failure_reason, actor_id=current_user.id,
    )
    return _subject_request_step(db, current_user, request, case, "identity",
                                 {"identity_method": case.identity_method})


@router.post("/subject-requests/{request_id}/extension")
def extend_subject_request(request_id: str, body: SubjectRequestExtension, request: Request,
                           db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    case = gov.subject_requests.extend_deadline(
        db, _subject_request(db, request_id, current_user), extended_due_at=body.extended_due_at,
        reason=body.reason, notified_at=body.notified_at,
    )
    return _subject_request_step(db, current_user, request, case, "extension",
                                 {"extended_due_at": case.extended_due_at})


@router.post("/subject-requests/{request_id}/decision")
def decide_subject_request(request_id: str, body: SubjectRequestDecision, request: Request,
                           db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    case = gov.subject_requests.decide(
        db, _subject_request(db, request_id, current_user), decision=body.decision, reason=body.reason,
        scope=body.scope, actor_id=current_user.id,
    )
    return _subject_request_step(db, current_user, request, case, "decision", {"decision": case.decision})


@router.post("/subject-requests/{request_id}/export")
def export_subject_request(request_id: str, request: Request, db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    """Auskunft/Herausgabe: der einzige Weg zum Kundendatenexport."""
    case = _subject_request(db, request_id, current_user)
    document = gov.subject_requests.build_export(db, case, actor_id=current_user.id)
    _audit(db, current_user, request, table="privacy_subject_requests", record_id=case.id, action="EXPORT",
           client_id=case.client_id, new_value={"export_sha256": document["export_sha256"],
                                                "decision": case.decision})
    _subject_event(db, current_user, case, "export", {"export_sha256": document["export_sha256"]})
    _commit_case(db)
    return document


@router.post("/subject-requests/{request_id}/action")
def record_subject_request_action(request_id: str, body: SubjectRequestAction, request: Request,
                                  db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    case = gov.subject_requests.record_action(
        db, _subject_request(db, request_id, current_user), completion_note=body.completion_note,
        erasure_case_id=body.erasure_case_id, actor_id=current_user.id,
    )
    return _subject_request_step(db, current_user, request, case, "action",
                                 {"linked_erasure_case_id": case.linked_erasure_case_id})


@router.post("/subject-requests/{request_id}/delivery")
def record_subject_request_delivery(request_id: str, body: SubjectRequestDelivery, request: Request,
                                    db: Session = Depends(get_db),
                                    current_user: User = Depends(get_current_user)):
    case = gov.subject_requests.record_delivery(
        db, _subject_request(db, request_id, current_user), delivered_at=body.delivered_at,
        delivery_channel=body.delivery_channel, delivery_reference=body.delivery_reference,
        actor_id=current_user.id,
    )
    return _subject_request_step(db, current_user, request, case, "delivery",
                                 {"delivered_at": case.delivered_at, "export_sha256": case.export_sha256})


@router.post("/subject-requests/{request_id}/withdraw")
def withdraw_subject_request(request_id: str, body: SubjectRequestWithdrawal, request: Request,
                             db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    case = gov.subject_requests.withdraw(db, _subject_request(db, request_id, current_user), reason=body.reason)
    return _subject_request_step(db, current_user, request, case, "withdraw")


# ── H10 C-DSG-03: Egress-Manifest ──────────────────────────────────────────────

def install_egress_guard() -> None:
    """Beim App-Start (main.py lifespan): Laufzeitschutz fuer ausgehende
    Verbindungen gemaess Egress-Manifest einschalten."""
    gov.activate_egress_guard(_database.SessionLocal)


def uninstall_egress_guard() -> None:
    gov.deactivate_egress_guard()


@router.get("/egress-manifest")
def get_egress_manifest(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Alle ausgehenden Kanaele mit Staat/Garantie (Owner-Felder), Laufzeit-
    status (aktiv, erlaubt, bestaetigt) und den zuletzt blockierten Versuchen
    (nur Kanal, Host, Grund)."""
    return gov.egress_view(db, _tenant(current_user))


# ── H10 C-DSG-04: Register der Verletzungen der Datensicherheit ────────────────

class IncidentRecord(BaseModel):
    discovered_at: str
    incident_type: str
    description: str = Field(min_length=1, max_length=8000)
    affected_data_categories: list[str] = Field(default_factory=list)
    affected_subjects_count: Optional[int] = None
    containment_measures: Optional[str] = Field(default=None, max_length=8000)


class IncidentAssessment(BaseModel):
    risk_level: str
    rationale: Optional[str] = Field(default=None, max_length=8000)


class IncidentDecision(BaseModel):
    decision: str
    reason: Optional[str] = Field(default=None, max_length=8000)


class IncidentNotification(BaseModel):
    notified_at: str
    reference: Optional[str] = Field(default=None, max_length=2000)


class IncidentSubjectNotification(BaseModel):
    notified_at: str
    channel: str
    reference: Optional[str] = Field(default=None, max_length=2000)


class IncidentEvidence(BaseModel):
    kind: str
    reference: Optional[str] = Field(default=None, max_length=2000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="SHA-256 des Nachweis-Artefakts (Kleinbuchstaben)")
    media_type: str = Field(min_length=3, max_length=200, description="Medientyp, z. B. application/pdf")
    size_bytes: int = Field(ge=0, description="Groesse des Artefakts in Bytes")


class ArtifactVerification(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IncidentClosure(BaseModel):
    note: Optional[str] = Field(default=None, max_length=8000)


def _require_staff(user: User) -> None:
    if user.role not in ("admin", "super_admin", "advisor"):
        raise HTTPException(status_code=403, detail="Nur fuer Mitarbeitende")


def _incident(db: Session, incident_id: str, user: User) -> PrivacySecurityIncident:
    _require_case_operator(db, user)
    return _own(db.get(PrivacySecurityIncident, incident_id), user)


def _incident_integrity_problems(db: Session, incident: PrivacySecurityIncident) -> list[str]:
    problems = gov.case_events.chain_problems(db, PrivacySecurityIncidentEvent, incident.id)
    events = gov.case_events.list_events(db, PrivacySecurityIncidentEvent, incident.id)
    hashes = {e.event_sha256: e.artifact_sha256 for e in events if e.artifact_sha256}
    return problems + gov.incidents.artifact_problems(db, incident.id, hashes)


def _incident_out(db: Session, incident: PrivacySecurityIncident) -> dict[str, Any]:
    out = gov.incidents.incident_out(incident)
    out["events"] = gov.case_events.events_out(db, PrivacySecurityIncidentEvent, incident.id)
    out["artifacts"] = gov.incidents.artifacts_out(db, incident.id)
    out["evidence_chain_ok"] = not _incident_integrity_problems(db, incident)
    return out


def _incident_step(db: Session, user: User, request: Request, incident: PrivacySecurityIncident, step: str,
                   extra: Optional[dict[str, Any]] = None, artifact_sha256: Optional[str] = None):
    _commit_case(
        db,
        lambda: _audit(db, user, request, table="privacy_security_incidents", record_id=incident.id,
                       action="UPDATE", new_value={"step": step, "status": incident.status, **(extra or {})}),
        lambda: gov.case_events.append_event(db, PrivacySecurityIncidentEvent, tenant_id=incident.tenant_id,
                                             case_id=incident.id, event_type=step, actor_id=user.id,
                                             payload={"status": incident.status, **(extra or {})},
                                             artifact_sha256=artifact_sha256),
    )
    return _incident_out(db, incident)


@router.post("/incidents", status_code=201)
def record_security_incident(body: IncidentRecord, request: Request, db: Session = Depends(get_db),
                             current_user: User = Depends(get_current_user)):
    """Jede Mitarbeiterin und jeder Mitarbeiter kann einen Vorfall erfassen;
    Bewertung und Entscheide nur Administration/benannte Datenschutzpersonen."""
    _require_staff(current_user)
    incident = gov.incidents.record_incident(
        db, tenant_id=_tenant(current_user), discovered_at=body.discovered_at, incident_type=body.incident_type,
        description=body.description, affected_data_categories=body.affected_data_categories,
        allowed_categories=gov.incident_data_categories(), affected_subjects_count=body.affected_subjects_count,
        containment_measures=body.containment_measures, recorded_by=current_user.id,
    )
    _audit(db, current_user, request, table="privacy_security_incidents", record_id=incident.id, action="CREATE",
           new_value={"reference": incident.reference, "incident_type": incident.incident_type})
    gov.case_events.append_event(db, PrivacySecurityIncidentEvent, tenant_id=incident.tenant_id,
                                 case_id=incident.id, event_type="recorded", actor_id=current_user.id,
                                 payload={"reference": incident.reference, "incident_type": incident.incident_type})
    _commit_case(db)
    return _incident_out(db, incident)


@router.get("/incidents")
def list_security_incidents(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _require_case_operator(db, current_user)
    return [gov.incidents.incident_out(i) for i in gov.incidents.list_incidents(db, _tenant(current_user))]


@router.get("/incidents/gate")
def security_incident_gate(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Gate: hohes Risiko ohne Meldeentscheid bzw. ohne Meldenachweis ist rot."""
    _require_case_operator(db, current_user)
    return gov.incident_gate(db, _tenant(current_user))


@router.get("/incidents/{incident_id}")
def get_security_incident(incident_id: str, db: Session = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    return _incident_out(db, _incident(db, incident_id, current_user))


@router.post("/incidents/{incident_id}/assessment")
def assess_security_incident(incident_id: str, body: IncidentAssessment, request: Request,
                             db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    incident = gov.incidents.assess_risk(db, _incident(db, incident_id, current_user), risk_level=body.risk_level,
                                         rationale=body.rationale, actor_id=current_user.id)
    return _incident_step(db, current_user, request, incident, "assessment", {"risk_level": incident.risk_level})


@router.post("/incidents/{incident_id}/notification-decision")
def decide_security_incident_notification(incident_id: str, body: IncidentDecision, request: Request,
                                          db: Session = Depends(get_db),
                                          current_user: User = Depends(get_current_user)):
    incident = gov.incidents.decide_notification(
        db, _incident(db, incident_id, current_user), decision=body.decision, reason=body.reason,
        actor_id=current_user.id,
        escalation_contact=gov.owner_values(db, _tenant(current_user)).get(gov.incidents.ESCALATION_CONTACT_FIELD),
    )
    return _incident_step(db, current_user, request, incident, "notification_decision",
                          {"notification_decision": incident.notification_decision})


@router.post("/incidents/{incident_id}/edoeb-notification")
def record_security_incident_edoeb_notification(incident_id: str, body: IncidentNotification, request: Request,
                                                db: Session = Depends(get_db),
                                                current_user: User = Depends(get_current_user)):
    incident = gov.incidents.record_edoeb_notification(db, _incident(db, incident_id, current_user),
                                                       notified_at=body.notified_at, reference=body.reference,
                                                       actor_id=current_user.id)
    return _incident_step(db, current_user, request, incident, "edoeb_notification",
                          {"edoeb_notified_at": incident.edoeb_notified_at})


@router.post("/incidents/{incident_id}/subject-notification-decision")
def decide_security_incident_subject_notification(incident_id: str, body: IncidentDecision, request: Request,
                                                  db: Session = Depends(get_db),
                                                  current_user: User = Depends(get_current_user)):
    incident = gov.incidents.decide_subject_notification(db, _incident(db, incident_id, current_user),
                                                         decision=body.decision, reason=body.reason,
                                                         actor_id=current_user.id)
    return _incident_step(db, current_user, request, incident, "subject_notification_decision",
                          {"subject_notification_decision": incident.subject_notification_decision})


@router.post("/incidents/{incident_id}/subject-notification")
def record_security_incident_subject_notification(incident_id: str, body: IncidentSubjectNotification,
                                                  request: Request, db: Session = Depends(get_db),
                                                  current_user: User = Depends(get_current_user)):
    incident = gov.incidents.record_subject_notification(db, _incident(db, incident_id, current_user),
                                                         notified_at=body.notified_at, channel=body.channel,
                                                         reference=body.reference, actor_id=current_user.id)
    return _incident_step(db, current_user, request, incident, "subject_notification",
                          {"subjects_notified_at": incident.subjects_notified_at})


@router.post("/incidents/{incident_id}/evidence")
def add_security_incident_evidence(incident_id: str, body: IncidentEvidence, request: Request,
                                   db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    incident = gov.incidents.add_evidence(db, _incident(db, incident_id, current_user), kind=body.kind,
                                          reference=body.reference, sha256=body.sha256, actor_id=current_user.id)

    def event_and_artifact():
        event = gov.case_events.append_event(
            db, PrivacySecurityIncidentEvent, tenant_id=incident.tenant_id, case_id=incident.id,
            event_type="evidence", actor_id=current_user.id,
            payload={"status": incident.status, "kind": body.kind, "media_type": body.media_type,
                     "size_bytes": body.size_bytes},
            artifact_sha256=body.sha256)
        gov.incidents.record_artifact(db, incident, kind=body.kind, reference=body.reference, sha256=body.sha256,
                                      media_type=body.media_type, size_bytes=body.size_bytes,
                                      actor_id=current_user.id, event_sha256=event.event_sha256)

    _commit_case(
        db,
        lambda: _audit(db, current_user, request, table="privacy_security_incidents", record_id=incident.id,
                       action="UPDATE", new_value={"step": "evidence", "kind": body.kind, "sha256": body.sha256}),
        event_and_artifact,
    )
    return _incident_out(db, incident)


@router.post("/incidents/{incident_id}/artifacts/{artifact_id}/verify")
def verify_security_incident_artifact(incident_id: str, artifact_id: str, body: ArtifactVerification,
                                      db: Session = Depends(get_db),
                                      current_user: User = Depends(get_current_user)):
    """Vorgelegtes Artefakt gegen den erfassten Digest pruefen (Austausch oder
    Veraenderung -> 409 INCIDENT_EVIDENCE_HASH_MISMATCH)."""
    return gov.incidents.verify_artifact(db, _incident(db, incident_id, current_user), artifact_id, body.sha256)


@router.post("/incidents/{incident_id}/notification-note")
def add_security_incident_notification_note(incident_id: str, body: IncidentClosure, request: Request,
                                            db: Session = Depends(get_db),
                                            current_user: User = Depends(get_current_user)):
    """N-899-05: Aenderung zum Meldeentscheid nur als neues, begruendetes
    Ereignis; der bisherige Entscheid wird nicht aufgehoben."""
    incident = _incident(db, incident_id, current_user)
    note = gov.incidents.notification_note(db, incident, reason=body.note)
    return _incident_step(db, current_user, request, incident, "notification_note",
                          {"note": note, "notification_decision": incident.notification_decision})


@router.post("/incidents/{incident_id}/remediation")
def record_security_incident_remediation(incident_id: str, body: IncidentClosure, request: Request,
                                         db: Session = Depends(get_db),
                                         current_user: User = Depends(get_current_user)):
    incident = gov.incidents.record_remediation(db, _incident(db, incident_id, current_user), note=body.note,
                                                actor_id=current_user.id)
    return _incident_step(db, current_user, request, incident, "remediation")


@router.post("/incidents/{incident_id}/close")
def close_security_incident(incident_id: str, body: IncidentClosure, request: Request,
                            db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    incident = _incident(db, incident_id, current_user)
    if _incident_integrity_problems(db, incident):
        raise DomainError(
            ReasonCode.INCIDENT_EVIDENCE_HASH_MISMATCH,
            "Ereignis-/Nachweiskette des Vorfalls ist nicht unversehrt; Abschluss gesperrt", http_status=409,
        )
    incident = gov.incidents.close(db, incident, note=body.note, actor_id=current_user.id)
    return _incident_step(db, current_user, request, incident, "close")

# ── H10 Nachtrag 1: Freigaben des Verzeichnisses und des Egress-Manifests ──────

class VersionApproval(BaseModel):
    keys: list[str] = Field(default_factory=list, description="leer = alle Bearbeitungen bzw. Kanaele")


@router.post("/processing-register/approve")
def approve_processing_register(body: VersionApproval, request: Request, db: Session = Depends(get_db),
                                current_user: User = Depends(get_current_user)):
    """Neue, freigegebene Fassung je Bearbeitung (append-only, Content-Hash).
    Nur ohne offene Pflichtangaben und mit vollstaendigem Register."""
    _require_case_operator(db, current_user)
    tenant = _tenant(current_user)
    view = gov.register_view(db, tenant)
    if view.get("problems"):
        raise DomainError(ReasonCode.PROCESSING_REGISTER_UNAVAILABLE, "; ".join(view["problems"]), http_status=409)
    if view.get("open_blocking_fields"):
        raise DomainError(ReasonCode.PRIVACY_OWNER_VALUES_OPEN,
                          "Angaben des Verantwortlichen fehlen; Freigabe nicht moeglich", http_status=409,
                          extra={"open_fields": view["open_blocking_fields"]})
    rows = gov.versions.approve_register(db, tenant, gov.owner_values(db, tenant), actor_id=current_user.id,
                                         keys=body.keys or None)
    _audit(db, current_user, request, table="processing_activity_versions", record_id="approve", action="APPROVE",
           new_value={"activities": [r.activity_key for r in rows], "hashes": [r.content_sha256 for r in rows]})
    _commit_case(db)
    return gov.register_view(db, tenant)


@router.post("/egress-manifest/approve")
def approve_egress_manifest(body: VersionApproval, request: Request, db: Session = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    """Neue, freigegebene Fassung je Kanal (append-only, Content-Hash). Der
    Laufzeitschutz laesst einen Kanal nur mit wirksamer Fassung zu, deren Hash
    dem aktuellen Manifest samt Owner-Angaben entspricht."""
    _require_case_operator(db, current_user)
    tenant = _tenant(current_user)
    view = gov.egress_view(db, tenant)
    if not view.get("available") or view.get("problems"):
        raise DomainError(ReasonCode.EGRESS_MANIFEST_MISSING, "; ".join(view.get("problems") or []), http_status=409)
    rows = gov.versions.approve_manifest(db, tenant, gov.owner_values(db, tenant), actor_id=current_user.id,
                                         keys=body.keys or None)
    _audit(db, current_user, request, table="outbound_processing_manifest_versions", record_id="approve",
           action="APPROVE", new_value={"channels": [r.channel_id for r in rows]})
    _commit_case(db)
    gov.refresh_egress_confirmations(db, tenant)
    return gov.egress_view(db, tenant)


@router.get("/egress-events")
def list_egress_events(limit: int = 200, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Persistentes Protokoll blockierter Verbindungen (ohne Payload)."""
    rows = (db.query(OutboundProcessingEvent).filter(OutboundProcessingEvent.tenant_id == _tenant(current_user))
            .order_by(OutboundProcessingEvent.occurred_at.desc()).limit(max(1, min(limit, 1000))).all())
    return [{"occurred_at": r.occurred_at, "channel_id": r.channel_id, "channel_class": r.channel_class,
             "destination_host": r.destination_host, "reason_code": r.reason_code, "result": r.result,
             "manifest_version": r.manifest_version, "channel_sha256": r.channel_sha256,
             "manifest_sha256": r.manifest_sha256, "payload_schema_hash": r.payload_schema_hash} for r in rows]


# ── H10 Nachtrag 2: kein stiller Ausfall bei gesperrter Datenuebermittlung ─────

@router.get("/egress-status")
def get_egress_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Fuer das Banner auf jeder Seite (alle Mitarbeitenden): gesperrte Kanaele
    mangels Freigabe, Kurs-Datenstand; ``is_admin`` steuert den Direktlink."""
    _require_staff(current_user)
    status = gov.egress_status(db)
    status["is_admin"] = current_user.role in ("admin", "super_admin")
    return status


@router.get("/egress-counts")
def list_egress_counts(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Erlaubte Uebertragungen je Kanal und Tag (nur Zaehler, ohne Inhalt)."""
    rows = (db.query(OutboundTransferDailyCount)
            .filter(OutboundTransferDailyCount.tenant_id == _tenant(current_user))
            .order_by(OutboundTransferDailyCount.day.desc(), OutboundTransferDailyCount.channel_id).limit(500).all())
    return [{"day": r.day, "channel_id": r.channel_id, "allowed_count": r.allowed_count} for r in rows]
