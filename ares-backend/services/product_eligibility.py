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
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from database import new_uuid
from models.mandates import Mandate
from core import product_evidence as evidence_contract
from core import sustainability_preference as sustainability
from core.reason_codes import DomainError, ReasonCode
from models.product_eligibility import (
    ProductEligibilityRule,
    ProductEligibilityRuleSet,
    ProductEvidenceItem,
    ProductEvidenceSnapshot,
    ProductSustainabilityAttribute,
)
from models.review import Product, ProductUniverseEntry, RecommendationPosition
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
# Eligibility-Domaene; sie ist keine zweite Produktfreigabe-Engine. Regeln,
# Identitaet und Auswertung: core/product_evidence.py (eine Quelle).
# ===========================================================================
_EVIDENCE_ITEM_COLUMNS = tuple(column.name for column in ProductEvidenceItem.__table__.columns)


def _canonical_value(value):
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Nicht endlicher Dezimalwert im Produktevidenz-Payload")
        normalized = format(value, "f")
        if "." in normalized:
            normalized = normalized.rstrip("0").rstrip(".")
        return normalized or "0"
    if isinstance(value, float):
        raise ValueError("Binärfloat ist im Produktevidenz-Payload nicht zulässig")
    if isinstance(value, dict):
        normalized = {unicodedata.normalize("NFC", str(key)): _canonical_value(item) for key, item in value.items()}
        if len(normalized) != len(value):
            raise ValueError("Schlüssel des Produktevidenz-Payloads sind nach NFC nicht eindeutig")
        return normalized
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
    """Domaenengetrennter Satz-Hash (Snapshot)."""
    canonical = canonical_product_evidence_json(payload)
    digest = hashlib.sha256(evidence_contract.PRODUCT_EVIDENCE_DOMAIN + canonical.encode("utf-8")).hexdigest()
    return canonical, digest


def product_evidence_item_payload_hash(payload: dict) -> tuple[str, str]:
    canonical = canonical_product_evidence_json(payload)
    return canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evidence_product_view(product) -> dict:
    """Identitaetsfelder eines Produkts fuer ``core.product_evidence``."""
    return {
        "id": product.id, "isin": getattr(product, "isin", None),
        "internal_product_id": getattr(product, "internal_product_id", None),
        "figi": getattr(product, "figi", None),
        "share_class_figi": getattr(product, "share_class_figi", None),
    }


def _evidence_row_view(row: ProductEvidenceItem) -> dict:
    return {name: getattr(row, name) for name in _EVIDENCE_ITEM_COLUMNS}


def evidence_today() -> str:
    """Heutiges Datum in UTC -- die eine Grenze fuer gueltig-ab/gueltig-bis."""
    return datetime.now(timezone.utc).date().isoformat()


def _mandate_jurisdiction(mandate) -> str:
    return str(getattr(mandate, "jurisdiction", None) or "CH")


def _evidence_query(db: Session):
    return lambda sql, params: db.execute(text(sql), params).mappings().all()


def effective_product_evidence_items(db: Session, mandate: Mandate, product_ids) -> list[ProductEvidenceItem]:
    """Tenantgebundene Nachweiszeilen (eigener Tenant + Plattform) der Produkte."""
    ids = sorted({str(product_id) for product_id in product_ids})
    if not ids:
        return []
    return db.query(ProductEvidenceItem).filter(
        ProductEvidenceItem.product_id.in_(ids),
        ProductEvidenceItem.jurisdiction == _mandate_jurisdiction(mandate),
        or_(ProductEvidenceItem.tenant_id.is_(None), ProductEvidenceItem.tenant_id == mandate_tenant_id(mandate)),
    ).order_by(ProductEvidenceItem.id).all()


def negotiated_cost_conditions(db: Session, mandate: Mandate, product_ids) -> dict[str, int]:
    """C-COMP-02 (Vorab-Entscheid 6.5): ausgehandelte Konditionen
    (``ProductUniverseEntry.override_ter_bps``) des Mandats-Tenants
    (``mandate_tenant_id``) in der Mandatsjurisdiktion, je Produkt.

    Der Override ist KEIN Kostennachweis und veraendert den Kundenausweis nie
    selbst. Er verlangt einen tenantgebundenen, versionierten, freigegebenen
    Kostennachweis (``ProductEvidenceItem`` Art ``costs`` des Tenants, mit
    Quelle und Gueltigkeit) mit genau diesem Satz, der im Satz-Snapshot
    (``cost_snapshot_id``) gebunden wird. Fehlt er, sperrt die Auswertung mit
    ``PRODUCT_EVIDENCE_COST_MISSING`` (``core.product_evidence.
    negotiated_cost_defect``) -- weder Anwendung noch stiller Rueckfall."""
    ids = sorted({str(product_id) for product_id in product_ids})
    if not ids:
        return {}
    rows = db.query(ProductUniverseEntry.product_id, ProductUniverseEntry.override_ter_bps).filter(
        ProductUniverseEntry.tenant_id == mandate_tenant_id(mandate),
        ProductUniverseEntry.jurisdiction == _mandate_jurisdiction(mandate),
        ProductUniverseEntry.product_id.in_(ids),
        ProductUniverseEntry.deleted_at.is_(None),
        ProductUniverseEntry.override_ter_bps.isnot(None),
    ).all()
    return {str(product_id): int(bps) for product_id, bps in rows}


