"""Red test for GOAL-ACHIEVABILITY-ATTRIBUTION-001 (Kontrollrunde 37).

Audit: docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md

Finding: the solver simulates exactly ONE shared wealth path after ALL goal
outflows, and feeds that SAME path into every individual goal's
shortfall/probability calculation (services/optimizer/objective.py). When two
goals are simultaneously due, both get the SAME probability and the SAME
shortfall magnitude, even though their target amounts, hardness, and rank
differ -- because there is no per-goal causal/funding attribution, only a
shared aggregate state evaluated twice from two different "due index"
viewpoints.

This test constructs two simultaneous one-off goals with very different
target amounts (CHF 90 hard, CHF 20 opportunistic) against the real
production ``GoalLiability`` dataclass and the real
``shortfall_squared_per_path`` / ``goal_probability_per_path`` functions, and
demonstrates that the shortfall/probability evidence for both goals comes out
mathematically IDENTICAL despite the very different target amounts.

A second, non-xfail "positive control" test proves the harness/call path
itself is sound: with only ONE goal present (no simultaneous competitor), its
shortfall correctly reflects just its own target.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.objective import (
    goal_probability_per_path,
    shortfall_squared_per_path,
)


def _one_off_goal(
    *,
    goal_id: str,
    target_amount_rappen: float,
    hardness: str,
    horizon_years: int = 1,
    target_year_index: int = 1,
) -> GoalLiability:
    """Build a real one-off 'Einmalige_Ausgabe'-shaped GoalLiability.

    liability_path_rappen mirrors exactly what
    services/optimizer/goal_liabilities.py::_build_einmalige_ausgabe produces:
    a single positive outflow entry at ``target_year_index - 1``, target_kind
    'cashflow_in_year'.
    """
    path = [0] * horizon_years
    path[target_year_index - 1] = target_amount_rappen
    return GoalLiability(
        goal_id=goal_id,
        label=f"Test goal {goal_id}",
        goal_type="Einmalige_Ausgabe",
        target_kind="cashflow_in_year",
        target_amount_rappen=target_amount_rappen,
        target_year_index=target_year_index,
        liability_path_rappen=path,
        hardness_key=hardness,
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-ACHIEVABILITY-ATTRIBUTION-001 -- round 47 red test, see audit "
        "docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md"
    ),
)
def test_simultaneous_goals_with_different_targets_get_identical_shortfall_and_probability():
    """Two simultaneous goals (CHF 90 hard vs CHF 20 opportunistic) should NOT
    receive identical shortfall/probability evidence -- but they do, because
    both are evaluated against the same shared aggregate wealth path.
    """
    initial_wealth_rappen = 100.0
    horizon_years = 1

    goal_a_hard = _one_off_goal(
        goal_id="goal-a-hard-90",
        target_amount_rappen=90.0,
        hardness="hart",
        horizon_years=horizon_years,
    )
    goal_b_opportunistic = _one_off_goal(
        goal_id="goal-b-opportunistic-20",
        target_amount_rappen=20.0,
        hardness="opportunistisch",
        horizon_years=horizon_years,
    )

    # The ONE shared wealth path the real scenario engine produces once BOTH
    # goals' outflows have been subtracted: 100 - 90 - 20 = -10.
    shared_wealth_paths = np.array([[initial_wealth_rappen, -10.0]], dtype=np.float64)

    shortfall_a = shortfall_squared_per_path(
        goal_a_hard,
        shared_wealth_paths,
        initial_wealth_rappen=initial_wealth_rappen,
        horizon_years=horizon_years,
    )
    shortfall_b = shortfall_squared_per_path(
        goal_b_opportunistic,
        shared_wealth_paths,
        initial_wealth_rappen=initial_wealth_rappen,
        horizon_years=horizon_years,
    )

    probability_a = goal_probability_per_path(
        shared_wealth_paths, goal_a_hard, initial_wealth_rappen
    )
    probability_b = goal_probability_per_path(
        shared_wealth_paths, goal_b_opportunistic, initial_wealth_rappen
    )

    # Sanity: both shortfalls come out as (-(-10))^2 = 100, regardless of the
    # 90-vs-20 target difference -- this is the bug, reproduced with the real
    # production functions.
    assert shortfall_a[0] == pytest.approx(100.0)
    assert shortfall_b[0] == pytest.approx(100.0)
    assert probability_a[0] == 0
    assert probability_b[0] == 0

    # This is the assertion that SHOULD hold if per-goal causal attribution
    # existed: a CHF 90 hard goal and a CHF 20 opportunistic goal must not
    # produce indistinguishable shortfall/probability evidence. It currently
    # FAILS because both read off the same negative shared wealth state.
    assert shortfall_a[0] != shortfall_b[0], (
        "Goal A (target 90) and Goal B (target 20) must not get identical "
        "shortfall evidence -- GOAL-ACHIEVABILITY-ATTRIBUTION-001"
    )


def test_single_goal_shortfall_reflects_its_own_target_positive_control():
    """Positive control (no xfail): with only ONE goal present, no shared
    aggregate contamination is possible -- the shortfall must correctly
    reflect just this goal's own target. Proves the harness/call path above
    is sound and the xfail failure is not a test-construction artifact.
    """
    initial_wealth_rappen = 100.0
    horizon_years = 1

    goal_only = _one_off_goal(
        goal_id="goal-only-150",
        target_amount_rappen=150.0,
        hardness="hart",
        horizon_years=horizon_years,
    )

    # Wealth path with ONLY this goal's own outflow subtracted: 100 - 150 = -50.
    wealth_paths = np.array([[initial_wealth_rappen, -50.0]], dtype=np.float64)

    shortfall = shortfall_squared_per_path(
        goal_only,
        wealth_paths,
        initial_wealth_rappen=initial_wealth_rappen,
        horizon_years=horizon_years,
    )
    probability = goal_probability_per_path(
        wealth_paths, goal_only, initial_wealth_rappen
    )

    # Gap is exactly -(-50) = 50 -> squared shortfall = 2500, tied to this
    # goal's own 150 target via the wealth path that only this goal funded.
    assert shortfall[0] == pytest.approx(50.0 ** 2)
    assert probability[0] == 0

    # Now show the goal succeeding on its own terms: wealth after its own
    # outflow is non-negative (100 - 90 = 10).
    goal_small = _one_off_goal(
        goal_id="goal-only-90",
        target_amount_rappen=90.0,
        hardness="hart",
        horizon_years=horizon_years,
    )
    wealth_paths_ok = np.array([[initial_wealth_rappen, 10.0]], dtype=np.float64)
    shortfall_ok = shortfall_squared_per_path(
        goal_small,
        wealth_paths_ok,
        initial_wealth_rappen=initial_wealth_rappen,
        horizon_years=horizon_years,
    )
    probability_ok = goal_probability_per_path(
        wealth_paths_ok, goal_small, initial_wealth_rappen
    )
    assert shortfall_ok[0] == pytest.approx(0.0)
    assert probability_ok[0] == 1
