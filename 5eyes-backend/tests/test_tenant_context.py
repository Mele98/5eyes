from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.tenant_context import (  # noqa: E402
    _reset_dbapi_context,
    is_postgres_bind,
    operator_bypass,
    reset_tenant_context,
    set_tenant_context,
)


def test_sqlite_tenant_context_is_noop_but_records_session_info(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tenant-context.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine)
    with Session() as db:
        assert is_postgres_bind(db) is False
        set_tenant_context(db, "firm-A")
        assert db.info["tenant_id"] == "firm-A"
        reset_tenant_context(db)
        assert "tenant_id" not in db.info


def test_operator_bypass_context_restores_previous_sqlite_state(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tenant-context-bypass.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine)
    with Session() as db:
        with operator_bypass(db):
            assert db.info["rls_bypass"] is True
        assert db.info["rls_bypass"] is False


# ---------------------------------------------------------------------------
# TENANT-CONTEXT-IDLE-IN-TRANSACTION-001 (Kontrollrunde 2026-09-25)
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, calls: list[str]):
        self._calls = calls

    def execute(self, sql, *args, **kwargs):
        self._calls.append(("execute", sql))

    def close(self):
        self._calls.append(("close_cursor", None))


class _FakeDbapiConnection:
    """Minimal stand-in for a raw (non-autocommit) DBAPI connection, as
    handed to SQLAlchemy pool 'checkin'/'checkout' event listeners."""

    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def cursor(self):
        return _FakeCursor(self.calls)

    def commit(self):
        self.calls.append(("commit", None))

    def rollback(self):
        self.calls.append(("rollback", None))


def test_reset_dbapi_context_commits_after_reset_statements():
    """Kern-Repro: RESET laeuft auf einer rohen (nicht-autocommit) DBAPI-
    Connection und startet dadurch implizit eine Transaktion. Ohne
    explizites commit()/rollback() blieb die Verbindung beim naechsten
    Pool-Checkin dauerhaft 'idle in transaction'. _reset_dbapi_context()
    muss die Transaktion jetzt selbst schliessen."""
    fake = _FakeDbapiConnection()

    _reset_dbapi_context(fake)

    kinds = [call[0] for call in fake.calls]
    assert kinds.count("execute") == 2
    assert "commit" in kinds
    # commit() muss NACH den beiden RESET-Statements und NACH dem
    # Cursor-Close passieren, sonst schliesst es die falsche/eine
    # unvollstaendige Transaktion.
    assert kinds.index("commit") > kinds.index("close_cursor")
    assert kinds[kinds.index("close_cursor") - 1] == "execute"
