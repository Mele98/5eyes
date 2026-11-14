"""CCX-P1 Snapshot und Hash live auf PostgreSQL unter FORCE RLS.

Echte Migrationskette bis Head in ein Wegwerf-Schema, Boot-RLS-Plan
(``ensure_postgres_rls_policies`` ohne Tabellenliste, wie ``init_db``), Probe
als NON-owner/NON-superuser/NOBYPASSRLS-Rolle mit zwei Mandanten:

* RLS ENABLE + FORCE und Policy fuer alle drei Tabellen; SELECT nur im
  eigenen Mandanten, ohne Kontext nichts;
* INSERT-Guard: gespoofter Mandant und fremdes Mandat werden abgelehnt;
  Bindung mit fremdem Mandanten scheitert am zusammengesetzten FK;
* Lebenszyklus: Einfuegen nur als DRAFT, Siegel nur mit Manifest-Bindung,
  SEALED append-only fuer App-Rolle UND Tabellen-Owner, einzig SEALED ->
  SUPERSEDED bei unveraendertem Inhalt;
* Parallelversiegelung mit zwei echten Transaktionen: genau ein Sieger
  (Unique ``ux_advisory_decision_envelopes_one_sealed`` bzw.
  ``..._one_successor``), der Verlierer wartet und scheitert nach dem Commit;
* upgrade -> downgrade (vor CCX-P1) -> upgrade.

Ohne ``POSTGRES_TEST_DATABASE_URL`` uebersprungen (CI-Job ``postgres-rls``).
"""
from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from tests.test_postgres_mandate_evidence_tenant_boundary_live import (  # noqa: F401
    POSTGRES_URL,
    _alembic_cfg,
    _mandate,
    _qi,
    _scoped_url,
    pytestmark,
)
from tests.test_tenant_database_boundary import _raw_insert

ENVELOPES = "advisory_decision_envelopes"
BINDINGS = "advisory_envelope_bindings"
MANIFESTS = "advisory_effective_input_manifests"
TABLES = (ENVELOPES, BINDINGS, MANIFESTS)
CCX_P1_PARENT = "e7b3d9f1a2c4"
NOW = "2026-11-14T00:00:00.000000Z"
H = "a" * 64


def _manifest(conn, row_id, mandate_id, **extra):
    values = {"id": row_id, "mandate_id": mandate_id, **{f"{c}_hash": H for c in (
        "client", "mandate", "goals", "cashflows", "risk", "preference", "cma", "policy", "constraints",
        "holdings")}, "engine_version": "e", "random_stream_id": "s", "rounding_policy_version": "ares-rounding/1",
        "manifest_hash": H, "created_at": NOW, "created_by": "adv"}
    values.update(extra)
    conn.execute(text(
        f"INSERT INTO {MANIFESTS} ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"
    ), values)


def _draft(conn, row_id, mandate_id, **extra):
    values = {"id": row_id, "mandate_id": mandate_id, "schema_version": "ares/advisory-envelope/1",
              "status": "DRAFT", "locale": "DE", "base_currency": "CHF", "created_at": NOW,
              "created_by": "adv", "optimistic_version": 1}
    values.update(extra)
    conn.execute(text(
        f"INSERT INTO {ENVELOPES} ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"
    ), values)


def _bind(conn, row_id, envelope_id, tenant_id, kind="effective_input_manifest", **extra):
    values = {"id": row_id, "tenant_id": tenant_id, "envelope_id": envelope_id, "binding_kind": kind,
              "object_type": MANIFESTS, "object_id": "man", "child_hash": H, "ordinal": 0,
              "created_at": NOW, "created_by": "adv"}
    values.update(extra)
    conn.execute(text(
        f"INSERT INTO {BINDINGS} ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"
    ), values)


