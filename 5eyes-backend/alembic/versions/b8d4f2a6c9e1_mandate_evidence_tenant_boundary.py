"""depot_snapshots + onsite_signature_*: tenant_id + insert guard (PG-002).

Red-team review 2026-10-28, finding 6: the append-only tables
``depot_snapshots``, ``onsite_signature_events``,
``onsite_signature_challenges`` and ``onsite_signature_evidence`` carried
only ``mandate_id``; the PostgreSQL RLS plan only discovers tables with a
``tenant_id`` column, so none of them had a policy.

Upgrade, in this order:

1. ``tenant_id`` (nullable) + index on all four tables.
2. Legacy rows are backfilled deterministically from their mandate
   (``mandates.tenant_id``), on PostgreSQL with the RLS operator bypass. The
   append-only UPDATE guard is lifted only around this statement and
   restored right after. Rows without a derivable tenant (mandate purged)
   stay NULL: quarantined -- under strict RLS no tenant sees them, they are
   never assigned to a guessed tenant. The count is reported.
3. Insert guard: tenant derived from the mandate (conflicting or missing ->
   rejected on PostgreSQL), client must be the mandate's client. RLS ENABLE
   + FORCE and the strict policy follow at boot via
   ``ensure_postgres_rls_policies`` (the tables now carry ``tenant_id``).

The DDL is frozen here as literals (red-team finding 5);
``services/mandate_evidence_tenant_boundary.py`` carries the same SQLite DDL
for create_all and the runtime patch, a test checks equality.

Revision ID: b8d4f2a6c9e1
Revises: e7a3c9d1b5f2
Create Date: 2026-10-30
"""
import logging
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "b8d4f2a6c9e1"
down_revision: Union[str, Sequence[str], None] = "e7a3c9d1b5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

TABLES: tuple[str, ...] = (
    "depot_snapshots",
    "onsite_signature_events",
    "onsite_signature_challenges",
    "onsite_signature_evidence",
)
TENANT_ERROR = "MANDATE_EVIDENCE_TENANT_MISMATCH"
PG_FUNCTION_NAME = "mandate_evidence_tenant_from_mandate"
BYPASS_GUC = "app.rls_bypass"

PG_FUNCTION = f"""CREATE OR REPLACE FUNCTION {PG_FUNCTION_NAME}() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text; mandate_client text;
BEGIN
  SELECT m.tenant_id, m.client_id INTO derived, mandate_client FROM mandates m WHERE m.id = NEW.mandate_id;
  IF derived IS NULL THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  IF NEW.tenant_id IS NOT NULL AND NEW.tenant_id IS DISTINCT FROM derived THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  IF NEW.client_id IS DISTINCT FROM mandate_client THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  NEW.tenant_id := derived;
  RETURN NEW;
END $$"""


def guard_name(table: str) -> str:
    return f"trg_{table}_tenant_guard"


def sqlite_guard(table: str) -> str:
    return (
        f"CREATE TRIGGER IF NOT EXISTS {guard_name(table)} "
        f"BEFORE INSERT ON {table} FOR EACH ROW "
        f"WHEN NEW.tenant_id IS NOT (SELECT m.tenant_id FROM mandates m WHERE m.id = NEW.mandate_id) "
        f"OR EXISTS (SELECT 1 FROM mandates m WHERE m.id = NEW.mandate_id "
        f"AND m.client_id IS NOT NEW.client_id) "
        f"BEGIN SELECT RAISE(ABORT, '{TENANT_ERROR}'); END"
    )


def sqlite_no_update(table: str) -> str:
    return (
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update "
        f"BEFORE UPDATE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END"
    )


def backfill(table: str) -> str:
    return (
        f"UPDATE {table} SET tenant_id = (SELECT m.tenant_id FROM mandates m "
        f"WHERE m.id = {table}.mandate_id) WHERE tenant_id IS NULL"
    )


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
        op.execute(sa.text(PG_FUNCTION))
        for table in TABLES:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {guard_name(table)} ON {table}"))
            op.execute(sa.text(
                f"CREATE TRIGGER {guard_name(table)} BEFORE INSERT ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION {PG_FUNCTION_NAME}()"
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
                "PG-002: Mandats-Evidenz ohne ableitbaren Mandanten bleibt quarantaeniert "
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
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {PG_FUNCTION_NAME}()"))
    else:
        for table in TABLES:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {guard_name(table)}"))
    for table in TABLES:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