def evaluate_product_evidence(
    db: Session, mandate: Mandate, product: Product, *, as_of: str | None = None, rows=None,
    negotiated: dict[str, int] | None = None,
) -> dict:
    """Bewertet alle Pflichtarten für genau ein Produkt fail-closed.

    ``negotiated``: vorab gelesene ``negotiated_cost_conditions`` (sonst je
    Aufruf gelesen)."""
    today = as_of or evidence_today()
    if rows is None:
        rows = effective_product_evidence_items(db, mandate, [product.id])
    if negotiated is None:
        negotiated = negotiated_cost_conditions(db, mandate, [product.id])
    by_id = {row.id: row for row in rows}
    defects, selected = evidence_contract.evaluate_items(
        evidence_product_view(product), [_evidence_row_view(row) for row in rows],
        tenant_id=mandate_tenant_id(mandate), jurisdiction=_mandate_jurisdiction(mandate), today=today,
        negotiated_ter_bps=negotiated.get(str(product.id)),
    )
    return {
        "status": evidence_contract.STATUS_VERIFIED if not defects else defects[0].status(),
        "issues": [defect.as_dict() for defect in defects],
        "items": [by_id[item["id"]] for item in selected],
        # Zum Zeitpunkt der Bewertung eingefroren (Werte, keine ORM-Objekte):
        # Vergleichsbasis der Revalidierung unter Sperre.
        "fingerprint": evidence_contract.lifecycle_fingerprint(selected),
        "as_of": today,
    }


class ProductEvidenceContext:
    """Evidenzstand der Kandidaten eines Laufs: eine Abfrage, je Produkt eine
    Bewertung. Rangfolge und Kosten lesen nur belegte Werte."""

    def __init__(self, db: Session, mandate: Mandate, products) -> None:
        self._db, self._mandate = db, mandate
        self._rows: dict[str, list] = {}
        for row in effective_product_evidence_items(db, mandate, [p.id for p in products]):
            self._rows.setdefault(str(row.product_id), []).append(row)
        self._negotiated = negotiated_cost_conditions(db, mandate, [p.id for p in products])
        self._cache: dict[str, dict] = {}

    def _evaluation(self, product) -> dict:
        key = str(product.id)
        if key not in self._cache:
            self._cache[key] = evaluate_product_evidence(
                self._db, self._mandate, product, rows=self._rows.get(key, []), negotiated=self._negotiated,
            )
        return self._cache[key]

    def verified(self, product) -> bool:
        return not self._evaluation(product)["issues"]

    def costs(self, product) -> tuple[str, int | None]:
        """``(known|missing|not_applicable, bps)`` -- NULL ist nie 0."""
        for item in self._evaluation(product)["items"]:
            if item.evidence_kind == "costs":
                return evidence_contract.rate_terms(json.loads(item.canonical_payload_json))
        return "missing", None

    def ter_status(self, product) -> str:
        return self.costs(product)[0]

    def ter_bps(self, product) -> int | None:
        return self.costs(product)[1]


def _evidence_reason(code: str) -> ReasonCode:
    """Katalogisierter Reason-Code eines Evidenzbefunds (geschlossene, statisch
    sichtbare Abbildung; Befunde kommen aus ``core.product_evidence``)."""
    if code == ReasonCode.PRODUCT_EVIDENCE_STALE:
        return ReasonCode.PRODUCT_EVIDENCE_STALE
    if code == ReasonCode.PRODUCT_EVIDENCE_CONFLICT:
        return ReasonCode.PRODUCT_EVIDENCE_CONFLICT
    if code == ReasonCode.PRODUCT_EVIDENCE_REVOKED:
        return ReasonCode.PRODUCT_EVIDENCE_REVOKED
    if code == ReasonCode.PRODUCT_EVIDENCE_HASH_MISMATCH:
        return ReasonCode.PRODUCT_EVIDENCE_HASH_MISMATCH
    if code == ReasonCode.PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH:
        return ReasonCode.PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH
    if code == ReasonCode.PRODUCT_EVIDENCE_KID_MISSING:
        return ReasonCode.PRODUCT_EVIDENCE_KID_MISSING
    if code == ReasonCode.PRODUCT_EVIDENCE_COST_MISSING:
        return ReasonCode.PRODUCT_EVIDENCE_COST_MISSING
    if code == ReasonCode.PRODUCT_EVIDENCE_RETROCESSION_MISSING:
        return ReasonCode.PRODUCT_EVIDENCE_RETROCESSION_MISSING
    if code == ReasonCode.PRODUCT_EVIDENCE_SUITABILITY_MISSING:
        return ReasonCode.PRODUCT_EVIDENCE_SUITABILITY_MISSING
    return ReasonCode.PRODUCT_EVIDENCE_MISSING


