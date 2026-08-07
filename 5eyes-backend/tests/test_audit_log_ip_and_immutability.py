"""2026-08-07 (CEO/CFO/CIO-Audit): zwei Funde rund um audit_log.

1. IP-Adresse fehlte im auditierbaren, hash-verketteten Audit-Trail (nur im
   App-Log, nicht in der DB) -- DSG Art. 32 Zugriffs-Nachvollziehbarkeit war
   nur teilweise erfuellt (Wer+Was+Wann ja, Woher nein).

2. KRITISCHER Fund waehrend der Implementierung: ensure_audit_log_actions()
   migriert audit_log per ALTER TABLE RENAME + Neuaufbau (fuer die
   integrity_hash-Spalte). SQLite haengt Trigger an die UMBENANNTE Tabelle
   und verwirft sie beim abschliessenden DROP TABLE audit_log__old -- die neu
   angelegte audit_log-Tabelle hatte danach GAR KEINEN Schutz mehr vor
   UPDATE/DELETE, obwohl das Rohschema (5eyes_schema_v4.0_FINAL.sql) die
   Tabelle ausdruecklich als unveraenderlich deklariert. Da JEDE Installation
   beim ersten Start durch diese Migration laeuft (die Rohschema-Datei hat
   noch kein integrity_hash), war dieser Schutz nach dem ersten Start IMMER
   weg -- unbemerkt, weil kein Test die Trigger je ausloeste.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database as db_module
from database import (
    bootstrap_sqlite_schema,
    ensure_audit_log_actions,
    ensure_audit_log_triggers,
    ensure_runtime_columns,
)
from models import allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth  # noqa: F401
from models.review import AuditLog
from sqlalchemy.orm import configure_mappers
from services.audit import log

configure_mappers()

SCHEMA_PATH = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"


def _fresh_engine(tmp_path, monkeypatch, name):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_path = tmp_path / f"{name}.db"
    bootstrap_sqlite_schema(db_path=str(db_path), schema_path=str(SCHEMA_PATH))
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db_module, "engine", engine)
    ensure_runtime_columns()
    session_local = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    return engine, session_local


def test_ip_address_is_stored_and_included_in_hash(tmp_path, monkeypatch):
    engine, session_local = _fresh_engine(tmp_path, monkeypatch, "audit_ip")
    ensure_audit_log_actions(engine)
    ensure_audit_log_triggers(engine)
    with session_local() as session:
        log(
            session, user_id="u1", user_name="Admin", table_name="users",
            record_id="u1", action="LOGIN", ip_address="203.0.113.42",
        )
        session.commit()
        entry = session.query(AuditLog).one()
    assert entry.ip_address == "203.0.113.42"

    # Ein manipulierter Eintrag mit anderer IP muss einen anderen Hash ergeben
    # -- die IP ist Teil der Integritaets-Pruefsumme, nicht nur Metadatum.
    from services.audit import _audit_integrity_payload
    import hashlib
    tampered = _audit_integrity_payload(
        entry_id=entry.id, user_id=entry.user_id, user_name=entry.user_name,
        table_name=entry.table_name, record_id=entry.record_id, action=entry.action,
        field_name=entry.field_name, old_value=entry.old_value, new_value=entry.new_value,
        mandate_id=entry.mandate_id, client_id=entry.client_id, created_at=entry.created_at,
        previous_hash="", ip_address="10.0.0.1",
    )
    assert entry.integrity_hash != hashlib.sha256(tampered.encode("utf-8")).hexdigest()


def test_ip_address_defaults_to_null_when_not_provided(tmp_path, monkeypatch):
    engine, session_local = _fresh_engine(tmp_path, monkeypatch, "audit_ip_null")
    ensure_audit_log_actions(engine)
    ensure_audit_log_triggers(engine)
    with session_local() as session:
        log(session, user_id="u1", user_name="Admin", table_name="users", record_id="u1", action="LOGIN")
        session.commit()
        entry = session.query(AuditLog).one()
    assert entry.ip_address is None


def test_fresh_bootstrap_audit_log_is_immutable_after_migration(tmp_path, monkeypatch):
    """KRITISCH: reproduziert exakt den Produktionspfad (bootstrap_sqlite_schema
    -> ensure_runtime_columns -> ensure_audit_log_actions -> ensure_audit_log_triggers,
    wie in database.init_db()) und beweist, dass UPDATE/DELETE auf audit_log
    danach weiterhin (bzw. wieder) blockiert werden."""
    engine, session_local = _fresh_engine(tmp_path, monkeypatch, "audit_immutable")
    ensure_audit_log_actions(engine)
    ensure_audit_log_triggers(engine)

    with session_local() as session:
        log(session, user_id="u1", user_name="Admin", table_name="users", record_id="u1", action="LOGIN")
        session.commit()
        entry_id = session.query(AuditLog).one().id

    with engine.begin() as conn:
        with pytest.raises(IntegrityError, match="immutable"):
            conn.execute(text("UPDATE audit_log SET action='DELETE' WHERE id=:id"), {"id": entry_id})

    with engine.begin() as conn:
        with pytest.raises(IntegrityError, match="immutable"):
            conn.execute(text("DELETE FROM audit_log WHERE id=:id"), {"id": entry_id})


def test_ensure_audit_log_triggers_is_idempotent(tmp_path, monkeypatch):
    """Mehrfacher Aufruf (z.B. bei mehreren App-Neustarts) darf nicht crashen."""
    engine, _ = _fresh_engine(tmp_path, monkeypatch, "audit_idempotent")
    ensure_audit_log_actions(engine)
    ensure_audit_log_triggers(engine)
    ensure_audit_log_triggers(engine)
    ensure_audit_log_triggers(engine)


def test_ensure_audit_log_actions_preserves_existing_ip_address_on_rerun(tmp_path, monkeypatch):
    """Regressionsschutz fuer die dynamische Spalten-Erkennung: ein zweiter
    Migrationslauf (z.B. nach einem Teil-Upgrade) darf bereits gespeicherte
    ip_address-Werte nicht verwerfen."""
    engine, session_local = _fresh_engine(tmp_path, monkeypatch, "audit_rerun")
    ensure_audit_log_actions(engine)
    ensure_audit_log_triggers(engine)
    with session_local() as session:
        log(session, user_id="u1", user_name="Admin", table_name="users",
            record_id="u1", action="LOGIN", ip_address="198.51.100.7")
        session.commit()

    # Migration erneut ausfuehren (simuliert zweiten App-Start) -- Marker-Check
    # sollte fruehzeitig zurueckkehren, aber selbst falls nicht: ip_address bleibt.
    ensure_audit_log_actions(engine)
    ensure_audit_log_triggers(engine)

    with session_local() as session:
        entry = session.query(AuditLog).one()
        assert entry.ip_address == "198.51.100.7"
