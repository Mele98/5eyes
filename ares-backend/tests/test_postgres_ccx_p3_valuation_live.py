"""CCX-P3 Bewertungs-Snapshot, Positionszeilen und Entscheid-Ledger live auf
PostgreSQL unter FORCE RLS.

Echte Migrationskette bis Head in ein Wegwerf-Schema, Boot-RLS-Plan, Probe als
NON-owner/NON-superuser/NOBYPASSRLS-Rolle mit zwei Mandanten:

* RLS ENABLE + FORCE und Policy fuer alle drei Tabellen; SELECT nur im eigenen
  Mandanten, ohne Kontext nichts;
* INSERT-Guard: gespoofter Mandant und fremdes Mandat werden abgelehnt; Zeile
  mit fremdem Mandanten scheitert am zusammengesetzten FK;
* Snapshot und Zeilen append-only (App-Rolle UND Owner), Snapshot nach
  ``position_count`` geschlossen; COMPLETE ohne Summe verletzt den CHECK;
* Ledger nur im DRAFT-Envelope einfuegbar, danach unveraenderlich;
* UPSERT ``ON CONFLICT DO UPDATE`` kann keine Zeile ueberschreiben;
* upgrade -> downgrade (vor CCX-P3) -> upgrade (inkl. wealth_inflows.currency).

Ohne ``POSTGRES_TEST_DATABASE_URL`` uebersprungen (CI-Job ``postgres-rls``).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from tests.test_postgres_ccx_p1_envelopes_live import _bind, _draft, _manifest, _seal, _sealed_envelope
from tests.test_postgres_mandate_evidence_tenant_boundary_live import (  # noqa: F401
    POSTGRES_URL,
    _alembic_cfg,
    _mandate,
    _qi,
    _scoped_url,
    pytestmark,
)
from tests.test_tenant_database_boundary import _raw_insert

SNAPSHOTS = "holdings_valuation_snapshots"
ROWS = "holdings_valuation_rows"
LEDGER = "position_decision_ledger"
TABLES = (SNAPSHOTS, ROWS, LEDGER)
CCX_P1_REV = "2c62f9012c73"
NOW = "2026-11-14T00:00:00.000000Z"
H = "c" * 64


def _snapshot(conn, row_id, mandate_id, tenant_id, *, count=1, coverage="COMPLETE", **extra):
    values = {"id": row_id, "tenant_id": tenant_id, "mandate_id": mandate_id,
              "schema_version": "ares/holdings-valuation/1", "as_of": "2026-11-14",
              "source_observed_at": "2026-11-14", "source_system": "manual_valuation", "base_currency": "CHF",
              "fx_basis_hash": H, "fx_basis_json": "{}", "coverage_status": coverage,
              "holdings_basis": "recorded", "position_count": count,
              "total_base_minor": 100 if coverage == "COMPLETE" else None,
              "advisory_base_minor": 100 if coverage == "COMPLETE" else None,
              "blocker_codes_json": "[]" if coverage == "COMPLETE" else '["CCX_VALUATION_INCOMPLETE"]',
              "snapshot_hash": row_id[:1] * 64 if len(row_id) else H, "created_at": NOW, "created_by": "adv"}
    values.update(extra)
    conn.execute(text(
        f"INSERT INTO {SNAPSHOTS} ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"
    ), values)


def _row(conn, row_id, snapshot_id, tenant_id, position_id="p1", **extra):
    values = {"id": row_id, "tenant_id": tenant_id, "snapshot_id": snapshot_id, "position_id": position_id,
              "source_kind": "wealth_position", "price_minor": 100, "price_currency": "CHF",
              "source_amount_minor": 100, "base_value_minor": 100, "data_quality": "OK",
              "included_in_total": 1, "row_hash": H}
    values.update(extra)
    conn.execute(text(
        f"INSERT INTO {ROWS} ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"
    ), values)


def _ledger(conn, row_id, envelope_id, mandate_id, tenant_id, position_id="h1", **extra):
    values = {"id": row_id, "tenant_id": tenant_id, "mandate_id": mandate_id, "envelope_id": envelope_id,
              "position_id": position_id, "decision": "KEEP", "reason_code": "CCX_POSITION_IN_TARGET",
              "source_snapshot_hash": H, "created_at": NOW, "created_by": "adv"}
    values.update(extra)
    conn.execute(text(
        f"INSERT INTO {LEDGER} ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"
    ), values)


@pytest.fixture(scope="module")
def pg_p3():
    pytest.importorskip("psycopg")
    from alembic import command

    from services.postgres_rls import ensure_postgres_rls_policies
    from services.tenant_context import attach_tenant_context_reset

    token = uuid.uuid4().hex[:12]
    schema, role, password = f"ccxp3_{token}", f"ccxp3_app_{token}", f"pw_{token}"
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
            _mandate(conn, "m-b", "c-b", "t-b")
            _snapshot(conn, "a-snap", "m-a", "t-a")
            _row(conn, "a-row", "a-snap", "t-a")
            _snapshot(conn, "b-snap", "m-b", "t-b")
            _row(conn, "b-row", "b-snap", "t-b")
            _sealed_envelope(conn, "e-a", "m-a", "t-a", "1" * 64)
            # Ledger-Zeile im DRAFT eines zweiten Envelopes (danach versiegelt).
            _manifest(conn, "man-e-a2", "m-a", tenant_id="t-a")
            _draft(conn, "e-a2", "m-a", tenant_id="t-a", predecessor_id=None)
            _bind(conn, "b-e-a2", "e-a2", "t-a")
            _ledger(conn, "l-a", "e-a2", "m-a", "t-a")
            conn.execute(text("UPDATE advisory_decision_envelopes SET status = 'SUPERSEDED', "
                              "optimistic_version = optimistic_version + 1 WHERE id = 'e-a'"))
            assert _seal(conn, "e-a2", "3" * 64) == 1
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
        yield {"app": app, "owner": owner, "schema": schema, "url": scoped}
    finally:
        if app is not None:
            app.dispose()
        owner.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
            conn.execute(text(f"DROP ROLE IF EXISTS {_qi(role)}"))
        admin.dispose()


def _rollback(db):
    from services.audit import restore_tenant_after_rollback
    from services.tenant_context import set_tenant_context

    restore_tenant_after_rollback(db, set_tenant_context)


def _session(ctx, tenant):
    from services.tenant_context import set_tenant_context

    session = sessionmaker(bind=ctx["app"])()
    set_tenant_context(session, tenant)
    return session


def test_force_rls_and_policies(pg_p3):
    from services.postgres_rls import tenant_scoped_table_names, tenant_tables_missing_rls_policies

    assert set(TABLES) <= set(tenant_scoped_table_names())
    with pg_p3["owner"].connect() as conn:
        assert tenant_tables_missing_rls_policies(conn, table_names=TABLES, schema=pg_p3["schema"]) == []
        for table in TABLES:
            forced = conn.execute(text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = :t"
            ), {"s": pg_p3["schema"], "t": table}).scalar()
            assert forced is True, table


def test_select_is_tenant_bound(pg_p3):
    with _session(pg_p3, "t-a") as db:
        assert {r[0] for r in db.execute(text(f"SELECT id FROM {SNAPSHOTS}"))} == {"a-snap"}
        assert {r[0] for r in db.execute(text(f"SELECT id FROM {ROWS}"))} == {"a-row"}
        assert {r[0] for r in db.execute(text(f"SELECT id FROM {LEDGER}"))} == {"l-a"}
    with _session(pg_p3, None) as db:
        for table in TABLES:
            assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0


@pytest.mark.parametrize("variant", [
    {"mandate_id": "m-a", "tenant_id": "t-b"},   # gespoofter Mandant
    {"mandate_id": "m-b", "tenant_id": "t-a"},   # fremdes Mandat (unter RLS unsichtbar)
])
def test_foreign_tenant_cannot_write_snapshot(pg_p3, variant):
    with _session(pg_p3, "t-a") as db:
        with pytest.raises(DBAPIError):
            _snapshot(db.connection(), "x-snap", **variant)
        _rollback(db)


def test_row_of_foreign_tenant_fails_composite_fk(pg_p3):
    with _session(pg_p3, "t-a") as db:
        _snapshot(db.connection(), "n-snap", "m-a", "t-a", count=2)
        with pytest.raises(DBAPIError):
            _row(db.connection(), "x-row", "n-snap", "t-b")
        _rollback(db)


@pytest.mark.parametrize("engine_key", ["app", "owner"])
@pytest.mark.parametrize("statement", [
    f"UPDATE {SNAPSHOTS} SET coverage_status = 'UNKNOWN'",
    f"DELETE FROM {SNAPSHOTS}",
    f"UPDATE {ROWS} SET base_value_minor = 0",
    f"DELETE FROM {ROWS}",
    f"UPDATE {LEDGER} SET decision = 'SELL'",
    f"DELETE FROM {LEDGER}",
])
def test_snapshot_rows_and_ledger_are_append_only(pg_p3, engine_key, statement):
    from services.tenant_context import set_tenant_context

    session = sessionmaker(bind=pg_p3[engine_key])()
    try:
        set_tenant_context(session, "t-a")  # FORCE RLS gilt auch fuer den Owner
        assert session.execute(text(f"SELECT count(*) FROM {statement.split()[2 if statement.startswith('DELETE') else 1]} "
                                    "WHERE tenant_id = 't-a'")).scalar() >= 1
        with pytest.raises(DBAPIError):
            session.execute(text(statement + " WHERE tenant_id = 't-a'"))
            session.flush()
    finally:
        session.rollback()
        session.close()


def test_closed_snapshot_and_complete_check(pg_p3):
    with _session(pg_p3, "t-a") as db:
        with pytest.raises(DBAPIError):  # a-snap hat position_count=1 und bereits eine Zeile
            _row(db.connection(), "late-row", "a-snap", "t-a", position_id="p2")
        _rollback(db)
        with pytest.raises(DBAPIError):  # COMPLETE ohne Summe
            _snapshot(db.connection(), "z-snap", "m-a", "t-a", total_base_minor=None)
        _rollback(db)


def test_ledger_only_while_envelope_is_draft(pg_p3):
    with _session(pg_p3, "t-a") as db:
        with pytest.raises(DBAPIError):
            _ledger(db.connection(), "l-late", "e-a2", "m-a", "t-a", position_id="h2")
        _rollback(db)


@pytest.mark.parametrize("table,conflict,assign", [
    (SNAPSHOTS, "id", "coverage_status = 'UNKNOWN'"),
    (ROWS, "id", "base_value_minor = 0"),
    (LEDGER, "id", "decision = 'SELL'"),
])
def test_upsert_cannot_overwrite(pg_p3, table, conflict, assign):
    from services.tenant_context import set_tenant_context

    for engine_key in ("app", "owner"):
        session = sessionmaker(bind=pg_p3[engine_key])()
        try:
            set_tenant_context(session, "t-a")
            assert session.execute(text(f"SELECT count(*) FROM {table}")).scalar() >= 1
            with pytest.raises(DBAPIError):
                session.execute(text(
                    f"INSERT INTO {table} SELECT * FROM {table} WHERE tenant_id = 't-a' "
                    f"ON CONFLICT ({conflict}) DO UPDATE SET {assign}"
                ))
                session.flush()
        finally:
            session.rollback()
            session.close()


def test_upgrade_downgrade_upgrade(pg_p3):
    from alembic import command

    url = pg_p3["url"]
    command.downgrade(_alembic_cfg(url), CCX_P1_REV)
    engine = create_engine(url, future=True)
    try:
        insp = inspect(engine)
        assert not set(TABLES) & set(insp.get_table_names())
        assert "currency" not in {c["name"] for c in insp.get_columns("wealth_inflows")}
    finally:
        engine.dispose()
    command.upgrade(_alembic_cfg(url), "head")
    engine = create_engine(url, future=True)
    try:
        insp = inspect(engine)
        assert set(TABLES) <= set(insp.get_table_names())
        assert "currency" in {c["name"] for c in insp.get_columns("wealth_inflows")}
    finally:
        engine.dispose()