def _raise_product_evidence(issue: dict, *, channel: str) -> None:
    raise DomainError(
        _evidence_reason(issue["reason_code"]),
        f"{issue['message']} Bitte den Produktnachweis prüfen und freigeben lassen.",
        http_status=409,
        extra={
            "channel": channel,
            "product_id": issue["product_id"],
            "evidence_kind": issue["evidence_kind"],
        },
    )


def lock_product_evidence(db: Session, mandate: Mandate, product_ids) -> list[ProductEvidenceItem]:
    """Sperrt die Nachweislinien der Produkte bis zum Commit und liest sie frisch.

    PostgreSQL: Transaktions-Advisory-Lock je Produkt (dieselbe Sperre nimmt
    die Freigabe/der Widerruf; sie deckt auch NEUE Zeilen und unter RLS die
    Plattform-Nachweise ab) plus ``SELECT ... FOR UPDATE`` der Zeilen. SQLite:
    Schreibtransaktion -- ein Schreibbefehl ohne Wirkung nimmt die
    Schreibsperre, ab dann kann keine andere Verbindung committen."""
    ids = sorted({str(product_id) for product_id in product_ids})
    if str(db.get_bind().dialect.name).startswith("postgresql"):
        for product_id in ids:
            db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"ares-product-evidence:{product_id}"},
            )
        for tenant_rows in (True, False):
            # Plattform-Zeilen sind fuer Tenants nur lesbar (RLS UPDATE-Policy):
            # dort FOR UPDATE ohne Treffer, die Advisory-Sperre schuetzt.
            query = db.query(ProductEvidenceItem.id).filter(ProductEvidenceItem.product_id.in_(ids))
            query = query.filter(
                ProductEvidenceItem.tenant_id == mandate_tenant_id(mandate) if tenant_rows
                else ProductEvidenceItem.tenant_id.is_(None)
            )
            query.order_by(ProductEvidenceItem.id).with_for_update().all()
    else:
        db.execute(text("UPDATE product_evidence_snapshots SET status = status WHERE id IS NULL"))
    db.flush()
    if not ids:
        return []
    return db.query(ProductEvidenceItem).filter(
        ProductEvidenceItem.product_id.in_(ids),
        ProductEvidenceItem.jurisdiction == _mandate_jurisdiction(mandate),
        or_(ProductEvidenceItem.tenant_id.is_(None), ProductEvidenceItem.tenant_id == mandate_tenant_id(mandate)),
    ).order_by(ProductEvidenceItem.id).populate_existing().all()


def _snapshot_issue(code: str, product_id: str | None = None, kind: str = "snapshot") -> dict:
    return evidence_contract.ProductEvidenceDefect(code, product_id, kind).as_dict()


def snapshot_run_product_evidence(
    db: Session, mandate: Mandate, run, *, channel: str = "recommendation_generate",
) -> ProductEvidenceSnapshot:
    """Bindet den vollstaendigen Evidenzsatz an den Lauf -- atomar.

    1. Bewertung aller Positionsprodukte (fail-closed).
    2. Sperre der Nachweislinien (``lock_product_evidence``).
    3. Zweite Bewertung auf den gesperrten, frisch gelesenen Zeilen; jede
       Abweichung (Widerruf, Ersatz, neuer Vorrang) bricht ab.
    4. Erst danach Snapshot-Insert.

    Der Aufrufer verwirft bei einem Fehler die ganze Transaktion."""
    db.flush()
    product_ids = sorted({str(row[0]) for row in db.query(RecommendationPosition.product_id).filter(
        RecommendationPosition.run_id == run.id,
    ).all()})
    if not product_ids:
        _raise_product_evidence(_snapshot_issue(evidence_contract.MISSING), channel=channel)
    products = db.query(Product).filter(Product.id.in_(product_ids)).order_by(Product.id).all()
    if len(products) != len(product_ids):
        known = {str(product.id) for product in products}
        gone = next(product_id for product_id in product_ids if product_id not in known)
        _raise_product_evidence(
            _snapshot_issue(evidence_contract.MISSING, gone, "instrument_identity"), channel=channel,
        )
    negotiated = negotiated_cost_conditions(db, mandate, product_ids)
    evaluations = {}
    for product in products:
        result = evaluate_product_evidence(db, mandate, product, negotiated=negotiated)
        if result["issues"]:
            _raise_product_evidence(result["issues"][0], channel=channel)
        evaluations[product.id] = result["fingerprint"]
    items = _revalidated_items(db, mandate, products, evaluations, channel=channel)
    # Die ausgehandelte Kondition wird nach der Sperre erneut gelesen; jede
    # Abweichung zur ersten Lesung ist ein veralteter Stand (fail-closed).
    if negotiated_cost_conditions(db, mandate, product_ids) != negotiated:
        _raise_product_evidence(_snapshot_issue(evidence_contract.STALE), channel=channel)
    return _persist_evidence_snapshot(db, mandate, run, product_ids, items, negotiated)


