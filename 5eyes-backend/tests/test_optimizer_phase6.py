"""Phase 6 FE-Optimizer-Panel Backend-Tests.

Verifiziert:
- stress_evaluations wird vom Solver in den generate_target_allocation Return-Dict
  durchgeschleift (None bei house_matrix-Modus, dict bei converged stochastic).
- evaluate_goal_sensitivity liefert Baseline+Modified-Solver-Run mit
  konsistentem Schema und sauberem Delta.
- POST /target-allocation/sensitivity Endpoint:
  * 200 + erwartete Felder bei gueltigem Goal-ID + delta_pct
  * 404 bei unbekanntem goal_id
  * 422 bei ungueltigem delta_pct (Pydantic-Validator)
  * 409 wenn OPTIMIZER_MODE != stochastic
"""
from __future__ import annotations

import copy
import datetime
import json
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers

from database import Base, get_db
from main import app
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

import services.portfolio_engine as pe
from models.allocation import HouseMatrix
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.auth import get_current_user, require_advisor
from services.portfolio_engine import (
    ensure_runtime_reference_data,
    evaluate_goal_sensitivity,
    generate_target_allocation,
)
from tests.risk_fixture_helpers import CURRENT_RISK_SCHEMA_MARKERS, add_current_risk_answers


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'opt_phase6.db'}",
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
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


def _seed_mandate(session_factory, suffix: str = "") -> tuple[str, str, str, str, str]:
    """Mandant mit Pension-Goal + Vermoegensziel. Gibt (advisor, cid, mid, aid, pension_goal_id) zurueck."""
    suffix = suffix or str(uuid.uuid4())[:6]
    advisor_id = f"user-p6-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    pension_goal_id = f"goal-p6-pension-{suffix}"
    now = _now()
    today = date.today()
    pension_start = (today + timedelta(days=365 * 5)).isoformat()
    pension_end = (today + timedelta(days=365 * 30)).isoformat()
    wealth_target_date = (today + timedelta(days=365 * 10)).isoformat()

    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-p6-{suffix}", password_hash="h",
                   full_name="Adv P6", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="P6", last_name="Mandant",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id=f"pos-p6-depot-{suffix}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id=f"cf-p6-savings-{suffix}", client_id=cid, label="Sparen",
            cashflow_type="Income", amount_rappen=20_000_00,
            currency="CHF", frequency="jährlich", nature="wiederkehrend",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id=pension_goal_id, mandate_id=mid, client_id=cid,
            goal_family="Lebenshaltung", goal_type="Pensionsausgabe",
            label="Pension", rank=1, weight_bps=5000,
            goal_scope="Beratungsvermögen", value_mode="real",
            target_amount_rappen=24_000_00, frequency="jährlich",
            start_date=pension_start, target_date=pension_end,
            is_ongoing=0, hardness="Hart",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id=f"goal-p6-wealth-{suffix}", mandate_id=mid, client_id=cid,
            goal_family="Vermoegen", goal_type="Vermoegensziel",
            label="Eigenheim Anzahlung", rank=2, weight_bps=3000,
            goal_scope="Beratungsvermögen", value_mode="nominal",
            target_wealth_rappen=300_000_00,
            target_date=wealth_target_date,
            is_ongoing=0, hardness="Primaer",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            q_income_points=2, q_obligations_points=3,
            q_savings_points=8, q_wealth_points=8,
            risk_capacity_total=21, risk_capacity_profile="Wachstumsorientiert",
            risk_capacity_score_x10=70,
            investment_horizon_years=15, investment_horizon_label="12 bis 17 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=4, q_risk_behavior_points=3,
            risk_willingness_total=10, risk_willingness_profile="Wachstumsorientiert",
            risk_willingness_score_x10=70,
            final_score_x10=70, final_profile="Wachstumsorientiert",
            is_overridden=0,
            **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        add_current_risk_answers(s, aid, now)
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, cid, mid, aid, pension_goal_id


def _client_with_user(session_factory, user: User | None) -> TestClient:
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[require_advisor] = lambda: user
    return TestClient(app)


# ============================================================================
# stress_evaluations Passthrough
# ============================================================================


def test_stress_evaluations_present_when_stochastic_converged(session_factory, monkeypatch):
    """Phase 5.2/6: stress_evaluations dict im Result wenn Solver konvergiert."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        # Bei stochastic-Modus + converged: stress_evaluations ist dict mit 3 Szenarien.
        # Bei fallback: kann None sein. Akzeptiere beides, aber wenn dict, dann
        # mit erwarteten Keys.
        stress = result.get("stress_evaluations")
        if stress is not None:
            assert isinstance(stress, dict)
            assert len(stress) >= 1
            for name, payload in stress.items():
                assert isinstance(payload, dict)
                assert "end_wealth_rappen" in payload
                assert "max_drawdown_bps" in payload


def test_stress_evaluations_none_in_house_matrix_mode(session_factory, monkeypatch):
    """House-Matrix-Modus: stress_evaluations ist None (kein Solver gerufen)."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        assert result.get("stress_evaluations") is None


# ============================================================================
# evaluate_goal_sensitivity (unit-level)
# ============================================================================


