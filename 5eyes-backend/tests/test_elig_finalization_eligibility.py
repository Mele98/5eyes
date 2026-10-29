"""ELIG-FINAL-001 -- positive and negative controls for the Finalize
product-eligibility re-evaluation (services/product_eligibility_finalization.py).

The reproducer in test_cert_product_eligibility_001_reproducers.py proves
the block when evidence is missing. These controls prove the gate is not
"always block": complete, correctly bound evidence finalizes; wrongly bound
or self-approved evidence does not.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from test_cert_product_eligibility_001_reproducers import (  # noqa: E402
    _generate_house_allocation,
    _make_product,
    _make_rule,
    _make_rule_set,
    _now_iso,
    session_factory,  # noqa: F401  (fixture)
)
from test_optimizer_shadow_mode import _seed_realistic_mandate  # noqa: E402

from database import new_uuid  # noqa: E402
from models.allocation import TargetAllocation  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.product_eligibility import ProductEligibilityOverride, ProductEligibilityRule  # noqa: E402
from models.profiling import SuitabilityCheck  # noqa: E402
from models.review import Product, RecommendationPosition, RecommendationRun  # noqa: E402
from routers.review import _validate_recommendation_for_finalization  # noqa: E402


def _iso(delta_days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).isoformat()


def _setup_run(session_factory, monkeypatch, *, suffix, rule_kwargs=None, weights=(10000,), with_rule=True):
    advisor_id, cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix=suffix)
    _generate_house_allocation(session_factory, mid, advisor_id, monkeypatch)
    with session_factory() as s:
        ta = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid, TargetAllocation.is_current == 1,
        ).first()
        product = _make_product(s, product_id=f"{suffix}-product")
        rule_id = None
        if with_rule:
            _make_rule(s, product_id=product.id, rule_set_id=_make_rule_set(s), **(rule_kwargs or {}))
            rule_id = s.query(ProductEligibilityRule.id).filter(
                ProductEligibilityRule.product_id == product.id,
            ).scalar()
        run_id = new_uuid()
        now = _now_iso()
        s.add(RecommendationRun(
            id=run_id, mandate_id=mid, client_id=cid, assessment_id=aid,
            target_allocation_id=ta.id, policy_id=ta.policy_id,
            capital_market_assumptions_id=ta.capital_market_assumptions_id,
            run_type="Optimizer", result_status="Draft",
            created_by=advisor_id, created_at=now, updated_at=now,
        ))
        for weight in weights:
            s.add(RecommendationPosition(
                id=new_uuid(), run_id=run_id, product_id=product.id,
                target_weight_bps=weight, target_amount_rappen=weight * 50_00,
                created_at=now, updated_at=now,
            ))
        s.commit()
    return {"advisor": advisor_id, "client": cid, "mandate": mid, "assessment": aid,
            "run": run_id, "product": product.id, "rule": rule_id}


def _add_appropriateness(session_factory, ctx, *, run_id=None, result="Angemessen", anchored=True):
    now = _now_iso()
    with session_factory() as s:
        s.add(SuitabilityCheck(
            id=new_uuid(), mandate_id=ctx["mandate"], client_id=ctx["client"],
            recommendation_run_id=run_id or ctx["run"], duty_type="Angemessenheitsprüfung",
            risk_assessment_id=ctx["assessment"] if anchored else None,
            result=result, checked_by=ctx["advisor"], checked_at=now,
            created_at=now, updated_at=now,
        ))
        s.commit()


def _add_override(session_factory, ctx, *, approved_by="compliance-2", expires_days=30, rule_id=None):
    from services.product_eligibility_override import (
        decision_binding_hash, decision_context, evaluate, override_evidence_hash,
    )

    now = _now_iso()
    with session_factory() as s:
        row = ProductEligibilityOverride(
            id=new_uuid(), rule_id=rule_id or ctx["rule"], product_id=ctx["product"],
            recommendation_run_id=ctx["run"], original_decision="indeterminate",
            overridden_dimension="override", reason_code="DOCUMENTED_EXCEPTION",
            requested_by=ctx["advisor"], approved_by=approved_by,
            valid_from=_iso(-1), expires_at=_iso(expires_days),
            created_at=now, updated_at=now,
        )
        # ELIG-OVERRIDE-CAPTURE-001: evidence hash bound to the current decision.
        mandate = s.get(Mandate, ctx["mandate"])
        decision_ctx = decision_context(s, mandate, s.get(RecommendationRun, ctx["run"]))
        product = s.get(Product, ctx["product"])
        decision = evaluate(s, decision_ctx, product, 0)
        row.evidence_hash = override_evidence_hash(row, decision_binding_hash(decision_ctx, decision))
        s.add(row)
        s.commit()


def _eligibility_findings(session_factory, ctx):
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == ctx["mandate"]).first()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == ctx["run"]).first()
        errors, warnings = _validate_recommendation_for_finalization(db, mandate, run)

    def pick(items):
        return [m for m in items if m.startswith("Produkteignung")]

    return pick(errors), pick(warnings), errors


def test_plain_eligible_product_adds_no_eligibility_finding(session_factory, monkeypatch):
    ctx = _setup_run(session_factory, monkeypatch, suffix="ok-plain")
    errors, warnings, all_errors = _eligibility_findings(session_factory, ctx)
    assert errors == [] and warnings == []
    assert all_errors == []


def test_complete_bound_evidence_finalizes(session_factory, monkeypatch):
    ctx = _setup_run(session_factory, monkeypatch, suffix="ok-evid",
                     rule_kwargs={"requires_appropriateness": 1, "requires_override": 1})
    _add_appropriateness(session_factory, ctx)
    _add_override(session_factory, ctx)
    errors, _warnings, _ = _eligibility_findings(session_factory, ctx)
    assert errors == []


def test_appropriateness_bound_to_other_run_is_no_evidence(session_factory, monkeypatch):
    ctx = _setup_run(session_factory, monkeypatch, suffix="other-run",
                     rule_kwargs={"requires_appropriateness": 1})
    _add_appropriateness(session_factory, ctx, run_id="another-run")
    errors, _w, _ = _eligibility_findings(session_factory, ctx)
    assert any("APPROPRIATENESS_EVIDENCE_MISSING" in e for e in errors), errors


def test_unanchored_legacy_positive_check_is_no_evidence(session_factory, monkeypatch):
    ctx = _setup_run(session_factory, monkeypatch, suffix="no-anchor",
                     rule_kwargs={"requires_appropriateness": 1})
    _add_appropriateness(session_factory, ctx, anchored=False)
    errors, _w, _ = _eligibility_findings(session_factory, ctx)
    assert any("APPROPRIATENESS_EVIDENCE_MISSING" in e for e in errors), errors


def test_negative_appropriateness_blocks(session_factory, monkeypatch):
    ctx = _setup_run(session_factory, monkeypatch, suffix="neg",
                     rule_kwargs={"requires_appropriateness": 1})
    _add_appropriateness(session_factory, ctx, result="Nicht angemessen")
    errors, _w, _ = _eligibility_findings(session_factory, ctx)
    assert any("APPROPRIATENESS_NOT_POSITIVE" in e for e in errors), errors


@pytest.mark.parametrize("variant", ["self_approved", "expired", "other_rule"])
def test_invalid_override_is_no_evidence(session_factory, monkeypatch, variant):
    ctx = _setup_run(session_factory, monkeypatch, suffix=f"ovr-{variant}",
                     rule_kwargs={"requires_override": 1})
    if variant == "self_approved":
        _add_override(session_factory, ctx, approved_by=ctx["advisor"])
    elif variant == "expired":
        _add_override(session_factory, ctx, expires_days=-0.5)
    else:
        _add_override(session_factory, ctx, rule_id="some-other-rule")
    errors, _w, _ = _eligibility_findings(session_factory, ctx)
    assert any("OVERRIDE_EVIDENCE_MISSING" in e for e in errors), errors


def test_manual_product_without_governed_rule_blocks(session_factory, monkeypatch):
    ctx = _setup_run(session_factory, monkeypatch, suffix="norule", with_rule=False)
    errors, _w, _ = _eligibility_findings(session_factory, ctx)
    assert any("NO_GOVERNED_RULE" in e for e in errors), errors


def test_out_of_band_product_blocks(session_factory, monkeypatch):
    ctx = _setup_run(session_factory, monkeypatch, suffix="band",
                     rule_kwargs={"profile_from": 10, "profile_to": 10})
    errors, _w, _ = _eligibility_findings(session_factory, ctx)
    assert any("RISK_BAND_MISMATCH" in e for e in errors), errors


def test_position_cap_is_aggregated_and_reported_as_warning_only(session_factory, monkeypatch):
    """ELIG-LIMIT-001 stays an owner decision: the cap is checked on the
    AGGREGATED weight (2 x 5000 = 10000 > 500), but only warned."""
    ctx = _setup_run(session_factory, monkeypatch, suffix="cap",
                     rule_kwargs={"max_position_bps": 500}, weights=(5000, 5000))
    errors, warnings, _ = _eligibility_findings(session_factory, ctx)
    assert errors == []
    assert any("POSITION_LIMIT_EXCEEDED" in w and "10000 bps" in w for w in warnings), warnings
