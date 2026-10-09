"""Acceptance tests for the real GOAL-FUNDING-PRIORITY-001 fix
(CERT-GOAL-FUNDING-001).

See docs/audits/2026-10-08-goal-funding-ledger-and-achievability-attribution-
certification-spec.md Sec. 11.2 (Golden Cases) / 11.3 (Property tests).

These are NEW tests (not part of the four pre-existing permanent red tests)
added because two of the three remaining pre-existing xfail tests in this
audit round encode a self-contradictory expectation (see
GOAL-FUNDING-PRIORITY-001 PR description) and therefore cannot pin the real
fix. These tests exercise the actual production mechanism added in
services/optimizer/goal_liabilities.py (`rank`, per-goal priority-scope
liability paths) and services/optimizer/objective.py
(`goal_probability_per_path` priority-scope reconstruction) with scenarios
that are NOT self-contradictory.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.goal_liabilities import goals_to_liabilities
from services.optimizer.objective import goal_probability_per_path
from services.optimizer.scenario_engine import N_BUCKETS, simulate_wealth_paths

HORIZON_YEARS = 2


def _goal(
    *,
    goal_id: str,
    goal_type: str,
    hardness: str,
    rank: int,
    target_wealth_rappen: int | None = None,
    target_amount_rappen: int | None = None,
    horizon_years: int = HORIZON_YEARS,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=goal_id,
        label=goal_id,
        goal_type=goal_type,
        target_amount_rappen=target_amount_rappen,
        target_wealth_rappen=target_wealth_rappen,
        target_return_bps=None,
        horizon_years=horizon_years,
        target_date=None,
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness=hardness,
        rank=rank,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
    )


def _simulate(initial_wealth_rappen: int, liability_path_rappen: list[int]) -> np.ndarray:
    weights = np.full(N_BUCKETS, 1.0 / N_BUCKETS, dtype=np.float64)
    return_paths = np.ones((1, HORIZON_YEARS, N_BUCKETS), dtype=np.float64)
    return simulate_wealth_paths(
        initial_wealth_rappen=initial_wealth_rappen,
        weights=weights,
        return_paths=return_paths,
        cashflow_series_rappen=[0] * HORIZON_YEARS,
        liability_path_rappen=liability_path_rappen,
    )


def test_golden_case_1_hard_rank1_protected_from_opportunistic_rank5():
    """Spec 11.2 Golden Case 1: CHF 100 / CHF 90 hard rank 1 / CHF 20
    opportunistic rank 5 -> P_protected(hard) == 1.
    """
    hard = _goal(
        goal_id="hard-90", goal_type="Vermoegensziel", hardness="Hart",
        rank=1, target_wealth_rappen=90,
    )
    opportunistic = _goal(
        goal_id="opp-20", goal_type="Einmalige_Ausgabe", hardness="Opportunistisch",
        rank=5, target_amount_rappen=20, horizon_years=1,
    )
    liabilities = goals_to_liabilities([hard, opportunistic], horizon_years=HORIZON_YEARS)
    joint_liability_path = liabilities[0].joint_liability_path_rappen
    assert joint_liability_path == [20, 0]

    wealth_joint = _simulate(100, joint_liability_path)
    np.testing.assert_allclose(wealth_joint, [[100.0, 80.0, 80.0]])

    hard_liability = liabilities[0]
    opportunistic_liability = liabilities[1]

    p_protected_hard = float(
        goal_probability_per_path(wealth_joint, hard_liability, initial_value_rappen=100).mean()
    )
    p_protected_opp = float(
        goal_probability_per_path(
            wealth_joint, opportunistic_liability, initial_value_rappen=100
        ).mean()
    )

    assert p_protected_hard == pytest.approx(1.0), (
        "Hard rank-1 goal must be fully achievable on its priority-protected "
        "scope even though the opportunistic rank-5 goal's spend already "
        "happened in the shared joint wealth path."
    )
    # The opportunistic goal's OWN scope (S_5) includes every goal, so it is
    # evaluated on the same joint path as before -- unchanged.
    assert p_protected_opp == pytest.approx(1.0)


def test_golden_case_3_sufficient_wealth_both_goals_admissible():
    """Spec 11.2 Golden Case 3: sufficient wealth (CHF 120) -> both goals are
    admissible; protected and joint views agree on status.
    """
    hard = _goal(
        goal_id="hard-90", goal_type="Vermoegensziel", hardness="Hart",
        rank=1, target_wealth_rappen=90,
    )
    opportunistic = _goal(
        goal_id="opp-20", goal_type="Einmalige_Ausgabe", hardness="Opportunistisch",
        rank=5, target_amount_rappen=20, horizon_years=1,
    )
    liabilities = goals_to_liabilities([hard, opportunistic], horizon_years=HORIZON_YEARS)
    wealth_joint = _simulate(120, liabilities[0].joint_liability_path_rappen)

    p_hard = float(
        goal_probability_per_path(wealth_joint, liabilities[0], initial_value_rappen=120).mean()
    )
    p_opp = float(
        goal_probability_per_path(wealth_joint, liabilities[1], initial_value_rappen=120).mean()
    )
    assert p_hard == pytest.approx(1.0)
    assert p_opp == pytest.approx(1.0)


def test_hard_invariant_lower_priority_non_interference():
    """Hard Invariant #1: changes to a lower-rank (higher number) goal must
    never change a higher-priority goal's protected probability.
    """
    hard = _goal(
        goal_id="hard-90", goal_type="Vermoegensziel", hardness="Hart",
        rank=1, target_wealth_rappen=90,
    )
    small_opportunistic = _goal(
        goal_id="opp-5", goal_type="Einmalige_Ausgabe", hardness="Opportunistisch",
        rank=5, target_amount_rappen=5, horizon_years=1,
    )
    large_opportunistic = _goal(
        goal_id="opp-20", goal_type="Einmalige_Ausgabe", hardness="Opportunistisch",
        rank=5, target_amount_rappen=20, horizon_years=1,
    )

    liabilities_small = goals_to_liabilities([hard, small_opportunistic], horizon_years=HORIZON_YEARS)
    liabilities_large = goals_to_liabilities([hard, large_opportunistic], horizon_years=HORIZON_YEARS)

    wealth_small = _simulate(100, liabilities_small[0].joint_liability_path_rappen)
    wealth_large = _simulate(100, liabilities_large[0].joint_liability_path_rappen)

    p_hard_small = float(
        goal_probability_per_path(wealth_small, liabilities_small[0], initial_value_rappen=100).mean()
    )
    p_hard_large = float(
        goal_probability_per_path(wealth_large, liabilities_large[0], initial_value_rappen=100).mean()
    )
    assert p_hard_small == pytest.approx(1.0)
    assert p_hard_large == pytest.approx(1.0)
    assert p_hard_small == p_hard_large, (
        "A rank-1 hard goal's protected probability must be unaffected by "
        "the SIZE of a rank-5 opportunistic goal's own spend."
    )


def test_input_order_invariance_permutation_does_not_change_protected_outcome():
    """Hard Invariant #2: permuting the input goal list must not change any
    goal's protected probability or its own scope liability path.
    """
    hard = _goal(
        goal_id="hard-90", goal_type="Vermoegensziel", hardness="Hart",
        rank=1, target_wealth_rappen=90,
    )
    opportunistic = _goal(
        goal_id="opp-20", goal_type="Einmalige_Ausgabe", hardness="Opportunistisch",
        rank=5, target_amount_rappen=20, horizon_years=1,
    )

    forward = goals_to_liabilities([hard, opportunistic], horizon_years=HORIZON_YEARS)
    reversed_ = goals_to_liabilities([opportunistic, hard], horizon_years=HORIZON_YEARS)

    forward_hard = next(l for l in forward if l.goal_id == "hard-90")
    reversed_hard = next(l for l in reversed_ if l.goal_id == "hard-90")

    assert forward_hard.priority_scope_liability_path_rappen == reversed_hard.priority_scope_liability_path_rappen
    assert forward_hard.joint_liability_path_rappen == reversed_hard.joint_liability_path_rappen

    wealth_forward = _simulate(100, forward_hard.joint_liability_path_rappen)
    wealth_reversed = _simulate(100, reversed_hard.joint_liability_path_rappen)

    p_forward = float(
        goal_probability_per_path(wealth_forward, forward_hard, initial_value_rappen=100).mean()
    )
    p_reversed = float(
        goal_probability_per_path(wealth_reversed, reversed_hard, initial_value_rappen=100).mean()
    )
    assert p_forward == pytest.approx(p_reversed)
