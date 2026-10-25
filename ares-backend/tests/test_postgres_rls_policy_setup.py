from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from services.postgres_rls import (  # noqa: E402
    ensure_postgres_tenant_not_null,
    ensure_postgres_rls_policies,
    rls_policy_sql,
    tenant_not_null_sql,
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


def test_postgres_not_null_sql_backfills_then_alters():
    update_sql, alter_sql = tenant_not_null_sql("mandates")
    assert update_sql == 'UPDATE "mandates" SET tenant_id = :tenant_id WHERE tenant_id IS NULL'
    assert alter_sql == 'ALTER TABLE "mandates" ALTER COLUMN tenant_id SET NOT NULL'


def test_sqlite_tenant_not_null_setup_is_noop_and_nullable(tmp_path):
    from sqlalchemy import inspect

    engine = create_engine(
        f"sqlite:///{tmp_path / 'rls-not-null-noop.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    assert ensure_postgres_tenant_not_null(engine) == []
    client_tenant = next(
        col for col in inspect(engine).get_columns("clients") if col["name"] == "tenant_id"
    )
    assert client_tenant["nullable"] is True


def test_reference_tables_get_split_policies_with_null_read_only():
    rendered = " ;; ".join(rls_policy_sql("products"))
    assert "CREATE POLICY tenant_isolation" not in rendered
    assert "DROP POLICY IF EXISTS tenant_isolation" in rendered
    select = next(s for s in rls_policy_sql("products") if "FOR SELECT" in s)
    assert "tenant_id IS NULL" in select
    for cmd in ("FOR INSERT", "FOR UPDATE", "FOR DELETE"):
        stmt = next(s for s in rls_policy_sql("products") if cmd in s)
        assert "IS NULL" not in stmt, cmd


def test_customer_tables_never_admit_null_tenant_rows():
    from services.postgres_rls import GLOBAL_REFERENCE_TABLES

    assert GLOBAL_REFERENCE_TABLES == {
        "capital_market_assumptions", "product_eligibility_rule_sets",
        "product_eligibility_rules", "products",
    }
    for table in set(tenant_scoped_table_names()) - GLOBAL_REFERENCE_TABLES:
        rendered = " ;; ".join(rls_policy_sql(table))
        assert "IS NULL" not in rendered, table
        assert "CREATE POLICY tenant_isolation" in rendered, table
        # Wechsel aus der Referenz-Variante darf keine weite Policy zuruecklassen.
        assert "DROP POLICY IF EXISTS tenant_reference_select" in rendered, table


def test_migration_ddl_matches_runtime_ddl():
    import importlib.util

    path = BACKEND_ROOT / "alembic" / "versions" / "e2b7c4f9a1d6_rls_global_reference_rows.py"
    spec = importlib.util.spec_from_file_location("_rls_ref_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from services.postgres_rls import (
        GLOBAL_REFERENCE_TABLES, REFERENCE_POLICY_NAMES,
        _policy_predicate, _reference_read_predicate,
    )

    assert set(module.REFERENCE_TABLES) == set(GLOBAL_REFERENCE_TABLES)
    assert tuple(module.REFERENCE_POLICIES) == REFERENCE_POLICY_NAMES
    assert module._WRITE == _policy_predicate()
    assert module._READ == _reference_read_predicate()
