"""RISK-OVERRIDE-WRITE-BOUNDARY-001 Restbefund B: risk_override_decisions +
risk_assessments.override_decision_id/_hash muessen in ALLEN Schema-Quellen
konsistent auftauchen (ORM, Alembic, Bootstrap-SQL, ensure_runtime_columns),
inklusive der Append-only-Trigger. Gleiche Bugklasse wie
test_cashflow_goal_include_toggle_schema_drift.py.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.postgres_rls import import_tenant_models  # noqa: E402

import_tenant_models()  # alle models/*.py, damit create_all jede FK aufloest

from models.profiling import RiskOverrideDecision  # noqa: E402

SCHEMA_FILE = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
TRIGGERS = {
    "trg_risk_override_decisions_no_update",
    "trg_risk_override_decisions_no_delete",
}
POINTER_COLUMNS = {"override_decision_id", "override_decision_hash"}
MODEL_COLUMNS = {c.name for c in RiskOverrideDecision.__table__.columns}


def _columns(db_path, table):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _triggers(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        return {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND tbl_name='risk_override_decisions'"
            )
        }


def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def test_alembic_has_exactly_one_head_and_it_is_the_decision_revision():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    # Genau ein Head; spaetere Revisionen duerfen auf der Decision-Revision
    # aufbauen, solange sie in der linearen Kette bleibt.
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert "c4e9a7d2b815" in chain


def test_fresh_bootstrap_has_decision_table_pointer_columns_and_triggers(tmp_path):
    import database as db_module

    db_path = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    assert _columns(db_path, "risk_override_decisions") == MODEL_COLUMNS
    assert POINTER_COLUMNS <= _columns(db_path, "risk_assessments")
    assert _triggers(db_path) == TRIGGERS


def test_runtime_patch_restores_table_columns_and_triggers_on_legacy_db(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "legacy.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("DROP TABLE risk_override_decisions")
        conn.execute("ALTER TABLE risk_assessments DROP COLUMN override_decision_id")
        conn.execute("ALTER TABLE risk_assessments DROP COLUMN override_decision_hash")
        conn.commit()
    assert not POINTER_COLUMNS & _columns(db_path, "risk_assessments")

    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    test_engine.dispose()

    assert _columns(db_path, "risk_override_decisions") == MODEL_COLUMNS
    assert POINTER_COLUMNS <= _columns(db_path, "risk_assessments")
    assert _triggers(db_path) == TRIGGERS


def test_orm_create_all_installs_append_only_triggers(tmp_path):
    from database import Base

    db_path = tmp_path / "orm.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    assert _triggers(db_path) == TRIGGERS


def test_alembic_head_creates_decision_table_and_downgrade_is_reversible(tmp_path):
    from alembic import command

    db_path = tmp_path / "alembic.db"
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_cfg(db_url)
    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    inspector = inspect(engine)
    assert {c["name"] for c in inspector.get_columns("risk_override_decisions")} == MODEL_COLUMNS
    assert POINTER_COLUMNS <= {c["name"] for c in inspector.get_columns("risk_assessments")}
    unique = {
        ix["name"]: ix for ix in inspector.get_indexes("risk_override_decisions")
    }["ux_risk_override_decision_sequence"]
    assert unique["unique"] and unique["column_names"] == ["assessment_id", "sequence_no"]
    engine.dispose()
    assert _triggers(db_path) == TRIGGERS

    # Kettenbasiert statt head-gekoppelt: zurueck VOR die Decision-Revision
    # (spaetere Revisionen wie f3a8d1c6b4e2 liegen darueber).
    command.downgrade(cfg, "a6d2e8f4c1b9")
    engine = create_engine(db_url)
    inspector = inspect(engine)
    assert "risk_override_decisions" not in inspector.get_table_names()
    assert not POINTER_COLUMNS & {c["name"] for c in inspector.get_columns("risk_assessments")}
    engine.dispose()


def test_alembic_head_emits_postgres_immutability_trigger():
    import io

    from alembic import command

    buffer = io.StringIO()
    cfg = _alembic_cfg("postgresql://user:pass@localhost/db")
    cfg.output_buffer = buffer
    command.upgrade(cfg, "a6d2e8f4c1b9:c4e9a7d2b815", sql=True)
    sql = buffer.getvalue()
    assert "CREATE TABLE risk_override_decisions" in sql
    assert "risk_override_decisions_immutable" in sql
    assert "BEFORE UPDATE OR DELETE ON risk_override_decisions" in sql


@pytest.mark.parametrize("statement", [
    "UPDATE risk_override_decisions SET reason = 'x'",
    "DELETE FROM risk_override_decisions",
])
def test_bootstrap_triggers_block_mutation(tmp_path, statement):
    import database as db_module

    db_path = tmp_path / "immut.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO risk_override_decisions (id, assessment_id, mandate_id, "
            "assessment_version, sequence_no, basis_final_score_x10, requested_score_x10, "
            "requested_profile, reason, actor_id, decided_at, rules_version, decision_hash, "
            "created_at) VALUES ('d1','ra','m',1,1,50,60,'Ausgewogen','r','u','t','v','h','t')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(statement)


def test_decision_table_has_no_hard_fk_to_assessments_or_mandates(tmp_path):
    """CIO-Entscheid 2026-10-19: Muster audit_log -- nur der Akteur verweist
    per FK auf users; assessment_id/mandate_id sind indizierte Spalten,
    damit Foundation-/Demo-Purges die Decisions stehen lassen koennen. Gilt
    fuer Bootstrap-DDL, Runtime-Patch-DDL und Alembic."""
    import database as db_module
    from alembic import command

    fresh = tmp_path / "fk_fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=fresh, schema_path=SCHEMA_FILE)
    migrated = tmp_path / "fk_alembic.db"
    command.upgrade(_alembic_cfg(f"sqlite:///{migrated}"), "head")
    patched = tmp_path / "fk_patch.db"
    with sqlite3.connect(str(patched)) as conn:
        for ddl in db_module.RISK_OVERRIDE_DECISION_SQLITE_TABLE_DDL:
            conn.execute(ddl)
    for db_path in (fresh, migrated, patched):
        with sqlite3.connect(str(db_path)) as conn:
            targets = {row[2] for row in conn.execute(
                "PRAGMA foreign_key_list(risk_override_decisions)"
            )}
        assert targets == {"users"}, (db_path.name, targets)
    assert {fk.column.table.name for fk in RiskOverrideDecision.__table__.foreign_keys} == {"users"}
