"""SIGN-001: die drei append-only Tabellen der Vor-Ort-Signatur muessen in
ALLEN Schema-Quellen konsistent sein (ORM, Alembic, Bootstrap-SQL,
ensure_runtime_columns), inklusive Unveraenderlichkeits-Triggern, Unique-
Indizes (Uebergaenge, Einmal-Challenge, ein Evidence-Paket je Vorgang) und
ohne harten FK auf mandates/clients (Purge-fest). Migrationstests sind
kettenbasiert (nie "ist Head").
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

from database import Base  # noqa: E402
from models.onsite_signature import APPEND_ONLY_TABLES  # noqa: E402

SCHEMA_FILE = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
REVISION = "a9e3c5d7f1b2"
PREVIOUS = "c4e8a2d6f913"
UNIQUE_INDEXES = {
    "onsite_signature_events": {
        "ux_onsite_signature_events_sequence": ["transaction_id", "sequence_no"],
        "ux_onsite_signature_events_challenge_use": ["challenge_id"],
    },
    "onsite_signature_challenges": {},
    "onsite_signature_evidence": {
        "ux_onsite_signature_evidence_transaction": ["transaction_id"],
    },
}


def _model_columns(table):
    return {c.name for c in Base.metadata.tables[table].columns}


def _columns(db_path, table):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _triggers(db_path, table):
    with sqlite3.connect(str(db_path)) as conn:
        return {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)
            )
        }


def _expected_triggers(table, tenant_guard):
    # PG-002: der Mandanten-Guard entsteht bei create_all/Alembic sofort, im
    # Bootstrap-/Runtime-Pfad erst ueber ensure_sqlite_mandate_evidence_tenant_boundary.
    guard = {f"trg_{table}_tenant_guard"} if tenant_guard else set()
    return {f"trg_{table}_no_update", f"trg_{table}_no_delete"} | guard


def _assert_schema(db_path, *, tenant_guard=False):
    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    try:
        for table in APPEND_ONLY_TABLES:
            assert _columns(db_path, table) == _model_columns(table), table
            assert _triggers(db_path, table) == _expected_triggers(table, tenant_guard), table
            unique = {
                ix["name"]: ix["column_names"]
                for ix in inspector.get_indexes(table) if ix["unique"]
            }
            for name, columns in UNIQUE_INDEXES[table].items():
                assert unique.get(name) == columns, (table, name, unique)
            fk_targets = {fk["referred_table"] for fk in inspector.get_foreign_keys(table)}
            assert fk_targets <= {"users"}, (table, fk_targets)
    finally:
        engine.dispose()


def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def test_alembic_chain_contains_revision_with_expected_parent():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert REVISION in chain
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_fresh_bootstrap_matches_orm(tmp_path):
    import database as db_module

    db_path = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    _assert_schema(db_path)


def test_orm_create_all_matches(tmp_path):
    db_path = tmp_path / "orm.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    _assert_schema(db_path, tenant_guard=True)


def test_runtime_patch_restores_tables_idempotently(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "legacy.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    with sqlite3.connect(str(db_path)) as conn:
        for table in APPEND_ONLY_TABLES:
            conn.execute(f"DROP TABLE {table}")
        conn.commit()
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    test_engine.dispose()
    _assert_schema(db_path)


def test_alembic_upgrade_and_downgrade_along_the_chain(tmp_path):
    from alembic import command

    db_path = tmp_path / "alembic.db"
    db_url = f"sqlite:///{db_path}"
    cfg = _alembic_cfg(db_url)
    # Kettenbasiert ueber REVISION hinaus: spaetere Revisionen (z. B. PG-002
    # tenant_id) gehoeren zum Schema, das das ORM heute beschreibt.
    command.upgrade(cfg, "head")
    _assert_schema(db_path, tenant_guard=True)
    command.downgrade(cfg, PREVIOUS)
    engine = create_engine(db_url)
    names = set(inspect(engine).get_table_names())
    engine.dispose()
    assert not names & set(APPEND_ONLY_TABLES)
    assert "risk_capacity_plausibility_evaluations" in names


def test_alembic_revision_emits_postgres_immutability_triggers():
    from alembic import command

    buffer = io.StringIO()
    cfg = _alembic_cfg("postgresql://user:pass@localhost/db")
    cfg.output_buffer = buffer
    command.upgrade(cfg, f"{PREVIOUS}:{REVISION}", sql=True)
    sql = buffer.getvalue()
    for table in APPEND_ONLY_TABLES:
        assert f"CREATE TABLE {table}" in sql
        assert f"BEFORE UPDATE OR DELETE ON {table}" in sql
    assert "WHERE challenge_id IS NOT NULL AND event_type IN ('FACTOR_VERIFIED','FACTOR_REJECTED')" in sql


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
@pytest.mark.parametrize("statement", ["UPDATE {t} SET id = id", "DELETE FROM {t}"])
def test_bootstrap_triggers_block_mutation(tmp_path, table, statement):
    import database as db_module

    db_path = tmp_path / "trg.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    columns = sorted(_model_columns(table))
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            ["1" for _ in columns],
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(statement.format(t=table))
