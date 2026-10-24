"""Enforce unique live/current allocation anchors.

Revision ID: d4e8f1a9c2b7
Revises: b6a7d9124e53
Create Date: 2026-08-20

The SQLite reference schema already protects RiskAssessment and
TargetAllocation per mandate.  PostgreSQL is Alembic-only, while test and
fresh desktop databases are commonly created from ORM metadata.  This
revision brings the versioned production schema to the same contract.

OptimizerPolicy is a global current singleton in runtime code: it has no
tenant or jurisdiction scope, and selection fails closed unless exactly one
current row exists.  Indexing the predicate column itself (rather than
``policy_name``) enforces that effective contract while retaining unlimited
historical rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e8f1a9c2b7"
down_revision: Union[str, Sequence[str], None] = "b6a7d9124e53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ux_risk_one_current",
        "risk_assessments",
        ["mandate_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1 AND deleted_at IS NULL"),
        postgresql_where=sa.text("is_current = 1 AND deleted_at IS NULL"),
    )
    op.create_index(
        "ux_target_alloc_one_current",
        "target_allocations",
        ["mandate_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1 AND deleted_at IS NULL"),
        postgresql_where=sa.text("is_current = 1 AND deleted_at IS NULL"),
    )
    op.create_index(
        "ux_optimizer_one_current",
        "optimizer_policies",
        ["is_current"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
        postgresql_where=sa.text("is_current = 1"),
    )


def downgrade() -> None:
    op.drop_index("ux_optimizer_one_current", table_name="optimizer_policies")
    op.drop_index("ux_target_alloc_one_current", table_name="target_allocations")
    op.drop_index("ux_risk_one_current", table_name="risk_assessments")
