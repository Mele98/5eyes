"""risk_override_decisions/risk_profile_signoffs: tenant_id + insert guard (PG-002).

Closure review of PR #662: both append-only evidence tables carried mandate,
client, effective risk profile, reasons and actors but no ``tenant_id``; the
PostgreSQL RLS plan only discovers tables with that column, so neither had a
policy.

Upgrade, in this order:

1. ``tenant_id`` (nullable) + index on both tables.
2. Legacy rows are backfilled deterministically from their mandate
   (``mandates.tenant_id``) with the RLS operator bypass. The append-only
   UPDATE guard is lifted only around this statement and restored right
   after. Rows without a derivable tenant (mandate purged, mandate without
   tenant) stay NULL: quarantined -- under strict RLS no tenant sees them,
   they are never assigned to a guessed tenant. The count is reported.
3. Insert guard: tenant derived from the mandate (conflicting or missing ->
   rejected on PostgreSQL), client must be the mandate's client, assessment
   must belong to the mandate. RLS ENABLE + FORCE and the strict policy
   follow at boot via ``ensure_postgres_rls_policies`` (both tables now carry
   ``tenant_id`` and are part of the plan).

Revision ID: b5d2e8f41a73
Revises: 94089093281c
Create Date: 2026-10-24
"""
import logging
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

from services import risk_evidence_tenant_boundary as retb
from services.tenant_context import BYPASS_GUC


revision: str = "b5d2e8f41a73"
down_revision: Union[str, Sequence[str], None] = "94089093281c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def _dialect() -> str:
    return op.get_bind().dialect.name if not context.is_offline_mode() else context.get_context().dialect.name


def upgrade() -> None:
    dialect = _dialect()
    for table in retb.RISK_EVIDENCE_TENANT_TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(), nullable=True))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    if dialect == "postgresql":
        op.execute(sa.text(f"SELECT set_config('{BYPASS_GUC}', 'on', true)"))
        for table in retb.RISK_EVIDENCE_TENANT_TABLES:
            immutable = retb.POSTGRES_IMMUTABLE_TRIGGERS[table]
            op.execute(sa.text(f"ALTER TABLE {table} DISABLE TRIGGER {immutable}"))
            op.execute(sa.text(retb.backfill_tenant_sql(table)))
            op.execute(sa.text(f"ALTER TABLE {table} ENABLE TRIGGER {immutable}"))
        op.execute(sa.text(retb.POSTGRES_FUNCTION))
        for table in retb.RISK_EVIDENCE_TENANT_TABLES:
            for ddl in retb.postgres_triggers(table):
                op.execute(sa.text(ddl))
    else:
        for table in retb.RISK_EVIDENCE_TENANT_TABLES:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_no_update"))
            op.execute(sa.text(retb.backfill_tenant_sql(table)))
            op.execute(sa.text(retb.SQLITE_NO_UPDATE_TRIGGERS[table]))
            for ddl in retb.sqlite_guard_triggers(table):
                op.execute(sa.text(ddl))

    if not context.is_offline_mode():
        bind = op.get_bind()
        quarantined = {
            table: int(bind.execute(sa.text(retb.quarantined_count_sql(table))).scalar() or 0)
            for table in retb.RISK_EVIDENCE_TENANT_TABLES
        }
        if any(quarantined.values()):
            logger.warning(
                "PG-002: Risiko-Evidence ohne ableitbaren Mandanten bleibt quarantaeniert "
                "(tenant_id NULL, unter RLS fuer keinen Mandanten sichtbar): %s",
                quarantined,
            )


def downgrade() -> None:
    dialect = _dialect()
    if dialect == "postgresql":
        for table in retb.RISK_EVIDENCE_TENANT_TABLES:
            op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
            op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
            op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
            op.execute(sa.text(
                f"DROP TRIGGER IF EXISTS {retb.guard_trigger_name(table)} ON {table}"
            ))
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {retb.POSTGRES_FUNCTION_NAME}()"))
    else:
        for table in retb.RISK_EVIDENCE_TENANT_TABLES:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {retb.guard_trigger_name(table)}"))
    for table in retb.RISK_EVIDENCE_TENANT_TABLES:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
