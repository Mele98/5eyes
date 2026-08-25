"""Engine-Integration: simulate_wealth_paths mit tax_regime-Parameter.

Spec: docs/planning/2026-05-17-sprint-3-tax-plugin-system.md §6
"""
from __future__ import annotations

import numpy as np
import pytest

from services.optimizer.scenario_engine import simulate_wealth_paths
from services.tax.regimes.generic import GenericFlatRateRegime


@pytest.fixture
def constant_returns():
    """Konstante 5% pro Jahr ueber alle Buckets — deterministisch fuer Tests."""
    def _make(n_paths: int = 5, horizon: int = 5):
        return np.full((n_paths, horizon, 5), 1.05, dtype=np.float64)
    return _make


@pytest.fixture
def uniform_weights():
    return np.array([0.2, 0.2, 0.2, 0.2, 0.2])


def test_backwards_compat_no_tax_regime(constant_returns, uniform_weights):
    """tax_regime=None → identisches Verhalten wie vor Sprint 3."""
    returns = constant_returns(n_paths=3, horizon=5)
    wealth_no_param = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 5,
    )
    wealth_explicit_none = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 5,
        tax_regime=None,
    )
    np.testing.assert_array_equal(wealth_no_param, wealth_explicit_none)


def test_zero_tax_regime_identical_to_no_regime(constant_returns, uniform_weights):
    """Tax-Regime mit allen Werten 0 → identisch zu kein Regime."""
    returns = constant_returns(n_paths=3, horizon=3)
    zero_regime = GenericFlatRateRegime()  # alle defaults = 0

    wealth_no = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 3,
    )
    wealth_zero = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 3,
        tax_regime=zero_regime,
    )
    np.testing.assert_array_equal(wealth_no, wealth_zero)


def test_wealth_tax_reduces_end_wealth(constant_returns, uniform_weights):
    """100 bps (1%) Wealth-Tax p.a. ueber 5 Jahre → messbar weniger Wealth."""
    returns = constant_returns(n_paths=1, horizon=5)
    regime = GenericFlatRateRegime(wealth_tax_bps_pa=100.0)

    wealth_no = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 5,
    )
    wealth_taxed = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 5,
        tax_regime=regime,
    )
    # Expected: (1.05 * 0.99)^5 = 1.05^5 * 0.99^5 = 1.27628 * 0.95099 = 1.21370
    # vs no_tax: 1.05^5 = 1.27628
    expected_taxed_end = 1_000_000_00 * (1.05 * 0.99) ** 5
    expected_no_tax_end = 1_000_000_00 * 1.05 ** 5
    assert abs(wealth_no[0, -1] - expected_no_tax_end) < 10
    assert abs(wealth_taxed[0, -1] - expected_taxed_end) < 10


def test_wealth_tax_compounding_10_years(constant_returns, uniform_weights):
    """1% Wealth-Tax 10 Jahre: ~9.5% Reduktion vs no-tax."""
    returns = constant_returns(n_paths=1, horizon=10)
    regime = GenericFlatRateRegime(wealth_tax_bps_pa=100.0)

    wealth_no = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 10,
    )
    wealth_taxed = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 10,
        tax_regime=regime,
    )
    reduction = (wealth_no[0, -1] - wealth_taxed[0, -1]) / wealth_no[0, -1]
    assert 0.09 < reduction < 0.11, f"reduction={reduction:.4f}"


def test_dividend_drag_requires_yield_array(constant_returns, uniform_weights):
    """dividend_yield_bps_per_bucket muss richtige Shape haben."""
    returns = constant_returns(n_paths=2, horizon=3)
    regime = GenericFlatRateRegime(dividend_tax_bps=2500.0)
    with pytest.raises(ValueError, match="dividend_yield_bps_per_bucket"):
        simulate_wealth_paths(
            initial_wealth_rappen=1_000_000_00,
            weights=uniform_weights,
            return_paths=returns,
            cashflow_series_rappen=[0] * 3,
            tax_regime=regime,
            dividend_yield_bps_per_bucket=np.array([100, 200]),  # wrong shape
        )


def test_dividend_drag_active(constant_returns, uniform_weights):
    """Dividend-Drag: 5 Buckets je 200 bps Yield, 25% Tax, uniform-weights:
    weighted yield = 200 bps, drag = 200 * 0.25 = 50 bps p.a."""
    returns = constant_returns(n_paths=1, horizon=5)
    regime = GenericFlatRateRegime(dividend_tax_bps=2500.0)
    yields = np.array([200, 200, 200, 200, 200], dtype=np.float64)

    wealth_no_div = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 5,
    )
    wealth_with_div = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 5,
        tax_regime=regime,
        dividend_yield_bps_per_bucket=yields,
    )
    # weighted yield = 0.02, drag = 0.02 * 0.25 = 0.005 (50 bps)
    # Faktor pro Jahr: 1.05 * (1 - 0.005) = 1.04475
    expected_with_drag = 1_000_000_00 * (1.05 * 0.995) ** 5
    assert abs(wealth_with_div[0, -1] - expected_with_drag) < 100  # Float-Rauschen
    # No-tax bleibt natuerlich hoeher
    assert wealth_no_div[0, -1] > wealth_with_div[0, -1]


