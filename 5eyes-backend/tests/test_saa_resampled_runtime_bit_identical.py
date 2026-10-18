"""SAA-RESAMPLED-RUNTIME-001 (2026-10-18): Laufzeit-Optimierungen im
Zielfunktions-Hotpath duerfen KEIN Ergebnis veraendern.

Hintergrund: Mit dem Resampling (SAA-RESAMPLED-STABILITY-001, 40 Bags je
Lauf) wertet der Solver die Zielfunktion je Lauf ~10'000-mal aus. Die
Stage-8-Laufzeitgrenze (``shadow_comparison.classify_shadow_verdict``:
``elapsed_ms > 15000`` = RED) brach dadurch im CI. Beschleunigt wurde
ausschliesslich bitidentisch:

* ``simulate_wealth_paths`` leitet die Portfolio-Faktoren einmal fuer alle
  Jahre ab (bzw. uebernimmt sie vom Solver) und rechnet die steuerfreie
  Rekursion auf zusammenhaengenden Zeilen.
* ``_positive_due_wealth_indices`` ist gecacht (reine Funktion des Plans).
* ``chance_constraint_penalty`` rechnet das ESS einmal statt je Ziel.

Diese Tests vergleichen gegen eine woertliche Kopie der bisherigen
Jahres-Schleife -- ``np.array_equal`` (bitgenau bis auf das Vorzeichen von
Null), keine Toleranz.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.objective import _positive_due_wealth_indices
from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.scenario_engine import simulate_wealth_paths
from services.tax.regimes.generic import GenericFlatRateRegime


def _reference_untaxed(
    *,
    initial_wealth_rappen,
    weights,
    return_paths,
    cashflow_series_rappen,
    liability_path_rappen=None,
    death_year_index_per_path=None,
):
    """Woertliche Kopie der Rekursion vor SAA-RESAMPLED-RUNTIME-001."""
    return_paths = np.asarray(return_paths, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64).reshape(5)
    n_paths, horizon, _ = return_paths.shape
    cashflow = np.asarray(list(cashflow_series_rappen), dtype=np.float64)
    if liability_path_rappen is None:
        liability = np.zeros(horizon, dtype=np.float64)
    else:
        liability = np.asarray(list(liability_path_rappen), dtype=np.float64)
    if death_year_index_per_path is not None:
        death_idx = np.asarray(death_year_index_per_path, dtype=np.int32)
        t_range = np.arange(horizon, dtype=np.int32)
        alive_mask = t_range[None, :] < death_idx[:, None]
        cashflow_per_path = cashflow[None, :] * alive_mask
        liability_per_path = liability[None, :] * alive_mask
    else:
        cashflow_per_path = None
        liability_per_path = None
    wealth = np.empty((n_paths, horizon + 1), dtype=np.float64)
    wealth[:, 0] = float(initial_wealth_rappen)
    for t in range(horizon):
        portfolio_factor = np.einsum("pb,b->p", return_paths[:, t, :], weights)
        prev = wealth[:, t]
        grown = np.where(prev > 0, prev * portfolio_factor, prev)
        if cashflow_per_path is not None:
            wealth[:, t + 1] = grown + cashflow_per_path[:, t] - liability_per_path[:, t]
        else:
            wealth[:, t + 1] = grown + cashflow[t] - liability[t]
    return wealth


def _random_case(rng):
    n_paths = int(rng.choice([1, 3, 500, 2000]))
    horizon = int(rng.integers(1, 45))
    return_paths = 1.0 + rng.normal(0.03, 0.2, (n_paths, horizon, 5))
    weights = rng.dirichlet(np.ones(5))
    liability = rng.integers(0, 20_000_00, horizon)
    # Viele Jahre ohne Outflow: der Pfad, der die Subtraktion auslaesst.
    liability[rng.random(horizon) < 0.6] = 0
    return dict(
        initial_wealth_rappen=int(rng.integers(0, 5_000_000_00)),
        weights=weights,
        return_paths=return_paths,
        # Stark negative Cashflows: Pfade werden negativ (W2.5-Zweig).
        cashflow_series_rappen=rng.integers(-60_000_00, 30_000_00, horizon).tolist(),
        liability_path_rappen=(liability.tolist() if rng.random() < 0.8 else None),
        death_year_index_per_path=(
            rng.integers(0, horizon + 3, n_paths) if rng.random() < 0.4 else None
        ),
    )


@pytest.mark.parametrize("seed", range(6))
def test_simulate_wealth_paths_fast_path_bit_identical(seed):
    rng = np.random.default_rng(1000 + seed)
    saw_negative_wealth = False
    for _ in range(40):
        case = _random_case(rng)
        expected = _reference_untaxed(**case)
        actual = simulate_wealth_paths(**case)
        factors = np.einsum("phb,b->ph", case["return_paths"], case["weights"])
        with_factors = simulate_wealth_paths(**case, portfolio_factors=factors)
        assert actual.shape == expected.shape
        assert actual.flags.c_contiguous
        assert np.array_equal(actual, expected)
        assert np.array_equal(with_factors, expected)
        saw_negative_wealth = saw_negative_wealth or bool(np.any(expected < 0))
    # Negative Pfade muessen tatsaechlich vorkommen, sonst prueft der Test
    # den W2.5-Zweig (kein Wachstum auf negativem Vermoegen) nicht.
    assert saw_negative_wealth


def test_portfolio_factors_equal_per_year_einsum():
    """Die ganze Ersparnis haengt an dieser Gleichheit: einmalige
    Kontraktion ueber alle Jahre == Kontraktion je Jahr, bitgenau."""
    rng = np.random.default_rng(7)
    for _ in range(100):
        n_paths = int(rng.choice([2, 7, 500, 2000]))
        horizon = int(rng.integers(1, 45))
        paths = 1.0 + rng.normal(0.0, 0.15, (n_paths, horizon, 5))
        weights = rng.dirichlet(np.ones(5))
        full = np.einsum("phb,b->ph", paths, weights)
        for t in range(horizon):
            assert np.array_equal(
                full[:, t], np.einsum("pb,b->p", paths[:, t, :], weights)
            )


def test_taxed_path_uses_same_factors():
    """Der Steuerpfad nimmt die Faktoren jetzt aus derselben einmaligen
    Ableitung; mit einem Null-Regime muss er exakt der steuerfreien
    Referenz entsprechen."""
    rng = np.random.default_rng(11)
    for _ in range(10):
        case = _random_case(rng)
        case["death_year_index_per_path"] = None
        expected = _reference_untaxed(**case)
        actual = simulate_wealth_paths(**case, tax_regime=GenericFlatRateRegime())
        assert np.array_equal(actual, expected)


def test_portfolio_factors_shape_is_validated():
    paths = np.ones((4, 3, 5))
    with pytest.raises(ValueError, match="portfolio_factors"):
        simulate_wealth_paths(
            initial_wealth_rappen=100,
            weights=np.full(5, 0.2),
            return_paths=paths,
            cashflow_series_rappen=[0, 0, 0],
            portfolio_factors=np.ones((4, 2)),
        )


def test_due_indices_cache_returns_read_only_identical_indices():
    liability = GoalLiability(
        goal_id="g",
        label="Ziel",
        goal_type="test",
        target_kind="outflow_stream",
        target_amount_rappen=100,
        target_year_index=2,
        liability_path_rappen=[0, 5, 0, 7, 0],
    )
    first = _positive_due_wealth_indices(liability, n_wealth_columns=5)
    second = _positive_due_wealth_indices(liability, n_wealth_columns=5)
    assert first.tolist() == [2, 4]
    assert first.dtype == np.intp
    assert not first.flags.writeable
    assert second is first
    # Anderer Plan / anderer Horizont -> eigener Eintrag.
    assert _positive_due_wealth_indices(
        liability, n_wealth_columns=4
    ).tolist() == [2]
