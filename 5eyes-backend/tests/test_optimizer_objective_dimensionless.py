"""Focused contracts for dimensionless optimizer objectives and due dates."""
from __future__ import annotations

import numpy as np
import pytest

import services.optimizer.objective as objective_module
from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.objective import (
    combined_objective_two_phase,
    goal_probability_per_path,
    shortfall_contributions,
    shortfall_objective,
    shortfall_squared_per_path,
)


def _liability(
    *,
    goal_id: str = "g1",
    target_kind: str = "wealth_at_t",
    target_amount_rappen: int = 100,
    target_year_index: int = 1,
    liability_path_rappen: list[int] | None = None,
    hardness_key: str = "primaer",
) -> GoalLiability:
    return GoalLiability(
        goal_id=goal_id,
        label=goal_id,
        goal_type="test",
        target_kind=target_kind,
        target_amount_rappen=target_amount_rappen,
        target_year_index=target_year_index,
        liability_path_rappen=list(liability_path_rappen or []),
        hardness_key=hardness_key,
        weight_bps=10_000,
        success_probability_min_x100=8_000,
    )


def test_primary_and_chance_terms_are_currency_scale_invariant():
    """Changing only the Rappen unit scale cannot change the objective."""
    small_goal = _liability(target_amount_rappen=150)
    large_goal = _liability(target_amount_rappen=15_000)
    small_paths = np.array([[100.0, 150.0], [100.0, 100.0]])
    large_paths = small_paths * 100.0

    small = combined_objective_two_phase(
        [small_goal],
        small_paths,
        initial_wealth_rappen=100,
        horizon_years=1,
        volatility_weight=0.0,
    )
    large = combined_objective_two_phase(
        [large_goal],
        large_paths,
        initial_wealth_rappen=10_000,
        horizon_years=1,
        volatility_weight=0.0,
    )

    # Primary = mean([0, (50/100)^2]) = 0.125. Chance is identical because
    # both contexts have P(success)=0.5 and tau=0.8.
    assert small == pytest.approx(0.125 + 1_000_000.0 * 0.3**2)
    assert large == pytest.approx(small)


def test_common_context_scale_preserves_absolute_goal_priority():
    """A 40-Rappen miss remains four times a 20-Rappen miss after squaring."""
    goals = [
        _liability(goal_id="small", target_amount_rappen=120),
        _liability(goal_id="large", target_amount_rappen=140),
    ]
    paths = np.array([[100.0, 100.0]])

    rows = shortfall_contributions(
        goals,
        paths,
        initial_wealth_rappen=100,
        horizon_years=1,
    )
    by_id = {row.goal_id: row for row in rows}

    assert by_id["small"].weighted_objective_contribution == pytest.approx(0.2**2)
    assert by_id["large"].weighted_objective_contribution == pytest.approx(0.4**2)
    assert (
        by_id["large"].weighted_objective_contribution
        / by_id["small"].weighted_objective_contribution
    ) == pytest.approx(4.0)


def test_return_goal_uses_same_context_scale_as_wealth_shortfall():
    goal = _liability(
        target_kind="return_rate",
        target_amount_rappen=1_000,  # 10% p.a.
    )
    paths = np.array([[100.0, 500.0]])  # savings must not help the TWR goal

    result = shortfall_objective(
        [goal],
        paths,
        initial_wealth_rappen=100,
        horizon_years=1,
        annualized_return_bps_per_path=np.array([0.0]),
    )

    # Implied target wealth is 110, TWR comparison wealth is 100:
    # dimensionless shortfall^2 = (10 / initial 100)^2.
    assert result == pytest.approx(0.1**2)


def test_cashflow_goal_uses_only_its_positive_due_index():
    goal = _liability(
        target_kind="cashflow_in_year",
        target_amount_rappen=10,
        target_year_index=1,  # deliberately differs from exact path due date
        liability_path_rappen=[0, 10, 0],
    )
    paths = np.array([
        [100.0, -25.0, 10.0, -30.0],  # negative before/after, funded when due
        [100.0, 25.0, -5.0, 30.0],    # five-Rappen gap exactly when due
    ])

    raw = shortfall_squared_per_path(
        goal,
        paths,
        initial_wealth_rappen=100,
        horizon_years=3,
    )
    probability = goal_probability_per_path(paths, goal, 100)

    assert raw.tolist() == pytest.approx([0.0, 5.0**2])
    assert probability.tolist() == [1, 0]


def test_outflow_stream_ignores_gaps_outside_own_payment_window():
    goal = _liability(
        target_kind="outflow_stream",
        target_amount_rappen=20,
        liability_path_rappen=[0, 10, 10, 0],
    )
    paths = np.array([
        [100.0, -20.0, 5.0, 7.0, -30.0],  # gaps only before/after dues
        [100.0, 20.0, 5.0, -7.0, 30.0],   # failure on the second due date
    ])

    raw = shortfall_squared_per_path(
        goal,
        paths,
        initial_wealth_rappen=100,
        horizon_years=4,
    )
    probability = goal_probability_per_path(paths, goal, 100)

    assert raw.tolist() == pytest.approx([0.0, 7.0**2])
    assert probability.tolist() == [1, 0]


@pytest.mark.parametrize("target_kind", ["cashflow_in_year", "outflow_stream"])
def test_spending_goal_without_positive_due_is_neutral(target_kind: str):
    goal = _liability(
        target_kind=target_kind,
        target_amount_rappen=0,
        liability_path_rappen=[0, 0, 0],
    )
    paths = np.array([[100.0, -10.0, -20.0, -30.0]])

    raw = shortfall_squared_per_path(
        goal,
        paths,
        initial_wealth_rappen=100,
        horizon_years=3,
    )

    assert raw.tolist() == [0.0]
    assert goal_probability_per_path(paths, goal, 100).tolist() == [1]


def test_phase_two_does_not_activate_for_nonzero_dimensionless_primary(monkeypatch):
    goal = _liability(
        target_amount_rappen=100,
        hardness_key="opportunistisch",  # no chance penalty; isolates switch
    )
    calls = 0

    def _volatility(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return 123.0

    monkeypatch.setattr(objective_module, "volatility_objective", _volatility)
    missed = np.array([[100.0, 99.0]])

    value = combined_objective_two_phase(
        [goal],
        missed,
        initial_wealth_rappen=100,
        horizon_years=1,
        volatility_weight=1.0,
    )

    assert value == pytest.approx(0.01**2)
    assert calls == 0

