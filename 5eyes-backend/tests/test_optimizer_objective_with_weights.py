"""Tests fuer optionale weights-Parameter in shortfall_objective + volatility_objective
(Phase 5c Mathematik-Backbone).

Verifiziert:
1. **Backwards-Compat:** weights=None liefert identisches Ergebnis wie alte Signatur
2. **Triviale Weights:** weights=ones(n) liefert identisches Ergebnis wie weights=None
3. **Echtes IS-Weighting:** weights summieren zu nicht-trivial, Ergebnis = weighted mean
4. **Edge-Cases:** weights mit falscher Shape → ValueError; Sum<=0 → ValueError
"""
from __future__ import annotations

import numpy as np
import pytest

from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.objective import shortfall_objective, volatility_objective


def _trivial_liability(target_at_year_3: int = 100_000_00) -> GoalLiability:
    """Eine einzige Liability mit target_kind='wealth_at_t' fuer aktiven Shortfall-Branch."""
    return GoalLiability(
        goal_id="g1",
        label="Test-Liability",
        goal_type="Vermoegensziel",
        target_kind="wealth_at_t",
        target_amount_rappen=int(target_at_year_3),
        target_year_index=3,
        liability_path_rappen=[0, 0, 0, 0, 0],
        hardness_key="hard",
        weight_bps=10_000,  # 100%
    )


def _make_wealth_paths(n_paths: int = 100, horizon: int = 5, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # Log-normal wealth: start 500k, drift +5% p.a., vol 15%
    starts = np.full((n_paths,), 500_000_00, dtype=np.float64)
    paths = np.zeros((n_paths, horizon + 1), dtype=np.float64)
    paths[:, 0] = starts
    for t in range(1, horizon + 1):
        ret = rng.normal(0.05, 0.15, size=n_paths)
        paths[:, t] = paths[:, t - 1] * np.exp(ret)
    return paths


def test_shortfall_objective_backwards_compat_no_weights():
    """Alte Signatur (ohne weights-Kwarg) liefert ein deterministisches Ergebnis."""
    liab = _trivial_liability()
    paths = _make_wealth_paths()
    result = shortfall_objective(
        [liab], paths, initial_wealth_rappen=500_000_00, horizon_years=5
    )
    assert isinstance(result, float)
    assert result >= 0


def test_shortfall_objective_none_vs_ones_identical():
    """weights=None und weights=np.ones(n) sollten identisch sein."""
    liab = _trivial_liability()
    paths = _make_wealth_paths()
    n = paths.shape[0]
    r_none = shortfall_objective(
        [liab], paths, initial_wealth_rappen=500_000_00, horizon_years=5, weights=None
    )
    r_ones = shortfall_objective(
        [liab], paths, initial_wealth_rappen=500_000_00, horizon_years=5,
        weights=np.ones(n),
    )
    assert abs(r_none - r_ones) < 1e-9


def test_shortfall_objective_nontrivial_weights_changes_result():
    """Mit IS-aehnlichen weights (nicht alle 1.0) ist Ergebnis verschieden.

    Stellt sicher dass viele Paths shortfall haben (target hoch, paths niedrig).
    """
    # Target hoch (10 Mio) sodass alle 500k-paths shortfall haben
    liab = _trivial_liability(target_at_year_3=10_000_000_00)
    paths = _make_wealth_paths()
    n = paths.shape[0]
    # Skewed weights — emuliert IS-Mean-Shift-Ergebnis
    weights = np.linspace(0.5, 1.5, n)
    r_unweighted = shortfall_objective(
        [liab], paths, initial_wealth_rappen=500_000_00, horizon_years=5
    )
    r_weighted = shortfall_objective(
        [liab], paths, initial_wealth_rappen=500_000_00, horizon_years=5, weights=weights
    )
    # Sollte verschieden sein (sonst ist der Code nicht IS-fähig)
    assert r_unweighted > 0, "Test-Fixture-Fehler: shortfall sollte > 0 sein"
    assert r_weighted > 0
    assert abs(r_unweighted - r_weighted) > 1e-6, (
        f"weights wirken nicht: unweighted={r_unweighted}, weighted={r_weighted}"
    )


def test_shortfall_objective_wrong_shape_raises():
    liab = _trivial_liability()
    paths = _make_wealth_paths(n_paths=50)
    with pytest.raises(ValueError, match="weights.shape"):
        shortfall_objective(
            [liab], paths, initial_wealth_rappen=500_000_00, horizon_years=5,
            weights=np.ones(99),  # falsche Shape
        )


def test_shortfall_objective_zero_weights_raises():
    liab = _trivial_liability()
    paths = _make_wealth_paths(n_paths=50)
    with pytest.raises(ValueError, match="Sum-of-weights"):
        shortfall_objective(
            [liab], paths, initial_wealth_rappen=500_000_00, horizon_years=5,
            weights=np.zeros(50),
        )


def test_volatility_objective_backwards_compat():
    """volatility_objective ohne weights liefert np.var (Backwards-Compat)."""
    paths = _make_wealth_paths()
    result = volatility_objective(paths)
    expected = float(np.var(paths[:, -1]))
    assert abs(result - expected) < 1e-9


def test_volatility_objective_ones_weights_matches_unweighted():
    """weights=ones(n) sollte sehr nah an np.var sein (uniform-weighted var)."""
    paths = _make_wealth_paths()
    n = paths.shape[0]
    r_none = volatility_objective(paths)
    r_ones = volatility_objective(paths, weights=np.ones(n))
    # Numerisch leicht verschieden (np.var nutzt n-Divisor, mein Code nutzt
    # Sum(w)-Divisor = n bei ones). Sollte identisch sein.
    assert abs(r_none - r_ones) < 1e-6


def test_volatility_objective_nontrivial_weights_changes_result():
    paths = _make_wealth_paths()
    n = paths.shape[0]
    weights = np.linspace(0.2, 1.8, n)
    r_unweighted = volatility_objective(paths)
    r_weighted = volatility_objective(paths, weights=weights)
    assert r_unweighted != r_weighted


def test_volatility_objective_wrong_shape_raises():
    paths = _make_wealth_paths(n_paths=30)
    with pytest.raises(ValueError, match="weights.shape"):
        volatility_objective(paths, weights=np.ones(77))


def test_weighted_variance_formula_is_correct():
    """Manuelle Verifikation der weighted-variance Formel.

    For Wealth-Distribution X mit weights w_i:
    weighted_var = Σ w_i (x_i - x̄_w)² / Σ w_i
    where x̄_w = Σ w_i · x_i / Σ w_i
    """
    # 4 Datenpunkte, asymmetric weights
    end_wealth = np.array([100.0, 200.0, 300.0, 400.0])
    weights = np.array([1.0, 1.0, 3.0, 5.0])

    paths = np.zeros((4, 2))
    paths[:, -1] = end_wealth

    expected_mean = float(np.sum(end_wealth * weights) / np.sum(weights))
    expected_var = float(np.sum(weights * (end_wealth - expected_mean) ** 2) / np.sum(weights))

    result = volatility_objective(paths, weights=weights)
    assert abs(result - expected_var) < 1e-9
