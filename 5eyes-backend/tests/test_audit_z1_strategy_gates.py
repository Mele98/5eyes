"""Z1 - Compliance-Gates auf direct create-Endpoints.

C1 - POST /mandates/{id}/recommendations:
  * Ohne RA -> 409
  * Body assessment_id != current -> 422
  * Body target_allocation_id stale/foreign -> 409
  * Body capital_market_assumptions_id != current -> 422
  * Glueck-Pfad mit korrekten IDs -> 201

C2 - POST /mandates/{id}/target-allocation:
  * Ohne RA -> 409 (= F4 Repeat aus audit-quick-fixes Logik, gleicher Helper)
  * Body based_on_assessment_id != current -> 422
  * Glueck-Pfad mit current RA -> 201
"""
from __future__ import annotations
import sys
import uuid
import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.allocation import (
    BuildingBlock,
    CapitalMarketAssumption,
    HouseMatrix,
    OptimizerPolicy,
    TargetAllocation,
)
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from services.auth import get_current_user, require_advisor
from services.portfolio_engine import ensure_runtime_reference_data
from tests.risk_fixture_helpers import CURRENT_RISK_SCHEMA_MARKERS, add_current_risk_answers, noop_lifespan


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_z1.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor():
    return User(id="user-z1-1", username="adv", password_hash="h",
                full_name="Adv", role="advisor", is_active=1,
                created_at=_now(), updated_at=_now())


@pytest.fixture()
def auth_client(session_factory, advisor, monkeypatch):
    def _odb():
        with session_factory() as s:
            yield s
    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    app.dependency_overrides[get_db] = _odb
    app.dependency_overrides[get_current_user] = lambda: advisor
    app.dependency_overrides[require_advisor] = lambda: advisor
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_client_and_mandate(session_factory, advisor):
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        if not s.query(User).filter(User.id == advisor.id).first():
            s.add(advisor)
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="T", last_name="X",
                     advisor_id=advisor.id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.commit()
    return cid, mid


def _seed_runtime(session_factory, advisor_id):
    with session_factory() as s:
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()


def _add_assessment(session_factory, mid, advisor_id, *, ready=True, is_current=1):
    aid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=is_current,
            valid_from=now[:10],
            q_income_points=2, q_obligations_points=3,
            q_savings_points=6, q_wealth_points=6,
            risk_capacity_total=17, risk_capacity_profile="Wachstumsorientiert",
            risk_capacity_score_x10=60,
            investment_horizon_years=10, investment_horizon_label="8 bis 11 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=3, q_risk_behavior_points=3,
            risk_willingness_total=9, risk_willingness_profile="Ausgewogen",
            risk_willingness_score_x10=60,
            final_score_x10=60 if ready else None,
            final_profile="Ausgewogen" if ready else None,
            is_overridden=0,
            **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        if ready:
            add_current_risk_answers(s, aid, now)
        s.commit()
    return aid


# ============================================================================
# Helper: TargetAllocationCreate-Body bauen
# ============================================================================
def _ta_body(policy_id, **overrides):
    base = dict(
        policy_id=policy_id,
        target_equities_bps=4500, target_bonds_bps=3500,
        target_real_estate_bps=1000, target_alternatives_bps=500,
        target_liquidity_bps=500,
        band_equities_min_bps=2500, band_equities_max_bps=5500,
        band_bonds_min_bps=2500, band_bonds_max_bps=4500,
        band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
        band_alternatives_min_bps=300, band_alternatives_max_bps=800,
        band_liquidity_min_bps=200, band_liquidity_max_bps=800,
    )
    base.update(overrides)
    return base


# ============================================================================
# C2 - create_target_allocation Hard-Gate
# ============================================================================

def test_c2_create_target_allocation_without_assessment_returns_409(
    auth_client, session_factory, advisor
):
    _seed_runtime(session_factory, advisor.id)
    cid, mid = _make_client_and_mandate(session_factory, advisor)
    with session_factory() as s:
        policy_id = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first().id
    resp = auth_client.post(f"/mandates/{mid}/target-allocation", json=_ta_body(policy_id))
    assert resp.status_code == 409, resp.text


def test_c2_create_target_allocation_with_mismatched_assessment_returns_422(
    auth_client, session_factory, advisor
):
    _seed_runtime(session_factory, advisor.id)
    cid, mid = _make_client_and_mandate(session_factory, advisor)
    aid = _add_assessment(session_factory, mid, advisor.id)
    with session_factory() as s:
        policy_id = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first().id
    body = _ta_body(policy_id, based_on_assessment_id=str(uuid.uuid4()))  # falsche ID
    resp = auth_client.post(f"/mandates/{mid}/target-allocation", json=body)
    assert resp.status_code == 422, resp.text


