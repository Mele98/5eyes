"""Prioritaets-Scope mit pfadweiser Todesmaske ohne expliziten Replay-Kontext.

GOAL-FUNDING-PRIORITY-001 / MORT-CHANNEL-001, Restvertrag des Audit-
Reproducers ``test_2026_10_18_mortality_p80_last_survivor_pr644_adversarial.py``
(beide Tests unveraendert uebernommen, ohne xfail).

Soll-Invariante: Fuer jeden Pfad p, jedes Jahr t und jeden Scope S gilt

    W_S[p, t+1] = g(W_S[p, t]) * f[p, t] + alive[p, t] * (CF[t] - L_S[t])

mit ``alive[p, t] = t < death[p]`` und ``g`` = W2.5-Regel (kein Wachstum
negativer Vermoegen). Der Scope-Pfad wird also auf DENSELBEN Szenarien, mit
derselben Todesmaske und demselben Cashflow direkt simuliert; eine nach dem
Tod maskierte Liability darf nie als Wachstum wieder auftauchen. Ohne
expliziten Replay-Kontext gilt das, wenn der gemeinsame Pfad unveraendert aus
``simulate_wealth_paths`` stammt (festgehaltener Kontext); sonst Abbruch.
"""
from __future__ import annotations

import gc

import numpy as np
import pytest

from services.mandate_model_inputs import mortality_solver_kwargs_from_mandate
from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.objective import _priority_protected_wealth_paths
from services.optimizer.priority_scope import (
    PriorityScopeUnavailableError,
    PriorityScopeWealth,
    ScopeReplayInputs,
    retained_replay_inputs,
)
from services.optimizer.retained_simulation_context import retained_count
from services.optimizer.scenario_engine import N_BUCKETS, simulate_wealth_paths
from services.portfolio_engine_payload import (
    _expected_death_year_offset_from_mandate,
)
from tests.mortality.test_mortality_planning_quantile_last_survivor import (
    _mandate,
)

_EQUAL = np.full(N_BUCKETS, 1.0 / N_BUCKETS, dtype=np.float64)


# ---------------------------------------------------------------------------
# Audit-Reproducer (unveraendert, ohne xfail)
# ---------------------------------------------------------------------------


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
    """A masked post-death liability must not reappear as synthetic growth."""
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

    reconstructed, was_reconstructed = _priority_protected_wealth_paths(
        observed_joint,
        goal,
    )

    assert was_reconstructed is True
    np.testing.assert_allclose(observed_joint, [[100.0, 100.0, 100.0]])
    np.testing.assert_allclose(expected_protected, observed_joint)
    np.testing.assert_allclose(reconstructed, expected_protected)


def test_feature_off_report_and_solver_share_the_same_mortality_contract():
    """Feature-off cannot mean no solver cutoff but a report-side median."""
    mandate = _mandate(use_mortality_simulation=0)

    assert mortality_solver_kwargs_from_mandate(mandate) == {}
    assert _expected_death_year_offset_from_mandate(mandate) is None


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _goal(scope: list[int], joint: list[int], *, rank: int = 1, gid: str = "g") -> GoalLiability:
    return GoalLiability(
        goal_id=gid,
        label=gid,
        goal_type="Einmalige_Ausgabe",
        target_kind="cashflow_in_year",
        target_amount_rappen=int(max(scope) if scope else 0),
        target_year_index=len(scope),
        liability_path_rappen=list(scope),
        hardness_key="hart",
        rank=rank,
        priority_scope_liability_path_rappen=list(scope),
        joint_liability_path_rappen=list(joint),
    )


def _oracle(initial, factors, cashflow, liability, death):
    """Unabhaengige Schleife der Soll-Invariante (ohne Steuer)."""
    n_paths, horizon = factors.shape
    out = np.zeros((n_paths, horizon + 1))
    for p in range(n_paths):
        w = float(initial)
        out[p, 0] = w
        for t in range(horizon):
            grown = w * factors[p, t] if w > 0 else w
            alive = 1.0 if t < death[p] else 0.0
            w = grown + alive * cashflow[t] - alive * liability[t]
            out[p, t + 1] = w
    return out


