"""CERT-PRODUCT-ELIGIBILITY-001 -- canonical knowledge taxonomy mapping and
the central `evaluate_product_eligibility()` eligibility core.

Source of truth: the Ares/Codex certification spec
(docs/audits/2026-10-08-product-eligibility-appropriateness-and-
finalization-certification-spec.md in the Ares audit worktree), Sections
4.2, 6, 7 and 8.

Implementation status (steps 2-5 of the spec's Section 17 order): this
module is additive and NOT YET wired into Generate, Finalize or the legacy
`services.portfolio_engine_payload._product_matches_constraints` matcher.
No production decision path calls this today. Wiring it in (steps 6-11)
requires at least one approved `ProductEligibilityRuleSet` to exist for the
real product catalog first -- see the module docstring in
models/product_eligibility.py for why that is an explicit governance
decision this module does not make on its own. Until such a rule set
exists, every call here returns `indeterminate` for every product, by
design (ELIG-DEFAULT-001's "Soll" behaviour).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy.orm import Session

from models.product_eligibility import ProductEligibilityRule
from models.review import Product
from schemas.product_eligibility import (
    DimensionStatus,
    KnowledgeCategory,
    ProductEligibilityDecisionV1,
    ServiceMode,
)

EVALUATOR_VERSION = "product-eligibility-v1.0"


def canonical_hash(payload: dict) -> str:
    """Deterministic hash for rule/snapshot evidence (Sections 11/12).

    Same convention as services.portfolio_engine's allocation_context_hash:
    sha256 over a sort_keys JSON dump.
    """
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def map_product_to_knowledge_categories(product: Product) -> list[KnowledgeCategory]:
    """Section 6.1 -- canonical, attribute-derived knowledge categories.

    Not hierarchical/exclusive: a leveraged structured derivative is
    expected to require coverage of several categories at once. Derived
    only from existing structured Product attributes (asset_class,
    product_type, sub_asset_class, descriptor text) -- never invented, and
    never from free text alone (Section 6.1: "Freitext... ist keine
    Coverage" governs what counts as EVIDENCE of knowledge, not how a
    product's own category is derived from its own catalog data).
    """
    # Lazy import (circular-import hardening, matching this module's own
    # established pattern in services.portfolio_engine_payload).
    from services.portfolio_engine import _norm_text
    from services.portfolio_engine_payload import (
        _product_is_derivative,
        _product_is_leveraged,
        _product_is_structured,
    )

    categories: set[KnowledgeCategory] = set()
    asset_class = _norm_text(product.asset_class).strip()
    product_type = _norm_text(product.product_type).strip().lower()
    sub_asset_class = _norm_text(product.sub_asset_class).strip().lower()
    is_fund_wrapper = product_type in ("etf", "fonds", "immobilienfonds")

    if asset_class == "Aktien":
        categories.add("equities")
    elif asset_class == "Obligationen":
        categories.add("bonds")
    elif asset_class == "Immobilien":
        if is_fund_wrapper:
            categories.add("real_estate_funds")
        else:
            categories.add("illiquid_products")
    elif asset_class == "Alternative":
        categories.add("alternatives")
        if sub_asset_class in ("private equity", "hedge funds"):
            categories.add("illiquid_products")
        elif sub_asset_class == "krypto":
            categories.add("complex_products")

    if is_fund_wrapper and asset_class != "Immobilien":
        categories.add("funds_etf")

    if _product_is_structured(product):
        categories.add("structured_products")
    if _product_is_derivative(product):
        categories.add("derivatives")
    if _product_is_leveraged(product):
        categories.add("leveraged_products")

    # Section 6.1 names complex_products as its own sibling category. A
    # product already flagged structured/derivative/leveraged/illiquid is
    # treated as complex too -- the simple wrapper categories (equities,
    # bonds, funds_etf, real_estate_funds, alternatives) alone never are.
    if categories & {
        "structured_products", "derivatives", "leveraged_products", "illiquid_products",
    }:
        categories.add("complex_products")

    return sorted(categories)


def resolve_active_rules_for_product(
    db: Session,
    product: Product,
    *,
    jurisdiction: str,
    tenant_id: str | None,
    as_of: str | None = None,
) -> list[ProductEligibilityRule]:
    """Section 4.3/11 -- only `approved` rules valid at `as_of` apply.

    Tenant rules and global rules are both candidates; Section 4.3 requires
    a documented priority/conflict policy before a tenant rule may override
    a global one. No such policy is documented yet, so when both a tenant
    and a global approved rule match the same product this function
    returns both and leaves the conflict to the caller, which must treat an
    unresolved multi-rule match as `indeterminate` (Section 4.2).
    """
    as_of = as_of or _now_iso()
    query = db.query(ProductEligibilityRule).filter(
        ProductEligibilityRule.status == "approved",
        ProductEligibilityRule.jurisdiction == jurisdiction,
        ProductEligibilityRule.valid_from <= as_of,
    ).filter(
        (ProductEligibilityRule.valid_to.is_(None)) | (ProductEligibilityRule.valid_to > as_of)
    ).filter(
        (ProductEligibilityRule.product_id == product.id)
        | (ProductEligibilityRule.tenant_scope == "global")
    )
    candidates = query.all()
    return [
        rule for rule in candidates
        if rule.product_id == product.id or rule.product_category_selector is not None
    ]


def evaluate_product_eligibility(
    db: Session,
    *,
    product: Product,
    service_mode: ServiceMode,
    score_bucket: int,
    aggregated_weight_bps: int,
    source_sub_allocations: Sequence[str],
    jurisdiction: str = "CH",
    tenant_id: str | None = None,
    knowledge_categories_covered: Sequence[KnowledgeCategory] | None = None,
    appropriateness_result: str | None = None,
    override_evidence: dict | None = None,
) -> ProductEligibilityDecisionV1:
    """Section 4.2/9 -- the single eligibility core Generate and Finalize
    must both consume (once wired in; see module docstring for why that
    wiring has not happened yet).

    No rule, multiple conflicting rules, or any missing required evidence
    resolves to `indeterminate`, never to a silent `eligible` (Section 4.2,
    ELIG-DEFAULT-001).
    """
    reason_codes: list[str] = []
    rules = resolve_active_rules_for_product(
        db, product, jurisdiction=jurisdiction, tenant_id=tenant_id,
    )

    if not rules:
        reason_codes.append("NO_GOVERNED_RULE")
        return ProductEligibilityDecisionV1(
            product_id=product.id,
            aggregated_weight_bps=aggregated_weight_bps,
            source_sub_allocations=list(source_sub_allocations),
            service_mode=service_mode,
            risk_band_status="indeterminate",
            service_permission_status="indeterminate",
            knowledge_status="indeterminate",
            appropriateness_status="indeterminate",
            suitability_status="indeterminate",
            override_status="not_applicable",
            position_limit_status="indeterminate",
            decision="indeterminate",
            reason_codes=reason_codes,
        )
    if len(rules) > 1:
        reason_codes.append("AMBIGUOUS_RULE_MATCH")
        return ProductEligibilityDecisionV1(
            product_id=product.id,
            aggregated_weight_bps=aggregated_weight_bps,
            source_sub_allocations=list(source_sub_allocations),
            service_mode=service_mode,
            risk_band_status="indeterminate",
            service_permission_status="indeterminate",
            knowledge_status="indeterminate",
            appropriateness_status="indeterminate",
            suitability_status="indeterminate",
            override_status="not_applicable",
            position_limit_status="indeterminate",
            decision="indeterminate",
            reason_codes=reason_codes,
        )

    rule = rules[0]

    if bool(rule.prohibited):
        reason_codes.append("PRODUCT_PROHIBITED")
        risk_band_status: DimensionStatus = "unsatisfied"
    elif int(rule.profile_from) <= int(score_bucket) <= int(rule.profile_to):
        risk_band_status = "satisfied"
    else:
        risk_band_status = "unsatisfied"
        reason_codes.append("RISK_BAND_MISMATCH")

    service_modes_allowed: list[str] = json.loads(rule.service_modes_json or "[]")
    if not service_modes_allowed:
        service_permission_status: DimensionStatus = "indeterminate"
        reason_codes.append("NO_SERVICE_MODE_DECLARED")
    elif service_mode in service_modes_allowed:
        service_permission_status = "satisfied"
    else:
        service_permission_status = "unsatisfied"
        reason_codes.append("SERVICE_MODE_NOT_PERMITTED")

    required_categories: list[str] = json.loads(rule.requires_knowledge_categories_json or "[]")
    covered = set(knowledge_categories_covered or [])
    if not required_categories:
        knowledge_status: DimensionStatus = "not_applicable"
    elif covered >= set(required_categories):
        knowledge_status = "satisfied"
    else:
        knowledge_status = "unsatisfied" if knowledge_categories_covered is not None else "indeterminate"
        reason_codes.append("KNOWLEDGE_COVERAGE_MISSING")

    if not bool(rule.requires_appropriateness):
        appropriateness_status: DimensionStatus = "not_applicable"
    elif appropriateness_result == "Angemessen" and knowledge_status == "satisfied":
        appropriateness_status = "satisfied"
    elif appropriateness_result is None:
        appropriateness_status = "indeterminate"
        reason_codes.append("APPROPRIATENESS_EVIDENCE_MISSING")
    else:
        appropriateness_status = "unsatisfied"
        reason_codes.append("APPROPRIATENESS_NOT_POSITIVE")

    # Section 4.2 lists suitability_status distinctly from risk_band_status;
    # today's only concrete suitability signal this core has is the risk
    # band itself plus whether the rule demands a dedicated suitability
    # check at all.
    if not bool(rule.requires_suitability):
        suitability_status: DimensionStatus = "not_applicable"
    else:
        suitability_status = risk_band_status

    if not bool(rule.requires_override):
        override_status: DimensionStatus = "not_applicable"
    elif override_evidence is not None:
        override_status = "satisfied"
    else:
        override_status = "indeterminate"
        reason_codes.append("OVERRIDE_EVIDENCE_MISSING")

    if rule.max_position_bps is None:
        position_limit_status: DimensionStatus = "not_applicable"
    elif int(aggregated_weight_bps) <= int(rule.max_position_bps):
        position_limit_status = "satisfied"
    else:
        position_limit_status = "unsatisfied"
        reason_codes.append("POSITION_LIMIT_EXCEEDED")

    statuses = [
        risk_band_status, service_permission_status, knowledge_status,
        appropriateness_status, suitability_status, override_status,
        position_limit_status,
    ]
    if any(status == "unsatisfied" for status in statuses):
        decision: str = "ineligible"
    elif any(status == "indeterminate" for status in statuses):
        decision = "indeterminate"
    else:
        decision = "eligible"

    rule_payload = {
        "rule_id": rule.id, "version": rule.version, "status": rule.status,
        "profile_from": rule.profile_from, "profile_to": rule.profile_to,
    }
    matched_rule_hash = canonical_hash(rule_payload)

    return ProductEligibilityDecisionV1(
        product_id=product.id,
        aggregated_weight_bps=aggregated_weight_bps,
        source_sub_allocations=list(source_sub_allocations),
        service_mode=service_mode,
        matched_rule_id=rule.id,
        matched_rule_version=rule.version,
        matched_rule_hash=matched_rule_hash,
        rule_scope=rule.tenant_scope,
        risk_band_status=risk_band_status,
        service_permission_status=service_permission_status,
        knowledge_status=knowledge_status,
        appropriateness_status=appropriateness_status,
        suitability_status=suitability_status,
        override_status=override_status,
        position_limit_bps=rule.max_position_bps,
        position_limit_status=position_limit_status,
        decision=decision,
        reason_codes=reason_codes,
    )
