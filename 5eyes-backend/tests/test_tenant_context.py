from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.tenant_context import (  # noqa: E402
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
