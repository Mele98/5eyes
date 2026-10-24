"""MORT-CHANNEL / GOAL-FUNDING-PRIORITY-001, Vertrag 1 (Engine v10).

Uebernommen aus dem Codex-Audit-Reproducer
``docs/audits/reproducers/test_2026_10_18_mortality_p80_last_survivor_pr644_adversarial.py``
(nur ``test_priority_reconstruction_preserves_pathwise_mortality_mask``;
Vertrag 2 -- Feature-off-Paritaet -- liegt in PR #652). Regulaerer Test,
kein xfail. Einzige Anpassung: der Scope bekommt den eingefrorenen
Simulationskontext (``replay``) statt nur des aggregierten Pfads.
"""
from __future__ import annotations

import numpy as np

from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.objective import _priority_protected_wealth_paths
from services.optimizer.priority_scope import ScopeReplayInputs
from services.optimizer.scenario_engine import N_BUCKETS, simulate_wealth_paths


def _zero_return_wealth(
    liability_path: list[int],
    *,
    death_index: int,
) -> np.ndarray:
    return simulate_wealth_paths(
        initial_wealth_rappen=100,
        weights=np.full(N_BUCKETS, 1.0 / N_BUCKETS, dtype=np.float64),
        return_paths=np.ones((1, 2, N_BUCKETS), dtype=np.float64),
        cashflow_series_rappen=[0, 0],
        liability_path_rappen=liability_path,
        death_year_index_per_path=np.array([death_index], dtype=np.int32),
    )


def test_priority_reconstruction_preserves_pathwise_mortality_mask():
    """A masked post-death liability must not reappear as synthetic growth.

    v8 reconstruction: [100, 100, 160]; direct replay: [100, 100, 100].
    """
    joint_path = [0, 80]
    protected_scope = [0, 20]
    death_index = 1
    observed_joint = _zero_return_wealth(joint_path, death_index=death_index)
    expected_protected = _zero_return_wealth(
        protected_scope,
        death_index=death_index,
    )
    goal = GoalLiability(
        goal_id="rank-1-post-death",
        label="rank-1-post-death",
        goal_type="Einmalige_Ausgabe",
        target_kind="cashflow_in_year",
        target_amount_rappen=20,
        target_year_index=2,
        liability_path_rappen=protected_scope,
        hardness_key="hart",
        rank=1,
        priority_scope_liability_path_rappen=protected_scope,
        joint_liability_path_rappen=joint_path,
    )
    replay = ScopeReplayInputs(
        initial_wealth_rappen=100,
        weights=np.full(N_BUCKETS, 1.0 / N_BUCKETS, dtype=np.float64),
        return_paths=np.ones((1, 2, N_BUCKETS), dtype=np.float64),
        cashflow_series_rappen=(0, 0),
        joint_liability_path_rappen=tuple(joint_path),
        death_year_index_per_path=np.array([death_index], dtype=np.int32),
    )

    reconstructed, was_reconstructed = _priority_protected_wealth_paths(
        observed_joint,
        goal,
        replay=replay,
    )

    assert was_reconstructed is True
    np.testing.assert_allclose(observed_joint, [[100.0, 100.0, 100.0]])
    np.testing.assert_allclose(expected_protected, observed_joint)
    np.testing.assert_allclose(reconstructed, expected_protected)
