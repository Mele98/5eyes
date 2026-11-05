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

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import ensure_audit_log_actions  # noqa: E402
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
        'BACKFILL','UPSERT'
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
    assert _trigger_names(engine) == {"trg_audit_log_no_update", "trg_audit_log_no_delete"}
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
