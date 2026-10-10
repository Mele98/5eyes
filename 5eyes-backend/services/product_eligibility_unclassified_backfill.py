"""CERT-PRODUCT-ELIGIBILITY-001 -- one-time backfill for products that have
NEVER had any suitability data at all (neither a legacy `ProductSuitability`
row nor a governed `ProductEligibilityRule`): custom/tenant-added products
from the Fondsuniversum-Erfassung/CSV-Import flow created before
routers.review.create_product() started requiring a suitability band
(2026-10-09), plus any jurisdiction (e.g. DE) whose products never went
through services.portfolio_engine.ensure_default_products().

This is additive and deliberately separate from
services/product_eligibility_legacy_migration.py: that module promotes an
EXISTING human suitability judgement (a `ProductSuitability` row) into the
governed schema. This module has no such judgement to promote -- there is
none -- so it only ever auto-classifies a product when it can do so SAFELY
by reusing the exact same, already-reviewed heuristic
(`services.product_eligibility.default_product_risk_band()`) the firm's own
default catalog already relies on, and ONLY for plain, recognized,
non-complex instrument types. Everything else is quarantined for manual
classification (e.g. via a future ProductEligibilityRule authoring
endpoint) -- never guessed, consistent with Section 15's "classify before
migrate, never silently resolve" discipline and Section 4.2's fail-closed
default.

Like the legacy migration, this always produces a report and never runs
automatically in request-serving code paths -- see
scripts/backfill_unclassified_product_eligibility.py, which defaults to
dry-run. A caller who wants this applied must pass dry_run=False and a
real, accountable `authored_by` principal id explicitly (Section 11: never
a synthetic system sentinel for a retroactive classification decision like
this one -- unlike the default-catalog bootstrap identity, which has never
had a human accountable for it in the first place).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.product_eligibility import ProductEligibilityRule, ProductEligibilityRuleSet
from models.review import Product
from services.product_eligibility import (
    author_default_catalog_rule,
    default_product_risk_band,
    ensure_rule_set,
)

AUTO_BACKFILL_SOURCE = "unclassified_product_auto_backfill_v1"

# Section 4.2 fail-closed default stays in force for every asset_class NOT
# listed here, and for Alternative/Liquiditaet sub_asset_class values NOT in
# the whitelist below -- those are quarantined, never guessed.
_AUTO_CLASSIFIABLE_ASSET_CLASSES = frozenset({"Aktien", "Obligationen", "Immobilien"})
_SAFE_ALTERNATIVE_LIQUIDITY_SUB_ASSET_CLASSES = frozenset({
    "Gold / Rohstoffe", "Geldmarktfonds", "Kontoguthaben", "Festgeld",
    "Liquid Alternatives", "Hedge Funds", "Private Equity", "Krypto",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class UnclassifiedBackfillItem:
    product_id: str
    classification: str  # "auto_classified" | "quarantined_complex" | "quarantined_unrecognized_category"
    reason: str
    new_rule_id: str | None = None


@dataclass
class UnclassifiedBackfillReport:
    dry_run: bool
    items: list[UnclassifiedBackfillItem] = field(default_factory=list)

    @property
    def classified_count(self) -> int:
        return sum(1 for i in self.items if i.classification == "auto_classified")

    @property
    def quarantined_count(self) -> int:
        return sum(1 for i in self.items if i.classification != "auto_classified")


def _is_safe_to_auto_classify(product: Product) -> tuple[bool, str]:
    # Lazy import (circular-import hardening, matching this package's own
    # established convention -- see services/product_eligibility.py).
    from services.portfolio_engine_payload import (
        _product_is_derivative,
        _product_is_leveraged,
        _product_is_structured,
    )

    if _product_is_structured(product) or _product_is_derivative(product) or _product_is_leveraged(product):
        return False, (
            "Komplexes Produkt (strukturiert/derivativ/gehebelt) -- "
            "braucht menschliche Klassifizierung, nie automatisch."
        )
    if product.asset_class in _AUTO_CLASSIFIABLE_ASSET_CLASSES:
        return True, "Einfacher Standard-Instrumententyp, Default-Risikoband anwendbar."
    if product.asset_class in ("Alternative", "Liquidität", "Liquiditaet") and (
        product.sub_asset_class in _SAFE_ALTERNATIVE_LIQUIDITY_SUB_ASSET_CLASSES
    ):
        return True, "Bekannte, sichere Alternative-/Liquiditaets-Kategorie."
    return False, (
        f"asset_class={product.asset_class!r} / sub_asset_class={product.sub_asset_class!r} "
        "nicht in der sicheren Default-Liste -- braucht menschliche Klassifizierung."
    )


def classify_and_backfill_unclassified_products(
    db: Session,
    *,
    jurisdiction_fallback: str,
    authored_by: str,
    dry_run: bool = True,
    now: str | None = None,
) -> UnclassifiedBackfillReport:
    """Classify every `Product` row with no existing `approved`
    `ProductEligibilityRule`, across every jurisdiction/tenant found in the
    DB. Safe to run repeatedly (idempotent: a product already covered by a
    rule -- from this function, the default catalog, or the legacy
    migration -- is skipped).
    """
    now = now or _now_iso()
    report = UnclassifiedBackfillReport(dry_run=dry_run)

    already_governed_ids = {
        row[0]
        for row in db.query(ProductEligibilityRule.product_id)
        .filter(ProductEligibilityRule.status == "approved")
        .all()
    }
    candidates = (
        db.query(Product)
        .filter(Product.deleted_at.is_(None))
        .filter(~Product.id.in_(already_governed_ids) if already_governed_ids else True)
        .all()
    )

    rule_set_cache: dict[tuple, ProductEligibilityRuleSet] = {}

    for product in candidates:
        safe, reason = _is_safe_to_auto_classify(product)
        if not safe:
            report.items.append(UnclassifiedBackfillItem(
                product_id=product.id,
                classification=(
                    "quarantined_complex" if "strukturiert" in reason
                    else "quarantined_unrecognized_category"
                ),
                reason=reason,
            ))
            continue

        profile_from, profile_to = default_product_risk_band(product)
        max_position_bps = 2500 if product.asset_class == "Aktien" else 4000
        jurisdiction = product.jurisdiction or jurisdiction_fallback
        tenant_scope = "tenant" if product.tenant_id else "global"

        new_rule_id = None
        if not dry_run:
            cache_key = (tenant_scope, product.tenant_id, jurisdiction)
            rule_set = rule_set_cache.get(cache_key)
            if rule_set is None:
                rule_set = ensure_rule_set(
                    db,
                    jurisdiction=jurisdiction,
                    authored_by=authored_by,
                    tenant_scope=tenant_scope,
                    tenant_id=product.tenant_id,
                    now=now,
                )
                rule_set_cache[cache_key] = rule_set
            rule = author_default_catalog_rule(
                db,
                product=product,
                rule_set=rule_set,
                profile_from=profile_from,
                profile_to=profile_to,
                service_modes=["investment_advice", "portfolio_management"],
                max_position_bps=max_position_bps,
                tenant_scope=tenant_scope,
                authored_by=authored_by,
                source_label=AUTO_BACKFILL_SOURCE,
                now=now,
            )
            new_rule_id = rule.id

        report.items.append(UnclassifiedBackfillItem(
            product_id=product.id,
            classification="auto_classified",
            reason=f"{reason} Band=({profile_from},{profile_to}).",
            new_rule_id=new_rule_id,
        ))

    if not dry_run:
        db.flush()
    return report
