"""Vorsorge projection fields + inflow link (VORSORGE-PROJECTION-001).

wealth_positions: pension_vehicle, pension_interest_rate_bps,
pension_maturity_value_rappen, pension_maturity_date -- deterministische
Fortschreibung externer Vorsorge (alle NULL = Defaults je Anlageform).
wealth_inflows: linked_position_id -- ein erfasster Zufluss IST der Bezug
einer Vorsorge-Position (automatischer Bezug entfaellt, keine Doppelzaehlung).

Revision ID: b3f7a1c9e2d4
Revises: d7c3e9a2f5b1
Create Date: 2026-10-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3f7a1c9e2d4"
down_revision: Union[str, Sequence[str], None] = "d7c3e9a2f5b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("wealth_positions", sa.Column("pension_vehicle", sa.String(), nullable=True))
    op.add_column("wealth_positions", sa.Column("pension_interest_rate_bps", sa.Integer(), nullable=True))
    op.add_column("wealth_positions", sa.Column("pension_maturity_value_rappen", sa.Integer(), nullable=True))
    op.add_column("wealth_positions", sa.Column("pension_maturity_date", sa.String(), nullable=True))
    op.add_column("wealth_inflows", sa.Column("linked_position_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("wealth_inflows", "linked_position_id")
    op.drop_column("wealth_positions", "pension_maturity_date")
    op.drop_column("wealth_positions", "pension_maturity_value_rappen")
    op.drop_column("wealth_positions", "pension_interest_rate_bps")
    op.drop_column("wealth_positions", "pension_vehicle")
