"""CERT-PRODUCT-ELIGIBILITY-001 -- governed product eligibility domain.

Implements the persistence layer of `ProductEligibilityRuleV1`,
`ProductEligibilitySnapshotV1`, `ProductEligibilityDecisionV1` and
`ProductEligibilityOverrideV1` from the Ares/Codex certification spec
(docs/audits/2026-10-08-product-eligibility-appropriateness-and-
finalization-certification-spec.md in the Ares audit worktree, Sections
4, 7 and 11).

This is additive and does not replace `models.review.ProductSuitability`.
The legacy table is not migrated here -- Section 15 of the spec requires an
explicit governance decision before any legacy row is promoted into an
approved rule, which is a business/compliance call, not an engineering one.
Until that decision is made and rules are actually approved here, every
product is `indeterminate` under `evaluate_product_eligibility()`
(services/product_eligibility.py) -- by design, fail-closed.
"""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from database import Base


class ProductEligibilityRuleSet(Base):
    __tablename__ = "product_eligibility_rule_sets"

    id = Column(String, primary_key=True)
    # Section 4.3 / 11: tenant_scope in {"global", "tenant"}; tenant_id only
    # set for tenant-scoped rule sets.
    tenant_scope = Column(String, nullable=False, default="global")
    tenant_id = Column(String, ForeignKey("tenants.id"))
    jurisdiction = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="draft")  # draft|approved|retired
    valid_from = Column(String, nullable=False)
    valid_to = Column(String)
    created_by = Column(String, nullable=False)
    approved_by = Column(String)
    approved_at = Column(String)
    supersedes_id = Column(String, ForeignKey("product_eligibility_rule_sets.id"))
    rule_set_hash = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    rules = relationship("ProductEligibilityRule", back_populates="rule_set")

    __table_args__ = (
        Index(
            "ix_product_eligibility_rule_sets_scope",
            "tenant_scope", "tenant_id", "jurisdiction", "status",
        ),
    )


class ProductEligibilityRule(Base):
    __tablename__ = "product_eligibility_rules"

    id = Column(String, primary_key=True)
    rule_set_id = Column(String, ForeignKey("product_eligibility_rule_sets.id"), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    # Exactly one of product_id / product_category_selector is set.
    product_id = Column(String, ForeignKey("products.id"))
    product_category_selector = Column(String)
    tenant_scope = Column(String, nullable=False, default="global")
    tenant_id = Column(String, ForeignKey("tenants.id"))
    jurisdiction = Column(String, nullable=False)
    # JSON-encoded lists (consistent with this codebase's *_json convention,
    # e.g. models.allocation.CapitalMarketAssumption.correlation_matrix_json).
    client_classifications_json = Column(String, nullable=False, default="[]")
    service_modes_json = Column(String, nullable=False, default="[]")
    profile_from = Column(Integer, nullable=False)
    profile_to = Column(Integer, nullable=False)
    requires_knowledge_categories_json = Column(String, nullable=False, default="[]")
    minimum_experience_level = Column(String)
    requires_appropriateness = Column(Integer, nullable=False, default=0)
    requires_suitability = Column(Integer, nullable=False, default=0)
    requires_override = Column(Integer, nullable=False, default=0)
    max_position_bps = Column(Integer)
    prohibited = Column(Integer, nullable=False, default=0)
    valid_from = Column(String, nullable=False)
    valid_to = Column(String)
    status = Column(String, nullable=False, default="draft")  # draft|approved|retired
    created_by = Column(String, nullable=False)
    approved_by = Column(String)
    approved_at = Column(String)
    supersedes_id = Column(String, ForeignKey("product_eligibility_rules.id"))
    rule_hash = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    rule_set = relationship("ProductEligibilityRuleSet", back_populates="rules")
    product = relationship("Product")

    __table_args__ = (
        Index(
            "ix_product_eligibility_rules_product_status",
            "product_id", "status", "valid_from", "valid_to",
        ),
    )


class ProductEligibilitySnapshot(Base):
    __tablename__ = "product_eligibility_snapshots"

    id = Column(String, primary_key=True)
    schema_version = Column(Integer, nullable=False, default=1)
    tenant_id = Column(String, ForeignKey("tenants.id"))
    client_id = Column(String, ForeignKey("clients.id"), nullable=False)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=False)
    recommendation_run_id = Column(String, ForeignKey("recommendation_runs.id"), nullable=False)
    target_allocation_id = Column(String)
    allocation_context_hash = Column(String)
    service_mode = Column(String, nullable=False)
    client_classification = Column(String)
    jurisdiction = Column(String, nullable=False)
    assessment_id = Column(String)
    risk_profile = Column(String)
    knowledge_assessment_id = Column(String)
    knowledge_assessment_version = Column(Integer)
    knowledge_hash = Column(String)
    suitability_check_id = Column(String)
    appropriateness_check_id = Column(String)
    product_rule_set_id = Column(String, ForeignKey("product_eligibility_rule_sets.id"))
    product_rule_set_version = Column(Integer)
    product_rule_set_hash = Column(String)
    cost_snapshot_id = Column(String)
    conflict_snapshot_id = Column(String)
    evaluated_positions_json = Column(String, nullable=False, default="[]")
    portfolio_aggregation_checks_json = Column(String, nullable=False, default="[]")
    overrides_json = Column(String, nullable=False, default="[]")
    blockers_json = Column(String, nullable=False, default="[]")
    warnings_json = Column(String, nullable=False, default="[]")
    verdict = Column(String, nullable=False)  # eligible|ineligible|indeterminate|stale|superseded
    evaluated_at = Column(String, nullable=False)
    expires_at = Column(String)
    evaluator_version = Column(String, nullable=False)
    snapshot_hash = Column(String, nullable=False)
    created_at = Column(String, nullable=False)

    decisions = relationship("ProductEligibilityDecision", back_populates="snapshot")

    __table_args__ = (
        Index(
            "ix_product_eligibility_snapshots_run",
            "recommendation_run_id",
        ),
    )


