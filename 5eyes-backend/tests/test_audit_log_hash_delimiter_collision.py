"""Kontrollrunde 2026-09-24: services.audit._audit_integrity_payload joined
all hashed fields with a bare '|' -- an ordinary, plausible character in
free-text fields (old_value/new_value/user_name, e.g. DSG-Art.-32 erasure
reasons in routers/clients.py). Two DIFFERENT sets of field values could
produce the IDENTICAL payload string (and therefore the identical
integrity_hash) whenever a '|' sits at a field boundary -- defeating the
whole purpose of the hash chain for exactly the case it exists to catch
("a value swapped, not just deleted").

Fix: the delimiter is now '\\x1f' (matches the already-correct scheme in
services/advisory_log_integrity.py). Since audit_log's immutability trigger
(trg_audit_log_no_update, database.py::ensure_audit_log_triggers) makes it
impossible to retroactively rehash existing rows -- unlike the REC-007
precedent for advisory_log, which has no such trigger -- verify_audit_chain()
must additionally accept the OLD '|'-scheme for rows written before this fix,
so historical rows aren't flagged as "tampered" by the fix itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

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
from models.review import AuditLog
from sqlalchemy.orm import configure_mappers
from services.audit import (
    _audit_integrity_payload,
    _audit_integrity_payload_legacy_pipe_delimiter,
    log,
    verify_audit_chain,
)

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
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=True, expire_on_commit=False, bind=engine)
    return engine, session_local


_COMMON_FIELDS = dict(
    entry_id="e1", user_id="u1", user_name="Advisor Name", table_name="mandates",
    record_id="r1", action="UPDATE", field_name="risk_note", mandate_id="m1",
    client_id="c1", created_at="2026-09-24T10:00:00.000Z", previous_hash="abc123",
    ip_address="1.2.3.4", tenant_id="t1",
)


def test_new_delimiter_no_longer_collides_on_pipe_at_field_boundary():
    """Reproduktion des Funds: die beiden Werte-Saetze durften bisher
    identisch hashen, tun es mit dem neuen Delimiter nicht mehr."""
    p1 = _audit_integrity_payload(old_value="A|B", new_value="C", **_COMMON_FIELDS)
    p2 = _audit_integrity_payload(old_value="A", new_value="B|C", **_COMMON_FIELDS)
    assert p1 != p2


def test_legacy_pipe_payload_still_collides_documenting_the_original_bug():
    """Die eingefrorene Alt-Funktion reproduziert den urspruenglichen Bug
    bewusst weiter -- sie wird nur zur Verifikation vorhandener Alt-Zeilen
    verwendet, nie fuer neue Schreibvorgaenge."""
    p1 = _audit_integrity_payload_legacy_pipe_delimiter(old_value="A|B", new_value="C", **_COMMON_FIELDS)
    p2 = _audit_integrity_payload_legacy_pipe_delimiter(old_value="A", new_value="B|C", **_COMMON_FIELDS)
    assert p1 == p2


def test_log_writes_pipe_containing_values_without_collision(tmp_path, monkeypatch):
    """End-to-end: zwei Eintraege mit unterschiedlichen, aber unter dem
    alten Schema kollidierenden Werten erhalten jetzt unterschiedliche
    integrity_hash-Werte, und verify_audit_chain erkennt keinen Fehler."""
    engine, session_local = _fresh_engine(tmp_path, monkeypatch, "delim_collision")
    with session_local() as session:
        log(session, user_id="u1", user_name="A", table_name="mandates", record_id="1",
            action="UPDATE", field_name="note", old_value="A|B", new_value="C")
        session.commit()
        log(session, user_id="u1", user_name="A", table_name="mandates", record_id="2",
            action="UPDATE", field_name="note", old_value="A", new_value="B|C")
        session.commit()

        rows = session.query(AuditLog).order_by(AuditLog.sequence.asc()).all()
        assert rows[0].integrity_hash != rows[1].integrity_hash

        result = verify_audit_chain(session)
        assert result == {"ok": True, "checked": 2, "errors": []}


def test_verify_audit_chain_accepts_legacy_pipe_scheme_row(tmp_path, monkeypatch):
    """Kern-Regressionsschutz: eine Zeile, die (wie jede vor diesem Fix
    geschriebene reale Zeile) unter dem ALTEN '|'-Schema gehasht wurde, darf
    vom Verifier nicht als "manipuliert" gemeldet werden -- audit_log kann
    wegen trg_audit_log_no_update nicht rueckwirkend umgehasht werden."""
    engine, session_local = _fresh_engine(tmp_path, monkeypatch, "delim_legacy_row")
    with session_local() as session:
        legacy_payload = _audit_integrity_payload_legacy_pipe_delimiter(
            entry_id="legacy-seq-1", user_id="u1", user_name="A", table_name="mandates",
            record_id="1", action="CREATE", field_name=None, old_value=None, new_value=None,
            mandate_id=None, client_id=None, created_at="2026-08-27T00:00:00.000Z",
            previous_hash="", ip_address=None, tenant_id=None,
        )
        import hashlib
        legacy_hash = hashlib.sha256(legacy_payload.encode("utf-8")).hexdigest()
        legacy_row = AuditLog(
            id="legacy-seq-1", user_id="u1", user_name="A", table_name="mandates",
            record_id="1", action="CREATE", integrity_hash=legacy_hash,
            created_at="2026-08-27T00:00:00.000Z", sequence=1, previous_hash="",
        )
        session.add(legacy_row)
        session.commit()

        result = verify_audit_chain(session)
        assert result == {"ok": True, "checked": 1, "errors": []}


def test_verify_audit_chain_still_detects_genuine_tampering_under_new_scheme(tmp_path, monkeypatch):
    """Der Verifier muss weiterhin echte Manipulation erkennen -- der
    zusaetzliche Legacy-Fallback darf keine False Negatives fuer neue
    Zeilen einfuehren. trg_audit_log_no_update blockiert ein echtes UPDATE
    auch fuer diesen Test (das ist der Punkt der Immutability) -- simuliert
    daher eine bereits manipuliert vorgefundene Zeile per direktem INSERT
    (Hash passt nicht zu den gespeicherten Feldern), statt eine echte Zeile
    nachtraeglich zu veraendern."""
    engine, session_local = _fresh_engine(tmp_path, monkeypatch, "delim_tamper")
    with session_local() as session:
        tampered_row = AuditLog(
            id="tampered-1", user_id="u1", user_name="A", table_name="mandates",
            record_id="1", action="UPDATE", field_name="note",
            old_value="original", new_value="tampered-after-the-fact",
            integrity_hash="0" * 64,  # passt zu keinem Schema
            created_at="2026-09-24T00:00:00.000Z", sequence=1, previous_hash="",
        )
        session.add(tampered_row)
        session.commit()

        result = verify_audit_chain(session)
        assert result["ok"] is False
        assert result["errors"]
