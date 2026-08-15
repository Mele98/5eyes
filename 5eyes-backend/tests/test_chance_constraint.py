from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import numpy as np
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
from services.allocation_messages import CONFLICT_PROFILE_LIMITS
from models.allocation import BuildingBlock, HouseMatrix, TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from models.wealth import Goal, WealthPosition
from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.objective import chance_constraint_penalty, goal_probability_per_path
from services.optimizer.solver import OptimizerResult
from services.portfolio_engine import (
    build_target_payload_from_allocation,
    ensure_runtime_reference_data,
    generate_target_allocation,
)
from services.risk_matrix import classify_limiting_factor


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _liability(
    *,
    target_kind: str = "wealth_at_t",
    target_amount_rappen: int = 100_000_00,
    target_year_index: int = 5,
    hardness: str = "hart",
    tau_x100: int = 8000,
) -> GoalLiability:
    return GoalLiability(
        goal_id=f"g-{target_kind}",
        label=f"Goal {target_kind}",
        goal_type="Renditeziel" if target_kind == "return_rate" else "Vermoegensziel",
        target_kind=target_kind,
        target_amount_rappen=target_amount_rappen,
        target_year_index=target_year_index,
        liability_path_rappen=[0] * 10,
        hardness_key=hardness,
        weight_bps=10000,
        success_probability_min_x100=tau_x100,
    )


def test_chance_penalty_zero_when_all_paths_reach_target():
    wealth_paths = np.full((2000, 11), 150_000_00, dtype=np.float64)
    penalty, rows = chance_constraint_penalty(
        wealth_paths,
        [_liability(target_amount_rappen=100_000_00)],
        initial_value_rappen=100_000_00,
    )
    assert penalty == 0.0
    assert rows[0]["probability"] == pytest.approx(1.0)
    assert rows[0]["status"] == "erreichbar"


def test_chance_penalty_full_shortfall_matches_lambda_tau_squared():
    wealth_paths = np.full((2000, 11), 50_000_00, dtype=np.float64)
    penalty, rows = chance_constraint_penalty(
        wealth_paths,
        [_liability(target_amount_rappen=100_000_00, tau_x100=8000)],
        initial_value_rappen=100_000_00,
    )
    assert rows[0]["probability"] == pytest.approx(0.0)
    assert rows[0]["status"] == "nicht_erreichbar"
    assert penalty == pytest.approx(1_000_000.0 * 0.8 * 0.8)


def test_chance_penalty_zero_when_probability_equals_tau():
    wealth_paths = np.full((2000, 11), 50_000_00, dtype=np.float64)
    wealth_paths[:1600, 5] = 100_000_00
    penalty, rows = chance_constraint_penalty(
        wealth_paths,
        [_liability(target_amount_rappen=100_000_00, tau_x100=8000)],
        initial_value_rappen=100_000_00,
    )
    assert rows[0]["probability"] == pytest.approx(0.8)
    assert rows[0]["status"] == "erreichbar"
    assert penalty == pytest.approx(0.0)


def test_opportunistic_goals_do_not_add_penalty():
    wealth_paths = np.full((2000, 11), 50_000_00, dtype=np.float64)
    penalty, rows = chance_constraint_penalty(
        wealth_paths,
        [_liability(target_amount_rappen=100_000_00, hardness="opportunistisch")],
        initial_value_rappen=100_000_00,
    )
    assert rows[0]["status"] == "nicht_erreichbar"
    assert penalty == 0.0


@pytest.mark.parametrize(
    ("reached", "expected"),
    [
        (1700, "erreichbar"),
        (1300, "knapp"),
        (840, "nicht_erreichbar"),
    ],
)
def test_chance_status_thresholds(reached, expected):
    wealth_paths = np.full((2000, 11), 50_000_00, dtype=np.float64)
    wealth_paths[:reached, 5] = 100_000_00
    _penalty, rows = chance_constraint_penalty(
        wealth_paths,
        [_liability(target_amount_rappen=100_000_00, tau_x100=8000)],
        initial_value_rappen=100_000_00,
    )
    assert rows[0]["status"] == expected


def test_return_goal_is_implicit_wealth_target():
    initial = 100_000_00
    target_wealth = int(round(initial * (1.05 ** 10)))
    wealth_paths = np.full((2000, 11), target_wealth - 10_000, dtype=np.float64)
    wealth_paths[:1000, 10] = target_wealth + 10_000
    per_path = goal_probability_per_path(
        wealth_paths,
        _liability(
            target_kind="return_rate",
            target_amount_rappen=500,
            target_year_index=10,
            tau_x100=5000,
        ),
        initial_value_rappen=initial,
    )
    assert int(round(target_wealth / 100)) == 162889
    assert float(np.mean(per_path)) == pytest.approx(0.5)


def test_limiting_factor_classification_cases():
    base = {
        "allocation_bps": {"equities": 6000, "bonds": 3000, "real_estate": 500, "alternatives": 400, "liquidity": 100},
        "risky_fraction": 6000,
        "max_risky_fraction": 7000,
        "min_liquidity_bps": 0,
        "bands": {},
        "achievability": [],
        "optimization_status": "converged",
    }
    assert classify_limiting_factor(**{**base, "optimization_status": "fallback_house_matrix"}) == "solver_konvergenz"
    assert classify_limiting_factor(**{
        **base,
        "achievability": [
            {"status": "nicht_erreichbar", "hardness": "hart"},
            {"status": "nicht_erreichbar", "hardness": "primär"},
        ],
    }) == "zielkonflikt"
    assert classify_limiting_factor(**{
        **base,
        "risky_fraction": 6975,
        "achievability": [{"status": "nicht_erreichbar", "hardness": "hart"}],
    }) == "risikoprofil"
    assert classify_limiting_factor(**{
        **base,
        "allocation_bps": {**base["allocation_bps"], "liquidity": 200},
        "min_liquidity_bps": 200,
    }) == "liquiditaetsreserve"
    assert classify_limiting_factor(**base) == "bandbreite"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'chance_constraint.db'}",
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


