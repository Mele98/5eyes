"""Persist review-trigger resolution evidence (decision/actor/anchors).

Revision ID: 8e9af7d00ffc
Revises: c3d8f4a1e6b2
Create Date: 2026-08-27

REVIEW-STATE-003 (Codex-Audit 2026-08-27): resolve_trigger() discarded the
required `decision` field entirely (only `triggered_notes` was read), had no
row lock or compare-and-set contract, and was freely replayable -- each call
recomputed `next_due_at` from the current server time with zero evidence of
what was actually decided. These four nullable, additive columns give the
resolve endpoint somewhere to persist an append-only evidence trail (actor,
server timestamp, decision, and the due-date anchor that was in effect right
before the resolution). NULL for pre-fix rows and for triggers that were
never resolved -- no backfill is attempted or possible for historical rows
that never had this evidence.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8e9af7d00ffc"
down_revision: Union[str, Sequence[str], None] = "c3d8f4a1e6b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "review_triggers",
        sa.Column("resolution_decision", sa.String(), nullable=True),
    )
    op.add_column(
        "review_triggers",
        sa.Column("resolved_by", sa.String(), nullable=True),
    )
    op.add_column(
        "review_triggers",
        sa.Column("resolved_at", sa.String(), nullable=True),
    )
    op.add_column(
        "review_triggers",
        sa.Column("previous_next_due_at", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("review_triggers", "previous_next_due_at")
    op.drop_column("review_triggers", "resolved_at")
    op.drop_column("review_triggers", "resolved_by")
    op.drop_column("review_triggers", "resolution_decision")
