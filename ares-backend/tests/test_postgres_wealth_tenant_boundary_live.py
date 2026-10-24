"""PG-002 live on PostgreSQL: wealth tables under FORCE RLS + DB link invariants.

Runs the real migration chain into a throwaway schema, applies the boot-time
RLS plan (``ensure_postgres_rls_policies``), and then probes as a dedicated
NON-owner, NON-superuser, NOBYPASSRLS role -- the only setup in which RLS is
meaningful. Two tenants, each with clients, positions and inflows:

* SELECT / INSERT / UPDATE / DELETE positive for the own tenant, negative for
  the other one, on ``wealth_positions`` and ``wealth_inflows``;
* ``tenant_id`` is derived from the client by the database (omitted ->
  filled, spoofed -> rejected), never trusted from the writer;
* raw SQL cannot link an inflow to another tenant's or another client's
  position, nor to a dangling or soft-deleted one -- not even with the
  operator bypass (composite foreign key + trigger);
* the migration aborts on an invalid legacy link.

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
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.postgres_rls import ensure_postgres_rls_policies  # noqa: E402
from services.tenant_context import (  # noqa: E402
    attach_tenant_context_reset,
    set_operator_bypass,
    set_tenant_context,
)
from services.wealth_tenant_boundary import COMPOSITE_FK_NAME, WEALTH_TENANT_TABLES  # noqa: E402
from tests.test_tenant_database_boundary import (  # noqa: E402
    MIGRATION_DOWN_REVISION,
    MIGRATION_REVISION,
    _raw_insert,
)

_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")


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


def _seed(conn) -> None:
    for tid in ("t-a", "t-b"):
        _raw_insert(conn, "tenants", id=tid, display_name=tid, slug=tid)
    _raw_insert(conn, "users", id="adv", tenant_id="t-a")
    for cid, tid in (("c-a", "t-a"), ("c-a2", "t-a"), ("c-b", "t-b")):
        _raw_insert(conn, "clients", id=cid, client_number=cid, tenant_id=tid)
    for pid, cid in (("p-a", "c-a"), ("p-a2", "c-a2"), ("p-b", "c-b")):
        _raw_insert(conn, "wealth_positions", id=pid, client_id=cid)
    _raw_insert(conn, "wealth_positions", id="p-a-del", client_id="c-a", deleted_at="2026-10-01")
    _raw_insert(conn, "wealth_inflows", id="i-a", client_id="c-a", linked_position_id="p-a")
    _raw_insert(conn, "wealth_inflows", id="i-b", client_id="c-b", linked_position_id="p-b")


@pytest.fixture(scope="module")
def pg_boundary():
    pytest.importorskip("psycopg")
    assert POSTGRES_URL is not None
    from alembic import command

    token = uuid.uuid4().hex[:12]
    schema, role, password = f"wtb_{token}", f"wtb_app_{token}", f"pw_{token}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    scoped = _scoped_url(POSTGRES_URL, schema)
    command.upgrade(_alembic_cfg(scoped), MIGRATION_REVISION)
    owner = create_engine(scoped, future=True)
    with owner.begin() as conn:
        _seed(conn)
        ensure_postgres_rls_policies(conn, table_names=("clients", *WEALTH_TENANT_TABLES))
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
    try:
        yield {"app": app, "owner": owner, "schema": schema, "scoped": scoped}
    finally:
        app.dispose()
        owner.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
            conn.execute(text(f"DROP ROLE IF EXISTS {_qi(role)}"))
        admin.dispose()


def _session(ctx, tenant: str | None = None, *, bypass: bool = False):
    session = sessionmaker(bind=ctx["app"])()
    set_tenant_context(session, tenant)
    if bypass:
        set_operator_bypass(session, True)
    return session


def test_migration_on_postgres_sets_not_null_composite_fk_triggers_and_force_rls(pg_boundary):
    with pg_boundary["owner"].connect() as conn:
        for table in WEALTH_TENANT_TABLES:
            nullable = conn.execute(text(
                "SELECT is_nullable FROM information_schema.columns WHERE table_schema = :s "
                "AND table_name = :t AND column_name = 'tenant_id'"
            ), {"s": pg_boundary["schema"], "t": table}).scalar()
            assert nullable == "NO", table
            forced = conn.execute(text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = :t"
            ), {"s": pg_boundary["schema"], "t": table}).scalar()
            assert forced is True, table
        fk = conn.execute(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n "
            "AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = :s)"
        ), {"n": COMPOSITE_FK_NAME, "s": pg_boundary["schema"]}).scalar()
        assert fk and "(linked_position_id, client_id)" in fk and "wealth_positions(id, client_id)" in fk
        backfilled = dict(conn.execute(text("SELECT id, tenant_id FROM wealth_positions")).all())
        assert backfilled["p-b"] == "t-b" and backfilled["p-a"] == "t-a"


@pytest.mark.parametrize("table", WEALTH_TENANT_TABLES)
def test_select_update_delete_are_tenant_bound(pg_boundary, table):
    own, foreign = ("p-a", "p-b") if table == "wealth_positions" else ("i-a", "i-b")
    with _session(pg_boundary, "t-a") as db:
        ids = {row[0] for row in db.execute(text(f"SELECT id FROM {table}")).all()}
        assert own in ids and foreign not in ids
        assert db.execute(text(f"UPDATE {table} SET label = 'x' WHERE id = :id"), {"id": foreign}).rowcount == 0
        assert db.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": foreign}).rowcount == 0
        assert db.execute(text(f"UPDATE {table} SET label = 'own' WHERE id = :id"), {"id": own}).rowcount == 1
        db.rollback()
    with _session(pg_boundary, None) as db:  # no tenant context -> nothing visible
        assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0


def test_insert_derives_tenant_and_rejects_foreign_client_and_spoofing(pg_boundary):
    with _session(pg_boundary, "t-a") as db:
        _raw_insert(db.connection(), "wealth_positions", id="new-a", client_id="c-a")
        assert db.execute(text("SELECT tenant_id FROM wealth_positions WHERE id = 'new-a'")).scalar() == "t-a"
        db.rollback()
    for values in (
        {"id": "x1", "client_id": "c-b"},  # other tenant's client: invisible -> no tenant
        {"id": "x2", "client_id": "c-a", "tenant_id": "t-b"},  # spoofed tenant
        {"id": "x3", "client_id": "c-b", "tenant_id": "t-a"},  # spoof towards own tenant
    ):
        with _session(pg_boundary, "t-a") as db:
            with pytest.raises(DBAPIError):
                _raw_insert(db.connection(), "wealth_positions", **values)
                db.flush()
            db.rollback()


@pytest.mark.parametrize(
    "target",
    ["p-b", "p-a2", "missing", "p-a-del"],
    ids=["other-tenant", "same-tenant-other-client", "dangling", "soft-deleted"],
)
@pytest.mark.parametrize("bypass", [False, True], ids=["tenant-session", "operator-bypass"])
def test_raw_sql_cannot_create_an_invalid_link(pg_boundary, target, bypass):
    with _session(pg_boundary, "t-a", bypass=bypass) as db:
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE wealth_inflows SET linked_position_id = :t WHERE id = 'i-a'"), {"t": target})
            db.flush()
        db.rollback()
    with _session(pg_boundary, "t-a", bypass=bypass) as db:
        with pytest.raises(IntegrityError):
            _raw_insert(db.connection(), "wealth_inflows", id=f"n-{target}", client_id="c-a", linked_position_id=target)
        db.rollback()


def test_linked_position_cannot_change_client(pg_boundary):
    with _session(pg_boundary, "t-a") as db:
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE wealth_positions SET client_id = 'c-a2' WHERE id = 'p-a'"))
        db.rollback()


def test_migration_aborts_on_invalid_legacy_link_on_postgres(pg_boundary):
    from alembic import command

    schema = f"wtb_bad_{uuid.uuid4().hex[:10]}"
    admin = create_engine(POSTGRES_URL, future=True)
    try:
        with admin.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
        scoped = _scoped_url(POSTGRES_URL, schema)
        cfg = _alembic_cfg(scoped)
        command.upgrade(cfg, MIGRATION_DOWN_REVISION)
        engine = create_engine(scoped, future=True)
        try:
            with engine.begin() as conn:
                for tid in ("t-a", "t-b"):
                    _raw_insert(conn, "tenants", id=tid, display_name=tid, slug=tid)
                _raw_insert(conn, "users", id="adv", tenant_id="t-a")
                _raw_insert(conn, "clients", id="c-a", client_number="c-a", tenant_id="t-a")
                _raw_insert(conn, "clients", id="c-b", client_number="c-b", tenant_id="t-b")
                _raw_insert(conn, "wealth_positions", id="p-b", client_id="c-b")
                _raw_insert(conn, "wealth_inflows", id="i-bad", client_id="c-a", linked_position_id="p-b")
        finally:
            engine.dispose()
        with pytest.raises(RuntimeError, match="i-bad"):
            command.upgrade(cfg, MIGRATION_REVISION)
    finally:
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
        admin.dispose()
