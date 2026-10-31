"""Wealth inflow certainty (INFLOW-CERTAINTY-001).

wealth_inflows.certainty: 'sicher' | 'unsicher'. Nullable with server
default 'sicher'; existing rows (and NULL) count as 'sicher', so existing
data keeps its behaviour. 'unsicher' inflows neither lower the liquidity
reserve nor enter the strategy simulation (services/wealth_inflow_certainty.py).

Revision ID: e5a1c7f3b9d2
Revises: e8a4c2f7d913
Create Date: 2026-10-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5a1c7f3b9d2"
down_revision: Union[str, Sequence[str], None] = "e8a4c2f7d913"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wealth_inflows",
        sa.Column("certainty", sa.String(), nullable=True, server_default="sicher"),
    )


def downgrade() -> None:
    op.drop_column("wealth_inflows", "certainty")
