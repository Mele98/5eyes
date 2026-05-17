"""DETaxRegime-Light Tests."""
from __future__ import annotations

import pytest

from services.tax.base import TaxContext
from services.tax.regimes.de import DETaxRegime
from services.tax.registry import resolve_regime_class


@pytest.fixture
def ctx():
    return TaxContext(year_index=0, calendar_year=2026, wealth_rappen=1_000_000_00)


def test_registry_resolves_de():
    assert resolve_regime_class("DE") is DETaxRegime


def test_de_no_wealth_tax(ctx):
    """DE hat KEINE Vermoegenssteuer (seit 1997 ausgesetzt)."""
    regime = DETaxRegime()
    assert regime.wealth_tax_bps_pa == 0.0
    assert regime.supports_wealth_tax is False
    result = regime.annual_wealth_tax(ctx)
    assert result.amount_rappen == 0.0


def test_de_dividend_tax_26_38_pct(ctx):
    """KESt 25% + Soli 5.5% = 26.375%."""
    regime = DETaxRegime()
    result = regime.dividend_tax(ctx, 10_000_00)
    expected = 10_000_00 * 0.26375
    assert result.amount_rappen == pytest.approx(expected, abs=10.0)


def test_de_capital_gains_same_rate_as_dividends(ctx):
    """In DE: Abgeltungsteuer trifft Dividenden + Kursgewinne gleich."""
    regime = DETaxRegime()
    div_bps = regime.dividend_tax(ctx, 1_000_00).effective_bps
    gain_bps = regime.capital_gains_tax(ctx, 1_000_00, holding_years=5).effective_bps
    assert div_bps == gain_bps


def test_de_supports_capital_gains_tax(ctx):
    """Im Gegensatz zu CH besteuert DE Kursgewinne — wichtig fuer Asset-Allocation."""
    regime = DETaxRegime()
    assert regime.supports_capital_gains_tax is True


def test_de_local_currency_eur():
    assert DETaxRegime().local_currency == "EUR"


def test_de_with_overrides():
    """Berater kann Werte ueberschreiben (z.B. mit Kirchensteuer-Aufschlag)."""
    regime = DETaxRegime()
    with_church = regime.with_overrides({"dividend_tax_bps": 2750.0})
    assert with_church.dividend_tax_bps == 2750.0
    assert regime.dividend_tax_bps == 2637.5
