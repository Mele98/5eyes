"""PG-002 follow-up: ``depot_check_analysis_snapshots`` and
``product_eligibility_overrides`` carry ``tenant_id`` directly.

Both were ``tenant_derived`` (the depot check via ``mandate_id``, the
overrides via ``recommendation_run_id`` -> run -> mandate) and therefore
outside the PostgreSQL RLS plan. Same pattern as
``tests/test_mandate_evidence_tenant_boundary.py`` (SQLite side; PostgreSQL
live: ``tests/test_postgres_tenant_direct_followup_live.py``).
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
from tests.test_mandate_evidence_tenant_boundary import (  # noqa: E402
    _alembic_config,
    _columns,
    _insert,
    _seed_tenants,
    _tenants,
    _triggers,
)

MIGRATION_REVISION = "d6a2c8e4f1b7"
MIGRATION_DOWN_REVISION = "b8d4f2a6c9e1"
DEPOT_CHECK = "depot_check_analysis_snapshots"
OVERRIDES = "product_eligibility_overrides"
TABLES = (DEPOT_CHECK, OVERRIDES)


def _migration_module():
    path = next((BACKEND_ROOT / "alembic" / "versions").glob(f"{MIGRATION_REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location(f"migration_{MIGRATION_REVISION}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_runs(conn) -> None:
    for run, mandate, client in (("run-a", "m-a", "c-a"), ("run-b", "m-b", "c-b")):
        _insert(conn, "recommendation_runs", run, mandate, client)


def _row(conn, table: str, row_id: str, mandate: str, **extra) -> None:
    """One evidence row bound to ``mandate`` (m-a/m-b/m-purged)."""
    suffix = mandate.split("-", 1)[1]
    if table == OVERRIDES:
        _insert_override(conn, row_id, f"run-{suffix}", **extra)
    else:
        _insert(conn, table, row_id, mandate, f"c-{suffix}", **extra)


def _insert_override(conn, row_id: str, run_id: str, **extra) -> None:
    values: dict[str, object] = {}
    for _cid, name, ctype, notnull, default, pk in conn.execute(text(f"PRAGMA table_info({OVERRIDES})")).all():
        if pk or (notnull and default is None):
            values[name] = 1 if "INT" in str(ctype).upper() else f"{row_id}-{name}"
    values.update(id=row_id, recommendation_run_id=run_id, **extra)
    columns = ", ".join(values)
    params = ", ".join(f":{key}" for key in values)
    conn.execute(text(f"INSERT INTO {OVERRIDES} ({columns}) VALUES ({params})"), values)


# --- 1. Inventory / RLS plan ------------------------------------------------------


@pytest.mark.parametrize("table", TABLES)
def test_table_is_tenant_direct_and_in_the_rls_plan(table):
    assert inventory.classification()[table] == inventory.TENANT_DIRECT
    assert table in set(tenant_scoped_table_names())
    assert "tenant_id" in Base.metadata.tables[table].c
    assert table in metb.ALL_TENANT_BOUND_TABLES


# --- 2. INSERT guard (ORM create_all) -------------------------------------------------


@pytest.fixture()
def orm_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'orm.db'}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        _seed_tenants(conn)
        _seed_runs(conn)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.parametrize("table", TABLES)
def test_insert_with_the_mandate_tenant_is_accepted(orm_engine, table):
    with orm_engine.begin() as conn:
        _row(conn, table, "own", "m-a", tenant_id="t-a")
    with orm_engine.connect() as conn:
        assert _tenants(conn, table) == {"own": "t-a"}
        assert metb.guard_trigger_name(table) in _triggers(conn, table)


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("tenant", ["t-b", None])
def test_spoofed_or_missing_tenant_is_rejected(orm_engine, table, tenant):
    with pytest.raises(IntegrityError, match=metb.TENANT_ERROR):
        with orm_engine.begin() as conn:
            _row(conn, table, "bad", "m-a", tenant_id=tenant)


def test_depot_check_with_foreign_client_is_rejected(orm_engine):
    with pytest.raises(IntegrityError, match=metb.TENANT_ERROR):
        with orm_engine.begin() as conn:
            _insert(conn, DEPOT_CHECK, "bad", "m-a", "c-b", tenant_id="t-a")


# --- 3. Migration along the chain -------------------------------------------------------


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
    _seed_runs(conn)
    for table in TABLES:
        _row(conn, table, f"{table}-a", "m-a")
        _row(conn, table, f"{table}-b", "m-b")
        _row(conn, table, f"{table}-purged", "m-purged")


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
                    _row(conn, table, f"{table}-spoof", "m-a", tenant_id="t-b")
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
    assert f"CREATE OR REPLACE FUNCTION {metb.POSTGRES_RUN_FUNCTION_NAME}()" in sql
    for table in TABLES:
        assert f"ALTER TABLE {table} ADD COLUMN tenant_id VARCHAR" in sql
        assert f"ALTER TABLE {table} DISABLE TRIGGER trg_{table}_immutable" in sql
        assert metb.backfill_tenant_sql(table) in sql
        assert f"ALTER TABLE {table} ENABLE TRIGGER trg_{table}_immutable" in sql
        assert f"CREATE TRIGGER {metb.guard_trigger_name(table)}" in sql
    assert f"ON {DEPOT_CHECK} FOR EACH ROW EXECUTE FUNCTION {metb.POSTGRES_FUNCTION_NAME}()" in sql
    assert f"ON {OVERRIDES} FOR EACH ROW EXECUTE FUNCTION {metb.POSTGRES_RUN_FUNCTION_NAME}()" in sql


def test_frozen_migration_ddl_equals_runtime_ddl():
    module = _migration_module()
    assert module.TABLES == TABLES
    assert module.TENANT_ERROR == metb.TENANT_ERROR
    assert module.PG_RUN_FUNCTION_NAME == metb.POSTGRES_RUN_FUNCTION_NAME
    for table in TABLES:
        assert module.sqlite_guard(table) == metb.sqlite_guard_trigger(table)
        assert module.backfill(table) == metb.backfill_tenant_sql(table)


# --- 4. SQLite runtime patch (bestehende Desktop-DB) -------------------------------------


def test_sqlite_runtime_patch_adds_column_backfills_and_installs_guard(tmp_path):
    from alembic import command

    import database as db_module
    from services.product_eligibility_override_schema import ensure_sqlite_override_append_only

    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    command.upgrade(_alembic_config(url), MIGRATION_DOWN_REVISION)
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            _seed_legacy_rows(conn)
        db_module.ensure_runtime_columns(engine)
        ensure_sqlite_override_append_only(engine)
        quarantined = metb.ensure_sqlite_mandate_evidence_tenant_boundary(engine)
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
        assert ensure_sqlite_override_append_only(engine) is False
        assert metb.ensure_sqlite_mandate_evidence_tenant_boundary(engine)[OVERRIDES] == 1
        for table in TABLES:
            with pytest.raises(IntegrityError, match=metb.TENANT_ERROR):
                with engine.begin() as conn:
                    _row(conn, table, f"{table}-spoof", "m-a", tenant_id="t-b")
    finally:
        engine.dispose()


def test_override_column_list_keeps_tenant_for_the_sqlite_rebuild():
    """The SQLite rebuild path of the override table (legacy run FK) builds
    the table from OVERRIDE_COLUMNS; tenant_id must be part of it (last,
    ORM order)."""
    from services.product_eligibility_override_schema import OVERRIDE_COLUMNS

    assert list(OVERRIDE_COLUMNS)[-1] == "tenant_id"
    assert list(OVERRIDE_COLUMNS) == [c.name for c in Base.metadata.tables[OVERRIDES].columns]
