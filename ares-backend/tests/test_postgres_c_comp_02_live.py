"""C-COMP-02 live auf PostgreSQL unter FORCE RLS (CI-Job ``postgres-rls``).

Echte Migrationskette bis Head, App-Rolle ohne Superuser/BYPASSRLS, zwei
Mandanten:

* Nachweise/Snapshots nur im eigenen Mandanten sichtbar (Negativkontrolle);
* append-only-Trigger und Tenant-Grenze in der Datenbank;
* zwei echte Transaktionen: ein Widerruf wartet auf den Commit des Snapshots
  und macht den Lauf danach sofort ungueltig -- auch fuer Plattform-Nachweise,
  deren Zeilen die App-Rolle nicht sperren darf (Advisory-Sperre);
* Widerruf vor der Revalidierung: kein Snapshot, kein Lauf.

Ohne ``POSTGRES_TEST_DATABASE_URL`` uebersprungen.
"""
from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

import main as _model_registry  # noqa: F401
import services.product_eligibility as evidence
from core import product_evidence as contract
from core.reason_codes import DomainError
from models.mandates import Mandate
from models.product_eligibility import ProductEvidenceItem, ProductEvidenceSnapshot
from models.review import Product, RecommendationPosition, RecommendationRun
from product_evidence_test_support import synthetic_values
from tests.test_postgres_mandate_evidence_tenant_boundary_live import (  # noqa: F401
    POSTGRES_URL, _alembic_cfg, _mandate, _qi, _scoped_url, pytestmark,
)
from tests.test_tenant_database_boundary import _raw_insert

NOW = "2026-11-25T00:00:00.000000Z"


@pytest.fixture(scope="module")
def pg():
    pytest.importorskip("psycopg")
    from alembic import command

    from services.postgres_rls import ensure_postgres_rls_policies
    from services.tenant_context import attach_tenant_context_reset

    token = uuid.uuid4().hex[:12]
    schema, role, password = f"ccomp2_{token}", f"ccomp2_app_{token}", f"pw_{token}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    scoped = _scoped_url(POSTGRES_URL, schema)
    owner = create_engine(scoped, future=True)
    app = None
    try:
        command.upgrade(_alembic_cfg(scoped), "head")
        with owner.begin() as conn:
            for tid in ("t-a", "t-b"):
                _raw_insert(conn, "tenants", id=tid, display_name=tid, slug=tid)
            for uid, tid in (("adv", "t-a"), ("adv2", "t-a"), ("adv-b", "t-b")):
                _raw_insert(conn, "users", id=uid, username=uid, tenant_id=tid)
            for mid, cid, tid in (("m-a", "c-a", "t-a"), ("m-b", "c-b", "t-b")):
                _raw_insert(conn, "clients", id=cid, client_number=cid, tenant_id=tid)
                _mandate(conn, mid, cid, tid)
            conn.execute(text(
                "INSERT INTO optimizer_policies (id, policy_name, version, is_current, valid_from, optimizer_engine, "
                "max_real_estate_bps, max_alternatives_bps, min_liquidity_bps, allow_other_assets_for_goals, "
                "created_by, created_at, updated_at) VALUES ('op-c', 'C', 1, 1, '2026-01-01', 'goal_based_v1', "
                "10000, 10000, 0, 0, 'adv', :n, :n)"
            ), {"n": NOW})
            ensure_postgres_rls_policies(conn)
            conn.execute(text(f"CREATE ROLE {_qi(role)} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{password}'"))
            conn.execute(text(f"GRANT USAGE ON SCHEMA {_qi(schema)} TO {_qi(role)}"))
            conn.execute(text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {_qi(schema)} TO {_qi(role)}"
            ))
        with sessionmaker(bind=owner)() as db:
            for pid, tid in (("p-a", "t-a"), ("p-g", None), ("p-race", "t-a"), ("p-b", "t-b")):
                db.add(Product(
                    id=pid, tenant_id=tid, product_name=pid, provider="Synthetisch", product_type="Fonds",
                    asset_class="Aktien", sub_asset_class="Aktien Schweiz", currency="CHF", ter_bps=25, is_active=1,
                    created_at=NOW, updated_at=NOW))
            db.commit()
            for pid, tid, creator in (("p-a", "t-a", "adv"), ("p-g", None, "adv"), ("p-race", "t-a", "adv"),
                                      ("p-b", "t-b", "adv-b")):
                product = db.get(Product, pid)
                rows = [evidence.create_product_evidence_draft(
                    db, product, values=synthetic_values(product, kind), tenant_id=tid, actor_id=creator)
                    for kind in contract.PRODUCT_EVIDENCE_KINDS]
                db.flush()
                evidence.approve_product_evidence_items(
                    db, product, seen=[(r.id, r.canonical_payload_hash) for r in rows], tenant_id=tid,
                    actor_id="adv2", is_same_person=lambda _c: False, approver_ids=[], attestation=None,
                    min_attestation_length=1)
            db.commit()
        app_url = make_url(scoped).set(username=role, password=password).render_as_string(hide_password=False)
        app = create_engine(app_url, future=True, pool_size=4, max_overflow=0)
        attach_tenant_context_reset(app)
        yield {"app": app, "owner": owner}
    finally:
        if app is not None:
            app.dispose()
        owner.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
            conn.execute(text(f"DROP ROLE IF EXISTS {_qi(role)}"))
        admin.dispose()