def test_c2_create_target_allocation_happy_path_returns_201(
    auth_client, session_factory, advisor
):
    _seed_runtime(session_factory, advisor.id)
    cid, mid = _make_client_and_mandate(session_factory, advisor)
    aid = _add_assessment(session_factory, mid, advisor.id)
    with session_factory() as s:
        policy_id = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first().id
    resp = auth_client.post(f"/mandates/{mid}/target-allocation", json=_ta_body(policy_id))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["based_on_assessment_id"] == aid, "autofill der current assessment-id"


# ============================================================================
# C1 - create_recommendation_run Hard-Gate
# ============================================================================

def _rec_body(policy_id, **overrides):
    base = dict(run_type="Optimizer", policy_id=policy_id)
    base.update(overrides)
    return base


def test_c1_create_run_without_assessment_returns_409(
    auth_client, session_factory, advisor
):
    _seed_runtime(session_factory, advisor.id)
    cid, mid = _make_client_and_mandate(session_factory, advisor)
    with session_factory() as s:
        policy_id = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first().id
    resp = auth_client.post(f"/mandates/{mid}/recommendations", json=_rec_body(policy_id))
    assert resp.status_code == 409, resp.text


def test_c1_create_run_with_foreign_target_allocation_returns_409(
    auth_client, session_factory, advisor
):
    _seed_runtime(session_factory, advisor.id)
    cid, mid = _make_client_and_mandate(session_factory, advisor)
    aid = _add_assessment(session_factory, mid, advisor.id)
    # Erzeuge TA fuer einen ANDEREN Mandanten
    cid2, mid2 = _make_client_and_mandate(session_factory, advisor)
    aid2 = _add_assessment(session_factory, mid2, advisor.id)
    with session_factory() as s:
        policy_id = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first().id
        foreign_ta = TargetAllocation(
            id=str(uuid.uuid4()), mandate_id=mid2, version=1, is_current=1,
            target_equities_bps=4500, target_bonds_bps=3500,
            target_real_estate_bps=1000, target_alternatives_bps=500,
            target_liquidity_bps=500,
            band_equities_min_bps=2500, band_equities_max_bps=5500,
            band_bonds_min_bps=2500, band_bonds_max_bps=4500,
            band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
            band_alternatives_min_bps=300, band_alternatives_max_bps=800,
            band_liquidity_min_bps=200, band_liquidity_max_bps=800,
            policy_id=policy_id, set_by=advisor.id, set_at=_now(),
            created_at=_now(), updated_at=_now(),
        )
        s.add(foreign_ta)
        s.commit()
        foreign_ta_id = foreign_ta.id

    body = _rec_body(policy_id, target_allocation_id=foreign_ta_id)
    resp = auth_client.post(f"/mandates/{mid}/recommendations", json=body)
    assert resp.status_code == 409, resp.text


def test_c1_create_run_with_mismatched_assessment_returns_422(
    auth_client, session_factory, advisor
):
    _seed_runtime(session_factory, advisor.id)
    cid, mid = _make_client_and_mandate(session_factory, advisor)
    aid = _add_assessment(session_factory, mid, advisor.id)
    with session_factory() as s:
        policy_id = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first().id
    body = _rec_body(policy_id, assessment_id=str(uuid.uuid4()))
    resp = auth_client.post(f"/mandates/{mid}/recommendations", json=body)
    assert resp.status_code == 422, resp.text


def test_c1_create_run_with_mismatched_cma_returns_422(
    auth_client, session_factory, advisor
):
    _seed_runtime(session_factory, advisor.id)
    cid, mid = _make_client_and_mandate(session_factory, advisor)
    aid = _add_assessment(session_factory, mid, advisor.id)
    with session_factory() as s:
        policy_id = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first().id
    body = _rec_body(policy_id, capital_market_assumptions_id=str(uuid.uuid4()))
    resp = auth_client.post(f"/mandates/{mid}/recommendations", json=body)
    assert resp.status_code == 422, resp.text


def test_c1_create_run_happy_path_autofills_current_anchors(
    auth_client, session_factory, advisor
):
    _seed_runtime(session_factory, advisor.id)
    cid, mid = _make_client_and_mandate(session_factory, advisor)
    aid = _add_assessment(session_factory, mid, advisor.id)
    with session_factory() as s:
        policy = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
        cma = s.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.is_current == 1).first()
        policy_id, cma_id = policy.id, cma.id
    body = _rec_body(policy_id)  # assessment_id und cma_id fehlen -> autofill
    resp = auth_client.post(f"/mandates/{mid}/recommendations", json=body)
    assert resp.status_code == 201, resp.text
    js = resp.json()
    assert js["assessment_id"] == aid
