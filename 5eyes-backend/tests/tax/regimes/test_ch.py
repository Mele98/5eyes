"""CHTaxRegime-Light Tests."""
from __future__ import annotations

import pytest

from services.tax.base import TaxContext
from services.tax.regimes.ch import CANTON_CODES, CHTaxRegime
from services.tax.registry import resolve_regime_class


@pytest.fixture
def ctx():
    return TaxContext(year_index=0, calendar_year=2026, wealth_rappen=1_000_000_00)


def test_registry_resolves_ch_to_ch_regime():
    """Lookup 'CH' → CHTaxRegime."""
    assert resolve_regime_class("CH") is CHTaxRegime


def test_registry_resolves_ch_canton_to_ch_regime():
    """Lookup 'CH-ZH', 'CH-GE' → CHTaxRegime via Glob 'CH-*'."""
    assert resolve_regime_class("CH-ZH") is CHTaxRegime
    assert resolve_regime_class("CH-GE") is CHTaxRegime


def test_default_ch_has_zero_capital_gains_tax(ctx):
    """CH-Privatvermoegen: Kapitalgewinne STEUERFREI — kritisch fuer Allocation-Bias."""
    regime = CHTaxRegime()
    result = regime.capital_gains_tax(ctx, gains_rappen=100_000_00, holding_years=5)
    assert result.amount_rappen == 0.0
    assert regime.supports_capital_gains_tax is False


def test_default_ch_has_wealth_tax(ctx):
    """Default ~40 bps = 0.4% p.a."""
    regime = CHTaxRegime()
    assert regime.wealth_tax_bps_pa == 40.0
    result = regime.annual_wealth_tax(ctx)
    assert result.amount_rappen == 1_000_000_00 * 0.004


def test_default_ch_dividend_tax_around_28pct(ctx):
    """Default ~28% marginale Einkommensteuer auf Dividenden."""
    regime = CHTaxRegime()
    result = regime.dividend_tax(ctx, 10_000_00)
    assert result.amount_rappen == pytest.approx(10_000_00 * 0.28, abs=1.0)


def test_for_canton_creates_instance_with_canton_specific_wealth_tax():
    """Factory: for_canton('GE') → höherer Wealth-Tax als 'SZ'."""
    ge = CHTaxRegime.for_canton("GE")
    sz = CHTaxRegime.for_canton("SZ")
    assert ge.wealth_tax_bps_pa > sz.wealth_tax_bps_pa
    assert ge.region_code == "GE"
    assert sz.region_code == "SZ"
    assert ge.id == "CH-GE"
    assert sz.id == "CH-SZ"


def test_for_canton_invalid_raises():
    with pytest.raises(ValueError, match="Unknown canton"):
        CHTaxRegime.for_canton("XY")


def test_for_canton_accepts_lowercase():
    """Eingabe-Tolerant fuer 'zh' und 'ZH'."""
    a = CHTaxRegime.for_canton("zh")
    b = CHTaxRegime.for_canton("ZH")
    assert a.region_code == b.region_code == "ZH"


def test_for_canton_explicit_override_used():
    """Wenn wealth_tax_bps_pa explizit gesetzt, ueberschreibt Kanton-Default."""
    regime = CHTaxRegime.for_canton("ZH", wealth_tax_bps_pa=99.0)
    assert regime.wealth_tax_bps_pa == 99.0


def test_canton_codes_all_26():
    """Alle 26 CH-Kantone sind exportiert."""
    assert len(CANTON_CODES) == 26
    expected = {
        "ZH", "BE", "LU", "UR", "SZ", "OW", "NW", "GL", "ZG", "FR",
        "SO", "BS", "BL", "SH", "AR", "AI", "SG", "GR", "AG", "TG",
        "TI", "VD", "VS", "NE", "GE", "JU",
    }
    assert set(CANTON_CODES) == expected


def test_canton_factory_works_for_all_26():
    """Jeder Kanton produziert gueltige Instanz ohne Fehler."""
    for code in CANTON_CODES:
        regime = CHTaxRegime.for_canton(code)
        assert regime.country_code == "CH"
        assert regime.region_code == code
        assert regime.wealth_tax_bps_pa > 0


def test_with_overrides_works_for_ch_regime():
    """Overrides funktionieren analog zu Generic."""
    regime = CHTaxRegime.for_canton("ZH")
    overridden = regime.with_overrides({"wealth_tax_bps_pa": 25.0})
    assert overridden.wealth_tax_bps_pa == 25.0
    assert regime.wealth_tax_bps_pa == 35.0  # ZH-Default unveraendert


def test_ch_local_currency_chf():
    assert CHTaxRegime().local_currency == "CHF"


def test_ch_tariff_version_includes_canton():
    """Tariff-Version unterscheidet Kantone (fuer Audit-Reproduzierbarkeit)."""
    zh = CHTaxRegime.for_canton("ZH")
    ge = CHTaxRegime.for_canton("GE")
    assert zh.tariff_version != ge.tariff_version
    assert "ZH" in zh.tariff_version
    assert "GE" in ge.tariff_version
