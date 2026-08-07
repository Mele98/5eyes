"""2026-07-26 (Generalaudit-Nachtrag): finalize_recommendation sperrt jetzt
die Mandate-Zeile vor dem Bulk-UPDATE (siehe test_audit_hardening.py::
test_r2_finalize_recommendation_locks_mandate_row fuer den Race-Condition-
Hintergrund). Dieser Test prueft den funktionalen Normalfall End-to-End:
die neue Sperre darf den bestehenden Finalisierungs-Ablauf NICHT veraendern.
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
from models.review import Product, RecommendationPosition, RecommendationRun
from models.users import User
from routers.review import finalize_recommendation
from services.portfolio_engine import generate_target_allocation
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: F401


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class _FakeClient:
    def __init__(self, host="127.0.0.1"):
        self.host = host


class _FakeRequest:
    def __init__(self, host="127.0.0.1"):
        self.headers = {}
        self.client = _FakeClient(host)


def _make_policy(session_factory, created_by) -> str:
    pid = new_uuid()
    now = _iso(datetime.now(timezone.utc))
    with session_factory() as s:
        s.add(OptimizerPolicy(
            id=pid, policy_name="Test-Policy", version=1,
            is_current=1, valid_from=now,
            optimizer_engine="goal_based_v1",
            max_real_estate_bps=2000, max_alternatives_bps=1000, min_liquidity_bps=0,
            created_by=created_by, created_at=now, updated_at=now,
        ))
        s.commit()
    return pid


def _make_cma(session_factory) -> str:
    cid = new_uuid()
    now = _iso(datetime.now(timezone.utc))
    with session_factory() as s:
        s.add(CapitalMarketAssumption(
            id=cid, assumption_set_name="Test-CMA", version=1,
            is_current=1, valid_from=now,
            correlation_matrix_json="", sub_asset_class_assumptions_json="",
            created_by="advisor", created_at=now, updated_at=now,
        ))
        s.commit()
    return cid


def _current_allocation_id(session_factory, mandate_id, advisor_id):
    from models.allocation import TargetAllocation
    with session_factory() as s:
        row = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id,
            TargetAllocation.is_current == 1,
        ).first()
        if row:
            return row.id
        # _seed_realistic_mandate legt keine TargetAllocation an -- ueber den
        # regulaeren Erzeugungsweg nachziehen (analog test_optimizer_shadow_mode.py).
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        return result["target_allocation"].id


def _make_run(session_factory, mandate_id, allocation_id, assessment_id, created_by, policy_id, cma_id, *, result_status="Draft") -> str:
    rid = new_uuid()
    now = _iso(datetime.now(timezone.utc))
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mandate_id).first()
        s.add(RecommendationRun(
            id=rid, mandate_id=mandate_id, client_id=mandate.client_id,
            assessment_id=assessment_id, target_allocation_id=allocation_id,
            policy_id=policy_id, capital_market_assumptions_id=cma_id,
            run_type="Optimizer", result_status=result_status,
            created_by=created_by, created_at=now, updated_at=now,
        ))
        s.commit()
    return rid


def _add_full_position(session_factory, run_id) -> None:
    """Fuegt genau eine Position mit 10000 bps hinzu, referenziert auf ein
    aktives Produkt -- erfuellt die Positions-/Gewichts-Checks in
    _validate_recommendation_for_finalization."""
    now = _iso(datetime.now(timezone.utc))
    pid = new_uuid()
    with session_factory() as s:
        s.add(Product(
            id=pid, product_name="Test ETF", provider="X",
            product_type="ETF", asset_class="Aktien", sub_asset_class="Aktien Welt",
            currency="CHF", ter_bps=20, sfdr_class="6",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RecommendationPosition(
            id=new_uuid(), run_id=run_id, product_id=pid,
            target_weight_bps=10000, target_amount_rappen=500_000_00,
            created_at=now, updated_at=now,
        ))
        s.commit()


def test_finalize_succeeds_and_supersedes_prior_final_run(session_factory):
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix="finalize-lock")
    alloc_id = _current_allocation_id(session_factory, mid, advisor_id)
    policy = _make_policy(session_factory, advisor_id)
    cma = _make_cma(session_factory)

    first_run_id = _make_run(session_factory, mid, alloc_id, aid, advisor_id, policy, cma, result_status="Final")
    second_run_id = _make_run(session_factory, mid, alloc_id, aid, advisor_id, policy, cma, result_status="Draft")
    _add_full_position(session_factory, second_run_id)

    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        result = finalize_recommendation(
            mandate_id=mid, run_id=second_run_id, request=_FakeRequest(), db=db, current_user=advisor,
        )
        assert result.result_status == "Final"

        first_run = db.query(RecommendationRun).filter(RecommendationRun.id == first_run_id).first()
        second_run = db.query(RecommendationRun).filter(RecommendationRun.id == second_run_id).first()
        assert first_run.result_status == "Superseded"
        assert second_run.result_status == "Final"


def test_finalize_first_run_for_mandate_with_no_prior_final(session_factory):
    """Der eigentliche Race-Faelle betroffene Fall: Mandat hat noch KEINEN
    Final-Run. Normaler Einzel-Aufruf muss weiterhin problemlos funktionieren."""
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(session_factory, suffix="finalize-first")
    alloc_id = _current_allocation_id(session_factory, mid, advisor_id)
    policy = _make_policy(session_factory, advisor_id)
    cma = _make_cma(session_factory)

    run_id = _make_run(session_factory, mid, alloc_id, aid, advisor_id, policy, cma, result_status="Draft")
    _add_full_position(session_factory, run_id)

    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        result = finalize_recommendation(
            mandate_id=mid, run_id=run_id, request=_FakeRequest(), db=db, current_user=advisor,
        )
        assert result.result_status == "Final"
