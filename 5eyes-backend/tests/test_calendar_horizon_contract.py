"""Shared calendar-year horizon semantics for dated optimizer inputs."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from services.calendar_horizon import add_calendar_years, calendar_years_until
from services.optimizer.goal_liabilities import goal_to_liability
from services.portfolio_engine import _simulation_horizon_years


def _dated_goal(target_date: date) -> SimpleNamespace:
    return SimpleNamespace(
        id="calendar-goal",
        label="Calendar goal",
        goal_type="Einmalige_Ausgabe",
        target_amount_rappen=10_000_00,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=None,
        target_date=target_date.isoformat(),
        start_date=None,
        is_ongoing=0,
        frequency="einmalig",
        hardness="Hart",
        rank=1,
        weight_bps=10_000,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
    )


def test_calendar_year_horizon_exact_anniversary_then_one_day_over() -> None:
    as_of = date.today()
    exact = add_calendar_years(as_of, 12)

    assert calendar_years_until(exact, as_of=as_of) == 12
    assert calendar_years_until(exact + timedelta(days=1), as_of=as_of) == 13


def test_calendar_year_horizon_handles_february_29_anniversary() -> None:
    as_of = date(2024, 2, 29)

    assert add_calendar_years(as_of, 1) == date(2025, 2, 28)
    assert calendar_years_until(date(2025, 2, 28), as_of=as_of) == 1
    assert calendar_years_until(date(2025, 3, 1), as_of=as_of) == 2


def test_goal_liability_and_monte_carlo_share_calendar_horizon_contract() -> None:
    today = date.today()
    exact = add_calendar_years(today, 12)

    exact_goal = _dated_goal(exact)
    over_goal = _dated_goal(exact + timedelta(days=1))

    exact_liability = goal_to_liability(exact_goal, horizon_years=20)
    over_liability = goal_to_liability(over_goal, horizon_years=20)

    assert exact_liability.target_year_index == 12
    assert over_liability.target_year_index == 13
    assert _simulation_horizon_years(
        {"horizonYears": 7}, [exact_goal], None
    ) == 12
    assert _simulation_horizon_years(
        {"horizonYears": 7}, [over_goal], None
    ) == 13
