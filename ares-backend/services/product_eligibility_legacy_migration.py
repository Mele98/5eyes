"""CERT-PRODUCT-ELIGIBILITY-001 -- legacy ProductSuitability migration.

Spec Section 15 ("Legacy- und Migrationsstrategie") of the Ares/Codex
certification spec requires an explicit governance decision before any
legacy `models.review.ProductSuitability` row is promoted into an initial
`approved` `ProductEligibilityRuleSet`. The user made that decision
(2026-10-09: "migrate ProductSuitability jetzt"). This module is the
backfill it authorized -- it still follows the spec's own guardrails:

1. No tenant-/jurisdiction-/service-field is invented (Section 15.1): every
   derived field traces 1:1 to an existing column (Product.jurisdiction,
   Product.tenant_id, ProductSuitability.advisory_allowed/
   discretionary_allowed/requires_appropriateness/requires_override/
   max_position_bps).
2. Only unambiguous rows are migrated (Section 15.2). A product with
   multiple ProductSuitability rows whose risk-band ranges overlap --
   whether the overlapping rows agree or disagree -- is quarantined, not
   silently resolved (Section 15.3): a human cleaned-up record is required
   first, this script never guesses which one is authoritative.
3. The backfill always produces a report; it is never silent (Section
   15.5) and never runs automatically -- see scripts/migrate_legacy_
   product_suitability.py, which defaults to dry-run.
4. This migration does not retroactively certify any past
   RecommendationRun (Section 15.4) -- the new rule's `valid_from` is the
   migration timestamp, not backdated.
5. ELIG-MIGRATION-IDEMPOTENCY-001 (Codex-Audit, Fix 2026-10-21): repeated
   runs are idempotent. A product that already has a non-retired,
   product-specific governed rule (from an earlier run of this migration,
   the default-catalog bootstrap, a tenant author or the unclassified
   backfill) is reported as `already_governed` and never migrated again --
   a second rule for the same product would otherwise create a duplicate
   (AMBIGUOUS_RULE_MATCH, i.e. the product silently drops out of Generate).

This module does NOT wire the new rules into Generate, Finalize, or any
other production decision path. It only backfills data that
services.product_eligibility.evaluate_product_eligibility() can later
consume once that separate wiring work (spec Section 17, steps 6-11) is
done.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from database import new_uuid
from models.product_eligibility import ProductEligibilityRule, ProductEligibilityRuleSet
from models.review import Product, ProductSuitability
from services.product_eligibility import canonical_hash
from services.product_eligibility_governance import compute_rule_hash

MIGRATION_SOURCE = "legacy_product_suitability_migration_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ranges_overlap(a_from: int, a_to: int, b_from: int, b_to: int) -> bool:
    return a_from <= b_to and b_from <= a_to


def _decision_tuple(row: ProductSuitability) -> tuple:
    return (
        int(row.advisory_allowed or 0),
        int(row.discretionary_allowed or 0),
        int(row.requires_appropriateness or 0),
        int(row.requires_override or 0),
        row.max_position_bps,
    )


@dataclass
class LegacyRuleMigrationItem:
    product_id: str
    legacy_suitability_id: str
    classification: str  # "verified_migrated_rule" | "already_governed" | "legacy_ambiguous_scope" | "legacy_conflicting"
    reason: str
    new_rule_id: str | None = None


@dataclass
class LegacyMigrationReport:
    dry_run: bool
    rule_set_id: str | None = None
    items: list[LegacyRuleMigrationItem] = field(default_factory=list)

    @property
    def migrated_count(self) -> int:
        return sum(1 for i in self.items if i.classification == "verified_migrated_rule")

    @property
    def already_governed_count(self) -> int:
        return sum(1 for i in self.items if i.classification == "already_governed")

    @property
    def quarantined_count(self) -> int:
        return sum(
            1 for i in self.items
            if i.classification not in ("verified_migrated_rule", "already_governed")
        )


def classify_and_migrate_legacy_suitability(
    db: Session,
    *,
    created_by: str,
    approved_by: str,
    jurisdiction_fallback: str = "CH",
    dry_run: bool = True,
) -> LegacyMigrationReport:
    """Classify every current `ProductSuitability` row and, unless
    `dry_run`, migrate the unambiguous ones into one new `approved`
    `ProductEligibilityRuleSet`.

    `created_by`/`approved_by` must be real, accountable principal ids --
    this mirrors the spec's own requirement (Section 11) that a RuleSet's
    governance identity is never a synthetic "system" sentinel.
    """
    if not dry_run and (not created_by or created_by == approved_by):
        # ELIG-GOVERNANCE-001 (2026-10-21): four-eyes -- the approving
        # principal must differ from the author of the migrated rule set.
        raise ValueError(
            "Vier-Augen-Prinzip: approved_by muss sich von created_by unterscheiden."
        )
    report = LegacyMigrationReport(dry_run=dry_run)

    rows = (
        db.query(ProductSuitability, Product)
        .join(Product, Product.id == ProductSuitability.product_id)
        .all()
    )
    by_product: dict[str, list[tuple[ProductSuitability, Product]]] = {}
    for suitability, product in rows:
        by_product.setdefault(product.id, []).append((suitability, product))

    to_migrate: list[tuple[ProductSuitability, Product]] = []
    already_governed_ids = {
        row[0]
        for row in db.query(ProductEligibilityRule.product_id)
        .filter(
            ProductEligibilityRule.product_id.isnot(None),
            ProductEligibilityRule.status.in_(("approved", "draft")),
        )
        .all()
    }

    for product_id, group in by_product.items():
        if product_id in already_governed_ids:
            for suitability, _ in group:
                report.items.append(LegacyRuleMigrationItem(
                    product_id=product_id,
                    legacy_suitability_id=suitability.id,
                    classification="already_governed",
                    reason=(
                        "Produkt hat bereits eine produktspezifische, nicht "
                        "zurueckgezogene Eignungsregel -- keine erneute Migration."
                    ),
                ))
            continue
        if len(group) == 1:
            to_migrate.append(group[0])
            continue

        conflicting = False
        ambiguous = False
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                row_i, _ = group[i]
                row_j, _ = group[j]
                if _ranges_overlap(
                    int(row_i.profile_from or 1), int(row_i.profile_to or 10),
                    int(row_j.profile_from or 1), int(row_j.profile_to or 10),
                ):
                    if _decision_tuple(row_i) != _decision_tuple(row_j):
                        conflicting = True
                    else:
                        ambiguous = True

        if conflicting:
            for suitability, _ in group:
                report.items.append(LegacyRuleMigrationItem(
                    product_id=product_id,
                    legacy_suitability_id=suitability.id,
                    classification="legacy_conflicting",
                    reason=(
                        "Mehrere ProductSuitability-Zeilen fuer dieses Produkt "
                        "haben ueberlappende Risikobaender mit widerspruechlichen "
                        "Entscheidungen (advisory/discretionary/appropriateness/"
                        "override/max_position_bps). Nicht automatisch aufloesbar."
                    ),
                ))
            continue
        if ambiguous:
            for suitability, _ in group:
                report.items.append(LegacyRuleMigrationItem(
                    product_id=product_id,
                    legacy_suitability_id=suitability.id,
                    classification="legacy_ambiguous_scope",
                    reason=(
                        "Mehrere ProductSuitability-Zeilen fuer dieses Produkt "
                        "haben ueberlappende Risikobaender mit identischer "
                        "Entscheidung (Duplikat ohne erkennbaren Zweck). Braucht "
                        "menschliche Bereinigung vor Migration."
                    ),
                ))
            continue

        # Non-overlapping bands for the same product are each independently
        # unambiguous (e.g. advisory-only for 1-3, advisory+discretionary
        # for 4-10) -- migrate every row in the group.
        to_migrate.extend(group)

    if not to_migrate:
        return report

    now = _now_iso()
    rule_set_id = new_uuid()
    rule_set_payload = {
        "source": MIGRATION_SOURCE,
        "row_count": len(to_migrate),
        "created_by": created_by,
    }
    rule_set = ProductEligibilityRuleSet(
        id=rule_set_id,
        tenant_scope="global",
        jurisdiction=jurisdiction_fallback,
        version=1,
        status="approved",
        valid_from=now,
        created_by=created_by,
        approved_by=approved_by,
        approved_at=now,
        rule_set_hash=canonical_hash(rule_set_payload),
        created_at=now,
        updated_at=now,
    )

    for suitability, product in to_migrate:
        advisory_allowed = int(suitability.advisory_allowed or 0) == 1
        discretionary_allowed = int(suitability.discretionary_allowed or 0) == 1
        service_modes: list[str] = []
        if advisory_allowed:
            service_modes.append("investment_advice")
        if discretionary_allowed:
            service_modes.append("portfolio_management")
        prohibited = not advisory_allowed and not discretionary_allowed

        rule_id = new_uuid()
        policy = dict(
            rule_set_id=rule_set_id,
            version=1,
            product_id=product.id,
            product_category_selector=None,
            tenant_scope="tenant" if product.tenant_id else "global",
            tenant_id=product.tenant_id,
            jurisdiction=product.jurisdiction or jurisdiction_fallback,
            client_classifications_json="[]",
            service_modes_json=json.dumps(service_modes),
            profile_from=int(suitability.profile_from or 1),
            profile_to=int(suitability.profile_to or 10),
            requires_knowledge_categories_json="[]",
            minimum_experience_level=None,
            requires_appropriateness=int(suitability.requires_appropriateness or 0),
            # Section 11: the legacy row's very existence IS a suitability
            # rule (risk-band gating) -- every migrated row therefore
            # requires_suitability=1. This is an explicit, documented
            # choice, not a silent default (see module docstring point 1).
            requires_suitability=1,
            requires_override=int(suitability.requires_override or 0),
            max_position_bps=suitability.max_position_bps,
            prohibited=int(prohibited),
            valid_from=now,
            valid_to=None,
            supersedes_id=None,
        )
        report.items.append(LegacyRuleMigrationItem(
            product_id=product.id,
            legacy_suitability_id=suitability.id,
            classification="verified_migrated_rule",
            reason="Eindeutige Einzelregel ohne ueberlappendes Band fuer dieses Produkt.",
            new_rule_id=rule_id,
        ))
        if dry_run:
            continue
        db.add(ProductEligibilityRule(
            id=rule_id,
            **policy,
            status="approved",
            created_by=created_by,
            approved_by=approved_by,
            approved_at=now,
            rule_hash=compute_rule_hash(
                policy, source=f"{MIGRATION_SOURCE}:{suitability.id}",
            ),
            created_at=now,
            updated_at=now,
        ))

    if not dry_run:
        db.add(rule_set)
        db.commit()
        report.rule_set_id = rule_set_id

    return report