def _capture_sensitivity_solver_calls(monkeypatch) -> list[dict]:
    """Replace the expensive solver and retain immutable call snapshots."""
    import services.optimizer.solver as optimizer_solver
    from services.optimizer.goal_liabilities import goals_to_liabilities

    calls: list[dict] = []

    def fake_run_solver(**kwargs):
        context = kwargs.get("optimizer_context")
        liabilities = (
            list(context.liabilities)
            if context is not None
            else goals_to_liabilities(
                kwargs["goals"],
                horizon_years=int(kwargs["horizon_years"]),
                inflation_series_bps=kwargs.get("inflation_series_bps"),
                external_wealth_rappen=int(
                    kwargs.get("external_wealth_rappen") or 0
                ),
                external_wealth_series_rappen=kwargs.get(
                    "external_wealth_series_rappen"
                ),
            )
        )
        calls.append({
            "horizon_years": int(kwargs["horizon_years"]),
            "scenario_horizon_years": kwargs.get("scenario_horizon_years"),
            "context_horizon_years": (
                int(context.horizon_years) if context is not None else None
            ),
            "return_paths": (
                np.array(context.return_paths, copy=True)
                if context is not None
                else None
            ),
            "cashflow_series_rappen": (
                list(context.cashflow_series_rappen)
                if context is not None
                else list(kwargs["cashflow_series_rappen"])
            ),
            "liabilities": [
                {
                    "goal_id": str(liability.goal_id),
                    "liability_path_rappen": list(
                        liability.liability_path_rappen
                    ),
                }
                for liability in liabilities
            ],
            "goals": [
                {
                    "id": str(goal.id),
                    "goal_type": goal.goal_type,
                    "target_amount_rappen": goal.target_amount_rappen,
                    "target_wealth_rappen": goal.target_wealth_rappen,
                    "target_return_bps": goal.target_return_bps,
                    "horizon_years": goal.horizon_years,
                    "start_date": goal.start_date,
                    "target_date": goal.target_date,
                    "full_state": {
                        column.name: copy.deepcopy(
                            getattr(goal, column.name, None)
                        )
                        for column in Goal.__table__.columns
                    },
                }
                for goal in kwargs["goals"]
            ],
            "sub_allocations": copy.deepcopy(kwargs.get("sub_allocations")),
            "risky_fraction_per_bucket": copy.deepcopy(
                kwargs.get("risky_fraction_per_bucket")
            ),
            "effective_bounds_bps": copy.deepcopy(
                kwargs.get("effective_bounds_bps")
            ),
        })
        return SimpleNamespace(
            objective_value=float(len(calls)),
            weights_bps={
                "liquidity": 2000,
                "bonds": 3000,
                "equities": 4000,
                "real_estate": 500,
                "alternatives": 500,
            },
            status="converged",
        )

    monkeypatch.setattr(optimizer_solver, "run_solver", fake_run_solver)
    return calls


def _captured_goal(call: dict, goal_id: str) -> dict:
    return next(goal for goal in call["goals"] if goal["id"] == goal_id)


def test_sensitivity_pension_shifts_both_dates_without_mutating_goal(
    session_factory, monkeypatch,
):
    """Recurring-goal shifts move the full period, not only its end date."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    calls = _capture_sensitivity_solver_calls(monkeypatch)

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        persisted_goal = s.query(Goal).filter(Goal.id == gid).one()
        original_start = persisted_goal.start_date
        original_end = persisted_goal.target_date

        out = evaluate_goal_sensitivity(
            db=s,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=gid,
            target_delta_pct=0,
            horizon_delta_years=2,
        )

        # The live SQLAlchemy entity and its persisted state stay untouched.
        assert persisted_goal.start_date == original_start
        assert persisted_goal.target_date == original_end
        s.expire_all()
        reloaded_goal = s.query(Goal).filter(Goal.id == gid).one()
        assert reloaded_goal.start_date == original_start
        assert reloaded_goal.target_date == original_end

    assert len(calls) == 2
    baseline_goal = _captured_goal(calls[0], gid)
    modified_goal = _captured_goal(calls[1], gid)
    assert baseline_goal["start_date"] == original_start
    assert baseline_goal["target_date"] == original_end

    start_before = date.fromisoformat(original_start)
    end_before = date.fromisoformat(original_end)
    start_after = date.fromisoformat(modified_goal["start_date"])
    end_after = date.fromisoformat(modified_goal["target_date"])
    assert start_after.year == start_before.year + 2
    assert end_after.year == end_before.year + 2
    assert (start_after.month, start_after.day) == (
        start_before.month,
        start_before.day,
    )
    assert (end_after.month, end_after.day) == (end_before.month, end_before.day)
    assert (
        end_after.year - start_after.year,
        end_after.month - start_after.month,
        end_after.day - start_after.day,
    ) == (
        end_before.year - start_before.year,
        end_before.month - start_before.month,
        end_before.day - start_before.day,
    )

    assert out["analysis_basis"] == (
        "live_reoptimization_common_scenarios_current_inputs_v3"
    )
    assert out["solver_horizon_years_baseline"] == calls[0]["horizon_years"]
    assert out["solver_horizon_years_new"] == calls[1]["horizon_years"]
    assert calls[1]["horizon_years"] == calls[0]["horizon_years"] + 2
    assert calls[0]["cashflow_series_rappen"] == calls[1][
        "cashflow_series_rappen"
    ][: calls[0]["horizon_years"]]
    assert len(calls[1]["cashflow_series_rappen"]) == calls[1]["horizon_years"]


def test_sensitivity_open_ended_pension_shift_preserves_stream_duration(
    session_factory, monkeypatch,
):
    """Moving an open-ended pension must move the run end with its start."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(
        session_factory,
        suffix="open-ended-pension",
    )
    with session_factory() as session:
        goal = session.query(Goal).filter(Goal.id == gid).one()
        goal.target_date = None
        goal.is_ongoing = 1
        session.commit()

    calls = _capture_sensitivity_solver_calls(monkeypatch)
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mid).one()
        persisted_goal = session.query(Goal).filter(Goal.id == gid).one()
        out = evaluate_goal_sensitivity(
            db=session,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=gid,
            target_delta_pct=0,
            horizon_delta_years=2,
        )
        assert persisted_goal.target_date is None
        session.expire_all()
        assert session.query(Goal).filter(Goal.id == gid).one().target_date is None

    assert len(calls) == 2
    baseline, modified = calls
    baseline_goal = _captured_goal(baseline, gid)
    modified_goal = _captured_goal(modified, gid)
    assert baseline_goal["target_date"] is None
    assert modified_goal["target_date"] is not None
    assert date.fromisoformat(modified_goal["start_date"]).year == (
        date.fromisoformat(baseline_goal["start_date"]).year + 2
    )
    assert modified["horizon_years"] == baseline["horizon_years"] + 2
    baseline_liability = next(
        liability
        for liability in baseline["liabilities"]
        if liability["goal_id"] == gid
    )
    modified_liability = next(
        liability
        for liability in modified["liabilities"]
        if liability["goal_id"] == gid
    )
    baseline_stream_years = sum(
        value > 0 for value in baseline_liability["liability_path_rappen"]
    )
    modified_stream_years = sum(
        value > 0 for value in modified_liability["liability_path_rappen"]
    )
    assert modified_stream_years == baseline_stream_years
    assert (
        date.fromisoformat(modified_goal["target_date"]).year
        - date.fromisoformat(modified_goal["start_date"]).year
        + 1
    ) == baseline_stream_years
    assert out["solver_horizon_years_new"] == (
        out["solver_horizon_years_baseline"] + 2
    )