def _seal(conn, envelope_id, digest):
    return conn.execute(text(
        f"UPDATE {ENVELOPES} SET status = 'SEALED', canonical_payload_json = '{{}}', envelope_hash = :h, "
        "sealed_at = :now, sealed_by = 'adv', optimistic_version = optimistic_version + 1 "
        "WHERE id = :id AND status = 'DRAFT'"
    ), {"id": envelope_id, "h": digest, "now": NOW}).rowcount


def _sealed_envelope(conn, envelope_id, mandate_id, tenant_id, digest):
    _manifest(conn, f"man-{envelope_id}", mandate_id, tenant_id=tenant_id)
    _draft(conn, envelope_id, mandate_id, tenant_id=tenant_id)
    _bind(conn, f"b-{envelope_id}", envelope_id, tenant_id)
    assert _seal(conn, envelope_id, digest) == 1


@pytest.fixture(scope="module")
def pg_ccx():
    pytest.importorskip("psycopg")
    from alembic import command

    from services.postgres_rls import ensure_postgres_rls_policies
    from services.tenant_context import attach_tenant_context_reset

    token = uuid.uuid4().hex[:12]
    schema, role, password = f"ccx_{token}", f"ccx_app_{token}", f"pw_{token}"
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
            _raw_insert(conn, "users", id="adv", tenant_id="t-a")
            for cid, tid in (("c-a", "t-a"), ("c-b", "t-b")):
                _raw_insert(conn, "clients", id=cid, client_number=cid, tenant_id=tid)
            _mandate(conn, "m-a", "c-a", "t-a")
            _mandate(conn, "m-a2", "c-a", "t-a")
            _mandate(conn, "m-race", "c-a", "t-a")
            _mandate(conn, "m-b", "c-b", "t-b")
            _sealed_envelope(conn, "e-a", "m-a", "t-a", "1" * 64)
            _sealed_envelope(conn, "e-b", "m-b", "t-b", "2" * 64)
            ensure_postgres_rls_policies(conn)
            conn.execute(text(
                f"CREATE ROLE {_qi(role)} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{password}'"
            ))
            conn.execute(text(f"GRANT USAGE ON SCHEMA {_qi(schema)} TO {_qi(role)}"))
            conn.execute(text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {_qi(schema)} TO {_qi(role)}"
            ))
        app_url = make_url(scoped).set(username=role, password=password).render_as_string(hide_password=False)
        app = create_engine(app_url, future=True, pool_size=2, max_overflow=0)
        attach_tenant_context_reset(app)
        yield {"app": app, "owner": owner, "schema": schema}
    finally:
        if app is not None:
            app.dispose()
        owner.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
            conn.execute(text(f"DROP ROLE IF EXISTS {_qi(role)}"))
        admin.dispose()


def _session(ctx, tenant):
    from services.tenant_context import set_tenant_context

    session = sessionmaker(bind=ctx["app"])()
    set_tenant_context(session, tenant)
    return session


def test_force_rls_and_policies(pg_ccx):
    from services.postgres_rls import tenant_scoped_table_names, tenant_tables_missing_rls_policies

    assert set(TABLES) <= set(tenant_scoped_table_names())
    with pg_ccx["owner"].connect() as conn:
        assert tenant_tables_missing_rls_policies(conn, table_names=TABLES, schema=pg_ccx["schema"]) == []
        for table in TABLES:
            forced = conn.execute(text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = :t"
            ), {"s": pg_ccx["schema"], "t": table}).scalar()
            assert forced is True, table


def test_select_is_tenant_bound(pg_ccx):
    with _session(pg_ccx, "t-a") as db:
        assert {r[0] for r in db.execute(text(f"SELECT id FROM {ENVELOPES}"))} == {"e-a"}
        assert {r[0] for r in db.execute(text(f"SELECT envelope_id FROM {BINDINGS}"))} == {"e-a"}
        assert {r[0] for r in db.execute(text(f"SELECT mandate_id FROM {MANIFESTS}"))} == {"m-a"}
    with _session(pg_ccx, None) as db:
        for table in TABLES:
            assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0


