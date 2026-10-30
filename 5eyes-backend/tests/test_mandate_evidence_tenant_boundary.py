"""PG-002 (red-team review 2026-10-28, finding 6): append-only mandate evidence
tables carry ``tenant_id`` directly and are part of the RLS plan.

``depot_snapshots`` and the three on-site signature tables were
``tenant_derived`` (only ``mandate_id``), so no PostgreSQL RLS policy covered
them. Checked here on SQLite (PostgreSQL live:
``tests/test_postgres_mandate_evidence_tenant_boundary_live.py``):

* inventory: ``tenant_direct`` and discovered by the RLS plan;
* INSERT guard: spoofed tenant, missing tenant and a foreign client are
  rejected, the mandate's tenant is accepted;
* migration along the chain: deterministic backfill from the mandate despite
  the append-only triggers, orphan rows stay quarantined (NULL), append-only
  still holds afterwards, downgrade removes column and guard;
* frozen DDL in the migration equals the runtime DDL;
* SQLite runtime patch for existing desktop DBs (column, backfill, guard).
"""
from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.postgres_rls import import_tenant_models, tenant_scoped_table_names  # noqa: E402

import_tenant_models()

from database import Base  # noqa: E402
from services import mandate_evidence_tenant_boundary as metb  # noqa: E402
from services import tenant_scope_inventory as inventory  # noqa: E402

MIGRATION_REVISION = "b8d4f2a6c9e1"
MIGRATION_DOWN_REVISION = "e7a3c9d1b5f2"
NOW = "2026-10-30T00:00:00.000Z"
TABLES = metb.MANDATE_EVIDENCE_TENANT_TABLES
_ACTOR_COLUMNS = ("created_by", "actor_id", "advisor_id")


def _alembic_config(database_url: str):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _migration_module():
    path = next((BACKEND_ROOT / "alembic" / "versions").glob(f"{MIGRATION_REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location(f"migration_{MIGRATION_REVISION}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_tenants(conn) -> None:
    from tests.test_tenant_database_boundary import _raw_insert

    for tid in ("t-a", "t-b"):
        _raw_insert(conn, "tenants", id=tid, display_name=tid, slug=tid)
    _raw_insert(conn, "users", id="adv", tenant_id="t-a")
    for cid, tid in (("c-a", "t-a"), ("c-b", "t-b")):
        _raw_insert(conn, "clients", id=cid, client_number=cid, tenant_id=tid)
    for mid, cid, tid in (("m-a", "c-a", "t-a"), ("m-b", "c-b", "t-b")):
        conn.execute(text(
            "INSERT INTO mandates (id, client_id, mandate_number, mandate_type, status, base_currency, "
            "advisory_language, opened_at, investment_universe, tenant_id, created_at, updated_at) "
            "VALUES (:id, :cid, :id, 'Anlageberatung', 'Aktiv', 'CHF', 'DE', '2026-01-01', 'Standard', "
            ":tid, :n, :n)"
        ), {"id": mid, "cid": cid, "tid": tid, "n": NOW})


def _insert(conn, table: str, row_id: str, mandate_id: str, client_id: str, **extra) -> None:
    """Raw INSERT filling every NOT NULL column of the PHYSICAL table."""
    values: dict[str, object] = {}
    for _cid, name, ctype, notnull, default, pk in conn.execute(text(f"PRAGMA table_info({table})")).all():
        if pk or (notnull and default is None):
            values[name] = 1 if "INT" in str(ctype).upper() else f"{row_id}-{name}"
    values.update(id=row_id, mandate_id=mandate_id, client_id=client_id)
    for column in ("transaction_id", *_ACTOR_COLUMNS):
        if column in values:
            values[column] = row_id if column == "transaction_id" else "adv"
    values.update(extra)
    columns = ", ".join(values)
    params = ", ".join(f":{key}" for key in values)
    conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({params})"), values)


def _tenants(conn, table: str) -> dict[str, object]:
    return dict(conn.execute(text(f"SELECT id, tenant_id FROM {table}")).all())


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).all()}


