"""ELIG-GOVERNANCE-001 / ELIG-TENANT-SCOPE-001 / ELIG-CATEGORY-SELECTOR-001 /
ELIG-MIGRATION-IDEMPOTENCY-001 (Fix 2026-10-21) -- Ergaenzungen zu den
Codex-Reproducern (tests/test_product_eligibility_*_codex.py):

* Positivkontrollen, damit der strikte Resolver nicht einfach "nie etwas"
  liefert (eigener Tenant, passender Selektor, genehmigtes Set).
* Vier-Augen ueber den echten Endpoint: Autor -> 409, zweiter Admin -> 200,
  danach ist das Produkt fuer den eigenen Tenant waehlbar, fuer einen
  fremden Tenant nicht.
* find-or-create: DB-Unique-Key greift auch bei NULL-tenant (global) und der
  Verlierer eines Rennens bekommt das Gewinner-Set statt eines Duplikats.
* Legacy-Migration: zweiter Lauf meldet already_governed, nicht quarantined.
* SQLite-Runtime-Reparatur legt die neuen Unique-Indizes auf Alt-DBs an.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database import Base, get_db, new_uuid  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, client_login, clients, fx_rate, mandates, portfolio_handoff,
    product_eligibility as product_eligibility_models, profiling,
    protocol_bausteine, review, snapshots, tenant, users, wealth,
)

configure_mappers()

from models.product_eligibility import (  # noqa: E402
    ProductEligibilityRule,
    ProductEligibilityRuleSet,
)
from models.review import Product, ProductSuitability  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from services.product_eligibility import (  # noqa: E402
    author_default_catalog_rule,
    author_tenant_product_rule,
    ensure_rule_set,
    evaluate_product_eligibility,
    is_eligible_candidate,
    resolve_active_rules_for_product,
)
from services.product_eligibility_governance import (  # noqa: E402
    RuleApprovalConflict,
    approve_rule,
    compute_rule_hash,
    RULE_POLICY_FIELDS,
)
from services.product_eligibility_legacy_migration import (  # noqa: E402
    classify_and_migrate_legacy_suitability,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _past() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


@pytest.fixture()
def sf(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'elig_gov.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _product(session, product_id: str, *, tenant_id: str | None = None, **overrides) -> Product:
    now = _now()
    values = dict(
        id=product_id, product_name=f"T {product_id}", provider="T",
        product_type="ETF", asset_class="Aktien", sub_asset_class="Aktien Global",
        currency="CHF", ter_bps=10, is_active=1, tenant_id=tenant_id,
        jurisdiction="CH", created_at=now, updated_at=now,
    )
    values.update(overrides)
    product = Product(**values)
    session.add(product)
    session.flush()
    return product


def _approved_set(session, *, tenant_scope="global", tenant_id=None) -> ProductEligibilityRuleSet:
    return ensure_rule_set(
        session, jurisdiction="CH", authored_by="author-x",
        tenant_scope=tenant_scope, tenant_id=tenant_id, now=_past(),
        approved_by="approver-y",
    )


def _selector_rule(session, rule_set, selector: str) -> ProductEligibilityRule:
    now = _past()
    policy = dict(
        rule_set_id=rule_set.id, version=1, product_id=None,
        product_category_selector=selector, tenant_scope="global", tenant_id=None,
        jurisdiction="CH", client_classifications_json="[]",
        service_modes_json='["investment_advice"]', profile_from=1, profile_to=10,
        requires_knowledge_categories_json="[]", minimum_experience_level=None,
        requires_appropriateness=0, requires_suitability=1, requires_override=0,
        max_position_bps=None, prohibited=0, valid_from=now, valid_to=None,
        supersedes_id=None,
    )
    rule = ProductEligibilityRule(
        id=new_uuid(), **policy, status="approved", created_by="author-x",
        approved_by="approver-y", approved_at=now,
        rule_hash=compute_rule_hash(policy), created_at=now, updated_at=now,
    )
    session.add(rule)
    session.flush()
    return rule


# -- Resolver: Positivkontrollen ---------------------------------------------

def test_tenant_rule_is_visible_to_its_own_tenant_only(sf):
    with sf() as s:
        product = _product(s, "own-tenant", tenant_id="tenant-a")
        rule_set = _approved_set(s, tenant_scope="tenant", tenant_id="tenant-a")
        rule = author_default_catalog_rule(
            s, product=product, rule_set=rule_set, profile_from=1, profile_to=10,
            service_modes=["investment_advice"], max_position_bps=None,
            tenant_scope="tenant", authored_by="author-x", approved_by="approver-y",
            now=_past(),
        )
        s.commit()
        assert [r.id for r in resolve_active_rules_for_product(
            s, product, jurisdiction="CH", tenant_id="tenant-a")] == [rule.id]
        assert resolve_active_rules_for_product(s, product, jurisdiction="CH", tenant_id="tenant-b") == []
        assert resolve_active_rules_for_product(s, product, jurisdiction="CH", tenant_id=None) == []
        assert is_eligible_candidate(
            s, product, service_mode="investment_advice", score_bucket=5, tenant_id="tenant-a")
        assert not is_eligible_candidate(
            s, product, service_mode="investment_advice", score_bucket=5, tenant_id="tenant-b")


def test_global_rule_copy_carrying_a_tenant_id_is_only_visible_to_that_tenant(sf):
    """Spiegel des Postgres-RLS-Praedikats (tenant_id = aktueller Tenant):
    eine pro Tenant provisionierte Kopie einer globalen Regel gehoert genau
    diesem Tenant -- auf SQLite (ohne RLS) darf sie nicht fremd sichtbar sein."""
    with sf() as s:
        product = _product(s, "global-main")
        rule_set = _approved_set(s)
        rule = author_default_catalog_rule(
            s, product=product, rule_set=rule_set, profile_from=1, profile_to=10,
            service_modes=["investment_advice"], max_position_bps=None,
            authored_by="author-x", approved_by="approver-y", now=_past(),
        )
        s.commit()
        assert [r.id for r in resolve_active_rules_for_product(
            s, product, jurisdiction="CH", tenant_id="tenant-b")] == [rule.id]
        rule.tenant_id = "main"
        s.commit()
        assert [r.id for r in resolve_active_rules_for_product(
            s, product, jurisdiction="CH", tenant_id="main")] == [rule.id]
        assert resolve_active_rules_for_product(s, product, jurisdiction="CH", tenant_id="tenant-b") == []
        assert resolve_active_rules_for_product(s, product, jurisdiction="CH", tenant_id=None) == []


def test_matching_category_selector_applies_and_unknown_keys_fail_closed(sf):
    with sf() as s:
        product = _product(s, "selector-equity")
        rule_set = _approved_set(s)
        matching = _selector_rule(s, rule_set, json.dumps({"asset_class": "Aktien", "currency": "CHF"}))
        _selector_rule(s, rule_set, json.dumps({"asset_class": "Aktien", "issuer_rating": "AAA"}))
        _selector_rule(s, rule_set, "not json")
        _selector_rule(s, rule_set, "{}")
        _selector_rule(s, rule_set, json.dumps({"asset_class": "Aktien", "currency": "EUR"}))
        s.commit()
        rules = resolve_active_rules_for_product(s, product, jurisdiction="CH", tenant_id=None)
        assert [r.id for r in rules] == [matching.id]


def test_overlapping_bands_stay_ambiguous(sf):
    with sf() as s:
        product = _product(s, "overlap")
        rule_set = _approved_set(s)
        for band in ((1, 6), (4, 10)):
            author_default_catalog_rule(
                s, product=product, rule_set=rule_set, profile_from=band[0], profile_to=band[1],
                service_modes=["investment_advice"], max_position_bps=None,
                authored_by="author-x", approved_by="approver-y", now=_past(),
            )
        s.commit()
        decision = evaluate_product_eligibility(
            s, product=product, service_mode="investment_advice", score_bucket=5,
            aggregated_weight_bps=0, source_sub_allocations=[], jurisdiction="CH",
        )
        assert decision.decision == "indeterminate"
        assert "AMBIGUOUS_RULE_MATCH" in decision.reason_codes


# -- Hash -------------------------------------------------------------------

@pytest.mark.parametrize("field", [f for f in RULE_POLICY_FIELDS])
def test_every_policy_field_changes_the_rule_hash(field):
    base = {name: None for name in RULE_POLICY_FIELDS}
    base.update(profile_from=1, profile_to=10, service_modes_json="[]")
    changed = dict(base)
    if field.endswith("_json"):
        changed[field] = '["x"]'
    elif isinstance(base[field], int):
        changed[field] = base[field] + 1
    else:
        changed[field] = "changed"
    assert compute_rule_hash(base) != compute_rule_hash(changed)


# -- Vier-Augen -------------------------------------------------------------

def test_tenant_rule_needs_second_principal_and_then_becomes_effective(sf):
    with sf() as s:
        product = _product(s, "four-eyes", tenant_id="tenant-a")
        rule = author_tenant_product_rule(
            s, product=product, created_by_user_id="admin-1", jurisdiction="CH",
            profile_from=1, profile_to=10, service_modes=["investment_advice"], now=_past(),
        )
        s.commit()
        assert rule.status == "draft" and rule.approved_by is None
        assert not is_eligible_candidate(
            s, product, service_mode="investment_advice", score_bucket=5, tenant_id="tenant-a")

        with pytest.raises(RuleApprovalConflict):
            approve_rule(s, rule_id=rule.id, approver_id="admin-1", tenant_id="tenant-a")
        with pytest.raises(LookupError):
            approve_rule(s, rule_id=rule.id, approver_id="admin-2", tenant_id="tenant-b")

        approve_rule(s, rule_id=rule.id, approver_id="admin-2", tenant_id="tenant-a")
        s.commit()
        rule_set = s.get(ProductEligibilityRuleSet, rule.rule_set_id)
        assert (rule.status, rule.approved_by) == ("approved", "admin-2")
        assert (rule_set.status, rule_set.approved_by) == ("approved", "admin-2")
        assert is_eligible_candidate(
            s, product, service_mode="investment_advice", score_bucket=5, tenant_id="tenant-a")
        with pytest.raises(RuleApprovalConflict):
            approve_rule(s, rule_id=rule.id, approver_id="admin-3", tenant_id="tenant-a")


def _api_client(session_factory, user_id: str, tenant_id: str) -> TestClient:
    from main import app
    from services.auth import get_current_user

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    current = SimpleNamespace(
        id=user_id, full_name=f"Tester {user_id}", email=f"{user_id}@test.local",
        role="admin", tenant_id=tenant_id,
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current
    return TestClient(app)


def test_approve_endpoint_enforces_four_eyes(sf):
    from main import app

    with sf() as s:
        s.add(Tenant(
            id="firm-a", display_name="firm-a", slug="firm-a", hosting_tier="tier2",
            license_status="active", is_active=1, created_at=_now(), updated_at=_now(),
        ))
        s.commit()
    try:
        with _api_client(sf, "admin-1", "firm-a") as client:
            created = client.post("/products", json={
                "product_name": "Firma A Hausfonds", "product_type": "Fonds",
                "asset_class": "Aktien", "currency": "CHF",
                "suitability_profile_from": 1, "suitability_profile_to": 10,
            })
            assert created.status_code == 201, created.text
            pid = created.json()["id"]
            self_approval = client.post(f"/products/{pid}/eligibility-rule/approve")
            assert self_approval.status_code == 409, self_approval.text
        with _api_client(sf, "admin-2", "firm-a") as client:
            approved = client.post(f"/products/{pid}/eligibility-rule/approve")
            assert approved.status_code == 200, approved.text
            assert len(approved.json()["approved_rule_ids"]) == 1
            again = client.post(f"/products/{pid}/eligibility-rule/approve")
            assert again.status_code == 409
    finally:
        app.dependency_overrides.clear()
    with sf() as s:
        rule = s.query(ProductEligibilityRule).filter_by(product_id=pid).one()
        assert (rule.created_by, rule.approved_by, rule.status) == ("admin-1", "admin-2", "approved")


# -- find-or-create ---------------------------------------------------------

@pytest.mark.parametrize("tenant_scope,tenant_id", [("global", None), ("tenant", "tenant-a")])
def test_rule_set_lineage_is_db_unique_including_null_tenant(sf, tenant_scope, tenant_id):
    with sf() as s:
        if tenant_id:
            s.add(Tenant(
                id=tenant_id, display_name=tenant_id, slug=tenant_id, hosting_tier="tier2",
                license_status="active", is_active=1, created_at=_now(), updated_at=_now(),
            ))
        first = ensure_rule_set(
            s, jurisdiction="CH", authored_by="author-x",
            tenant_scope=tenant_scope, tenant_id=tenant_id, approved_by="approver-y",
        )
        s.commit()
        now = _now()
        s.add(ProductEligibilityRuleSet(
            id=new_uuid(), tenant_scope=tenant_scope, tenant_id=tenant_id,
            jurisdiction="CH", version=first.version, status="approved",
            valid_from=now, created_by="author-x", rule_set_hash="dup",
            created_at=now, updated_at=now,
        ))
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_concurrent_find_or_create_returns_the_winner(sf, monkeypatch):
    """Verlierer eines Rennens: der Vorab-Lookup sieht (noch) nichts, der
    Insert scheitert am Unique-Key -> das bereits committete Set wird
    zurueckgegeben, kein Duplikat, keine Exception."""
    with sf() as winner_session:
        winner = ensure_rule_set(
            winner_session, jurisdiction="CH", authored_by="author-x", approved_by="approver-y",
        )
        winner_session.commit()

    with sf() as loser_session:
        from sqlalchemy.orm import Query

        original_first = Query.first
        calls = {"n": 0}

        def first_once_empty(self):
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return original_first(self)

        monkeypatch.setattr(Query, "first", first_once_empty)
        monkeypatch.setattr(
            Query, "scalar", lambda self: 0,
        )
        result = ensure_rule_set(
            loser_session, jurisdiction="CH", authored_by="author-x", approved_by="approver-y",
        )
        monkeypatch.undo()
        assert result.id == winner.id
        loser_session.commit()
        assert loser_session.query(ProductEligibilityRuleSet).count() == 1


# -- Legacy-Migration -------------------------------------------------------

def test_second_migration_run_reports_already_governed_not_quarantined(sf):
    with sf() as s:
        product = _product(s, "legacy-twice")
        now = _now()
        for band in ((1, 3), (4, 10)):
            s.add(ProductSuitability(
                id=new_uuid(), product_id=product.id, profile_from=band[0], profile_to=band[1],
                advisory_allowed=1, discretionary_allowed=1, requires_appropriateness=0,
                requires_override=0, created_at=now, updated_at=now,
            ))
        s.commit()
        first = classify_and_migrate_legacy_suitability(
            s, created_by="author-x", approved_by="approver-y", dry_run=False)
        second = classify_and_migrate_legacy_suitability(
            s, created_by="author-x", approved_by="approver-y", dry_run=False)
        assert (first.migrated_count, second.migrated_count) == (2, 0)
        assert (second.already_governed_count, second.quarantined_count) == (2, 0)
        assert second.rule_set_id is None
        assert s.query(ProductEligibilityRuleSet).count() == 1
        hashes = {r.rule_hash for r in s.query(ProductEligibilityRule).all()}
        assert len(hashes) == 2


# -- SQLite-Runtime-Reparatur ----------------------------------------------

def test_runtime_repair_adds_lineage_indexes_to_legacy_sqlite_db(tmp_path):
    from database import ensure_current_anchor_unique_indexes

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX ux_product_eligibility_rule_sets_lineage_tenant"))
        conn.execute(text("DROP INDEX ux_product_eligibility_rule_sets_lineage_global"))
    ensure_current_anchor_unique_indexes(engine)
    names = {ix["name"]: ix for ix in inspect(engine).get_indexes("product_eligibility_rule_sets")}
    assert names["ux_product_eligibility_rule_sets_lineage_tenant"]["unique"]
    assert names["ux_product_eligibility_rule_sets_lineage_global"]["unique"]
    engine.dispose()


def test_legacy_migration_rejects_self_approval(sf):
    with sf() as s:
        with pytest.raises(ValueError):
            classify_and_migrate_legacy_suitability(
                s, created_by="author-x", approved_by="author-x", dry_run=False)
        report = classify_and_migrate_legacy_suitability(
            s, created_by="author-x", approved_by="author-x", dry_run=True)
        assert report.migrated_count == 0