@pytest.mark.parametrize("variant", [
    {"mandate_id": "m-a", "tenant_id": "t-b"},   # gespoofter Mandant
    {"mandate_id": "m-b", "tenant_id": "t-a"},   # fremdes Mandat (unter RLS unsichtbar)
])
def test_foreign_tenant_cannot_write_envelope_or_manifest(pg_ccx, variant):
    with _session(pg_ccx, "t-a") as db:
        with pytest.raises(DBAPIError):
            _draft(db.connection(), "e-x", **variant)
        db.rollback()
        with pytest.raises(DBAPIError):
            _manifest(db.connection(), "man-x", **variant)
        db.rollback()


def test_binding_with_foreign_tenant_fails_on_composite_fk(pg_ccx):
    with pg_ccx["owner"].begin() as conn:
        _draft(conn, "e-fk", "m-a2", tenant_id="t-a")
    try:
        with pg_ccx["owner"].connect() as conn:
            with pytest.raises(IntegrityError):
                _bind(conn, "b-fk", "e-fk", "t-b")
            conn.rollback()
    finally:
        with pg_ccx["owner"].begin() as conn:
            conn.execute(text(f"DELETE FROM {ENVELOPES} WHERE id = 'e-fk'"))


def test_lifecycle_insert_draft_only_and_seal_needs_manifest_binding(pg_ccx):
    with _session(pg_ccx, "t-a") as db:
        with pytest.raises(DBAPIError):
            _draft(db.connection(), "e-s", "m-a2", tenant_id="t-a", status="SEALED")
        db.rollback()
        _draft(db.connection(), "e-d", "m-a2", tenant_id="t-a")
        with pytest.raises(DBAPIError, match="CCX_BINDING_MISSING"):
            _seal(db.connection(), "e-d", "3" * 64)
        db.rollback()


@pytest.mark.parametrize("statement", [
    f"UPDATE {ENVELOPES} SET canonical_payload_json = '[]', optimistic_version = optimistic_version + 1 "
    "WHERE id = 'e-a'",
    f"UPDATE {ENVELOPES} SET envelope_hash = '{'9' * 64}', optimistic_version = optimistic_version + 1 "
    "WHERE id = 'e-a'",
    f"UPDATE {ENVELOPES} SET status = 'SUPERSEDED' WHERE id = 'e-a'",
    f"DELETE FROM {ENVELOPES} WHERE id = 'e-a'",
    f"UPDATE {BINDINGS} SET child_hash = '{'9' * 64}' WHERE envelope_id = 'e-a'",
    f"DELETE FROM {BINDINGS} WHERE envelope_id = 'e-a'",
    f"UPDATE {MANIFESTS} SET goals_hash = 'x' WHERE mandate_id = 'm-a'",
    f"DELETE FROM {MANIFESTS} WHERE mandate_id = 'm-a'",
])
def test_sealed_rows_are_append_only_for_app_and_owner(pg_ccx, statement):
    with _session(pg_ccx, "t-a") as db:
        with pytest.raises(DBAPIError):
            db.execute(text(statement))
        db.rollback()
    with pg_ccx["owner"].connect() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text(statement))
        conn.rollback()


def test_binding_cannot_be_added_to_sealed_envelope(pg_ccx):
    with _session(pg_ccx, "t-a") as db:
        with pytest.raises(DBAPIError):
            _bind(db.connection(), "b-late", "e-a", "t-a", kind="late")
        db.rollback()


def test_only_supersession_with_unchanged_content_is_allowed(pg_ccx):
    with _session(pg_ccx, "t-a") as db:
        changed = db.execute(text(
            f"UPDATE {ENVELOPES} SET status = 'SUPERSEDED', optimistic_version = optimistic_version + 1 "
            "WHERE id = 'e-a' AND status = 'SEALED'"
        )).rowcount
        assert changed == 1
        db.rollback()


