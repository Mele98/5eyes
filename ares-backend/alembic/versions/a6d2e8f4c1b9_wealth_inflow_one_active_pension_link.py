"""At most one active pension transfer per source (PENSION-TRANSFER-LEDGER-001).

wealth_inflows.linked_position_id (b3f7a1c9e2d4) marks an inflow as THE
lump-sum withdrawal of an external pension position. The current model is a
full payout: the source is booked out once. Two active inflows on the same
source would book the capital out once but pay it into free wealth twice.
The router pre-checks with a SELECT; this partial unique index backs it
against concurrent writes (same sqlite_where/postgresql_where pattern as
f2c8a4e9b1d3).

Existing installations with duplicate active links fail this migration
loudly instead of silently picking a winner (fail-closed, manual cleanup).

Revision ID: a6d2e8f4c1b9
Revises: b3f7a1c9e2d4
Create Date: 2026-10-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a6d2e8f4c1b9"
down_revision: Union[str, Sequence[str], None] = "b3f7a1c9e2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PREDICATE = "linked_position_id IS NOT NULL AND is_active = 1 AND deleted_at IS NULL"


def upgrade() -> None:
    op.create_index(
        "ux_wealth_inflow_one_active_pension_link",
        "wealth_inflows",
        ["linked_position_id"],
        unique=True,
        sqlite_where=sa.text(_PREDICATE),
        postgresql_where=sa.text(_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index("ux_wealth_inflow_one_active_pension_link", table_name="wealth_inflows")
