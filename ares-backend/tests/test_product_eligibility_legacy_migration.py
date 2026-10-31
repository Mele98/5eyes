"""CERT-PRODUCT-ELIGIBILITY-001 -- legacy ProductSuitability migration
(spec Section 15). Covers the three classification branches
(verified_migrated_rule / legacy_ambiguous_scope / legacy_conflicting) and
confirms the migration is additive, idempotent-safe under dry-run, and
never invents tenant/jurisdiction/service data.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
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
from models.review import Product, ProductSuitability  # noqa: E402
from services.product_eligibility_legacy_migration import (  # noqa: E402
    classify_and_migrate_legacy_suitability,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _make_product(session, *, product_id: str, jurisdiction=None, tenant_id=None) -> Product:
    now = _now_iso()
    product = Product(
        id=product_id, product_name=f"Test {product_id}", provider="Test",
        product_type="ETF", asset_class="Aktien", sub_asset_class="Aktien Global",
        currency="CHF", ter_bps=50, is_active=1, created_at=now, updated_at=now,
        jurisdiction=jurisdiction, tenant_id=tenant_id,
    )
    session.add(product)
    session.flush()
    return product


def _make_suitability(session, *, product_id: str, **overrides) -> ProductSuitability:
    now = _now_iso()
    defaults = dict(
        id=new_uuid(), product_id=product_id, profile_from=1, profile_to=10,
        advisory_allowed=1, discretionary_allowed=1,
        requires_appropriateness=0, requires_override=0, max_position_bps=None,
        created_at=now, updated_at=now,
    )
    defaults.update(overrides)
    row = ProductSuitability(**defaults)
    session.add(row)
    session.flush()
    return row


def test_single_rule_product_migrates_cleanly(session_factory):
    with session_factory() as s:
        _make_product(s, product_id="p-single")
        _make_suitability(s, product_id="p-single", profile_from=4, profile_to=10, max_position_bps=2500)
        s.commit()

        report = classify_and_migrate_legacy_suitability(
            s, created_by="advisor-1", approved_by="compliance-1", dry_run=False,
        )

        assert report.migrated_count == 1
        assert report.quarantined_count == 0
        assert report.rule_set_id is not None

        rule_set = s.query(ProductEligibilityRuleSet).filter_by(id=report.rule_set_id).first()
        assert rule_set.status == "approved"
        assert rule_set.tenant_scope == "global"
        assert rule_set.jurisdiction == "CH"
        assert rule_set.approved_by == "compliance-1"

        rule = s.query(ProductEligibilityRule).filter_by(product_id="p-single").first()
        assert rule is not None
        assert rule.status == "approved"
        assert rule.profile_from == 4 and rule.profile_to == 10
        assert rule.max_position_bps == 2500
        assert json.loads(rule.service_modes_json) == ["investment_advice", "portfolio_management"]
        assert rule.prohibited == 0
        assert rule.requires_suitability == 1


def test_non_overlapping_bands_for_same_product_both_migrate(session_factory):
    with session_factory() as s:
        _make_product(s, product_id="p-split")
        _make_suitability(
            s, product_id="p-split", profile_from=1, profile_to=3,
            advisory_allowed=1, discretionary_allowed=0,
        )
        _make_suitability(
            s, product_id="p-split", profile_from=4, profile_to=10,
            advisory_allowed=1, discretionary_allowed=1,
        )
        s.commit()

        report = classify_and_migrate_legacy_suitability(
            s, created_by="advisor-1", approved_by="compliance-1", dry_run=False,
        )

        assert report.migrated_count == 2
        assert report.quarantined_count == 0
        rules = s.query(ProductEligibilityRule).filter_by(product_id="p-split").all()
        assert len(rules) == 2
        modes = sorted(json.loads(r.service_modes_json) for r in rules)
        assert modes == [["investment_advice"], ["investment_advice", "portfolio_management"]]


def test_overlapping_contradictory_bands_are_quarantined_as_conflicting(session_factory):
    with session_factory() as s:
        _make_product(s, product_id="p-conflict")
        _make_suitability(
            s, product_id="p-conflict", profile_from=1, profile_to=10,
            advisory_allowed=1, discretionary_allowed=1,
        )
        _make_suitability(
            s, product_id="p-conflict", profile_from=5, profile_to=8,
            advisory_allowed=0, discretionary_allowed=0,
        )
        s.commit()

        report = classify_and_migrate_legacy_suitability(
            s, created_by="advisor-1", approved_by="compliance-1", dry_run=False,
        )

        assert report.migrated_count == 0
        assert report.quarantined_count == 2
        assert all(i.classification == "legacy_conflicting" for i in report.items)
        assert s.query(ProductEligibilityRule).filter_by(product_id="p-conflict").count() == 0
        assert report.rule_set_id is None


def test_overlapping_identical_duplicate_bands_are_quarantined_as_ambiguous(session_factory):
    with session_factory() as s:
        _make_product(s, product_id="p-dup")
        _make_suitability(s, product_id="p-dup", profile_from=1, profile_to=10)
        _make_suitability(s, product_id="p-dup", profile_from=1, profile_to=10)
        s.commit()

        report = classify_and_migrate_legacy_suitability(
            s, created_by="advisor-1", approved_by="compliance-1", dry_run=False,
        )

        assert report.migrated_count == 0
        assert report.quarantined_count == 2
        assert all(i.classification == "legacy_ambiguous_scope" for i in report.items)
        assert s.query(ProductEligibilityRule).filter_by(product_id="p-dup").count() == 0


def test_dry_run_writes_nothing(session_factory):
    with session_factory() as s:
        _make_product(s, product_id="p-dry")
        _make_suitability(s, product_id="p-dry")
        s.commit()

        report = classify_and_migrate_legacy_suitability(
            s, created_by="advisor-1", approved_by="compliance-1", dry_run=True,
        )

        assert report.migrated_count == 1
        assert report.rule_set_id is None  # dry-run never assigns a persisted id
        assert s.query(ProductEligibilityRuleSet).count() == 0
        assert s.query(ProductEligibilityRule).count() == 0


def test_prohibited_derived_when_neither_service_mode_allowed(session_factory):
    with session_factory() as s:
        _make_product(s, product_id="p-prohibited")
        _make_suitability(
            s, product_id="p-prohibited", advisory_allowed=0, discretionary_allowed=0,
        )
        s.commit()

        report = classify_and_migrate_legacy_suitability(
            s, created_by="advisor-1", approved_by="compliance-1", dry_run=False,
        )

        rule = s.query(ProductEligibilityRule).filter_by(product_id="p-prohibited").first()
        assert rule.prohibited == 1
        assert json.loads(rule.service_modes_json) == []


def test_tenant_and_jurisdiction_are_read_not_invented(session_factory):
    with session_factory() as s:
        from models.tenant import Tenant
        s.add(Tenant(
            id="tenant-x", display_name="Tenant X", slug="tenant-x",
            created_at=_now_iso(), updated_at=_now_iso(),
        ))
        s.flush()
        _make_product(s, product_id="p-tenant", jurisdiction="DE", tenant_id="tenant-x")
        _make_suitability(s, product_id="p-tenant")
        s.commit()

        classify_and_migrate_legacy_suitability(
            s, created_by="advisor-1", approved_by="compliance-1", dry_run=False,
        )

        rule = s.query(ProductEligibilityRule).filter_by(product_id="p-tenant").first()
        assert rule.jurisdiction == "DE"
        assert rule.tenant_scope == "tenant"
        assert rule.tenant_id == "tenant-x"
