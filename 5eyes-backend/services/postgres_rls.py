"""PostgreSQL row-level-security setup for tenant-owned tables."""
from __future__ import annotations

import importlib
import pkgutil
import re
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from database import Base
from services.tenant_context import BYPASS_GUC, TENANT_GUC


_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def import_tenant_models() -> None:
    """Import every ORM module so Base.metadata knows all tenant-owned tables.

    RLS-CI-guard hardening (2026-08-17): this used to be a hand-maintained
    list of ``import models.X`` statements. A prior security audit flagged it
    as fragile -- a future model file with a ``tenant_id`` column that
    nobody remembered to add to this list would be invisible to
    ``Base.metadata`` and therefore to ``tenant_scoped_table_names()`` /
    ``ensure_postgres_rls_policies()``, silently shipping without an RLS
    policy. The check would still "pass" because it only ever verified the
    tables already on the list, never "every table that should be on it".

    Fix: walk the ``models`` package directory at runtime via ``pkgutil`` and
    import every submodule found there. Any new ``models/*.py`` file is
    picked up automatically on the next run -- there is no list left to
    forget to update. See ``tests/test_rls_dynamic_table_coverage_guard.py``
    for the unit test proving this (and the live-Postgres integration test
    that asserts every discovered table actually has a ``pg_policies`` row).
    """

    import models as _models_pkg

    for module_info in pkgutil.iter_modules(_models_pkg.__path__, prefix=f"{_models_pkg.__name__}."):
        importlib.import_module(module_info.name)


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


def _assert_rls_effective_role(conn: Connection) -> None:
    """#299-Security-Follow-up #4: RLS wird von einer Superuser- oder BYPASSRLS-
    Rolle vollstaendig umgangen — auch mit FORCE ROW LEVEL SECURITY. Verbindet die
    App in staging/production mit einer solchen Rolle, ist die gesamte DB-seitige
    Tenant-Isolation wirkungslos. Daher hart abbrechen. Dev/test bleiben frei
    (lokales PostgreSQL laeuft oft als superuser).
    """
    from config import settings

    if settings.app_env not in {"staging", "production"}:
        return
    row = conn.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).first()
    if row is not None and (bool(row[0]) or bool(row[1])):
        raise RuntimeError(
            "Tenant-RLS wirkungslos: die App-DB-Rolle ist Superuser oder hat "
            "BYPASSRLS. In staging/production eine dedizierte, unprivilegierte Rolle "
            "(NOSUPERUSER, NOBYPASSRLS, nicht Tabellen-Owner) verwenden."
        )


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
            _assert_rls_effective_role(conn)
            return _execute_policy_ddl(conn, resolved)
    _assert_rls_effective_role(connectable)
    return _execute_policy_ddl(connectable, resolved)


def tenant_tables_missing_rls_policies(
    connectable: Engine | Connection,
    *,
    table_names: Iterable[str] | None = None,
    schema: str | None = None,
) -> list[str]:
    """CI/ops guard: which dynamically-discovered tenant tables have NO
    ``pg_policies`` row at all right now?

    This is the coverage check the 2026-08-17 audit asked for: instead of
    trusting a fixed list of "tables we already know are covered", it asks
    Postgres's own catalog which of the tables ``tenant_scoped_table_names()``
    discovers *right now* (by introspecting ``Base.metadata`` -- see
    ``import_tenant_models()``) actually have a policy applied. A future
    model with a ``tenant_id`` column that ships without a call to
    ``ensure_postgres_rls_policies()`` for it shows up here, loudly, instead
    of silently passing.

    Returns an empty list on SQLite/non-Postgres dialects (RLS is a Postgres
    concept). ``schema`` optionally restricts the ``pg_policies`` lookup to
    one schema (tests that spin up a throwaway per-test schema should pass
    it; production callers on the default ``public`` schema can leave it
    unset).
    """

    if not _is_postgres(connectable):
        return []

    resolved = tuple(table_names or tenant_scoped_table_names())
    if not resolved:
        return []

    query = "SELECT DISTINCT tablename FROM pg_policies WHERE tablename = ANY(:names)"
    params: dict[str, object] = {"names": list(resolved)}
    if schema is not None:
        query += " AND schemaname = :schema"
        params["schema"] = schema

    if isinstance(connectable, Engine):
        with connectable.connect() as conn:
            rows = conn.execute(text(query), params).all()
    else:
        rows = connectable.execute(text(query), params).all()

    covered = {row[0] for row in rows}
    return sorted(set(resolved) - covered)


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
