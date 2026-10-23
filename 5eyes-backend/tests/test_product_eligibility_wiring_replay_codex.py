"""Codex-Reproducer 2026-10-09 (Product-Eligibility-Wiring), als regulaerer Test uebernommen.

Urspruenglich strict-xfail-Replays aus dem Codex-Audit; seit dem Fix
(Branch fix/product-eligibility-governance) muessen alle Faelle gruen sein:
Resolver strikt auf Tenant + genehmigtes Regelset + exakten Selektor,
Regel-Hash ueber alle Policy-Felder, Vier-Augen-Genehmigung,
DB-Unique-Key fuer find-or-create, idempotente Legacy-Migration.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, new_uuid  # noqa: E402
from models import (  # noqa: E402,F401
    allocation,
    client_login,
    clients,
    fx_rate,
    mandates,
    portfolio_handoff,
    product_eligibility as product_eligibility_models,
    profiling,
    protocol_bausteine,
    review,
    snapshots,
    tenant,
    users,
    wealth,
)

configure_mappers()

from models.product_eligibility import (  # noqa: E402
    ProductEligibilityRule,
    ProductEligibilityRuleSet,
)
from models.review import Product, ProductSuitability  # noqa: E402
from services.product_eligibility import (  # noqa: E402
    evaluate_product_eligibility,
    resolve_active_rules_for_product,
)
from services.product_eligibility_legacy_migration import (  # noqa: E402
    classify_and_migrate_legacy_suitability,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _past() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite:///:memory:")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _product(session, product_id: str, *, tenant_id: str | None = None) -> Product:
    now = _now()
    value = Product(
        id=product_id,
        product_name=f"Audit {product_id}",
        provider="Audit",
        product_type="ETF",
        asset_class="Aktien",
        sub_asset_class="Aktien Global",
        currency="CHF",
        ter_bps=10,
        is_active=1,
        tenant_id=tenant_id,
        jurisdiction="CH",
        created_at=now,
        updated_at=now,
    )
    session.add(value)
    session.flush()
    return value


def _rule_set(
    session,
    *,
    status: str = "approved",
    tenant_scope: str = "global",
    tenant_id: str | None = None,
) -> str:
    now = _now()
    value = ProductEligibilityRuleSet(
        id=new_uuid(),
        tenant_scope=tenant_scope,
        tenant_id=tenant_id,
        jurisdiction="CH",
        version=1,
        status=status,
        valid_from=_past(),
        created_by="audit-author",
        approved_by="audit-approver" if status == "approved" else None,
        approved_at=now if status == "approved" else None,
        rule_set_hash="audit-rule-set-hash",
        created_at=now,
        updated_at=now,
    )
    session.add(value)
    session.flush()
    return value.id


def _rule(session, *, rule_set_id: str, product_id: str | None, **overrides):
    now = _now()
    values = dict(
        id=new_uuid(),
        rule_set_id=rule_set_id,
        version=1,
        product_id=product_id,
        product_category_selector=None,
        tenant_scope="global",
        tenant_id=None,
        jurisdiction="CH",
        client_classifications_json="[]",
        service_modes_json='["investment_advice"]',
        profile_from=1,
        profile_to=10,
        requires_knowledge_categories_json="[]",
        requires_appropriateness=0,
        requires_suitability=1,
        requires_override=0,
        max_position_bps=None,
        prohibited=0,
        valid_from=_past(),
        status="approved",
        created_by="audit-author",
        approved_by="audit-approver",
        approved_at=now,
        rule_hash="audit-rule-hash",
        created_at=now,
        updated_at=now,
    )
    values.update(overrides)
    value = ProductEligibilityRule(**values)
    session.add(value)
    session.flush()
    return value


def _evaluate(session, product: Product, *, score_bucket: int = 5, tenant_id=None):
    return evaluate_product_eligibility(
        session,
        product=product,
        service_mode="investment_advice",
        score_bucket=score_bucket,
        aggregated_weight_bps=0,
        source_sub_allocations=[],
        jurisdiction="CH",
        tenant_id=tenant_id,
    )


# Codex-Reproducer ELIG-RULE-RESOLUTION-001 (ehemals strict xfail)
def test_non_overlapping_migrated_bands_select_the_applicable_band(session_factory):
    with session_factory() as session:
        product = _product(session, "audit-split-band")
        rule_set_id = _rule_set(session)
        _rule(
            session,
            rule_set_id=rule_set_id,
            product_id=product.id,
            profile_from=1,
            profile_to=3,
        )
        expected = _rule(
            session,
            rule_set_id=rule_set_id,
            product_id=product.id,
            profile_from=4,
            profile_to=10,
        )
        session.commit()

        decision = _evaluate(session, product, score_bucket=5)
        assert decision.decision == "eligible"
        assert decision.matched_rule_id == expected.id


# Codex-Reproducer ELIG-TENANT-SCOPE-001 (ehemals strict xfail)
def test_tenant_scoped_rule_is_invisible_to_a_different_tenant(session_factory):
    with session_factory() as session:
        product = _product(session, "audit-tenant-rule", tenant_id="tenant-a")
        rule_set_id = _rule_set(
            session, tenant_scope="tenant", tenant_id="tenant-a"
        )
        _rule(
            session,
            rule_set_id=rule_set_id,
            product_id=product.id,
            tenant_scope="tenant",
            tenant_id="tenant-a",
        )
        session.commit()

        rules = resolve_active_rules_for_product(
            session,
            product,
            jurisdiction="CH",
            tenant_id="tenant-b",
        )
        assert rules == []


# Codex-Reproducer ELIG-RULESET-GOVERNANCE-001 (ehemals strict xfail)
def test_approved_rule_inside_draft_rule_set_is_not_active(session_factory):
    with session_factory() as session:
        product = _product(session, "audit-draft-set")
        rule_set_id = _rule_set(session, status="draft")
        _rule(session, rule_set_id=rule_set_id, product_id=product.id)
        session.commit()

        decision = _evaluate(session, product)
        assert decision.decision == "indeterminate"
        assert "NO_GOVERNED_RULE" in decision.reason_codes


# Codex-Reproducer ELIG-CATEGORY-SELECTOR-001 (ehemals strict xfail)
def test_unrelated_category_selector_does_not_match_product(session_factory):
    with session_factory() as session:
        product = _product(session, "audit-equity-product")
        rule_set_id = _rule_set(session)
        _rule(
            session,
            rule_set_id=rule_set_id,
            product_id=None,
            product_category_selector='{"asset_class":"Obligationen"}',
        )
        session.commit()

        rules = resolve_active_rules_for_product(
            session,
            product,
            jurisdiction="CH",
            tenant_id=None,
        )
        assert rules == []


# Codex-Reproducer ELIG-MIGRATION-IDEMPOTENCY-001 (ehemals strict xfail)
def test_repeated_apply_does_not_duplicate_approved_rules(session_factory):
    with session_factory() as session:
        product = _product(session, "audit-repeat-migration")
        now = _now()
        session.add(
            ProductSuitability(
                id=new_uuid(),
                product_id=product.id,
                profile_from=1,
                profile_to=10,
                advisory_allowed=1,
                discretionary_allowed=1,
                requires_appropriateness=0,
                requires_override=0,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

        first = classify_and_migrate_legacy_suitability(
            session,
            created_by="audit-author",
            approved_by="audit-approver",
            dry_run=False,
        )
        second = classify_and_migrate_legacy_suitability(
            session,
            created_by="audit-author",
            approved_by="audit-approver",
            dry_run=False,
        )

        assert first.migrated_count == 1
        assert second.migrated_count == 0
        assert (
            session.query(ProductEligibilityRule)
            .filter(ProductEligibilityRule.product_id == product.id)
            .count()
            == 1
        )
