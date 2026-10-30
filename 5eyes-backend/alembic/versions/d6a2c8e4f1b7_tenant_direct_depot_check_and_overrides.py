"""depot_check_analysis_snapshots + product_eligibility_overrides: tenant_id + insert guard (PG-002).

Follow-up to ``b8d4f2a6c9e1``: both append-only tables were
``tenant_derived`` (the depot check via ``mandate_id``, the overrides via
``recommendation_run_id`` -> run -> mandate) and therefore outside the
PostgreSQL RLS plan.

Upgrade, in this order:

1. ``tenant_id`` (nullable) + index on both tables.
2. Legacy rows are backfilled deterministically (depot check: from the
   mandate; overrides: from the mandate of the run), on PostgreSQL with the
   RLS operator bypass. The append-only UPDATE guard is lifted only around
   this statement. Rows without a derivable tenant (purged mandate or run)
   stay NULL: quarantined, never assigned to a guessed tenant.
3. Insert guard. Depot check: the function ``mandate_evidence_tenant_from_mandate``
   of ``b8d4f2a6c9e1`` (mandate tenant + client of the mandate). Overrides:
   new function ``run_evidence_tenant_from_run`` (tenant of the run's
   mandate; under RLS a foreign mandate is invisible -> rejected). RLS
   ENABLE + FORCE and the strict policy follow at boot via
   ``ensure_postgres_rls_policies``.

DDL frozen as literals; ``services/mandate_evidence_tenant_boundary.py``
carries the same SQLite DDL for create_all and the runtime patch, a test
checks equality.

Revision ID: d6a2c8e4f1b7
Revises: b8d4f2a6c9e1
Create Date: 2026-10-30
"""
import logging
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "d6a2c8e4f1b7"
down_revision: Union[str, Sequence[str], None] = "b8d4f2a6c9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

DEPOT_CHECK = "depot_check_analysis_snapshots"
OVERRIDES = "product_eligibility_overrides"
TABLES: tuple[str, ...] = (DEPOT_CHECK, OVERRIDES)
TENANT_ERROR = "MANDATE_EVIDENCE_TENANT_MISMATCH"
PG_MANDATE_FUNCTION_NAME = "mandate_evidence_tenant_from_mandate"  # aus b8d4f2a6c9e1
PG_RUN_FUNCTION_NAME = "run_evidence_tenant_from_run"
BYPASS_GUC = "app.rls_bypass"

PG_RUN_FUNCTION = f"""CREATE OR REPLACE FUNCTION {PG_RUN_FUNCTION_NAME}() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text;
BEGIN
  SELECT m.tenant_id INTO derived FROM recommendation_runs r JOIN mandates m ON m.id = r.mandate_id
   WHERE r.id = NEW.recommendation_run_id;
  IF derived IS NULL THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  IF NEW.tenant_id IS NOT NULL AND NEW.tenant_id IS DISTINCT FROM derived THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  NEW.tenant_id := derived;
  RETURN NEW;
END $$"""

_RUN_TENANT = (
    "SELECT m.tenant_id FROM recommendation_runs r JOIN mandates m ON m.id = r.mandate_id "
    "WHERE r.id = {ref}.recommendation_run_id"
)


def guard_name(table: str) -> str:
    return f"trg_{table}_tenant_guard"


def sqlite_guard(table: str) -> str:
    if table == OVERRIDES:
        return (
            f"CREATE TRIGGER IF NOT EXISTS {guard_name(table)} "
            f"BEFORE INSERT ON {table} FOR EACH ROW "
            f"WHEN NEW.tenant_id IS NOT ({_RUN_TENANT.format(ref='NEW')}) "
            f"BEGIN SELECT RAISE(ABORT, '{TENANT_ERROR}'); END"
        )
    return (
        f"CREATE TRIGGER IF NOT EXISTS {guard_name(table)} "
        f"BEFORE INSERT ON {table} FOR EACH ROW "
        f"WHEN NEW.tenant_id IS NOT (SELECT m.tenant_id FROM mandates m WHERE m.id = NEW.mandate_id) "
        f"OR EXISTS (SELECT 1 FROM mandates m WHERE m.id = NEW.mandate_id "
        f"AND m.client_id IS NOT NEW.client_id) "
        f"BEGIN SELECT RAISE(ABORT, '{TENANT_ERROR}'); END"
    )


def sqlite_no_update(table: str) -> str:
    message = f"{table} is immutable"
    return (
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update "
        f"BEFORE UPDATE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{message}'); END"
    )


def backfill(table: str) -> str:
    if table == OVERRIDES:
        return (
            f"UPDATE {table} SET tenant_id = ({_RUN_TENANT.format(ref=table)}) "
            f"WHERE tenant_id IS NULL"
        )
    return (
        f"UPDATE {table} SET tenant_id = (SELECT m.tenant_id FROM mandates m "
        f"WHERE m.id = {table}.mandate_id) WHERE tenant_id IS NULL"
    )


def _pg_function(table: str) -> str:
    return PG_RUN_FUNCTION_NAME if table == OVERRIDES else PG_MANDATE_FUNCTION_NAME


def _dialect() -> str:
    if context.is_offline_mode():
        return context.get_context().dialect.name
    return op.get_bind().dialect.name


def upgrade() -> None:
    dialect = _dialect()
    for table in TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(), nullable=True))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    if dialect == "postgresql":
        op.execute(sa.text(f"SELECT set_config('{BYPASS_GUC}', 'on', true)"))
        for table in TABLES:
            op.execute(sa.text(f"ALTER TABLE {table} DISABLE TRIGGER trg_{table}_immutable"))
            op.execute(sa.text(backfill(table)))
            op.execute(sa.text(f"ALTER TABLE {table} ENABLE TRIGGER trg_{table}_immutable"))
        op.execute(sa.text(PG_RUN_FUNCTION))
        for table in TABLES:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {guard_name(table)} ON {table}"))
            op.execute(sa.text(
                f"CREATE TRIGGER {guard_name(table)} BEFORE INSERT ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION {_pg_function(table)}()"
            ))
    else:
        for table in TABLES:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_no_update"))
            op.execute(sa.text(backfill(table)))
            op.execute(sa.text(sqlite_no_update(table)))
            op.execute(sa.text(sqlite_guard(table)))

    if not context.is_offline_mode():
        bind = op.get_bind()
        quarantined = {
            table: int(bind.execute(sa.text(
                f"SELECT count(*) FROM {table} WHERE tenant_id IS NULL"
            )).scalar() or 0)
            for table in TABLES
        }
        if any(quarantined.values()):
            logger.warning(
                "PG-002: Evidenz ohne ableitbaren Mandanten bleibt quarantaeniert "
                "(tenant_id NULL, unter RLS fuer keinen Mandanten sichtbar): %s",
                quarantined,
            )


def downgrade() -> None:
    dialect = _dialect()
    if dialect == "postgresql":
        for table in TABLES:
            op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
            op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
            op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {guard_name(table)} ON {table}"))
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {PG_RUN_FUNCTION_NAME}()"))
    else:
        for table in TABLES:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {guard_name(table)}"))
    for table in TABLES:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
