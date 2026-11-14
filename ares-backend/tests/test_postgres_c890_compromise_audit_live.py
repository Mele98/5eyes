"""H11 (Hygiene-Folgepunkt C-890, N-897-19): 'COMPROMISE'-Audit-Eintrag live auf PostgreSQL.

Befund: Auf PostgreSQL war der ``COMPROMISE``-Insert (Kontowiderruf wegen
Kompromittierung) nicht live getestet; die CHECK-Ersetzung
(``ck_audit_log_action_allowed``, Migration ``d66fbf0588e3``) lief nur ueber die
Migrationsausfuehrung im CI.

Hier: komplette Alembic-Kette bis head in einem eigenen Schema (Fixture aus
``test_postgres_kyc_review_policy_live``), danach
* der CHECK enthaelt 'COMPROMISE';
* ``services.audit.log(action="COMPROMISE")`` wird angenommen und die Kette ist
  ok (Zaehler, Vorgaenger-Hash);
* Negativkontrolle: eine unbekannte Aktion scheitert am CHECK (der CHECK ist
  also wirksam und nicht etwa entfernt).

Ohne ``POSTGRES_TEST_DATABASE_URL`` uebersprungen; der CI-Job ``postgres-rls``
fuehrt diese Datei ausdruecklich aus.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.test_postgres_kyc_review_policy_live import pg_schema  # noqa: E402,F401  (Fixture)


def _check_definition(engine) -> str:
    with engine.connect() as conn:
        return str(conn.execute(text(
            "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE c.conname = 'ck_audit_log_action_allowed' AND t.relname = 'audit_log' "
            "AND n.nspname = current_schema()")).scalar() or "")


def test_postgres_accepts_compromise_audit_entry_and_keeps_chain(pg_schema):  # noqa: F811
    from services.audit import log, verify_audit_chain

    engine = pg_schema["engine"]
    assert "'COMPROMISE'" in _check_definition(engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    with session_local() as s:
        log(s, user_id="adm-a", user_name="Admin A", table_name="users", record_id="rev-1",
            action="LOGIN", tenant_id="t-pg")
        s.commit()
    with session_local() as s:
        log(s, user_id="adm-a", user_name="Admin A", table_name="users", record_id="rev-1",
            action="COMPROMISE", new_value="Widerruf wegen Kompromittierung (Test)", tenant_id="t-pg")
        s.commit()
    with session_local() as s:
        verdict = verify_audit_chain(s)
        actions = [row[0] for row in s.execute(text("SELECT action FROM audit_log ORDER BY sequence"))]
    assert verdict["ok"] is True, verdict["errors"]
    assert actions == ["LOGIN", "COMPROMISE"]


def test_postgres_check_still_rejects_unknown_action(pg_schema):  # noqa: F811
    from services.audit import log

    engine = pg_schema["engine"]
    session_local = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    with session_local() as s:
        log(s, user_id="adm-a", user_name="Admin A", table_name="users", record_id="rev-1",
            action="NOT_AN_AUDIT_ACTION", tenant_id="t-pg")
        with pytest.raises(Exception, match="ck_audit_log_action_allowed"):
            s.commit()
