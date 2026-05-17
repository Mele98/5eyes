"""GenericFlatRateRegime Tests — Flat-Rate-Logik."""
from __future__ import annotations

import pytest

from services.tax.base import TaxContext
from services.tax.regimes.generic import GenericFlatRateRegime


@pytest.fixture
def ctx():
    return TaxContext(
        year_index=0,
        calendar_year=2026,
        wealth_rappen=1_000_000_00,  # 1 Mio Rappen
    )


def test_default_regime_has_zero_taxes(ctx):
    """Default-Instanz: alle Steuern 0 (sicherer Default)."""
    r = GenericFlatRateRegime()
    assert r.annual_wealth_tax(ctx).amount_rappen == 0.0
    assert r.dividend_tax(ctx, 10_000_00).amount_rappen == 0.0
    assert r.interest_tax(ctx, 5_000_00).amount_rappen == 0.0
    assert r.capital_gains_tax(ctx, 50_000_00, 5).amount_rappen == 0.0
    assert r.pension_lumpsum_tax(ctx, 100_000_00).amount_rappen == 0.0


def test_wealth_tax_exact_amount(ctx):
    """50 bps Wealth-Tax auf 1 Mio Rappen = 5'000 Rappen (50 CHF)."""
    r = GenericFlatRateRegime(wealth_tax_bps_pa=50.0)
    result = r.annual_wealth_tax(ctx)
    assert result.amount_rappen == 1_000_000_00 * 0.005
    assert result.effective_bps == 50.0
    assert result.regime_id == "GENERIC"


def test_wealth_tax_zero_on_negative_wealth():
    """Keine Wealth-Tax wenn Wealth negativ (Schulden-Phase)."""
    ctx_neg = TaxContext(year_index=0, calendar_year=2026, wealth_rappen=-100_000_00)
    r = GenericFlatRateRegime(wealth_tax_bps_pa=100.0)
    result = r.annual_wealth_tax(ctx_neg)
    assert result.amount_rappen == 0.0


def test_dividend_tax_exact_amount(ctx):
    """2500 bps (25%) auf 10'000 Rappen Dividenden = 2500 Rappen."""
    r = GenericFlatRateRegime(dividend_tax_bps=2500.0)
    result = r.dividend_tax(ctx, 10_000_00)
    assert result.amount_rappen == 10_000_00 * 0.25
    assert result.effective_bps == 2500.0


def test_interest_tax_falls_back_to_dividend(ctx):
    """Wenn interest_tax_bps=None → nutzt dividend_tax_bps."""
    r = GenericFlatRateRegime(dividend_tax_bps=2500.0, interest_tax_bps=None)
    div = r.dividend_tax(ctx, 1000_00).amount_rappen
    inter = r.interest_tax(ctx, 1000_00).amount_rappen
    assert div == inter


def test_interest_tax_separate_when_set(ctx):
    """Wenn interest_tax_bps explizit gesetzt, nutzt diesen statt dividend."""
    r = GenericFlatRateRegime(dividend_tax_bps=2500.0, interest_tax_bps=3000.0)
    inter = r.interest_tax(ctx, 1000_00)
    assert inter.amount_rappen == 1000_00 * 0.30
    assert inter.effective_bps == 3000.0


def test_capital_gains_tax_exact_amount(ctx):
    """2000 bps (20%) auf 50'000 Gains = 10'000."""
    r = GenericFlatRateRegime(capital_gains_tax_bps=2000.0)
    result = r.capital_gains_tax(ctx, 50_000_00, holding_years=3)
    assert result.amount_rappen == 50_000_00 * 0.20


def test_pension_lumpsum_tax_exact_amount(ctx):
    """500 bps (5%) auf 200k Lumpsum = 10'000."""
    r = GenericFlatRateRegime(pension_lumpsum_tax_bps=500.0)
    result = r.pension_lumpsum_tax(ctx, 200_000_00)
    assert result.amount_rappen == 200_000_00 * 0.05


def test_capability_flags_derived_from_values():
    """supports_*-Flags werden aus den Werten abgeleitet."""
    r_zero = GenericFlatRateRegime()
    assert r_zero.supports_wealth_tax is False
    assert r_zero.supports_capital_gains_tax is False

    r_active = GenericFlatRateRegime(
        wealth_tax_bps_pa=50.0,
        capital_gains_tax_bps=2000.0,
    )
    assert r_active.supports_wealth_tax is True
    assert r_active.supports_capital_gains_tax is True


def test_with_overrides_returns_new_instance(ctx):
    """with_overrides ist Immutable — Original unveraendert."""
    original = GenericFlatRateRegime(wealth_tax_bps_pa=50.0)
    overridden = original.with_overrides({"wealth_tax_bps_pa": 100.0})

    assert original.wealth_tax_bps_pa == 50.0  # unveraendert
    assert overridden.wealth_tax_bps_pa == 100.0
    assert original is not overridden


def test_with_overrides_records_in_result(ctx):
    """Wenn Override aktiv, TaxResult.used_overrides ist gesetzt."""
    r = GenericFlatRateRegime(wealth_tax_bps_pa=50.0)
    r2 = r.with_overrides({"wealth_tax_bps_pa": 100.0})
    result = r2.annual_wealth_tax(ctx)
    assert result.used_overrides == {"wealth_tax_bps_pa": 100.0}


def test_with_overrides_ignores_unknown_keys():
    """Unbekannte Keys werden ignoriert (Berater-Tippfehler-tolerant)."""
    r = GenericFlatRateRegime(wealth_tax_bps_pa=50.0)
    r2 = r.with_overrides({"unknown_key_xyz": 999.0})
    assert r2.wealth_tax_bps_pa == 50.0
    assert r is r2  # gleiche Instanz, weil nichts angewendet


def test_with_overrides_empty_returns_same_instance():
    """Leeres Override-Dict → keine neue Instanz (Performance)."""
    r = GenericFlatRateRegime()
    r2 = r.with_overrides({})
    assert r is r2


def test_validate_negative_warning():
    """Negative Werte → Warnung."""
    r = GenericFlatRateRegime()
    warnings = r.validate_parameters({"wealth_tax_bps_pa": -50.0})
    assert len(warnings) >= 1
    assert "negative" in warnings[0].lower()


def test_validate_extremely_high_warning():
    """50%+ Werte → Warnung."""
    r = GenericFlatRateRegime()
    warnings = r.validate_parameters({"wealth_tax_bps_pa": 6000.0})  # 60%
    assert len(warnings) >= 1
    assert any("high" in w.lower() for w in warnings)


def test_validate_normal_values_no_warning():
    """Normale Werte → keine Warnung."""
    r = GenericFlatRateRegime()
    warnings = r.validate_parameters({
        "wealth_tax_bps_pa": 50.0,
        "dividend_tax_bps": 2500.0,
        "capital_gains_tax_bps": 2000.0,
    })
    assert warnings == ()


def test_validate_non_numeric_warning():
    """Non-numerische Werte → Warnung + ignored."""
    r = GenericFlatRateRegime()
    warnings = r.validate_parameters({"wealth_tax_bps_pa": "fifty"})  # type: ignore[dict-item]
    assert len(warnings) >= 1
    assert "non-numeric" in warnings[0].lower()


def test_tax_result_includes_tariff_version(ctx):
    """Jeder TaxResult enthaelt tariff_version fuer Audit-Reproduzierbarkeit."""
    r = GenericFlatRateRegime(wealth_tax_bps_pa=50.0, tariff_version="GENERIC-v1")
    result = r.annual_wealth_tax(ctx)
    assert result.tariff_version == "GENERIC-v1"
