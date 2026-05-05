"""Tests fuer services/optimizer/scenario_engine.py.

Verifiziert:
- Shape-Korrektheit (n_paths, horizon, 5) fuer Returns; (n_paths, horizon+1) fuer Wealth
- Determinismus mit gleichem Seed
- Antithetic verdoppelt nicht-trivial die Sample-Anzahl
- Cornish-Fisher Vektor-Variante matcht skalare Variante
- Wealth wird negativ bei zu negativem Cashflow (W2.5)
- Wachstum wirkt nicht auf negativen Wealth (W2.5)
- Standard-Cholesky bei degenerierter Matrix faellt auf Identity zurueck
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.distributions import cornish_fisher_quantile
from services.optimizer.scenario_engine import (
    BUCKET_ORDER,
    N_BUCKETS,
    ScenarioInputs,
    build_default_correlation_matrix,
    build_scenario_paths,
    cornish_fisher_array,
    scenario_inputs_from_cma,
    simulate_wealth_paths,
)


# ============================================================================
# Hilfsfunktionen
# ============================================================================


def _make_cma(**overrides):
    """Mock-CMA als SimpleNamespace mit allen Optimizer-relevanten Feldern."""
    defaults = {
        "bonds_chf_ig_return_bps": 220,
        "bonds_chf_ig_vol_bps": 350,
        "bonds_fx_hedged_return_bps": 220,
        "bonds_fx_hedged_vol_bps": 430,
        "equity_ch_return_bps": 620,
        "equity_ch_vol_bps": 1450,
        "equity_intl_return_bps": 700,
        "equity_intl_vol_bps": 1600,
        "real_estate_ch_return_bps": 450,
        "real_estate_ch_vol_bps": 820,
        "alternatives_gold_return_bps": 300,
        "alternatives_gold_vol_bps": 1200,
        "liquidity_return_bps": 80,
        "liquidity_vol_bps": 20,
        "correlation_matrix_json": "",
        "equities_skewness_bps": 0,
        "equities_excess_kurt_bps": 0,
        "bonds_skewness_bps": 0,
        "bonds_excess_kurt_bps": 0,
        "real_estate_skewness_bps": 0,
        "real_estate_excess_kurt_bps": 0,
        "alternatives_skewness_bps": 0,
        "alternatives_excess_kurt_bps": 0,
        "liquidity_skewness_bps": 0,
        "liquidity_excess_kurt_bps": 0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _identity_inputs(*, mu=500, sigma=1000):
    """Trivial-Inputs: alle Buckets gleiche mu/sigma, identity Korrelation."""
    return ScenarioInputs(
        mu_bps=np.full(N_BUCKETS, mu, dtype=np.float64),
        sigma_bps=np.full(N_BUCKETS, sigma, dtype=np.float64),
        skew_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        excess_kurt_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        cholesky=np.eye(N_BUCKETS),
    )


# ============================================================================
# Cornish-Fisher Vektor vs Skalar
# ============================================================================


def test_cf_array_matches_scalar_for_each_element():
    """cornish_fisher_array(z, s, k) muss elementweise identisch zu skalaren CF sein."""
    z = np.array([-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0])
    skew = np.full_like(z, -0.4)
    kurt = np.full_like(z, 1.5)
    arr_out = cornish_fisher_array(z, skew, kurt)
    for i, zi in enumerate(z):
        scalar_out = cornish_fisher_quantile(zi, -0.4, 1.5)
        assert arr_out[i] == pytest.approx(scalar_out, rel=1e-12)


def test_cf_array_clips_inputs_like_scalar():
    """Extreme Inputs werden geclamped, Vektor-Variante respektiert das."""
    z = np.array([1.0])
    out_extreme = cornish_fisher_array(z, np.array([5.0]), np.array([0.0]))
    out_clamped = cornish_fisher_array(z, np.array([1.0]), np.array([0.0]))
    assert out_extreme[0] == pytest.approx(out_clamped[0], rel=1e-12)


# ============================================================================
# build_scenario_paths
# ============================================================================


def test_scenario_paths_shape_correct():
    inputs = _identity_inputs()
    paths = build_scenario_paths(inputs, horizon_years=10, n_paths=100, seed=42)
    assert paths.shape == (100, 10, N_BUCKETS)


def test_scenario_paths_deterministic_same_seed():
    inputs = _identity_inputs()
    a = build_scenario_paths(inputs, horizon_years=5, n_paths=50, seed=12345)
    b = build_scenario_paths(inputs, horizon_years=5, n_paths=50, seed=12345)
    assert np.array_equal(a, b)


def test_scenario_paths_different_seeds_produce_different_arrays():
    inputs = _identity_inputs()
    a = build_scenario_paths(inputs, horizon_years=5, n_paths=50, seed=1)
    b = build_scenario_paths(inputs, horizon_years=5, n_paths=50, seed=2)
    assert not np.allclose(a, b)


def test_scenario_paths_with_zero_vol_returns_constant_factor():
    """sigma=0 -> exp(mu - 0) = exp(mu), kein Random-Effekt."""
    inputs = ScenarioInputs(
        mu_bps=np.full(N_BUCKETS, 500, dtype=np.float64),
        sigma_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        skew_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        excess_kurt_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        cholesky=np.eye(N_BUCKETS),
    )
    paths = build_scenario_paths(inputs, horizon_years=3, n_paths=10, seed=42)
    # Alle Returns sollten exp(0.05) ~= 1.0513 sein
    expected = math.exp(0.05)
    assert np.allclose(paths, expected, rtol=1e-10)


def test_scenario_paths_antithetic_doubles_paths():
    """Mit antithetic=True wird auf n_paths gerundet (effektiv 2x sample size).

    Verifizierung: erste Haelfte und zweite Haelfte sind nicht identisch
    (nur die underlying Z-werte sind antithetic).
    """
    inputs = _identity_inputs()
    paths_anti = build_scenario_paths(inputs, horizon_years=2, n_paths=100, seed=42, antithetic=True)
    paths_no = build_scenario_paths(inputs, horizon_years=2, n_paths=100, seed=42, antithetic=False)
    # Beide haben shape (100, 2, 5)
    assert paths_anti.shape == paths_no.shape
    # Aber die zweite Haelfte mit antithetic ist anders als die erste
    first_half = paths_anti[:50]
    second_half = paths_anti[50:]
    assert not np.allclose(first_half, second_half)


def test_scenario_paths_with_negative_skew_creates_left_skewed_returns():
    """Negativer Skew -> mehr extreme negative Returns als positive Returns."""
    inputs = ScenarioInputs(
        mu_bps=np.array([500, 500, 500, 500, 500], dtype=np.float64),
        sigma_bps=np.array([1500, 1500, 1500, 1500, 1500], dtype=np.float64),
        skew_bps=np.array([-5000, -5000, -5000, -5000, -5000], dtype=np.float64),  # -0.5 skew
        excess_kurt_bps=np.array([20000, 20000, 20000, 20000, 20000], dtype=np.float64),  # 2.0 kurt
        cholesky=np.eye(N_BUCKETS),
    )
    paths = build_scenario_paths(inputs, horizon_years=1, n_paths=20000, seed=42, antithetic=False)
    # Returns fuer Bucket 0 (equities)
    returns = paths[:, 0, 0]  # alle Pfade, Jahr 0, Bucket 0
    # Frequenz extrem-tiefer Returns (<0.85 = mehr als -15% Verlust)
    freq_severe_loss = np.mean(returns < 0.85)
    # Mit Normal-Distribution waere das: 1.4% (P(R < 0.85) bei mu=5%, sigma=15%)
    # Mit fat tails sollte das deutlich hoeher sein
    assert freq_severe_loss > 0.025, (
        f"Mit fat tails muessen severe losses haeufiger sein, got {freq_severe_loss:.4f}"
    )


# ============================================================================
# simulate_wealth_paths
# ============================================================================


def test_wealth_paths_shape_horizon_plus_one():
    inputs = _identity_inputs(mu=0, sigma=0)
    paths = build_scenario_paths(inputs, horizon_years=5, n_paths=10, seed=42)
    weights = np.array([0.6, 0.3, 0.0, 0.0, 0.1])
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=100_000_00,
        weights=weights,
        return_paths=paths,
        cashflow_series_rappen=[0] * 5,
    )
    assert wealth.shape == (10, 6)


def test_wealth_paths_initial_wealth_at_index_zero():
    inputs = _identity_inputs(mu=0, sigma=0)
    paths = build_scenario_paths(inputs, horizon_years=3, n_paths=5, seed=42)
    weights = np.array([0.5, 0.5, 0, 0, 0])
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=500_000_00,
        weights=weights,
        return_paths=paths,
        cashflow_series_rappen=[0] * 3,
    )
    assert np.all(wealth[:, 0] == 500_000_00)


def test_wealth_paths_zero_returns_zero_cashflow_stays_constant():
    """Mit mu=0/sigma=0 (= return-factor=1.0) und cashflow=0 bleibt wealth konstant."""
    inputs = _identity_inputs(mu=0, sigma=0)
    paths = build_scenario_paths(inputs, horizon_years=4, n_paths=3, seed=42)
    weights = np.array([0.4, 0.3, 0.2, 0.0, 0.1])  # summe 1.0
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=weights,
        return_paths=paths,
        cashflow_series_rappen=[0] * 4,
    )
    # Alle Pfade in allen Jahren haben gleichen Wert
    assert np.allclose(wealth, 1_000_000_00, rtol=1e-9)


def test_wealth_paths_can_go_negative_with_excessive_outflow():
    """W2.5: Cashflow zehrt Vermoegen auf -> wealth wird negativ (Lebensluecke)."""
    inputs = _identity_inputs(mu=0, sigma=0)
    paths = build_scenario_paths(inputs, horizon_years=3, n_paths=5, seed=42)
    weights = np.array([0, 0, 0, 0, 1.0])  # alles Liquiditaet
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=100_000_00,
        weights=weights,
        return_paths=paths,
        cashflow_series_rappen=[-200_000_00] * 3,
    )
    # Year 1: 100k - 200k = -100k
    # Year 2: -100k (kein Wachstum bei Schuld) - 200k = -300k
    # Year 3: -300k - 200k = -500k
    assert wealth[0, 1] == pytest.approx(-100_000_00)
    assert wealth[0, 2] == pytest.approx(-300_000_00)
    assert wealth[0, 3] == pytest.approx(-500_000_00)


def test_wealth_paths_negative_wealth_does_not_grow():
    """W2.5: Wenn wealth negativ ist, wirkt der Return-Faktor nicht (kein Schuldzins)."""
    inputs = _identity_inputs(mu=1000, sigma=0)  # 10% return
    paths = build_scenario_paths(inputs, horizon_years=2, n_paths=2, seed=42)
    weights = np.array([1.0, 0, 0, 0, 0])  # 100% equities
    # Start mit -50k Vermoegen (artificial)
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=-50_000_00,
        weights=weights,
        return_paths=paths,
        cashflow_series_rappen=[0, 0],
    )
    # Year 1 und 2: bleibt bei -50k weil negativ -> kein Wachstum
    assert np.allclose(wealth[:, 1], -50_000_00)
    assert np.allclose(wealth[:, 2], -50_000_00)


def test_wealth_paths_with_liability_subtracts_from_wealth():
    """liability_path subtrahiert vom Wealth (Goal-Outflow)."""
    inputs = _identity_inputs(mu=0, sigma=0)
    paths = build_scenario_paths(inputs, horizon_years=3, n_paths=2, seed=42)
    weights = np.array([0, 0, 0, 0, 1.0])
    # Cashflow 0, Liability 50k in Jahr 2 (Index 1)
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=200_000_00,
        weights=weights,
        return_paths=paths,
        cashflow_series_rappen=[0, 0, 0],
        liability_path_rappen=[0, 50_000_00, 0],
    )
    # Year 1: 200k -> 200k (no liability)
    # Year 2: 200k - 50k = 150k
    # Year 3: 150k -> 150k
    assert wealth[0, 1] == pytest.approx(200_000_00)
    assert wealth[0, 2] == pytest.approx(150_000_00)
    assert wealth[0, 3] == pytest.approx(150_000_00)


def test_wealth_paths_with_short_cashflow_pads_with_zero():
    """Wenn cashflow_series kuerzer als horizon: Auffuellen mit 0."""
    inputs = _identity_inputs(mu=0, sigma=0)
    paths = build_scenario_paths(inputs, horizon_years=5, n_paths=2, seed=42)
    weights = np.array([0, 0, 0, 0, 1.0])
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=100_000_00,
        weights=weights,
        return_paths=paths,
        cashflow_series_rappen=[10_000_00],  # nur 1 Jahr
    )
    # Year 1: 100k + 10k = 110k. Danach kein cashflow.
    assert wealth[0, 1] == pytest.approx(110_000_00)
    assert wealth[0, 5] == pytest.approx(110_000_00)


# ============================================================================
# scenario_inputs_from_cma
# ============================================================================


def test_scenario_inputs_aggregates_equity_returns():
    cma = _make_cma(equity_ch_return_bps=600, equity_intl_return_bps=800)
    inputs = scenario_inputs_from_cma(cma)
    # Equities = avg(600, 800) = 700
    assert inputs.mu_bps[BUCKET_ORDER.index("equities")] == 700.0


def test_scenario_inputs_uses_default_correlation_when_json_empty():
    cma = _make_cma(correlation_matrix_json="")
    inputs = scenario_inputs_from_cma(cma)
    expected_default = build_default_correlation_matrix()
    expected_chol = np.linalg.cholesky(expected_default)
    assert np.allclose(inputs.cholesky, expected_chol)


def test_scenario_inputs_picks_skew_kurt_from_cma_when_set():
    cma = _make_cma(equities_skewness_bps=-5000, equities_excess_kurt_bps=25000)
    inputs = scenario_inputs_from_cma(cma)
    eq_idx = BUCKET_ORDER.index("equities")
    assert inputs.skew_bps[eq_idx] == -5000
    assert inputs.excess_kurt_bps[eq_idx] == 25000


def test_scenario_inputs_falls_back_to_zero_when_skew_kurt_none():
    cma = _make_cma(equities_skewness_bps=None, equities_excess_kurt_bps=None)
    inputs = scenario_inputs_from_cma(cma)
    eq_idx = BUCKET_ORDER.index("equities")
    assert inputs.skew_bps[eq_idx] == 0
    assert inputs.excess_kurt_bps[eq_idx] == 0


# ============================================================================
# Performance Sanity (kleiner Benchmark)
# ============================================================================


def test_scenario_engine_can_handle_2000_paths_10_years_in_reasonable_time():
    """Performance-Sanity: 2000 paths x 10 years sollte in <1s laufen."""
    import time
    inputs = _identity_inputs()
    t0 = time.perf_counter()
    paths = build_scenario_paths(inputs, horizon_years=10, n_paths=2000, seed=42)
    elapsed = time.perf_counter() - t0
    assert paths.shape == (2000, 10, 5)
    assert elapsed < 1.0, f"Performance regression: {elapsed:.3f}s for 2000x10x5 paths"


def test_wealth_simulation_vectorized_handles_large_batch():
    """Wealth-Simulation fuer 5000 paths x 30 years sollte <0.5s sein."""
    import time
    inputs = _identity_inputs()
    paths = build_scenario_paths(inputs, horizon_years=30, n_paths=5000, seed=42)
    weights = np.array([0.5, 0.3, 0.1, 0.0, 0.1])
    t0 = time.perf_counter()
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=weights,
        return_paths=paths,
        cashflow_series_rappen=[0] * 30,
    )
    elapsed = time.perf_counter() - t0
    assert wealth.shape == (5000, 31)
    assert elapsed < 0.5, f"Wealth-sim too slow: {elapsed:.3f}s"
