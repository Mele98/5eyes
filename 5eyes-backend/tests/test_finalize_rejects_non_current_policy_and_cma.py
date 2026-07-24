"""2026-07-24 (Generalaudit, Folgefund zu F4/Lifecycle-Haertung Runde 4):
_validate_recommendation_for_finalization prueft is_current fuer
RiskAssessment und TargetAllocation, aber NICHT fuer OptimizerPolicy und
CapitalMarketAssumption -- obwohl beide Modelle dasselbe is_current-Feld
haben und an anderer Stelle im selben Router bereits danach gefiltert
wird. Eine Empfehlung konnte so auf einer bereits ersetzten Policy- oder
CMA-Version finalisiert werden, analog zum urspruenglichen F4-Bug.
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: F401
from database import new_uuid
from models.allocation import CapitalMarketAssumption, OptimizerPolicy
from models.mandates import Mandate
from models.review import RecommendationRun
from routers.review import _validate_recommendation_for_finalization
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: F401


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _make_policy(session_factory, created_by, *, is_current: bool) -> str:
    pid = new_uuid()
    now = _iso(datetime.now(timezone.utc))
    with session_factory() as s:
        s.add(OptimizerPolicy(
            id=pid, policy_name="Test-Policy", version=1,
            is_current=(1 if is_current else 0), valid_from=now,
            optimizer_engine="goal_based_v1",
            max_real_estate_bps=2000, max_alternatives_bps=1000, min_liquidity_bps=0,
            created_by=created_by, created_at=now, updated_at=now,
        ))
        s.commit()
    return pid


def _make_cma(session_factory, *, is_current: bool) -> str:
    cid = new_uuid()
    now = _iso(datetime.now(timezone.utc))
    with session_factory() as s:
        s.add(CapitalMarketAssumption(
            id=cid, assumption_set_name="Test-CMA", version=1,
            is_current=(1 if is_current else 0), valid_from=now,
            correlation_matrix_json="", sub_asset_class_assumptions_json="",
            created_by="advisor", created_at=now, updated_at=now,
        ))
        s.commit()
    return cid


def _make_run_with_policy_cma(session_factory, mandate_id, allocation_id, assessment_id, created_by, policy_id, cma_id) -> str:
    rid = new_uuid()
    now = _iso(datetime.now(timezone.utc))
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).first()
        s.add(RecommendationRun(
            id=rid, mandate_id=mandate_id, client_id=mandate.client_id,
            assessment_id=assessment_id, target_allocation_id=allocation_id,
            policy_id=policy_id, capital_market_assumptions_id=cma_id,
            run_type="Optimizer", result_status="Draft",
            created_by=created_by, created_at=now, updated_at=now,
        ))
        s.commit()
    return rid


def _current_allocation_id(session_factory, mandate_id):
    from models.allocation import TargetAllocation
    with session_factory() as s:
        row = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id,
            TargetAllocation.is_current == 1,
        ).first()
        return row.id if row else None


def test_finalize_rejects_non_current_policy(session_factory):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix="policy-noncur")
    alloc_id = _current_allocation_id(session_factory, mid)
    old_policy = _make_policy(session_factory, advisor_id, is_current=False)
    cma = _make_cma(session_factory, is_current=True)
    run_id = _make_run_with_policy_cma(session_factory, mid, alloc_id, aid, advisor_id, old_policy, cma)

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).first()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).first()
        errors, _warnings = _validate_recommendation_for_finalization(db, mandate, run)
    assert "Empfehlung basiert nicht auf der aktuellen Policy-Version." in errors


def test_finalize_accepts_current_policy(session_factory):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix="policy-cur")
    alloc_id = _current_allocation_id(session_factory, mid)
    cur_policy = _make_policy(session_factory, advisor_id, is_current=True)
    cma = _make_cma(session_factory, is_current=True)
    run_id = _make_run_with_policy_cma(session_factory, mid, alloc_id, aid, advisor_id, cur_policy, cma)

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).first()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).first()
        errors, _warnings = _validate_recommendation_for_finalization(db, mandate, run)
    assert "Empfehlung basiert nicht auf der aktuellen Policy-Version." not in errors


def test_finalize_rejects_non_current_cma(session_factory):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix="cma-noncur")
    alloc_id = _current_allocation_id(session_factory, mid)
    policy = _make_policy(session_factory, advisor_id, is_current=True)
    old_cma = _make_cma(session_factory, is_current=False)
    run_id = _make_run_with_policy_cma(session_factory, mid, alloc_id, aid, advisor_id, policy, old_cma)

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).first()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).first()
        errors, _warnings = _validate_recommendation_for_finalization(db, mandate, run)
    assert "Empfehlung basiert nicht auf der aktuellen CMA-Version." in errors


def test_finalize_accepts_current_cma(session_factory):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix="cma-cur")
    alloc_id = _current_allocation_id(session_factory, mid)
    policy = _make_policy(session_factory, advisor_id, is_current=True)
    cur_cma = _make_cma(session_factory, is_current=True)
    run_id = _make_run_with_policy_cma(session_factory, mid, alloc_id, aid, advisor_id, policy, cur_cma)

    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mid).first()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).first()
        errors, _warnings = _validate_recommendation_for_finalization(db, mandate, run)
    assert "Empfehlung basiert nicht auf der aktuellen CMA-Version." not in errors
