"""W4-d: Umbenennung der audit_log-Immutability-Funktion gegen ECHTES PostgreSQL.

Die Revision f6a2c8e4b1d7 benennt die Funktion hinter den Triggern
``trg_audit_log_no_update``/``trg_audit_log_no_delete`` per ``ALTER FUNCTION
... RENAME`` in ``fn_ares_audit_log_immutable`` um. Geprueft wird hier, was
nur ein echtes Postgres zeigen kann:

* nach ``upgrade head`` haengen beide Trigger an der umbenannten Funktion
  (gleiche OID wie vorher, also kein DROP/CREATE);
* UPDATE und DELETE auf ``audit_log`` scheitern weiterhin, INSERT geht;
* ``downgrade -1`` stellt den Namen der anlegenden Revision wieder her,
  die Trigger greifen auch dann; erneutes ``upgrade`` ist wieder gruen;
* ist die Funktion schon umbenannt (z.B. durch den externen Migrator), ist
  die Revision ein No-op;
* fehlt ein Trigger, bricht die Revision ab, statt still weiterzulaufen.

Eigenes Schema je Lauf (search_path), gleiches Muster wie
``test_postgres_alembic_views_live.py``. Ohne ``POSTGRES_TEST_DATABASE_URL``
wird uebersprungen; in CI setzt der ``postgres-rls``-Job sie.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

TARGET = "fn_ares_audit_log_immutable"
RENAME_REVISION = "f6a2c8e4b1d7"
PREVIOUS_REVISION = "2cbc77503cd9"
TRIGGERS = ("trg_audit_log_no_delete", "trg_audit_log_no_update")


def _creating_name() -> str:
    path = BACKEND_ROOT / "alembic" / "versions" / "e84f9a2d1c70_postgres_market_data_runtime_tables.py"
    spec = importlib.util.spec_from_file_location("_e84_for_live_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AUDIT_LOG_IMMUTABLE_FUNCTION


def _qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@pytest.fixture()
def pg_schema():
    pytest.importorskip("psycopg")
    assert POSTGRES_URL is not None
    schema = f"auditfn_{uuid.uuid4().hex[:12]}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    sep = "&" if "?" in POSTGRES_URL else "?"
    scoped_url = f"{POSTGRES_URL}{sep}options=-csearch_path%3D{schema}"
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", scoped_url.replace("%", "%%"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    engine = create_engine(scoped_url, future=True)
    try:
        yield cfg, engine, schema
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {_qi(schema)} CASCADE"))
        admin.dispose()


def _bindings(engine, schema: str) -> dict[str, tuple[str, int]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT t.tgname, p.proname, p.oid::bigint FROM pg_trigger t"
                " JOIN pg_proc p ON p.oid = t.tgfoid"
                " JOIN pg_class c ON c.oid = t.tgrelid"
                " JOIN pg_namespace n ON n.oid = c.relnamespace"
                " WHERE c.relname = 'audit_log' AND n.nspname = :schema"
                " AND NOT t.tgisinternal AND t.tgenabled <> 'D' ORDER BY t.tgname"
            ),
            {"schema": schema},
        ).all()
    return {r[0]: (r[1], int(r[2])) for r in rows}


def _assert_immutable(engine) -> None:
    row_id = f"audit-{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_log (id, user_name, table_name, record_id, action, created_at)"
                " VALUES (:id, 'probe', 'probe_table', 'r1', 'CREATE', '2026-10-24T00:00:00Z')"
            ),
            {"id": row_id},
        )
    for stmt in (
        "UPDATE audit_log SET user_name = 'changed' WHERE id = :id",
        "DELETE FROM audit_log WHERE id = :id",
    ):
        with pytest.raises(Exception, match="audit_log is immutable"):
            with engine.begin() as conn:
                conn.execute(text(stmt), {"id": row_id})
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT user_name FROM audit_log WHERE id = :id"), {"id": row_id}
        ).scalar_one() == "probe"


def _head(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_rename_keeps_oid_and_triggers_and_downgrade_restores(pg_schema):
    cfg, engine, schema = pg_schema
    old_name = _creating_name()

    command.upgrade(cfg, PREVIOUS_REVISION)
    before = _bindings(engine, schema)
    assert set(before) == set(TRIGGERS)
    assert {name for name, _ in before.values()} == {old_name}
    oids = {o for _, o in before.values()}
    assert len(oids) == 1
    oid = next(iter(oids))

    command.upgrade(cfg, "head")
    assert _head(engine) == RENAME_REVISION
    after = _bindings(engine, schema)
    assert after == {trg: (TARGET, oid) for trg in TRIGGERS}
    _assert_immutable(engine)

    command.downgrade(cfg, "-1")
    assert _head(engine) == PREVIOUS_REVISION
    assert _bindings(engine, schema) == {trg: (old_name, oid) for trg in TRIGGERS}
    _assert_immutable(engine)

    command.upgrade(cfg, "head")
    assert _bindings(engine, schema) == after
    _assert_immutable(engine)


def test_rename_is_a_noop_when_already_renamed(pg_schema):
    cfg, engine, schema = pg_schema
    old_name = _creating_name()
    command.upgrade(cfg, PREVIOUS_REVISION)
    oid = next(iter(_bindings(engine, schema).values()))[1]
    # Wie der externe Migrator: in place umbenennen, bevor die Revision laeuft.
    with engine.begin() as conn:
        conn.execute(text(f"ALTER FUNCTION {_qi(old_name)}() RENAME TO {TARGET}"))
    command.upgrade(cfg, "head")
    assert _head(engine) == RENAME_REVISION
    assert _bindings(engine, schema) == {trg: (TARGET, oid) for trg in TRIGGERS}
    _assert_immutable(engine)


def test_rename_refuses_when_a_trigger_is_missing(pg_schema):
    cfg, engine, schema = pg_schema
    command.upgrade(cfg, PREVIOUS_REVISION)
    with engine.begin() as conn:
        conn.execute(text("DROP TRIGGER trg_audit_log_no_delete ON audit_log"))
    with pytest.raises(Exception, match="audit_log immutability triggers missing"):
        command.upgrade(cfg, "head")
    assert _head(engine) == PREVIOUS_REVISION
