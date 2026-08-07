"""2026-08-07 (CEO/CFO/CIO-Audit): audit_log.action CHECK-Constraint im
Rohschema (5eyes_schema_v4.0_FINAL.sql) erlaubte nur 6 von 32 codebase-weit
tatsaechlich verwendeten action-Werten ('CREATE','UPDATE','DELETE','LOGIN',
'EXPORT','PASSWORD_RESET'). Jeder Aufruf von services.audit.log(action=X)
mit einem der 26 fehlenden Werte (z.B. 'ACTIVATE' beim Aktivieren einer
Optimizer-Policy, 'UPSERT' beim FX-Rate-Update, '2FA_ENABLE' etc.) warf auf
einer echten SQLite-Bootstrap-DB eine IntegrityError -- unbemerkt, weil
Base.metadata.create_all() (von fast allen Tests genutzt) KEINE CHECK-
Constraints kennt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import configure_mappers, sessionmaker

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
from services.audit import log

configure_mappers()

SCHEMA_PATH = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"

PREVIOUSLY_MISSING_ACTIONS = [
    "2FA_DISABLE", "2FA_ENABLE", "2FA_RECOVERY_REGEN", "2FA_RECOVERY_USED",
    "ACTIVATE", "APPROVE", "BACKFILL", "BACKUP", "CLONE", "DB_OPTIMIZE",
    "FOUNDATION_EXAMPLE", "FOUNDATION_PURGE", "INVITE", "INVITE_ACCEPT",
    "INVITE_RESEND", "INVITE_REVOKE", "MARKET_DATA_PURGE",
    "MARKET_DATA_REFRESH", "OPTIMIZER_MODE_CHANGE", "PASSWORD_CHANGE",
    "PASSWORD_RESET_CONFIRM", "PASSWORD_RESET_REQUEST", "REPLACE",
    "REPLACE_ALL", "SENSITIVITY", "SUPPORT_BUNDLE", "UPSERT",
]


@pytest.fixture()
def fresh_session(tmp_path, monkeypatch):
    db_path = tmp_path / "audit_action_drift.db"
    bootstrap_sqlite_schema(db_path=str(db_path), schema_path=str(SCHEMA_PATH))
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db_module, "engine", engine)
    ensure_runtime_columns()
    ensure_audit_log_actions(engine)
    ensure_audit_log_triggers(engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    return session_local


@pytest.mark.parametrize("action_value", PREVIOUSLY_MISSING_ACTIONS)
def test_previously_missing_action_now_accepted_on_fresh_bootstrap(fresh_session, action_value):
    with fresh_session() as session:
        log(
            session, user_id="u1", user_name="Admin", table_name="system",
            record_id="r1", action=action_value,
        )
        session.commit()
        entry = session.query(AuditLog).one()
        assert entry.action == action_value


def test_unknown_action_still_rejected_by_check_constraint(fresh_session):
    """Die CHECK-Constraint muss weiterhin echten Schutz bieten -- ein
    komplett unbekannter Wert darf NICHT durchrutschen."""
    with fresh_session() as session:
        with pytest.raises(IntegrityError):
            log(
                session, user_id="u1", user_name="Admin", table_name="system",
                record_id="r1", action="TOTALLY_MADE_UP_ACTION",
            )
            session.commit()
