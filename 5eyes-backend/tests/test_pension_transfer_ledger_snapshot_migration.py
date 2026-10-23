"""PENSION-TRANSFER-LEDGER-001: Spalte target_allocations.
pension_transfer_ledger_snapshot_json in allen Schema-Quellen (ORM, Alembic,
Runtime-Patch). Kettenbasiert -- nie "ist Head"."""
from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.allocation import TargetAllocation  # noqa: E402

REVISION = "b8e4d2a7c913"
DOWN_REVISION = "f3a8d1c6b4e2"
COLUMN = "pension_transfer_ledger_snapshot_json"
SCHEMA_FILE = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"


def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _columns(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(target_allocations)")}


def test_orm_declares_column():
    assert COLUMN in {c.name for c in TargetAllocation.__table__.columns}


def test_revision_is_in_single_head_chain_after_develop_head():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert REVISION in chain
    assert script.get_revision(REVISION).down_revision == DOWN_REVISION


def test_alembic_upgrade_adds_and_downgrade_removes_column(tmp_path):
    from alembic import command

    db_path = tmp_path / "alembic.db"
    cfg = _alembic_cfg(f"sqlite:///{db_path}")
    command.upgrade(cfg, DOWN_REVISION)
    assert COLUMN not in _columns(db_path)
    command.upgrade(cfg, REVISION)
    assert COLUMN in _columns(db_path)
    command.downgrade(cfg, DOWN_REVISION)
    assert COLUMN not in _columns(db_path)


def test_alembic_revision_emits_postgres_add_column():
    from alembic import command

    buffer = io.StringIO()
    cfg = _alembic_cfg("postgresql://user:pass@localhost/db")
    cfg.output_buffer = buffer
    command.upgrade(cfg, f"{DOWN_REVISION}:{REVISION}", sql=True)
    assert f"ALTER TABLE target_allocations ADD COLUMN {COLUMN}" in buffer.getvalue()


def test_runtime_patch_adds_column_to_bootstrapped_db(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "runtime.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    test_engine.dispose()
    assert COLUMN in _columns(db_path)
