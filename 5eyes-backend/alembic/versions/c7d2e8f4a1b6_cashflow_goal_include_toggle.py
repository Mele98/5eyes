"""Add is_included toggle to cashflows and goals (CASHFLOW-GOAL-INCLUDE-TOGGLE-001).

Revision ID: c7d2e8f4a1b6
Revises: e5b8a3f1c9d4
Create Date: 2026-10-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d2e8f4a1b6"
down_revision: Union[str, Sequence[str], None] = "e5b8a3f1c9d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cashflows",
        sa.Column(
            "is_included",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "goals",
        sa.Column(
            "is_included",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("goals", "is_included")
    op.drop_column("cashflows", "is_included")
