"""CERT-PRODUCT-ELIGIBILITY-001 -- canonical knowledge taxonomy mapping and
the central `evaluate_product_eligibility()` eligibility core.

Source of truth: the Ares/Codex certification spec
(docs/audits/2026-10-08-product-eligibility-appropriateness-and-
finalization-certification-spec.md in the Ares audit worktree), Sections
4.2, 6, 7 and 8.

Implementation status (2026-10-09): steps 2-9 of the spec's Section 17
order. `derive_service_mode()` and `is_eligible_candidate()` below are now
wired into `services.portfolio_engine.generate_recommendation_run()` as
the sole eligibility gate for candidate selection -- the legacy
`_product_matches_constraints()` risk-band/suitability tail and its
`ignore_suitability` relaxation path have been removed (Section 19 names
that relaxation explicitly as an unacceptable non-fix). The user
authorized the governance decision for the legacy-rule migration
(2026-10-09: "migrate ProductSuitability jetzt") -- see
services/product_eligibility_legacy_migration.py, already run against the
real production database. Finalize (step 10) and Release-Certificate/
Signed-Publication/Handoff binding (step 11) are not yet wired to the
same snapshot and remain follow-up work.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy.orm import Session

from database import new_uuid
from models.mandates import Mandate
from models.product_eligibility import ProductEligibilityRule, ProductEligibilityRuleSet
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
    """Section 4.3/11 -- only `approved` rules inside an `approved`,
    currently valid RuleSet, visible to `tenant_id` and matching this
    product exactly, apply.

    ELIG-TENANT-SCOPE-001 / ELIG-RULESET-GOVERNANCE-001 /
    ELIG-CATEGORY-SELECTOR-001 (Codex-Audit, Fix 2026-10-21): before, a
    rule naming the product_id applied regardless of its tenant (a tenant-A
    policy was evidence in a tenant-B run), the RuleSet status was never
    read (an approved rule inside a draft RuleSet was active), and any
    global category-selector rule matched every product. Now:

    * tenant: a global rule without tenant_id applies everywhere; any rule
      or RuleSet carrying a tenant_id only to exactly that `tenant_id` --
      never when `tenant_id` is None (mirrors the Postgres RLS predicate,
      see product_eligibility_governance.rule_visible_to_tenant).
    * RuleSet: status `approved` and valid at `as_of`.
    * selector: exact attribute match (selector_matches_product).

    Specificity precedence (2026-10-09): an exact `product_id` rule always
    wins over a category-level one. Several rules at the same level are
    returned together; `evaluate_product_eligibility()` narrows them by risk
    band and otherwise reports `AMBIGUOUS_RULE_MATCH`.
    """
    from services.product_eligibility_governance import (
        rule_visible_to_tenant,
        selector_matches_product,
    )

    as_of = as_of or _now_iso()
    rows = (
        db.query(ProductEligibilityRule, ProductEligibilityRuleSet)
        .join(
            ProductEligibilityRuleSet,
            ProductEligibilityRuleSet.id == ProductEligibilityRule.rule_set_id,
        )
        .filter(
            ProductEligibilityRule.status == "approved",
            ProductEligibilityRule.jurisdiction == jurisdiction,
            ProductEligibilityRule.valid_from <= as_of,
            (ProductEligibilityRule.valid_to.is_(None)) | (ProductEligibilityRule.valid_to > as_of),
            ProductEligibilityRuleSet.status == "approved",
            ProductEligibilityRuleSet.valid_from <= as_of,
            (ProductEligibilityRuleSet.valid_to.is_(None)) | (ProductEligibilityRuleSet.valid_to > as_of),
            (ProductEligibilityRule.product_id == product.id)
            | (
                ProductEligibilityRule.product_id.is_(None)
                & ProductEligibilityRule.product_category_selector.isnot(None)
            ),
        )
        .order_by(ProductEligibilityRule.profile_from, ProductEligibilityRule.id)
        .all()
    )
    visible = [
        rule for rule, rule_set in rows
        if rule_visible_to_tenant(rule, rule_set, tenant_id)
    ]
    exact_matches = [rule for rule in visible if rule.product_id == product.id]
    if exact_matches:
        return exact_matches
    return [
        rule for rule in visible
        if rule.product_id is None
        and selector_matches_product(rule.product_category_selector, product)
    ]


# -- Default-catalog bootstrap rules (2026-10-09) -----------------------------
#
# services.portfolio_engine.ensure_default_products()/ensure_hedged_product_
# variants() seed the firm's own curated reference product catalog (used on
# every fresh install, demo environment and test fixture) together with a
# matching legacy `ProductSuitability` row, using the long-standing
# `_default_product_risk_band()` policy. That policy has run unattributed
# (ProductSuitability has no created_by/approved_by column at all) since
# before this certification package existed -- it is bootstrap/fixture
# data, not a per-product compliance decision about a specific client-
# facing product the way the Section 15 legacy migration is. Wiring
# `is_eligible_candidate()` into Generate's candidate selection (2026-10-09)
# makes a governed rule's *absence* fail-closed, so this exact catalog
# needs an equivalent governed rule the moment it is created, or Generate
# can never select any of it (confirmed by running the full suite: every
# call site that seeds through ensure_default_products() broke without
# this). The functions below port that same, already-in-force policy into
# the governed schema at the same insertion point -- they do not invent a
# new risk policy, and they deliberately do NOT cover custom/tenant-added
# products (Fondsuniversum-Erfassung/CSV-Import): those stay governed-rule-
# less and therefore `indeterminate` until a human explicitly authors a
# rule for them, which is the correct fail-closed behaviour this whole
# package exists to enforce.
#
# `created_by`/`approved_by` use an explicit, non-deceptive bootstrap
# identity rather than a real principal id -- this differs from the
# legacy-migration module's "never a synthetic system sentinel" rule on
# purpose (see that module's docstring, Section 11): that rule is about
# never *inventing* an accountable human for a retroactive compliance
# decision on live client-facing data. This path has never had a human
# accountable for it in the first place, and the label makes what it is
# obvious to any future reader/auditor rather than hiding it.
DEFAULT_CATALOG_BOOTSTRAP_IDENTITY = "bootstrap:default_product_catalog_v1"


def ensure_rule_set(
    db: Session,
    *,
    jurisdiction: str,
    authored_by: str,
    tenant_scope: str = "global",
    tenant_id: str | None = None,
    now: str | None = None,
    approved_by: str | None = None,
) -> ProductEligibilityRuleSet:
    """Find-or-create the one persistent RuleSet that rules authored by a
    given principal (`authored_by`) for a given (tenant_scope, tenant_id,
    jurisdiction) bucket belong to.

    `authored_by` is part of the lookup key (not just an attribute) so a
    bootstrap-identity RuleSet (default catalog) and a real-principal
    RuleSet for the same tenant/jurisdiction never merge into one -- each
    authoring identity gets its own RuleSet lineage.

    ELIG-GOVERNANCE-001 (2026-10-21):
    * The key is backed by a DB unique index (models/product_eligibility.py,
      ux_product_eligibility_rule_sets_lineage_*). The insert runs in a
      SAVEPOINT; losing a concurrent race (IntegrityError) re-reads the
      winner instead of failing or creating a duplicate lineage.
    * A newly created RuleSet is `approved` only when `approved_by` is given
      explicitly (default-catalog bootstrap, owner-authorized backfill);
      otherwise it starts as `draft` and needs four-eyes approval
      (services.product_eligibility_governance.approve_rule). An existing
      draft or approved lineage is reused; retired lineages are not.
    """
    from sqlalchemy import func
    from sqlalchemy.exc import IntegrityError

    def _lineage_query():
        return db.query(ProductEligibilityRuleSet).filter(
            ProductEligibilityRuleSet.tenant_scope == tenant_scope,
            ProductEligibilityRuleSet.tenant_id == tenant_id,
            ProductEligibilityRuleSet.jurisdiction == jurisdiction,
            ProductEligibilityRuleSet.created_by == authored_by,
        )

    def _find_open():
        return (
            _lineage_query()
            .filter(ProductEligibilityRuleSet.status.in_(("approved", "draft")))
            .order_by(ProductEligibilityRuleSet.version.desc())
            .first()
        )

    existing = _find_open()
    if existing is not None:
        return existing

    now = now or _now_iso()
    max_version = _lineage_query().with_entities(
        func.max(ProductEligibilityRuleSet.version)
    ).scalar()
    rule_set_payload = {
        "source": authored_by,
        "tenant_scope": tenant_scope,
        "tenant_id": tenant_id,
        "jurisdiction": jurisdiction,
    }
    rule_set = ProductEligibilityRuleSet(
        id=new_uuid(),
        tenant_scope=tenant_scope,
        tenant_id=tenant_id,
        jurisdiction=jurisdiction,
        version=int(max_version or 0) + 1,
        status="approved" if approved_by else "draft",
        valid_from=now,
        created_by=authored_by,
        approved_by=approved_by,
        approved_at=now if approved_by else None,
        rule_set_hash=canonical_hash(rule_set_payload),
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(rule_set)
            db.flush()
    except IntegrityError:
        winner = _find_open()
        if winner is None:
            raise
        return winner
    return rule_set


def ensure_default_catalog_rule_set(
    db: Session, *, jurisdiction: str, now: str | None = None,
) -> ProductEligibilityRuleSet:
    """Backward-compatible wrapper around ensure_rule_set() for the
    default-catalog bootstrap identity specifically (global scope)."""
    return ensure_rule_set(
        db,
        jurisdiction=jurisdiction,
        authored_by=DEFAULT_CATALOG_BOOTSTRAP_IDENTITY,
        tenant_scope="global",
        tenant_id=None,
        now=now,
        approved_by=DEFAULT_CATALOG_BOOTSTRAP_IDENTITY,
    )


def default_product_risk_band(product: Product) -> tuple[int, int]:
    """Suitability risk band policy, keyed by sub_asset_class/asset_class.

    Moved here 2026-10-09 (CERT-PRODUCT-ELIGIBILITY-001) from services.
    portfolio_engine._default_product_risk_band(), which is now a thin
    alias -- this is the single source of truth, reused by the default
    catalog bootstrap above AND by services.product_eligibility_
    unclassified_backfill.py for custom/tenant products so both paths can
    never drift apart.
    """
    if product.sub_asset_class in ("Aktien Schwellenlaender", "Thema Verteidigung", "Thema Fossile Energie", "Thema Tabak", "Thema Alkohol", "Thema Gluecksspiel", "Thema Kernenergie"):
        return (6, 10)
    if product.sub_asset_class in ("Private Equity", "Krypto", "Hedge Funds"):
        return (7, 10)
    if product.asset_class == "Aktien":
        return (4, 10)
    if product.asset_class == "Immobilien":
        return (4, 10)
    if product.sub_asset_class == "Obligationen Emerging":
        return (5, 10)
    return (1, 10)


def seed_default_catalog_suitability_and_rules(
    db: Session,
    *,
    products: Sequence[Product],
    jurisdiction: str,
    now: str,
) -> None:
    """Seed the legacy `ProductSuitability` row AND its governed
    `ProductEligibilityRule` counterpart for every freshly created
    default-catalog product, from the one shared risk-band policy
    (`default_product_risk_band()`).

    Shared by services.portfolio_engine.ensure_default_products() (fresh
    install / fresh test DB) and ensure_hedged_product_variants() (additive
    backfill) -- both paths previously carried a near-identical copy of
    this block, which is exactly how the two could have silently drifted
    apart (the original reason `default_product_risk_band()` was already
    shared between them).
    """
    from models.review import ProductSuitability

    rule_set = ensure_default_catalog_rule_set(db, jurisdiction=jurisdiction, now=now)
    for product in products:
        profile_from, profile_to = default_product_risk_band(product)
        max_position_bps = 2500 if product.asset_class == "Aktien" else 4000
        db.add(ProductSuitability(
            id=new_uuid(),
            product_id=product.id,
            profile_from=profile_from,
            profile_to=profile_to,
            advisory_allowed=1,
            discretionary_allowed=1,
            requires_appropriateness=0,
            requires_override=0,
            max_position_bps=max_position_bps,
            created_at=now,
            updated_at=now,
        ))
        author_default_catalog_rule(
            db,
            product=product,
            rule_set=rule_set,
            profile_from=profile_from,
            profile_to=profile_to,
            service_modes=["investment_advice", "portfolio_management"],
            max_position_bps=max_position_bps,
            now=now,
        )
    db.flush()


_SAME_AS_AUTHOR = "__same_as_author__"


def author_default_catalog_rule(
    db: Session,
    *,
    product: Product,
    rule_set: ProductEligibilityRuleSet,
    profile_from: int,
    profile_to: int,
    service_modes: list[str],
    max_position_bps: int | None,
    requires_appropriateness: bool = False,
    requires_override: bool = False,
    tenant_scope: str = "global",
    authored_by: str = DEFAULT_CATALOG_BOOTSTRAP_IDENTITY,
    source_label: str = DEFAULT_CATALOG_BOOTSTRAP_IDENTITY,
    now: str | None = None,
    approved_by: str | None = _SAME_AS_AUTHOR,
) -> ProductEligibilityRule:
    """Author one product-specific governed rule.

    `approved_by` defaults to `authored_by` (approved immediately) for the
    bootstrap/backfill callers that existed before four-eyes approval;
    `approved_by=None` authors a `draft` rule that needs
    services.product_eligibility_governance.approve_rule() by a different
    principal (ELIG-GOVERNANCE-001, used by author_tenant_product_rule()).
    `rule_hash` covers every policy-relevant field (compute_rule_hash).

    Originally written for the default-catalog bootstrap path (see module
    note above), this is the one shared rule-authoring primitive -- also
    reused by routers.review.create_product() (real advisor, tenant_scope=
    "tenant", authored_by=the creating user's id) and by services.
    product_eligibility_unclassified_backfill.py (an explicitly authorized
    backfill run, authored_by=the authorizing principal's id). Exactly one
    rule per product_id -- never a category selector -- so default-catalog,
    tenant-authored and backfilled rules can never collide with each other
    or with a Section 15 legacy-migration row (disjoint product sets by
    construction) or trigger the AMBIGUOUS_RULE_MATCH path.
    """
    from services.product_eligibility_governance import compute_rule_hash

    now = now or _now_iso()
    if approved_by == _SAME_AS_AUTHOR:
        approved_by = authored_by
    prohibited = not service_modes
    policy = dict(
        rule_set_id=rule_set.id,
        version=1,
        product_id=product.id,
        product_category_selector=None,
        tenant_scope=tenant_scope,
        tenant_id=product.tenant_id if tenant_scope == "tenant" else None,
        jurisdiction=rule_set.jurisdiction,
        client_classifications_json="[]",
        service_modes_json=json.dumps(service_modes),
        profile_from=profile_from,
        profile_to=profile_to,
        requires_knowledge_categories_json="[]",
        minimum_experience_level=None,
        requires_appropriateness=int(requires_appropriateness),
        # Consistent with the Section 15 legacy migration's own documented
        # choice: a risk-band gate IS a suitability rule.
        requires_suitability=1,
        requires_override=int(requires_override),
        max_position_bps=max_position_bps,
        prohibited=int(prohibited),
        valid_from=now,
        valid_to=None,
        supersedes_id=None,
    )
    rule = ProductEligibilityRule(
        id=new_uuid(),
        **policy,
        status="approved" if approved_by else "draft",
        created_by=authored_by,
        approved_by=approved_by,
        approved_at=now if approved_by else None,
        rule_hash=compute_rule_hash(policy, source=source_label),
        created_at=now,
        updated_at=now,
    )
    db.add(rule)
    return rule


# -- Tenant-authored custom-product rules (2026-10-09) -----------------------
#
# routers.review.create_product()/the CSV-import path let an advisor add a
# product to their own tenant's catalog (Fondsuniversum-Erfassung). Unlike
# the firm's default catalog, there is no pre-existing, already-reviewed
# risk-band policy for an arbitrary custom fund -- so unlike
# author_default_catalog_rule(), this is a REAL point-of-entry compliance
# decision made by the advisor adding the product right now, and
# created_by/approved_by MUST be that real advisor's user id (Section 11:
# "never a synthetic system sentinel" applies in full force here, unlike
# the bootstrap-catalog case above).
TENANT_PRODUCT_RULE_SOURCE = "tenant_product_creation_v1"


def author_tenant_product_rule(
    db: Session,
    *,
    product: Product,
    created_by_user_id: str,
    jurisdiction: str,
    profile_from: int,
    profile_to: int,
    service_modes: list[str],
    max_position_bps: int | None = None,
    requires_appropriateness: bool = False,
    requires_override: bool = False,
    now: str | None = None,
) -> ProductEligibilityRule:
    """Author the one tenant-scoped governed rule for a product an advisor
    just added to their own tenant's catalog, attributed to that advisor.

    ELIG-GOVERNANCE-001 (2026-10-21): the rule (and a newly created RuleSet)
    is a `draft` -- the author can no longer approve their own policy. It
    becomes effective only after a different principal approves it via
    POST /products/{id}/eligibility-rule/approve (409 for the author).
    Until then the product stays `indeterminate` (fail-closed).
    """
    rule_set = ensure_rule_set(
        db,
        jurisdiction=jurisdiction,
        authored_by=created_by_user_id,
        tenant_scope="tenant",
        tenant_id=product.tenant_id,
        now=now,
        approved_by=None,
    )
    return author_default_catalog_rule(
        db,
        product=product,
        rule_set=rule_set,
        profile_from=profile_from,
        profile_to=profile_to,
        service_modes=service_modes,
        max_position_bps=max_position_bps,
        requires_appropriateness=requires_appropriateness,
        requires_override=requires_override,
        tenant_scope="tenant",
        authored_by=created_by_user_id,
        source_label=TENANT_PRODUCT_RULE_SOURCE,
        now=now,
        approved_by=None,
    )


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
        # ELIG-RULE-RESOLUTION-001 (2026-10-21): the Section 15 migration
        # deliberately keeps non-overlapping bands of one product as separate
        # rules (e.g. 1-3 and 4-10). Exactly one of them covers the client's
        # score bucket -- that one is the applicable rule. Overlap or no
        # coverage stays ambiguous (fail-closed).
        covering = [
            candidate for candidate in rules
            if int(candidate.profile_from) <= int(score_bucket) <= int(candidate.profile_to)
        ]
        if len(covering) == 1:
            rules = covering
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

    # ELIG-GOVERNANCE-001 (2026-10-21): the decision references the exact
    # persisted rule hash (computed over every policy field at authoring
    # time), not a fresh hash over a handful of fields.
    matched_rule_hash = rule.rule_hash

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


# Section 5 -- mandate.mandate_type's four real values map 1:1 onto the
# canonical taxonomy. No "execution_only" mandate type exists in this app
# today; an unrecognized mandate_type fails closed to "reporting_only"
# (the most restrictive mapped mode -- Section 5: "unbekannter oder
# inkonsistenter Mandatstyp blockiert") rather than silently defaulting to
# the most permissive one.
_MANDATE_TYPE_TO_SERVICE_MODE: dict[str, ServiceMode] = {
    "Anlageberatung": "investment_advice",
    "Vermögensverwaltung": "portfolio_management",
    "Finanzplanung": "financial_planning",
    "Reporting only": "reporting_only",
}


def derive_service_mode(mandate: Mandate) -> ServiceMode:
    """Section 5 -- service_mode is derived server-side from the mandate,
    never accepted as client input."""
    return _MANDATE_TYPE_TO_SERVICE_MODE.get(
        str(getattr(mandate, "mandate_type", "") or ""), "reporting_only",
    )


def mandate_tenant_id(mandate: Mandate) -> str:
    """The run's tenant for rule visibility -- same resolution as the
    product pool (services.portfolio_engine_payload.
    _tenant_visible_products_query: mandate.tenant_id, DEFAULT_TENANT_ID
    fallback), so a tenant's own private products keep their own rules."""
    from models.tenant import DEFAULT_TENANT_ID

    return getattr(mandate, "tenant_id", None) or DEFAULT_TENANT_ID


def is_eligible_candidate(
    db: Session,
    product: Product,
    *,
    service_mode: ServiceMode,
    score_bucket: int,
    jurisdiction: str = "CH",
    tenant_id: str | None = None,
) -> bool:
    """The single eligibility gate Generate's candidate selection consumes
    (services.portfolio_engine.generate_recommendation_run()). Position-
    limit checking happens separately, post-aggregation, once the final
    aggregated weight per product is known -- this call always passes
    `aggregated_weight_bps=0` because that dimension is not yet decided at
    pre-aggregation candidate-selection time.

    `tenant_id` is the run's tenant (the mandate's, as for the product pool
    in _tenant_visible_products_query); tenant-scoped rules only count for
    exactly that tenant, None means global rules only.

    `indeterminate` is deliberately NOT eligible -- Section 4.2: "Kein
    Regelmatch... ergibt indeterminate und blockiert staerkere Kanaele."
    """
    decision = evaluate_product_eligibility(
        db,
        product=product,
        service_mode=service_mode,
        score_bucket=score_bucket,
        aggregated_weight_bps=0,
        source_sub_allocations=[],
        jurisdiction=jurisdiction,
        tenant_id=tenant_id,
    )
    return decision.decision == "eligible"