def _session(ctx, tenant, engine="app"):
    from services.tenant_context import set_tenant_context

    session = sessionmaker(bind=ctx[engine], expire_on_commit=False)()
    set_tenant_context(session, tenant)
    return session


def _run(db, product_id):
    run = RecommendationRun(
        id=f"run-{uuid.uuid4().hex[:8]}", mandate_id="m-a", client_id="c-a", policy_id="op-c", run_type="Optimizer",
        result_status="Draft", created_by="adv", created_at=NOW, updated_at=NOW)
    db.add(run)
    db.flush()
    db.add(RecommendationPosition(id=uuid.uuid4().hex, run_id=run.id, product_id=product_id, target_weight_bps=10_000,
                                  created_at=NOW, updated_at=NOW))
    db.flush()
    return run, db.get(Mandate, "m-a")


def _kid(db, product_id):
    return db.query(ProductEvidenceItem).filter_by(
        product_id=product_id, evidence_kind="kid", status="approved").one()


def test_rls_hides_foreign_items_and_snapshots(pg):
    with _session(pg, "t-a") as db:
        run, mandate = _run(db, "p-a")
        snapshot_id = evidence.snapshot_run_product_evidence(db, mandate, run).id
        db.commit()
    with _session(pg, "t-a") as db:
        assert {r[0] for r in db.query(ProductEvidenceItem.product_id).distinct()} == {"p-a", "p-g", "p-race"}
        assert db.get(ProductEvidenceSnapshot, snapshot_id) is not None
    with _session(pg, "t-b") as db:
        assert {r[0] for r in db.query(ProductEvidenceItem.product_id).distinct()} == {"p-g", "p-b"}
        assert db.get(ProductEvidenceSnapshot, snapshot_id) is None
    with _session(pg, None) as db:
        assert {r[0] for r in db.query(ProductEvidenceItem.product_id).distinct()} == {"p-g"}
        assert db.query(ProductEvidenceSnapshot).count() == 0


