"""RISK-PROFILE-SIGNOFF-001: risk_profile_signoffs + risk_assessments.
signoff_id/_hash/_status muessen in ALLEN Schema-Quellen konsistent
auftauchen (ORM, Alembic, Bootstrap-SQL, ensure_runtime_columns), inklusive
Append-only-Trigger, ohne harten FK auf risk_assessments/mandates, und der
Altbestand (Signatur ohne Snapshot) wird als 'legacy_unbound' markiert.
Gleiches Muster wie test_risk_override_decision_schema_drift.py.
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

from models.profiling import RiskProfileSignoff  # noqa: E402

SCHEMA_FILE = BACKEND_ROOT / "ares_schema.sql"
REVISION = "d7b3f1a9c2e4"
TRIGGERS = {
    "trg_risk_profile_signoffs_no_update",
    "trg_risk_profile_signoffs_no_delete",
}
POINTER_COLUMNS = {"signoff_id", "signoff_hash", "signoff_status"}
MODEL_COLUMNS = {c.name for c in RiskProfileSignoff.__table__.columns}


def _columns(db_path, table):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _triggers(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        return {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND tbl_name='risk_profile_signoffs'"
            )
        }


def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def test_alembic_has_exactly_one_head_and_chain_contains_signoff_revision():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert REVISION in chain
    assert script.get_revision(REVISION).down_revision == "c4e9a7d2b815"


def test_fresh_bootstrap_has_signoff_table_pointer_columns_and_triggers(tmp_path):
    import database as db_module

    db_path = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    assert _columns(db_path, "risk_profile_signoffs") == MODEL_COLUMNS
    assert POINTER_COLUMNS <= _columns(db_path, "risk_assessments")
    assert _triggers(db_path) == TRIGGERS


def test_runtime_patch_restores_schema_and_marks_legacy_signatures(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "legacy.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("DROP TABLE risk_profile_signoffs")
        for column in sorted(POINTER_COLUMNS):
            conn.execute(f"ALTER TABLE risk_assessments DROP COLUMN {column}")
        conn.commit()

    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()
    # Altsignatur ohne Snapshot (vor RiskProfileSignoffV1) einspielen.
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO risk_assessments (id, mandate_id, version, is_current, valid_from, "
            "q_income_points, q_obligations_points, q_savings_points, q_wealth_points, "
            "risk_capacity_total, risk_capacity_profile, investment_horizon_years, "
            "investment_horizon_label, risk_capacity_score_x10, q_investment_goal_points, "
            "q_risk_preference_points, q_risk_behavior_points, risk_willingness_total, "
            "risk_willingness_profile, risk_willingness_score_x10, final_score_x10, "
            "final_profile, is_overridden, assessed_by, client_signed_at, client_signed_method) "
            "VALUES ('ra-legacy','m',1,1,'2026-01-01',1,1,1,1,4,'Ausgewogen',10,'Mehr als 12 Jahre',"
            "50,1,1,1,3,'Ausgewogen',50,50,'Ausgewogen',0,'u','2026-07-19T10:00:00Z','advisor_recorded')"
        )
        conn.commit()
    db_module.ensure_runtime_columns()  # idempotent + Backfill
    test_engine.dispose()

    assert _columns(db_path, "risk_profile_signoffs") == MODEL_COLUMNS
    assert POINTER_COLUMNS <= _columns(db_path, "risk_assessments")
    assert _triggers(db_path) == TRIGGERS
    with sqlite3.connect(str(db_path)) as conn:
        status = conn.execute(
            "SELECT signoff_status, client_signed_at FROM risk_assessments WHERE id='ra-legacy'"
        ).fetchone()
    # Altsignatur bleibt sichtbar, ist aber ausdruecklich ungebunden.
    assert status == ("legacy_unbound", "2026-07-19T10:00:00Z")


def test_orm_create_all_installs_append_only_triggers(tmp_path):
    from database import Base

    db_path = tmp_path / "orm.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    assert _triggers(db_path) == TRIGGERS


def test_alembic_head_creates_signoff_table_backfills_and_downgrade_is_reversible(tmp_path):
    from alembic import command

    db_path = tmp_path / "alembic.db"
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_cfg(db_url)
    command.upgrade(cfg, "c4e9a7d2b815")
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO risk_assessments (id, mandate_id, version, is_current, valid_from, "
            "q_income_points, q_obligations_points, q_savings_points, q_wealth_points, "
            "risk_capacity_total, risk_capacity_profile, investment_horizon_years, "
            "investment_horizon_label, risk_capacity_score_x10, q_investment_goal_points, "
            "q_risk_preference_points, q_risk_behavior_points, risk_willingness_total, "
            "risk_willingness_profile, risk_willingness_score_x10, final_score_x10, "
            "final_profile, is_overridden, assessed_at, assessed_by, created_at, updated_at, "
            "client_signed_at, client_signed_method) "
            "VALUES ('ra-legacy','m',1,1,'2026-01-01',1,1,1,1,4,'Ausgewogen',10,'x',50,1,1,1,3,"
            "'Ausgewogen',50,50,'Ausgewogen',0,'t','u','t','t','2026-07-19T10:00:00Z','portal')"
        )
        conn.commit()
    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    inspector = inspect(engine)
    assert {c["name"] for c in inspector.get_columns("risk_profile_signoffs")} == MODEL_COLUMNS
    assert POINTER_COLUMNS <= {c["name"] for c in inspector.get_columns("risk_assessments")}
    unique = {
        ix["name"]: ix for ix in inspector.get_indexes("risk_profile_signoffs")
    }["ux_risk_profile_signoff_sequence"]
    assert unique["unique"] and unique["column_names"] == ["assessment_id", "sequence_no"]
    engine.dispose()
    assert _triggers(db_path) == TRIGGERS
    with sqlite3.connect(str(db_path)) as conn:
        assert conn.execute(
            "SELECT signoff_status FROM risk_assessments WHERE id='ra-legacy'"
        ).fetchone() == ("legacy_unbound",)

    command.downgrade(cfg, "c4e9a7d2b815")
    engine = create_engine(db_url)
    inspector = inspect(engine)
    assert "risk_profile_signoffs" not in inspector.get_table_names()
    assert "risk_override_decisions" in inspector.get_table_names()
    assert not POINTER_COLUMNS & {c["name"] for c in inspector.get_columns("risk_assessments")}
    engine.dispose()


def test_alembic_signoff_revision_emits_postgres_immutability_trigger():
    from alembic import command

    buffer = io.StringIO()
    cfg = _alembic_cfg("postgresql://user:pass@localhost/db")
    cfg.output_buffer = buffer
    command.upgrade(cfg, f"c4e9a7d2b815:{REVISION}", sql=True)
    sql = buffer.getvalue()
    assert "CREATE TABLE risk_profile_signoffs" in sql
    assert "risk_profile_signoffs_immutable" in sql
    assert "BEFORE UPDATE OR DELETE ON risk_profile_signoffs" in sql
    assert "legacy_unbound" in sql


@pytest.mark.parametrize("statement", [
    "UPDATE risk_profile_signoffs SET note = 'x'",
    "DELETE FROM risk_profile_signoffs",
])
def test_bootstrap_triggers_block_mutation(tmp_path, statement):
    import database as db_module

    db_path = tmp_path / "immut.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO risk_profile_signoffs (id, assessment_id, mandate_id, assessment_version, "
            "sequence_no, effective_score_x10, effective_profile, final_score_x10, is_overridden, "
            "override_binding, assessment_input_hash, method, evidence_level, actor_id, signed_at, "
            "rules_version, signoff_hash, created_at) VALUES "
            "('s1','ra','m',1,1,50,'Ausgewogen',50,0,'no_override','h','advisor_recorded',"
            "'advisor_attested','u','t','v','h','t')"
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(statement)


def test_bootstrap_rejects_decision_binding_without_decision_reference(tmp_path):
    import database as db_module

    db_path = tmp_path / "check.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO risk_profile_signoffs (id, assessment_id, mandate_id, "
                "assessment_version, sequence_no, effective_score_x10, effective_profile, "
                "final_score_x10, is_overridden, override_binding, assessment_input_hash, method, "
                "evidence_level, actor_id, signed_at, rules_version, signoff_hash, created_at) "
                "VALUES ('s1','ra','m',1,1,50,'Ausgewogen',50,1,'decision','h','advisor_recorded',"
                "'advisor_attested','u','t','v','h','t')"
            )


def test_signoff_table_has_no_hard_fk_to_assessments_or_mandates(tmp_path):
    import database as db_module
    from alembic import command

    fresh = tmp_path / "fk_fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=fresh, schema_path=SCHEMA_FILE)
    migrated = tmp_path / "fk_alembic.db"
    command.upgrade(_alembic_cfg(f"sqlite:///{migrated}"), "head")
    patched = tmp_path / "fk_patch.db"
    with sqlite3.connect(str(patched)) as conn:
        for ddl in db_module.RISK_PROFILE_SIGNOFF_SQLITE_TABLE_DDL:
            conn.execute(ddl)
    for db_path in (fresh, migrated, patched):
        with sqlite3.connect(str(db_path)) as conn:
            targets = {row[2] for row in conn.execute(
                "PRAGMA foreign_key_list(risk_profile_signoffs)"
            )}
        assert targets == {"users"}, (db_path.name, targets)
    assert {fk.column.table.name for fk in RiskProfileSignoff.__table__.foreign_keys} == {"users"}


def test_advisory_log_system_event_column_in_all_schema_sources(tmp_path, monkeypatch):
    """CIO-Abnahme #662: Portal-Signoffs sind im Beratungsprotokoll als
    System-Ereignis gekennzeichnet (advisory_log.system_event) -- in
    Bootstrap, Runtime-Patch, ORM und Alembic (inkl. Downgrade)."""
    import database as db_module
    from alembic import command
    from models.review import AdvisoryLog

    assert "system_event" in {c.name for c in AdvisoryLog.__table__.columns}
    fresh = tmp_path / "evt_fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=fresh, schema_path=SCHEMA_FILE)
    assert "system_event" in _columns(fresh, "advisory_log")

    with sqlite3.connect(str(fresh)) as conn:
        conn.execute("ALTER TABLE advisory_log DROP COLUMN system_event")
        conn.commit()
    test_engine = create_engine(f"sqlite:///{fresh}")
    db_module.run_advisory_log_migration(test_engine)
    db_module.run_advisory_log_migration(test_engine)  # idempotent
    test_engine.dispose()
    assert "system_event" in _columns(fresh, "advisory_log")

    migrated = tmp_path / "evt_alembic.db"
    cfg = _alembic_cfg(f"sqlite:///{migrated}")
    command.upgrade(cfg, "head")
    assert "system_event" in _columns(migrated, "advisory_log")
    command.downgrade(cfg, "c4e9a7d2b815")
    assert "system_event" not in _columns(migrated, "advisory_log")
