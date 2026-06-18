"""PostgreSQL row-level-security setup for tenant-owned tables."""
from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from database import Base
from services.tenant_context import BYPASS_GUC, TENANT_GUC


_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def import_tenant_models() -> None:
    """Import ORM modules so Base.metadata knows all tenant-owned tables."""

    import models.allocation  # noqa: F401
    import models.client_login  # noqa: F401
    import models.clients  # noqa: F401
    import models.fx_rate  # noqa: F401
    import models.mandates  # noqa: F401
    import models.market_data_cache  # noqa: F401
    import models.market_data_validation_log  # noqa: F401
    import models.profiling  # noqa: F401
    import models.protocol_bausteine  # noqa: F401
    import models.review  # noqa: F401
    import models.snapshots  # noqa: F401
    import models.tenant  # noqa: F401
    import models.users  # noqa: F401
    import models.wealth  # noqa: F401


def tenant_scoped_table_names() -> tuple[str, ...]:
    """Return all mapped tables that physically carry a tenant_id column."""

    import_tenant_models()
    names = [
        table.name
        for table in Base.metadata.sorted_tables
        if "tenant_id" in table.c
    ]
    return tuple(sorted(names))


def quote_identifier(identifier: str) -> str:
    if not _IDENTIFIER_RE.match(identifier):
        raise ValueError(f"Ungueltiger SQL-Identifier: {identifier!r}")
    return f'"{identifier}"'


def _policy_predicate() -> str:
    tenant_expr = f"NULLIF(current_setting('{TENANT_GUC}', true), '')"
    bypass_expr = f"current_setting('{BYPASS_GUC}', true) = 'on'"
    return f"(tenant_id::text = {tenant_expr} OR {bypass_expr})"


def rls_policy_sql(table_name: str) -> tuple[str, ...]:
    """DDL statements for one tenant table, deterministic for tests."""

    q_table = quote_identifier(table_name)
    predicate = _policy_predicate()
    return (
        f"ALTER TABLE {q_table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {q_table} FORCE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS tenant_isolation ON {q_table}",
        (
            f"CREATE POLICY tenant_isolation ON {q_table} "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        ),
    )


def tenant_not_null_sql(table_name: str) -> tuple[str, str]:
    q_table = quote_identifier(table_name)
    return (
        f"UPDATE {q_table} SET tenant_id = :tenant_id WHERE tenant_id IS NULL",
        f"ALTER TABLE {q_table} ALTER COLUMN tenant_id SET NOT NULL",
    )


def _is_postgres(connectable: Engine | Connection) -> bool:
    dialect = getattr(connectable, "dialect", None)
    if dialect is None and hasattr(connectable, "engine"):
        dialect = getattr(connectable.engine, "dialect", None)
    return str(getattr(dialect, "name", "")).startswith("postgresql")


def _execute_policy_ddl(conn: Connection, table_names: Iterable[str]) -> list[str]:
    applied: list[str] = []
    for table_name in table_names:
        for statement in rls_policy_sql(table_name):
            conn.execute(text(statement))
        applied.append(table_name)
    return applied


def ensure_postgres_rls_policies(
    connectable: Engine | Connection,
    *,
    table_names: Iterable[str] | None = None,
) -> list[str]:
    """Enable and FORCE tenant RLS policies on PostgreSQL tenant tables.

    Returns the applied table names. On SQLite and other dialects it is a no-op.
    """

    if not _is_postgres(connectable):
        return []

    resolved = tuple(table_names or tenant_scoped_table_names())
    if isinstance(connectable, Engine):
        with connectable.begin() as conn:
            return _execute_policy_ddl(conn, resolved)
    return _execute_policy_ddl(connectable, resolved)


def _execute_tenant_not_null(conn: Connection, table_names: Iterable[str], default_tenant_id: str) -> list[str]:
    applied: list[str] = []
    for table_name in table_names:
        update_sql, alter_sql = tenant_not_null_sql(table_name)
        conn.execute(text(update_sql), {"tenant_id": default_tenant_id})
        conn.execute(text(alter_sql))
        applied.append(table_name)
    return applied


def ensure_postgres_tenant_not_null(
    connectable: Engine | Connection,
    *,
    table_names: Iterable[str] | None = None,
    default_tenant_id: str = "main",
) -> list[str]:
    """Backfill and enforce tenant_id NOT NULL on PostgreSQL tenant tables.

    SQLite remains nullable for backwards compatibility.
    """

    if not _is_postgres(connectable):
        return []

    resolved = tuple(table_names or tenant_scoped_table_names())
    if isinstance(connectable, Engine):
        with connectable.begin() as conn:
            return _execute_tenant_not_null(conn, resolved, default_tenant_id)
    return _execute_tenant_not_null(connectable, resolved, default_tenant_id)
