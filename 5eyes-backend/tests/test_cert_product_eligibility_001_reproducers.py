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
from models.review import (  # noqa: E402
    Product, ProductSuitability, RecommendationPosition, RecommendationRun,
)
from schemas.profiling import SuitabilityCheckCreate  # noqa: E402
from services.portfolio_engine_payload import _product_matches_constraints  # noqa: E402
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


# ---------------------------------------------------------------------------
# ELIG-MODE-001 -- service mode is not an input to the matcher at all.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="ELIG-MODE-001 -- CERT-PRODUCT-ELIGIBILITY-001")
def test_matcher_rejects_discretionary_forbidden_product_in_discretionary_mode(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="mode-001-product")
        s.add(ProductSuitability(
            id=new_uuid(), product_id=product.id,
            profile_from=1, profile_to=10,
            advisory_allowed=1, discretionary_allowed=0,
            created_at=_now_iso(), updated_at=_now_iso(),
        ))
        s.commit()
        s.refresh(product)

        # Soll: a product that is explicitly forbidden for discretionary
        # mandates (discretionary_allowed=0) must be rejected when the
        # service mode is discretionary. The matcher has no such parameter
        # today -- this call raises TypeError, which IS the failure this
        # xfail documents.
        result = _product_matches_constraints(
            product, _default_prefs(), score_bucket=5, service_mode="discretionary",
        )
        assert result is False


# ---------------------------------------------------------------------------
# ELIG-RULE-001 -- requires_appropriateness/requires_override are loaded but
# never consulted by the matcher.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="ELIG-RULE-001 -- CERT-PRODUCT-ELIGIBILITY-001")
def test_matcher_blocks_product_requiring_unmet_appropriateness_and_override(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="rule-001-product")
        s.add(ProductSuitability(
            id=new_uuid(), product_id=product.id,
            profile_from=1, profile_to=10, advisory_allowed=1,
            requires_appropriateness=1, requires_override=1,
            created_at=_now_iso(), updated_at=_now_iso(),
        ))
        s.commit()
        s.refresh(product)

        # Soll: without appropriateness/override evidence, a product whose
        # rule requires both must NOT match. Today the matcher ignores both
        # flags entirely and returns True purely from the risk band.
        result = _product_matches_constraints(product, _default_prefs(), score_bucket=5)
        assert result is False


# ---------------------------------------------------------------------------
# ELIG-DEFAULT-001 -- a product with zero suitability rules is treated as
# universally allowed instead of indeterminate/blocked.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="ELIG-DEFAULT-001 -- CERT-PRODUCT-ELIGIBILITY-001")
def test_matcher_fails_closed_when_no_suitability_rule_exists(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="default-001-product")
        s.commit()
        s.refresh(product)
        assert product.suitability == []

        # Soll: no rule at all is `indeterminate`, not `eligible`.
        result = _product_matches_constraints(product, _default_prefs(), score_bucket=5)
        assert result is False


# ---------------------------------------------------------------------------
# ELIG-FALLBACK-001 -- ignore_suitability turns a hard rejection back into a
# match; this is the exact flag services.portfolio_engine.
# generate_recommendation_run() passes in its fallback retry.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="ELIG-FALLBACK-001 -- CERT-PRODUCT-ELIGIBILITY-001")
def test_ignore_suitability_must_not_resurrect_an_out_of_band_product(session_factory):
    with session_factory() as s:
        product = _make_product(s, product_id="fallback-001-product")
        s.add(ProductSuitability(
            id=new_uuid(), product_id=product.id,
            profile_from=8, profile_to=10, advisory_allowed=1,
            created_at=_now_iso(), updated_at=_now_iso(),
        ))
        s.commit()
        s.refresh(product)

        blocked = _product_matches_constraints(product, _default_prefs(), score_bucket=3)
        assert blocked is False

        # Soll: a hard suitability rejection must stay a rejection in
        # production decisions. Today ignore_suitability=True (exactly the
        # parameter the Generate-fallback path uses) flips this back to True.
        relaxed = _product_matches_constraints(
            product, _default_prefs(), score_bucket=3, ignore_suitability=True,
        )
        assert relaxed is False


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