class ProductEligibilityDecision(Base):
    __tablename__ = "product_eligibility_decisions"

    id = Column(String, primary_key=True)
    snapshot_id = Column(String, ForeignKey("product_eligibility_snapshots.id"), nullable=False)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    stable_instrument_id = Column(String)
    aggregated_weight_bps = Column(Integer, nullable=False)
    source_sub_allocations_json = Column(String, nullable=False, default="[]")
    service_mode = Column(String, nullable=False)
    matched_rule_id = Column(String, ForeignKey("product_eligibility_rules.id"))
    matched_rule_version = Column(Integer)
    matched_rule_hash = Column(String)
    rule_scope = Column(String)
    risk_band_status = Column(String, nullable=False)
    service_permission_status = Column(String, nullable=False)
    knowledge_status = Column(String, nullable=False)
    appropriateness_status = Column(String, nullable=False)
    suitability_status = Column(String, nullable=False)
    override_status = Column(String, nullable=False)
    position_limit_bps = Column(Integer)
    position_limit_status = Column(String, nullable=False)
    cost_evidence_status = Column(String, nullable=False, default="not_evaluated")
    conflict_evidence_status = Column(String, nullable=False, default="not_evaluated")
    decision = Column(String, nullable=False)  # eligible|ineligible|indeterminate
    reason_codes_json = Column(String, nullable=False, default="[]")
    created_at = Column(String, nullable=False)

    snapshot = relationship("ProductEligibilitySnapshot", back_populates="decisions")

    __table_args__ = (
        Index(
            "ix_product_eligibility_decisions_snapshot_product",
            "snapshot_id", "product_id",
        ),
    )


class ProductEligibilityOverride(Base):
    __tablename__ = "product_eligibility_overrides"

    id = Column(String, primary_key=True)
    snapshot_id = Column(String, ForeignKey("product_eligibility_snapshots.id"))
    rule_id = Column(String, ForeignKey("product_eligibility_rules.id"))
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    recommendation_run_id = Column(String, ForeignKey("recommendation_runs.id"), nullable=False)
    original_decision = Column(String, nullable=False)
    overridden_dimension = Column(String, nullable=False)
    reason_code = Column(String, nullable=False)
    reason_text = Column(String)
    requested_by = Column(String, nullable=False)
    approved_by = Column(String, nullable=False)
    client_acknowledgement_id = Column(String)
    warning_delivery_id = Column(String)
    valid_from = Column(String, nullable=False)
    expires_at = Column(String, nullable=False)
    policy_basis = Column(String)
    evidence_hash = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    __table_args__ = (
        Index(
            "ix_product_eligibility_overrides_run_product",
            "recommendation_run_id", "product_id",
        ),
    )
