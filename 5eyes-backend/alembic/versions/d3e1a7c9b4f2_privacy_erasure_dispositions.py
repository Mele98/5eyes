"""PRIVACY-001: Aufbewahrungsmatrix, Legal/Privacy-Rollen, Legal Holds,
Loeschvorgaenge und Dispositionen.

Fuenf neue Tabellen mit direktem ``tenant_id`` (RLS ENABLE + FORCE und die
strikte Policy folgen beim Boot ueber ``ensure_postgres_rls_policies``).
Bewusst ohne FK auf clients/mandates/users: ein Demo-Purge darf nicht an
ihnen scheitern, und der Loeschbeleg muss den Kunden ueberdauern.
Keine Seed-Daten: Fristen und Rechtsgrundlagen sind genehmigte Policy-Daten.
Neue Tabellen, kein Backfill.

Revision ID: d3e1a7c9b4f2
Revises: a9e3c5d7f1b2
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d3e1a7c9b4f2"
down_revision: Union[str, Sequence[str], None] = "a9e3c5d7f1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "privacy_retention_policies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("evidence_type", sa.String(), nullable=False),
        sa.Column("data_category", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("disposition", sa.String(), nullable=False),
        sa.Column("legal_basis", sa.Text(), nullable=True),
        sa.Column("retention_trigger", sa.String(), nullable=True),
        sa.Column("retention_months", sa.Integer(), nullable=True),
        sa.Column("matrix_json", sa.Text(), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("proposed_by", sa.String(), nullable=False),
        sa.Column("proposed_at", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approved_at", sa.String(), nullable=True),
        sa.Column("retired_at", sa.String(), nullable=True),
        sa.CheckConstraint("status IN ('PROPOSED','APPROVED','RETIRED')", name="ck_privacy_policy_status"),
        sa.CheckConstraint(
            "disposition IN ('DELETE','ANONYMIZE','PARTIAL_DELETE_MINIMIZE','RETAIN_RESTRICTED')",
            name="ck_privacy_policy_disposition",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_privacy_retention_policies_lookup", "privacy_retention_policies",
        ["tenant_id", "evidence_type", "data_category", "status"],
    )

    op.create_table(
        "privacy_role_designations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("privacy_role", sa.String(), nullable=False),
        sa.Column("granted_by", sa.String(), nullable=False),
        sa.Column("granted_at", sa.String(), nullable=False),
        sa.Column("revoked_by", sa.String(), nullable=True),
        sa.Column("revoked_at", sa.String(), nullable=True),
        sa.CheckConstraint("privacy_role IN ('LEGAL','PRIVACY')", name="ck_privacy_role_designation_role"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_privacy_role_designations_user", "privacy_role_designations", ["tenant_id", "user_id"],
    )

    op.create_table(
        "privacy_legal_holds",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("case_reference", sa.String(), nullable=False),
        sa.Column("legal_reason", sa.Text(), nullable=False),
        sa.Column("scope_json", sa.Text(), nullable=False),
        sa.Column("set_by", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approved_at", sa.String(), nullable=True),
        sa.Column("review_date", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("extension_count", sa.Integer(), nullable=False),
        sa.Column("released_by", sa.String(), nullable=True),
        sa.Column("released_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint("status IN ('PROPOSED','ACTIVE','RELEASED')", name="ck_privacy_legal_hold_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_privacy_legal_holds_client", "privacy_legal_holds", ["tenant_id", "client_id", "status"],
    )

    op.create_table(
        "privacy_erasure_cases",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("inventory_version", sa.String(), nullable=False),
        sa.Column("relationship_end_date", sa.String(), nullable=True),
        sa.Column("opened_by", sa.String(), nullable=False),
        sa.Column("opened_at", sa.String(), nullable=False),
        sa.Column("executed_by", sa.String(), nullable=True),
        sa.Column("executed_at", sa.String(), nullable=True),
        sa.Column("receipt_json", sa.Text(), nullable=True),
        sa.Column("receipt_sha256", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "status IN ('DECISION_PENDING','READY','EXECUTED','PARTIALLY_EXECUTED')",
            name="ck_privacy_erasure_case_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_privacy_erasure_cases_client", "privacy_erasure_cases", ["tenant_id", "client_id"])

    op.create_table(
        "privacy_erasure_dispositions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("table_name", sa.String(), nullable=False),
        sa.Column("data_category", sa.String(), nullable=False),
        sa.Column("evidence_type", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("rows_digest", sa.String(length=64), nullable=True),
        sa.Column("decision_status", sa.String(), nullable=False),
        sa.Column("disposition", sa.String(), nullable=True),
        sa.Column("policy_id", sa.String(), nullable=True),
        sa.Column("legal_hold_id", sa.String(), nullable=True),
        sa.Column("legal_basis", sa.Text(), nullable=True),
        sa.Column("retention_trigger", sa.String(), nullable=True),
        sa.Column("retain_until", sa.String(), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("applied_at", sa.String(), nullable=True),
        sa.Column("disposed_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "decision_status IN ('NO_DATA','DECISION_PENDING','DECIDED','APPLIED','FAILED',"
            "'DISPOSAL_DUE','DISPOSED')",
            name="ck_privacy_disposition_decision_status",
        ),
        sa.CheckConstraint(
            "disposition IS NULL OR disposition IN ('DELETE','ANONYMIZE','PARTIAL_DELETE_MINIMIZE',"
            "'RETAIN_RESTRICTED','LEGAL_HOLD')",
            name="ck_privacy_disposition_value",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_privacy_erasure_dispositions_case", "privacy_erasure_dispositions", ["case_id"])
    op.create_index(
        "ix_privacy_erasure_dispositions_client", "privacy_erasure_dispositions",
        ["tenant_id", "client_id", "evidence_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_privacy_erasure_dispositions_client", table_name="privacy_erasure_dispositions")
    op.drop_index("ix_privacy_erasure_dispositions_case", table_name="privacy_erasure_dispositions")
    op.drop_table("privacy_erasure_dispositions")
    op.drop_index("ix_privacy_erasure_cases_client", table_name="privacy_erasure_cases")
    op.drop_table("privacy_erasure_cases")
    op.drop_index("ix_privacy_legal_holds_client", table_name="privacy_legal_holds")
    op.drop_table("privacy_legal_holds")
    op.drop_index("ix_privacy_role_designations_user", table_name="privacy_role_designations")
    op.drop_table("privacy_role_designations")
    op.drop_index("ix_privacy_retention_policies_lookup", table_name="privacy_retention_policies")
    op.drop_table("privacy_retention_policies")
