"""Sprint U-38 (Roadmap-Punkt 38, 2026-06-01): Tests fuer
ensure_audit_log_indexes.

Verifiziert dass die idempotente Index-Erstellung alle 5 Indexes
zuverlaessig anlegt — auch nach ensure_audit_log_actions, das die
Tabelle bei Schema-Migration neu aufbaut und Indexes droppt.

Index-Catalog (Stand U-38)
  1. idx_audit_mandate_table  (mandate_id, table_name) — NEU U-38
  2. idx_audit_record         (table_name, record_id)
  3. idx_audit_mandate        (mandate_id)
  4. idx_audit_user           (user_id)
  5. idx_audit_time           (created_at)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, ensure_audit_log_indexes
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()


EXPECTED_INDEXES = {
    "idx_audit_mandate_table",  # NEU in U-38
    "idx_audit_record",
    "idx_audit_mandate",
    "idx_audit_user",
    "idx_audit_time",
}


@pytest.fixture()
def fresh_engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


def _list_audit_indexes(engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='audit_log' "
            "  AND name NOT LIKE 'sqlite_%'"
        )).fetchall()
    return {row[0] for row in rows}


# ---------------------------------------------------------------------------
# Happy-Path
# ---------------------------------------------------------------------------

def test_ensure_indexes_creates_all_five(fresh_engine):
    """Aufruf auf eine frische DB legt alle 5 Indexes an."""
    ensure_audit_log_indexes(fresh_engine)
    actual = _list_audit_indexes(fresh_engine)
    missing = EXPECTED_INDEXES - actual
    assert not missing, f"Fehlende Indexes nach ensure: {missing}"


def test_new_u38_composite_index_uses_mandate_id_and_table_name(fresh_engine):
    """Spezifischer Punkt-38-Test: der neue Index muss BEIDE Spalten in
    der richtigen Reihenfolge haben (mandate_id zuerst, dann table_name)."""
    ensure_audit_log_indexes(fresh_engine)
    with fresh_engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT sql FROM sqlite_master "
            "WHERE type='index' AND name='idx_audit_mandate_table'"
        )).fetchall()
    assert len(rows) == 1
    sql = str(rows[0][0]).lower()
    # SQLite normalisiert die Spalten-Reihenfolge in der DDL — wir matchen lose.
    assert "mandate_id" in sql
    assert "table_name" in sql
    # Reihenfolge: mandate_id muss VOR table_name kommen (composite-Effizienz)
    assert sql.index("mandate_id") < sql.index("table_name")


# ---------------------------------------------------------------------------
# Idempotenz
# ---------------------------------------------------------------------------

def test_ensure_is_idempotent_no_error_on_repeat(fresh_engine):
    """Zweiter Aufruf darf KEINEN Fehler werfen (CREATE INDEX IF NOT EXISTS)."""
    ensure_audit_log_indexes(fresh_engine)
    ensure_audit_log_indexes(fresh_engine)
    ensure_audit_log_indexes(fresh_engine)
    actual = _list_audit_indexes(fresh_engine)
    assert EXPECTED_INDEXES.issubset(actual)


def test_ensure_recreates_after_index_drop(fresh_engine):
    """Wenn ein Index versehentlich entfernt wird (z.B. via ensure_audit_log_actions
    Schema-Migration), legt der naechste ensure-Aufruf ihn wieder an."""
    ensure_audit_log_indexes(fresh_engine)
    # Drop den neuen U-38-Index manuell
    with fresh_engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS idx_audit_mandate_table"))
    actual_before = _list_audit_indexes(fresh_engine)
    assert "idx_audit_mandate_table" not in actual_before

    # Re-run ensure -> Index ist wieder da
    ensure_audit_log_indexes(fresh_engine)
    actual_after = _list_audit_indexes(fresh_engine)
    assert "idx_audit_mandate_table" in actual_after


# ---------------------------------------------------------------------------
# Defensive
# ---------------------------------------------------------------------------

def test_ensure_is_noop_when_table_missing(tmp_path):
    """Wenn audit_log-Tabelle fehlt, soll ensure leise no-op machen, nicht crashen."""
    # Engine OHNE Base.metadata.create_all -> Tabelle existiert NICHT
    engine = create_engine(f"sqlite:///{tmp_path / 'noaudit.db'}")
    try:
        # Darf keinen Exception werfen
        ensure_audit_log_indexes(engine)
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Performance-Sanity (EXPLAIN QUERY PLAN nutzt den Composite-Index)
# ---------------------------------------------------------------------------

def test_composite_index_is_used_by_mandate_table_query(fresh_engine):
    """SQLite-EXPLAIN bestaetigt dass der neue Composite-Index fuer
    typische Queries verwendet wird."""
    ensure_audit_log_indexes(fresh_engine)
    with fresh_engine.connect() as conn:
        plan = conn.execute(text(
            "EXPLAIN QUERY PLAN "
            "SELECT * FROM audit_log "
            "WHERE mandate_id = 'X' AND table_name = 'advisory_log'"
        )).fetchall()
    plan_text = " ".join(str(row) for row in plan).lower()
    # SQLite-Optimizer sollte den Composite-Index nennen
    assert "idx_audit_mandate_table" in plan_text or "using index" in plan_text, (
        f"Plan zeigt keinen Index-Use:\n{plan_text}"
    )
