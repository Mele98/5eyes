"""PG-002 live on PostgreSQL: append-only mandate evidence under FORCE RLS
(red-team review 2026-10-28, finding 6).

``depot_snapshots``, ``onsite_signature_events``, ``onsite_signature_challenges``
and ``onsite_signature_evidence`` were outside the RLS plan. This test runs
the real migration chain into a throwaway schema, seeds LEGACY rows before the
migration (backfill despite the append-only triggers), applies the boot-time
RLS plan (``ensure_postgres_rls_policies`` without a table list -- exactly as
``init_db`` does) and probes as a NON-owner, NON-superuser, NOBYPASSRLS role
with two tenants:

* every table has RLS ENABLE + FORCE and a policy after boot;
* SELECT is tenant-bound; without tenant context nothing is visible, an
  orphan (quarantined, ``tenant_id IS NULL``) row is invisible to all;
* raw-SQL INSERT derives ``tenant_id`` from the mandate, rejects a spoofed
  tenant, a foreign (invisible) mandate and a foreign client;
* the append-only guard still blocks UPDATE/DELETE.

Skipped without ``POSTGRES_TEST_DATABASE_URL`` (CI job ``postgres-rls``).
"""
from __future__ import annotations

import os
import re
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

from services.mandate_evidence_tenant_boundary import (  # noqa: E402
    MANDATE_EVIDENCE_TENANT_TABLES,
)
from services.postgres_rls import (  # noqa: E402
    ensure_postgres_rls_policies,
    tenant_scoped_table_names,
    tenant_tables_missing_rls_policies,
)
from services.tenant_context import (  # noqa: E402
    attach_tenant_context_reset,
    set_tenant_context,
)
from tests.test_tenant_database_boundary import _raw_insert  # noqa: E402

MIGRATION_DOWN_REVISION = "e5b3c9d1a7f4"
NOW = "2026-10-30T00:00:00.000Z"
TABLES = MANDATE_EVIDENCE_TENANT_TABLES
_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")
_ACTOR_COLUMNS = ("created_by", "actor_id", "advisor_id")


def _qi(identifier: str) -> str:
    assert _IDENT.match(identifier), identifier
    return f'"{identifier}"'


def _scoped_url(url: str, schema: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}options=-csearch_path%3D{schema}"


def _alembic_cfg(scoped_url: str):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", scoped_url.replace("%", "%%"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _required_columns(conn, table: str) -> dict[str, str]:
    rows = conn.execute(text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = :t "
        "AND is_nullable = 'NO' AND column_default IS NULL"
    ), {"t": table}).all()
    return {name: dtype for name, dtype in rows}


def _insert(conn, table: str, row_id: str, mandate_id: str, client_id: str, **extra) -> None:
    values: dict[str, object] = {}
    for name, dtype in _required_columns(conn, table).items():
        values[name] = 1 if dtype in ("integer", "bigint", "smallint") else f"{row_id}-{name}"
    values.update(id=row_id, mandate_id=mandate_id, client_id=client_id)
    for column in ("transaction_id", *_ACTOR_COLUMNS):
        if column in values:
            values[column] = row_id if column == "transaction_id" else "adv"
    values.update(extra)
    columns = ", ".join(values)
    params = ", ".join(f":{key}" for key in values)
    conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({params})"), values)


def _mandate(conn, mid: str, cid: str, tid: str) -> None:
    conn.execute(text(
        "INSERT INTO mandates (id, client_id, mandate_number, mandate_type, status, base_currency, "
        "advisory_language, opened_at, investment_universe, tenant_id, created_at, updated_at) "
        "VALUES (:id, :cid, :id, 'Anlageberatung', 'Aktiv', 'CHF', 'DE', '2026-01-01', 'Standard', "
        ":tid, :n, :n)"
    ), {"id": mid, "cid": cid, "tid": tid, "n": NOW})


def _seed_legacy(conn) -> None:
    for tid in ("t-a", "t-b"):
        _raw_insert(conn, "tenants", id=tid, display_name=tid, slug=tid)
    _raw_insert(conn, "users", id="adv", tenant_id="t-a")
    for cid, tid in (("c-a", "t-a"), ("c-b", "t-b")):
        _raw_insert(conn, "clients", id=cid, client_number=cid, tenant_id=tid)
    _mandate(conn, "m-a", "c-a", "t-a")
    _mandate(conn, "m-b", "c-b", "t-b")
    for table in TABLES:
        _insert(conn, table, f"{table}-a", "m-a", "c-a")
        _insert(conn, table, f"{table}-b", "m-b", "c-b")
        _insert(conn, table, f"{table}-purged", "m-purged", "c-purged")