def _triggers(conn, table: str) -> set[str]:
    return {
        row[0] for row in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = :t"
        ), {"t": table}).all()
    }


# --- 1. Inventory / RLS plan ----------------------------------------------------


@pytest.mark.parametrize("table", TABLES)
def test_table_is_tenant_direct_and_in_the_rls_plan(table):
    assert inventory.classification()[table] == inventory.TENANT_DIRECT
    assert table not in inventory.TENANT_DERIVED_TABLES
    assert table in set(tenant_scoped_table_names())
    assert "tenant_id" in Base.metadata.tables[table].c


# --- 2. INSERT guard (ORM create_all) ---------------------------------------------


@pytest.fixture()
def orm_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'orm.db'}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        _seed_tenants(conn)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.parametrize("table", TABLES)
def test_insert_with_the_mandate_tenant_is_accepted(orm_engine, table):
    with orm_engine.begin() as conn:
        _insert(conn, table, "own", "m-a", "c-a", tenant_id="t-a")
    with orm_engine.connect() as conn:
        assert _tenants(conn, table) == {"own": "t-a"}
        assert metb.guard_trigger_name(table) in _triggers(conn, table)


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize(
    "variant",
    [
        {"mandate_id": "m-a", "client_id": "c-a", "tenant_id": "t-b"},   # gespoofter Mandant
        {"mandate_id": "m-a", "client_id": "c-a", "tenant_id": None},    # Mandant fehlt
        {"mandate_id": "m-a", "client_id": "c-b", "tenant_id": "t-a"},   # fremder Kunde
        {"mandate_id": "m-b", "client_id": "c-b", "tenant_id": "t-a"},   # fremdes Mandat
    ],
)
def test_inconsistent_insert_is_rejected_by_the_database(orm_engine, table, variant):
    with pytest.raises(IntegrityError, match=metb.TENANT_ERROR):
        with orm_engine.begin() as conn:
            _insert(conn, table, "bad", **variant)


# --- 3. Migration along the chain ---------------------------------------------------


def test_migration_is_in_the_single_head_chain():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert MIGRATION_REVISION in chain
    assert script.get_revision(MIGRATION_REVISION).down_revision == MIGRATION_DOWN_REVISION


def _seed_legacy_rows(conn) -> None:
    _seed_tenants(conn)
    for table in TABLES:
        _insert(conn, table, f"{table}-a", "m-a", "c-a")
        _insert(conn, table, f"{table}-b", "m-b", "c-b")
        _insert(conn, table, f"{table}-purged", "m-purged", "c-purged")


def test_migration_backfills_despite_append_only_quarantines_orphans_and_downgrades(tmp_path):
    from alembic import command

    url = f"sqlite:///{tmp_path / 'chain.db'}"
    cfg = _alembic_config(url)
    command.upgrade(cfg, MIGRATION_DOWN_REVISION)
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            _seed_legacy_rows(conn)
        command.upgrade(cfg, MIGRATION_REVISION)
        with engine.connect() as conn:
            for table in TABLES:
                assert _tenants(conn, table) == {
                    f"{table}-a": "t-a", f"{table}-b": "t-b", f"{table}-purged": None,
                }, table
                assert {
                    f"trg_{table}_no_update", f"trg_{table}_no_delete", metb.guard_trigger_name(table),
                } <= _triggers(conn, table)
        for table in TABLES:
            with pytest.raises(Exception, match="immutable"):
                with engine.begin() as conn:
                    conn.execute(text(f"UPDATE {table} SET tenant_id = 't-b' WHERE id = '{table}-a'"))
            with pytest.raises(IntegrityError, match=metb.TENANT_ERROR):
                with engine.begin() as conn:
                    _insert(conn, table, f"{table}-spoof", "m-a", "c-a", tenant_id="t-b")
        command.downgrade(cfg, MIGRATION_DOWN_REVISION)
        with engine.connect() as conn:
            for table in TABLES:
                assert "tenant_id" not in _columns(conn, table), table
                triggers = _triggers(conn, table)
                assert metb.guard_trigger_name(table) not in triggers
                assert {f"trg_{table}_no_update", f"trg_{table}_no_delete"} <= triggers
        command.upgrade(cfg, MIGRATION_REVISION)
    finally:
        engine.dispose()


