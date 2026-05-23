from __future__ import annotations

import datetime
import random
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)

configure_mappers()

import services.portfolio_engine as pe
from models.allocation import BuildingBlock, HouseMatrix
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from models.wealth import WealthPosition
from services.allocation_messages import WARN_FALLBACK
from services.portfolio_engine import (
    build_target_payload_from_allocation,
    ensure_runtime_reference_data,
    generate_target_allocation,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'risk_budget_cap.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(autouse=True)
def fast_monte_carlo(monkeypatch):
    monkeypatch.setattr(pe, "_run_allocation_monte_carlo", lambda **_kwargs: {"goal_summaries": []})


def _prefs_for_equity(equity_bps: int) -> dict:
    liquidity = 100
    real_estate = 300
    alternatives = 100
    bonds = 10000 - int(equity_bps) - liquidity - real_estate - alternatives
    return {
        "policy": {},
        "tilts": {},
        "product": {},
        "limits": {},
        "geo": {},
        "assetClasses": {},
        "simulation": {"monteCarloRuns": 250},
        "bands": {
            "equities": {"target_bps": int(equity_bps)},
            "bonds": {"target_bps": int(bonds)},
            "real_estate": {"target_bps": real_estate},
            "alternatives": {"target_bps": alternatives},
            "liquidity": {"target_bps": liquidity},
        },
    }


def _seed_risk_cap_case(
    session,
    *,
    final_score_x10: int = 70,
    override_score_x10: int = 70,
    max_risky_bps: int = 7000,
):
    now = _now()
    advisor_id = "advisor-riskcap"
    client_id = "client-riskcap"
    mandate_id = "mandate-riskcap"
    assessment_id = "assessment-riskcap"
    session.add(User(
        id=advisor_id,
        username="advisor-riskcap",
        password_hash="h",
        full_name="Advisor Riskcap",
        role="advisor",
        is_active=1,
        created_at=now,
        updated_at=now,
    ))
    session.add(Client(
        id=client_id,
        client_number="C-RISKCAP",
        first_name="Risk",
        last_name="Cap",
        advisor_id=advisor_id,
        created_at=now,
        updated_at=now,
    ))
    session.add(Mandate(
        id=mandate_id,
        client_id=client_id,
        mandate_number="M-RISKCAP",
        mandate_type="Anlageberatung",
        opened_at=now,
        created_at=now,
        updated_at=now,
    ))
    session.add(RiskAssessment(
        id=assessment_id,
        mandate_id=mandate_id,
        version=1,
        is_current=1,
        valid_from=now[:10],
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        risk_capacity_total=32,
        risk_capacity_profile="Wachstumsorientiert",
        investment_horizon_years=15,
        investment_horizon_label="Mehr als 12 Jahre",
        risk_capacity_score_x10=final_score_x10,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        risk_willingness_total=12,
        risk_willingness_profile="Wachstumsorientiert",
        risk_willingness_score_x10=final_score_x10,
        final_score_x10=final_score_x10,
        final_profile="Wachstumsorientiert",
        is_overridden=1,
        override_score_x10=override_score_x10,
        override_profile="Wachstumsorientiert",
        override_reason="Test override fuer dokumentierte Strategie-Freigabe",
        override_client_confirmed=1,
        override_warning_delivered=1,
        knowledge_services_json="{}",
        knowledge_instruments_json="{}",
        income_sources_json="[]",
        assessed_at=now,
        assessed_by=advisor_id,
        created_at=now,
        updated_at=now,
    ))
    session.add(WealthPosition(
        id="pos-riskcap",
        client_id=client_id,
        label="Depot",
        position_type="Depot",
        assignment="Beratungsvermoegen",
        current_value_rappen=500_000_00,
        currency="CHF",
        alloc_equities_bps=0,
        alloc_bonds_bps=0,
        alloc_real_estate_bps=0,
        alloc_alternatives_bps=0,
        alloc_liquidity_bps=10000,
        is_active=1,
        created_at=now,
        updated_at=now,
    ))
    session.flush()
    policy, cma = ensure_runtime_reference_data(session, advisor_id)
    for row in session.query(BuildingBlock).filter(BuildingBlock.policy_id == policy.id).all():
        row.risky_fraction_bps = 10000 if row.asset_class == "Aktien" else 0
    score_bucket = max(1, min(10, int(round(int(override_score_x10) / 10))))
    house_matrix = session.query(HouseMatrix).filter(
        HouseMatrix.policy_id == policy.id,
        HouseMatrix.score_from <= score_bucket,
        HouseMatrix.score_to >= score_bucket,
        HouseMatrix.is_active == 1,
    ).one()
    house_matrix.liq_min_bps = 0
    house_matrix.liq_target_bps = 500
    house_matrix.liq_max_bps = 1500
    house_matrix.bonds_min_bps = 1000
    house_matrix.bonds_target_bps = 2500
    house_matrix.bonds_max_bps = 3500
    house_matrix.equity_min_bps = 4500
    house_matrix.equity_target_bps = 6000
    house_matrix.equity_max_bps = 7500
    house_matrix.equity_minimum_bps = 4500
    house_matrix.real_estate_min_bps = 0
    house_matrix.real_estate_target_bps = 700
    house_matrix.real_estate_max_bps = 1000
    house_matrix.alt_min_bps = 0
    house_matrix.alt_target_bps = 300
    house_matrix.alt_max_bps = 1000
    house_matrix.max_risky_fraction_bps = int(max_risky_bps)
    session.flush()
    return (
        session.query(Mandate).filter(Mandate.id == mandate_id).one(),
        policy,
        cma,
        session.query(RiskAssessment).filter(RiskAssessment.id == assessment_id).one(),
    )


def test_cap_breach_falls_back_to_house_matrix_mid(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    with session_factory() as session:
        mandate, _policy, _cma, _assessment = _seed_risk_cap_case(session)
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id="advisor-riskcap",
            preferences=_prefs_for_equity(7200),
        )
        ta = result["target_allocation"]

    assert result["risk_budget_bps"] == 7000
    assert result["risky_fraction_total_bps"] <= 7000
    assert ta.risky_fraction_bps_at_generation <= ta.risk_budget_bps_at_generation
    assert ta.optimization_method == "fallback_house_matrix"
    assert ta.optimization_status == "fallback_house_matrix"
    assert any(message.get("code") == WARN_FALLBACK for message in result["warnings"])


def test_ok_allocation_persists_risk_budget_fields_and_reload_payload(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    prefs = _prefs_for_equity(6800)
    with session_factory() as session:
        mandate, policy, cma, assessment = _seed_risk_cap_case(session)
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id="advisor-riskcap",
            preferences=prefs,
        )
        ta = result["target_allocation"]
        reloaded = build_target_payload_from_allocation(
            session,
            mandate,
            ta,
            policy,
            cma,
            assessment,
            prefs,
        )

    assert result["warnings"] == []
    assert ta.optimization_status is None
    assert ta.risky_fraction_bps_at_generation == 6800
    assert ta.risk_budget_bps_at_generation == 7000
    assert ta.limiting_factor == "bandbreite"
    assert reloaded["risky_fraction_total_bps"] == 6800
    assert reloaded["risk_budget_bps"] == 7000


def test_cap_binding_sets_limiting_factor(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    with session_factory() as session:
        mandate, _policy, _cma, _assessment = _seed_risk_cap_case(session)
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id="advisor-riskcap",
            preferences=_prefs_for_equity(6995),
        )
        ta = result["target_allocation"]

    assert result["risky_fraction_total_bps"] == 6995
    assert result["limiting_factor"] == "risikoprofil"
    assert ta.limiting_factor == "risikoprofil"


def test_risk_override_score_selects_risk_budget_bucket(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    with session_factory() as session:
        mandate, _policy, _cma, _assessment = _seed_risk_cap_case(
            session,
            final_score_x10=20,
            override_score_x10=70,
        )
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id="advisor-riskcap",
            preferences=_prefs_for_equity(6800),
        )

    assert result["score_bucket"] == 7
    assert result["risk_budget_bps"] == 7000
    assert result["risky_fraction_total_bps"] == 6800


@pytest.mark.parametrize("mode", ["house_matrix", "stochastic"])
def test_cap_is_active_in_house_matrix_and_stochastic_modes(session_factory, monkeypatch, mode):
    monkeypatch.setattr(pe.settings, "optimizer_mode", mode)
    monkeypatch.setattr(pe, "_run_stochastic_optimizer_pass", lambda **_kwargs: None)
    with session_factory() as session:
        mandate, _policy, _cma, _assessment = _seed_risk_cap_case(session)
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id="advisor-riskcap",
            preferences=_prefs_for_equity(7200),
        )

    assert result["risky_fraction_total_bps"] <= result["risk_budget_bps"]
    assert result["target_allocation"].optimization_status == "fallback_house_matrix"
    assert any(message.get("code") == WARN_FALLBACK for message in result["warnings"])


def test_generated_allocations_never_exceed_persisted_risk_budget(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    rng = random.Random(20260523)
    with session_factory() as session:
        mandate, _policy, _cma, _assessment = _seed_risk_cap_case(session)
        for _idx in range(20):
            equity_bps = rng.randint(6000, 7500)
            result = generate_target_allocation(
                db=session,
                mandate=mandate,
                user_id="advisor-riskcap",
                preferences=_prefs_for_equity(equity_bps),
            )
            ta = result["target_allocation"]
            assert ta.risky_fraction_bps_at_generation <= ta.risk_budget_bps_at_generation
            assert result["risky_fraction_total_bps"] <= result["risk_budget_bps"]