def _revalidated_items(db: Session, mandate: Mandate, products, evaluations: dict, *, channel: str) -> list[dict]:
    """Zweite, atomare Pruefung unter Sperre; liefert die sortierten Zeilen."""
    locked = [_evidence_row_view(row) for row in lock_product_evidence(db, mandate, [p.id for p in products])]
    negotiated = negotiated_cost_conditions(db, mandate, [p.id for p in products])
    selected: list[dict] = []
    for product in products:
        defects, current = evidence_contract.evaluate_items(
            evidence_product_view(product), locked, tenant_id=mandate_tenant_id(mandate),
            jurisdiction=_mandate_jurisdiction(mandate), today=evidence_today(),
            negotiated_ter_bps=negotiated.get(str(product.id)),
        )
        if defects:
            _raise_product_evidence(defects[0].as_dict(), channel=channel)
        if evidence_contract.lifecycle_fingerprint(current) != evaluations[product.id]:
            _raise_product_evidence(
                _snapshot_issue(evidence_contract.STALE, str(product.id)), channel=channel,
            )
        selected.extend(current)
    return sorted(selected, key=evidence_contract.item_sort_key)


def product_evidence_set(
    mandate: Mandate, run, product_ids: list[str], items: list[dict], negotiated: dict[str, int] | None = None,
) -> dict:
    """Sortierter Evidenzsatz eines Laufs (Payload des Satz-Hashs).

    6.3: ``dimension_snapshots`` bindet Eignung, Kosten und Interessenkonflikt
    je als typisierten, gehashten Snapshot (``bound`` oder ``not_applicable``,
    nie NULL); deren IDs stehen zusaetzlich in den Spalten
    ``eligibility_snapshot_id``/``cost_snapshot_id``/``conflict_snapshot_id``."""
    expires = sorted(item["valid_until"] for item in items if item["valid_until"])
    return {
        "schema_version": evidence_contract.PRODUCT_EVIDENCE_SCHEMA,
        "evaluator_version": evidence_contract.PRODUCT_EVIDENCE_EVALUATOR,
        "tenant_id": mandate_tenant_id(mandate),
        "mandate_id": str(mandate.id),
        "jurisdiction": _mandate_jurisdiction(mandate),
        "mandate_jurisdiction": getattr(mandate, "jurisdiction", None),  # roh (NULL bleibt NULL)
        "recommendation_run_id": str(run.id),
        "product_ids": list(product_ids),
        "items": [evidence_contract.item_binding(item) for item in items],
        "dimension_snapshots": evidence_contract.dimension_snapshots(items, negotiated),
        "as_of": evidence_today(),
        "expires_at": expires[0] if expires else None,
        "status": evidence_contract.STATUS_VERIFIED,
    }