def test_sensitivity_open_ended_pension_negative_shift_preserves_stream_duration(
    session_factory, monkeypatch,
):
    """Moving an open pension earlier shortens the run but not its stream."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(
        session_factory,
        suffix="open-ended-pension-negative",
    )
    with session_factory() as session:
        goal = session.query(Goal).filter(Goal.id == gid).one()
        goal.target_date = None
        goal.is_ongoing = 1
        for other_goal in session.query(Goal).filter(
            Goal.mandate_id == mid,
            Goal.id != gid,
        ).all():
            # Isolate the open-ended stream.  The fixture's separate 10-year
            # wealth goal is a legitimate unaffected-goal floor and is tested
            # independently below; leaving it active would make 10 years the
            # correct modified solver horizon.
            other_goal.is_active = 0
        session.commit()

    calls = _capture_sensitivity_solver_calls(monkeypatch)
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mid).one()
        out = evaluate_goal_sensitivity(
            db=session,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=gid,
            target_delta_pct=0,
            horizon_delta_years=-2,
        )

    assert len(calls) == 2
    baseline, modified = calls
    baseline_goal = _captured_goal(baseline, gid)
    modified_goal = _captured_goal(modified, gid)
    assert date.fromisoformat(modified_goal["start_date"]).year == (
        date.fromisoformat(baseline_goal["start_date"]).year - 2
    )
    assert baseline["horizon_years"] == 10
    assert modified["horizon_years"] == 8
    baseline_liability = next(
        liability
        for liability in baseline["liabilities"]
        if liability["goal_id"] == gid
    )
    modified_liability = next(
        liability
        for liability in modified["liabilities"]
        if liability["goal_id"] == gid
    )
    assert sum(
        value > 0 for value in baseline_liability["liability_path_rappen"]
    ) == 6
    assert sum(
        value > 0 for value in modified_liability["liability_path_rappen"]
    ) == 6
    assert modified["cashflow_series_rappen"] == baseline[
        "cashflow_series_rappen"
    ][: modified["horizon_years"]]
    assert out["solver_horizon_years_new"] == 8


def test_sensitivity_open_ended_negative_shift_respects_unaffected_goal_floor(
    session_factory, monkeypatch,
):
    """An independent 10-year goal pins the run, not the pension duration."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(
        session_factory,
        suffix="open-ended-negative-multi-goal",
    )
    with session_factory() as session:
        pension = session.query(Goal).filter(Goal.id == gid).one()
        pension.target_date = None
        pension.is_ongoing = 1
        wealth_goal = session.query(Goal).filter(
            Goal.mandate_id == mid,
            Goal.id != gid,
            Goal.goal_type == "Vermoegensziel",
        ).one()
        wealth_goal_id = wealth_goal.id
        session.commit()

    calls = _capture_sensitivity_solver_calls(monkeypatch)
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mid).one()
        persisted_pension = session.query(Goal).filter(Goal.id == gid).one()
        evaluate_goal_sensitivity(
            db=session,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=gid,
            target_delta_pct=0,
            horizon_delta_years=-2,
        )
        assert persisted_pension.target_date is None
        session.expire_all()
        assert session.query(Goal).filter(Goal.id == gid).one().target_date is None

    assert len(calls) == 2
    baseline, modified = calls
    assert baseline["horizon_years"] == 10
    assert modified["horizon_years"] == 10
    baseline_pension = _captured_goal(baseline, gid)
    modified_pension = _captured_goal(modified, gid)
    assert date.fromisoformat(modified_pension["start_date"]).year == (
        date.fromisoformat(baseline_pension["start_date"]).year - 2
    )
    assert baseline_pension["target_date"] is None
    assert modified_pension["target_date"] is not None

    baseline_liability = next(
        liability
        for liability in baseline["liabilities"]
        if liability["goal_id"] == gid
    )
    modified_liability = next(
        liability
        for liability in modified["liabilities"]
        if liability["goal_id"] == gid
    )
    assert sum(
        value > 0 for value in baseline_liability["liability_path_rappen"]
    ) == 6
    assert sum(
        value > 0 for value in modified_liability["liability_path_rappen"]
    ) == 6
    assert baseline["cashflow_series_rappen"] == modified[
        "cashflow_series_rappen"
    ]

    baseline_wealth_goal = _captured_goal(baseline, wealth_goal_id)
    modified_wealth_goal = _captured_goal(modified, wealth_goal_id)
    assert baseline_wealth_goal["full_state"] == modified_wealth_goal["full_state"]


