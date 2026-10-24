"""GOAL-ACHIEVABILITY-ATTRIBUTION-001, Restbefund A (Review PR #659).

``publish_goal_achievability`` las die Zielzeilen aus dem Scope-Wrapper und
die Plan-Solvenz aus dem separaten ``wealth_paths``-Argument, ohne beide
aneinander zu binden. Ein fremder Pfad kippte die Plan-Solvenz von 0 auf 1.

Der erste Test ist der unabhaengige Reproducer, unveraendert ohne xfail.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = next(
    p for p in Path(__file__).resolve().parents
    if (p / "services" / "optimizer" / "priority_scope.py").is_file()
)
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.goal_attribution import publish_goal_achievability  # noqa: E402
from services.optimizer.goal_liabilities import GoalLiability  # noqa: E402
from services.optimizer.priority_scope import (  # noqa: E402
    PriorityScopeUnavailableError,
    PriorityScopeWealth,
    ScopeReplayInputs,
)
from services.optimizer.scenario_engine import N_BUCKETS  # noqa: E402


def test_publication_must_reject_scope_wrapper_bound_to_another_joint_path():
    """One publication must not combine two different plan paths."""
    goal = GoalLiability(
        goal_id="rank-1",
        label="rank-1",
        goal_type="Einmalige_Ausgabe",
        target_kind="cashflow_in_year",
        target_amount_rappen=20,
        target_year_index=1,
        liability_path_rappen=[20],
        hardness_key="hart",
        rank=1,
        priority_scope_liability_path_rappen=[20],
        joint_liability_path_rappen=[120],
    )
    replay = ScopeReplayInputs(
        initial_wealth_rappen=100,
        weights=np.full(N_BUCKETS, 1.0 / N_BUCKETS),
        return_paths=np.ones((400, 1, N_BUCKETS)),
        cashflow_series_rappen=(0,),
        joint_liability_path_rappen=(120,),
    )
    true_joint = replay.simulate([120])
    foreign_joint = replay.simulate([0])
    scopes = PriorityScopeWealth(
        joint=true_joint,
        liabilities=[goal],
        replay=replay,
    )

    with pytest.raises(PriorityScopeUnavailableError):
        publish_goal_achievability(
            foreign_joint,
            [goal],
            100,
            scope_wealth=scopes,
        )


# --------------------------------------------------------------------------
# Pflichtregressionen
# --------------------------------------------------------------------------


def _wealth_goal(goal_id: str = "w", *, rank: int = 1, amount: int = 100) -> GoalLiability:
    return GoalLiability(
        goal_id=goal_id,
        label=goal_id,
        goal_type="Vermoegensziel",
        target_kind="wealth_at_t",
        target_amount_rappen=amount,
        target_year_index=2,
        liability_path_rappen=[0, 0],
        hardness_key="primaer",
        rank=rank,
    )


def _paths(middle: float, end: float, n: int = 50) -> np.ndarray:
    paths = np.empty((n, 3), dtype=np.float64)
    paths[:, 0] = 100.0
    paths[:, 1] = middle
    paths[:, 2] = end
    return paths


def test_same_object_and_bitwise_copy_are_accepted_with_identical_rows():
    goal = _wealth_goal()
    joint = _paths(110.0, 120.0)
    same = publish_goal_achievability(
        joint, [goal], 100,
        scope_wealth=PriorityScopeWealth(joint=joint, liabilities=[goal]),
    )
    copied = publish_goal_achievability(
        joint.copy(), [goal], 100,
        scope_wealth=PriorityScopeWealth(joint=joint, liabilities=[goal]),
    )
    plain = publish_goal_achievability(joint, [goal], 100)
    assert same == copied == plain


def test_same_end_value_but_different_intermediate_path_is_rejected():
    """Gleiche Form und gleiche Endzahl reichen nicht: die Bahn zaehlt."""
    goal = _wealth_goal()
    wrapper_joint = _paths(110.0, 120.0)
    foreign = _paths(-5.0, 120.0)
    with pytest.raises(PriorityScopeUnavailableError):
        publish_goal_achievability(
            foreign, [goal], 100,
            scope_wealth=PriorityScopeWealth(joint=wrapper_joint, liabilities=[goal]),
        )


def test_wrapper_without_differing_scope_is_still_bound():
    """Auch ohne Replay liest jede Zielzeile ``wrapper.joint``: Bindung gilt immer."""
    goal = _wealth_goal()
    with pytest.raises(PriorityScopeUnavailableError):
        publish_goal_achievability(
            _paths(110.0, 50.0), [goal], 100,
            scope_wealth=PriorityScopeWealth(joint=_paths(110.0, 120.0), liabilities=[goal]),
        )


def test_shape_mismatch_is_rejected():
    goal = _wealth_goal()
    joint = _paths(110.0, 120.0)
    with pytest.raises(PriorityScopeUnavailableError):
        publish_goal_achievability(
            joint[:10], [goal], 100,
            scope_wealth=PriorityScopeWealth(joint=joint, liabilities=[goal]),
        )


def test_wrapper_from_another_goal_batch_is_rejected():
    """Gleicher Pfad, aber Wrapper aus einem anderen Ziel-Batch: fail-closed."""
    joint = _paths(110.0, 120.0)
    published = [_wealth_goal("a"), _wealth_goal("b", rank=2)]
    other_batch = [_wealth_goal("a"), _wealth_goal("c", rank=2)]
    with pytest.raises(PriorityScopeUnavailableError):
        publish_goal_achievability(
            joint, published, 100,
            scope_wealth=PriorityScopeWealth(joint=joint, liabilities=other_batch),
        )
    changed_rank = [_wealth_goal("a"), _wealth_goal("b", rank=3)]
    with pytest.raises(PriorityScopeUnavailableError):
        publish_goal_achievability(
            joint, published, 100,
            scope_wealth=PriorityScopeWealth(joint=joint, liabilities=changed_rank),
        )


def test_batch_order_is_not_part_of_the_identity():
    joint = _paths(110.0, 120.0)
    a, b = _wealth_goal("a"), _wealth_goal("b", rank=2)
    rows = publish_goal_achievability(
        joint, [a, b], 100,
        scope_wealth=PriorityScopeWealth(joint=joint, liabilities=[b, a]),
    )
    assert [row["goal_id"] for row in rows[:2]] == ["a", "b"]
