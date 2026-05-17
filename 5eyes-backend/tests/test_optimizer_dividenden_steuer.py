"""Sprint 2 Item 2 Tests: Dividenden-Yield + Kapitalertragssteuer.

Spec: docs/planning/2026-05-17-sprint-2-steuern-dividenden.md

3eyes Slide 20: 'Total Return basierend auf Dividend Yield Annahmen und
Preis-Rendite-Annahmen'. Wir trennen Total-Return in:
- Dividend-Anteil: aus CMA-Field dividend_yield_bps_X
- Preis-Anteil: implizit = Total Return - Dividend-Anteil
Steuer auf Dividend-Anteil: drag = dividend_yield * tax_rate (jaehrlich).

Verifiziert:
1. Backwards-Compat: ohne Parameter → identisches Wealth
2. Mit dividend_yield aber tax=0 → identisches Wealth (kein Drag)
3. Mit tax aber yield=0 (per_bucket) → identisches Wealth
4. Mit beiden aktiv → exakte Drag-Formel
5. Tax-Drag pro Bucket korrekt gewichtet (uniform weights vs. nur Equity)
6. Wrong-shape → ValueError
"""
from __future__ import annotations

import numpy as np
import pytest

from services.optimizer.scenario_engine import simulate_wealth_paths


def _constant_returns(n_paths: int, horizon: int, annual: float) -> np.ndarray:
    return np.full((n_paths, horizon, 5), 1.0 + annual, dtype=np.float64)


def test_no_dividend_no_tax_backwards_compat():
    """Default-Params (kein dividend_yield, kein tax) → no-op."""
    returns = _constant_returns(5, 3, 0.05)
    weights = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
    base = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 3,
    )
    with_div_no_tax = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 3,
        dividend_yield_bps_per_bucket=np.array([0, 0, 300, 200, 250]),
        kapitalertrag_steuer_bps=0,  # Steuer aus
    )
    no_div_with_tax = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 3,
        dividend_yield_bps_per_bucket=None,
        kapitalertrag_steuer_bps=2500,  # Tax aktiv aber kein Yield
    )
    assert np.array_equal(base, with_div_no_tax)
    assert np.array_equal(base, no_div_with_tax)


def test_dividend_tax_drag_exact_formula():
    """Drag-Formel: portfolio_drag = Σ_b weights_b * dividend_b * tax_rate.

    Setup: nur Equity_CH (Idx 2) hat dividend_yield 300 bps (3%),
    tax 2500 bps (25%). Weights: 100% Equity_CH.
    Erwarteter Drag pro Jahr: 1.0 * 0.03 * 0.25 = 0.0075 = 75 bps.

    Bei Return 5% → effektiver Return 5% - 0.75% = 4.25%.
    """
    returns = _constant_returns(1, 1, 0.05)
    weights = np.array([0.0, 0.0, 1.0, 0.0, 0.0])  # 100% Equity_CH
    div_yields = np.array([0, 0, 300, 0, 0])  # 3% Yield nur auf Equity_CH

    wealth_with = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=weights,
        return_paths=returns,
        cashflow_series_rappen=[0],
        dividend_yield_bps_per_bucket=div_yields,
        kapitalertrag_steuer_bps=2500,
    )
    expected = 1_000_000_00 * (1.05 - 0.03 * 0.25)
    assert abs(wealth_with[0, 1] - expected) < 1.0


def test_dividend_drag_zero_when_weights_skip_dividend_bucket():
    """Wenn nur Liquidity (Bucket 0) gewichtet wird und nur Equity_CH yield hat,
    kein Drag (Yield-bucket nicht gewichtet)."""
    returns = _constant_returns(1, 1, 0.05)
    weights = np.array([1.0, 0.0, 0.0, 0.0, 0.0])  # 100% Liquidity
    div_yields = np.array([0, 0, 300, 0, 0])  # 3% nur auf Equity_CH

    wealth_with_tax = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=weights,
        return_paths=returns,
        cashflow_series_rappen=[0],
        dividend_yield_bps_per_bucket=div_yields,
        kapitalertrag_steuer_bps=2500,
    )
    wealth_no_tax = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=weights,
        return_paths=returns,
        cashflow_series_rappen=[0],
    )
    # Identisches Ergebnis, weil weighted_drag = 0
    assert np.array_equal(wealth_with_tax, wealth_no_tax)


