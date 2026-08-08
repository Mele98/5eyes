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
from models.users import User
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


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def test_tenant_id_is_derived_from_user_and_included_in_hash(tmp_path, monkeypatch):
    """Roadmap #21 (2026-08-08): tenant_id wird beim Schreiben aus user_id
    hergeleitet (kein Call-Site muss angepasst werden) und ist Teil der
    Integritaets-Pruefsumme -- ein manipulierter tenant_id-Wert muss einen
    anderen Hash ergeben."""
    engine, session_local = _fresh_engine(tmp_path, monkeypatch, "audit_tenant")
    ensure_audit_log_actions(engine)
    ensure_audit_log_triggers(engine)
    with session_local() as session:
        session.add(User(
            id="u1", username="u1", password_hash="h", full_name="Admin", role="admin",
            is_active=1, tenant_id="firm-A", created_at=_now_iso(), updated_at=_now_iso(),
        ))
        session.commit()
        log(session, user_id="u1", user_name="Admin", table_name="users", record_id="u1", action="LOGIN")
        session.commit()
        entry = session.query(AuditLog).one()
    assert entry.tenant_id == "firm-A"

    from services.audit import _audit_integrity_payload
    import hashlib
    tampered = _audit_integrity_payload(
        entry_id=entry.id, user_id=entry.user_id, user_name=entry.user_name,
        table_name=entry.table_name, record_id=entry.record_id, action=entry.action,
        field_name=entry.field_name, old_value=entry.old_value, new_value=entry.new_value,
        mandate_id=entry.mandate_id, client_id=entry.client_id, created_at=entry.created_at,
        previous_hash="", ip_address=entry.ip_address, tenant_id="firm-B",
    )
    assert entry.integrity_hash != hashlib.sha256(tampered.encode("utf-8")).hexdigest()


def test_tenant_id_stays_null_when_user_lookup_misses(tmp_path, monkeypatch):
    """Client-Portal-Logins u.ae. uebergeben eine user_id, die KEINE Zeile in
    users hat -- muss weiterhin klaglos funktionieren (tenant_id bleibt NULL,
    keine Regression gegenueber dem bisherigen Verhalten)."""
    engine, session_local = _fresh_engine(tmp_path, monkeypatch, "audit_tenant_miss")
    ensure_audit_log_actions(engine)
    ensure_audit_log_triggers(engine)
    with session_local() as session:
        log(session, user_id="no-such-user", user_name="Client", table_name="risk_assessments",
            record_id="ra1", action="UPDATE")
        session.commit()
        entry = session.query(AuditLog).one()
    assert entry.tenant_id is None


def test_tenant_id_survives_rename_rebuild_migration(tmp_path, monkeypatch):
    """Reproduziert dieselbe Bugklasse wie der Trigger-Verlust oben: eine
    per ensure_runtime_columns nachgezogene tenant_id-Spalte darf die
    RENAME+Neuaufbau-Migration in ensure_audit_log_actions() nicht
    unbemerkt wieder verwerfen."""
    engine, session_local = _fresh_engine(tmp_path, monkeypatch, "audit_tenant_rebuild")
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(audit_log)"))}
        assert "tenant_id" in existing, "ensure_runtime_columns haette tenant_id schon ergaenzt haben muessen"
        conn.execute(text(
            "INSERT INTO audit_log (id, user_name, table_name, record_id, action, created_at, tenant_id) "
            "VALUES ('pre-existing', 'Admin', 'users', 'u1', 'LOGIN', '2026-01-01T00:00:00Z', 'firm-A')"
        ))
    ensure_audit_log_actions(engine)  # loest die RENAME+Neuaufbau-Migration aus
    ensure_audit_log_triggers(engine)
    with session_local() as session:
        entry = session.query(AuditLog).filter(AuditLog.id == "pre-existing").one()
    assert entry.tenant_id == "firm-A", "tenant_id wurde von der RENAME-Migration verworfen"


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
