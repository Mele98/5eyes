"""CERT-PRODUCT-ELIGIBILITY-001 -- V1 contract shapes.

Mirrors Sections 4, 5, 6.1 and 7 of the Ares/Codex certification spec
(docs/audits/2026-10-08-product-eligibility-appropriateness-and-
finalization-certification-spec.md in the Ares audit worktree). These are
the canonical in-process/decision shapes consumed by
services.product_eligibility.evaluate_product_eligibility(); persistence
uses models.product_eligibility, which stores the same fields flattened/
JSON-encoded for SQLite+PostgreSQL parity.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

# Section 5 -- service_mode is derived server-side from the mandate, never
# accepted as client input.
ServiceMode = Literal[
    "investment_advice",
    "portfolio_management",
    "execution_only",
    "financial_planning",
    "reporting_only",
]

# Section 13 -- verdict states.
EligibilityVerdict = Literal[
    "eligible", "ineligible", "indeterminate", "stale", "superseded",
]

# Per-dimension decision status (Section 4.2). "not_applicable" covers rules
# that do not require a given dimension at all (e.g. requires_override=0).
DimensionStatus = Literal[
    "satisfied", "unsatisfied", "indeterminate", "not_applicable",
]

RuleSetStatus = Literal["draft", "approved", "retired"]

TenantScope = Literal["global", "tenant"]

# Section 6.1 -- canonical knowledge/product category taxonomy. Free text or
# bare JSON object is not coverage.
KnowledgeCategory = Literal[
    "equities",
    "bonds",
    "funds_etf",
    "real_estate_funds",
    "alternatives",
    "structured_products",
    "derivatives",
    "leveraged_products",
    "illiquid_products",
    "complex_products",
]


class ProductEligibilityRuleV1(BaseModel):
    rule_id: str
    rule_set_id: str
    version: int
    tenant_scope: TenantScope
    tenant_id: Optional[str] = None
    jurisdiction: str
    client_classifications: list[str] = []
    service_modes: list[ServiceMode] = []
    product_id: Optional[str] = None
    product_category_selector: Optional[str] = None
    profile_from: int
    profile_to: int
    requires_knowledge_categories: list[KnowledgeCategory] = []
    minimum_experience_level: Optional[str] = None
    requires_appropriateness: bool = False
    requires_suitability: bool = False
    requires_override: bool = False
    max_position_bps: Optional[int] = None
    prohibited: bool = False
    valid_from: str
    valid_to: Optional[str] = None
    status: RuleSetStatus
    created_by: str
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    supersedes_id: Optional[str] = None
    rule_hash: str


class ProductEligibilityDecisionV1(BaseModel):
    product_id: str
    stable_instrument_id: Optional[str] = None
    aggregated_weight_bps: int
    source_sub_allocations: list[str] = []
    service_mode: ServiceMode
    matched_rule_id: Optional[str] = None
    matched_rule_version: Optional[int] = None
    matched_rule_hash: Optional[str] = None
    rule_scope: Optional[str] = None
    risk_band_status: DimensionStatus
    service_permission_status: DimensionStatus
    knowledge_status: DimensionStatus
    appropriateness_status: DimensionStatus
    suitability_status: DimensionStatus
    override_status: DimensionStatus
    position_limit_bps: Optional[int] = None
    position_limit_status: DimensionStatus
    cost_evidence_status: DimensionStatus = "not_applicable"
    conflict_evidence_status: DimensionStatus = "not_applicable"
    decision: Literal["eligible", "ineligible", "indeterminate"]
    reason_codes: list[str] = []


class ProductEligibilitySnapshotV1(BaseModel):
    schema_version: int = 1
    snapshot_id: str
    tenant_id: Optional[str] = None
    client_id: str
    mandate_id: str
    recommendation_run_id: str
    target_allocation_id: Optional[str] = None
    allocation_context_hash: Optional[str] = None
    service_mode: ServiceMode
    client_classification: Optional[str] = None
    jurisdiction: str
    assessment_id: Optional[str] = None
    risk_profile: Optional[str] = None
    knowledge_assessment_id: Optional[str] = None
    knowledge_assessment_version: Optional[int] = None
    knowledge_hash: Optional[str] = None
    suitability_check_id: Optional[str] = None
    appropriateness_check_id: Optional[str] = None
    product_rule_set_id: Optional[str] = None
    product_rule_set_version: Optional[int] = None
    product_rule_set_hash: Optional[str] = None
    cost_snapshot_id: Optional[str] = None
    conflict_snapshot_id: Optional[str] = None
    evaluated_positions: list[ProductEligibilityDecisionV1] = []
    portfolio_aggregation_checks: list[str] = []
    overrides: list[str] = []
    blockers: list[str] = []
    warnings: list[str] = []
    verdict: EligibilityVerdict
    evaluated_at: str
    expires_at: Optional[str] = None
    evaluator_version: str
    snapshot_hash: str


class ProductEligibilityOverrideV1(BaseModel):
    override_id: str
    rule_id: str
    product_id: str
    recommendation_run_id: str
    original_decision: Literal["ineligible", "indeterminate"]
    overridden_dimension: str
    reason_code: str
    reason_text: Optional[str] = None
    requested_by: str
    approved_by: str
    client_acknowledgement_id: Optional[str] = None
    warning_delivery_id: Optional[str] = None
    valid_from: str
    expires_at: str
    policy_basis: Optional[str] = None
    evidence_hash: str
