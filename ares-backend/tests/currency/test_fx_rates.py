"""FXRateSource Tests."""
from __future__ import annotations

import pytest

from services.currency.fx_rates import DEFAULT_FX_RATES, FXRateSource


def test_default_source_initializes():
    source = FXRateSource()
    assert source.rate_to_chf("CHF") == 1.0
    assert source.rate_to_chf("EUR") > 0


def test_chf_must_be_present_and_one():
    with pytest.raises(ValueError, match="CHF"):
        FXRateSource(rates_in_chf={"EUR": 0.95})  # no CHF
    with pytest.raises(ValueError, match="CHF"):
        FXRateSource(rates_in_chf={"CHF": 0.5, "EUR": 0.95})  # CHF != 1


def test_invalid_currency_code_raises():
    with pytest.raises(ValueError, match="Invalid currency"):
        FXRateSource(rates_in_chf={"CHF": 1.0, "XX": 0.5})  # 2 chars


def test_invalid_rate_raises():
    with pytest.raises(ValueError, match="Invalid rate"):
        FXRateSource(rates_in_chf={"CHF": 1.0, "EUR": -1.0})
    with pytest.raises(ValueError, match="Invalid rate"):
        FXRateSource(rates_in_chf={"CHF": 1.0, "EUR": 0})


def test_rate_to_chf_known_currency():
    source = FXRateSource()
    eur = source.rate_to_chf("EUR")
    assert 0.5 < eur < 1.5  # plausibel 2026


def test_rate_to_chf_lowercase_accepted():
    source = FXRateSource()
    assert source.rate_to_chf("eur") == source.rate_to_chf("EUR")


def test_rate_to_chf_unknown_currency_raises():
    source = FXRateSource()
    with pytest.raises(ValueError, match="Unknown"):
        source.rate_to_chf("XYZ")


def test_cross_rate_eur_usd_via_chf():
    """EUR/USD = EUR-rate / USD-rate (beide in CHF)."""
    source = FXRateSource()
    eur_in_chf = source.rate_to_chf("EUR")
    usd_in_chf = source.rate_to_chf("USD")
    expected = eur_in_chf / usd_in_chf
    actual = source.cross_rate("EUR", "USD")
    assert abs(actual - expected) < 1e-9


def test_cross_rate_identity():
    source = FXRateSource()
    assert source.cross_rate("CHF", "CHF") == 1.0
    assert source.cross_rate("EUR", "EUR") == 1.0


def test_cross_rate_inverse():
    """cross_rate(A,B) * cross_rate(B,A) = 1."""
    source = FXRateSource()
    a_to_b = source.cross_rate("EUR", "USD")
    b_to_a = source.cross_rate("USD", "EUR")
    assert abs(a_to_b * b_to_a - 1.0) < 1e-9


def test_supported_currencies_contains_majors():
    source = FXRateSource()
    supported = source.supported_currencies()
    for major in ("CHF", "EUR", "USD", "GBP", "JPY"):
        assert major in supported


def test_supported_currencies_sorted():
    source = FXRateSource()
    supported = source.supported_currencies()
    assert list(supported) == sorted(supported)


def test_default_rates_dict_has_chf_one():
    assert DEFAULT_FX_RATES["CHF"] == 1.0


def test_default_rates_dict_has_major_currencies():
    for major in ("CHF", "EUR", "USD", "GBP", "JPY", "CAD", "AUD"):
        assert major in DEFAULT_FX_RATES