@pytest.mark.parametrize("statement", [
    "UPDATE product_evidence_items SET note = 'x' WHERE product_id = 'p-a'",
    "UPDATE product_evidence_items SET canonical_payload_hash = repeat('0', 64) WHERE product_id = 'p-a'",
    "DELETE FROM product_evidence_items WHERE product_id = 'p-a'",
    "UPDATE product_evidence_snapshots SET status = 'stale'",
    "DELETE FROM product_evidence_snapshots",
])
def test_append_only_for_app_and_owner(pg, statement):
    with _session(pg, "t-a") as db:
        run, mandate = _run(db, "p-a")
        evidence.snapshot_run_product_evidence(db, mandate, run)
        db.commit()
    for engine in ("app", "owner"):
        with _session(pg, "t-a", engine) as db, pytest.raises(DBAPIError, match="unver"):
            db.execute(text(statement))


def test_database_rejects_item_of_foreign_tenant_product(pg):
    with _session(pg, "t-a", "owner") as db:
        product = db.get(Product, "p-b")
        evidence.create_product_evidence_draft(
            db, product, values=synthetic_values(product, "kid"), tenant_id="t-a", actor_id="adv")
        with pytest.raises(DBAPIError, match="verschiedenen Tenants"):
            db.flush()


@pytest.mark.parametrize("product_id,closer_engine,closer_tenant", [
    ("p-race", "app", "t-a"),   # Tenant-Zeile: FOR UPDATE + Advisory-Sperre
    ("p-g", "owner", None),      # Plattform-Zeile: nur Advisory-Sperre moeglich
])
def test_revocation_waits_for_snapshot_commit_and_is_effective_afterwards(pg, product_id, closer_engine, closer_tenant):
    started, finished, errors = threading.Event(), threading.Event(), []

    def revoke():
        try:
            with _session(pg, closer_tenant, closer_engine) as other:
                row = _kid(other, product_id)
                started.set()
                evidence.close_product_evidence_item(other, row, status="revoked", reason="LIVE_RACE", actor_id="adv2")
                other.commit()
        except Exception as exc:  # noqa: BLE001 - im Hauptthread ausgewertet
            errors.append(exc)
        finally:
            finished.set()

    with _session(pg, "t-a") as db:
        run, mandate = _run(db, product_id)
        evidence.snapshot_run_product_evidence(db, mandate, run)
        run_id = run.id
        worker = threading.Thread(target=revoke)
        worker.start()
        assert started.wait(20)
        assert not finished.wait(2), "Widerruf lief trotz Sperre durch"
        db.commit()
    worker.join(30)
    assert finished.is_set() and not errors, errors
    with _session(pg, "t-a") as db:
        with pytest.raises(DomainError) as exc:
            evidence.assert_run_product_evidence(
                db, db.get(Mandate, "m-a"), db.get(RecommendationRun, run_id), channel="t")
        assert exc.value.reason_code == "PRODUCT_EVIDENCE_REVOKED"


def test_revocation_committed_between_check_and_lock_leaves_no_snapshot(pg, monkeypatch):
    original, raced = evidence.evaluate_product_evidence, []

    def racing(session, mandate, product, **kw):
        result = original(session, mandate, product, **kw)
        if not raced:
            raced.append(True)
            with _session(pg, "t-a") as other:
                evidence.close_product_evidence_item(
                    other, _kid(other, "p-a"), status="revoked", reason="LIVE_RACE", actor_id="adv2")
                other.commit()
        return result

    monkeypatch.setattr(evidence, "evaluate_product_evidence", racing)
    with _session(pg, "t-a") as db:
        run, mandate = _run(db, "p-a")
        run_id = run.id
        with pytest.raises(DomainError) as exc:
            evidence.snapshot_run_product_evidence(db, mandate, run)
        assert exc.value.reason_code == "PRODUCT_EVIDENCE_REVOKED"
        db.rollback()
    with pg["owner"].connect() as conn:
        for sql in ("SELECT count(*) FROM product_evidence_snapshots WHERE recommendation_run_id = :r",
                    "SELECT count(*) FROM recommendation_runs WHERE id = :r",
                    "SELECT count(*) FROM recommendation_positions WHERE run_id = :r"):
            assert conn.execute(text(sql), {"r": run_id}).scalar() == 0
