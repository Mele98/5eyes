"""DepotSnapshotV1 -- append-only, hash-gebundener IST-Bestand eines Mandats.

DEPOT-E2E-SNAPSHOT-001 / DEPOT-E2E-STRESS-001 Option 2: der IST-Stress-
Replay rechnet auf einem unveraenderlichen Depot-Snapshot (Positionen,
Werte, Waehrung, Stichtag, FX-Evidenz, SHA-256). UPDATE/DELETE per Trigger
verboten (SQLite und PostgreSQL). Kein FK auf mandates/clients (Purge-fest).

Revision ID: c8e2f4a6b1d3
Revises: f6b1d4a8c2e7
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8e2f4a6b1d3"
down_revision: Union[str, Sequence[str], None] = "f6b1d4a8c2e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS trg_depot_snapshots_no_update "
    "BEFORE UPDATE ON depot_snapshots FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'depot_snapshots is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_depot_snapshots_no_delete "
    "BEFORE DELETE ON depot_snapshots FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'depot_snapshots is immutable'); END",
)

_PG_FUNCTION = """
CREATE OR REPLACE FUNCTION depot_snapshots_immutable()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'depot_snapshots is immutable';
END;
$$ LANGUAGE plpgsql
"""

_PG_TRIGGER = """
CREATE TRIGGER trg_depot_snapshots_immutable
BEFORE UPDATE OR DELETE ON depot_snapshots
FOR EACH ROW EXECUTE FUNCTION depot_snapshots_immutable()
"""


def upgrade() -> None:
    op.create_table(
        "depot_snapshots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("as_of_date", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("snapshot_json", sa.String(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        # Muster audit_log/financial_coverage_attestations: kein FK auf
        # mandates/clients (Purge-fest), nur der Akteur verweist auf users.
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_depot_snapshots_mandate", "depot_snapshots", ["mandate_id", "as_of_date"],
    )

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for ddl in _SQLITE_TRIGGERS:
            op.execute(ddl)
    elif dialect == "postgresql":
        op.execute(_PG_FUNCTION)
        op.execute(_PG_TRIGGER)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_depot_snapshots_immutable ON depot_snapshots")
        op.execute("DROP FUNCTION IF EXISTS depot_snapshots_immutable()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_depot_snapshots_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_depot_snapshots_no_delete")
    op.drop_index("ix_depot_snapshots_mandate", table_name="depot_snapshots")
    op.drop_table("depot_snapshots")
