from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from services.postgres_rls import (  # noqa: E402
    ensure_postgres_rls_policies,
    rls_policy_sql,
    tenant_scoped_table_names,
)


def test_tenant_scoped_table_inventory_matches_current_models():
    names = set(tenant_scoped_table_names())
    assert {"clients", "mandates", "protocol_bausteine", "users"}.issubset(names)
    assert "tenants" not in names


def test_rls_policy_sql_contains_using_and_with_check():
    statements = rls_policy_sql("clients")
    rendered = "\n".join(statements)
    assert "ENABLE ROW LEVEL SECURITY" in rendered
    assert "FORCE ROW LEVEL SECURITY" in rendered
    assert "CREATE POLICY tenant_isolation" in rendered
    assert "USING" in rendered
    assert "WITH CHECK" in rendered
    assert "current_setting('app.tenant_id', true)" in rendered
    assert "current_setting('app.rls_bypass', true) = 'on'" in rendered


def test_rls_policy_sql_rejects_unsafe_identifier():
    import pytest

    with pytest.raises(ValueError):
        rls_policy_sql("clients;drop table users")


def test_sqlite_rls_policy_setup_is_noop(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'rls-noop.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    assert ensure_postgres_rls_policies(engine) == []
