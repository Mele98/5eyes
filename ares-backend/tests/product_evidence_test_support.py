"""Synthetische Produktevidenz ueber den echten Draft-/Freigabepfad."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Request

from database import new_uuid
from models.product_eligibility import PRODUCT_EVIDENCE_KINDS
from models.users import User
from routers.review import approve_product_evidence, create_product_evidence
from schemas.review import ProductEvidenceApprovalRequest, ProductEvidenceItemCreate


def _request() -> Request:
    return Request({
        "type": "http", "method": "POST", "path": "/products/test/evidence",
        "headers": [], "client": ("127.0.0.1", 0), "server": ("test", 80),
        "scheme": "http", "query_string": b"",
    })


def _four_eyes_users(db, *, actor_id: str, tenant_id: str) -> tuple[User, User]:
    creator = db.get(User, actor_id)
    if creator is None:
        raise AssertionError("Der Test-Nachweis benötigt eine vorhandene Erstellerperson.")
    approver = db.query(User).filter(
        User.tenant_id == tenant_id,
        User.id != actor_id,
        User.role.in_(("admin", "super_admin", "compliance_reviewer")),
        User.is_active == 1,
    ).order_by(User.id).first()
    if approver is None:
        now = datetime.now(timezone.utc).isoformat()
        uid = new_uuid()
        approver = User(
            id=uid, tenant_id=tenant_id, username=f"evidence-approver-{uid}",
            password_hash="synthetic-test-only", full_name="Synthetische Zweitfreigabe",
            email=f"{uid}@example.invalid", role="compliance_reviewer", is_active=1,
            created_at=now, updated_at=now,
        )
        db.add(approver)
        db.flush()
    return creator, approver


def add_synthetic_product_evidence(db, products, *, actor_id: str, tenant_id: str,
                                   jurisdiction: str = "CH") -> None:
    now = datetime.now(timezone.utc)
    today = now.date()
    creator, approver = _four_eyes_users(db, actor_id=actor_id, tenant_id=tenant_id)
    for product in products:
        stable = str(product.isin or product.internal_product_id or product.figi or product.id)
        for kind in PRODUCT_EVIDENCE_KINDS:
            payload = {
                "classification": "synthetic_test_fixture", "evidence_kind": kind,
                "status": "not_applicable" if kind == "kid" else "synthetic",
            }
            if kind == "costs":
                payload.update(value=int(product.ter_bps or 0), unit="bps_per_year")
            if kind == "retrocession":
                payload.update(value=int(product.retrocession_bps or 0), unit="bps_per_year")
            source = f"synthetic-test:{product.id}:{kind}"
            import hashlib

            draft = create_product_evidence(
                product.id,
                ProductEvidenceItemCreate(
                    stable_instrument_id=stable, share_class_id=product.share_class_figi,
                    jurisdiction=jurisdiction, evidence_kind=kind,
                    source_type="synthetic_test_fixture", source_reference=source,
                    source_document_title="Synthetischer Testnachweis",
                    source_document_version="1", source_document_date=today,
                    retrieved_at=now,
                    source_document_sha256=hashlib.sha256(source.encode()).hexdigest(),
                    payload=payload, as_of=today, valid_from=today,
                ),
                _request(), db, creator,
            )
            approved = approve_product_evidence(
                draft.id, ProductEvidenceApprovalRequest(approval_mode="four_eyes"),
                _request(), db, approver,
            )
            assert approved.status == "approved" and approved.approved_by != approved.created_by