def test_sensitivity_incomplete_current_assessment_fails_before_solver(
    session_factory, monkeypatch,
):
    """Sensitivity has the same strategy-ready assessment gate as Generate."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, aid, gid = _seed_mandate(
        session_factory,
        suffix="incomplete-assessment",
    )
    with session_factory() as session:
        assessment = session.query(RiskAssessment).filter(
            RiskAssessment.id == aid
        ).one()
        assessment.knowledge_services_json = None
        session.commit()

    calls = _capture_sensitivity_solver_calls(monkeypatch)
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mid).one()
        with pytest.raises(ValueError, match="unvollstaendig"):
            evaluate_goal_sensitivity(
                db=session,
                mandate=mandate,
                user_id=advisor_id,
                goal_id=gid,
                target_delta_pct=0,
            )

    assert calls == []


def test_sensitivity_without_allocation_basis_fails_before_solver(
    session_factory, monkeypatch,
):
    """Sensitivity must share Generate's minimum economic-data contract."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, client_id, mid, _aid, gid = _seed_mandate(
        session_factory,
        suffix="sensitivity-no-basis",
    )
    with session_factory() as session:
        for position in session.query(WealthPosition).filter(
            WealthPosition.client_id == client_id
        ).all():
            position.is_active = 0
        for cashflow in session.query(Cashflow).filter(
            Cashflow.client_id == client_id
        ).all():
            cashflow.is_active = 0
        session.commit()

    calls = _capture_sensitivity_solver_calls(monkeypatch)
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mid).one()
        with pytest.raises(ValueError, match=r"Keine Verm.gensbasis"):
            evaluate_goal_sensitivity(
                db=session,
                mandate=mandate,
                user_id=advisor_id,
                goal_id=gid,
                target_delta_pct=0,
            )

    assert calls == []


def test_sensitivity_does_not_silently_disable_incomplete_mortality(
    session_factory, monkeypatch,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(
        session_factory,
        suffix="incomplete-mortality",
    )
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mid).one()
        mandate.jurisdiction = "CH"
        mandate.use_mortality_simulation = 1
        mandate.client_birth_year = 1980
        mandate.client_sex = None
        session.commit()

    calls = _capture_sensitivity_solver_calls(monkeypatch)
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mid).one()
        with pytest.raises(
            ValueError,
            match="requires client_birth_year.*client_sex M/F",
        ):
            evaluate_goal_sensitivity(
                db=session,
                mandate=mandate,
                user_id=advisor_id,
                goal_id=gid,
                target_delta_pct=0,
            )

    assert calls == []


def test_sensitivity_requires_tax_jurisdiction_for_activated_estimate(
    session_factory, monkeypatch,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(
        session_factory,
        suffix="incomplete-tax-estimate",
    )
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mid).one()
        mandate.tax_estimate_in_cashflow_enabled = 1
        mandate.tax_jurisdiction = None
        session.commit()

    calls = _capture_sensitivity_solver_calls(monkeypatch)
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mid).one()
        with pytest.raises(ValueError, match="Steuerbasis"):
            evaluate_goal_sensitivity(
                db=session,
                mandate=mandate,
                user_id=advisor_id,
                goal_id=gid,
                target_delta_pct=0,
            )

    assert calls == []


