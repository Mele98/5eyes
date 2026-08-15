"""Mark target allocations whose context artefacts are mandatory.

Revision ID: b6a7d9124e53
Revises: e84f9a2d1c70
Create Date: 2026-08-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6a7d9124e53"
down_revision: Union[str, Sequence[str], None] = "e84f9a2d1c70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "target_allocations",
        sa.Column(
            "context_artifacts_required",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("target_allocations", "context_artifacts_required")
