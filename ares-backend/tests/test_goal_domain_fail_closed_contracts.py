"""Peer-review contracts for the complete Goal decision domain.

The API must validate the merged state of partial updates, and the allocation
engine must independently reject malformed rows inserted outside the API on
both Generate and Reload.  These tests intentionally do not patch production
validation code.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import services.portfolio_engine as pe
from database import Base, get_db
from main import app
from models.allocation import TargetAllocation
from models.mandates import Mandate
from models.users import User
from models.wealth import Goal
from services.auth import get_current_user
from test_optimizer_production_contract import (
    _generate,
    _install_solver_double,
    _preferences,
    _reload_payload,
    _seed_realistic_mandate,
)
from tests.risk_fixture_helpers import noop_lifespan


FINAL_WEIGHTS = {
    "equities": 5000,
    "bonds": 3000,
    "real_estate": 500,
    "alternatives": 1000,
    "liquidity": 500,
}


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_domain_contracts.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user() -> User:
    return User(
        id="goal-domain-advisor",
        username="goal-domain-advisor",
        password_hash="h",
        full_name="Goal Domain Advisor",
        role="advisor",
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user, monkeypatch):
    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def _create_api_mandate(auth_client: TestClient, advisor: User, suffix: str) -> str:
    client_response = auth_client.post(
        "/clients",
        json={
            "client_number": f"GOAL-{suffix}",
            "first_name": "Goal",
            "last_name": "Domain",
            "advisor_id": advisor.id,
            "household_type": "Einzelperson",
        },
    )
    assert client_response.status_code == 201, client_response.text
    mandate_response = auth_client.post(
        f"/clients/{client_response.json()['id']}/mandates",
        json={
            "mandate_number": f"GOAL-M-{suffix}",
            "mandate_type": "Anlageberatung",
        },
    )
    assert mandate_response.status_code == 201, mandate_response.text
    return mandate_response.json()["id"]


def _create_api_goal(auth_client: TestClient, mandate_id: str) -> dict:
    response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Vermögen",
            "goal_type": "Vermögensziel",
            "label": "Kapitalziel",
            "rank": 1,
            "weight_bps": 5000,
            "goal_scope": "Beratungsvermögen",
            "value_mode": "nominal",
            "target_wealth_rappen": 50_000_000,
            "target_date": "2035-01-01",
            "hardness": "Primär",
            "success_probability_min_x100": 8000,
            "probability_pct": 100,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_api_rejects_finite_recurring_goal_without_end_date(
    auth_client,
    advisor_user,
):
    mandate_id = _create_api_mandate(
        auth_client,
        advisor_user,
        "finite-recurring-no-end",
    )

    response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Cashflow",
            "goal_type": "Wiederkehrende_Ausgabe",
            "label": "Befristete Ausgabe ohne Enddatum",
            "rank": 1,
            "weight_bps": 5000,
            "goal_scope": "Beratungsvermögen",
            "value_mode": "nominal",
            "target_amount_rappen": 120_000,
            "start_date": "2030-01-01",
            "is_ongoing": False,
            "frequency": "jährlich",
            "hardness": "Primär",
        },
    )

    assert response.status_code == 422, response.text
    assert "target_date" in response.text or "Enddatum" in response.text


def test_api_rejects_non_recurring_goal_with_start_date_only(
    auth_client,
    advisor_user,
):
    mandate_id = _create_api_mandate(
        auth_client,
        advisor_user,
        "wealth-start-only",
    )

    response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Vermögen",
            "goal_type": "Vermögensziel",
            "label": "Vermögensziel ohne Bewertungsanker",
            "rank": 1,
            "weight_bps": 5000,
            "goal_scope": "Beratungsvermögen",
            "value_mode": "nominal",
            "target_wealth_rappen": 50_000_000,
            "start_date": "2030-01-01",
            "hardness": "Primär",
        },
    )

    assert response.status_code == 422, response.text
    assert "target_date" in response.text or "horizon" in response.text


def test_api_accepts_open_ended_recurring_goal_with_start_date(
    auth_client,
    advisor_user,
):
    mandate_id = _create_api_mandate(
        auth_client,
        advisor_user,
        "open-recurring-start",
    )

    response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Cashflow",
            "goal_type": "Wiederkehrende_Ausgabe",
            "label": "Offene wiederkehrende Ausgabe",
            "rank": 1,
            "weight_bps": 5000,
            "goal_scope": "Beratungsvermögen",
            "value_mode": "nominal",
            "target_amount_rappen": 120_000,
            "start_date": "2030-01-01",
            "is_ongoing": True,
            "frequency": "jährlich",
            "hardness": "Primär",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["start_date"] == "2030-01-01"
    assert response.json()["target_date"] is None


API_INVALID_UPDATES = (
    ("family_type_mismatch", {"goal_family": "Cashflow"}),
    ("hardness", {"hardness": "Beliebig"}),
    ("goal_scope", {"goal_scope": "Haushaltsvermögen"}),
    ("value_mode", {"value_mode": "inflationsnah"}),
    ("rank_low", {"rank": 0}),
    ("weight_low", {"weight_bps": -1}),
    ("weight_high", {"weight_bps": 10001}),
    ("success_probability_low", {"success_probability_min_x100": -1}),
    ("success_probability_high", {"success_probability_min_x100": 10001}),
    ("probability_low", {"probability_pct": -1}),
    ("probability_high", {"probability_pct": 101}),
    ("required_target_removed", {"target_wealth_rappen": None}),
    ("forbidden_target_added", {"target_amount_rappen": 10_000}),
    (
        "required_anchor_removed",
        {"target_date": None, "horizon_years": None},
    ),
    (
        "start_date_is_not_a_wealth_timing_anchor",
        {
            "start_date": "2030-01-01",
            "target_date": None,
            "horizon_years": None,
        },
    ),
    ("pension_pillar_on_non_pension", {"pension_pillar": "AHV"}),
)


@pytest.mark.parametrize("case_name,patch", API_INVALID_UPDATES)
def test_goal_update_validates_the_complete_merged_domain(
    auth_client,
    advisor_user,
    case_name,
    patch,
):
    mandate_id = _create_api_mandate(auth_client, advisor_user, case_name)
    goal = _create_api_goal(auth_client, mandate_id)

    response = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal['id']}",
        json=patch,
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "patch",
    [
        {"hardness": "Hart"},
        {"hardness": "Primaer"},
        {"hardness": "Primär"},
        {"hardness": "Opportunistisch"},
        {"goal_scope": "Beratungsvermögen"},
        {"goal_scope": "Beratungsvermoegen"},
        {"goal_scope": "Gesamtvermögen"},
        {"goal_scope": "Gesamtvermoegen"},
    ],
)
def test_goal_update_preserves_supported_german_and_legacy_spellings(
    auth_client,
    advisor_user,
    patch,
):
    suffix = str(abs(hash(tuple(patch.items()))))[-8:]
    mandate_id = _create_api_mandate(auth_client, advisor_user, suffix)
    goal = _create_api_goal(auth_client, mandate_id)

    response = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal['id']}",
        json=patch,
    )

    assert response.status_code == 200, response.text
    for field, value in patch.items():
        assert response.json()[field] == value


RAW_INVALID_CASES = (
    ("family_type_mismatch", r"goal_family|Zielfamilie|Zieltyp"),
    ("hardness", r"hardness|Haerte|Härte"),
    ("goal_scope", r"goal_scope|Ziel.?Scope|Vermoegen"),
    ("value_mode", r"value_mode|Wertmodus|nominal|real"),
    ("rank_low", r"rank|Rang"),
    ("weight_low", r"weight_bps|Gewicht"),
    ("weight_high", r"weight_bps|Gewicht"),
    ("success_probability_low", r"success_probability_min_x100|Erfolgswahrscheinlichkeit"),
    ("success_probability_high", r"success_probability_min_x100|Erfolgswahrscheinlichkeit"),
    ("probability_low", r"probability_pct|Wahrscheinlichkeit"),
    ("probability_high", r"probability_pct|Wahrscheinlichkeit"),
    ("missing_cashflow_target", r"target_amount_rappen|Zielbetrag|Cashflow"),
    ("forbidden_cashflow_target", r"target_wealth_rappen|Zielvermoegen|nicht erlaubt"),
    ("missing_return_target", r"target_return_bps|positive Zielrendite"),
    ("forbidden_return_target", r"target_amount_rappen|Zielbetrag|nicht erlaubt"),
    ("missing_wealth_target", r"target_wealth_rappen|Zielvermoegen|Vermoegensziel"),
    ("forbidden_maximize_target", r"target_amount_rappen|Zielwert|Maximierung"),
    ("missing_one_time_anchor", r"target_date|horizon|Zeithorizont|Datum"),
    ("missing_recurring_anchor", r"start_date|target_date|horizon|Zeithorizont|Datum"),
    ("finite_recurring_without_end", r"target_date|Enddatum|is_ongoing"),
    ("missing_wealth_anchor", r"target_date|horizon|Zeithorizont|Datum"),
    ("start_only_capital_preservation", r"target_date|horizon|Zeithorizont|Datum"),
    ("start_only_wealth_target", r"target_date|horizon|Zeithorizont|Datum"),
    ("start_only_one_time_expense", r"target_date|horizon|Zeithorizont|Datum"),
    ("start_only_return_target", r"target_date|horizon|Zeithorizont|Datum"),
    ("unknown_pension_pillar", r"pension_pillar|Vorsorge|Saeule|Säule"),
    ("pension_pillar_on_non_pension", r"pension_pillar|Pensionsausgabe|Saeule|Säule"),
)


def _mutate_raw_goal(goal: Goal, case: str) -> None:
    if case == "family_type_mismatch":
        goal.goal_family = "Vermögen"
    elif case == "hardness":
        goal.hardness = "Beliebig"
    elif case == "goal_scope":
        goal.goal_scope = "Haushaltsvermögen"
    elif case == "value_mode":
        goal.value_mode = "inflationsnah"
    elif case == "rank_low":
        goal.rank = 0
    elif case == "weight_low":
        goal.weight_bps = -1
    elif case == "weight_high":
        goal.weight_bps = 10001
    elif case == "success_probability_low":
        goal.success_probability_min_x100 = -1
    elif case == "success_probability_high":
        goal.success_probability_min_x100 = 10001
    elif case == "probability_low":
        goal.probability_pct = -1
    elif case == "probability_high":
        goal.probability_pct = 101
    elif case == "missing_cashflow_target":
        goal.target_amount_rappen = None
    elif case == "forbidden_cashflow_target":
        goal.target_wealth_rappen = 10_000
    elif case == "missing_return_target":
        goal.goal_family = "Rendite"
        goal.goal_type = "Renditeziel"
        goal.hardness = "Opportunistisch"
        goal.target_amount_rappen = None
        goal.target_return_bps = None
        goal.frequency = None
        goal.pension_pillar = None
    elif case == "forbidden_return_target":
        goal.goal_family = "Rendite"
        goal.goal_type = "Renditeziel"
        goal.hardness = "Opportunistisch"
        goal.target_return_bps = 450
        goal.frequency = None
        goal.pension_pillar = None
    elif case == "missing_wealth_target":
        goal.goal_family = "Vermögen"
        goal.goal_type = "Vermögensziel"
        goal.target_amount_rappen = None
        goal.target_wealth_rappen = None
        goal.frequency = None
        goal.pension_pillar = None
    elif case == "forbidden_maximize_target":
        goal.goal_family = "Maximierung"
        goal.goal_type = "Maximierung"
        goal.frequency = None
        goal.pension_pillar = None
    elif case == "missing_one_time_anchor":
        goal.goal_type = "Einmalige_Ausgabe"
        goal.frequency = None
        goal.is_ongoing = 0
        goal.start_date = None
        goal.target_date = None
        goal.horizon_years = None
        goal.pension_pillar = None
    elif case == "missing_recurring_anchor":
        goal.start_date = None
        goal.target_date = None
        goal.horizon_years = None
    elif case == "finite_recurring_without_end":
        goal.is_ongoing = 0
        goal.target_date = None
    elif case == "missing_wealth_anchor":
        goal.goal_family = "Vermögen"
        goal.goal_type = "Vermögensziel"
        goal.target_wealth_rappen = 10_000_000
        goal.target_amount_rappen = None
        goal.frequency = None
        goal.start_date = None
        goal.target_date = None
        goal.horizon_years = None
        goal.pension_pillar = None
    elif case in {
        "start_only_capital_preservation",
        "start_only_wealth_target",
        "start_only_one_time_expense",
        "start_only_return_target",
    }:
        goal.start_date = "2051-08-20"
        goal.target_date = None
        goal.horizon_years = None
        goal.is_ongoing = 0
        goal.frequency = None
        goal.pension_pillar = None
        goal.target_amount_rappen = None
        goal.target_wealth_rappen = None
        goal.target_return_bps = None
        if case == "start_only_capital_preservation":
            goal.goal_family = "Vermögen"
            goal.goal_type = "Kapitalerhalt"
            goal.target_wealth_rappen = 10_000_000
        elif case == "start_only_wealth_target":
            goal.goal_family = "Vermögen"
            goal.goal_type = "Vermögensziel"
            goal.target_wealth_rappen = 10_000_000
        elif case == "start_only_one_time_expense":
            goal.goal_family = "Cashflow"
            goal.goal_type = "Einmalige_Ausgabe"
            goal.target_amount_rappen = 1_000_000
        else:
            goal.goal_family = "Rendite"
            goal.goal_type = "Renditeziel"
            goal.hardness = "Opportunistisch"
            goal.target_return_bps = 450
    elif case == "unknown_pension_pillar":
        goal.pension_pillar = "XYZ"
    elif case == "pension_pillar_on_non_pension":
        goal.goal_type = "Wiederkehrende_Ausgabe"
        goal.pension_pillar = "AHV"
    else:
        raise AssertionError(f"unknown raw goal case: {case}")


def _seed_and_mutate_goal(session_factory, case: str, suffix: str):
    advisor_id, _client_id, mandate_id, _assessment_id, goal_id = (
        _seed_realistic_mandate(session_factory, suffix=suffix)
    )
    with session_factory() as session:
        goal = session.query(Goal).filter(Goal.id == goal_id).one()
        _mutate_raw_goal(goal, case)
        session.commit()
    return advisor_id, mandate_id, goal_id


@pytest.mark.parametrize("case,error_pattern", RAW_INVALID_CASES)
def test_generate_rejects_invalid_raw_goal_before_solver(
    session_factory,
    monkeypatch,
    case,
    error_pattern,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48)
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kwargs: {"goal_summaries": [], "current_goal_summaries": []},
    )
    advisor_id, mandate_id, _goal_id = _seed_and_mutate_goal(
        session_factory,
        case,
        suffix=f"goal-generate-{case}",
    )
    solver_calls = _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        before = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count()
        with pytest.raises(ValueError, match=error_pattern):
            pe.generate_target_allocation(
                session,
                mandate,
                advisor_id,
                preferences=_preferences(),
            )
        after = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count()

    assert solver_calls == []
    assert after == before


@pytest.mark.parametrize("case,error_pattern", RAW_INVALID_CASES)
def test_reload_rejects_invalid_raw_goal_before_analytics(
    session_factory,
    monkeypatch,
    case,
    error_pattern,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48)
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kwargs: {"goal_summaries": [], "current_goal_summaries": []},
    )
    advisor_id, _client_id, mandate_id, _assessment_id, goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix=f"goal-reload-{case}",
        )
    )
    _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )

    with session_factory() as session:
        goal = session.query(Goal).filter(Goal.id == goal_id).one()
        _mutate_raw_goal(goal, case)
        session.commit()
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        analytics_calls: list[dict] = []
        monkeypatch.setattr(
            pe,
            "_run_allocation_monte_carlo",
            lambda **kwargs: analytics_calls.append(kwargs) or {
                "goal_summaries": [],
                "current_goal_summaries": [],
            },
        )

        with pytest.raises(ValueError, match=error_pattern):
            _reload_payload(session, allocation)

    assert analytics_calls == []


@pytest.mark.parametrize(
    "hardness,goal_scope",
    [
        ("Primaer", "Beratungsvermoegen"),
        ("Primär", "Beratungsvermögen"),
        ("Hart", "Gesamtvermoegen"),
        ("Opportunistisch", "Gesamtvermögen"),
    ],
)
def test_generate_and_reload_preserve_legitimate_legacy_goal_spellings(
    session_factory,
    monkeypatch,
    hardness,
    goal_scope,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48)
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kwargs: {"goal_summaries": [], "current_goal_summaries": []},
    )
    suffix = f"goal-legacy-{abs(hash((hardness, goal_scope)))}"
    advisor_id, _client_id, mandate_id, _assessment_id, goal_id = (
        _seed_realistic_mandate(session_factory, suffix=suffix)
    )
    with session_factory() as session:
        goal = session.query(Goal).filter(Goal.id == goal_id).one()
        goal.hardness = hardness
        goal.goal_scope = goal_scope
        session.commit()

    solver_calls = _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )
    assert len(solver_calls) == 1

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        payload = _reload_payload(session, allocation)
        assert payload["target_allocation"].id == allocation.id