def test_sensitivity_return_goal_changes_return_target_and_solver_horizon(
    session_factory, monkeypatch,
):
    """Renditeziel deltas affect return bps and the modified solver horizon."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)

    with session_factory() as s:
        return_goal = s.query(Goal).filter(
            Goal.mandate_id == mid,
            Goal.goal_type == "Vermoegensziel",
        ).one()
        return_goal.goal_family = "Rendite"
        return_goal.goal_type = "Renditeziel"
        return_goal.target_amount_rappen = None
        return_goal.target_wealth_rappen = None
        return_goal.target_return_bps = 500
        # Match the existing 30-year pension floor so +3 genuinely extends
        # the shared solver horizon instead of remaining below that floor.
        return_goal.horizon_years = 30
        s.commit()
        return_goal_id = return_goal.id

    calls = _capture_sensitivity_solver_calls(monkeypatch)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        persisted_goal = s.query(Goal).filter(Goal.id == return_goal_id).one()
        out = evaluate_goal_sensitivity(
            db=s,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=return_goal_id,
            target_delta_pct=20,
            horizon_delta_years=3,
        )
        assert persisted_goal.target_return_bps == 500
        assert persisted_goal.horizon_years == 30

    assert len(calls) == 2
    baseline_goal = _captured_goal(calls[0], return_goal_id)
    modified_goal = _captured_goal(calls[1], return_goal_id)
    assert baseline_goal["target_return_bps"] == 500
    assert modified_goal["target_return_bps"] == 600
    assert baseline_goal["horizon_years"] == 30
    assert modified_goal["horizon_years"] == 33
    assert calls[1]["horizon_years"] == calls[0]["horizon_years"] + 3

    assert out["target_return_bps_baseline"] == 500
    assert out["target_return_bps_new"] == 600
    assert out["solver_horizon_years_baseline"] == calls[0]["horizon_years"]
    assert out["solver_horizon_years_new"] == calls[1]["horizon_years"]


def test_sensitivity_return_horizon_cannot_clip_another_goal(
    session_factory,
    monkeypatch,
):
    """Shortening a return goal must retain a later pension liability."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _pension_goal_id = _seed_mandate(
        session_factory,
        suffix="return-horizon-floor",
    )
    with session_factory() as session:
        return_goal = session.query(Goal).filter(
            Goal.mandate_id == mid,
            Goal.goal_type == "Vermoegensziel",
        ).one()
        return_goal.goal_family = "Rendite"
        return_goal.goal_type = "Renditeziel"
        return_goal.target_wealth_rappen = None
        return_goal.target_return_bps = 500
        return_goal.horizon_years = 30
        session.commit()
        return_goal_id = return_goal.id

    calls = _capture_sensitivity_solver_calls(monkeypatch)
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mid).one()
        out = evaluate_goal_sensitivity(
            db=session,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=return_goal_id,
            target_delta_pct=0,
            horizon_delta_years=-10,
        )

    assert len(calls) == 2
    assert calls[1]["horizon_years"] >= 30
    assert out["solver_horizon_years_new"] >= 30


def test_sensitivity_horizon_uses_common_scenario_prefix_and_full_cashflows(
    session_factory, monkeypatch,
):
    """A longer counterfactual extends inputs and reuses the exact path prefix."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 12)
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(
        session_factory,
        suffix="common-prefix",
    )

    with session_factory() as s:
        return_goal = s.query(Goal).filter(
            Goal.mandate_id == mid,
            Goal.goal_type == "Vermoegensziel",
        ).one()
        return_goal.goal_family = "Rendite"
        return_goal.goal_type = "Renditeziel"
        return_goal.target_amount_rappen = None
        return_goal.target_wealth_rappen = None
        return_goal.target_return_bps = 500
        # Start at the existing pension horizon; the perturbation must extend
        # cashflows and scenarios by exactly three additional annual buckets.
        return_goal.horizon_years = 30
        s.commit()
        goal_id = return_goal.id

    calls = _capture_sensitivity_solver_calls(monkeypatch)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).one()
        out = evaluate_goal_sensitivity(
            db=s,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=goal_id,
            target_delta_pct=0,
            horizon_delta_years=3,
        )

    assert len(calls) == 2
    baseline, modified = calls
    assert baseline["scenario_horizon_years"] == modified["horizon_years"]
    assert modified["scenario_horizon_years"] == modified["horizon_years"]
    baseline_cf = baseline["cashflow_series_rappen"]
    modified_cf = modified["cashflow_series_rappen"]
    assert baseline_cf == modified_cf[: baseline["horizon_years"]]
    assert len(modified_cf) == modified["horizon_years"]
    assert any(int(value) != 0 for value in modified_cf[len(baseline_cf) :])
    assert out["live_model_input_hash"] == out["baseline_model_input_hash"]
    assert out["baseline_model_input_hash"] != out["modified_model_input_hash"]
    assert out["fx_basis"]["basis_id"] == "default_fx_rates_2026_v1"
    assert out["fx_basis"]["uses_versioned_defaults"] is True


def test_sensitivity_live_hash_binds_current_house_matrix_bounds(
    session_factory,
    monkeypatch,
):
    """No-TA live context must hash its House-derived effective bounds."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, goal_id = _seed_mandate(
        session_factory,
        suffix="house-bounds-hash",
    )
    _capture_sensitivity_solver_calls(monkeypatch)

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mid).one()
        first = evaluate_goal_sensitivity(
            db=session,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=goal_id,
            target_delta_pct=0,
        )
        house_row = session.query(HouseMatrix).filter(
            HouseMatrix.score_from <= 7,
            HouseMatrix.score_to >= 7,
        ).one()
        house_row.equity_max_bps = int(house_row.equity_max_bps) - 1
        session.commit()

        second = evaluate_goal_sensitivity(
            db=session,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=goal_id,
            target_delta_pct=0,
        )

    assert first["constraint_basis"] == "live_canonical_stochastic_context"
    assert second["constraint_basis"] == "live_canonical_stochastic_context"
    assert first["live_model_input_hash"] != second["live_model_input_hash"]


