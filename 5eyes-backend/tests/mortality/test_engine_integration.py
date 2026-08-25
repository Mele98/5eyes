"""Engine-Integration: simulate_wealth_paths mit death_year_index_per_path."""
from __future__ import annotations

import numpy as np
import pytest

from services.mortality.bfs import BFS_2020_2022
from services.mortality.sampler import (
    death_year_index_from_age,
    sample_age_at_death,
)
from services.optimizer.scenario_engine import simulate_wealth_paths


@pytest.fixture
def constant_returns():
    def _make(n_paths: int = 3, horizon: int = 10):
        return np.full((n_paths, horizon, 5), 1.05, dtype=np.float64)
    return _make


@pytest.fixture
def uniform_weights():
    return np.array([0.2, 0.2, 0.2, 0.2, 0.2])


def test_backwards_compat_no_mortality(constant_returns, uniform_weights):
    """death_year_index=None → identisches Verhalten wie ohne Mortality."""
    returns = constant_returns(n_paths=3, horizon=5)
    wealth_no_param = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[10_000_00] * 5,
    )
    wealth_explicit_none = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[10_000_00] * 5,
        death_year_index_per_path=None,
    )
    np.testing.assert_array_equal(wealth_no_param, wealth_explicit_none)


def test_cashflow_zero_after_death(constant_returns, uniform_weights):
    """Pfad mit death_index=3: cashflow in t=0,1,2 aktiv, t=3,4 = 0."""
    returns = constant_returns(n_paths=1, horizon=5)
    cashflow_per_year = 10_000_00  # positiv

    # Ohne Mortality: cashflow alle 5 Jahre
    wealth_alive = simulate_wealth_paths(
        initial_wealth_rappen=0,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[cashflow_per_year] * 5,
    )

    # Mit death_index=3: cashflow nur in t=0,1,2
    wealth_dies = simulate_wealth_paths(
        initial_wealth_rappen=0,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[cashflow_per_year] * 5,
        death_year_index_per_path=np.array([3], dtype=np.int32),
    )
    # wealth_dies sollte am Ende weniger haben als wealth_alive
    assert wealth_dies[0, -1] < wealth_alive[0, -1]


def test_liability_zero_after_death(constant_returns, uniform_weights):
    """Liability nach Tod auch 0 (Pension-Ausgaben stoppen)."""
    returns = constant_returns(n_paths=1, horizon=5)
    liability_per_year = 50_000_00

    wealth_dies = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 5,
        liability_path_rappen=[liability_per_year] * 5,
        death_year_index_per_path=np.array([2], dtype=np.int32),
    )
    wealth_no_death = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 5,
        liability_path_rappen=[liability_per_year] * 5,
    )
    # Wer frueher stirbt, hat mehr Wealth uebrig (weniger Liability abgezogen)
    assert wealth_dies[0, -1] > wealth_no_death[0, -1]


def test_wrong_shape_raises(constant_returns, uniform_weights):
    returns = constant_returns(n_paths=3, horizon=5)
    with pytest.raises(ValueError, match="death_year_index"):
        simulate_wealth_paths(
            initial_wealth_rappen=1_000_000_00,
            weights=uniform_weights,
            return_paths=returns,
            cashflow_series_rappen=[0] * 5,
            death_year_index_per_path=np.array([3, 3], dtype=np.int32),  # 2 statt 3
        )


def test_growth_continues_after_death(constant_returns, uniform_weights):
    """Vermoegen waechst auch nach Tod weiter (Erbschaft fuer Erben)."""
    returns = constant_returns(n_paths=1, horizon=5)
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 5,
        death_year_index_per_path=np.array([2], dtype=np.int32),
    )
    # Wachstum 1.05 pro Jahr ueber 5 Jahre = 1.27628
    expected = 1_000_000_00 * 1.05 ** 5
    assert abs(wealth[0, -1] - expected) < 100


def test_realistic_mortality_with_sampler(constant_returns, uniform_weights):
    """End-to-end: Sampler → death_index → Engine."""
    horizon = 30
    n_paths = 1000
    returns = constant_returns(n_paths=n_paths, horizon=horizon)

    # Mandant 65, Mann, 1 Mio Wealth, will 50k/Jahr Pension auszahlen
    death_ages = sample_age_at_death(
        n_paths=n_paths,
        current_age=65,
        sex="M",
        table=BFS_2020_2022,
        seed=42,
    )
    death_idx = death_year_index_from_age(
        death_ages, current_age=65, horizon_years=horizon
    )

    wealth = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[-50_000_00] * horizon,  # Auszahlung
        death_year_index_per_path=death_idx,
    )
    # Plausibilitaet: alle Pfade haben validen Wealth (kein NaN/Inf)
    assert np.isfinite(wealth).all()
    # Pfade die frueh sterben haben mehr Wealth uebrig
    early_death_paths = death_idx < 10
    if early_death_paths.any():
        early_mean = wealth[early_death_paths, -1].mean()
        late_death_paths = death_idx >= 20
        if late_death_paths.any():
            late_mean = wealth[late_death_paths, -1].mean()
            assert early_mean > late_mean


def test_all_paths_die_at_index_one(constant_returns, uniform_weights):
    """Wenn alle in t=1 sterben: cashflow nur in t=0, dann 0."""
    n_paths = 5
    returns = constant_returns(n_paths=n_paths, horizon=5)
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=0,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[100_000_00] * 5,
        death_year_index_per_path=np.ones(n_paths, dtype=np.int32),
    )
    # Jeder Pfad bekommt nur den ersten cashflow (100k)
    # dann wachsen 4 Jahre lang ohne weiteren Cashflow
    expected = 100_000_00 * 1.05 ** 4
    np.testing.assert_allclose(wealth[:, -1], expected, rtol=1e-6)


def test_per_path_different_death_times(constant_returns, uniform_weights):
    """Verschiedene death_index pro Pfad → unterschiedlich akkumuliertes Wealth."""
    returns = constant_returns(n_paths=3, horizon=5)
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=0,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[100_000_00] * 5,
        death_year_index_per_path=np.array([1, 3, 5], dtype=np.int32),
    )
    # Pfad 0 (death=1): 1 cashflow, dann 4 Jahre Wachstum
    # Pfad 1 (death=3): 3 cashflows, dann 2 Jahre Wachstum
    # Pfad 2 (death=5): 5 cashflows, kein weiteres Wachstum
    # Pfad 2 sollte mehr Wealth haben als Pfad 0
    assert wealth[2, -1] > wealth[1, -1] > wealth[0, -1]
