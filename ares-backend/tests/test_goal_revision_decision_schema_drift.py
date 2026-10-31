"""GOAL-REVISION-DECISION-001: goal_revision_decisions muss in ALLEN
Schema-Quellen konsistent auftauchen (ORM, Alembic, Bootstrap-SQL,
ensure_runtime_columns), inklusive Append-only-Trigger und ohne harten FK
auf goals/mandates (Purge-fest). Muster: test_risk_profile_signoff_schema_
drift.py.
"""
from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.postgres_rls import import_tenant_models  # noqa: E402

import_tenant_models()

from models.wealth import GoalRevisionDecision  # noqa: E402

SCHEMA_FILE = BACKEND_ROOT / "ares_schema.sql"
REVISION = "e3c7a91f5b28"
PREVIOUS = "e5a1c7f3b9d2"
TRIGGERS = {
    "trg_goal_revision_decisions_no_update",
    "trg_goal_revision_decisions_no_delete",
}
MODEL_COLUMNS = {c.name for c in GoalRevisionDecision.__table__.columns}

_INSERT = (
    "INSERT INTO goal_revision_decisions (id, goal_id, mandate_id, sequence_no, "
    "goal_snapshot_hash, goal_snapshot_json, previous_hardness, new_status, reason, "
    "evidence_status, evidence_engine_version, actor_id, decided_at, rules_version, "
    "decision_hash, created_at) VALUES ('d1','g','m',1,'h','{}','Hart',"
    "'nachrangiges_wunschziel','Begruendung','not_found_reachable_locally',"
    "'saa_resampled_v11','u','t','v','h','t')"
)


def _columns(db_path, table):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _triggers(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        return {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND tbl_name='goal_revision_decisions'"
            )
        }


def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def test_alembic_has_exactly_one_head_and_chain_contains_goal_revision():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert REVISION in chain
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_fresh_bootstrap_has_table_and_triggers(tmp_path):
    import database as db_module

    db_path = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    assert _columns(db_path, "goal_revision_decisions") == MODEL_COLUMNS
    assert _triggers(db_path) == TRIGGERS


def test_bootstrap_sql_and_runtime_ddl_are_textually_identical():
    import database as db_module

    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    assert db_module.GOAL_REVISION_DECISION_SQLITE_TABLE_DDL[0] in sql


def test_runtime_patch_restores_schema(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "legacy.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("DROP TABLE goal_revision_decisions")
        conn.commit()
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    test_engine.dispose()
    assert _columns(db_path, "goal_revision_decisions") == MODEL_COLUMNS
    assert _triggers(db_path) == TRIGGERS


def test_orm_create_all_installs_append_only_triggers(tmp_path):
    from database import Base

    db_path = tmp_path / "orm.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    assert _triggers(db_path) == TRIGGERS


def test_alembic_head_creates_table_and_downgrade_is_reversible(tmp_path):
    from alembic import command

    db_path = tmp_path / "alembic.db"
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_cfg(db_url)
    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    inspector = inspect(engine)
    assert {c["name"] for c in inspector.get_columns("goal_revision_decisions")} == MODEL_COLUMNS
    unique = {
        ix["name"]: ix for ix in inspector.get_indexes("goal_revision_decisions")
    }["ux_goal_revision_decision_sequence"]
    assert unique["unique"] and unique["column_names"] == ["goal_id", "sequence_no"]
    engine.dispose()
    assert _triggers(db_path) == TRIGGERS

    command.downgrade(cfg, PREVIOUS)
    engine = create_engine(db_url)
    assert "goal_revision_decisions" not in inspect(engine).get_table_names()
    assert "risk_profile_signoffs" in inspect(engine).get_table_names()
    engine.dispose()


def test_alembic_revision_emits_postgres_immutability_trigger():
    from alembic import command

    buffer = io.StringIO()
    cfg = _alembic_cfg("postgresql://user:pass@localhost/db")
    cfg.output_buffer = buffer
    command.upgrade(cfg, f"{PREVIOUS}:{REVISION}", sql=True)
    sql = buffer.getvalue()
    assert "CREATE TABLE goal_revision_decisions" in sql
    assert "goal_revision_decisions_immutable" in sql
    assert "BEFORE UPDATE OR DELETE ON goal_revision_decisions" in sql


@pytest.mark.parametrize("statement", [
    "UPDATE goal_revision_decisions SET reason = 'x'",
    "DELETE FROM goal_revision_decisions",
])
def test_bootstrap_triggers_block_mutation(tmp_path, statement):
    import database as db_module

    db_path = tmp_path / "immut.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(_INSERT)
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(statement)


def test_bootstrap_rejects_unknown_new_status(tmp_path):
    import database as db_module

    db_path = tmp_path / "check.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(_INSERT.replace("'nachrangiges_wunschziel'", "'geloescht'"))


def test_table_has_no_hard_fk_to_goals_or_mandates(tmp_path):
    import database as db_module
    from alembic import command

    fresh = tmp_path / "fk_fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=fresh, schema_path=SCHEMA_FILE)
    migrated = tmp_path / "fk_alembic.db"
    command.upgrade(_alembic_cfg(f"sqlite:///{migrated}"), "head")
    patched = tmp_path / "fk_patch.db"
    with sqlite3.connect(str(patched)) as conn:
        for ddl in db_module.GOAL_REVISION_DECISION_SQLITE_TABLE_DDL:
            conn.execute(ddl)
    for db_path in (fresh, migrated, patched):
        with sqlite3.connect(str(db_path)) as conn:
            targets = {row[2] for row in conn.execute(
                "PRAGMA foreign_key_list(goal_revision_decisions)"
            )}
        assert targets == {"users"}, (db_path.name, targets)
    assert {fk.column.table.name for fk in GoalRevisionDecision.__table__.foreign_keys} == {"users"}