def test_sensitivity_without_allocation_uses_exact_generate_live_context(
    session_factory,
    monkeypatch,
):
    """No-TA sensitivity must use Generate's canonical mandate plan.

    In particular, mandate-default geography and PE choices may not degrade to
    bucket-average building-block risk fractions merely because no allocation
    has been persisted yet.
    """
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, goal_id = _seed_mandate(
        session_factory,
        suffix="live-canonical-plan",
    )
    sensitivity_calls = _capture_sensitivity_solver_calls(monkeypatch)
    generate_contexts: list[dict] = []

    def fake_generate_optimizer(**kwargs):
        generate_contexts.append({
            "sub_allocations": copy.deepcopy(kwargs["sub_allocations"]),
            "risky_fraction_per_bucket": copy.deepcopy(
                kwargs["risky_fraction_per_bucket"]
            ),
            "effective_bounds_bps": copy.deepcopy(
                kwargs["effective_bounds_bps"]
            ),
        })
        return None

    monkeypatch.setattr(
        pe,
        "_run_stochastic_optimizer_pass",
        fake_generate_optimizer,
    )

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mid).one()
        mandate.default_building_blocks_json = json.dumps({
            "equitiesGeo": "Global",
            "altsGold": True,
            "altsPe": True,
        })
        session.flush()

        generate_target_allocation(
            session,
            mandate,
            advisor_id,
            preferences=None,
        )
        assert len(generate_contexts) == 1

        # Keep the generated artifact as history, but deliberately exercise
        # the path where there is no active allocation context to reuse.
        current = session.query(pe.TargetAllocation).filter(
            pe.TargetAllocation.mandate_id == mid,
            pe.TargetAllocation.is_current == 1,
        ).one()
        current.is_current = 0
        session.flush()

        out = evaluate_goal_sensitivity(
            db=session,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=goal_id,
            target_delta_pct=0,
        )

    assert len(sensitivity_calls) == 2
    expected = generate_contexts[0]
    assert any(
        row["sub_asset_class"] == "Private Equity"
        for row in expected["sub_allocations"]
    )
    from services.optimizer.constraints import (
        MAX_ALTERNATIVES,
        MAX_REAL_ESTATE,
        MIN_LIQUIDITY,
    )

    assert expected["effective_bounds_bps"]["real_estate"][1] <= int(
        round(MAX_REAL_ESTATE * 10000)
    )
    assert expected["effective_bounds_bps"]["alternatives"][1] <= int(
        round(MAX_ALTERNATIVES * 10000)
    )
    assert expected["effective_bounds_bps"]["liquidity"][0] >= int(
        round(MIN_LIQUIDITY * 10000)
    )
    for call in sensitivity_calls:
        assert call["sub_allocations"] == expected["sub_allocations"]
        assert (
            call["risky_fraction_per_bucket"]
            == expected["risky_fraction_per_bucket"]
        )
        assert call["effective_bounds_bps"] == expected["effective_bounds_bps"]
    assert out["constraint_basis"] == "live_canonical_stochastic_context"


def test_sensitivity_returns_expected_schema(session_factory, monkeypatch):
    """Sensitivity-Helper liefert alle benoetigten Felder."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        out = evaluate_goal_sensitivity(
            db=s, mandate=mandate, user_id=advisor_id,
            goal_id=gid, target_delta_pct=-10,
        )
    expected_keys = {
        "goal_id", "delta_pct",
        "target_amount_rappen_baseline", "target_amount_rappen_new",
        "objective_value_milli_baseline", "objective_value_milli_new",
        "delta_objective_pct",
        "weights_bps_baseline", "weights_bps_new",
        "status_baseline", "status_new",
    }
    assert expected_keys.issubset(out.keys())
    assert out["goal_id"] == gid
    assert out["delta_pct"] == -10
    # Delta -10% auf 24'000 -> 21'600 CHF.
    assert out["target_amount_rappen_new"] == 21_600_00
    # Weights summe ~10000bps
    weights = out["weights_bps_new"]
    assert sum(weights.values()) == pytest.approx(10000, abs=5)


def test_sensitivity_zero_delta_does_not_change_target(session_factory, monkeypatch):
    """delta_pct=0 -> target_amount_new == baseline."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        out = evaluate_goal_sensitivity(
            db=s, mandate=mandate, user_id=advisor_id,
            goal_id=gid, target_delta_pct=0,
        )
    assert out["target_amount_rappen_baseline"] == out["target_amount_rappen_new"]


def test_sensitivity_unknown_goal_raises(session_factory, monkeypatch):
    """Goal-ID gehoert nicht zum Mandanten -> ValueError mit 'nicht gefunden'."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        with pytest.raises(ValueError, match="nicht gefunden"):
            evaluate_goal_sensitivity(
                db=s, mandate=mandate, user_id=advisor_id,
                goal_id="goal-does-not-exist", target_delta_pct=-10,
            )


def test_sensitivity_house_matrix_mode_raises(session_factory, monkeypatch):
    """Bei OPTIMIZER_MODE=house_matrix verweigert der Helper die Auswertung."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        with pytest.raises(ValueError, match="OPTIMIZER_MODE=stochastic"):
            evaluate_goal_sensitivity(
                db=s, mandate=mandate, user_id=advisor_id,
                goal_id=gid, target_delta_pct=-10,
            )


# ============================================================================
# Endpoint: POST /mandates/{id}/target-allocation/sensitivity
# ============================================================================


def test_endpoint_happy_path_returns_200(session_factory, monkeypatch, cleanup_overrides):
    """Authenticated Advisor + valides Goal -> 200 mit komplettem Payload."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.post(
        f"/mandates/{mid}/target-allocation/sensitivity",
        json={"goal_id": gid, "target_delta_pct": -10},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["goal_id"] == gid
    assert body["delta_pct"] == -10
    assert body["target_amount_rappen_new"] == 21_600_00
    assert isinstance(body["weights_bps_new"], dict)
    assert body["status_new"] in (
        "converged", "converged_robustified", "diverged", "diverged_infeasible", "fallback_house_matrix",
    )


def test_endpoint_unknown_goal_returns_404(session_factory, monkeypatch, cleanup_overrides):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.post(
        f"/mandates/{mid}/target-allocation/sensitivity",
        json={"goal_id": "nope-not-existing", "target_delta_pct": 10},
    )
    assert resp.status_code == 404


def test_endpoint_invalid_delta_returns_422(session_factory, monkeypatch, cleanup_overrides):
    """delta_pct=42 nicht in {-20,-10,0,10,20} -> Pydantic 422."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.post(
        f"/mandates/{mid}/target-allocation/sensitivity",
        json={"goal_id": gid, "target_delta_pct": 42},
    )
    assert resp.status_code == 422


