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
import re
import sys
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from database import new_uuid
from config import settings
from models.mandates import Mandate
from core import sustainability_preference as sustainability
from core.reason_codes import DomainError, ReasonCode
from models.product_eligibility import (
    PRODUCT_EVIDENCE_KINDS,
    ProductEligibilityRule,
    ProductEligibilityRuleSet,
    ProductEvidenceItem,
    ProductEvidenceSnapshot,
    ProductSustainabilityAttribute,
)
from models.review import Product, RecommendationPosition
from core.db_integrity import raise_if_check_violation
from services.product_eligibility_governance import TENANT_PRODUCT_RULE_SOURCE as _TENANT_PRODUCT_RULE_SOURCE
from services.product_eligibility_governance import parse_utc_timestamp
from services.product_eligibility_governance import effective_sustainability_threshold, evaluate_criterion
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


def _effective_at(row, cutoff) -> bool:
    """Point-in-Time: freigegeben (approved_at <= cutoff) und cutoff im
    halboffenen Fenster [valid_from, valid_to). Fehlende/unlesbare Zeitpunkte
    -> nicht wirksam (fail-closed)."""
    approved_at = parse_utc_timestamp(row.approved_at)
    valid_from = parse_utc_timestamp(row.valid_from)
    if approved_at is None or valid_from is None:
        return False
    if approved_at > cutoff or valid_from > cutoff:
        return False
    if row.valid_to is None:
        return True
    valid_to = parse_utc_timestamp(row.valid_to)
    return valid_to is not None and cutoff < valid_to


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
        instant_within_validity,
        rule_visible_to_tenant,
        selector_matches_product,
    )

    product_match = (ProductEligibilityRule.product_id == product.id) | (
        ProductEligibilityRule.product_id.is_(None)
        & ProductEligibilityRule.product_category_selector.isnot(None)
    )
    if as_of is None:
        # Aktueller Stand: Status `approved`. C-860-01: die Gueltigkeitsfenster
        # von Regel und RuleSet als echte UTC-Zeitpunkte nach dem Laden, nicht
        # als SQL-Textvergleich ('...SS+00:00' sortierte vor '...SS.000Z' --
        # eine eben geseedete Regel galt bis zum Sekundenwechsel als ungueltig).
        as_of = _now_iso()
        candidates = (
            db.query(ProductEligibilityRule, ProductEligibilityRuleSet)
            .join(
                ProductEligibilityRuleSet,
                ProductEligibilityRuleSet.id == ProductEligibilityRule.rule_set_id,
            )
            .filter(
                ProductEligibilityRule.status == "approved",
                ProductEligibilityRule.jurisdiction == jurisdiction,
                ProductEligibilityRuleSet.status == "approved",
                product_match,
            )
            .order_by(ProductEligibilityRule.profile_from, ProductEligibilityRule.id)
            .all()
        )
        rows = [
            (rule, rule_set) for rule, rule_set in candidates
            if instant_within_validity(rule.valid_from, rule.valid_to, as_of)
            and instant_within_validity(rule_set.valid_from, rule_set.valid_to, as_of)
        ]
    else:
        # Point-in-Time (N-855-6, C-855-01 / N-855-9, 2026-11): galt die Regel
        # zum Stichtag? Regel UND Regelset muessen zum Stichtag bereits
        # freigegeben gewesen sein (approved_at gesetzt und <= as_of; Legacy-
        # Zeilen ohne Freigabezeitpunkt historisch fail-closed), und as_of muss
        # im halboffenen Fenster [valid_from, valid_to) liegen. Eine durch eine
        # Folgeregel abgeloeste Regel (retired, valid_to gesetzt) zaehlt in
        # ihrem Fenster; nie freigegebene Entwuerfe nie. Alle Zeitvergleiche
        # als UTC-datetime, nicht als String ('Z' und '+00:00' gemischt).
        cutoff = parse_utc_timestamp(as_of)
        if cutoff is None:
            raise ValueError(f"as_of ist kein ISO-Zeitstempel: {as_of!r}")
        candidates = (
            db.query(ProductEligibilityRule, ProductEligibilityRuleSet)
            .join(
                ProductEligibilityRuleSet,
                ProductEligibilityRuleSet.id == ProductEligibilityRule.rule_set_id,
            )
            .filter(
                ProductEligibilityRule.status.in_(("approved", "retired")),
                ProductEligibilityRule.jurisdiction == jurisdiction,
                ProductEligibilityRuleSet.status == "approved",
                product_match,
            )
            .order_by(ProductEligibilityRule.profile_from, ProductEligibilityRule.id)
            .all()
        )
        rows = [
            (rule, rule_set) for rule, rule_set in candidates
            if (rule.status == "approved" or rule.valid_to is not None)
            and _effective_at(rule, cutoff) and _effective_at(rule_set, cutoff)
        ]
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
    except IntegrityError as exc:
        # RC-CH-1-F1: CHECK-Verstoss -> zentraler Handler (422), kein Konflikt.
        raise_if_check_violation(exc)
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
    supersedes_id: str | None = None,
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
        supersedes_id=supersedes_id,
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
# N-855-7: definiert in services.product_eligibility_governance (eine Quelle,
# dort fuer das Neu-Binden des Hashes bei der Freigabe gebraucht).
TENANT_PRODUCT_RULE_SOURCE = _TENANT_PRODUCT_RULE_SOURCE


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
    supersedes_id: str | None = None,
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
        supersedes_id=supersedes_id,
    )


