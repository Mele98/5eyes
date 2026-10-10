"""CERT-PRODUCT-ELIGIBILITY-001 -- permanent repository reproducers.

Source of truth: the Ares/Codex audit worktree
`C:\\Users\\Emanuele\\Documents\\ChatGPT\\5eyes wird zu Ares\\asset-allocation-stochastic-core`
(branch `codex/asset-allocation-stochastic-core`),
`docs/audits/2026-10-08-product-eligibility-appropriateness-and-finalization-certification-spec.md`.
That spec documents nine reproduced-but-not-committed findings (its own
temporary reproducer was deliberately removed after the run, per its
`product_code_mutated: false` / `tests_mutated: false` audit discipline).
Step 1 of the spec's own "Implementierungsreihenfolge fuer Claude" (Section
17) is to adopt these nine reproducers as PERMANENT repository tests before
touching any product code. This file is that step.

All nine root causes below were independently re-verified against this
repo's actual current `develop` HEAD (717ce3ab529d53c9fb355ee2b401932829ea0054)
before writing these tests -- not copied from the spec's historical evidence
unchecked.

Do not close any of these by weakening the assertion, deleting the test, or
flipping only a config default (the spec explicitly calls out
"Nicht zuerst nur den Config-Default auf True setzen" for ELIG-GATE-001 --
the real fix is a fail-closed, evidence-bound eligibility core, not a
default flip). Closure requires the full `ProductEligibilitySnapshotV1` /
`ProductEligibilityDecisionV1` / `ProductEligibilityRuleV1` contract from
Section 4 of the spec.

UPDATE (2026-10-09, Schritt 6/7): ELIG-MODE-001/RULE-001/DEFAULT-001/
FALLBACK-001 are now re-targeted at the real production decision surface
(`services.product_eligibility.is_eligible_candidate()`, which
`generate_recommendation_run()` now actually calls) instead of the legacy
`_product_matches_constraints()`, whose suitability dimension was removed
entirely in this change (it is now a pure preference filter -- see its
docstring). This is not a weakening: every Soll-scenario and assertion is
unchanged, only the call target moved to where the real decision now
lives. ELIG-GOVERNANCE-001/KNOWLEDGE-001/GATE-001/LIMIT-001/FINAL-001
remain untouched and still xfail -- out of scope for this step (Finalize/
knowledge/hard-gate wiring is steps 8/10/11, not done yet).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from config import settings  # noqa: E402
from database import Base, new_uuid  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, client_login, fx_rate, mandates, profiling,
    protocol_bausteine, review, snapshots, tenant, users, wealth,
)
configure_mappers()

from models.mandates import Mandate  # noqa: E402
from models.product_eligibility import ProductEligibilityRule, ProductEligibilityRuleSet  # noqa: E402
from models.review import (  # noqa: E402
    Product, ProductSuitability, RecommendationPosition, RecommendationRun,
)
from schemas.profiling import SuitabilityCheckCreate  # noqa: E402
from services.portfolio_engine_payload import _product_matches_constraints  # noqa: E402
from services.product_eligibility import is_eligible_candidate  # noqa: E402
from routers.review import _validate_recommendation_for_finalization  # noqa: E402
from test_optimizer_shadow_mode import _seed_realistic_mandate  # noqa: E402


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


def _default_prefs() -> dict:
    return {"product": {}, "geo": {}, "policy": {}}


def _make_product(session, *, product_id: str, sub_asset_class: str = "Aktien Global") -> Product:
    now = _now_iso()
    product = Product(
        id=product_id,
        product_name=f"Test Product {product_id}",
        provider="Test",
        product_type="ETF",
        asset_class="Aktien",
        sub_asset_class=sub_asset_class,
        currency="CHF",
        ter_bps=50,
        is_active=1,
        created_at=now,
        updated_at=now,
    )
    session.add(product)
    session.flush()
    return product


def _make_rule_set(session, *, created_by: str = "advisor") -> str:
    rid = new_uuid()
    now = _now_iso()
    session.add(ProductEligibilityRuleSet(
        id=rid, tenant_scope="global", jurisdiction="CH", version=1,
        status="approved", valid_from=_now_iso(), created_by=created_by,
        approved_by="compliance-officer", approved_at=now,
        rule_set_hash="test-hash", created_at=now, updated_at=now,
    ))
    session.flush()
    return rid


def _make_rule(session, *, product_id: str, rule_set_id: str, **overrides) -> None:
    now = _now_iso()
    defaults = dict(
        id=new_uuid(), rule_set_id=rule_set_id, version=1,
        product_id=product_id, tenant_scope="global", jurisdiction="CH",
        client_classifications_json="[]",
        service_modes_json='["investment_advice"]',
        profile_from=1, profile_to=10,
        requires_knowledge_categories_json="[]",
        requires_appropriateness=0, requires_suitability=0, requires_override=0,
        prohibited=0, valid_from=_now_iso(), status="approved",
        created_by="advisor", approved_by="compliance-officer", approved_at=now,
        rule_hash="test-rule-hash", created_at=now, updated_at=now,
    )
    defaults.update(overrides)
    session.add(ProductEligibilityRule(**defaults))
    session.flush()


# ---------------------------------------------------------------------------
# ELIG-MODE-001 -- service mode is not an input to the matcher at all.
# ---------------------------------------------------------------------------


def test_matcher_rejects_discretionary_forbidden_product_in_discretionary_mode(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="mode-001-product")
        rs = _make_rule_set(s)
        # Approved rule only covers investment_advice -- discretionary is
        # not in service_modes_json at all.
        _make_rule(s, product_id=product.id, rule_set_id=rs, service_modes_json='["investment_advice"]')
        s.commit()
        s.refresh(product)

        # Soll: a product whose governed rule does not list
        # "portfolio_management" must be ineligible for a discretionary
        # mandate's service mode.
        result = is_eligible_candidate(s, product, service_mode="portfolio_management", score_bucket=5)
        assert result is False


# ---------------------------------------------------------------------------
# ELIG-RULE-001 -- requires_appropriateness/requires_override are loaded but
# never consulted by the matcher.
# ---------------------------------------------------------------------------


def test_matcher_blocks_product_requiring_unmet_appropriateness_and_override(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="rule-001-product")
        rs = _make_rule_set(s)
        _make_rule(
            s, product_id=product.id, rule_set_id=rs,
            requires_appropriateness=1, requires_override=1,
        )
        s.commit()
        s.refresh(product)

        # Soll: without appropriateness/override evidence, a product whose
        # rule requires both must NOT be eligible.
        result = is_eligible_candidate(s, product, service_mode="investment_advice", score_bucket=5)
        assert result is False


# ---------------------------------------------------------------------------
# ELIG-DEFAULT-001 -- a product with zero suitability rules is treated as
# universally allowed instead of indeterminate/blocked.
# ---------------------------------------------------------------------------


def test_matcher_fails_closed_when_no_suitability_rule_exists(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="default-001-product")
        s.commit()
        s.refresh(product)
        assert product.suitability == []

        # Soll: no governed rule at all is `indeterminate`, not `eligible`.
        result = is_eligible_candidate(s, product, service_mode="investment_advice", score_bucket=5)
        assert result is False


# ---------------------------------------------------------------------------
# ELIG-FALLBACK-001 -- a suitability-relaxation escape hatch (the former
# ignore_suitability=True parameter services.portfolio_engine.
# generate_recommendation_run() used in its fallback retry) must not exist
# on the real production decision surface at all.
# ---------------------------------------------------------------------------


def test_ignore_suitability_must_not_resurrect_an_out_of_band_product(session_factory):
    import inspect

    with session_factory() as s:
        product = _make_product(s, product_id="fallback-001-product")
        rs = _make_rule_set(s)
        _make_rule(s, product_id=product.id, rule_set_id=rs, profile_from=8, profile_to=10)
        s.commit()
        s.refresh(product)

        blocked = is_eligible_candidate(s, product, service_mode="investment_advice", score_bucket=3)
        assert blocked is False

        # Soll: the real decision surface must not even HAVE a relaxation
        # parameter -- not just default it to off. Today, calling with any
        # "ignore"/"relaxed"/"override_suitability"-shaped kwarg raises
        # TypeError (proving no such escape hatch exists), which IS the
        # failure this xfail documents until the parameter truly never
        # existed in any form reachable from Generate.
        params = inspect.signature(is_eligible_candidate).parameters
        suspicious = [p for p in params if "ignore" in p.lower() or "relax" in p.lower()]
        assert not suspicious, f"Verdaechtiger Relaxation-Parameter gefunden: {suspicious}"
        # And the actual Generate call site must not contain the removed
        # fallback pattern anymore (source-level proof, matches this
        # repo's established convention for "no production code regression"
        # checks).
        source = Path(BACKEND_ROOT / "services" / "portfolio_engine.py").read_text(encoding="utf-8")
        assert "ignore_suitability=True" not in source


# ---------------------------------------------------------------------------
# ELIG-KNOWLEDGE-001 -- positive appropriateness is schema-valid with no
# knowledge_assessment_id at all.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="ELIG-KNOWLEDGE-001 -- CERT-PRODUCT-ELIGIBILITY-001")
def test_positive_appropriateness_requires_a_knowledge_anchor():
    # Soll: a positive Angemessenheitspruefung without any
    # knowledge_assessment_id must be schema-rejected. Today
    # SuitabilityCheckCreate accepts this combination unconditionally.
    with pytest.raises(ValueError):
        SuitabilityCheckCreate(
            duty_type="Angemessenheitsprüfung",
            result="Angemessen",
            knowledge_assessment_id=None,
        )


# ---------------------------------------------------------------------------
# ELIG-GATE-001 -- the suitability hard-gate is opt-in (default off).
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="ELIG-GATE-001 -- CERT-PRODUCT-ELIGIBILITY-001")
def test_suitability_hard_gate_is_not_default_off():
    # Soll: recommendation generation must not be able to silently skip
    # eligibility checking. NOTE (spec Section 17): flipping only this
    # config default is explicitly NOT an accepted fix on its own -- even
    # with the gate on, audit_mandate_suitability() checks assessment
    # freshness, not the concrete per-position product decision. This
    # assertion documents today's off-by-default symptom only.
    assert settings.require_suitability_before_recommendation is True


# ---------------------------------------------------------------------------
# ELIG-LIMIT-001 -- aggregated per-product position caps are not enforced
# at finalization.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="ELIG-LIMIT-001 -- CERT-PRODUCT-ELIGIBILITY-001")
def test_finalize_rejects_position_exceeding_aggregated_product_cap(session_factory):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix="elig-limit")
    with session_factory() as s:
        from models.allocation import TargetAllocation
        allocation_row = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid, TargetAllocation.is_current == 1,
        ).first()
        product = _make_product(s, product_id="limit-001-product")
        s.add(ProductSuitability(
            id=new_uuid(), product_id=product.id,
            profile_from=1, profile_to=10, advisory_allowed=1,
            max_position_bps=500,
            created_at=_now_iso(), updated_at=_now_iso(),
        ))
        run_id = new_uuid()
        now = _now_iso()
        s.add(RecommendationRun(
            id=run_id, mandate_id=mid, client_id=_cid,
            assessment_id=aid, target_allocation_id=allocation_row.id,
            policy_id=allocation_row.policy_id,
            capital_market_assumptions_id=allocation_row.capital_market_assumptions_id,
            run_type="Optimizer", result_status="Draft",
            created_by=advisor_id, created_at=now, updated_at=now,
        ))
        s.add(RecommendationPosition(
            id=new_uuid(), run_id=run_id, product_id=product.id,
            target_weight_bps=10000, target_amount_rappen=500_000_00,
            created_at=now, updated_at=now,
        ))
        s.commit()

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).first()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).first()
        errors, _warnings = _validate_recommendation_for_finalization(db, mandate, run)

    # Soll: 10'000 bps on a product capped at 500 bps must block finalize.
    assert any("max_position_bps" in e or "Positionsdeckel" in e or "500" in e for e in errors), errors


# ---------------------------------------------------------------------------
# ELIG-FINAL-001 -- finalize does not require appropriateness/override
# evidence even when the matched rule demands it.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="ELIG-FINAL-001 -- CERT-PRODUCT-ELIGIBILITY-001")
def test_finalize_rejects_run_missing_required_appropriateness_and_override_evidence(session_factory):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix="elig-final")
    with session_factory() as s:
        from models.allocation import TargetAllocation
        allocation_row = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid, TargetAllocation.is_current == 1,
        ).first()
        product = _make_product(s, product_id="final-001-product")
        s.add(ProductSuitability(
            id=new_uuid(), product_id=product.id,
            profile_from=1, profile_to=10, advisory_allowed=1,
            requires_appropriateness=1, requires_override=1,
            created_at=_now_iso(), updated_at=_now_iso(),
        ))
        run_id = new_uuid()
        now = _now_iso()
        s.add(RecommendationRun(
            id=run_id, mandate_id=mid, client_id=_cid,
            assessment_id=aid, target_allocation_id=allocation_row.id,
            policy_id=allocation_row.policy_id,
            capital_market_assumptions_id=allocation_row.capital_market_assumptions_id,
            run_type="Optimizer", result_status="Draft",
            created_by=advisor_id, created_at=now, updated_at=now,
        ))
        s.add(RecommendationPosition(
            id=new_uuid(), run_id=run_id, product_id=product.id,
            target_weight_bps=10000, target_amount_rappen=500_000_00,
            created_at=now, updated_at=now,
        ))
        s.commit()

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).first()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).first()
        errors, _warnings = _validate_recommendation_for_finalization(db, mandate, run)

    # Soll: no SuitabilityCheck/override evidence exists anywhere for this
    # mandate, yet the matched rule requires both -- finalize must block.
    assert any("Angemessenheit" in e or "Override" in e or "appropriateness" in e.lower() for e in errors), errors


# ---------------------------------------------------------------------------
# ELIG-GOVERNANCE-001 -- ProductSuitability has no governance dimensions.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="ELIG-GOVERNANCE-001 -- CERT-PRODUCT-ELIGIBILITY-001")
def test_product_suitability_has_governance_columns():
    columns = {c.name for c in ProductSuitability.__table__.columns}
    required = {
        "tenant_id", "jurisdiction", "version", "valid_from", "valid_to",
        "status", "approved_by", "supersedes_id", "rule_hash",
    }
    missing = required - columns
    assert not missing, f"ProductSuitability fehlt Governance-Spalten: {sorted(missing)}"