def _persist_evidence_snapshot(
    db: Session, mandate: Mandate, run, product_ids: list[str], items: list[dict],
    negotiated: dict[str, int] | None = None,
) -> ProductEvidenceSnapshot:
    payload = product_evidence_set(mandate, run, product_ids, items, negotiated)
    dimensions = payload["dimension_snapshots"]
    canonical, digest = product_evidence_hash(payload)
    # Identischer Satz am selben Tag (z. B. Position hinzu und wieder entfernt):
    # dieselbe unveraenderliche Zeile, kein zweiter Eintrag.
    snapshot = db.query(ProductEvidenceSnapshot).filter(
        ProductEvidenceSnapshot.product_evidence_hash == digest,
    ).first()
    if snapshot is None:
        snapshot = ProductEvidenceSnapshot(
            id=new_uuid(), tenant_id=payload["tenant_id"], mandate_id=payload["mandate_id"],
            recommendation_run_id=payload["recommendation_run_id"], product_ids_json=json.dumps(product_ids),
            item_ids_json=json.dumps([item["id"] for item in payload["items"]]),
            item_hashes_json=json.dumps([item["canonical_payload_hash"] for item in payload["items"]]),
            **{column: dimensions[dimension]["snapshot_id"]
               for dimension, column in evidence_contract.DIMENSION_COLUMNS.items()},
            as_of=payload["as_of"], evaluated_at=_now_iso(), expires_at=payload["expires_at"],
            status=payload["status"], reason_codes_json="[]", canonical_payload_json=canonical,
            product_evidence_hash=digest, schema_version=payload["schema_version"],
            evaluator_version=payload["evaluator_version"], created_at=_now_iso(),
        )
        db.add(snapshot)
        db.flush()
    run.product_evidence_snapshot_id = snapshot.id
    run.product_evidence_hash = snapshot.product_evidence_hash
    run.product_evidence_status = evidence_contract.STATUS_VERIFIED
    db.flush()
    return snapshot


def _run_evidence_state(db: Session, run, *, channel: str):
    db.flush()
    defect, payload, items = evidence_contract.run_evidence_state(
        _evidence_query(db), str(run.id), today=evidence_today(),
    )
    if defect is not None:
        _raise_product_evidence(defect.as_dict(), channel=channel)
    return payload, items


def assert_run_product_evidence(
    db: Session, mandate: Mandate, run, *, channel: str,
) -> ProductEvidenceSnapshot:
    """Der gebundene Satz muss heute unveraendert wirksam sein (409 sonst)."""
    _run_evidence_state(db, run, channel=channel)
    snapshot = db.get(ProductEvidenceSnapshot, run.product_evidence_snapshot_id)
    if snapshot is None or snapshot.tenant_id != mandate_tenant_id(mandate):
        _raise_product_evidence(_snapshot_issue(evidence_contract.HASH_MISMATCH), channel=channel)
    return snapshot


def bind_run_product_evidence(db: Session, mandate: Mandate, run, *, channel: str) -> ProductEvidenceSnapshot:
    """Finalisierung: gebundenen Satz unter Sperre erneut pruefen.

    Hat sich nur die Produktmenge durch manuelle Positionen geaendert bzw. gibt
    es (manueller Entwurf) noch keinen Satz, wird atomar neu gebunden. Ist der
    Beleg eines bereits gebundenen Produkts abgelaufen, widerrufen oder ersetzt,
    ist die Empfehlung veraltet -- nie stilles Neuversiegeln."""
    db.flush()
    product_ids = sorted({str(row[0]) for row in db.query(RecommendationPosition.product_id).filter(
        RecommendationPosition.run_id == run.id,
    ).all()})
    lock_product_evidence(db, mandate, product_ids)
    snapshot = db.get(ProductEvidenceSnapshot, run.product_evidence_snapshot_id) if (
        run.product_evidence_snapshot_id
    ) else None
    if snapshot is None and not run.product_evidence_status:
        return snapshot_run_product_evidence(db, mandate, run, channel=channel)
    if snapshot is None or json.loads(snapshot.product_ids_json) == product_ids:
        return assert_run_product_evidence(db, mandate, run, channel=channel)
    if evidence_contract.stored_json_hash(
        snapshot.canonical_payload_json, domain=evidence_contract.PRODUCT_EVIDENCE_DOMAIN,
    ) != run.product_evidence_hash:
        _raise_product_evidence(_snapshot_issue(evidence_contract.HASH_MISMATCH), channel=channel)
    bound = [item for item in json.loads(snapshot.canonical_payload_json)["items"]
             if item["product_id"] in product_ids]
    rebound = snapshot_run_product_evidence(db, mandate, run, channel=channel)
    current = json.loads(rebound.canonical_payload_json)["items"]
    if any(item not in current for item in bound):
        _raise_product_evidence(_snapshot_issue(evidence_contract.STALE), channel=channel)
    return rebound


def run_product_evidence_values(
    db: Session, mandate: Mandate, run, *, channel: str,
) -> dict[str, dict[str, dict]]:
    """Nur im verifizierten Snapshot gebundene Werte (nie Stammdaten)."""
    _payload, items = _run_evidence_state(db, run, channel=channel)
    values: dict[str, dict[str, dict]] = {}
    for item in items:
        values.setdefault(str(item["product_id"]), {})[str(item["evidence_kind"])] = {
            "payload": json.loads(item["canonical_payload_json"]),
            "source_reference": item["source_reference"],
            "as_of": item["as_of"],
            "item_id": item["id"],
            "payload_hash": item["canonical_payload_hash"],
        }
    return values


# Pflege- und Freigabeweg ---------------------------------------------------