# AUDIT-FIX Fondsuniversum R7/F3 (2026-11): Eignungsfelder einer Import-Zeile
# (ProductCreate) -> Spalte der governed Regel.
_IMPORT_SUITABILITY_RULE_FIELDS = (
    ("suitability_profile_from", "profile_from"),
    ("suitability_profile_to", "profile_to"),
    ("suitability_service_modes", "service_modes"),
    ("suitability_prohibited", "prohibited"),
    ("suitability_requires_appropriateness", "requires_appropriateness"),
    ("suitability_requires_override", "requires_override"),
    ("suitability_max_position_bps", "max_position_bps"),
)


def _rule_policy_view(rule: ProductEligibilityRule) -> dict:
    return {
        "profile_from": int(rule.profile_from),
        "profile_to": int(rule.profile_to),
        "service_modes": sorted(json.loads(rule.service_modes_json or "[]")),
        "prohibited": bool(rule.prohibited),
        "requires_appropriateness": bool(rule.requires_appropriateness),
        "requires_override": bool(rule.requires_override),
        "max_position_bps": rule.max_position_bps,
    }


def reauthor_tenant_product_rule_on_import(
    db: Session,
    *,
    product: Product,
    jurisdiction: str,
    created_by_user_id: str,
    row: dict,
    explicit_fields: set[str],
    now: str | None = None,
) -> tuple[ProductEligibilityRule | None, list[str]]:
    """AUDIT-FIX Fondsuniversum R7/F3 (2026-11): ein Re-Import (Upsert) hat
    die Eignungsfelder bisher still verworfen -- eine verschaerfte Eignung im
    monatlichen Upload blieb ohne Hinweis wirkungslos.

    Jetzt derselbe Weg wie beim Erfassen: weicht die Eignung der Zeile von
    der aktuell massgebenden Regel ab (offener Entwurf, sonst freigegebene
    Regel), entsteht ein neuer Regel-ENTWURF (Vier-Augen-Freigabe ueber
    POST /products/{id}/eligibility-rule/approve). Die freigegebene Regel
    bleibt bis zur Freigabe in Kraft (supersedes_id) und wird erst bei der
    Freigabe abgeloest (product_eligibility_governance.approve_rule). Ein
    offener, noch nie wirksamer Vorgaenger-Entwurf wird zurueckgezogen.
    Nicht gelieferte bzw. leere Eignungsfelder gelten als "unveraendert".
    Gibt (neuer Entwurf oder None, IDs der zurueckgezogenen Entwuerfe)
    zurueck; der Aufrufer protokolliert beides im Audit-Log (N-855-4)."""
    rules = (
        db.query(ProductEligibilityRule)
        .filter(
            ProductEligibilityRule.product_id == product.id,
            ProductEligibilityRule.jurisdiction == jurisdiction,
            ProductEligibilityRule.status.in_(("draft", "approved")),
        )
        .order_by(ProductEligibilityRule.created_at, ProductEligibilityRule.id)
        .all()
    )
    drafts = [rule for rule in rules if rule.status == "draft"]
    approved = [rule for rule in rules if rule.status == "approved"]
    reference = drafts[-1] if drafts else (approved[-1] if approved else None)
    current = _rule_policy_view(reference) if reference is not None else None
    desired: dict = {}
    for row_field, rule_field in _IMPORT_SUITABILITY_RULE_FIELDS:
        value = row.get(row_field)
        given = row_field in explicit_fields and value is not None
        if not given and current is not None:
            desired[rule_field] = current[rule_field]
        else:
            desired[rule_field] = sorted(value) if rule_field == "service_modes" else value
    if desired["prohibited"]:
        desired["service_modes"] = []
    elif not desired["service_modes"]:
        desired["service_modes"] = sorted(row.get("suitability_service_modes") or [])
    if current is not None and desired == current:
        return None, []
    for draft in drafts:
        draft.status = "retired"
        draft.updated_at = now or _now_iso()
    return author_tenant_product_rule(
        db,
        product=product,
        created_by_user_id=created_by_user_id,
        jurisdiction=jurisdiction,
        profile_from=desired["profile_from"],
        profile_to=desired["profile_to"],
        service_modes=list(desired["service_modes"]),
        max_position_bps=desired["max_position_bps"],
        requires_appropriateness=bool(desired["requires_appropriateness"]),
        requires_override=bool(desired["requires_override"]),
        now=now,
        supersedes_id=approved[-1].id if approved else None,
    ), [draft.id for draft in drafts]


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
    elif appropriateness_result == "Angemessen" and knowledge_status != "unsatisfied":
        # ELIG-FINAL-001 (2026-10-25): a positive check now always carries a
        # knowledge anchor (ELIG-KNOWLEDGE-001). Without required
        # categories (not_applicable) it was wrongly "unsatisfied"; an
        # unevaluated coverage (indeterminate) stays a hint, not a block
        # (owner rule "Kenntnisluecke: Hinweis, nicht Sperre"). Proven
        # missing coverage (unsatisfied) still blocks.
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


