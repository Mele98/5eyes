"""CERT-PRODUCT-ELIGIBILITY-001 -- unit coverage for the new, additive
`services.product_eligibility.evaluate_product_eligibility()` core (spec
Section 17, steps 2-5). Not yet wired into Generate/Finalize/the legacy
matcher -- see tests/test_cert_product_eligibility_001_reproducers.py for
the still-open findings that wiring will eventually close.

Section 16.2/16.3 of the spec names the negative/positive matrix this file
starts covering: no rule, ambiguous rules, prohibited product, risk-band
mismatch, service-mode mismatch, missing/negative appropriateness, missing
override evidence, aggregated position cap, and a fully-eligible golden
case with deterministic replay.
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
    allocation, clients, client_login, fx_rate, mandates, profiling,
    protocol_bausteine, review, snapshots, tenant, users, wealth,
    product_eligibility as product_eligibility_models,
)
configure_mappers()

from models.product_eligibility import ProductEligibilityRule, ProductEligibilityRuleSet  # noqa: E402
from models.review import Product  # noqa: E402
from services.product_eligibility import (  # noqa: E402
    evaluate_product_eligibility,
    map_product_to_knowledge_categories,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _past_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _future_iso(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _make_product(session, *, product_id: str, asset_class: str = "Aktien", product_type: str = "ETF") -> Product:
    now = _now_iso()
    product = Product(
        id=product_id, product_name=f"Test {product_id}", provider="Test",
        product_type=product_type, asset_class=asset_class,
        sub_asset_class="Aktien Global", currency="CHF", ter_bps=50,
        is_active=1, created_at=now, updated_at=now,
    )
    session.add(product)
    session.flush()
    return product


def _make_rule_set(session, *, created_by: str = "advisor") -> str:
    rid = new_uuid()
    now = _now_iso()
    session.add(ProductEligibilityRuleSet(
        id=rid, tenant_scope="global", jurisdiction="CH", version=1,
        status="approved", valid_from=_past_iso(1), created_by=created_by,
        approved_by="compliance-officer", approved_at=now,
        rule_set_hash="test-hash", created_at=now, updated_at=now,
    ))
    session.flush()
    return rid


def _make_rule(session, *, product_id: str, rule_set_id: str, **overrides) -> ProductEligibilityRule:
    now = _now_iso()
    defaults = dict(
        id=new_uuid(), rule_set_id=rule_set_id, version=1,
        product_id=product_id, tenant_scope="global", jurisdiction="CH",
        client_classifications_json="[]",
        service_modes_json='["investment_advice"]',
        profile_from=1, profile_to=10,
        requires_knowledge_categories_json="[]",
        requires_appropriateness=0, requires_suitability=0, requires_override=0,
        prohibited=0, valid_from=_past_iso(1), status="approved",
        created_by="advisor", approved_by="compliance-officer", approved_at=now,
        rule_hash="test-rule-hash", created_at=now, updated_at=now,
    )
    defaults.update(overrides)
    rule = ProductEligibilityRule(**defaults)
    session.add(rule)
    session.flush()
    return rule


def test_no_rule_is_indeterminate_not_eligible(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="p-no-rule")
        s.commit()
        s.refresh(product)

        decision = evaluate_product_eligibility(
            s, product=product, service_mode="investment_advice",
            score_bucket=5, aggregated_weight_bps=1000, source_sub_allocations=["x"],
        )
        assert decision.decision == "indeterminate"
        assert "NO_GOVERNED_RULE" in decision.reason_codes


def test_ambiguous_rule_match_is_indeterminate(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="p-ambiguous")
        rs = _make_rule_set(s)
        _make_rule(s, product_id=product.id, rule_set_id=rs)
        _make_rule(s, product_id=product.id, rule_set_id=rs)
        s.commit()
        s.refresh(product)

        decision = evaluate_product_eligibility(
            s, product=product, service_mode="investment_advice",
            score_bucket=5, aggregated_weight_bps=1000, source_sub_allocations=["x"],
        )
        assert decision.decision == "indeterminate"
        assert "AMBIGUOUS_RULE_MATCH" in decision.reason_codes


def test_prohibited_product_is_ineligible(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="p-prohibited")
        rs = _make_rule_set(s)
        _make_rule(s, product_id=product.id, rule_set_id=rs, prohibited=1)
        s.commit()
        s.refresh(product)

        decision = evaluate_product_eligibility(
            s, product=product, service_mode="investment_advice",
            score_bucket=5, aggregated_weight_bps=1000, source_sub_allocations=["x"],
        )
        assert decision.decision == "ineligible"
        assert "PRODUCT_PROHIBITED" in decision.reason_codes


def test_risk_band_mismatch_is_ineligible(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="p-band")
        rs = _make_rule_set(s)
        _make_rule(s, product_id=product.id, rule_set_id=rs, profile_from=8, profile_to=10)
        s.commit()
        s.refresh(product)

        decision = evaluate_product_eligibility(
            s, product=product, service_mode="investment_advice",
            score_bucket=3, aggregated_weight_bps=1000, source_sub_allocations=["x"],
        )
        assert decision.decision == "ineligible"
        assert "RISK_BAND_MISMATCH" in decision.reason_codes


def test_service_mode_not_permitted_is_ineligible(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="p-mode")
        rs = _make_rule_set(s)
        _make_rule(
            s, product_id=product.id, rule_set_id=rs,
            service_modes_json='["portfolio_management"]',
        )
        s.commit()
        s.refresh(product)

        decision = evaluate_product_eligibility(
            s, product=product, service_mode="investment_advice",
            score_bucket=5, aggregated_weight_bps=1000, source_sub_allocations=["x"],
        )
        assert decision.decision == "ineligible"
        assert "SERVICE_MODE_NOT_PERMITTED" in decision.reason_codes


def test_missing_appropriateness_evidence_is_indeterminate(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="p-approp-missing")
        rs = _make_rule_set(s)
        _make_rule(s, product_id=product.id, rule_set_id=rs, requires_appropriateness=1)
        s.commit()
        s.refresh(product)

        decision = evaluate_product_eligibility(
            s, product=product, service_mode="investment_advice",
            score_bucket=5, aggregated_weight_bps=1000, source_sub_allocations=["x"],
        )
        assert decision.decision == "indeterminate"
        assert "APPROPRIATENESS_EVIDENCE_MISSING" in decision.reason_codes


def test_negative_appropriateness_is_ineligible_not_rehabilitated(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="p-approp-negative")
        rs = _make_rule_set(s)
        _make_rule(s, product_id=product.id, rule_set_id=rs, requires_appropriateness=1)
        s.commit()
        s.refresh(product)

        decision = evaluate_product_eligibility(
            s, product=product, service_mode="investment_advice",
            score_bucket=5, aggregated_weight_bps=1000, source_sub_allocations=["x"],
            appropriateness_result="Nicht angemessen",
        )
        assert decision.decision == "ineligible"
        assert "APPROPRIATENESS_NOT_POSITIVE" in decision.reason_codes


def test_missing_override_evidence_is_indeterminate(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="p-override-missing")
        rs = _make_rule_set(s)
        _make_rule(s, product_id=product.id, rule_set_id=rs, requires_override=1)
        s.commit()
        s.refresh(product)

        decision = evaluate_product_eligibility(
            s, product=product, service_mode="investment_advice",
            score_bucket=5, aggregated_weight_bps=1000, source_sub_allocations=["x"],
        )
        assert decision.decision == "indeterminate"
        assert "OVERRIDE_EVIDENCE_MISSING" in decision.reason_codes


def test_aggregated_position_exceeding_cap_is_ineligible(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="p-cap")
        rs = _make_rule_set(s)
        _make_rule(s, product_id=product.id, rule_set_id=rs, max_position_bps=500)
        s.commit()
        s.refresh(product)

        decision = evaluate_product_eligibility(
            s, product=product, service_mode="investment_advice",
            score_bucket=5, aggregated_weight_bps=800, source_sub_allocations=["a", "b"],
        )
        assert decision.decision == "ineligible"
        assert "POSITION_LIMIT_EXCEEDED" in decision.reason_codes


def test_aggregated_position_exactly_at_cap_is_eligible(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="p-cap-exact")
        rs = _make_rule_set(s)
        _make_rule(s, product_id=product.id, rule_set_id=rs, max_position_bps=500)
        s.commit()
        s.refresh(product)

        decision = evaluate_product_eligibility(
            s, product=product, service_mode="investment_advice",
            score_bucket=5, aggregated_weight_bps=500, source_sub_allocations=["a"],
        )
        assert decision.decision == "eligible"


def test_fully_satisfied_rule_with_evidence_is_eligible_golden_case(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="p-golden")
        rs = _make_rule_set(s)
        _make_rule(
            s, product_id=product.id, rule_set_id=rs,
            requires_appropriateness=1,
            requires_knowledge_categories_json='["equities"]',
            requires_override=0,
        )
        s.commit()
        s.refresh(product)

        decision = evaluate_product_eligibility(
            s, product=product, service_mode="investment_advice",
            score_bucket=5, aggregated_weight_bps=1000, source_sub_allocations=["x"],
            knowledge_categories_covered=["equities"],
            appropriateness_result="Angemessen",
        )
        assert decision.decision == "eligible"
        assert decision.reason_codes == []


def test_replay_with_identical_inputs_is_deterministic(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="p-replay")
        rs = _make_rule_set(s)
        _make_rule(s, product_id=product.id, rule_set_id=rs)
        s.commit()
        s.refresh(product)

        kwargs = dict(
            product=product, service_mode="investment_advice",
            score_bucket=5, aggregated_weight_bps=1000, source_sub_allocations=["x"],
        )
        first = evaluate_product_eligibility(s, **kwargs)
        second = evaluate_product_eligibility(s, **kwargs)
        assert first.decision == second.decision
        assert first.matched_rule_hash == second.matched_rule_hash
        assert first.reason_codes == second.reason_codes


def test_retired_and_expired_rules_are_not_matched(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="p-retired")
        rs = _make_rule_set(s)
        _make_rule(s, product_id=product.id, rule_set_id=rs, status="retired")
        _make_rule(
            s, product_id=product.id, rule_set_id=rs,
            valid_from=_past_iso(100), valid_to=_past_iso(10),
        )
        s.commit()
        s.refresh(product)

        decision = evaluate_product_eligibility(
            s, product=product, service_mode="investment_advice",
            score_bucket=5, aggregated_weight_bps=1000, source_sub_allocations=["x"],
        )
        assert decision.decision == "indeterminate"
        assert "NO_GOVERNED_RULE" in decision.reason_codes


def test_knowledge_category_mapping_equities_etf():
    import sys as _sys
    from unittest.mock import MagicMock
    product = MagicMock(
        asset_class="Aktien", product_type="ETF", sub_asset_class="Aktien Global",
        security_type=None, security_type2=None, market_sector=None,
    )
    categories = map_product_to_knowledge_categories(product)
    assert "equities" in categories
    assert "funds_etf" in categories
    assert "complex_products" not in categories


def test_knowledge_category_mapping_direct_real_estate_is_illiquid():
    from unittest.mock import MagicMock
    product = MagicMock(
        asset_class="Immobilien", product_type="Einzeltitel", sub_asset_class="Immobilien Schweiz",
        security_type=None, security_type2=None, market_sector=None,
    )
    categories = map_product_to_knowledge_categories(product)
    assert "illiquid_products" in categories
    assert "complex_products" in categories
    assert "real_estate_funds" not in categories
