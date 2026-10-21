"""FinancialCoverageAttestationV1 -- append-only, gehashte Berater-Bestaetigung
der vollstaendigen Finanzdatenerfassung eines Haushalts.

RISK-CAPACITY-PLAUSIBILITY-001 Restbefund A (Codex-Closure-Review PR #653,
2026-10-20): Zeilenpraesenz ist keine Vollstaendigkeit. Die
Plausibilitaetspruefung der Risikofaehigkeit verwendet niedrige erfasste
Ausgaben nur noch dann als Konsistenzbeleg, wenn eine gueltige Bestaetigung
vorliegt. UPDATE/DELETE per Trigger verboten (SQLite und PostgreSQL).

Revision ID: f3a8d1c6b4e2
Revises: d7b3f1a9c2e4
Create Date: 2026-10-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a8d1c6b4e2"
down_revision: Union[str, Sequence[str], None] = "d7b3f1a9c2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS trg_financial_coverage_attestations_no_update "
    "BEFORE UPDATE ON financial_coverage_attestations FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'financial_coverage_attestations is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_financial_coverage_attestations_no_delete "
    "BEFORE DELETE ON financial_coverage_attestations FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'financial_coverage_attestations is immutable'); END",
)

_PG_FUNCTION = """
CREATE OR REPLACE FUNCTION financial_coverage_attestations_immutable()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'financial_coverage_attestations is immutable';
END;
$$ LANGUAGE plpgsql
"""

_PG_TRIGGER = """
CREATE TRIGGER trg_financial_coverage_attestations_immutable
BEFORE UPDATE OR DELETE ON financial_coverage_attestations
FOR EACH ROW EXECUTE FUNCTION financial_coverage_attestations_immutable()
"""


def upgrade() -> None:
    op.create_table(
        "financial_coverage_attestations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("household_persons_json", sa.String(), nullable=False),
        sa.Column("income_complete", sa.Integer(), nullable=False),
        sa.Column("expenses_complete", sa.Integer(), nullable=False),
        sa.Column("obligations_complete", sa.Integer(), nullable=False),
        sa.Column("irregular_expenses_reviewed", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("cashflow_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("cashflow_row_count", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("attested_at", sa.String(), nullable=False),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("attestation_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        # Muster audit_log/risk_override_decisions: kein FK auf
        # mandates/clients (Purge-fest), nur der Akteur verweist auf users.
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_financial_coverage_attestations_mandate",
        "financial_coverage_attestations",
        ["mandate_id", "attested_at"],
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
        op.execute(
            "DROP TRIGGER IF EXISTS trg_financial_coverage_attestations_immutable "
            "ON financial_coverage_attestations"
        )
        op.execute("DROP FUNCTION IF EXISTS financial_coverage_attestations_immutable()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_financial_coverage_attestations_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_financial_coverage_attestations_no_delete")
    op.drop_index(
        "ix_financial_coverage_attestations_mandate",
        table_name="financial_coverage_attestations",
    )
    op.drop_table("financial_coverage_attestations")
