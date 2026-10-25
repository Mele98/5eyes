"""RESERVE-DOUBLE-COUNT-001 (Variablen-Audit 2026-10-18, Befund 1.11).

The liquidity reserve R is sized from the client's near-term outflows (here: a
one-off goal of CHF 150'000 in 2 years). Part of it is held inside the SAA as
liquidity (internal reserve S, capped by the SAA ceiling), the rest E = R - S
is carved out of advisory wealth A and recommended as cash *outside* the
mandate. The stochastic solver therefore starts with I = A - E.

Defect: the goal that E was sized for still reached the solver as a full
liability, and nothing gave E back. Every CHF of E was "spent" twice -- once
by the carve-out and once more as goal outflow. On this example
(A = 600k, c = 200 bps -> S = 12k, E = 138k) the solver saw the client
CHF 138'000 poorer than he is.

Invariant (money conservation, zero-return view): over the solver horizon,

    I + sum(solver cashflows)  ==  A + sum(engine cashflows)

i.e. the carved-out reserve re-enters the solver exactly once, as cash (no
return) in the year(s) the outflows it was sized for fall due. It must not
re-enter earlier than the outflow (that would let it earn market returns) and
never more than E.
"""
from __future__ import annotations

import pytest

import services.optimizer.solver as solver_module
from models.mandates import Mandate
from models.wealth import Goal, WealthPosition
from routers.profiling import create_risk_assessment
from schemas.profiling import RiskAssessmentCreate
from services.portfolio_engine import generate_target_allocation
from test_runtime_contracts import (  # noqa: F401
    _FakeSignRequest,
    advisor_user,
    complete_risk_questionnaire_answers,
    seed_client_and_mandate,
    session_factory,
)

CHF = 100
A_CHF = 600_000
GOAL_CHF = 150_000
GOAL_YEARS = 2


def _generate_capturing_solver_context(session_factory, advisor_user, monkeypatch):
    import services.portfolio_engine as engine_module

    captured: dict = {}
    real_build = solver_module.build_optimizer_context
    real_pass = engine_module._run_stochastic_optimizer_pass

    def spy_build(**kwargs):
        context = real_build(**kwargs)
        captured.setdefault("context", context)
        return context

    def spy_pass(**kwargs):
        captured.setdefault("engine_cashflows", list(kwargs["cashflow_projection_series_rappen"]))
        return real_pass(**kwargs)

    monkeypatch.setattr(solver_module, "build_optimizer_context", spy_build)
    monkeypatch.setattr(engine_module, "_run_stochastic_optimizer_pass", spy_pass)

    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)
    payload = RiskAssessmentCreate(
        q_income_points=4, q_obligations_points=4, q_savings_points=12, q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre", investment_horizon_years=15,
        q_investment_goal_points=4, q_risk_preference_points=4, q_risk_behavior_points=4,
        answers=complete_risk_questionnaire_answers(),
    )
    with session_factory() as session:
        create_risk_assessment(request=_FakeSignRequest(), mandate_id=mandate_id, body=payload,
                               db=session, current_user=advisor_user)
        session.add_all([
            WealthPosition(
                id="depot-1", client_id=client_id, label="Depot", position_type="Depot",
                assignment="Beratungsvermögen", current_value_rappen=A_CHF * CHF, currency="CHF",
                alloc_equities_bps=6000, alloc_bonds_bps=3000, alloc_real_estate_bps=0,
                alloc_liquidity_bps=500, alloc_alternatives_bps=500, is_active=1,
                created_at="2026-03-27T00:00:00.000Z", updated_at="2026-03-27T00:00:00.000Z",
            ),
            Goal(
                id="goal-1", mandate_id=mandate_id, client_id=client_id, goal_family="Cashflow",
                goal_type="Einmalige_Ausgabe", label="Eigenmittel Kauf", rank=1,
                goal_scope="Beratungsvermögen", value_mode="nominal",
                target_amount_rappen=GOAL_CHF * CHF, horizon_years=GOAL_YEARS, hardness="Hart",
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z", updated_at="2026-03-27T00:00:00.000Z",
            ),
        ])
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = generate_target_allocation(db=session, mandate=mandate, user_id=advisor_user.id,
                                            preferences=None)
        session.commit()
    return result, captured


