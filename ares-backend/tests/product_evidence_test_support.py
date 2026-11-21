"""Explizite synthetische Produktevidenz fuer bestehende Erfolgspfad-Tests."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from database import new_uuid
from models.product_eligibility import PRODUCT_EVIDENCE_KINDS, ProductEvidenceItem
from services.product_eligibility import product_evidence_item_payload_hash


def add_synthetic_product_evidence(db, products, *, actor_id: str, tenant_id: str,
                                   jurisdiction: str = "CH") -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    now = datetime.now(timezone.utc).isoformat()
    for product in products:
        stable = str(product.isin or product.internal_product_id or product.figi or product.id)
        for kind in PRODUCT_EVIDENCE_KINDS:
            payload = {
                "classification": "synthetic_test_fixture", "evidence_kind": kind,
                "status": "not_applicable" if kind in {"kid", "retrocession"} else "synthetic",
            }
            if kind == "costs":
                payload.update(value=int(product.ter_bps or 0), unit="bps_per_year")
            canonical, payload_hash = product_evidence_item_payload_hash(payload)
            source = f"synthetic-test:{product.id}:{kind}"
            db.add(ProductEvidenceItem(
                id=new_uuid(), tenant_id=tenant_id, product_id=product.id,
                stable_instrument_id=stable, share_class_id=product.share_class_figi,
                jurisdiction=jurisdiction, evidence_kind=kind,
                source_type="synthetic_test_fixture", source_reference=source,
                source_document_title="Synthetischer Testnachweis",
                source_document_version="1", source_document_date=today,
                retrieved_at=now,
                source_document_sha256=hashlib.sha256(source.encode()).hexdigest(),
                canonical_payload_json=canonical, canonical_payload_hash=payload_hash,
                as_of=today, valid_from=today, status="approved",
                created_by=actor_id, created_at=now, approved_by=actor_id,
                approved_at=now, approval_mode="single_approver_attested", updated_at=now,
            ))
    db.flush()