def _evidence_transition(message: str) -> DomainError:
    return DomainError(ReasonCode.PRODUCT_EVIDENCE_STATE_INVALID, message, http_status=409)


def create_product_evidence_draft(db: Session, product: Product, *, values: dict, tenant_id: str | None,
                                  actor_id: str) -> ProductEvidenceItem:
    """Entwurf; Identitaet und Pflichtwerte werden schon hier exakt geprueft."""
    identity = {"stable_instrument_id": values["stable_instrument_id"], "share_class_id": values.get("share_class_id")}
    if not evidence_contract.identity_matches(identity, evidence_product_view(product)):
        _raise_product_evidence(
            _snapshot_issue(evidence_contract.SHARE_CLASS_MISMATCH, str(product.id), values["evidence_kind"]),
            channel="product_evidence_create",
        )
    try:
        canonical, payload_hash = product_evidence_item_payload_hash(values["payload"])
    except ValueError as exc:
        raise DomainError(ReasonCode.PRODUCT_EVIDENCE_STATE_INVALID, str(exc), http_status=422) from exc
    code = evidence_contract.payload_defect_code(
        values["evidence_kind"], json.loads(canonical), values["source_reference"],
    )
    if code is not None:
        _raise_product_evidence(
            _snapshot_issue(code, str(product.id), values["evidence_kind"]), channel="product_evidence_create",
        )
    if evidence_contract.is_synthetic(values["source_type"]) and not evidence_contract.synthetic_evidence_allowed():
        raise DomainError(
            ReasonCode.PRODUCT_EVIDENCE_STATE_INVALID,
            "Synthetische Nachweise sind in der Produktivinstallation nicht zulässig.", http_status=409,
        )
    stable, share_class = evidence_contract.product_identity(evidence_product_view(product))
    if values.get("supersedes_id"):
        predecessor = db.get(ProductEvidenceItem, values["supersedes_id"])
        if (
            predecessor is None or predecessor.tenant_id != tenant_id or predecessor.status != "approved"
            or _evidence_line(predecessor) != (
                str(product.id), stable, share_class, values["jurisdiction"], values["evidence_kind"],
            )
        ):
            raise _evidence_transition(
                "Der zu ersetzende Nachweis ist nicht aktiv oder gehört nicht zu dieser Nachweislinie.")
    now = _now_iso()
    row = ProductEvidenceItem(
        id=new_uuid(), tenant_id=tenant_id, product_id=product.id, stable_instrument_id=stable,
        share_class_id=share_class, jurisdiction=values["jurisdiction"], evidence_kind=values["evidence_kind"],
        canonical_payload_json=canonical, canonical_payload_hash=payload_hash, status="draft",
        created_by=actor_id, created_at=now, updated_at=now,
        **{name: values.get(name) for name in (
            "source_type", "source_reference", "source_document_title", "source_document_version",
            "source_document_date", "retrieved_at", "source_document_sha256", "as_of", "valid_from", "valid_until",
            "note", "supersedes_id",
        )},
    )
    db.add(row)
    return row


def _evidence_line(row) -> tuple:
    return (str(row.product_id), *evidence_contract.evidence_identity(_evidence_row_view(row)), row.jurisdiction,
            row.evidence_kind)


def _lock_evidence_line(db: Session, product_id: str) -> None:
    if str(db.get_bind().dialect.name).startswith("postgresql"):
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                   {"key": f"ares-product-evidence:{product_id}"})
    else:
        db.execute(text("UPDATE product_evidence_snapshots SET status = status WHERE id IS NULL"))


