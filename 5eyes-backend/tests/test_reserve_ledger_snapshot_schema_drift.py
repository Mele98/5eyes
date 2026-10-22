"""RESERVE-LEDGER-SNAPSHOT-001: target_allocations.reserve_funding_ledger_json/_hash
muessen in allen Schema-Quellen (ORM, Alembic, Bootstrap + ensure_runtime_columns)
vorhanden sein; Alembic bleibt bei genau einem Head (kettenbasiert geprueft).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.allocation import TargetAllocation  # noqa: E402

SCHEMA_FILE = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
REVISION = "a3f6c1e8d924"
DOWN_REVISION = "d7b3f1a9c2e4"
COLUMNS = {"reserve_funding_ledger_json", "reserve_funding_ledger_hash"}


def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _columns(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(target_allocations)")}


def test_orm_declares_snapshot_columns():
    assert COLUMNS <= {c.name for c in TargetAllocation.__table__.columns}


def test_alembic_single_head_chain_contains_snapshot_revision():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert REVISION in chain
    assert script.get_revision(REVISION).down_revision == DOWN_REVISION


def test_bootstrap_plus_runtime_patch_has_snapshot_columns(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    test_engine.dispose()
    assert COLUMNS <= _columns(db_path)


def test_alembic_upgrade_and_downgrade_snapshot_revision(tmp_path):
    from alembic import command

    db_path = tmp_path / "alembic.db"
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_cfg(db_url)
    command.upgrade(cfg, DOWN_REVISION)
    assert not COLUMNS & _columns(db_path)
    command.upgrade(cfg, REVISION)
    engine = create_engine(db_url)
    assert COLUMNS <= {c["name"] for c in inspect(engine).get_columns("target_allocations")}
    engine.dispose()
    command.downgrade(cfg, DOWN_REVISION)
    assert not COLUMNS & _columns(db_path)
