"""N-869-4 (Pruefrunde #869): Verkettung ohne Lese-Abfrage auf audit_log.

log() las den Vorgaenger-Hash per ``SELECT ... FROM audit_log WHERE sequence
= N-1``. Unter PostgreSQL steht audit_log unter strikter RLS: bei einem
Tenant-Wechsel war der Vorgaenger unsichtbar, previous_hash wurde '' und die
Kette brach. Jetzt fuehrt die Zaehlerzeile (system_only, ohne RLS) den Hash
des letzten Eintrags (``last_hash``), atomar mit ``value`` fortgeschrieben.

SQLite-Teil (dieser Test): log() setzt KEINE Abfrage auf audit_log ab,
last_hash folgt der Kette (auch mehrere Eintraege je Transaktion, Savepoint-
Rollback), der Bestand ohne last_hash wird nachgetragen bzw. faellt einmalig
auf das Lesen zurueck, und der Verifier prueft last_hash gegen das
Kettenende. Der PG-Teil mit Policies und zwei Tenants steht in
tests/test_postgres_audit_chain_rls_live.py.
"""
from __future__ import annotations

import re
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database as db_module  # noqa: E402
from database import Base, bootstrap_sqlite_schema, ensure_audit_log_actions, ensure_runtime_columns  # noqa: E402
from services.audit import (  # noqa: E402
    _verify_audit_chain_detail,
    log,
    run_startup_audit_chain_check,
    verify_audit_chain,
)

_READS_AUDIT_LOG = re.compile(r"\bFROM\s+audit_log\b(?!_)", re.IGNORECASE)


@pytest.fixture()
def session_local(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'lasthash.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    factory.engine = engine
    yield factory
    engine.dispose()


def _log(session, record_id: str, tenant: str) -> None:
    log(session, user_id="u1", user_name="A", table_name="clients", record_id=record_id,
        action="UPDATE", tenant_id=tenant)


def _counter(session_local) -> tuple[int, str | None]:
    with session_local.engine.connect() as conn:
        row = conn.execute(text(
            "SELECT value, last_hash FROM audit_log_sequence_counter WHERE id = 'singleton'"
        )).one()
    return int(row[0]), row[1]


def _hash_of(session_local, sequence: int) -> str:
    with session_local.engine.connect() as conn:
        return conn.execute(
            text("SELECT integrity_hash FROM audit_log WHERE sequence = :s"), {"s": sequence}
        ).scalar_one()


def test_log_never_reads_audit_log(session_local):
    """Kernaussage von N-869-4: die Verkettung braucht keine (unter RLS
    gefilterte) Lese-Abfrage auf audit_log -- weder ueber Transaktions-
    grenzen noch innerhalb einer Transaktion noch bei Tenant-Wechsel."""
    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    with session_local() as s:
        _log(s, "genesis", "tenant-a")
        s.commit()
    event.listen(session_local.engine, "before_cursor_execute", _capture)
    try:
        with session_local() as s:
            _log(s, "b1", "tenant-b")
            s.commit()
        with session_local() as s:
            _log(s, "a1", "tenant-a")
            _log(s, "b2", "tenant-b")
            _log(s, "a2", "tenant-a")
            s.commit()
    finally:
        event.remove(session_local.engine, "before_cursor_execute", _capture)
    reads = [st for st in statements if _READS_AUDIT_LOG.search(st)]
    assert not reads, reads
    with session_local() as s:
        assert verify_audit_chain(s) == {"ok": True, "checked": 5, "errors": []}
    assert _counter(session_local) == (5, _hash_of(session_local, 5))


def test_savepoint_rollback_restores_last_hash(session_local):
    with session_local() as s:
        _log(s, "kept-1", "tenant-a")
        sp = s.begin_nested()
        _log(s, "lost-1", "tenant-b")
        sp.rollback()
        _log(s, "kept-2", "tenant-b")
        s.commit()
    with session_local() as s:
        assert verify_audit_chain(s)["ok"]
    assert _counter(session_local) == (2, _hash_of(session_local, 2))


def test_existing_counter_without_last_hash_falls_back_once(session_local):
    """Bestand vor N-869-4: last_hash NULL. Der naechste Eintrag liest seinen
    Vorgaenger einmalig wie bisher, danach fuehrt log() last_hash selbst."""
    with session_local() as s:
        _log(s, "old-1", "tenant-a")
        _log(s, "old-2", "tenant-a")
        s.commit()
    with session_local.engine.begin() as conn:
        conn.execute(text("UPDATE audit_log_sequence_counter SET last_hash = NULL"))
    with session_local() as s:
        _log(s, "new-1", "tenant-b")
        s.commit()
        assert verify_audit_chain(s)["ok"]
    assert _counter(session_local) == (3, _hash_of(session_local, 3))


def test_runtime_columns_add_and_backfill_last_hash(tmp_path, monkeypatch):
    """SQLite-Upgrade: Zaehlertabelle ohne last_hash (Stand vor N-869-4) mit
    verketteten Eintraegen -> ensure_runtime_columns legt die Spalte an und
    traegt den Hash der Zeile mit sequence = value nach."""
    db_path = tmp_path / "upgrade.db"
    bootstrap_sqlite_schema(db_path=str(db_path), schema_path=str(BACKEND_ROOT / "ares_schema.sql"))
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db_module, "engine", engine)
    ensure_runtime_columns(engine)
    ensure_audit_log_actions(engine)  # Rohschema -> integrity_hash usw. (Boot-Reihenfolge)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    with factory() as s:
        _log(s, "x1", "tenant-a")
        _log(s, "x2", "tenant-b")
        s.commit()
    with engine.begin() as conn:
        expected = conn.execute(text("SELECT integrity_hash FROM audit_log WHERE sequence = 2")).scalar_one()
        # Stand vor N-869-4 nachstellen: Zaehlertabelle ohne last_hash.
        conn.execute(text("ALTER TABLE audit_log_sequence_counter DROP COLUMN last_hash"))

    ensure_runtime_columns(engine)

    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT value, last_hash FROM audit_log_sequence_counter WHERE id = 'singleton'"
        )).one() == (2, expected)
    engine.dispose()


def test_verifier_detects_replaced_chain_end(session_local):
    with session_local() as s:
        _log(s, "a", "tenant-a")
        _log(s, "b", "tenant-b")
        s.commit()
    with session_local.engine.begin() as conn:
        conn.execute(text("UPDATE audit_log_sequence_counter SET last_hash = :h"), {"h": "f" * 64})
    with session_local() as s:
        result = _verify_audit_chain_detail(s)
    assert not result["ok"]
    assert result["breaks"] == [2]
    assert any("Kettenende passt nicht" in e for e in result["errors"])


def test_startup_check_runs_inside_read_scope(session_local):
    """Der Lese-Kontext (unter PG: Operator-Bypass) umschliesst die ganze
    Pruefung, auch die Zeilenzaehlung."""
    calls: list[str] = []

    @contextmanager
    def _scope(db):
        calls.append("enter")
        db.info["scope_active"] = True
        try:
            yield
        finally:
            db.info["scope_active"] = False
            calls.append("exit")

    with session_local() as s:
        _log(s, "a", "tenant-a")
        s.commit()
    report = run_startup_audit_chain_check(session_local, read_scope=_scope)
    assert report is not None and report["ok"]
    # Zaehlung, Bestandssiegel und Bericht laufen je in eigener Session, jede
    # im Lese-Kontext.
    assert calls == ["enter", "exit"] * 3
