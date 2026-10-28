"""DepotCheckAnalysisSnapshot -- Depot-Check-Ergebnis gebunden an einen DepotSnapshotV1.

DEPOT-E2E-SNAPSHOT-001: JSON-Depot-Check und Depot-Check-PDF lesen denselben
gespeicherten, hash-gebundenen Analysis-Snapshot (snapshot_id + snapshot_hash
des Depot-Snapshots, Analyse-Version, Ergebnis-Hash). UPDATE/DELETE per
Trigger verboten (SQLite und PostgreSQL). Kein FK auf mandates/clients/
depot_snapshots (Purge-fest, Bindung per Hash).

Revision ID: e7a3c9d1b5f2
Revises: d2f8b6a1c4e9
Create Date: 2026-10-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7a3c9d1b5f2"
down_revision: Union[str, Sequence[str], None] = "d2f8b6a1c4e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "depot_check_analysis_snapshots"
_INDEX = "ix_depot_check_analysis_snapshots_mandate"

_SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS trg_depot_check_analysis_snapshots_no_update "
    "BEFORE UPDATE ON depot_check_analysis_snapshots FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'depot_check_analysis_snapshots is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_depot_check_analysis_snapshots_no_delete "
    "BEFORE DELETE ON depot_check_analysis_snapshots FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'depot_check_analysis_snapshots is immutable'); END",
)

_PG_FUNCTION = """
CREATE OR REPLACE FUNCTION depot_check_analysis_snapshots_immutable()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'depot_check_analysis_snapshots is immutable';
END;
$$ LANGUAGE plpgsql
"""

_PG_TRIGGER = """
CREATE TRIGGER trg_depot_check_analysis_snapshots_immutable
BEFORE UPDATE OR DELETE ON depot_check_analysis_snapshots
FOR EACH ROW EXECUTE FUNCTION depot_check_analysis_snapshots_immutable()
"""


def upgrade() -> None:
    # Wie depot_snapshots (c8e2f4a6b1d3): reines DDL, auch offline (--sql)
    # erzeugbar; SQLite-Bootstrap/Runtime-Patch nutzen CREATE ... IF NOT EXISTS.
    bind = op.get_bind()
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("depot_snapshot_id", sa.String(), nullable=False),
        sa.Column("depot_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("as_of_date", sa.String(), nullable=False),
        sa.Column("analysis_json", sa.String(), nullable=False),
        sa.Column("analysis_hash", sa.String(length=64), nullable=False),
        sa.Column("result_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        # Muster depot_snapshots: kein FK auf mandates/clients (Purge-fest),
        # nur der Akteur verweist auf users.
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(_INDEX, _TABLE, ["mandate_id", "created_at"])

    if bind.dialect.name == "sqlite":
        for ddl in _SQLITE_TRIGGERS:
            op.execute(ddl)
    elif bind.dialect.name == "postgresql":
        op.execute(_PG_FUNCTION)
        op.execute(_PG_TRIGGER)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS trg_depot_check_analysis_snapshots_immutable ON {_TABLE}")
        op.execute("DROP FUNCTION IF EXISTS depot_check_analysis_snapshots_immutable()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_depot_check_analysis_snapshots_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_depot_check_analysis_snapshots_no_delete")
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
