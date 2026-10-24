"""Persist immutable asset-allocation decision artefacts.

Revision ID: 7b31f8d2a6c4
Revises: c91f2c722881
Create Date: 2026-08-10

The stochastic allocation engine must be able to reload the exact
sub-allocation and constraint context that was active when a target
allocation was accepted.  These nullable columns keep existing allocations
valid while making every newly generated stochastic allocation reproducible.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7b31f8d2a6c4"
down_revision: Union[str, Sequence[str], None] = "c91f2c722881"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "target_allocations",
        sa.Column("sub_allocations_json", sa.String(), nullable=True),
    )
    op.add_column(
        "target_allocations",
        sa.Column("effective_constraints_json", sa.String(), nullable=True),
    )
    op.add_column(
        "target_allocations",
        sa.Column("allocation_context_hash", sa.String(), nullable=True),
    )
    op.add_column(
        "optimizer_runs",
        sa.Column("robustification_json", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("optimizer_runs", "robustification_json")
    op.drop_column("target_allocations", "allocation_context_hash")
    op.drop_column("target_allocations", "effective_constraints_json")
    op.drop_column("target_allocations", "sub_allocations_json")
