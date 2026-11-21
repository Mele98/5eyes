"""H11 (Hygiene-Folgepunkt C-890, N-897-18): SQLite-Upgrade-Pfad fuer 'COMPROMISE'.

Befund: Der Marker ``has_compromise_action`` (``database._audit_log_ddl_is_current``)
loest auf Bestands-DBs den Neuaufbau des ``audit_log``-CHECKs aus. Kein Test
pinnte das: wurde der Marker auf ``True`` gesetzt, blieb jede Bestands-DB beim
alten CHECK -- und ein Widerruf wegen Kompromittierung (action 'COMPROMISE')
scheiterte dort -- ohne dass ein Test rot wurde (die Drift-Tests pruefen nur
frische ``init_db``-Installationen).

Der Test legt eine DB mit dem alten CHECK an (aktuelles Neuaufbau-DDL ohne
'COMPROMISE', alle uebrigen Marker erfuellt), schreibt verkettete Eintraege,
laesst den Upgrade-Pfad laufen und verlangt: CHECK enthaelt 'COMPROMISE',
Zeilenzahl und Hashes unveraendert, Kette ok, ein 'COMPROMISE'-Eintrag wird
angenommen und schliesst an die Kette an.

Gegenprobe (Mutation): ``has_compromise_action = True`` -> rot.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database as db_module  # noqa: E402
from database import _audit_log_ddl_is_current, ensure_audit_log_actions  # noqa: E402
from models import allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth  # noqa: E402,F401
from models.review import AuditLogSequenceCounter  # noqa: E402
from models.users import User  # noqa: E402
from services.audit import log, verify_audit_chain  # noqa: E402

configure_mappers()

_OLD_DDL = db_module._AUDIT_LOG_REBUILT_DDL.replace("'COMPROMISE',", "")


def test_old_ddl_differs_only_by_the_compromise_marker():
    assert "'COMPROMISE'" not in _OLD_DDL.upper() and "'COMPROMISE'" in db_module._AUDIT_LOG_REBUILT_DDL
    assert not _audit_log_ddl_is_current(_OLD_DDL)
    assert _audit_log_ddl_is_current(db_module._AUDIT_LOG_REBUILT_DDL)


@pytest.fixture()
def old_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'c890_upgrade.db'}", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text(_OLD_DDL))
    User.__table__.create(engine)
    AuditLogSequenceCounter.__table__.create(engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    with session_local() as s:
        log(s, user_id="u1", user_name="Admin", table_name="users", record_id="u1", action="LOGIN",
            ip_address="203.0.113.7", tenant_id="tenant-a")
        for i in range(2):
            log(s, user_id="u2", user_name="Reviewer", table_name="kyc_review_decisions", record_id=f"d{i}",
                action="APPROVE", tenant_id="tenant-a")
        s.commit()
    yield engine, session_local
    engine.dispose()


def _rows(engine) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(
            "SELECT id, integrity_hash, sequence, previous_hash FROM audit_log ORDER BY sequence"))]


def _ddl(engine) -> str:
    with engine.connect() as conn:
        return str(conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='audit_log'")).scalar())


def test_old_check_rejects_compromise_before_upgrade(old_db):
    engine, session_local = old_db
    with session_local() as s:
        log(s, user_id="u3", user_name="Admin", table_name="reviewer_accounts", record_id="r1", action="COMPROMISE")
        with pytest.raises(IntegrityError):
            s.commit()


def test_upgrade_rebuilds_check_keeps_chain_and_accepts_compromise(old_db):
    engine, session_local = old_db
    before = _rows(engine)
    assert len(before) == 3

    ensure_audit_log_actions(engine)

    assert "'COMPROMISE'" in _ddl(engine).upper()
    assert _rows(engine) == before  # Zeilenzahl, Hashes, Sequenzen, Vorgaenger unveraendert
    with session_local() as s:
        log(s, user_id="u3", user_name="Admin", table_name="reviewer_accounts", record_id="r1",
            action="COMPROMISE", new_value="Widerruf wegen Kompromittierung")
        s.commit()
    with session_local() as s:
        verdict = verify_audit_chain(s)
    assert verdict["ok"], verdict["errors"]
    assert verdict["checked"] == 4
    assert _rows(engine)[-1][2] == 4