def test_zero_dividend_yield_no_drag(constant_returns, uniform_weights):
    """Dividend-Yield 0 → kein Drag, auch wenn Tax aktiv."""
    returns = constant_returns(n_paths=1, horizon=5)
    regime = GenericFlatRateRegime(dividend_tax_bps=2500.0)

    wealth_no_yield = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 5,
        tax_regime=regime,
        dividend_yield_bps_per_bucket=np.zeros(5),
    )
    wealth_no_regime = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 5,
    )
    np.testing.assert_allclose(wealth_no_yield, wealth_no_regime, rtol=1e-9)


def test_combined_wealth_and_dividend_tax(constant_returns, uniform_weights):
    """Beide Steuern aktiv: Drag dann Wealth-Tax — Effekt ist multiplikativ."""
    returns = constant_returns(n_paths=1, horizon=5)
    regime = GenericFlatRateRegime(
        wealth_tax_bps_pa=50.0,
        dividend_tax_bps=2500.0,
    )
    yields = np.array([200, 200, 200, 200, 200], dtype=np.float64)

    wealth = simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 5,
        tax_regime=regime,
        dividend_yield_bps_per_bucket=yields,
    )
    # Schritt 1: 1.05 (Wachstum)
    # Schritt 2: * (1 - 0.005) = 1.04475 (Dividend-Drag)
    # Schritt 3: * (1 - 0.005) = 1.039426 (Wealth-Tax)
    expected_factor = 1.05 * 0.995 * 0.995
    expected_end = 1_000_000_00 * expected_factor ** 5
    assert abs(wealth[0, -1] - expected_end) < 100


def test_wealth_tax_skipped_on_negative_wealth(constant_returns, uniform_weights):
    """Negative Wealth → Wealth-Tax wird NICHT angewendet."""
    returns = constant_returns(n_paths=1, horizon=3)
    regime = GenericFlatRateRegime(wealth_tax_bps_pa=200.0)  # 2%

    # Cashflow stark negativ → Wealth wird schnell negativ
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=100_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[-200_000_00] * 3,
        tax_regime=regime,
    )
    # Letzte Periode muss negativ sein
    assert wealth[0, -1] < 0
    # Verglichen mit no-tax: wenn negativ, Differenz minimal (1 positive year max)
    wealth_no_tax = simulate_wealth_paths(
        initial_wealth_rappen=100_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[-200_000_00] * 3,
    )
    # End-Wealth-Differenz sollte klein sein (Tax nur in ersten Jahren auf positivem Wealth)
    diff_rappen = abs(wealth_no_tax[0, -1] - wealth[0, -1])
    assert diff_rappen < 5_000_00  # < 5'000 Rappen Unterschied


def test_calendar_year_passed_to_regime(constant_returns, uniform_weights):
    """base_calendar_year+t wird an Regime-Context weitergegeben — verifizierbar
    via Custom-Regime das Year aufzeichnet."""
    from services.tax.base import TaxContext
    captured_years: list[int] = []

    class _SpyRegime(GenericFlatRateRegime):
        def annual_wealth_tax(self, ctx: TaxContext):
            captured_years.append(ctx.calendar_year)
            return super().annual_wealth_tax(ctx)

    returns = constant_returns(n_paths=1, horizon=3)
    regime = _SpyRegime(wealth_tax_bps_pa=50.0)
    simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 3,
        tax_regime=regime,
        base_calendar_year=2030,
    )
    assert captured_years == [2030, 2031, 2032]


def test_age_propagation(constant_returns, uniform_weights):
    """mandate_age_at_start + t wird in TaxContext.age weitergereicht."""
    from services.tax.base import TaxContext
    captured_ages: list[int | None] = []

    class _SpyRegime(GenericFlatRateRegime):
        def annual_wealth_tax(self, ctx: TaxContext):
            captured_ages.append(ctx.age)
            return super().annual_wealth_tax(ctx)

    returns = constant_returns(n_paths=1, horizon=3)
    regime = _SpyRegime(wealth_tax_bps_pa=50.0)
    simulate_wealth_paths(
        initial_wealth_rappen=1_000_000_00,
        weights=uniform_weights,
        return_paths=returns,
        cashflow_series_rappen=[0] * 3,
        tax_regime=regime,
        mandate_age_at_start=55,
    )
    assert captured_ages == [55, 56, 57]