# ---------------------------------------------------------------------------
# Referenzfall / Oracle
# ---------------------------------------------------------------------------


def test_reference_case_pathwise_different_death_indices_match_oracle():
    """Vier Pfade, Tod in Jahr 0/1/2/nie, Nullrendite: handgerechnet."""
    horizon = 3
    death = np.array([0, 1, 2, 9], dtype=np.int32)
    cashflow = [10, 10, 10]
    joint = [30, 40, 50]
    scope = [5, 0, 20]
    returns = np.ones((4, horizon, N_BUCKETS))
    observed = simulate_wealth_paths(
        initial_wealth_rappen=100, weights=_EQUAL, return_paths=returns,
        cashflow_series_rappen=cashflow, liability_path_rappen=joint,
        death_year_index_per_path=death,
    )
    scoped, replayed = _priority_protected_wealth_paths(observed, _goal(scope, joint))
    assert replayed is True
    expected = np.array([
        [100, 100, 100, 100],   # tot ab Jahr 0: nichts fliesst
        [100, 105, 105, 105],   # nur Jahr 0: +10 - 5
        [100, 105, 115, 115],   # Jahre 0..1: +10-5, +10-0
        [100, 105, 115, 105],   # lebt: +5, +10, -10
    ], dtype=np.float64)
    np.testing.assert_array_equal(scoped, expected)
    np.testing.assert_array_equal(
        scoped, _oracle(100, np.ones((4, horizon)), cashflow, scope, death),
    )
    # Der gemeinsame Pfad selbst folgt derselben Invariante.
    np.testing.assert_array_equal(
        observed, _oracle(100, np.ones((4, horizon)), cashflow, joint, death),
    )


def test_retained_context_equals_explicit_replay_bit_for_bit():
    rng = np.random.default_rng(7)
    horizon, n_paths = 6, 64
    returns = 1.0 + rng.normal(0.03, 0.12, size=(n_paths, horizon, N_BUCKETS))
    death = rng.integers(0, horizon + 2, size=n_paths).astype(np.int32)
    cashflow = [int(v) for v in rng.integers(-50, 80, size=horizon)]
    joint = [int(v) for v in rng.integers(0, 120, size=horizon)]
    scope = [int(v) // 3 for v in joint]
    goal = _goal(scope, joint)
    observed = simulate_wealth_paths(
        initial_wealth_rappen=1000, weights=_EQUAL, return_paths=returns,
        cashflow_series_rappen=cashflow, liability_path_rappen=joint,
        death_year_index_per_path=death,
    )
    explicit = ScopeReplayInputs(
        initial_wealth_rappen=1000, weights=_EQUAL, return_paths=returns,
        cashflow_series_rappen=tuple(cashflow),
        joint_liability_path_rappen=tuple(joint),
        death_year_index_per_path=death,
    )
    via_retained, _ = _priority_protected_wealth_paths(observed, goal)
    via_explicit, _ = _priority_protected_wealth_paths(observed, goal, replay=explicit)
    np.testing.assert_array_equal(via_retained, via_explicit)


# ---------------------------------------------------------------------------
# Deterministische Seed-Tests + Property/Metamorph
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(20))
def test_seeded_property_scope_equals_direct_simulation_and_oracle(seed):
    rng = np.random.default_rng(1000 + seed)
    horizon = int(rng.integers(1, 9))
    n_paths = int(rng.integers(1, 40))
    returns = 1.0 + rng.normal(0.02, 0.15, size=(n_paths, horizon, N_BUCKETS))
    weights = rng.dirichlet(np.ones(N_BUCKETS))
    death = rng.integers(0, horizon + 2, size=n_paths).astype(np.int32)
    cashflow = [int(v) for v in rng.integers(-300, 300, size=horizon)]
    joint = [int(v) for v in rng.integers(0, 400, size=horizon)]
    scope = [int(rng.integers(0, v + 1)) for v in joint]
    initial = int(rng.integers(0, 2000))
    observed = simulate_wealth_paths(
        initial_wealth_rappen=initial, weights=weights, return_paths=returns,
        cashflow_series_rappen=cashflow, liability_path_rappen=joint,
        death_year_index_per_path=death,
    )
    goal = _goal(scope, joint)
    scoped, replayed = _priority_protected_wealth_paths(observed, goal)
    direct = simulate_wealth_paths(
        initial_wealth_rappen=initial, weights=weights, return_paths=returns,
        cashflow_series_rappen=cashflow, liability_path_rappen=scope,
        death_year_index_per_path=death,
    )
    if scope == joint:
        assert replayed is False
        np.testing.assert_array_equal(scoped, observed)
        return
    assert replayed is True
    # Spalten nach der letzten gelesenen Faelligkeit sind bewusst NaN.
    due = [i + 1 for i, v in enumerate(scope) if v > 0]
    last = max(due) if due else 0
    np.testing.assert_allclose(scoped[:, : last + 1], direct[:, : last + 1], rtol=0, atol=1e-9)
    factors = np.einsum("phb,b->ph", returns, weights)
    np.testing.assert_allclose(
        scoped[:, : last + 1],
        _oracle(initial, factors, cashflow, scope, death)[:, : last + 1],
        rtol=1e-12, atol=1e-6,
    )


