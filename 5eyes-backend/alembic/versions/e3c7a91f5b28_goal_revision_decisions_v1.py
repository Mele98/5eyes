"""Append-only GoalRevisionDecisionV1.

GOAL-REVISION-DECISION-001 (CIO-Entscheid 2026-10-21 nach Codex-Closure-
Review zu PR #655): die Engine stuft ein Ziel nie mehr automatisch aus der
Zielhierarchie-Stufe 1 herab (ein lokales Optimum ist kein globaler
Unmoeglichkeitsnachweis). Herabgestuft (nachrangiges Wunschziel) wird nur
ein Ziel mit einer expliziten, replaybaren Berater-Entscheidung in
goal_revision_decisions, deren Ziel-Snapshot-Hash zum aktuellen Ziel passt.
UPDATE/DELETE sind per Trigger verboten (SQLite und PostgreSQL); wie
risk_override_decisions KEIN FK auf goals/mandates (Purge-fest).

Revision ID: e3c7a91f5b28
Revises: e5a1c7f3b9d2
Create Date: 2026-10-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3c7a91f5b28"
down_revision: Union[str, Sequence[str], None] = "e5a1c7f3b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS trg_goal_revision_decisions_no_update "
    "BEFORE UPDATE ON goal_revision_decisions FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'goal_revision_decisions is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_goal_revision_decisions_no_delete "
    "BEFORE DELETE ON goal_revision_decisions FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'goal_revision_decisions is immutable'); END",
)

_PG_FUNCTION = """
CREATE OR REPLACE FUNCTION goal_revision_decisions_immutable()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'goal_revision_decisions is immutable';
END;
$$ LANGUAGE plpgsql
"""

_PG_TRIGGER = """
CREATE TRIGGER trg_goal_revision_decisions_immutable
BEFORE UPDATE OR DELETE ON goal_revision_decisions
FOR EACH ROW EXECUTE FUNCTION goal_revision_decisions_immutable()
"""


def upgrade() -> None:
    op.create_table(
        "goal_revision_decisions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("goal_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=True),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("previous_decision_id", sa.String(), nullable=True),
        sa.Column("goal_snapshot_hash", sa.String(), nullable=False),
        sa.Column("goal_snapshot_json", sa.String(), nullable=False),
        sa.Column("previous_hardness", sa.String(), nullable=False),
        sa.Column("new_status", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("evidence_status", sa.String(), nullable=False),
        sa.Column("evidence_best_probability_bps", sa.Integer(), nullable=True),
        sa.Column("evidence_wilson_upper_bps", sa.Integer(), nullable=True),
        sa.Column("evidence_tau_bps", sa.Integer(), nullable=True),
        sa.Column("evidence_engine_version", sa.String(), nullable=False),
        sa.Column("evidence_allocation_id", sa.String(), nullable=True),
        sa.Column("evidence_screening_cube_hash", sa.String(), nullable=True),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("decided_at", sa.String(), nullable=False),
        sa.Column("rules_version", sa.String(), nullable=False),
        sa.Column("decision_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        # Wie audit_log/risk_override_decisions: nur der Akteur per FK.
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("sequence_no >= 1", name="ck_goal_revision_sequence"),
        sa.CheckConstraint(
            "new_status IN ('nachrangiges_wunschziel')",
            name="ck_goal_revision_new_status",
        ),
    )
    op.create_index(
        "ux_goal_revision_decision_sequence",
        "goal_revision_decisions",
        ["goal_id", "sequence_no"],
        unique=True,
    )
    op.create_index(
        "ix_goal_revision_decisions_mandate",
        "goal_revision_decisions",
        ["mandate_id"],
    )

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for ddl in _SQLITE_TRIGGERS:
            op.execute(ddl)
    elif dialect == "postgresql":
        op.execute(_PG_FUNCTION)
        op.execute(_PG_TRIGGER)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_goal_revision_decisions_immutable ON goal_revision_decisions")
        op.execute("DROP FUNCTION IF EXISTS goal_revision_decisions_immutable()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_goal_revision_decisions_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_goal_revision_decisions_no_delete")
    op.drop_index("ix_goal_revision_decisions_mandate", table_name="goal_revision_decisions")
    op.drop_index("ux_goal_revision_decision_sequence", table_name="goal_revision_decisions")
    op.drop_table("goal_revision_decisions")