def _seed_return_goal_case(session):
    now = _now()
    advisor_id = "advisor-stage3"
    client_id = "client-stage3"
    mandate_id = "mandate-stage3"
    session.add(User(
        id=advisor_id,
        username="advisor-stage3",
        password_hash="h",
        full_name="Advisor Stage3",
        role="advisor",
        is_active=1,
        created_at=now,
        updated_at=now,
    ))
    session.add(Client(
        id=client_id,
        client_number="C-STAGE3",
        first_name="Chance",
        last_name="Constraint",
        advisor_id=advisor_id,
        created_at=now,
        updated_at=now,
    ))
    session.add(Mandate(
        id=mandate_id,
        client_id=client_id,
        mandate_number="M-STAGE3",
        mandate_type="Anlageberatung",
        opened_at=now,
        created_at=now,
        updated_at=now,
    ))
    session.add(RiskAssessment(
        id="assessment-stage3",
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
        risk_capacity_score_x10=70,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        risk_willingness_total=12,
        risk_willingness_profile="Wachstumsorientiert",
        risk_willingness_score_x10=70,
        final_score_x10=70,
        final_profile="Wachstumsorientiert",
        is_overridden=1,
        override_score_x10=70,
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
        id="pos-stage3",
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
    session.add(Goal(
        id="goal-return-stage3",
        mandate_id=mandate_id,
        client_id=client_id,
        goal_family="Rendite",
        goal_type="Renditeziel",
        label="Ambitioniertes Renditeziel",
        rank=1,
        weight_bps=10000,
        goal_scope="Beratungsvermoegen",
        value_mode="nominal",
        target_return_bps=2500,
        horizon_years=10,
        hardness="Primaer",
        success_probability_min_x100=5000,
        is_active=1,
        created_at=now,
        updated_at=now,
    ))
    session.flush()
    policy, cma = ensure_runtime_reference_data(session, advisor_id)
    for row in session.query(BuildingBlock).filter(BuildingBlock.policy_id == policy.id).all():
        row.risky_fraction_bps = 10000 if row.asset_class == "Aktien" else 0
    house_matrix = session.query(HouseMatrix).filter(
        HouseMatrix.policy_id == policy.id,
        HouseMatrix.score_from <= 7,
        HouseMatrix.score_to >= 7,
        HouseMatrix.is_active == 1,
    ).one()
    house_matrix.liq_min_bps = 0
    house_matrix.liq_target_bps = 100
    house_matrix.liq_max_bps = 1000
    house_matrix.bonds_min_bps = 1000
    house_matrix.bonds_target_bps = 2705
    house_matrix.bonds_max_bps = 3500
    house_matrix.equity_min_bps = 4500
    house_matrix.equity_target_bps = 6995
    house_matrix.equity_max_bps = 7500
    house_matrix.equity_minimum_bps = 4500
    house_matrix.real_estate_min_bps = 0
    house_matrix.real_estate_target_bps = 100
    house_matrix.real_estate_max_bps = 1000
    house_matrix.alt_min_bps = 0
    house_matrix.alt_target_bps = 100
    house_matrix.alt_max_bps = 1000
    house_matrix.max_risky_fraction_bps = 7000
    session.flush()
    return (
        session.query(Mandate).filter(Mandate.id == mandate_id).one(),
        policy,
        cma,
        session.query(RiskAssessment).filter(RiskAssessment.id == "assessment-stage3").one(),
    )


def test_generate_persists_achievability_and_reload_returns_same(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")

    achievability = [{
        "goal_id": "goal-return-stage3",
        "label": "Ambitioniertes Renditeziel",
        "target_kind": "return_rate",
        "probability": 0.42,
        "tau": 0.5,
        "status": "nicht_erreichbar",
        "hardness": "primär",
    }]

    def _fake_solver_pass(**kwargs):
        targets = kwargs["targets"]
        targets.update({
            "equities": 6995,
            "bonds": 2605,
            "real_estate": 100,
            "alternatives": 100,
            "liquidity": 200,
        })
        return OptimizerResult(
            weights_bps=dict(targets),
            objective_value=123.0,
            iterations=1,
            seed=42,
            status="converged",
            method="stochastic",
            reasoning=["fake stochastic stage3"],
            n_paths=2000,
            n_starts_attempted=1,
            goal_achievability=tuple(achievability),
        )

    monkeypatch.setattr(pe, "_run_stochastic_optimizer_pass", _fake_solver_pass)

    with session_factory() as session:
        mandate, policy, cma, assessment = _seed_return_goal_case(session)
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id="advisor-stage3",
            preferences=None,
        )
        session.commit()
        ta = session.query(TargetAllocation).filter(TargetAllocation.mandate_id == mandate.id).one()
        reloaded = build_target_payload_from_allocation(
            session,
            mandate,
            ta,
            policy,
            cma,
            assessment,
            preferences=None,
        )

    assert result["goal_achievability"][0]["status"] == "nicht_erreichbar"
    assert result["limiting_factor"] == "risikoprofil"
    assert CONFLICT_PROFILE_LIMITS in [msg["code"] for msg in result["messages"]]
    assert json.loads(ta.goal_achievability_json) == achievability
    assert reloaded["goal_achievability"] == achievability
    assert reloaded["limiting_factor"] == "risikoprofil"
    assert reloaded["messages"] == result["messages"]
