"""H-865-1 (Pruefrunde #865): der SQLite-Neuaufbau von audit_log erhaelt die Kette.

``database.py::ensure_audit_log_actions`` baut ``audit_log`` per RENAME +
CREATE + INSERT...SELECT neu auf, sobald ein action-Marker im CHECK fehlt.
Der Kopierschritt setzte bisher ``NULL AS integrity_hash``: lief der Neuaufbau
auf einer Installation mit Bestandsdaten erneut (z.B. fuer einen kuenftigen
action-Wert nach dem Muster ``has_erasure_action``), verloren ALLE Zeilen
ihren Hash -- ``verify_audit_chain()`` meldete jede Zeile als manipuliert,
und die Unveraenderlichkeits-Trigger verhindern jede Reparatur.

Zusaetzlich (Befund CEO/CFO/CIO-Audit 2026-08-07): SQLite verwirft beim
``DROP TABLE audit_log__old`` die Trigger. Der Neuaufbau muss sie selbst
wieder anlegen, nicht erst ein spaeterer, separater Aufruf.

Der Test baut eine Tabelle im Vor-Zustand (CHECK ohne 'CLIENT_ERASE', also
genau der Fall, der den Neuaufbau ausloest), schreibt verkettete Eintraege
ueber ``services.audit.log()`` (auch mehrere pro Transaktion, mit IP und
Tenant) plus eine gehashte Altzeile ohne sequence, erzwingt den Neuaufbau und
prueft: Kette ok, Hashes/Sequenzen/Vorgaenger byte-gleich, Trigger aktiv.
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database as db_module  # noqa: E402
from database import AuditLogRebuildInterrupted, ensure_audit_log_actions  # noqa: E402
from models import allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth  # noqa: E402,F401
from models.review import AuditLogSequenceCounter  # noqa: E402
from models.users import User  # noqa: E402
from services.audit import log, verify_audit_chain  # noqa: E402

configure_mappers()

# Vor-Zustand: identisch zum Neuaufbau-DDL, aber OHNE 'CLIENT_ERASE' im
# action-CHECK -> has_erasure_action ist False -> Neuaufbau wird ausgeloest.
_PRE_REBUILD_DDL = """
CREATE TABLE audit_log (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    user_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    record_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN (
        'CREATE','UPDATE','DELETE','LOGIN','EXPORT','PASSWORD_RESET',
        'BACKFILL','UPSERT','LEGACY_X'
    )),
    field_name TEXT,
    old_value TEXT,
    new_value TEXT,
    mandate_id TEXT,
    client_id TEXT,
    integrity_hash TEXT,
    ip_address TEXT,
    created_at TEXT NOT NULL,
    tenant_id TEXT,
    sequence INTEGER,
    previous_hash TEXT
)
"""

_TRIGGERS = (
    "CREATE TRIGGER trg_audit_log_no_update BEFORE UPDATE ON audit_log FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is immutable'); END",
    "CREATE TRIGGER trg_audit_log_no_delete BEFORE DELETE ON audit_log FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is immutable'); END",
)

# Nach dem Neuaufbau: beide Unveraenderlichkeits-Trigger plus der
# Ketten-Pflicht-Trigger fuer neue Zeilen (N-869-3).
_ALL_TRIGGERS = {"trg_audit_log_no_update", "trg_audit_log_no_delete", "trg_audit_log_require_chain"}

_SNAPSHOT_SQL = (
    "SELECT id, integrity_hash, sequence, previous_hash, created_at, ip_address, "
    "tenant_id, old_value, new_value FROM audit_log ORDER BY id"
)


@pytest.fixture()
def pre_rebuild_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_rebuild.db'}", connect_args={"check_same_thread": False}
    )
    with engine.begin() as conn:
        conn.execute(text(_PRE_REBUILD_DDL))
        for stmt in _TRIGGERS:
            conn.execute(text(stmt))
    User.__table__.create(engine)
    AuditLogSequenceCounter.__table__.create(engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

    with engine.begin() as conn:
        # Gehashte Altzeile ohne sequence (vor SEC-003, '|'-Schema) -- deren
        # Hash muss den Neuaufbau ebenso ueberstehen.
        conn.execute(text(
            "INSERT INTO audit_log (id, user_id, user_name, table_name, record_id, action, "
            "integrity_hash, created_at) VALUES ('legacy-1', 'u0', 'Alt', 'clients', 'c0', "
            "'CREATE', :h, '2026-08-01T08:00:00.000Z')"
        ), {"h": "ab" * 32})

    with session_local() as s:
        log(s, user_id="u1", user_name="Admin", table_name="users", record_id="u1",
            action="LOGIN", ip_address="203.0.113.7", tenant_id="tenant-a")
        s.commit()
    with session_local() as s:
        # Mehrere Eintraege in EINER Transaktion (N-862-1-Pfad).
        for i in range(3):
            log(s, user_id="u2", user_name="Berater | Pipe", table_name="goals",
                record_id=f"g{i}", action="UPDATE", field_name="rank",
                old_value=str(i), new_value=str(i + 1), tenant_id="tenant-b")
        s.commit()
    with session_local() as s:
        log(s, user_id="u1", user_name="Admin", table_name="asset_class_annual_returns",
            record_id="2020-2021", action="BACKFILL", new_value="rows_written=7 errors=0")
        s.commit()
    yield engine, session_local
    engine.dispose()


def _ddl(engine) -> str:
    with engine.connect() as conn:
        return str(conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='audit_log'")
        ).scalar())


def _trigger_names(engine) -> set[str]:
    with engine.connect() as conn:
        return {
            row[0] for row in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_log'"
            ))
        }


def _snapshot(engine) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(_SNAPSHOT_SQL))]


def test_rebuild_preserves_hashes_sequence_and_previous_hash(pre_rebuild_db):
    engine, session_local = pre_rebuild_db
    with session_local() as s:
        before_verdict = verify_audit_chain(s)
    assert before_verdict["ok"] and before_verdict["checked"] == 5, before_verdict
    before = _snapshot(engine)
    assert "CLIENT_ERASE" not in _ddl(engine)

    ensure_audit_log_actions(engine)

    # Der Neuaufbau ist tatsaechlich gelaufen (sonst bewiese der Test nichts).
    assert "CLIENT_ERASE" in _ddl(engine)
    after = _snapshot(engine)
    assert after == before, "Neuaufbau hat Hashes/Sequenzen/Vorgaenger veraendert"
    assert all(row[1] for row in after), "integrity_hash ging beim Neuaufbau verloren"
    with session_local() as s:
        after_verdict = verify_audit_chain(s)
    assert after_verdict["ok"], after_verdict["errors"]
    assert after_verdict["checked"] == 5


def test_rebuild_recreates_immutability_triggers_itself(pre_rebuild_db):
    """Ohne separaten ensure_audit_log_triggers()-Aufruf: direkt nach dem
    Neuaufbau muessen UPDATE und DELETE abgewiesen werden."""
    engine, _ = pre_rebuild_db
    ensure_audit_log_actions(engine)
    assert "CLIENT_ERASE" in _ddl(engine)
    assert _trigger_names(engine) == _ALL_TRIGGERS
    with pytest.raises(DatabaseError, match="audit_log is immutable"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE audit_log SET integrity_hash = 'x' WHERE sequence = 1"))
    with pytest.raises(DatabaseError, match="audit_log is immutable"):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM audit_log WHERE sequence = 2"))
    assert len(_snapshot(engine)) == 6


def test_chain_continues_after_rebuild(pre_rebuild_db):
    """Nach dem Neuaufbau schliesst der naechste log()-Eintrag an die
    erhaltene Kette an (Zaehler und Vorgaenger-Hash passen)."""
    engine, session_local = pre_rebuild_db
    ensure_audit_log_actions(engine)
    with session_local() as s:
        log(s, user_id="u1", user_name="Admin", table_name="clients", record_id="c9",
            action="CLIENT_ERASE")
        s.commit()
        verdict = verify_audit_chain(s)
    assert verdict["ok"], verdict["errors"]
    assert verdict["checked"] == 6


def test_rebuild_is_idempotent(pre_rebuild_db):
    engine, _ = pre_rebuild_db
    ensure_audit_log_actions(engine)
    first = _snapshot(engine)
    ddl = _ddl(engine)
    ensure_audit_log_actions(engine)
    assert _ddl(engine) == ddl
    assert _snapshot(engine) == first


# ---------------------------------------------------------------------------
# N-869-1 (Pruefrunde #869): Atomaritaet und Wiederaufnahme
# ---------------------------------------------------------------------------

def _table_names(engine) -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}


def _count(engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar())


def _autocommit(engine, *statements: str) -> None:
    """Fuehrt DDL im Autocommit aus -- so, wie der alte Neuaufbau unter
    pysqlite tatsaechlich lief (RENAME/CREATE sofort committet)."""
    raw = engine.raw_connection()
    try:
        dbapi = raw.driver_connection
        previous = dbapi.isolation_level
        dbapi.isolation_level = None
        try:
            for statement in statements:
                dbapi.execute(statement)
        finally:
            dbapi.isolation_level = previous
    finally:
        raw.close()


def test_copy_failure_rolls_back_everything(pre_rebuild_db):
    """Eine Altzeile verletzt den neuen action-CHECK -> das Kopieren scheitert.
    Danach muss die DB exakt im Vor-Zustand sein: altes DDL, alle Zeilen,
    beide Trigger, KEIN audit_log__old. Vorher (Autocommit-DDL) blieben
    __old mit der Historie und ein leeres audit_log ohne Trigger committet."""
    engine, session_local = pre_rebuild_db
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO audit_log (id, user_name, table_name, record_id, action, created_at) "
            "VALUES ('legacy-x', 'Alt', 't', 'r', 'LEGACY_X', '2026-07-01T00:00:00.000Z')"
        ))
    before = _snapshot(engine)
    ddl_before = _ddl(engine)
    triggers_before = _trigger_names(engine)

    with pytest.raises(sqlite3.IntegrityError):
        ensure_audit_log_actions(engine)

    assert "audit_log__old" not in _table_names(engine)
    assert _ddl(engine) == ddl_before
    assert _snapshot(engine) == before
    assert _trigger_names(engine) == triggers_before == {
        "trg_audit_log_no_update", "trg_audit_log_no_delete",
    }
    with session_local() as s:
        assert verify_audit_chain(s)["ok"]


def test_interrupted_rebuild_with_empty_new_table_is_completed(pre_rebuild_db, caplog):
    """Zustand nach einem Abbruch des ALTEN Codes: __old mit Historie, neue
    leere Tabelle ohne Trigger. Der naechste Start setzt den Neuaufbau fort
    (WARNING, nicht still) und stellt alles vollstaendig wieder her."""
    engine, session_local = pre_rebuild_db
    before = _snapshot(engine)
    _autocommit(
        engine,
        "ALTER TABLE audit_log RENAME TO audit_log__old",
        db_module._AUDIT_LOG_REBUILT_DDL,
    )
    assert _count(engine, "audit_log") == 0
    assert _trigger_names(engine) == set()

    with caplog.at_level(logging.WARNING, logger="database.audit_log"):
        ensure_audit_log_actions(engine)

    assert any("Unterbrochener audit_log-Neuaufbau" in r.getMessage() for r in caplog.records)
    assert "audit_log__old" not in _table_names(engine)
    assert _snapshot(engine) == before
    assert _trigger_names(engine) == _ALL_TRIGGERS
    with session_local() as s:
        assert verify_audit_chain(s)["ok"]


def test_interrupted_rebuild_with_only_old_table_is_completed(pre_rebuild_db):
    engine, _ = pre_rebuild_db
    before = _snapshot(engine)
    _autocommit(engine, "ALTER TABLE audit_log RENAME TO audit_log__old")
    ensure_audit_log_actions(engine)
    assert "audit_log__old" not in _table_names(engine)
    assert "CLIENT_ERASE" in _ddl(engine)
    assert _snapshot(engine) == before


def test_interrupted_rebuild_with_rows_in_both_tables_fails_closed(pre_rebuild_db, caplog):
    """Zeilen in __old UND in der neuen Tabelle: nicht sicher aufloesbar.
    CRITICAL + Abbruch (Start blockiert), beide Tabellen unveraendert."""
    engine, _ = pre_rebuild_db
    n_total = _count(engine, "audit_log")
    _autocommit(
        engine,
        "ALTER TABLE audit_log RENAME TO audit_log__old",
        db_module._AUDIT_LOG_REBUILT_DDL,
        "INSERT INTO audit_log (id, user_name, table_name, record_id, action, created_at) "
        "VALUES ('after-crash', 'X', 't', 'r', 'LOGIN', '2026-11-01T00:00:00.000Z')",
    )
    with caplog.at_level(logging.WARNING, logger="database.audit_log"):
        with pytest.raises(AuditLogRebuildInterrupted):
            ensure_audit_log_actions(engine)
    assert [r.levelno for r in caplog.records] == [logging.CRITICAL]
    assert _count(engine, "audit_log__old") == n_total
    assert _count(engine, "audit_log") == 1


# ---------------------------------------------------------------------------
# N-869-3 (Pruefrunde #869): DB-Trigger gegen Zeilen ausserhalb der Kette
# ---------------------------------------------------------------------------

def test_rebuild_installs_chain_guard_and_keeps_legacy_rows(pre_rebuild_db):
    """Der Neuaufbau kopiert Altzeilen ohne sequence (vor dem Trigger) und
    legt danach den Ketten-Pflicht-Trigger an: neue Zeilen ohne sequence/
    Hash/Vorgaenger werden abgewiesen, log() funktioniert weiter."""
    engine, session_local = pre_rebuild_db
    ensure_audit_log_actions(engine)
    with engine.connect() as conn:
        legacy = conn.execute(text("SELECT COUNT(*) FROM audit_log WHERE sequence IS NULL")).scalar()
    assert legacy == 1
    for columns, values in (
        ("", ""),
        (", sequence, previous_hash", ", 99, ''"),
        (", integrity_hash, previous_hash", ", 'h', ''"),
        (", sequence, integrity_hash", ", 99, 'h'"),
    ):
        with pytest.raises(DatabaseError, match="outside hash chain"):
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO audit_log (id, user_name, table_name, record_id, action, created_at"
                    + columns + ") VALUES ('x', 'X', 't', 'r', 'LOGIN', '2026-11-05T00:00:00.000Z'"
                    + values + ")"
                ))
    with session_local() as s:
        log(s, user_id="u1", user_name="Admin", table_name="clients", record_id="c1", action="CREATE")
        s.commit()
        assert verify_audit_chain(s)["ok"]