def approve_product_evidence_items(db: Session, product: Product, *, seen: list[tuple[str, str]], tenant_id: str | None,
                                   actor_id: str, is_same_person, approver_ids: list[str],
                                   attestation: str | None, min_attestation_length: int) -> list[ProductEvidenceItem]:
    """Gibt GENAU die gesehene Menge ``(Nachweis, Inhalts-Hash)`` frei -- alle
    oder keine. Vier Augen; die Tier-1-Ausnahme braucht eine Begruendung und
    genau eine freigabeberechtigte Person und ersetzt nie Quelle oder Beleg."""
    _lock_evidence_line(db, str(product.id))
    if len({item_id for item_id, _hash in seen}) != len(seen):
        raise _evidence_transition("Die freizugebende Menge enthält einen Nachweis doppelt.")
    rows = {row.id: row for row in db.query(ProductEvidenceItem).filter(
        ProductEvidenceItem.id.in_([item_id for item_id, _hash in seen]),
        ProductEvidenceItem.product_id == product.id,
    ).populate_existing().all()}
    ordered: list[ProductEvidenceItem] = []
    now = _now_iso()
    for item_id, seen_hash in seen:
        row = rows.get(item_id)
        if row is None or (row.tenant_id is not None and row.tenant_id != tenant_id):
            raise _evidence_transition("Ein freizugebender Nachweis gehört nicht zu diesem Produkt.")
        if row.status != "draft":
            raise _evidence_transition("Nur ein Entwurf kann freigegeben werden. Bitte neu laden.")
        _assert_approvable(product, row, seen_hash)
        row.approval_mode = "four_eyes"
        if is_same_person(row.created_by):
            if (
                row.tenant_id is None or approver_ids != [str(actor_id)]
                or len((attestation or "").strip()) < min_attestation_length
            ):
                raise DomainError(
                    ReasonCode.PRODUCT_EVIDENCE_FOUR_EYES_REQUIRED,
                    "Der Nachweis braucht die Freigabe einer anderen Person. Die Einzelfreigabe ist nur mit "
                    "dokumentierter Begründung und genau einer freigabeberechtigten Person der Verwaltung zulässig.",
                    http_status=409,
                )
            row.approval_mode = "single_approver_attested"
        ordered.append(row)
    active = db.query(ProductEvidenceItem).filter(
        ProductEvidenceItem.product_id == product.id, ProductEvidenceItem.status == "approved",
    ).populate_existing().all()
    for row in ordered:
        if not row.supersedes_id:
            continue
        predecessor = next((r for r in active if r.id == row.supersedes_id), None)
        if (
            predecessor is None or predecessor.tenant_id != row.tenant_id
            or _evidence_line(predecessor) != _evidence_line(row)
        ):
            raise _evidence_transition("Der zu ersetzende Nachweis ist nicht mehr aktiv.")
        _close_evidence(predecessor, "retired", actor_id, now,
                        reason_code=ReasonCode.PRODUCT_EVIDENCE_SUPERSEDED.value)
        active.remove(predecessor)
    db.flush()  # Vorgaenger zuerst schliessen (Unique-Index je aktiver Linie)
    for row in ordered:
        _assert_no_overlap(row, active)
        row.status, row.approved_by, row.approved_at, row.updated_at = "approved", actor_id, now, now
        active.append(row)
    db.flush()
    return ordered


def _assert_approvable(product: Product, row: ProductEvidenceItem, seen_hash: str) -> None:
    """Gesehener Inhalt, Integritaet, Pflichtwert und Identitaet des Entwurfs."""
    code = None
    if row.canonical_payload_hash != seen_hash or (
        evidence_contract.stored_json_hash(row.canonical_payload_json) != seen_hash
    ):
        code = evidence_contract.HASH_MISMATCH
    elif not evidence_contract.identity_matches(_evidence_row_view(row), evidence_product_view(product)):
        code = evidence_contract.SHARE_CLASS_MISMATCH
    else:
        code = evidence_contract.payload_defect_code(
            row.evidence_kind, json.loads(row.canonical_payload_json), row.source_reference,
        )
    if code is not None:
        _raise_product_evidence(
            _snapshot_issue(code, str(product.id), row.evidence_kind), channel="product_evidence_approve",
        )


def _assert_no_overlap(row: ProductEvidenceItem, active: list[ProductEvidenceItem]) -> None:
    """Genau ein wirksamer Beleg je Linie und Zeitpunkt."""
    for other in active:
        if other.tenant_id != row.tenant_id or _evidence_line(other) != _evidence_line(row):
            continue
        if (other.valid_until is None or other.valid_until >= row.valid_from) and (
            row.valid_until is None or row.valid_until >= other.valid_from
        ):
            raise DomainError(
                ReasonCode.PRODUCT_EVIDENCE_CONFLICT,
                "Für diese Nachweislinie gilt im selben Zeitraum bereits ein freigegebener Nachweis. "
                "Bitte den bestehenden Nachweis ersetzen oder stilllegen.",
                http_status=409,
                extra={"product_id": str(row.product_id), "evidence_kind": row.evidence_kind},
            )


def _close_evidence(row: ProductEvidenceItem, status: str, actor_id: str, now: str, *, reason_code: str) -> None:
    row.status, row.reason_code = status, reason_code
    row.retired_or_revoked_by, row.retired_or_revoked_at, row.updated_at = actor_id, now, now


def close_product_evidence_item(db: Session, row: ProductEvidenceItem, *, status: str, reason: str,
                                actor_id: str) -> ProductEvidenceItem:
    """Stilllegen (``retired``) oder Widerrufen (``revoked``)."""
    _lock_evidence_line(db, str(row.product_id))
    db.refresh(row)
    if row.status != "approved":
        raise _evidence_transition("Nur ein freigegebener Nachweis kann geschlossen werden. Bitte neu laden.")
    _close_evidence(row, status, actor_id, _now_iso(), reason_code=reason)
    db.flush()
    return row