@pytest.fixture(scope="module")
def pg_evidence():
    pytest.importorskip("psycopg")
    assert POSTGRES_URL is not None
    from alembic import command

    token = uuid.uuid4().hex[:12]
    schema, role, password = f"metb_{token}", f"metb_app_{token}", f"pw_{token}"
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
        # Kettenbasiert: ueber die Revision hinweg bis zum Kopf (der Boot-Plan
        # unten deckt alle ORM-Tabellen ab, also muessen alle existieren).
        command.upgrade(_alembic_cfg(scoped), "head")
        with owner.begin() as conn:
            # Boot-Pfad (database.init_db): Plan ohne Tabellenliste.
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


def test_boot_plan_covers_tables_with_force_rls(pg_evidence):
    assert set(TABLES) <= set(tenant_scoped_table_names())
    with pg_evidence["owner"].connect() as conn:
        assert tenant_tables_missing_rls_policies(
            conn, table_names=TABLES, schema=pg_evidence["schema"],
        ) == []
        for table in TABLES:
            forced = conn.execute(text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = :t"
            ), {"s": pg_evidence["schema"], "t": table}).scalar()
            assert forced is True, table


@pytest.mark.parametrize("table", TABLES)
def test_legacy_rows_backfilled_and_select_is_tenant_bound(pg_evidence, table):
    with _session(pg_evidence, "t-a") as db:
        rows = dict(db.execute(text(f"SELECT id, tenant_id FROM {table}")).all())
        assert rows == {f"{table}-a": "t-a"}
    with _session(pg_evidence, "t-b") as db:
        rows = dict(db.execute(text(f"SELECT id, tenant_id FROM {table}")).all())
        assert rows == {f"{table}-b": "t-b"}
    with _session(pg_evidence, None) as db:
        assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0
    with pg_evidence["owner"].connect() as conn:
        # Quarantaene: verwaiste Zeile bleibt NULL, nie einem Mandanten zugeordnet.
        assert conn.execute(text(
            f"SELECT tenant_id FROM {table} WHERE id = :id"
        ), {"id": f"{table}-purged"}).one()[0] is None


@pytest.mark.parametrize("table", TABLES)
def test_insert_derives_tenant_from_the_mandate(pg_evidence, table):
    with _session(pg_evidence, "t-a") as db:
        _insert(db.connection(), table, f"{table}-new", "m-a", "c-a")
        assert db.execute(text(
            f"SELECT tenant_id FROM {table} WHERE id = :id"
        ), {"id": f"{table}-new"}).scalar() == "t-a"
        db.rollback()


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize(
    "variant",
    [
        {"mandate_id": "m-a", "client_id": "c-a", "tenant_id": "t-b"},  # gespoofter Mandant
        {"mandate_id": "m-b", "client_id": "c-b"},                      # fremdes Mandat (unsichtbar)
        {"mandate_id": "m-b", "client_id": "c-b", "tenant_id": "t-a"},  # fremdes Mandat, eigener Tag
        {"mandate_id": "m-a", "client_id": "c-b"},                      # fremder Kunde
        {"mandate_id": "m-purged", "client_id": "c-a"},                 # Mandat ohne Mandant
    ],
)
def test_foreign_tenant_cannot_write(pg_evidence, table, variant):
    with _session(pg_evidence, "t-a") as db:
        with pytest.raises(DBAPIError):
            _insert(db.connection(), table, f"{table}-x", **variant)
        db.rollback()


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize(
    "statement",
    ["UPDATE {t} SET tenant_id = 't-b' WHERE id = :id", "DELETE FROM {t} WHERE id = :id"],
)
def test_append_only_still_holds(pg_evidence, table, statement):
    with _session(pg_evidence, "t-a") as db:
        with pytest.raises(DBAPIError):
            db.execute(text(statement.format(t=table)), {"id": f"{table}-a"})
        db.rollback()