# ===========================================================================
# C-COMP-02 -- Product-Evidence v1. Diese Logik erweitert bewusst dieselbe
# Eligibility-Domaene; sie ist keine zweite Produktfreigabe-Engine.
# ===========================================================================
PRODUCT_EVIDENCE_SCHEMA = "ares-product-evidence/v1"
PRODUCT_EVIDENCE_EVALUATOR = "ares-product-evidence/1"
_PRODUCT_EVIDENCE_DOMAIN = b"ares-product-evidence/v1\n"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_KIND_REASON = {
    "kid": ReasonCode.PRODUCT_EVIDENCE_KID_MISSING,
    "costs": ReasonCode.PRODUCT_EVIDENCE_COST_MISSING,
    "retrocession": ReasonCode.PRODUCT_EVIDENCE_RETROCESSION_MISSING,
    "suitability": ReasonCode.PRODUCT_EVIDENCE_SUITABILITY_MISSING,
}


def _canonical_value(value):
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Decimal):
        normalized = format(value, "f")
        if "." in normalized:
            normalized = normalized.rstrip("0").rstrip(".")
        return normalized or "0"
    if isinstance(value, float):
        raise ValueError("Binärfloat ist im Produktevidenz-Payload nicht zulässig")
    if isinstance(value, dict):
        return {unicodedata.normalize("NFC", str(key)): _canonical_value(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (bool, int)):
        return value
    raise ValueError(f"Nicht kanonisierbarer Typ: {type(value).__name__}")


def canonical_product_evidence_json(payload: dict) -> str:
    """UTF-8/NFC, sortierte Schlüssel, kein Whitespace, keine Floats."""
    return json.dumps(
        _canonical_value(payload), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    )


def product_evidence_hash(payload: dict) -> tuple[str, str]:
    canonical = canonical_product_evidence_json(payload)
    digest = hashlib.sha256(_PRODUCT_EVIDENCE_DOMAIN + canonical.encode("utf-8")).hexdigest()
    return canonical, digest


def product_evidence_item_payload_hash(payload: dict) -> tuple[str, str]:
    canonical = canonical_product_evidence_json(payload)
    return canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def seed_synthetic_default_catalog_evidence(
    db: Session, *, products: Sequence[Product], actor_id: str, jurisdiction: str,
    allowed_product_names: Sequence[str],
) -> None:
    """Legt klar bezeichnete Muster-Nachweise nur fuer Dev/Test an.

    Der Aufrufer muss den Laufzeitmodus pruefen. Die Funktion selbst schreibt
    ausschliesslich globale Musterkatalog-Produkte und erfindet keine externen
    Produktdaten: jeder Payload und jede Quellenreferenz ist als synthetisch
    markiert. Kundeneigene Produkte werden nie automatisch belegt.
    """
    now = _now_iso()
    today = datetime.now(timezone.utc).date().isoformat()
    allowed = frozenset(str(name) for name in allowed_product_names)
    for product in products:
        if product.tenant_id is not None or str(product.product_name) not in allowed:
            continue
        existing = {
            row[0] for row in db.query(ProductEvidenceItem.evidence_kind).filter(
                ProductEvidenceItem.product_id == product.id,
                ProductEvidenceItem.tenant_id.is_(None),
                ProductEvidenceItem.jurisdiction == jurisdiction,
                ProductEvidenceItem.status == "approved",
            ).all()
        }
        for kind in PRODUCT_EVIDENCE_KINDS:
            if kind in existing:
                continue
            payload = {
                "classification": "synthetic_dev_demo_fixture",
                "evidence_kind": kind,
                "product_id": str(product.id),
                "status": "not_applicable" if kind in {"kid", "retrocession"} else "synthetic",
            }
            if kind == "costs":
                payload["value"] = int(product.ter_bps or 0)
                payload["unit"] = "bps_per_year"
            canonical, payload_hash = product_evidence_item_payload_hash(payload)
            source_reference = f"synthetic-dev-demo:{product.id}:{kind}"
            db.add(ProductEvidenceItem(
                id=new_uuid(), tenant_id=None, product_id=product.id,
                stable_instrument_id=_product_stable_id(product),
                share_class_id=_product_share_class_id(product),
                jurisdiction=jurisdiction, evidence_kind=kind,
                source_type="synthetic_dev_demo_fixture",
                source_reference=source_reference,
                source_document_title="Synthetischer Ares-Musternachweis",
                source_document_version="ares-product-evidence-fixture/1",
                source_document_date=today, retrieved_at=now,
                source_document_sha256=hashlib.sha256(source_reference.encode("utf-8")).hexdigest(),
                canonical_payload_json=canonical, canonical_payload_hash=payload_hash,
                as_of=today, valid_from=today, valid_until=None,
                status="approved", note="Nur Development/Test; nicht fuer Kundenbetrieb.",
                created_by=actor_id, created_at=now, approved_by=actor_id,
                approved_at=now, approval_mode="single_approver_attested",
                updated_at=now,
            ))
    db.flush()


def seed_synthetic_catalog_evidence_if_allowed(
    db: Session, *, actor_id: str, jurisdiction: str,
) -> None:
    """Dev/Test-only adapter; production and packaged builds stay fail-closed."""
    if settings.app_env not in {"development", "test"} or getattr(sys, "frozen", False):
        return
    # Deferred import avoids changing the portfolio engine's module graph.
    from services.portfolio_engine import DEFAULT_CATALOG_PRODUCTS

    allowed_names = [row[0] for row in DEFAULT_CATALOG_PRODUCTS]
    products = db.query(Product).filter(
        Product.tenant_id.is_(None),
        Product.product_name.in_(allowed_names),
        Product.deleted_at.is_(None),
    ).all()
    seed_synthetic_default_catalog_evidence(
        db, products=products, actor_id=actor_id, jurisdiction=jurisdiction,
        allowed_product_names=allowed_names,
    )


def _product_stable_id(product: Product) -> str:
    return str(
        getattr(product, "isin", None)
        or getattr(product, "internal_product_id", None)
        or getattr(product, "figi", None)
        or product.id
    )


def _product_share_class_id(product: Product) -> str | None:
    value = getattr(product, "share_class_figi", None)
    return str(value) if value else None


def _evidence_issue(code, product: Product, kind: str, message: str, *, status: str) -> dict:
    return {
        "status": status,
        "reason_code": str(code),
        "product_id": str(product.id),
        "evidence_kind": kind,
        "message": message,
    }


def evaluate_product_evidence(
    db: Session, mandate: Mandate, product: Product, *, as_of: str | None = None,
) -> dict:
    """Bewertet alle Pflichtarten für genau ein Produkt fail-closed.

    Tenant-Nachweise übersteuern globale Nachweise. Mehr als ein am Stichtag
    wirksamer Nachweis derselben Präzedenz ist ein Konflikt, nie "erster gewinnt".
    """
    today = as_of or datetime.now(timezone.utc).date().isoformat()
    tenant_id = mandate_tenant_id(mandate)
    jurisdiction = str(getattr(mandate, "jurisdiction", None) or "CH")
    rows = db.query(ProductEvidenceItem).filter(
        ProductEvidenceItem.product_id == product.id,
        ProductEvidenceItem.jurisdiction == jurisdiction,
        or_(ProductEvidenceItem.tenant_id.is_(None), ProductEvidenceItem.tenant_id == tenant_id),
    ).all()
    selected: list[ProductEvidenceItem] = []
    issues: list[dict] = []
    for kind in PRODUCT_EVIDENCE_KINDS:
        kind_rows = [row for row in rows if row.evidence_kind == kind]
        tenant_rows = [row for row in kind_rows if row.tenant_id == tenant_id]
        scoped = tenant_rows if tenant_rows else [row for row in kind_rows if row.tenant_id is None]
        approved = [row for row in scoped if row.status == "approved"]
        active = [row for row in approved if row.valid_from <= today and (
            row.valid_until is None or today <= row.valid_until
        )]
        if len(active) > 1:
            issues.append(_evidence_issue(
                ReasonCode.PRODUCT_EVIDENCE_CONFLICT, product, kind,
                "Mehrere gleichzeitig gültige Produktnachweise stehen im Konflikt.",
                status="conflict",
            ))
            continue
        if not active:
            if any(row.status == "revoked" for row in scoped):
                issues.append(_evidence_issue(
                    ReasonCode.PRODUCT_EVIDENCE_REVOKED, product, kind,
                    "Der Produktnachweis wurde widerrufen.", status="revoked",
                ))
            elif approved:
                issues.append(_evidence_issue(
                    ReasonCode.PRODUCT_EVIDENCE_STALE, product, kind,
                    "Der Produktnachweis ist noch nicht oder nicht mehr gültig.", status="stale",
                ))
            else:
                reason = _KIND_REASON.get(kind, ReasonCode.PRODUCT_EVIDENCE_MISSING)
                issues.append(_evidence_issue(
                    reason, product, kind,
                    "Für das Produkt fehlt ein freigegebener Pflichtnachweis.", status="missing",
                ))
            continue
        item = active[0]
        if item.stable_instrument_id != _product_stable_id(product) or (
            _product_share_class_id(product) is not None
            and item.share_class_id != _product_share_class_id(product)
        ):
            issues.append(_evidence_issue(
                ReasonCode.PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH, product, kind,
                "Der Produktnachweis gehört nicht zur aktuellen Anteilsklasse.", status="conflict",
            ))
            continue
        try:
            parsed = json.loads(item.canonical_payload_json)
            canonical, digest = product_evidence_item_payload_hash(parsed)
        except (TypeError, ValueError, json.JSONDecodeError):
            canonical, digest = "", ""
        if (
            canonical != item.canonical_payload_json
            or digest != item.canonical_payload_hash
            or not _HEX64.fullmatch(str(item.source_document_sha256 or ""))
        ):
            issues.append(_evidence_issue(
                ReasonCode.PRODUCT_EVIDENCE_HASH_MISMATCH, product, kind,
                "Die Integrität des Produktnachweises ist nicht belegt.", status="hash_mismatch",
            ))
            continue
        if kind in {"costs", "retrocession"} and not (
            parsed.get("value") is not None or parsed.get("status") == "not_applicable"
        ):
            reason = _KIND_REASON[kind]
            issues.append(_evidence_issue(
                reason, product, kind,
                "Der Nachweis enthält weder einen Wert noch einen belegten Nichtanwendungsstatus.",
                status="missing",
            ))
            continue
        selected.append(item)
    status = "verified" if not issues else issues[0]["status"]
    return {"status": status, "issues": issues, "items": selected, "as_of": today}


def _raise_product_evidence(issue: dict, *, channel: str) -> None:
    raise DomainError(
        issue["reason_code"],
        f"{issue['message']} Bitte den Produktnachweis prüfen und erneut freigeben.",
        http_status=409,
        extra={
            "channel": channel,
            "product_id": issue["product_id"],
            "evidence_kind": issue["evidence_kind"],
        },
    )


def snapshot_run_product_evidence(db: Session, mandate: Mandate, run) -> ProductEvidenceSnapshot:
    """Prüft nach der internen Kandidatenrechnung, vor Kundenpersistenz."""
    positions = db.query(RecommendationPosition).filter(
        RecommendationPosition.run_id == run.id,
    ).all()
    product_ids = sorted({str(position.product_id) for position in positions})
    products = db.query(Product).filter(Product.id.in_(product_ids)).all() if product_ids else []
    if len(products) != len(product_ids):
        issue = _evidence_issue(
            ReasonCode.PRODUCT_EVIDENCE_MISSING,
            type("MissingProduct", (), {"id": "unknown"})(),
            "instrument_identity", "Ein ausgewähltes Produkt ist nicht mehr verfügbar.", status="missing",
        )
        _raise_product_evidence(issue, channel="recommendation_generate")
    evaluations = [evaluate_product_evidence(db, mandate, product) for product in products]
    issues = [issue for result in evaluations for issue in result["issues"]]
    if issues:
        _raise_product_evidence(issues[0], channel="recommendation_generate")
    items = sorted(
        [item for result in evaluations for item in result["items"]],
        key=lambda item: (item.product_id, item.evidence_kind, item.id),
    )
    as_of = datetime.now(timezone.utc).date().isoformat()
    expires = sorted({item.valid_until for item in items if item.valid_until})
    payload = {
        "schema_version": PRODUCT_EVIDENCE_SCHEMA,
        "evaluator_version": PRODUCT_EVIDENCE_EVALUATOR,
        "tenant_id": mandate_tenant_id(mandate),
        "mandate_id": str(mandate.id),
        "recommendation_run_id": str(run.id),
        "product_ids": product_ids,
        "items": [{
            "id": item.id,
            "product_id": item.product_id,
            "stable_instrument_id": item.stable_instrument_id,
            "share_class_id": item.share_class_id,
            "evidence_kind": item.evidence_kind,
            "canonical_payload_hash": item.canonical_payload_hash,
            "source_document_sha256": item.source_document_sha256,
            "as_of": item.as_of,
            "valid_from": item.valid_from,
            "valid_until": item.valid_until,
            "status": item.status,
            "approved_by": item.approved_by,
            "approved_at": item.approved_at,
        } for item in items],
        "as_of": as_of,
        "expires_at": expires[0] if expires else None,
        "status": "verified",
    }
    canonical, digest = product_evidence_hash(payload)
    snapshot = ProductEvidenceSnapshot(
        id=new_uuid(), tenant_id=mandate_tenant_id(mandate), mandate_id=mandate.id,
        recommendation_run_id=run.id, product_ids_json=json.dumps(product_ids),
        item_ids_json=json.dumps([item.id for item in items]),
        item_hashes_json=json.dumps([item.canonical_payload_hash for item in items]),
        eligibility_snapshot_id=None, cost_snapshot_id=None, conflict_snapshot_id=None,
        as_of=as_of, evaluated_at=_now_iso(), expires_at=payload["expires_at"],
        status="verified", reason_codes_json="[]", canonical_payload_json=canonical,
        product_evidence_hash=digest, schema_version=PRODUCT_EVIDENCE_SCHEMA,
        evaluator_version=PRODUCT_EVIDENCE_EVALUATOR, created_at=_now_iso(),
    )
    db.add(snapshot)
    db.flush()
    run.product_evidence_snapshot_id = snapshot.id
    run.product_evidence_hash = snapshot.product_evidence_hash
    run.product_evidence_status = "verified"
    return snapshot


def assert_run_product_evidence(
    db: Session, mandate: Mandate, run, *, channel: str,
) -> ProductEvidenceSnapshot:
    snapshot_id = getattr(run, "product_evidence_snapshot_id", None)
    snapshot = db.get(ProductEvidenceSnapshot, snapshot_id) if snapshot_id else None
    if snapshot is None or getattr(run, "product_evidence_status", None) != "verified":
        _raise_product_evidence(_evidence_issue(
            ReasonCode.PRODUCT_EVIDENCE_MISSING,
            type("MissingSnapshot", (), {"id": "unknown"})(),
            "snapshot", "Der freigegebene Produktnachweis-Snapshot fehlt.", status="missing",
        ), channel=channel)
    try:
        stored_payload = json.loads(snapshot.canonical_payload_json)
        canonical, digest = product_evidence_hash(stored_payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        canonical, digest = "", ""
    if (
        canonical != snapshot.canonical_payload_json
        or digest != snapshot.product_evidence_hash
        or digest != getattr(run, "product_evidence_hash", None)
    ):
        _raise_product_evidence(_evidence_issue(
            ReasonCode.PRODUCT_EVIDENCE_HASH_MISMATCH,
            type("Snapshot", (), {"id": "unknown"})(),
            "snapshot", "Die Integrität des Produktnachweis-Snapshots ist nicht belegt.",
            status="hash_mismatch",
        ), channel=channel)
    product_ids = json.loads(snapshot.product_ids_json)
    products = db.query(Product).filter(Product.id.in_(product_ids)).all() if product_ids else []
    evaluations = [evaluate_product_evidence(db, mandate, product) for product in products]
    issues = [issue for result in evaluations for issue in result["issues"]]
    if issues:
        _raise_product_evidence(issues[0], channel=channel)
    current_items = sorted(
        [item for result in evaluations for item in result["items"]],
        key=lambda item: (item.product_id, item.evidence_kind, item.id),
    )
    if (
        [item.id for item in current_items] != json.loads(snapshot.item_ids_json)
        or [item.canonical_payload_hash for item in current_items] != json.loads(snapshot.item_hashes_json)
    ):
        _raise_product_evidence(_evidence_issue(
            ReasonCode.PRODUCT_EVIDENCE_STALE,
            type("Snapshot", (), {"id": "unknown"})(),
            "snapshot", "Die Produktevidenz wurde ersetzt; die Empfehlung ist veraltet.", status="stale",
        ), channel=channel)
    return snapshot


# ===========================================================================
# E2b Nachtrag 1 (Owner-Vertretung 2026-11-12): Durchsetzung der
# Kundenausschluesse AM PRODUKT. Ist in der aktuellen Nachhaltigkeits-
# praeferenz ein Ausschluss erfasst, waehlt die Produktselektion nur Produkte,
# deren freigegebener, am Stichtag gueltiger, fuer den Tenant sichtbarer
# Nachweis (product_sustainability_attributes, evaluate_criterion) jedes
# Ausschluss-Kriterium erfuellt. Keine Katalog-Themenzuordnung ohne Nachweis,
# unbekannt != erfuellt. Liquiditaet ist ausgenommen (gleiche Ausnahme wie
# die Abdeckungspruefung). Fehlt zur Laufzeit ein Nachweis -> fail-closed
# (SUSTAINABILITY_EVIDENCE_MISSING, kurze Meldung + Detail).
# ===========================================================================
_EVIDENCE_EXEMPT_ASSET_CLASSES = frozenset({"Liquiditaet", "Liquidität"})


class CustomerExclusionEvidence:
    """Praedikat + Belege fuer die Ausschluesse einer Erfassung."""

    def __init__(self, db: Session, mandate: Mandate, decision: dict, themes: list, as_of: str):
        self.db, self.mandate, self.themes, self.as_of = db, mandate, list(themes), as_of
        self.decision_hash = decision.get("decision_hash")
        self._tenant = getattr(mandate, "tenant_id", None)
        self._categories = {t: sustainability.EXCLUSION_EVIDENCE_CATEGORIES[t] for t in self.themes}
        self._thresholds = {
            t: effective_sustainability_threshold(db, self._tenant, c, as_of) for t, c in self._categories.items()
        }
        self._evaluate = evaluate_criterion
        self._labels = sustainability.EXCLUSION_LABELS
        self._by_product: dict[str, list] = {}
        for row in db.query(ProductSustainabilityAttribute).filter(
            ProductSustainabilityAttribute.status == "approved",
        ).all():
            self._by_product.setdefault(row.product_id, []).append(row)
        self._cache: dict[str, dict] = {}

    @staticmethod
    def exempt(product) -> bool:
        return str(getattr(product, "asset_class", None) or "").strip() in _EVIDENCE_EXEMPT_ASSET_CLASSES

    def evidence(self, product) -> dict:
        """{thema: Nachweis-ID|None} je Ausschluss (Liquiditaet: leer)."""
        if self.exempt(product):
            return {}
        if product.id not in self._cache:
            rows = self._by_product.get(product.id) or []
            found = {}
            for theme, category in self._categories.items():
                result = self._evaluate(
                    self.db, product, category, self._thresholds[theme], self.as_of,
                    tenant_id=self._tenant, attributes=rows,
                ) if rows else None
                found[theme] = result.attribute_id if result is not None and result.satisfied else None
            self._cache[product.id] = found
        return self._cache[product.id]

    def __call__(self, product) -> bool:
        return all(self.evidence(product).values())

    def satisfies(self, product, themes) -> bool:
        """Belegt das Produkt ALLE genannten Themen (Kombination am selben
        Produkt)? Liquiditaet ausgenommen."""
        if self.exempt(product):
            return True
        ev = self.evidence(product)
        return all(ev.get(t) for t in themes)

    def missing_themes(self, product) -> list:
        return [t for t, ev in self.evidence(product).items() if not ev]

    def raise_if_uncovered(self, eligible_products, sub_allocations, slot_candidates) -> None:
        """Vor der Selektion: je Slot ein belegtes Produkt nach DERSELBEN
        Slot-Regel wie die Engine (``slot_candidates``: exakt, sonst
        Anlageklasse normalisiert), sonst kurze fail-closed-Meldung."""
        missing = []
        for sub in sub_allocations:
            if str(sub.get("asset_class") or "").strip() in _EVIDENCE_EXEMPT_ASSET_CLASSES:
                continue
            if not slot_candidates(eligible_products, sub.get("sub_asset_class"), sub.get("asset_class")):
                missing.append(str(sub.get("sub_asset_class") or ""))
        if missing:
            self._raise("Produktauswahl gesperrt", missing)

    def _raise(self, label: str, subs: list) -> None:
        themes = ", ".join(self._labels[t] for t in self.themes)
        raise DomainError(
            ReasonCode.SUSTAINABILITY_EVIDENCE_MISSING,
            f"{label}: Für den Ausschluss ({themes}) fehlt ein gültiger Produktnachweis. "
            "Einstellung: Nachweise im Produktuniversum. Bitte Nachweis erneuern oder Präferenz neu erheben.",
            http_status=409,
            extra={"detail": "Betroffen: " + ", ".join(subs), "themes": list(self.themes)},
        )

    def snapshot(self, products) -> str:
        """Belege der gewaehlten Produkte (an der Empfehlung gespeichert)."""
        positions = {p.id: self.evidence(p) for p in products if not self.exempt(p)}
        return json.dumps({
            "decision_hash": self.decision_hash, "themes": list(self.themes), "as_of": self.as_of,
            "positions": positions,
            "complete": all(all(ev.values()) for ev in positions.values()),
        }, sort_keys=True)


def customer_exclusion_evidence(db: Session, mandate: Mandate, as_of: str | None = None):
    """``CustomerExclusionEvidence`` der aktuellen Erfassung oder None (keine
    Ausschluesse). Unlesbare Erfassung -> None; die Untergrenze sperrt dann
    bereits fail-closed (SUSTAINABILITY_PREFERENCE_UNREADABLE)."""
    row = db.execute(text(sustainability.CURRENT_DECISION_SQL), {"mandate_id": mandate.id}).mappings().first()
    decision = dict(row) if row else None
    try:
        themes = sustainability.effective_exclusions(decision)
    except (TypeError, ValueError):
        return None
    if not themes:
        return None
    return CustomerExclusionEvidence(
        db, mandate, decision, themes, as_of or datetime.now(timezone.utc).date().isoformat(),
    )


def assert_run_positions_evidenced(db: Session, mandate: Mandate, run, *, label: str) -> None:
    """Finalisierung: jede Position der Empfehlung muss den Ausschluss HEUTE
    belegt erfuellen (abgelaufener/zurueckgezogener Nachweis -> 409)."""
    check = customer_exclusion_evidence(db, mandate)
    if check is None:
        return
    product_ids = [p.product_id for p in db.query(RecommendationPosition).filter(
        RecommendationPosition.run_id == run.id,
    ).all()]
    products = db.query(Product).filter(Product.id.in_(product_ids)).all() if product_ids else []
    bad = [p for p in products if not check(p)]
    if bad:
        check._raise(label, [str(p.product_name or p.id) for p in bad])


RUN_EVIDENCE_NO_RUN = "no_run"


def run_exclusion_evidence_status(db: Session, mandate: Mandate, run_id) -> str:
    """N-901-02: Beleg-Status der Produktauswahl eines Laufs, HEUTE neu
    bewertet (Nachweis gueltig, nicht zurueckgezogen/abgelaufen, Tenant) --
    nie aus einem eingefrorenen Snapshot. ``none`` = kein Ausschluss aktiv,
    ``no_run`` = Ausschluss aktiv, aber kein Lauf, ``ok``/``missing``."""
    check = customer_exclusion_evidence(db, mandate)
    if check is None:
        return sustainability.RUN_EVIDENCE_NONE
    if not run_id:
        return RUN_EVIDENCE_NO_RUN
    product_ids = [r.product_id for r in db.query(RecommendationPosition).filter(
        RecommendationPosition.run_id == run_id,
    ).all()]
    if not product_ids:
        return sustainability.RUN_EVIDENCE_MISSING
    products = db.query(Product).filter(Product.id.in_(product_ids)).all()
    if len(products) != len(set(product_ids)) or not all(check(p) for p in products):
        return sustainability.RUN_EVIDENCE_MISSING
    return sustainability.RUN_EVIDENCE_OK


def assert_product_evidenced(db: Session, mandate: Mandate, product) -> None:
    """Ein Produkt muss allgemein und für Kundenausschlüsse belegt sein."""
    product_evidence = evaluate_product_evidence(db, mandate, product)
    if product_evidence["issues"]:
        _raise_product_evidence(product_evidence["issues"][0], channel="position_add")
    check = customer_exclusion_evidence(db, mandate)
    if check is not None and not check(product):
        check._raise("Position kann nicht hinzugefügt werden", [str(product.product_name or product.id)])