def test_dividend_drag_weighted_correctly_uniform_portfolio():
    """Uniform weights [0.2 * 5]: drag = 0.2 * Σ dividend_bps / 10000 * tax_rate.

    div_yields = [0, 0, 300, 200, 0], tax=2500 bps (25%).
    drag = 0.2 * (0.03 + 0.02) * 0.25 = 0.2 * 0.05 * 0.25 = 0.0025 = 25 bps."""
    returns = _constant_returns(1, 1, 0.05)
    weights = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
    div_yields = np.array([0, 0, 300, 200, 0])

    wealth = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=weights,
        return_paths=returns,
        cashflow_series_rappen=[0],
        dividend_yield_bps_per_bucket=div_yields,
        kapitalertrag_steuer_bps=2500,
    )
    # Drag = 0.2*(0.03+0.02)*0.25 = 0.0025
    # End-Wealth = initial * (1.05 - 0.0025) = initial * 1.0475
    expected = 1_000_000_00 * (1.05 - 0.0025)
    assert abs(wealth[0, 1] - expected) < 1.0


def test_dividend_drag_compounding_over_10_years():
    """5% Return mit 75bps Drag p.a. ueber 10 Jahre:
    no-tax = (1.05)^10 ≈ 1.629
    with-tax-drag = (1.05 - 0.0075)^10 = (1.0425)^10 ≈ 1.516"""
    returns = _constant_returns(1, 10, 0.05)
    weights = np.array([0.0, 0.0, 1.0, 0.0, 0.0])  # 100% Equity_CH
    div_yields = np.array([0, 0, 300, 0, 0])

    no_tax = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 10,
    )
    with_drag = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 10,
        dividend_yield_bps_per_bucket=div_yields,
        kapitalertrag_steuer_bps=2500,
    )
    no_tax_end = no_tax[0, -1] / 1_000_000_00
    drag_end = with_drag[0, -1] / 1_000_000_00
    assert abs(no_tax_end - 1.05 ** 10) < 1e-6
    assert abs(drag_end - 1.0425 ** 10) < 1e-6


def test_dividend_per_bucket_wrong_shape_raises():
    returns = _constant_returns(5, 3, 0.05)
    weights = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
    with pytest.raises(ValueError, match="dividend_yield_bps_per_bucket"):
        simulate_wealth_paths(
            initial_wealth_rappen=1_000_000_00,
            weights=weights,
            return_paths=returns,
            cashflow_series_rappen=[0] * 3,
            dividend_yield_bps_per_bucket=np.array([300, 200, 250]),  # wrong shape (3,)
            kapitalertrag_steuer_bps=2500,
        )


def test_combined_vermoegen_and_dividend_taxes():
    """Beide Steuer-Arten zusammen: Drag dann Vermoegenssteuer."""
    returns = _constant_returns(1, 1, 0.05)
    weights = np.array([0.0, 0.0, 1.0, 0.0, 0.0])
    div_yields = np.array([0, 0, 300, 0, 0])

    wealth = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=weights,
        return_paths=returns,
        cashflow_series_rappen=[0],
        vermoegenssteuer_bps_pa=50,  # 0.5%
        dividend_yield_bps_per_bucket=div_yields,
        kapitalertrag_steuer_bps=2500,
    )
    # Schritt 1: 1.05 - 0.0075 = 1.0425 (Kapitalertrag-Drag)
    # Schritt 2: * (1 - 0.005) = 1.0373... (Vermoegenssteuer)
    expected = 1_000_000_00 * 1.0425 * (1 - 0.005)
    assert abs(wealth[0, 1] - expected) < 1.0
