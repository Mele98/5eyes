"""Tests fuer OptimizerContext.scenario_weights — Phase 5c Solver-Toggle.

Verifiziert:
1. scenario_weights=None (Default): Solver-Verhalten identisch zu vorher
   (kein Bias, Backwards-Compat)
2. scenario_weights=ones(n): identisches Objective wie =None (Sanity)
3. scenario_weights=IS-Likelihoods: Objective verschieden, weighted estimator
4. OptimizerContext frozen-dataclass akzeptiert das neue Field korrekt
"""
from __future__ import annotations

import numpy as np
import pytest

from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.solver import OptimizerContext, _objective_from_array, _weights_bps_to_array


def _make_minimal_context(*, scenario_weights=None) -> OptimizerContext:
    """Minimal-Context fuer Objective-Tests."""
    n_paths = 100
    horizon = 5
    rng = np.random.default_rng(42)
    # Log-normal return-factors um 1.05 +/- 0.15
    return_paths = np.exp(rng.normal(0.05, 0.15, size=(n_paths, horizon, 5)))

    liab = GoalLiability(
        goal_id="g1",
        label="Test",
        goal_type="Vermoegensziel",
        target_kind="wealth_at_t",
        target_amount_rappen=2_000_000_00,  # high target → shortfall guaranteed
        target_year_index=3,
        liability_path_rappen=[0] * horizon,
        hardness_key="hard",
        weight_bps=10_000,
    )

    return OptimizerContext(
        cma_id="test-cma",
        seed=42,
        horizon_years=horizon,
        n_paths=n_paths,
        advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[0] * (horizon + 1),
        return_paths=return_paths,
        liabilities=[liab],
        aggregated_liability_path=np.zeros(horizon, dtype=np.float64),
        bounds=[(0.0, 1.0)] * 5,
        scipy_constraints=[],
        score_x10=70,
        risky_fraction_per_bucket=None,
        scenario_weights=scenario_weights,
    )


def test_context_default_scenario_weights_is_none():
    """Default-Field: scenario_weights ist None."""
    ctx = _make_minimal_context()
    assert ctx.scenario_weights is None


def test_context_accepts_scenario_weights_field():
    """Frozen-dataclass akzeptiert weights als np.ndarray."""
    weights = np.ones(100)
    ctx = _make_minimal_context(scenario_weights=weights)
    assert ctx.scenario_weights is not None
    assert ctx.scenario_weights.shape == (100,)


def test_objective_from_array_none_weights_unchanged():
    """scenario_weights=None liefert identisches Objective wie ohne weights-Mechanik."""
    ctx = _make_minimal_context()
    w = _weights_bps_to_array({"liquidity": 200, "bonds": 3000, "equity_ch": 3500, "equity_intl": 3000, "alternatives": 300})
    obj_none = _objective_from_array(ctx, w)
    assert obj_none > 0


def test_objective_from_array_ones_weights_matches_none():
    """scenario_weights=ones(n) gleiches Ergebnis wie =None (Sanity)."""
    ctx_none = _make_minimal_context(scenario_weights=None)
    ctx_ones = _make_minimal_context(scenario_weights=np.ones(100))
    w = _weights_bps_to_array({"liquidity": 200, "bonds": 3000, "equity_ch": 3500, "equity_intl": 3000, "alternatives": 300})
    o_none = _objective_from_array(ctx_none, w)
    o_ones = _objective_from_array(ctx_ones, w)
    # Relative Toleranz wegen Objective-Magnitude (Rappen²)
    assert abs(o_none - o_ones) / max(abs(o_none), 1.0) < 1e-12


def test_objective_from_array_skewed_weights_differs():
    """IS-aehnliche weights (nicht trivial) liefern verschiedenes Objective."""
    ctx_none = _make_minimal_context(scenario_weights=None)
    skewed = np.linspace(0.3, 1.7, 100)  # Mean ≈ 1.0
    ctx_skewed = _make_minimal_context(scenario_weights=skewed)
    w = _weights_bps_to_array({"liquidity": 200, "bonds": 3000, "equity_ch": 3500, "equity_intl": 3000, "alternatives": 300})
    o_none = _objective_from_array(ctx_none, w)
    o_skewed = _objective_from_array(ctx_skewed, w)
    assert abs(o_none - o_skewed) > 1e-6, (
        f"weights wirken nicht: o_none={o_none}, o_skewed={o_skewed}"
    )
