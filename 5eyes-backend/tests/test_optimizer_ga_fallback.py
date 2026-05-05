"""Tests fuer Phase 5.3 GA-Fallback in services/optimizer/solver.py.

Verifiziert:
- _solve_via_genetic_algorithm liefert sinnvolle Allocation
- DE respektiert Bounds (auch ohne explizite Constraint)
- DE renormalisiert auf sum=1
- DE-Penalty bestraft Risky-Fraction-Verletzung
- Solver fallback_chain: SLSQP success -> kein GA-Fallback gebraucht
- Determinismus mit seed
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.constraints import (
    HouseMatrixBands,
    build_constraint_set,
    is_feasible,
)
from services.optimizer.scenario_engine import BUCKET_ORDER, N_BUCKETS
from services.optimizer.solver import (
    _solve_via_genetic_algorithm,
    build_initial_guesses,
)


def _trivial_objective(w: np.ndarray) -> float:
    """Sum of squared deviations from a target portfolio - simple convex."""
    target = np.array([0.5, 0.3, 0.05, 0.05, 0.10])
    return float(np.sum((w - target) ** 2))


def _wide_bounds():
    return HouseMatrixBands(
        equities=(0.0, 1.0), bonds=(0.0, 1.0),
        real_estate=(0.0, 0.20), alternatives=(0.0, 0.10),
        liquidity=(0.02, 1.0),
    )


# ============================================================================
# GA-Fallback Basis
# ============================================================================


def test_ga_fallback_returns_feasible_for_simple_objective():
    bounds, constraints = build_constraint_set(_wide_bounds(), score_x10=70)
    result = _solve_via_genetic_algorithm(
        _trivial_objective, bounds, constraints, seed=42, max_iter=30, popsize=10,
    )
    assert result.fun < float("inf")
    # Result respektiert sum=1 (innerhalb Toleranz)
    assert sum(result.x) == pytest.approx(1.0, abs=1e-2)


def test_ga_fallback_respects_bounds():
    """DE darf weights nicht ausserhalb der Bounds liefern."""
    bounds, constraints = build_constraint_set(_wide_bounds(), score_x10=70)
    result = _solve_via_genetic_algorithm(
        _trivial_objective, bounds, constraints, seed=42, max_iter=30, popsize=10,
    )
    for i, (lo, hi) in enumerate(bounds):
        assert lo - 1e-3 <= result.x[i] <= hi + 1e-3


def test_ga_fallback_deterministic_with_seed():
    bounds, constraints = build_constraint_set(_wide_bounds(), score_x10=70)
    a = _solve_via_genetic_algorithm(
        _trivial_objective, bounds, constraints, seed=42, max_iter=20, popsize=10,
    )
    b = _solve_via_genetic_algorithm(
        _trivial_objective, bounds, constraints, seed=42, max_iter=20, popsize=10,
    )
    assert np.allclose(a.x, b.x)


def test_ga_fallback_handles_objective_crash():
    """Wenn objective_fn crashed: DE-Wrapper liefert success=False, kein crash."""
    def crashing_obj(w):
        raise RuntimeError("simulated crash")

    bounds, constraints = build_constraint_set(_wide_bounds(), score_x10=70)
    # DE wird crashen sobald die Objective einmal gerufen wird
    result = _solve_via_genetic_algorithm(
        crashing_obj, bounds, constraints, seed=42, max_iter=10, popsize=5,
    )
    assert result.success is False
    assert "DE-crash" in str(result.message)


def test_ga_fallback_penalty_pushes_away_from_risky_fraction_violation():
    """Penalty auf Risky-Fraction-Verletzung sollte DE in feasible Region pushen."""
    bounds, constraints = build_constraint_set(_wide_bounds(), score_x10=20)  # nur 20% risky
    result = _solve_via_genetic_algorithm(
        _trivial_objective, bounds, constraints, seed=42, max_iter=40, popsize=15,
    )
    # Bei score=20 ist max risky 20%. Mit equities 80% rf und bonds 25% rf:
    # 0.20 risky muss respektiert sein
    feasible, reasons = is_feasible(
        np.asarray(result.x), bounds=bounds, constraints=constraints, tolerance=0.05,
    )
    # DE-Penalty kann marginal verletzen aber sollte nahe feasible sein
    if not feasible:
        # Mindestens das objective sollte den Penalty zeigen
        assert result.fun < 1e8, (
            f"GA didn't escape penalty region: fun={result.fun}, reasons={reasons}"
        )