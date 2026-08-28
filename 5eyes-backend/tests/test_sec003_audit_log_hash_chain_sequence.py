"""SEC-003 (Codex-Audit 2026-08-26, docs/audits/2026-08-26-data-lifecycle-
crypto-browser-followup-audit.md): services/audit.py::log() determined the
"previous" entry via `ORDER BY created_at DESC, id DESC` with no lock or
sequence. Two near-simultaneous calls could both read the same latest row
and compute a hash chained from it -- a fork instead of a linear chain.

Fix: an atomically-claimed `sequence` + persisted `previous_hash` column
(via a singleton counter row, `UPDATE ... SET value = value + 1`). This
file proves the fix with: sequential chaining, a REAL two-thread
concurrency race against the same SQLite file (not a mock), the verifier,
and that legacy (pre-migration) rows are left alone and don't crash the
verifier.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database as db_module
from database import (
    Base,
    bootstrap_sqlite_schema,
    ensure_audit_log_actions,
    ensure_audit_log_triggers,
    ensure_runtime_columns,
)
from models import allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth  # noqa: F401
from models.review import AuditLog, AuditLogSequenceCounter
from sqlalchemy.orm import configure_mappers
from services.audit import log, verify_audit_chain

configure_mappers()

SCHEMA_PATH = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"


def _fresh_engine(tmp_path, monkeypatch, name):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_path = tmp_path / f"{name}.db"
    bootstrap_sqlite_schema(db_path=str(db_path), schema_path=str(SCHEMA_PATH))
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @__import__("sqlalchemy").event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA busy_timeout = 5000")
        cur.execute("PRAGMA journal_mode = WAL")
        cur.close()

    monkeypatch.setattr(db_module, "engine", engine)
    ensure_runtime_columns()
    ensure_audit_log_actions(engine)
    ensure_audit_log_triggers(engine)
    # SEC-003: audit_log_sequence_counter ist eine neue ORM-only-Tabelle,
    # in der echten init_db() ueber Base.metadata.create_all() angelegt
    # (checkfirst=True, laeuft bei jedem Boot -- auch fuer Bestands-DBs).
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=True, expire_on_commit=False, bind=engine)
    return engine, session_local


def test_sequential_calls_chain_correctly(tmp_path, monkeypatch):
    engine, session_local = _fresh_engine(tmp_path, monkeypatch, "seq_chain")
    with session_local() as session:
        log(session, user_id="u1", user_name="A", table_name="t", record_id="1", action="CREATE")
        session.commit()
        log(session, user_id="u1", user_name="A", table_name="t", record_id="2", action="UPDATE")
        session.commit()
        log(session, user_id="u1", user_name="A", table_name="t", record_id="3", action="DELETE")
        session.commit()

        rows = session.query(AuditLog).order_by(AuditLog.sequence.asc()).all()
        assert [r.sequence for r in rows] == [1, 2, 3]
        assert rows[0].previous_hash == ""
        assert rows[1].previous_hash == rows[0].integrity_hash
        assert rows[2].previous_hash == rows[1].integrity_hash

        result = verify_audit_chain(session)
        assert result == {"ok": True, "checked": 3, "errors": []}


def test_multiple_log_calls_in_the_same_session_do_not_collide(tmp_path, monkeypatch):
    """Regressionsschutz fuer den REC-005-Stale-Fixture-Fehler: mehrere
    log()-Aufrufe INNERHALB derselben Session/Transaktion (typisch, wenn ein
    Endpoint mehrere Aktionen pro Request loggt) muessen unterschiedliche,
    aufeinanderfolgende Sequenznummern bekommen -- nicht dieselbe."""
    engine, session_local = _fresh_engine(tmp_path, monkeypatch, "seq_same_session")
    with session_local() as session:
        log(session, user_id="u1", user_name="A", table_name="t", record_id="1", action="CREATE")
        log(session, user_id="u1", user_name="A", table_name="t", record_id="2", action="UPDATE")
        session.commit()

        rows = session.query(AuditLog).order_by(AuditLog.sequence.asc()).all()
        assert [r.sequence for r in rows] == [1, 2]
        assert rows[1].previous_hash == rows[0].integrity_hash


def test_counter_row_self_heals_when_missing(tmp_path, monkeypatch):
    """ensure_runtime_columns() seedet die Zaehlerzeile normalerweise idempotent
    mit -- fuer den seltenen Fall, dass sie trotzdem fehlt (z.B. manuell
    geloescht, oder ein Aufrufkontext ohne diesen Boot-Schritt), muss log()
    sie defensiv selbst anlegen statt zu crashen. Zeile hier absichtlich
    geloescht, um genau diesen Pfad zu erzwingen."""
    engine, session_local = _fresh_engine(tmp_path, monkeypatch, "seq_self_heal")
    with session_local() as session:
        session.query(AuditLogSequenceCounter).filter(
            AuditLogSequenceCounter.id == "singleton"
        ).delete()
        session.commit()
        assert session.query(AuditLogSequenceCounter).count() == 0

        log(session, user_id="u1", user_name="A", table_name="t", record_id="1", action="CREATE")
        session.commit()
        entry = session.query(AuditLog).one()
        assert entry.sequence == 1
        assert entry.previous_hash == ""


def test_real_two_thread_concurrency_produces_exactly_one_linear_chain(tmp_path, monkeypatch):
    """SEC-003 Kernbeweis: zwei ECHTE Threads mit UNABHAENGIGEN Engines/
    Sessions gegen dieselbe SQLite-Datei, synchronisiert per Barrier
    unmittelbar vor dem log()-Aufruf, um die Race-Window maximal auszunutzen.
    Vor dem Fix (ORDER BY created_at DESC ohne Lock) konnte das zwei Zeilen
    mit identischem previous_hash erzeugen (Gabelung). Nach dem Fix muss
    exakt eine lineare Kette [1, 2] entstehen -- unabhaengig davon, welcher
    Thread zuerst dran kommt."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    db_path = tmp_path / "seq_race.db"
    bootstrap_sqlite_schema(db_path=str(db_path), schema_path=str(SCHEMA_PATH))

    setup_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db_module, "engine", setup_engine)
    ensure_runtime_columns()
    ensure_audit_log_actions(setup_engine)
    ensure_audit_log_triggers(setup_engine)
    Base.metadata.create_all(bind=setup_engine)
    setup_engine.dispose()

    def _make_session_local():
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @event.listens_for(engine, "connect")
        def _pragma(dbapi_connection, _record):
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA busy_timeout = 5000")
            cur.execute("PRAGMA journal_mode = WAL")
            cur.close()

        return sessionmaker(autocommit=False, autoflush=True, expire_on_commit=False, bind=engine)

    session_local_a = _make_session_local()
    session_local_b = _make_session_local()

    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def _worker(session_local, record_id):
        try:
            with session_local() as session:
                barrier.wait(timeout=5)
                log(session, user_id="u1", user_name="A", table_name="t", record_id=record_id, action="CREATE")
                session.commit()
        except Exception as exc:  # noqa: BLE001 -- capture for the main thread to assert on
            errors.append(exc)

    t1 = threading.Thread(target=_worker, args=(session_local_a, "race-1"))
    t2 = threading.Thread(target=_worker, args=(session_local_b, "race-2"))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert not errors, f"Worker-Threads warfen unerwartete Fehler: {errors}"

    verify_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    verify_session_local = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=verify_engine)
    with verify_session_local() as session:
        rows = session.query(AuditLog).order_by(AuditLog.sequence.asc()).all()
        assert [r.sequence for r in rows] == [1, 2], (
            f"Erwartet genau eine lineare Sequenz [1, 2], bekommen: {[r.sequence for r in rows]}"
        )
        assert rows[1].previous_hash == rows[0].integrity_hash, (
            "Gabelung erkannt: der zweite Eintrag verkettet nicht auf den ersten "
            "(previous_hash stimmt nicht mit dem Hash des Vorgaengers ueberein)."
        )
        result = verify_audit_chain(session)
        assert result["ok"] is True, f"Verifier fand Fehler: {result['errors']}"


def test_verify_audit_chain_ignores_legacy_rows_without_sequence(tmp_path, monkeypatch):
    """Altdaten (sequence IS NULL, vor dieser Migration) duerfen den
    Verifier nicht crashen oder als Kettenbruch zaehlen -- sie beanspruchen
    bewusst keine rueckwirkende lineare Garantie."""
    engine, session_local = _fresh_engine(tmp_path, monkeypatch, "seq_legacy")
    with session_local() as session:
        legacy = AuditLog(
            id="legacy-1", user_id="u1", user_name="A", table_name="t",
            record_id="legacy", action="CREATE", integrity_hash="deadbeef",
            created_at="2026-01-01T00:00:00.000Z",
            # sequence/previous_hash bleiben NULL -- simuliert eine Zeile
            # von vor der Migration.
        )
        session.add(legacy)
        session.commit()

        log(session, user_id="u1", user_name="A", table_name="t", record_id="new", action="CREATE")
        session.commit()

        result = verify_audit_chain(session)
        assert result["checked"] == 1  # nur die NEUE Zeile wird geprueft
        assert result["ok"] is True
