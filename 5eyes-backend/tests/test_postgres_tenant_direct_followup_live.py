"""PG-002 follow-up live on PostgreSQL: ``depot_check_analysis_snapshots`` and
``product_eligibility_overrides`` under FORCE RLS.

Real migration chain into a throwaway schema, LEGACY rows seeded before the
migration (backfill despite the append-only triggers), boot-time RLS plan
(``ensure_postgres_rls_policies`` without a table list), probes as a
NON-owner, NON-superuser, NOBYPASSRLS role with two tenants:

* both tables have RLS ENABLE + FORCE and a policy;
* SELECT is tenant-bound; orphan rows (quarantined) are invisible to all;
* INSERT derives the tenant (depot check: mandate; overrides: mandate of the
  run) and rejects a spoofed tenant, a foreign mandate/run and (depot check)
  a foreign client;
* UPDATE/DELETE stay blocked.

Skipped without ``POSTGRES_TEST_DATABASE_URL`` (CI job ``postgres-rls``).
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.postgres_rls import (  # noqa: E402
    ensure_postgres_rls_policies,
    tenant_tables_missing_rls_policies,
)
from services.tenant_context import attach_tenant_context_reset, set_tenant_context  # noqa: E402
from tests.test_postgres_mandate_evidence_tenant_boundary_live import (  # noqa: E402
    _alembic_cfg,
    _mandate,
    _qi,
    _required_columns,
    _scoped_url,
)
from tests.test_tenant_database_boundary import _raw_insert  # noqa: E402

MIGRATION_DOWN_REVISION = "b8d4f2a6c9e1"
DEPOT_CHECK = "depot_check_analysis_snapshots"
OVERRIDES = "product_eligibility_overrides"
TABLES = (DEPOT_CHECK, OVERRIDES)
_NUMERIC = ("integer", "bigint", "smallint", "numeric", "double precision", "real")


def _fill(conn, table: str, row_id: str, **values) -> None:
    row: dict[str, object] = {}
    for name, dtype in _required_columns(conn, table).items():
        row[name] = 1 if dtype in _NUMERIC else f"{row_id}-{name}"
    for column in ("created_by", "actor_id"):
        if column in row:
            row[column] = "adv"
    row.update(id=row_id, **values)
    columns = ", ".join(row)
    params = ", ".join(f":{key}" for key in row)
    conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({params})"), row)


def _row(conn, table: str, row_id: str, mandate: str, **extra) -> None:
    suffix = mandate.split("-", 1)[1]
    if table == OVERRIDES:
        _fill(conn, OVERRIDES, row_id, recommendation_run_id=f"run-{suffix}", product_id="prod",
              snapshot_id=None, rule_id=None, **extra)
    else:
        _fill(conn, DEPOT_CHECK, row_id, mandate_id=mandate, client_id=f"c-{suffix}", **extra)


def _seed_legacy(conn) -> None:
    for tid in ("t-a", "t-b"):
        _raw_insert(conn, "tenants", id=tid, display_name=tid, slug=tid)
    _raw_insert(conn, "users", id="adv", tenant_id="t-a")
    for cid, tid in (("c-a", "t-a"), ("c-b", "t-b")):
        _raw_insert(conn, "clients", id=cid, client_number=cid, tenant_id=tid)
    _mandate(conn, "m-a", "c-a", "t-a")
    _mandate(conn, "m-b", "c-b", "t-b")
    _fill(conn, "optimizer_policies", "pol")
    _fill(conn, "products", "prod", tenant_id=None)
    for suffix in ("a", "b"):
        _fill(conn, "recommendation_runs", f"run-{suffix}", mandate_id=f"m-{suffix}",
              client_id=f"c-{suffix}", policy_id="pol")
    # Verwaister Lauf (Mandat geloescht): Override bleibt quarantaeniert.
    conn.execute(text("SET LOCAL session_replication_role = replica"))
    _fill(conn, "recommendation_runs", "run-purged", mandate_id="m-purged", client_id="c-purged",
          policy_id="pol")
    conn.execute(text("SET LOCAL session_replication_role = origin"))
    for table in TABLES:
        for mandate in ("m-a", "m-b", "m-purged"):
            _row(conn, table, f"{table}-{mandate}", mandate)


@pytest.fixture(scope="module")
def pg_ctx():
    pytest.importorskip("psycopg")
    assert POSTGRES_URL is not None
    from alembic import command

    token = uuid.uuid4().hex[:12]
    schema, role, password = f"tdf_{token}", f"tdf_app_{token}", f"pw_{token}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    scoped = _scoped_url(POSTGRES_URL, schema)
    owner = create_engine(scoped, future=True)
    app = None
    try:
        command.upgrade(_alembic_cfg(scoped), MIGRATION_DOWN_REVISION)
        with owner.begin() as conn:
            _seed_legacy(conn)
        command.upgrade(_alembic_cfg(scoped), "head")
        with owner.begin() as conn:
            ensure_postgres_rls_policies(conn)
            conn.execute(text(
                f"CREATE ROLE {_qi(role)} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{password}'"
            ))
            conn.execute(text(f"GRANT USAGE ON SCHEMA {_qi(schema)} TO {_qi(role)}"))
            conn.execute(text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {_qi(schema)} TO {_qi(role)}"
            ))
        app_url = make_url(scoped).set(username=role, password=password).render_as_string(hide_password=False)
        app = create_engine(app_url, future=True, pool_size=1, max_overflow=0)
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


def _session(ctx, tenant: str | None):
    session = sessionmaker(bind=ctx["app"])()
    set_tenant_context(session, tenant)
    return session


def test_boot_plan_covers_tables_with_force_rls(pg_ctx):
    with pg_ctx["owner"].connect() as conn:
        assert tenant_tables_missing_rls_policies(conn, table_names=TABLES, schema=pg_ctx["schema"]) == []
        for table in TABLES:
            forced = conn.execute(text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = :t"
            ), {"s": pg_ctx["schema"], "t": table}).scalar()
            assert forced is True, table


@pytest.mark.parametrize("table", TABLES)
def test_legacy_rows_backfilled_and_select_is_tenant_bound(pg_ctx, table):
    for tenant, own in (("t-a", "m-a"), ("t-b", "m-b")):
        with _session(pg_ctx, tenant) as db:
            rows = dict(db.execute(text(f"SELECT id, tenant_id FROM {table}")).all())
            assert rows == {f"{table}-{own}": tenant}
    with _session(pg_ctx, None) as db:
        assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0
    with pg_ctx["owner"].connect() as conn:
        assert conn.execute(text(
            f"SELECT tenant_id FROM {table} WHERE id = :id"
        ), {"id": f"{table}-m-purged"}).one()[0] is None


@pytest.mark.parametrize("table", TABLES)
def test_insert_derives_tenant(pg_ctx, table):
    with _session(pg_ctx, "t-a") as db:
        _row(db.connection(), table, f"{table}-new", "m-a")
        assert db.execute(text(
            f"SELECT tenant_id FROM {table} WHERE id = :id"
        ), {"id": f"{table}-new"}).scalar() == "t-a"
        db.rollback()


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize(
    ("mandate", "extra"),
    [
        ("m-a", {"tenant_id": "t-b"}),  # gespoofter Mandant
        ("m-b", {}),                    # fremdes Mandat / fremder Lauf (unsichtbar)
        ("m-b", {"tenant_id": "t-a"}),  # fremdes Mandat, eigener Tag
        ("m-purged", {}),               # Mandat/Lauf ohne Mandant
    ],
)
def test_foreign_tenant_cannot_write(pg_ctx, table, mandate, extra):
    with _session(pg_ctx, "t-a") as db:
        with pytest.raises(DBAPIError):
            _row(db.connection(), table, f"{table}-x", mandate, **extra)
        db.rollback()


def test_depot_check_with_foreign_client_is_rejected(pg_ctx):
    with _session(pg_ctx, "t-a") as db:
        with pytest.raises(DBAPIError):
            _fill(db.connection(), DEPOT_CHECK, "dc-x", mandate_id="m-a", client_id="c-b")
        db.rollback()


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize(
    "statement",
    ["UPDATE {t} SET tenant_id = 't-b' WHERE id = :id", "DELETE FROM {t} WHERE id = :id"],
)
def test_append_only_still_holds(pg_ctx, table, statement):
    with _session(pg_ctx, "t-a") as db:
        with pytest.raises(DBAPIError):
            db.execute(text(statement.format(t=table)), {"id": f"{table}-m-a"})
        db.rollback()
