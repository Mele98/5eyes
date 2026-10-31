"""Postgres-RLS: globale Referenzzeilen fuer alle Tenants lesbar.

RLS-GLOBAL-REFERENCE-ROWS (2026-10-24). Das einheitliche Praedikat
``tenant_id::text = current_setting('app.tenant_id')`` ist fuer
``tenant_id IS NULL`` nie wahr. Globale Produkte, die globale CMA und die
globalen Eignungsregelwerke/-regeln waren damit fuer jede Tenant-Session auf
Postgres unsichtbar (belegt in tests/test_postgres_rls_global_reference_rows.py).

Neu fuer genau diese vier Referenztabellen: Policies je Kommando.
- SELECT: eigener Tenant ODER ``tenant_id IS NULL`` ODER Operator-Bypass.
- INSERT/UPDATE/DELETE: eigener Tenant ODER Operator-Bypass. Ein Tenant kann
  globale Zeilen weder aendern noch loeschen noch neu anlegen.
Kunden-, Benutzer- und Audit-Tabellen bleiben unveraendert strikt.

Gleiche DDL wie ``services/postgres_rls.py::rls_policy_sql`` (die init_db bei
jedem Start erneut anwendet); hier bewusst eingefroren statt importiert.
Idempotent (DROP POLICY IF EXISTS vor jedem CREATE). SQLite: No-op, dort gibt
es kein RLS.

Downgrade stellt die strikte Einzel-Policy ``tenant_isolation`` wieder her
(fail-closed: globale Zeilen danach wieder unsichtbar, aber nie schreibbar).

Revision ID: e2b7c4f9a1d6
Revises: c4d9e2a7f1b6
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import op


revision: str = "e2b7c4f9a1d6"
down_revision: Union[str, Sequence[str], None] = "c4d9e2a7f1b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


REFERENCE_TABLES = (
    "capital_market_assumptions",
    "product_eligibility_rule_sets",
    "product_eligibility_rules",
    "products",
)
REFERENCE_POLICIES = (
    "tenant_reference_select",
    "tenant_reference_insert",
    "tenant_reference_update",
    "tenant_reference_delete",
)
_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')"
_BYPASS = "current_setting('app.rls_bypass', true) = 'on'"
_WRITE = f"(tenant_id::text = {_TENANT} OR {_BYPASS})"
_READ = f"(tenant_id::text = {_TENANT} OR tenant_id IS NULL OR {_BYPASS})"


def _is_postgres() -> bool:
    return op.get_context().dialect.name.startswith("postgresql")


def _drop_all(table: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    for name in REFERENCE_POLICIES:
        op.execute(f'DROP POLICY IF EXISTS {name} ON "{table}"')


def upgrade() -> None:
    if not _is_postgres():
        return
    for table in REFERENCE_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        _drop_all(table)
        op.execute(
            f'CREATE POLICY tenant_reference_select ON "{table}" FOR SELECT USING ({_READ})'
        )
        op.execute(
            f'CREATE POLICY tenant_reference_insert ON "{table}" FOR INSERT WITH CHECK ({_WRITE})'
        )
        op.execute(
            f'CREATE POLICY tenant_reference_update ON "{table}" FOR UPDATE '
            f"USING ({_WRITE}) WITH CHECK ({_WRITE})"
        )
        op.execute(
            f'CREATE POLICY tenant_reference_delete ON "{table}" FOR DELETE USING ({_WRITE})'
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    for table in REFERENCE_TABLES:
        _drop_all(table)
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" '
            f"USING ({_WRITE}) WITH CHECK ({_WRITE})"
        )
