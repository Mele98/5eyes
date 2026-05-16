"""Tests fuer build_scenario_paths_with_weights — der IS-faehige Wrapper
fuer scenario_engine.build_scenario_paths.

Phase 5b der Stochastic-Optimizer-Spec: nicht-disruptive Erweiterung des
Pfad-Generators um optional Importance-Sampling. Wrapper liefert immer
ein (paths, weights)-Tupel; bei IS=off ist weights[i]=1.0 trivial,
bei IS=on sind weights die Likelihood-Ratios.
"""
from __future__ import annotations

import numpy as np
import pytest

from services.optimizer.scenario_engine import (
    N_BUCKETS,
    ScenarioInputs,
    build_scenario_paths,
    build_scenario_paths_with_weights,
)


def _trivial_inputs() -> ScenarioInputs:
    """Minimale CMA-Inputs fuer Test-Zwecke."""
    return ScenarioInputs(
        mu_bps=np.array([50, 150, 600, 700, 300], dtype=np.float64),
        sigma_bps=np.array([10, 300, 1500, 1800, 1000], dtype=np.float64),
        skew_bps=np.zeros(5),
        excess_kurt_bps=np.zeros(5),
        cholesky=np.linalg.cholesky(np.eye(5)),
    )


def test_wrapper_off_matches_legacy_build_scenario_paths():
    """Wenn IS=off, sollten die Pfade identisch zu build_scenario_paths sein."""
    inputs = _trivial_inputs()
    legacy = build_scenario_paths(inputs, horizon_years=5, n_paths=100, seed=42, antithetic=True)
    wrapped, weights = build_scenario_paths_with_weights(
        inputs, horizon_years=5, n_paths=100, seed=42, antithetic=True, use_importance_sampling=False
    )
    assert np.array_equal(legacy, wrapped)
    assert weights.shape == (100,)
    assert np.allclose(weights, 1.0)


def test_wrapper_returns_correct_shapes():
    inputs = _trivial_inputs()
    paths, weights = build_scenario_paths_with_weights(
        inputs, horizon_years=10, n_paths=500, seed=1, use_importance_sampling=True
    )
    assert paths.shape == (500, 10, N_BUCKETS)
    assert weights.shape == (500,)
    assert np.all(weights > 0), "Likelihood-Weights muessen strikt positiv sein"


def test_wrapper_is_active_uses_weights_not_trivial():
    """Wenn IS aktiv, sind die Weights nicht-trivial (nicht alle 1.0)."""
    inputs = _trivial_inputs()
    _, weights = build_scenario_paths_with_weights(
        inputs, horizon_years=5, n_paths=200, seed=7, use_importance_sampling=True
    )
    # Mindestens einige Pfade haben Weight != 1.0
    assert not np.allclose(weights, 1.0)


def test_wrapper_is_deterministic_with_seed():
    """Gleicher Seed → identische (paths, weights) bei IS-aktiv."""
    inputs = _trivial_inputs()
    p1, w1 = build_scenario_paths_with_weights(
        inputs, horizon_years=3, n_paths=50, seed=99, use_importance_sampling=True
    )
    p2, w2 = build_scenario_paths_with_weights(
        inputs, horizon_years=3, n_paths=50, seed=99, use_importance_sampling=True
    )
    assert np.array_equal(p1, p2)
    assert np.array_equal(w1, w2)


def test_wrapper_unbiased_estimator_for_terminal_wealth():
    """Mit IS sollte E_proposal[wealth_T * w] ≈ E_target[wealth_T].

    Wir bauen 5000 Pfade mit IS=on und 5000 mit IS=off (gleiche
    Konfiguration), berechnen Terminal-Wealth-Mean und vergleichen.
    """
    inputs = _trivial_inputs()
    horizon, n = 3, 5000

    # Without IS
    paths_off, w_off = build_scenario_paths_with_weights(
        inputs, horizon_years=horizon, n_paths=n, seed=2024, use_importance_sampling=False
    )
    terminal_off = np.prod(paths_off, axis=1)  # (n, n_buckets)
    mean_off = (terminal_off * w_off[:, None]).sum(axis=0) / w_off.sum()

    # With IS
    paths_on, w_on = build_scenario_paths_with_weights(
        inputs, horizon_years=horizon, n_paths=n, seed=2024, use_importance_sampling=True
    )
    terminal_on = np.prod(paths_on, axis=1)  # (n, n_buckets)
    mean_on = (terminal_on * w_on[:, None]).sum(axis=0) / w_on.sum()

    # Beide Estimators sollten ~gleichen Mean ergeben (innerhalb MC-Fehler).
    # Liquidity-Bucket (Idx 0) ist quasi-deterministisch (sigma 10bps), sollte
    # sehr nah beieinander sein.
    rel_diff_liq = abs(mean_off[0] - mean_on[0]) / max(abs(mean_off[0]), 1e-10)
    assert rel_diff_liq < 0.001, (
        f"Liquidity-Mean (deterministisch): off={mean_off[0]:.5f}, on={mean_on[0]:.5f}"
    )
    # Equity-Buckets duerfen toleranter divergieren (IS reduziert Tail-Variance,
    # aber Mean bleibt unverzerrt; mit 5000 Pfaden sollte rel_diff < 5%)
    for bucket in [2, 3]:
        rel_diff = abs(mean_off[bucket] - mean_on[bucket]) / max(abs(mean_off[bucket]), 1e-10)
        assert rel_diff < 0.05, (
            f"Bucket {bucket}: off={mean_off[bucket]:.5f}, on={mean_on[bucket]:.5f}, rel_diff={rel_diff:.4%}"
        )


def test_wrapper_default_off():
    """Default-Parameter ist use_importance_sampling=False."""
    inputs = _trivial_inputs()
    paths, weights = build_scenario_paths_with_weights(
        inputs, horizon_years=2, n_paths=10, seed=1
    )
    assert np.allclose(weights, 1.0), "Default sollte IS aus haben"
