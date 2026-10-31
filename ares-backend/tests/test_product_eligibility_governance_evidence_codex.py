"""Codex-Reproducer 2026-10-13 (Product-Eligibility-Governance/Evidence), als regulaerer Test uebernommen.

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
from sqlalchemy import UniqueConstraint, create_engine
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
    ProductEligibilityRuleSet,
)
from models.review import Product  # noqa: E402
from services.product_eligibility import (  # noqa: E402
    author_default_catalog_rule,
    author_tenant_product_rule,
    ensure_rule_set,
    evaluate_product_eligibility,
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


def _rule_set(session, *, author: str = "audit-author") -> ProductEligibilityRuleSet:
    now = _now()
    value = ProductEligibilityRuleSet(
        id=new_uuid(),
        tenant_scope="global",
        tenant_id=None,
        jurisdiction="CH",
        version=1,
        status="approved",
        valid_from=_past(),
        created_by=author,
        approved_by="audit-approver",
        approved_at=now,
        rule_set_hash="audit-rule-set-hash",
        created_at=now,
        updated_at=now,
    )
    session.add(value)
    session.flush()
    return value


# Codex-Reproducer ELIG-GOVERNANCE-001 (ehemals strict xfail)
def test_policy_relevant_rule_fields_change_the_persisted_rule_hash(session_factory):
    with session_factory() as session:
        product = _product(session, "audit-policy-hash")
        rule_set = _rule_set(session)
        baseline = author_default_catalog_rule(
            session,
            product=product,
            rule_set=rule_set,
            profile_from=1,
            profile_to=10,
            service_modes=["investment_advice"],
            max_position_bps=1000,
            requires_appropriateness=False,
            requires_override=False,
            authored_by="audit-author",
            source_label="audit-source",
            now=_past(),
        )
        stricter = author_default_catalog_rule(
            session,
            product=product,
            rule_set=rule_set,
            profile_from=1,
            profile_to=10,
            service_modes=["investment_advice"],
            max_position_bps=500,
            requires_appropriateness=True,
            requires_override=True,
            authored_by="audit-author",
            source_label="audit-source",
            now=_past(),
        )
        assert baseline.rule_hash != stricter.rule_hash


# Codex-Reproducer ELIG-GOVERNANCE-001 (ehemals strict xfail)
def test_decision_references_the_exact_persisted_rule_hash(session_factory):
    with session_factory() as session:
        product = _product(session, "audit-matched-rule-hash")
        rule_set = _rule_set(session)
        rule = author_default_catalog_rule(
            session,
            product=product,
            rule_set=rule_set,
            profile_from=1,
            profile_to=10,
            service_modes=["investment_advice"],
            max_position_bps=None,
            authored_by="audit-author",
            source_label="audit-source",
            now=_past(),
        )
        session.commit()

        decision = evaluate_product_eligibility(
            session,
            product=product,
            service_mode="investment_advice",
            score_bucket=5,
            aggregated_weight_bps=1000,
            source_sub_allocations=["audit"],
            jurisdiction="CH",
        )
        assert decision.matched_rule_id == rule.id
        assert decision.matched_rule_hash == rule.rule_hash


# Codex-Reproducer ELIG-GOVERNANCE-001 (ehemals strict xfail)
def test_tenant_policy_is_not_auto_approved_by_its_author(session_factory):
    with session_factory() as session:
        product = _product(session, "audit-self-approval", tenant_id="tenant-a")
        rule = author_tenant_product_rule(
            session,
            product=product,
            created_by_user_id="tenant-admin-a",
            jurisdiction="CH",
            profile_from=1,
            profile_to=10,
            service_modes=["investment_advice"],
            now=_past(),
        )
        session.flush()
        rule_set = session.get(ProductEligibilityRuleSet, rule.rule_set_id)

        assert not (
            rule.status == "approved" and rule.approved_by == rule.created_by
        )
        assert not (
            rule_set.status == "approved"
            and rule_set.approved_by == rule_set.created_by
        )


# Codex-Reproducer ELIG-GOVERNANCE-001 (ehemals strict xfail)
def test_rule_set_find_or_create_key_is_database_unique_for_concurrency():
    table = ProductEligibilityRuleSet.__table__
    required_key = {"tenant_scope", "tenant_id", "jurisdiction", "created_by"}
    unique_column_sets = [
        {column.name for column in constraint.columns}
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    unique_column_sets.extend(
        {column.name for column in index.columns}
        for index in table.indexes
        if index.unique
    )
    assert any(required_key <= columns for columns in unique_column_sets)