def test_postgres_offline_sql_backfills_with_bypass_and_installs_guard():
    from alembic import command

    buffer = io.StringIO()
    cfg = _alembic_config("postgresql://user:pass@localhost/db")
    cfg.output_buffer = buffer
    command.upgrade(cfg, f"{MIGRATION_DOWN_REVISION}:{MIGRATION_REVISION}", sql=True)
    sql = buffer.getvalue()
    assert "set_config('app.rls_bypass', 'on', true)" in sql
    assert f"CREATE OR REPLACE FUNCTION {metb.POSTGRES_FUNCTION_NAME}()" in sql
    for table in TABLES:
        assert f"ALTER TABLE {table} ADD COLUMN tenant_id VARCHAR" in sql
        assert f"ALTER TABLE {table} DISABLE TRIGGER trg_{table}_immutable" in sql
        assert metb.backfill_tenant_sql(table) in sql
        assert f"ALTER TABLE {table} ENABLE TRIGGER trg_{table}_immutable" in sql
        assert f"CREATE TRIGGER {metb.guard_trigger_name(table)}" in sql
        # Backfill vor dem Guard, Guard nach der Funktion.
        assert sql.index(metb.backfill_tenant_sql(table)) < sql.index(
            f"CREATE TRIGGER {metb.guard_trigger_name(table)}"
        )


def test_frozen_migration_ddl_equals_runtime_ddl():
    module = _migration_module()
    assert module.TABLES == TABLES
    assert module.TENANT_ERROR == metb.TENANT_ERROR
    assert module.PG_FUNCTION_NAME == metb.POSTGRES_FUNCTION_NAME
    for table in TABLES:
        assert module.sqlite_guard(table) == metb.sqlite_guard_trigger(table)
        assert module.sqlite_no_update(table) == metb.sqlite_no_update_trigger(table)
        assert module.backfill(table) == metb.backfill_tenant_sql(table)


# --- 4. SQLite runtime patch (bestehende Desktop-DB) ---------------------------------


def test_sqlite_runtime_patch_adds_column_backfills_and_installs_guard(tmp_path):
    from alembic import command

    import database as db_module

    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    command.upgrade(_alembic_config(url), MIGRATION_DOWN_REVISION)
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            _seed_legacy_rows(conn)
        db_module.ensure_runtime_columns(engine)
        quarantined = metb.ensure_sqlite_mandate_evidence_tenant_boundary(engine)
        # Verwaiste Zeilen werden gezaehlt (und geloggt), nie einem Mandanten zugeordnet.
        assert {table: quarantined[table] for table in TABLES} == {table: 1 for table in TABLES}
        with engine.connect() as conn:
            for table in TABLES:
                assert _tenants(conn, table) == {
                    f"{table}-a": "t-a", f"{table}-b": "t-b", f"{table}-purged": None,
                }, table
                assert {f"trg_{table}_no_update", metb.guard_trigger_name(table)} <= _triggers(conn, table)
                indexes = {row[1] for row in conn.execute(text(f"PRAGMA index_list({table})")).all()}
                assert metb.tenant_index_name(table) in indexes
        # idempotent
        db_module.ensure_runtime_columns(engine)
        again = metb.ensure_sqlite_mandate_evidence_tenant_boundary(engine)
        assert {table: again[table] for table in TABLES} == {table: 1 for table in TABLES}
        for table in TABLES:
            with pytest.raises(Exception, match="immutable"):
                with engine.begin() as conn:
                    conn.execute(text(f"UPDATE {table} SET tenant_id = 't-b' WHERE id = '{table}-a'"))
            with pytest.raises(IntegrityError, match=metb.TENANT_ERROR):
                with engine.begin() as conn:
                    _insert(conn, table, f"{table}-spoof", "m-a", "c-a", tenant_id="t-b")
    finally:
        engine.dispose()