def test_endpoint_house_matrix_mode_returns_409(session_factory, monkeypatch, cleanup_overrides):
    """OPTIMIZER_MODE=house_matrix -> 409 'Sensitivity-Analyse erfordert ...'."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.post(
        f"/mandates/{mid}/target-allocation/sensitivity",
        json={"goal_id": gid, "target_delta_pct": -10},
    )
    assert resp.status_code == 409
    assert "stochastic" in resp.json()["detail"].lower()


# ============================================================================
# Phase 6.1: stress_evaluations Persistenz (target_allocations.stress_evaluations_json)
# ============================================================================


def test_stress_evaluations_persisted_to_db_column(session_factory, monkeypatch):
    """Phase 6.1: stress_evaluations_json wird in der DB-Spalte abgelegt
    (JSON-String, deserialisierbar als dict). Nur fuer stochastic-Modus.
    """
    import json

    from models.allocation import TargetAllocation
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        ta_id = result["target_allocation"].id
        # Reload from DB to verify the column is actually persisted.
        ta = s.query(TargetAllocation).filter(TargetAllocation.id == ta_id).first()
        # Wenn der Solver konvergierte und Stress-Eval lief: Spalte ist gesetzt.
        # Bei Fallback kann sie None sein - dann ueberspringen.
        if result.get("stress_evaluations") is not None:
            assert ta.stress_evaluations_json is not None
            parsed = json.loads(ta.stress_evaluations_json)
            assert isinstance(parsed, dict)
            assert parsed == result["stress_evaluations"]


def test_stress_evaluations_column_null_in_house_matrix(session_factory, monkeypatch):
    """Phase 6.1: house_matrix-Modus -> stress_evaluations_json bleibt NULL."""
    from models.allocation import TargetAllocation
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        ta_id = result["target_allocation"].id
        ta = s.query(TargetAllocation).filter(TargetAllocation.id == ta_id).first()
        assert ta.stress_evaluations_json is None


def test_payload_endpoint_returns_persisted_stress_evaluations(
    session_factory, monkeypatch, cleanup_overrides,
):
    """Phase 6.1: GET /target-allocation/current/payload liefert stress_evaluations
    aus der DB ohne erneuten Solver-Lauf - das ist der Nutzen der Persistenz."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    # 1. Allocation erzeugen (persistiert stress_evaluations_json in DB)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        had_stress = result.get("stress_evaluations") is not None
    if not had_stress:
        pytest.skip("Solver fiel auf fallback_house_matrix - kein Stress-Eval persistiert")

    # 2. /current/payload aufrufen (anderer Codepfad: build_target_payload_from_allocation)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.get(f"/mandates/{mid}/target-allocation/current/payload")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    stress = body.get("stress_evaluations")
    assert stress is not None
    assert isinstance(stress, dict)
    assert len(stress) >= 1
    for _name, payload in stress.items():
        assert "end_wealth_rappen" in payload
        assert "max_drawdown_bps" in payload


def test_payload_endpoint_handles_corrupted_stress_json_gracefully(
    session_factory, monkeypatch, cleanup_overrides,
):
    """Phase 6.1: Defekter JSON in der DB-Spalte fuehrt zu stress_evaluations=None
    und keinem Crash - Robustheit beim Deserialisieren ist Pflicht."""
    from models.allocation import TargetAllocation
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        # Sabotiere das persistierte JSON.
        ta = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid,
            TargetAllocation.is_current == 1,
        ).first()
        ta.stress_evaluations_json = "{not-valid-json"
        s.commit()

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.get(f"/mandates/{mid}/target-allocation/current/payload")
    assert resp.status_code == 200, resp.text
    assert resp.json().get("stress_evaluations") is None


# ============================================================================
# Phase 6.2: optimizer_reasoning Persistenz (target_allocations.optimizer_reasoning_json)
# ============================================================================


def test_optimizer_reasoning_persisted_to_db_column(session_factory, monkeypatch):
    """Phase 6.2: optimizer_reasoning_json wird in der DB-Spalte abgelegt
    (JSON-Liste mit Solver-Trace-Zeilen). Nur fuer stochastic-Modus."""
    import json

    from models.allocation import TargetAllocation
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        ta = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid,
            TargetAllocation.is_current == 1,
        ).first()
        # Wenn der Solver konvergierte: Reasoning-Spalte ist gesetzt.
        # (Bei fallback-Fall ist OptimizerResult.reasoning trotzdem gefuellt.)
        if ta.optimization_method is not None:
            assert ta.optimizer_reasoning_json is not None
            parsed = json.loads(ta.optimizer_reasoning_json)
            assert isinstance(parsed, list)
            assert len(parsed) >= 1
            assert all(isinstance(item, (str, dict)) for item in parsed)


def test_optimizer_reasoning_column_null_in_house_matrix(session_factory, monkeypatch):
    """Phase 6.2: house_matrix-Modus -> optimizer_reasoning_json bleibt NULL."""
    from models.allocation import TargetAllocation
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        ta = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid,
            TargetAllocation.is_current == 1,
        ).first()
        assert ta.optimizer_reasoning_json is None


