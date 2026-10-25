"""wealth_positions/wealth_inflows: tenant_id, composite link reference, triggers (PG-002).

Closure review of PR #666: both tables had no local ``tenant_id`` (invisible
to the PostgreSQL RLS plan) and ``wealth_inflows.linked_position_id`` was a
free string without any database invariant.

Upgrade, in this order:

1. ``tenant_id`` (nullable) on both tables, backfilled from the row's client
   (``clients.tenant_id``) -- never guessed or defaulted.
2. Existing links are verified: a dangling link or a link to another client's
   position ABORTS the migration with the offending inflow ids (operator
   repair, no silent re-assignment). Rows whose client has no tenant abort
   on PostgreSQL as well.
3. PostgreSQL: ``tenant_id SET NOT NULL``, unique key
   ``wealth_positions(id, client_id)``, composite foreign key
   ``wealth_inflows(linked_position_id, client_id)``, trigger functions
   (tenant derived from the client, link guard incl. soft-delete policy,
   linked position cannot change client). RLS ENABLE + FORCE and the policy
   follow at boot via ``ensure_postgres_rls_policies`` (the tables now carry
   ``tenant_id`` and are part of the plan).
   SQLite: unique index + equivalent triggers (ALTER TABLE cannot add a
   foreign key there).

The backfill and the checks run with the RLS operator bypass, so a database
whose ``clients`` already has FORCE RLS is migrated completely.

Revision ID: 94089093281c
Revises: 2cbc77503cd9
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

from services import wealth_tenant_boundary as wtb
from services.tenant_context import BYPASS_GUC


revision: str = "94089093281c"
down_revision: Union[str, Sequence[str], None] = "2cbc77503cd9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _dialect() -> str:
    return op.get_bind().dialect.name if not context.is_offline_mode() else context.get_context().dialect.name


def upgrade() -> None:
    dialect = _dialect()
    offline = context.is_offline_mode()
    for table in wtb.WEALTH_TENANT_TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(), nullable=True))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    if dialect == "postgresql":
        op.execute(sa.text(f"SELECT set_config('{BYPASS_GUC}', 'on', true)"))
    for table in wtb.WEALTH_TENANT_TABLES:
        op.execute(sa.text(wtb.backfill_tenant_sql(table)))

    if not offline:
        bind = op.get_bind()
        invalid = wtb.find_invalid_inflow_links(bind, dialect=dialect)
        if invalid:
            raise RuntimeError(
                "PG-002-Migration abgebrochen: Vorsorge-Zufluesse mit verwaister oder "
                f"kundenfremder Verknuepfung: {', '.join(invalid[:50])}. Bitte bereinigen."
            )
        if dialect == "postgresql":
            missing = {
                table: bind.execute(sa.text(f"SELECT count(*) FROM {table} WHERE tenant_id IS NULL")).scalar()
                for table in wtb.WEALTH_TENANT_TABLES
            }
            if any(missing.values()):
                raise RuntimeError(
                    f"PG-002-Migration abgebrochen: Zeilen ohne ableitbaren Tenant {missing}. "
                    "Kunden-Tenant zuerst setzen."
                )

    if dialect == "postgresql":
        for table in wtb.WEALTH_TENANT_TABLES:
            op.alter_column(table, "tenant_id", nullable=False)
            op.create_foreign_key(f"fk_{table}_tenant", table, "tenants", ["tenant_id"], ["id"])
        op.create_unique_constraint(wtb.POSITION_ID_CLIENT_UNIQUE, "wealth_positions", ["id", "client_id"])
        op.create_foreign_key(
            wtb.COMPOSITE_FK_NAME,
            "wealth_inflows",
            "wealth_positions",
            ["linked_position_id", "client_id"],
            ["id", "client_id"],
        )
        for ddl in wtb.POSTGRES_FUNCTIONS:
            op.execute(sa.text(ddl))
        for table in wtb.WEALTH_TENANT_TABLES:
            for ddl in wtb.postgres_triggers(table):
                op.execute(sa.text(ddl))
    else:
        op.create_index(wtb.POSITION_ID_CLIENT_UNIQUE, "wealth_positions", ["id", "client_id"], unique=True)
        for table in wtb.WEALTH_TENANT_TABLES:
            for ddl in wtb.sqlite_triggers(table):
                op.execute(sa.text(ddl))


def downgrade() -> None:
    dialect = _dialect()
    if dialect == "postgresql":
        for table in wtb.WEALTH_TENANT_TABLES:
            op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
            op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
            op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_wealth_inflows_link_guard ON wealth_inflows"))
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_wealth_positions_linked_client_guard ON wealth_positions"
        ))
        for table in wtb.WEALTH_TENANT_TABLES:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_tenant_from_client ON {table}"))
        for function in (
            "wealth_inflow_link_guard",
            "wealth_position_linked_client_guard",
            "wealth_row_tenant_from_client",
        ):
            op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}()"))
        op.drop_constraint(wtb.COMPOSITE_FK_NAME, "wealth_inflows", type_="foreignkey")
        op.drop_constraint(wtb.POSITION_ID_CLIENT_UNIQUE, "wealth_positions", type_="unique")
        for table in wtb.WEALTH_TENANT_TABLES:
            op.drop_constraint(f"fk_{table}_tenant", table, type_="foreignkey")
    else:
        for table in wtb.WEALTH_TENANT_TABLES:
            for ddl in wtb.sqlite_triggers(table):
                name = ddl.split("IF NOT EXISTS", 1)[1].split()[0]
                op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
        op.drop_index(wtb.POSITION_ID_CLIENT_UNIQUE, table_name="wealth_positions")
    for table in wtb.WEALTH_TENANT_TABLES:
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
