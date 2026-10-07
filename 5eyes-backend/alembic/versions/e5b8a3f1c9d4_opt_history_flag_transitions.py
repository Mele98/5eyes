"""Add opt_history flag-transition columns for professional-opt-out/qualified-investor.

DUAL-STACK-01-Nachtrag (2026-10-07): is_professional_opt_out/
is_qualified_investor had -- after the FIDLEG-STATE-001 fix, which removed
them from the general Client PUT -- NO valid change path left at all (the
opt-history router only ever transitioned client_classification). These
four nullable columns let POST /clients/{id}/opt-history transition the two
boolean flags in the SAME append-only, beleggebundene history row as the
classification change. NULL = this particular transition left that flag
untouched (a pure reclassification without a flag change, or vice versa,
both remain valid).

Revision ID: e5b8a3f1c9d4
Revises: d1a9c4b7e2f6
Create Date: 2026-10-07

Note: originally chained onto a1c5e7f92b46 (the develop head at time of
writing). PR #543 (KYC-01, revision d1a9c4b7e2f6) merged first -- rebased
down_revision onto it to keep a single linear Alembic chain (Alembic would
otherwise see two heads for a1c5e7f92b46).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5b8a3f1c9d4"
down_revision: Union[str, Sequence[str], None] = "d1a9c4b7e2f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "client_opt_history",
        sa.Column("from_professional_opt_out", sa.Integer(), nullable=True),
    )
    op.add_column(
        "client_opt_history",
        sa.Column("to_professional_opt_out", sa.Integer(), nullable=True),
    )
    op.add_column(
        "client_opt_history",
        sa.Column("from_qualified_investor", sa.Integer(), nullable=True),
    )
    op.add_column(
        "client_opt_history",
        sa.Column("to_qualified_investor", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("client_opt_history", "to_qualified_investor")
    op.drop_column("client_opt_history", "from_qualified_investor")
    op.drop_column("client_opt_history", "to_professional_opt_out")
    op.drop_column("client_opt_history", "from_professional_opt_out")
