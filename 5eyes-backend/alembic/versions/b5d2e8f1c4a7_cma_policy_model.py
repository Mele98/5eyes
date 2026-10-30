"""CMA_POLICY-Modell: versionierte Policy, Komponentenledger, append-only Freigaben.

CMA-001 (Entscheidungsdokument 2026-10-27, Abschnitt 5 / Paragraf 7.4).
Legt ``cma_policies``, ``cma_policy_components`` und ``cma_policy_approvals``
an (Freigaben per Trigger unveraenderlich) und ergaenzt
``recommendation_runs.cma_policy_row_id`` (Bindung einer Finalisierung an
ihre damalige Policy). Keine Daten, keine Werte: das Finalisierungs-Gate
wird erst durch die erste Policy-Aktivierung scharf.

Revision ID: b5d2e8f1c4a7
Revises: e5b3c9d1a7f4
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b5d2e8f1c4a7"
down_revision: Union[str, Sequence[str], None] = "e5b3c9d1a7f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RUNS = "recommendation_runs"
_RUN_COLUMN = "cma_policy_row_id"

_SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS trg_cma_policy_approvals_no_update "
    "BEFORE UPDATE ON cma_policy_approvals FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'cma_policy_approvals is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_cma_policy_approvals_no_delete "
    "BEFORE DELETE ON cma_policy_approvals FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'cma_policy_approvals is immutable'); END",
)

_PG_FUNCTION = """
CREATE OR REPLACE FUNCTION cma_policy_approvals_immutable()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'cma_policy_approvals is immutable';
END;
$$ LANGUAGE plpgsql
"""

_PG_TRIGGER = """
CREATE TRIGGER trg_cma_policy_approvals_immutable
BEFORE UPDATE OR DELETE ON cma_policy_approvals
FOR EACH ROW EXECUTE FUNCTION cma_policy_approvals_immutable()
"""


def _offline() -> bool:
    return bool(getattr(op.get_context(), "as_sql", False))


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _run_column_exists() -> bool:
    return _RUN_COLUMN in {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(_RUNS)
    }


def upgrade() -> None:
    offline = _offline()
    if offline or not _has_table("cma_policies"):
        op.create_table(
            "cma_policies",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("policy_id", sa.String(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("capital_market_assumptions_id", sa.String(), nullable=False),
            sa.Column("correlation_policy_ref", sa.String(), nullable=True),
            sa.Column("valid_from", sa.String(), nullable=False),
            sa.Column("valid_until", sa.String(), nullable=True),
            sa.Column("data_as_of", sa.String(), nullable=False),
            sa.Column("base_currency", sa.String(), nullable=False),
            sa.Column("return_basis", sa.String(), nullable=False),
            sa.Column("fee_basis", sa.String(), nullable=False),
            sa.Column("method_version", sa.String(), nullable=False),
            sa.Column("sources_json", sa.String(), nullable=False),
            sa.Column("rationale", sa.String(), nullable=False),
            sa.Column("impact_report_ref", sa.String(), nullable=True),
            sa.Column("supersedes_id", sa.String(), nullable=True),
            sa.Column("expiry_rule", sa.String(), nullable=True),
            sa.Column("exception_rule", sa.String(), nullable=True),
            sa.Column("rollback_rule", sa.String(), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.Column("validated_by", sa.String(), nullable=True),
            sa.Column("validated_at", sa.String(), nullable=True),
            sa.Column("approved_at", sa.String(), nullable=True),
            sa.Column("activated_by", sa.String(), nullable=True),
            sa.Column("activated_at", sa.String(), nullable=True),
            sa.Column("retired_at", sa.String(), nullable=True),
            sa.Column("revoked_by", sa.String(), nullable=True),
            sa.Column("revoked_at", sa.String(), nullable=True),
            sa.Column("revocation_reason", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(
                ["capital_market_assumptions_id"], ["capital_market_assumptions.id"],
            ),
            sa.ForeignKeyConstraint(["supersedes_id"], ["cma_policies.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["validated_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["activated_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["revoked_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("policy_id", "version", name="uq_cma_policies_policy_version"),
        )
        op.create_index(
            "ix_cma_policies_cma_status",
            "cma_policies",
            ["capital_market_assumptions_id", "status"],
        )
    if offline or not _has_table("cma_policy_components"):
        op.create_table(
            "cma_policy_components",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("policy_row_id", sa.String(), nullable=False),
            sa.Column("asset_key", sa.String(), nullable=False),
            sa.Column("component", sa.String(), nullable=False),
            sa.Column("value_bps", sa.Integer(), nullable=False),
            sa.Column("unit", sa.String(), nullable=False),
            sa.Column("horizon_years", sa.Integer(), nullable=False),
            sa.Column("method", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("sign", sa.String(), nullable=False),
            sa.Column("confidence", sa.String(), nullable=True),
            sa.Column("range_min_bps", sa.Integer(), nullable=False),
            sa.Column("range_max_bps", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["policy_row_id"], ["cma_policies.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "policy_row_id", "asset_key", "component",
                name="uq_cma_policy_components_asset_component",
            ),
        )
    if offline or not _has_table("cma_policy_approvals"):
        op.create_table(
            "cma_policy_approvals",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("policy_row_id", sa.String(), nullable=False),
            sa.Column("approver_id", sa.String(), nullable=False),
            sa.Column("approved_at", sa.String(), nullable=False),
            sa.Column("rationale", sa.String(), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.ForeignKeyConstraint(["policy_row_id"], ["cma_policies.id"]),
            sa.ForeignKeyConstraint(["approver_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "policy_row_id", "approver_id", name="uq_cma_policy_approvals_approver",
            ),
        )
        dialect = op.get_bind().dialect.name
        if dialect == "sqlite":
            for ddl in _SQLITE_TRIGGERS:
                op.execute(ddl)
        elif dialect == "postgresql":
            op.execute(_PG_FUNCTION)
            op.execute(_PG_TRIGGER)
    if offline or not _run_column_exists():
        op.add_column(_RUNS, sa.Column(_RUN_COLUMN, sa.String(), nullable=True))


def downgrade() -> None:
    offline = _offline()
    if offline or _run_column_exists():
        op.drop_column(_RUNS, _RUN_COLUMN)
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_cma_policy_approvals_immutable ON cma_policy_approvals"
        )
        op.execute("DROP FUNCTION IF EXISTS cma_policy_approvals_immutable()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_cma_policy_approvals_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_cma_policy_approvals_no_delete")
    op.drop_table("cma_policy_approvals")
    op.drop_table("cma_policy_components")
    op.drop_index("ix_cma_policies_cma_status", table_name="cma_policies")
    op.drop_table("cma_policies")
