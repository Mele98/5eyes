"""C-COMP-02: Product-Evidence v1, fail-closed und P5-bindbar."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.reason_codes import DomainError, ReasonCode
from database import Base
from models.product_eligibility import PRODUCT_EVIDENCE_KINDS, ProductEvidenceItem
from models.review import Product, RecommendationPosition, RecommendationRun
from services.product_eligibility import (
    assert_run_product_evidence,
    canonical_product_evidence_json,
    evaluate_product_evidence,
    product_evidence_hash,
    product_evidence_item_payload_hash,
    run_product_evidence_values,
    snapshot_run_product_evidence,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'product-evidence.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _product(product_id: str = "product-1", *, name: str = "Synthetisches Kundenprodukt") -> Product:
    now = _now()
    return Product(
        id=product_id, tenant_id=None, product_name=name, provider="Synthetischer Anbieter",
        product_type="Fonds", asset_class="Aktien", sub_asset_class="Aktien Schweiz",
        currency="CHF", ter_bps=25, is_active=1, created_at=now, updated_at=now,
    )


def _add_evidence(db, product: Product, kind: str, *, item_id: str | None = None,
                  status: str = "approved", valid_until: str | None = None,
                  supersedes_id: str | None = None) -> ProductEvidenceItem:
    today = datetime.now(timezone.utc).date().isoformat()
    payload = {"kind": kind, "status": "not_applicable" if kind in {"kid", "retrocession"} else "synthetic"}
    if kind == "costs":
        payload["value"] = 25
    canonical, payload_hash = product_evidence_item_payload_hash(payload)
    reference = f"synthetic-test:{product.id}:{kind}:{item_id or 'v1'}"
    row = ProductEvidenceItem(
        id=item_id or f"e-{kind}", tenant_id="tenant-1", product_id=product.id,
        stable_instrument_id=product.id, share_class_id=None, jurisdiction="CH",
        evidence_kind=kind, source_type="synthetic_test_fixture",
        source_reference=reference, source_document_title="Synthetischer Testnachweis",
        source_document_version="1", source_document_date=today, retrieved_at=_now(),
        source_document_sha256=hashlib.sha256(reference.encode()).hexdigest(),
        canonical_payload_json=canonical, canonical_payload_hash=payload_hash,
        as_of=today, valid_from=today, valid_until=valid_until, status=status,
        created_by="user-1", created_at=_now(), approved_by="user-2" if status == "approved" else None,
        approved_at=_now() if status == "approved" else None,
        approval_mode="four_eyes" if status == "approved" else None,
        supersedes_id=supersedes_id, updated_at=_now(),
    )
    db.add(row)
    db.flush()
    return row


def _complete(db, product: Product) -> list[ProductEvidenceItem]:
    return [_add_evidence(db, product, kind) for kind in PRODUCT_EVIDENCE_KINDS]


def _run_and_mandate(db, product: Product):
    now = _now()
    run = RecommendationRun(
        id="run-1", mandate_id="mandate-1", client_id="client-1", policy_id="policy-1",
        run_type="Optimizer", result_status="Draft", created_by="user-1", created_at=now,
        updated_at=now,
    )
    db.add(run)
    db.add(RecommendationPosition(
        id="position-1", run_id=run.id, product_id=product.id, target_weight_bps=10_000,
        created_at=now, updated_at=now,
    ))
    db.flush()
    mandate = SimpleNamespace(id="mandate-1", tenant_id="tenant-1", jurisdiction="CH")
    return run, mandate


def test_canonical_codec_is_domain_separated_and_rejects_binary_float():
    first = {"z": "e\u0301", "amount": 25, "nested": {"b": True, "a": None}}
    second = {"nested": {"a": None, "b": True}, "amount": 25, "z": "é"}
    assert canonical_product_evidence_json(first) == canonical_product_evidence_json(second)
    assert product_evidence_hash(first)[1] == product_evidence_hash(second)[1]
    assert product_evidence_hash(first)[1] != product_evidence_item_payload_hash(first)[1]
    with pytest.raises(ValueError, match="Binärfloat"):
        canonical_product_evidence_json({"amount": 0.1})


def test_missing_evidence_blocks_snapshot_then_complete_evidence_binds_run(db):
    product = _product()
    db.add(product)
    run, mandate = _run_and_mandate(db, product)

    with pytest.raises(DomainError) as exc:
        snapshot_run_product_evidence(db, mandate, run)
    assert exc.value.reason_code == ReasonCode.PRODUCT_EVIDENCE_MISSING
    assert run.product_evidence_snapshot_id is None

    _complete(db, product)
    snapshot = snapshot_run_product_evidence(db, mandate, run)
    assert snapshot.status == "verified"
    assert run.product_evidence_hash == snapshot.product_evidence_hash
    assert len(json.loads(snapshot.item_ids_json)) == len(PRODUCT_EVIDENCE_KINDS)
    assert assert_run_product_evidence(db, mandate, run, channel="test").id == snapshot.id
    values = run_product_evidence_values(db, mandate, run, channel="test")
    assert values[product.id]["costs"]["payload"]["value"] == 25
    assert values[product.id]["retrocession"]["payload"]["status"] == "not_applicable"


def test_unbound_draft_note_is_irrelevant_but_revoke_and_replacement_are_stale(db):
    product = _product()
    db.add(product)
    rows = _complete(db, product)
    run, mandate = _run_and_mandate(db, product)
    snapshot_run_product_evidence(db, mandate, run)

    draft = _add_evidence(db, product, "costs", item_id="draft-note", status="draft")
    draft.note = "Nur interne Notiz ohne Freigabe"
    db.flush()
    assert_run_product_evidence(db, mandate, run, channel="test")

    selected = next(row for row in rows if row.evidence_kind == "costs")
    selected.status = "revoked"
    selected.retired_or_revoked_by = "user-2"
    selected.retired_or_revoked_at = _now()
    selected.reason_code = "SOURCE_WITHDRAWN"
    selected.updated_at = _now()
    db.flush()
    with pytest.raises(DomainError) as revoked:
        assert_run_product_evidence(db, mandate, run, channel="test")
    assert revoked.value.reason_code == ReasonCode.PRODUCT_EVIDENCE_REVOKED

    replacement = _add_evidence(
        db, product, "costs", item_id="e-costs-v2", supersedes_id=selected.id,
    )
    assert replacement.status == "approved"
    with pytest.raises(DomainError) as stale:
        assert_run_product_evidence(db, mandate, run, channel="test")
    assert stale.value.reason_code == ReasonCode.PRODUCT_EVIDENCE_STALE


def test_snapshot_is_database_immutable(db):
    product = _product()
    db.add(product)
    _complete(db, product)
    run, mandate = _run_and_mandate(db, product)
    snapshot = snapshot_run_product_evidence(db, mandate, run)
    db.commit()
    snapshot.status = "stale"
    with pytest.raises(Exception, match="Snapshot ist unveränderlich"):
        db.flush()


def test_detector_control_tampered_payload_hash_is_rejected(db):
    product = _product()
    db.add(product)
    rows = _complete(db, product)
    db.commit()
    mandate = SimpleNamespace(id="mandate-1", tenant_id="tenant-1", jurisdiction="CH")
    # Detektorkontrolle: direkte Mutation eines freigegebenen Nachweises wird
    # bereits vom DB-Trigger verworfen.
    rows[0].canonical_payload_hash = "0" * 64
    with pytest.raises(Exception, match="freigegebener Nachweis ist unveränderlich"):
        db.flush()
    db.rollback()

    # Ein bereits korrupt importierter Datensatz darf auch beim Lesen nicht
    # als belegt gelten: Draft darf vor seiner Freigabe korrigiert werden.
    product = db.get(Product, "product-1")
    original = db.get(ProductEvidenceItem, "e-instrument_identity")
    original.status = "retired"
    original.retired_or_revoked_by = "user-2"
    original.retired_or_revoked_at = _now()
    original.reason_code = "SUPERSEDED"
    original.updated_at = _now()
    db.flush()
    corrupt = _add_evidence(db, product, "instrument_identity", item_id="corrupt", status="draft")
    corrupt.canonical_payload_hash = "0" * 64
    corrupt.status = "approved"
    corrupt.approved_by = "user-2"
    corrupt.approved_at = _now()
    corrupt.approval_mode = "four_eyes"
    db.flush()
    result = evaluate_product_evidence(db, mandate, product)
    assert result["status"] == "hash_mismatch"
    assert result["issues"][0]["reason_code"] == str(ReasonCode.PRODUCT_EVIDENCE_HASH_MISMATCH)