@pytest.mark.parametrize("seed", range(10))
def test_metamorphic_post_death_liability_is_irrelevant(seed):
    """Liability-Erhoehung nach dem Tod eines Pfads aendert diesen Pfad nicht."""
    rng = np.random.default_rng(5000 + seed)
    horizon, n_paths = 5, 12
    returns = 1.0 + rng.normal(0.01, 0.1, size=(n_paths, horizon, N_BUCKETS))
    death = np.full(n_paths, 2, dtype=np.int32)
    cashflow = [int(v) for v in rng.integers(0, 50, size=horizon)]
    joint = [int(v) for v in rng.integers(10, 100, size=horizon)]
    scope_a = [v // 2 for v in joint]
    scope_b = list(scope_a)
    for t in range(2, horizon):  # nur Jahre nach dem Tod aller Pfade
        scope_b[t] = scope_a[t] + int(rng.integers(1, 500))
    joint_b = [max(j, s) for j, s in zip(joint, scope_b)]

    def _scoped(joint_path, scope):
        observed = simulate_wealth_paths(
            initial_wealth_rappen=500, weights=_EQUAL, return_paths=returns,
            cashflow_series_rappen=cashflow, liability_path_rappen=joint_path,
            death_year_index_per_path=death,
        )
        return _priority_protected_wealth_paths(observed, _goal(scope, joint_path))[0]

    a = _scoped(joint, scope_a)
    b = _scoped(joint_b, scope_b)
    np.testing.assert_array_equal(a, b)


def test_metamorphic_death_beyond_horizon_equals_no_mortality():
    rng = np.random.default_rng(11)
    horizon, n_paths = 4, 16
    returns = 1.0 + rng.normal(0.02, 0.1, size=(n_paths, horizon, N_BUCKETS))
    cashflow, joint, scope = [5, 5, 5, 5], [40, 30, 20, 10], [10, 0, 20, 5]

    def _run(death):
        observed = simulate_wealth_paths(
            initial_wealth_rappen=300, weights=_EQUAL, return_paths=returns,
            cashflow_series_rappen=cashflow, liability_path_rappen=joint,
            death_year_index_per_path=death,
        )
        return _priority_protected_wealth_paths(observed, _goal(scope, joint))[0]

    np.testing.assert_array_equal(
        _run(np.full(n_paths, horizon, dtype=np.int32)), _run(None),
    )


def test_no_synthetic_growth_at_zero_return():
    """Nullrendite: kein Scope-Pfad uebersteigt Start + lebende Cashflows."""
    horizon, n_paths = 4, 5
    death = np.arange(n_paths, dtype=np.int32)
    cashflow, joint, scope = [0, 0, 0, 0], [80, 80, 80, 80], [20, 20, 20, 20]
    observed = simulate_wealth_paths(
        initial_wealth_rappen=100, weights=_EQUAL,
        return_paths=np.ones((n_paths, horizon, N_BUCKETS)),
        cashflow_series_rappen=cashflow, liability_path_rappen=joint,
        death_year_index_per_path=death,
    )
    scoped, _ = _priority_protected_wealth_paths(observed, _goal(scope, joint))
    assert float(np.max(scoped)) <= 100.0
    for p in range(n_paths):
        assert scoped[p, -1] == 100.0 - 20.0 * min(int(death[p]), horizon)


# ---------------------------------------------------------------------------
# Rand- und Fehlerfaelle: fail-closed
# ---------------------------------------------------------------------------


def _masked_case():
    observed = _zero_return_wealth([0, 80], death_index=1)
    return observed, _goal([0, 20], [0, 80])


def test_copy_of_joint_path_has_no_context_and_fails_closed():
    observed, goal = _masked_case()
    with pytest.raises(PriorityScopeUnavailableError):
        _priority_protected_wealth_paths(observed.copy(), goal)


def test_mutated_joint_path_fails_parity_and_closes():
    observed, goal = _masked_case()
    observed[0, 2] = 160.0
    with pytest.raises(PriorityScopeUnavailableError):
        _priority_protected_wealth_paths(observed, goal)


def test_goal_from_another_batch_is_rejected():
    observed = _zero_return_wealth([0, 80], death_index=1)
    foreign = _goal([0, 20], [0, 90])
    with pytest.raises(PriorityScopeUnavailableError):
        _priority_protected_wealth_paths(observed, foreign)


def test_opt_out_keeps_fail_closed():
    """Solver-Pfad: kein festgehaltener Kontext, expliziter Replay noetig."""
    observed = simulate_wealth_paths(
        initial_wealth_rappen=100, weights=_EQUAL,
        return_paths=np.ones((1, 2, N_BUCKETS)),
        cashflow_series_rappen=[0, 0], liability_path_rappen=[0, 80],
        death_year_index_per_path=np.array([1], dtype=np.int32),
        retain_scope_context=False,
    )
    assert retained_replay_inputs(observed) is None
    with pytest.raises(PriorityScopeUnavailableError):
        _priority_protected_wealth_paths(observed, _goal([0, 20], [0, 80]))


@pytest.mark.parametrize("tax_mode,n_bins", [("binned", 20), ("per_path", 20), ("median", 7)])
def test_tax_modes_the_replay_cannot_reproduce_are_not_retained(tax_mode, n_bins):
    observed = simulate_wealth_paths(
        initial_wealth_rappen=100, weights=_EQUAL,
        return_paths=np.ones((1, 2, N_BUCKETS)),
        cashflow_series_rappen=[0, 0], liability_path_rappen=[0, 80],
        tax_mode=tax_mode, tax_n_bins=n_bins,
    )
    assert retained_replay_inputs(observed) is None


def test_slice_and_subset_have_no_context():
    observed, goal = _masked_case()
    assert retained_replay_inputs(observed[:, :2]) is None
    wrapper = PriorityScopeWealth(joint=observed, liabilities=[goal])
    subset = wrapper.subset(np.array([0]))
    assert subset.replay is None
    np.testing.assert_array_equal(subset.for_goal(goal), [[100.0, 100.0, 100.0]])


def test_retained_context_is_released_with_the_array():
    gc.collect()
    before = retained_count()
    arrays = [_zero_return_wealth([0, 80], death_index=1) for _ in range(5)]
    assert retained_count() == before + 5
    del arrays
    gc.collect()
    assert retained_count() == before


def test_retention_does_not_change_any_number():
    rng = np.random.default_rng(3)
    returns = 1.0 + rng.normal(0.02, 0.1, size=(8, 5, N_BUCKETS))
    kwargs = dict(
        initial_wealth_rappen=777, weights=_EQUAL, return_paths=returns,
        cashflow_series_rappen=[1, -2, 3, -4, 5], liability_path_rappen=[9, 0, 9, 0, 9],
        death_year_index_per_path=rng.integers(0, 6, size=8).astype(np.int32),
    )
    np.testing.assert_array_equal(
        simulate_wealth_paths(**kwargs),
        simulate_wealth_paths(**kwargs, retain_scope_context=False),
    )