def product_evidence_overview(db: Session, tenant_id: str, jurisdiction: str, products) -> list[dict]:
    """Uebersicht je Produkt: verifiziert oder erster Befund (Pflegeansicht)."""
    scope = _EvidenceScope(tenant_id, jurisdiction)
    context = ProductEvidenceContext(db, scope, products)
    out = []
    for product in products:
        result = context._evaluation(product)
        out.append({
            "product_id": str(product.id), "product_name": product.product_name,
            "sub_asset_class": product.sub_asset_class,
            "stable_instrument_id": evidence_contract.product_identity(evidence_product_view(product))[0],
            "share_class_id": evidence_contract.product_identity(evidence_product_view(product))[1],
            "status": result["status"], "issues": result["issues"],
        })
    return out


DEMO_EVIDENCE_SOURCE_TYPE = "synthetic_demo"


def ensure_demo_product_evidence(db: Session, mandate: Mandate, products, *, actor_id: str, make_approver) -> int:
    """Synthetische Nachweise fuer den Demo-Systemfall -- nur ausserhalb der
    Produktivinstallation, ueber Entwurf und Vier-Augen-Freigabe einer als
    Demo gekennzeichneten, inaktiven Zweitperson. Kennzeichnung im Quellentyp:
    in der Produktivinstallation zaehlen diese Zeilen nie. Produkte ohne
    erfasste TER bleiben unbelegt (nie 0)."""
    if not evidence_contract.synthetic_evidence_allowed():
        return 0
    tenant_id, jurisdiction, today = mandate_tenant_id(mandate), _mandate_jurisdiction(mandate), evidence_today()
    products = [p for p in products if p.tenant_id in (None, tenant_id)]
    known = {str(row.product_id) for row in effective_product_evidence_items(db, mandate, [p.id for p in products])}
    products = [p for p in products if str(p.id) not in known]
    if not products:
        return 0
    now, approver = _now_iso(), make_approver()
    for product in products:
        stable, share_class = evidence_contract.product_identity(evidence_product_view(product))
        drafts = []
        for kind in evidence_contract.PRODUCT_EVIDENCE_KINDS:
            payload = {"classification": DEMO_EVIDENCE_SOURCE_TYPE, "evidence_kind": kind, "status": "synthetic"}
            rate = {"costs": product.ter_bps, "retrocession": product.retrocession_bps}.get(kind)
            if rate is not None:
                payload["value"] = int(rate)
            elif kind in ("kid", "retrocession") or (
                kind == "costs" and str(product.product_type or "").strip().casefold() == "cash"
            ):
                payload["status"] = evidence_contract.NOT_APPLICABLE
            elif kind == "costs":
                continue  # unbekannte TER wird nie erfunden
            reference = f"Synthetischer Demo-Nachweis {kind}"
            drafts.append(create_product_evidence_draft(db, product, tenant_id=tenant_id, actor_id=actor_id, values={
                "stable_instrument_id": stable, "share_class_id": share_class, "jurisdiction": jurisdiction,
                "evidence_kind": kind, "source_type": DEMO_EVIDENCE_SOURCE_TYPE, "source_reference": reference,
                "source_document_title": reference, "source_document_date": today, "retrieved_at": now,
                "source_document_sha256": hashlib.sha256(f"{reference}:{product.id}".encode()).hexdigest(),
                "payload": payload, "as_of": today, "valid_from": today,
            }))
        db.flush()
        approve_product_evidence_items(
            db, product, seen=[(row.id, row.canonical_payload_hash) for row in drafts], tenant_id=tenant_id,
            actor_id=approver.id, is_same_person=lambda creator: str(creator) == str(approver.id),
            approver_ids=[], attestation=None, min_attestation_length=1,
        )
    return len(products)


class _EvidenceScope:
    """Minimale Mandatssicht (Tenant + Jurisdiktion) fuer die Pflegeuebersicht."""

    def __init__(self, tenant_id: str, jurisdiction: str) -> None:
        self.tenant_id, self.jurisdiction = tenant_id, jurisdiction


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
    """C-COMP-02: allgemeine Produktevidenz und (N-901-02) bei aktivem Ausschluss
    der Nachhaltigkeitsnachweis; sonst ist die Position nicht hinzufuegbar (409)."""
    product_evidence = evaluate_product_evidence(db, mandate, product)
    if product_evidence["issues"]:
        _raise_product_evidence(product_evidence["issues"][0], channel="position_add")
    check = customer_exclusion_evidence(db, mandate)
    if check is not None and not check(product):
        check._raise("Position kann nicht hinzugefügt werden", [str(product.product_name or product.id)])
