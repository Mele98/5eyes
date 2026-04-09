from datetime import date
from types import SimpleNamespace

from services.portfolio_engine import _monte_carlo_goal_summary


def _policy():
    return SimpleNamespace(allow_other_assets_for_goals=1)


def _recurring_goal(*, start_year_offset: int, duration_years: int):
    current_year = date.today().year
    start_year = current_year + start_year_offset
    target_year = start_year + duration_years - 1
    return SimpleNamespace(
        id=f"goal-{start_year_offset}-{duration_years}",
        label="Pension",
        goal_type="Pensionsausgabe",
        target_amount_rappen=300_000,
        frequency="monatlich",
        start_date=f"{start_year}-01-01",
        target_date=f"{target_year}-12-31",
        is_ongoing=0,
        goal_scope="Beratungsvermoegen",
    )


def test_recurring_goal_duration_is_clipped_to_simulated_horizon():
    current_year = date.today().year
    goal = _recurring_goal(start_year_offset=0, duration_years=20)
    summary = _monte_carlo_goal_summary(
        goal,
        path_values_by_year=[[0]] + [[36_000_000] for _ in range(10)],
        annualized_return_samples_bps=[],
        advisory_wealth_rappen=36_000_000,
        total_wealth_rappen=36_000_000,
        start_year=current_year,
        horizon_years=10,
        policy=_policy(),
    )

    assert summary["years"] == 10
    assert summary["projected_value_p50_rappen"] == 36_000_000
    assert summary["funded_ratio_p50"] == 1.0
    assert summary["success_rate_pct"] == 100
    assert summary["score"] == 100


def test_recurring_goal_duration_respects_delayed_start_within_horizon():
    current_year = date.today().year
    goal = _recurring_goal(start_year_offset=5, duration_years=20)
    summary = _monte_carlo_goal_summary(
        goal,
        path_values_by_year=[[0]] + [[18_000_000] for _ in range(10)],
        annualized_return_samples_bps=[],
        advisory_wealth_rappen=18_000_000,
        total_wealth_rappen=18_000_000,
        start_year=current_year,
        horizon_years=10,
        policy=_policy(),
    )

    assert summary["years"] == 10
    assert summary["projected_value_p50_rappen"] == 18_000_000
    assert summary["funded_ratio_p50"] == 1.0
    assert summary["success_rate_pct"] == 100
    assert summary["score"] == 100
