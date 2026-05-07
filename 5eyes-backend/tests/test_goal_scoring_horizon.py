from types import SimpleNamespace

from services.portfolio_engine import _goal_duration_years, _monte_carlo_goal_summary


def _make_goal(**overrides):
    base = {
        "id": "goal-1",
        "label": "Pension",
        "goal_type": "Pensionsausgabe",
        "goal_scope": "Beratungsvermoegen",
        "rank": 1,
        "target_amount_rappen": 300_000,
        "target_wealth_rappen": 0,
        "target_return_bps": 0,
        "start_date": "2028-01-01",
        "target_date": "2048-12-31",
        "horizon_years": None,
        "is_ongoing": 0,
        "frequency": "monatlich",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_policy():
    return SimpleNamespace(allow_other_assets_for_goals=0)


def test_goal_duration_years_clips_dated_recurring_goal_to_simulation_horizon():
    goal = _make_goal()

    duration = _goal_duration_years(goal, start_year=2026, horizon_years=10)

    assert duration == 9


def test_monte_carlo_goal_summary_marks_partial_recurring_evaluation():
    goal = _make_goal()
    summary = _monte_carlo_goal_summary(
        goal,
        path_values_by_year=[[40_000_000] for _ in range(11)],
        annualized_return_samples_bps=[450],
        inflation_series_bps=[0] * 11,
        advisory_wealth_rappen=40_000_000,
        total_wealth_rappen=40_000_000,
        start_year=2026,
        horizon_years=10,
        policy=_make_policy(),
    )

    assert summary["success_rate_pct"] == 100
    assert summary["funded_ratio_p50"] == 1.2346
    assert summary["score"] == 100
    assert summary["evaluation_note"] == "Bewertet fuer 9 von 21 Jahren (Simulationshorizont: 10 Jahre)."


def test_monte_carlo_goal_summary_marks_recurring_goal_outside_horizon():
    goal = _make_goal(start_date="2040-01-01", target_date="2060-12-31")
    summary = _monte_carlo_goal_summary(
        goal,
        path_values_by_year=[[40_000_000] for _ in range(11)],
        annualized_return_samples_bps=[450],
        inflation_series_bps=[0] * 11,
        advisory_wealth_rappen=40_000_000,
        total_wealth_rappen=40_000_000,
        start_year=2026,
        horizon_years=10,
        policy=_make_policy(),
    )

    assert summary["success_rate_pct"] == 0
    assert summary["funded_ratio_p50"] == 0.0
    assert summary["score"] == 0
    assert "ausserhalb des aktuellen Simulationshorizonts" in summary["evaluation_note"]
