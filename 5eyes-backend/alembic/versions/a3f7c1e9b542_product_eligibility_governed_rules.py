"""Add governed ProductEligibility rule/snapshot/decision/override tables (CERT-PRODUCT-ELIGIBILITY-001).

Revision ID: a3f7c1e9b542
Revises: c7d2e8f4a1b6
Create Date: 2026-10-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3f7c1e9b542"
down_revision: Union[str, Sequence[str], None] = "c7d2e8f4a1b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_eligibility_rule_sets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_scope", sa.String(), nullable=False, server_default="global"),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id")),
        sa.Column("jurisdiction", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("valid_from", sa.String(), nullable=False),
        sa.Column("valid_to", sa.String()),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String()),
        sa.Column("approved_at", sa.String()),
        sa.Column("supersedes_id", sa.String(), sa.ForeignKey("product_eligibility_rule_sets.id")),
        sa.Column("rule_set_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_product_eligibility_rule_sets_scope",
        "product_eligibility_rule_sets",
        ["tenant_scope", "tenant_id", "jurisdiction", "status"],
    )

    op.create_table(
        "product_eligibility_rules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("rule_set_id", sa.String(), sa.ForeignKey("product_eligibility_rule_sets.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id")),
        sa.Column("product_category_selector", sa.String()),
        sa.Column("tenant_scope", sa.String(), nullable=False, server_default="global"),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id")),
        sa.Column("jurisdiction", sa.String(), nullable=False),
        sa.Column("client_classifications_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("service_modes_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("profile_from", sa.Integer(), nullable=False),
        sa.Column("profile_to", sa.Integer(), nullable=False),
        sa.Column("requires_knowledge_categories_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("minimum_experience_level", sa.String()),
        sa.Column("requires_appropriateness", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requires_suitability", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requires_override", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_position_bps", sa.Integer()),
        sa.Column("prohibited", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_from", sa.String(), nullable=False),
        sa.Column("valid_to", sa.String()),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String()),
        sa.Column("approved_at", sa.String()),
        sa.Column("supersedes_id", sa.String(), sa.ForeignKey("product_eligibility_rules.id")),
        sa.Column("rule_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_product_eligibility_rules_product_status",
        "product_eligibility_rules",
        ["product_id", "status", "valid_from", "valid_to"],
    )

    op.create_table(
        "product_eligibility_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id")),
        sa.Column("client_id", sa.String(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("mandate_id", sa.String(), sa.ForeignKey("mandates.id"), nullable=False),
        sa.Column("recommendation_run_id", sa.String(), sa.ForeignKey("recommendation_runs.id"), nullable=False),
        sa.Column("target_allocation_id", sa.String()),
        sa.Column("allocation_context_hash", sa.String()),
        sa.Column("service_mode", sa.String(), nullable=False),
        sa.Column("client_classification", sa.String()),
        sa.Column("jurisdiction", sa.String(), nullable=False),
        sa.Column("assessment_id", sa.String()),
        sa.Column("risk_profile", sa.String()),
        sa.Column("knowledge_assessment_id", sa.String()),
        sa.Column("knowledge_assessment_version", sa.Integer()),
        sa.Column("knowledge_hash", sa.String()),
        sa.Column("suitability_check_id", sa.String()),
        sa.Column("appropriateness_check_id", sa.String()),
        sa.Column("product_rule_set_id", sa.String(), sa.ForeignKey("product_eligibility_rule_sets.id")),
        sa.Column("product_rule_set_version", sa.Integer()),
        sa.Column("product_rule_set_hash", sa.String()),
        sa.Column("cost_snapshot_id", sa.String()),
        sa.Column("conflict_snapshot_id", sa.String()),
        sa.Column("evaluated_positions_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("portfolio_aggregation_checks_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("overrides_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("blockers_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("warnings_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("evaluated_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String()),
        sa.Column("evaluator_version", sa.String(), nullable=False),
        sa.Column("snapshot_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_product_eligibility_snapshots_run",
        "product_eligibility_snapshots",
        ["recommendation_run_id"],
    )

    op.create_table(
        "product_eligibility_decisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("snapshot_id", sa.String(), sa.ForeignKey("product_eligibility_snapshots.id"), nullable=False),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("stable_instrument_id", sa.String()),
        sa.Column("aggregated_weight_bps", sa.Integer(), nullable=False),
        sa.Column("source_sub_allocations_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("service_mode", sa.String(), nullable=False),
        sa.Column("matched_rule_id", sa.String(), sa.ForeignKey("product_eligibility_rules.id")),
        sa.Column("matched_rule_version", sa.Integer()),
        sa.Column("matched_rule_hash", sa.String()),
        sa.Column("rule_scope", sa.String()),
        sa.Column("risk_band_status", sa.String(), nullable=False),
        sa.Column("service_permission_status", sa.String(), nullable=False),
        sa.Column("knowledge_status", sa.String(), nullable=False),
        sa.Column("appropriateness_status", sa.String(), nullable=False),
        sa.Column("suitability_status", sa.String(), nullable=False),
        sa.Column("override_status", sa.String(), nullable=False),
        sa.Column("position_limit_bps", sa.Integer()),
        sa.Column("position_limit_status", sa.String(), nullable=False),
        sa.Column("cost_evidence_status", sa.String(), nullable=False, server_default="not_evaluated"),
        sa.Column("conflict_evidence_status", sa.String(), nullable=False, server_default="not_evaluated"),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("reason_codes_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_product_eligibility_decisions_snapshot_product",
        "product_eligibility_decisions",
        ["snapshot_id", "product_id"],
    )

    op.create_table(
        "product_eligibility_overrides",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("snapshot_id", sa.String(), sa.ForeignKey("product_eligibility_snapshots.id")),
        sa.Column("rule_id", sa.String(), sa.ForeignKey("product_eligibility_rules.id")),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("recommendation_run_id", sa.String(), sa.ForeignKey("recommendation_runs.id"), nullable=False),
        sa.Column("original_decision", sa.String(), nullable=False),
        sa.Column("overridden_dimension", sa.String(), nullable=False),
        sa.Column("reason_code", sa.String(), nullable=False),
        sa.Column("reason_text", sa.String()),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=False),
        sa.Column("client_acknowledgement_id", sa.String()),
        sa.Column("warning_delivery_id", sa.String()),
        sa.Column("valid_from", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("policy_basis", sa.String()),
        sa.Column("evidence_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_product_eligibility_overrides_run_product",
        "product_eligibility_overrides",
        ["recommendation_run_id", "product_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_eligibility_overrides_run_product", table_name="product_eligibility_overrides")
    op.drop_table("product_eligibility_overrides")
    op.drop_index("ix_product_eligibility_decisions_snapshot_product", table_name="product_eligibility_decisions")
    op.drop_table("product_eligibility_decisions")
    op.drop_index("ix_product_eligibility_snapshots_run", table_name="product_eligibility_snapshots")
    op.drop_table("product_eligibility_snapshots")
    op.drop_index("ix_product_eligibility_rules_product_status", table_name="product_eligibility_rules")
    op.drop_table("product_eligibility_rules")
    op.drop_index("ix_product_eligibility_rule_sets_scope", table_name="product_eligibility_rule_sets")
    op.drop_table("product_eligibility_rule_sets")