def test_carved_out_reserve_reenters_solver_exactly_once(session_factory, advisor_user, monkeypatch):
    result, captured = _generate_capturing_solver_context(session_factory, advisor_user, monkeypatch)
    A = A_CHF * CHF
    R = int(result["reserve_needed_rappen"])
    E = int(result["external_reserve_rappen"])
    I = int(result["investable_advisory_wealth_rappen"])
    # Preconditions: the scenario really carves out a reserve sized for the goal.
    assert R == GOAL_CHF * CHF
    assert E == R - A * 200 // 10000 == 138_000 * CHF
    assert I == A - E

    context = captured["context"]
    assert int(context.advisory_wealth_rappen) == I
    horizon = len(context.cashflow_series_rappen)
    engine_cf = (captured["engine_cashflows"] + [0] * horizon)[:horizon]
    solver_cf = [int(v) for v in context.cashflow_series_rappen]

    # The goal is still a full liability in the solver (it must be: it is paid).
    liability = [int(v) for v in context.aggregated_liability_path]
    assert sum(liability) >= GOAL_CHF * CHF

    solver_money = I + sum(solver_cf)
    client_money = A + sum(engine_cf)
    assert solver_money == client_money, (
        f"solver sees CHF {(client_money - solver_money) / CHF:,.0f} less than the client owns "
        "(carved-out reserve lost a second time against the goal liability)"
    )

    # Timing: the reserve is cash. It is released no earlier than the outflow
    # it funds and never exceeds that year's outflow (no market return on it).
    release = [s - e for s, e in zip(solver_cf, engine_cf)]
    assert all(r >= 0 for r in release)
    for t, r in enumerate(release):
        assert r <= liability[t] + max(0, -engine_cf[t])
    goal_due_index = next(t for t, v in enumerate(liability) if v > 0)
    assert release[goal_due_index] > 0


def test_release_series_is_chronological_capped_and_conservative():
    from services.portfolio_engine_reserve import _tranche_release_series

    # Outflows: cashflow deficit 20k in year 0, goal 100k in year 2, 30k in year 5.
    cf = [-20_000, 10_000, 0, 0, 0, 0]
    liab = [0, 0, 100_000, 0, 0, 30_000]
    assert _tranche_release_series(85_000, cf, liab) == [20_000, 0, 65_000, 0, 0, 0]
    # Reserve larger than all outflows: unreleased remainder stays outside (floor).
    assert _tranche_release_series(500_000, cf, liab) == [20_000, 0, 100_000, 0, 0, 30_000]
    # No reserve -> no release; no outflows -> no release.
    assert _tranche_release_series(0, cf, liab) == [0] * 6
    assert _tranche_release_series(50_000, [5, 5], [0, 0]) == [0, 0]
    with pytest.raises(ValueError):
        _tranche_release_series(-1, cf, liab)


def test_generate_publishes_the_ledger_the_solver_consumed(session_factory, advisor_user, monkeypatch):
    """RESERVE-FUNDING-LEDGER-001: Solver, Reporting und Payload teilen EINEN Ledger."""
    from services.reserve_funding_ledger import RESERVE_ACCOUNTING_BASIS

    result, captured = _generate_capturing_solver_context(session_factory, advisor_user, monkeypatch)
    ledger = result["reserve_funding_ledger"]
    assert ledger["total_external_rappen"] == int(result["external_reserve_rappen"]) > 0
    context = captured["context"]
    horizon = len(context.cashflow_series_rappen)
    engine_cf = (captured["engine_cashflows"] + [0] * horizon)[:horizon]
    solver_release = [int(s) - int(e) for s, e in zip(context.cashflow_series_rappen, engine_cf)]
    assert solver_release == list(ledger["release_series_rappen"])[:horizon]
    # Ein-Ziel-Fall: die Release-Tranche ist an genau dieses Ziel gebunden.
    assert {r["destination_id"] for r in ledger["releases"]} == {"goal-1"}
    # Reporting: IST und SOLL starten auf derselben wirtschaftlichen Basis A.
    mc = result["monte_carlo"]
    assert mc["reserve_accounting_basis"] == RESERVE_ACCOUNTING_BASIS
    assert mc["target_p50_series_rappen"][0] == mc["current_p50_series_rappen"][0] == A_CHF * CHF
    assert result["simulation"]["target_mix_series_rappen"][0] == A_CHF * CHF
