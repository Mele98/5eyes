"""Evidenz-Spalten in allen Schema-Quellen (ORM, Alembic, Runtime-Patch).

- optimizer_runs.objective_contract_{version,hash,json} (b0eeb3e878b5)
- target_allocations.goal_driver_evidence_json (3960ca037812)

Kettenbasiert -- nie "ist Head".
"""
from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.allocation import OptimizerRun, TargetAllocation  # noqa: E402

SCHEMA_FILE = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
CASES = [
    pytest.param(
        "b0eeb3e878b5", "94089093281c", "optimizer_runs", OptimizerRun,
        ("objective_contract_version", "objective_contract_hash", "objective_contract_json"),
        id="objective_contract",
    ),
    pytest.param(
        "3960ca037812", "b0eeb3e878b5", "target_allocations", TargetAllocation,
        ("goal_driver_evidence_json",),
        id="goal_driver_evidence",
    ),
]


def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _columns(db_path, table):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


@pytest.mark.parametrize("revision, down, table, model, columns", CASES)
def test_orm_declares_columns(revision, down, table, model, columns):
    assert set(columns) <= {c.name for c in model.__table__.columns}
    assert all(model.__table__.columns[name].nullable for name in columns)


@pytest.mark.parametrize("revision, down, table, model, columns", CASES)
def test_revision_is_in_the_single_head_chain(revision, down, table, model, columns):
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert revision in chain
    assert script.get_revision(revision).down_revision == down


@pytest.mark.parametrize("revision, down, table, model, columns", CASES)
def test_alembic_upgrade_adds_and_downgrade_removes(tmp_path, revision, down, table, model, columns):
    from alembic import command

    db_path = tmp_path / "alembic.db"
    cfg = _alembic_cfg(f"sqlite:///{db_path}")
    command.upgrade(cfg, down)
    assert not set(columns) & _columns(db_path, table)
    command.upgrade(cfg, revision)
    assert set(columns) <= _columns(db_path, table)
    command.downgrade(cfg, down)
    assert not set(columns) & _columns(db_path, table)


@pytest.mark.parametrize("revision, down, table, model, columns", CASES)
def test_alembic_revision_emits_postgres_add_column(revision, down, table, model, columns):
    from alembic import command

    buffer = io.StringIO()
    cfg = _alembic_cfg("postgresql://user:pass@localhost/db")
    cfg.output_buffer = buffer
    command.upgrade(cfg, f"{down}:{revision}", sql=True)
    for name in columns:
        assert f"ALTER TABLE {table} ADD COLUMN {name}" in buffer.getvalue()


def test_runtime_patch_adds_columns_to_bootstrapped_db(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "runtime.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    # Die Bootstrap-DDL fuehrt optimizer_runs nicht (ORM-Tabelle); eine
    # Alt-DB hat sie mit dem Vor-Stand-Feldsatz.
    with sqlite3.connect(str(db_path)) as conn:
        if not _columns(db_path, "optimizer_runs"):
            conn.execute("CREATE TABLE optimizer_runs (id TEXT PRIMARY KEY, validation_seed INTEGER)")
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    test_engine.dispose()
    assert {"objective_contract_version", "objective_contract_hash",
            "objective_contract_json"} <= _columns(db_path, "optimizer_runs")
    assert "goal_driver_evidence_json" in _columns(db_path, "target_allocations")
