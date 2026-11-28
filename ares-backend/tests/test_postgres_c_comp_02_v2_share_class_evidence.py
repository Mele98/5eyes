"""C-COMP-02 V2 live auf PostgreSQL unter FORCE RLS (CI-Job ``postgres-rls``).

Vorab-Entscheide 6.1, 6.3 und 6.4 an der echten DB-Grenze (Migrationskette
bis Head, App-Rolle ohne Superuser/BYPASSRLS):

* 6.4: ein direkter INSERT (App-Rolle UND Eigentuemer, am Service vorbei)
  einer fremden/abweichenden Anteilsklassenzeile scheitert per Trigger; ein
  UPDATE der Identitaetsspalten ebenso; die passende Zeile ist Positivkontrolle;
* 6.3: ein Satz-Snapshot ohne die drei Dimensionsbindungen wird abgelehnt,
  der echte Bindeweg schreibt alle drei;
* 6.1: der Envelope-CHECK laesst V1 und V2 zu (V2 wird versiegelt).

Ohne ``POSTGRES_TEST_DATABASE_URL`` uebersprungen.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import services.product_eligibility as evidence
from core import product_evidence as contract
from models.product_eligibility import ProductEvidenceSnapshot
from tests.test_postgres_c_comp_02_live import NOW, _run, _session, pg  # noqa: F401
from tests.test_postgres_mandate_evidence_tenant_boundary_live import pytestmark  # noqa: F401

_ITEM_SQL = (
    "INSERT INTO product_evidence_items (id, tenant_id, product_id, stable_instrument_id, share_class_id, "
    "jurisdiction, evidence_kind, source_type, source_reference, source_document_title, retrieved_at, "
    "source_document_sha256, canonical_payload_json, canonical_payload_hash, as_of, valid_from, status, "
    "created_by, created_at, updated_at) VALUES (:id, 't-a', 'p-a', 'p-a', :share_class, 'CH', 'kid', "
    "'synthetic_test_fixture', 'synthetic-direct', 'Direkt', :now, repeat('a', 64), '{}', repeat('b', 64), "
    "'2026-11-25', '2026-11-25', 'draft', 'adv', :now, :now)"
)


@pytest.mark.parametrize("engine", ["app", "owner"])
@pytest.mark.parametrize("share_class", ["SC-OTHER", "  SC-FOREIGN  "])
def test_direct_insert_of_foreign_share_class_row_fails_at_database(pg, engine, share_class):  # noqa: F811
    with _session(pg, "t-a", engine) as db, pytest.raises(DBAPIError, match="PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH"):
        db.execute(text(_ITEM_SQL), {"id": f"direct-{engine}-{len(share_class)}", "share_class": share_class,
                                     "now": NOW})


@pytest.mark.parametrize("engine", ["app", "owner"])
def test_matching_direct_insert_is_the_positive_control_and_update_to_mismatch_fails(pg, engine):  # noqa: F811
    with _session(pg, "t-a", engine) as db:
        db.execute(text(_ITEM_SQL), {"id": f"match-{engine}", "share_class": None, "now": NOW})
        db.flush()
        with pytest.raises(DBAPIError, match="PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH"):
            with db.begin_nested():
                db.execute(text(
                    "UPDATE product_evidence_items SET share_class_id = 'SC-OTHER' WHERE id = :id"
                ), {"id": f"match-{engine}"})
        db.rollback()


def test_snapshot_without_dimension_binding_is_rejected_and_real_path_binds_all_three(pg):  # noqa: F811
    with _session(pg, "t-a") as db:
        run, mandate = _run(db, "p-a")
        snapshot = evidence.snapshot_run_product_evidence(db, mandate, run)
        payload = json.loads(snapshot.canonical_payload_json)
        for dimension, column in contract.DIMENSION_COLUMNS.items():
            assert getattr(snapshot, column) == payload["dimension_snapshots"][dimension]["snapshot_id"]
        values = {c.name: getattr(snapshot, c.name) for c in ProductEvidenceSnapshot.__table__.columns}
        db.commit()
    values.update({"id": "unbound-snapshot", "product_evidence_hash": "f" * 64, "cost_snapshot_id": None})
    with _session(pg, "t-a") as db, pytest.raises(DBAPIError, match="Konfliktsnapshot muessen gebunden"):
        db.add(ProductEvidenceSnapshot(**values))
        db.flush()


def test_envelope_schema_check_admits_v1_and_v2(pg):  # noqa: F811
    with _session(pg, None, "owner") as db:
        definition = db.execute(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_advisory_decision_envelopes_schema_version'"
        )).scalar()
    assert "ares/advisory-envelope/1" in definition and "ares/advisory-envelope/2" in definition