def test_parallel_sealing_has_exactly_one_winner(pg_ccx):
    """Zwei echte Transaktionen versiegeln den ersten Entscheid desselben
    Mandats: die zweite wartet an der Unique-Pruefung und scheitert nach dem
    Commit der ersten -- nie zwei SEALED."""
    first = _session(pg_ccx, "t-a")
    second = _session(pg_ccx, "t-a")
    outcome: dict = {}
    try:
        for db, suffix in ((first, "1"), (second, "2")):
            _manifest(db.connection(), f"man-r{suffix}", "m-race", tenant_id="t-a")
            _draft(db.connection(), f"e-r{suffix}", "m-race", tenant_id="t-a")
            _bind(db.connection(), f"b-r{suffix}", f"e-r{suffix}", "t-a")
        assert _seal(first.connection(), "e-r1", "4" * 64) == 1

        def _second():
            try:
                _seal(second.connection(), "e-r2", "5" * 64)
                second.commit()
                outcome["result"] = "committed"
            except IntegrityError as exc:
                second.rollback()
                outcome["result"] = "unique_violation"
                outcome["detail"] = str(exc.orig)
            except Exception as exc:  # pragma: no cover - Diagnose
                second.rollback()
                outcome["result"] = f"other: {exc!r}"

        worker = threading.Thread(target=_second)
        worker.start()
        worker.join(timeout=1.5)
        assert worker.is_alive(), "zweite Transaktion haette auf die erste warten muessen"
        first.commit()
        worker.join(timeout=30)
        assert not worker.is_alive()
        assert outcome["result"] == "unique_violation", outcome
        assert "ux_advisory_decision_envelopes_one_sealed" in outcome["detail"]
    finally:
        first.close()
        second.close()
    with _session(pg_ccx, "t-a") as db:
        rows = db.execute(text(
            f"SELECT id, status FROM {ENVELOPES} WHERE mandate_id = 'm-race'")).all()
        assert [r.id for r in rows if r.status == "SEALED"] == ["e-r1"]


def test_parallel_successors_of_same_predecessor_have_one_winner(pg_ccx):
    first = _session(pg_ccx, "t-a")
    second = _session(pg_ccx, "t-a")
    outcome: dict = {}
    try:
        _draft(first.connection(), "e-s1", "m-race", tenant_id="t-a", predecessor_id="e-r1")

        def _second():
            try:
                _draft(second.connection(), "e-s2", "m-race", tenant_id="t-a", predecessor_id="e-r1")
                second.commit()
                outcome["result"] = "committed"
            except IntegrityError as exc:
                second.rollback()
                outcome["result"] = "unique_violation"
                outcome["detail"] = str(exc.orig)

        worker = threading.Thread(target=_second)
        worker.start()
        worker.join(timeout=1.5)
        assert worker.is_alive()
        first.commit()
        worker.join(timeout=30)
        assert outcome["result"] == "unique_violation", outcome
        assert "ux_advisory_decision_envelopes_one_successor" in outcome["detail"]
    finally:
        first.close()
        second.close()


def test_upgrade_downgrade_upgrade_on_postgres():
    pytest.importorskip("psycopg")
    from alembic import command
    from sqlalchemy import inspect

    token = uuid.uuid4().hex[:12]
    schema = f"ccxmig_{token}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    scoped = _scoped_url(POSTGRES_URL, schema)
    engine = create_engine(scoped, future=True)
    try:
        cfg = _alembic_cfg(scoped)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, CCX_P1_PARENT)
        with engine.connect() as conn:
            assert not set(TABLES) & set(inspect(conn).get_table_names(schema=schema))
            functions = {r[0] for r in conn.execute(text(
                "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = :s"), {"s": schema})}
            assert not {f"{t}_guard" for t in TABLES} & functions
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            assert set(TABLES) <= set(inspect(conn).get_table_names(schema=schema))
            triggers = {r[0] for r in conn.execute(text(
                "SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = :s"), {"s": schema})}
            assert {f"trg_{t}_guard" for t in TABLES} <= triggers
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
        admin.dispose()