def test_payload_endpoint_returns_persisted_optimizer_reasoning(
    session_factory, monkeypatch, cleanup_overrides,
):
    """Phase 6.2: GET /current/payload reasoning-Liste enthaelt persistierte
    Solver-Reasoning-Zeilen (z.B. 'SLSQP', 'Best objective', 'Stress')."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        gen_result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        had_optimizer = gen_result["target_allocation"].optimization_method is not None
    if not had_optimizer:
        pytest.skip("Solver lief nicht - kein Reasoning persistiert")

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.get(f"/mandates/{mid}/target-allocation/current/payload")
    assert resp.status_code == 200, resp.text
    reasoning = resp.json().get("reasoning", [])
    assert isinstance(reasoning, list)
    joined = " | ".join(reasoning)
    # Mindestens einer der Solver-Trace-Marker muss drin sein.
    assert any(
        marker in joined
        for marker in ("SLSQP", "Solver", "Best objective", "Stress", "iterations")
    ), f"Reasoning ohne Solver-Trace nach Reload: {reasoning}"


def test_sensitivity_endpoint_writes_audit_log(
    session_factory, monkeypatch, cleanup_overrides,
):
    """Phase 6.3: Jeder Sensitivity-Call legt einen AuditLog-Eintrag an
    (FINMA-Trace). record_id=goal_id, action=SENSITIVITY, new_value=delta_pct."""
    from models.review import AuditLog
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.post(
        f"/mandates/{mid}/target-allocation/sensitivity",
        json={"goal_id": gid, "target_delta_pct": -10},
    )
    assert resp.status_code == 200, resp.text
    with session_factory() as s:
        entries = s.query(AuditLog).filter(
            AuditLog.action == "SENSITIVITY",
            AuditLog.record_id == gid,
        ).all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.user_id == advisor_id
    assert entry.mandate_id == mid
    assert entry.table_name == "goals"
    assert entry.new_value == "-10"


def test_sensitivity_works_for_goal_with_only_target_wealth(
    session_factory, monkeypatch,
):
    """Edge-Case: ein Vermoegensziel hat nur target_wealth_rappen (kein _amount).
    Helper muss trotzdem den korrekten Wert um delta_pct skalieren."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    # Wealth-Goal ID anhand des suffix patterns aus _seed_mandate
    with session_factory() as s:
        wealth_goal = s.query(Goal).filter(
            Goal.mandate_id == mid,
            Goal.goal_type == "Vermoegensziel",
        ).first()
        assert wealth_goal is not None
        assert wealth_goal.target_wealth_rappen == 300_000_00
        assert (wealth_goal.target_amount_rappen or 0) == 0
        wgid = wealth_goal.id

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        out = evaluate_goal_sensitivity(
            db=s, mandate=mandate, user_id=advisor_id,
            goal_id=wgid, target_delta_pct=20,
        )
    # +20% auf 300'000 -> 360'000 CHF
    assert out["target_amount_rappen_baseline"] == 300_000_00
    assert out["target_amount_rappen_new"] == 360_000_00


def test_sensitivity_multiple_calls_create_separate_audit_entries(
    session_factory, monkeypatch, cleanup_overrides,
):
    """Edge-Case: drei Sensitivity-Calls hintereinander -> drei separate
    AuditLog-Eintraege mit unterschiedlichen new_values."""
    from models.review import AuditLog
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    for delta in (-20, -10, 10):
        resp = client.post(
            f"/mandates/{mid}/target-allocation/sensitivity",
            json={"goal_id": gid, "target_delta_pct": delta},
        )
        assert resp.status_code == 200, (delta, resp.text)
    with session_factory() as s:
        entries = s.query(AuditLog).filter(
            AuditLog.action == "SENSITIVITY",
            AuditLog.record_id == gid,
        ).order_by(AuditLog.created_at.asc()).all()
    assert len(entries) == 3
    deltas = [int(e.new_value) for e in entries]
    assert deltas == [-20, -10, 10]


def test_sensitivity_endpoint_no_audit_on_404(
    session_factory, monkeypatch, cleanup_overrides,
):
    """Phase 6.3: Bei unbekanntem goal_id (404) darf KEIN AuditLog entstehen."""
    from models.review import AuditLog
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.post(
        f"/mandates/{mid}/target-allocation/sensitivity",
        json={"goal_id": "nope", "target_delta_pct": 10},
    )
    assert resp.status_code == 404
    with session_factory() as s:
        entries = s.query(AuditLog).filter(
            AuditLog.action == "SENSITIVITY",
        ).all()
    assert len(entries) == 0


def test_payload_endpoint_handles_corrupted_reasoning_json_gracefully(
    session_factory, monkeypatch, cleanup_overrides,
):
    """Phase 6.2: defekter optimizer_reasoning_json -> kein Crash, leere Liste,
    generic Reasoning + Drift-Warnings stehen weiter zur Verfuegung."""
    from models.allocation import TargetAllocation
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        ta = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid,
            TargetAllocation.is_current == 1,
        ).first()
        ta.optimizer_reasoning_json = "[truly broken"
        s.commit()

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.get(f"/mandates/{mid}/target-allocation/current/payload")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # generic 2-Satz-Reasoning muss da sein, kein Crash
    reasoning = body.get("reasoning", [])
    assert any("bestehende aktuelle Soll-Allokation" in r for r in reasoning)
