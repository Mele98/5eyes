"""Append-only RiskOverrideDecisionV1 + Decision-Pointer am Assessment.

RISK-OVERRIDE-WRITE-BOUNDARY-001 Restbefund B (Codex-Closure-Review zu
PR #646, 2026-10-19): jeder Override/Re-Override schreibt eine
unveraenderliche, gehashte Decision-Zeile; risk_assessments traegt nur den
Pointer (override_decision_id/_hash). UPDATE/DELETE auf der Decision-Tabelle
sind per Trigger verboten (SQLite und PostgreSQL).

Revision ID: c4e9a7d2b815
Revises: a6d2e8f4c1b9
Create Date: 2026-10-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e9a7d2b815"
down_revision: Union[str, Sequence[str], None] = "a6d2e8f4c1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS trg_risk_override_decisions_no_update "
    "BEFORE UPDATE ON risk_override_decisions FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'risk_override_decisions is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_risk_override_decisions_no_delete "
    "BEFORE DELETE ON risk_override_decisions FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'risk_override_decisions is immutable'); END",
)

_PG_FUNCTION = """
CREATE OR REPLACE FUNCTION risk_override_decisions_immutable()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'risk_override_decisions is immutable';
END;
$$ LANGUAGE plpgsql
"""

_PG_TRIGGER = """
CREATE TRIGGER trg_risk_override_decisions_immutable
BEFORE UPDATE OR DELETE ON risk_override_decisions
FOR EACH ROW EXECUTE FUNCTION risk_override_decisions_immutable()
"""


def upgrade() -> None:
    op.create_table(
        "risk_override_decisions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("assessment_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=True),
        sa.Column("assessment_version", sa.Integer(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("previous_decision_id", sa.String(), nullable=True),
        sa.Column("basis_final_score_x10", sa.Integer(), nullable=False),
        sa.Column("basis_final_profile", sa.String(), nullable=True),
        sa.Column("basis_capacity_score_x10", sa.Integer(), nullable=True),
        sa.Column("basis_willingness_score_x10", sa.Integer(), nullable=True),
        sa.Column("requested_score_x10", sa.Integer(), nullable=False),
        sa.Column("requested_profile", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("client_confirmed", sa.Integer(), nullable=False),
        sa.Column("warning_delivered", sa.Integer(), nullable=False),
        sa.Column("warning_document_id", sa.String(), nullable=True),
        sa.Column("required_client_confirmation", sa.Integer(), nullable=False),
        sa.Column("required_warning", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("decided_at", sa.String(), nullable=False),
        sa.Column("rules_version", sa.String(), nullable=False),
        sa.Column("decision_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["risk_assessments.id"]),
        sa.ForeignKeyConstraint(["mandate_id"], ["mandates.id"]),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_risk_override_decision_sequence",
        "risk_override_decisions",
        ["assessment_id", "sequence_no"],
        unique=True,
    )
    op.create_index(
        "ix_risk_override_decisions_mandate",
        "risk_override_decisions",
        ["mandate_id"],
    )
    op.add_column("risk_assessments", sa.Column("override_decision_id", sa.String(), nullable=True))
    op.add_column("risk_assessments", sa.Column("override_decision_hash", sa.String(), nullable=True))

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
        op.execute("DROP TRIGGER IF EXISTS trg_risk_override_decisions_immutable ON risk_override_decisions")
        op.execute("DROP FUNCTION IF EXISTS risk_override_decisions_immutable()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_risk_override_decisions_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_risk_override_decisions_no_delete")
    op.drop_column("risk_assessments", "override_decision_hash")
    op.drop_column("risk_assessments", "override_decision_id")
    op.drop_index("ix_risk_override_decisions_mandate", table_name="risk_override_decisions")
    op.drop_index("ux_risk_override_decision_sequence", table_name="risk_override_decisions")
    op.drop_table("risk_override_decisions")
