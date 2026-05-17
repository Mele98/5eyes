"""Currency-Converter Tests."""
from __future__ import annotations

import pytest

from services.currency.converter import (
    SUPPORTED_CURRENCIES,
    convert_rappen,
    format_currency,
)
from services.currency.fx_rates import FXRateSource


def test_identity_conversion():
    """Same currency → exact same amount."""
    assert convert_rappen(12345, "CHF", "CHF") == 12345.0
    assert convert_rappen(12345, "EUR", "EUR") == 12345.0
    assert convert_rappen(0, "CHF", "EUR") == 0.0


def test_zero_amount_returns_zero():
    """0 input → 0 output regardless of currencies."""
    assert convert_rappen(0, "USD", "EUR") == 0.0
    assert convert_rappen(0, "JPY", "GBP") == 0.0


def test_eur_to_chf_uses_rate():
    """100 EUR → ~95 CHF (mit Default-Rate 0.95)."""
    result = convert_rappen(10000, "EUR", "CHF")  # 100 EUR
    assert 9000 < result < 10500  # plausibel


def test_chf_to_eur_inverse():
    """95 CHF → ~100 EUR (inverse rate)."""
    result = convert_rappen(9500, "CHF", "EUR")
    assert 9500 < result < 10500


def test_roundtrip_preserves_amount():
    """convert(amount, A, B) → convert(result, B, A) ≈ amount."""
    original = 100000.0
    intermediate = convert_rappen(original, "EUR", "USD")
    back = convert_rappen(intermediate, "USD", "EUR")
    assert abs(back - original) < 0.01


def test_cross_via_chf():
    """USD → EUR rechnet ueber CHF."""
    source = FXRateSource()
    usd_to_eur = convert_rappen(10000, "USD", "EUR", source=source)
    # USD * USD-CHF / EUR-CHF
    expected = 10000 * source.rate_to_chf("USD") / source.rate_to_chf("EUR")
    assert abs(usd_to_eur - expected) < 0.01


def test_lowercase_currency_accepted():
    assert convert_rappen(100, "chf", "chf") == 100.0


def test_unknown_currency_raises():
    with pytest.raises(ValueError):
        convert_rappen(100, "XYZ", "CHF")


def test_custom_source_used():
    """Wenn source-Parameter gesetzt, wird der genutzt."""
    custom = FXRateSource(rates_in_chf={"CHF": 1.0, "EUR": 0.50})  # extrem
    result = convert_rappen(100, "EUR", "CHF", source=custom)
    assert result == 50.0


def test_format_currency_basic_chf():
    """123'456.78 CHF."""
    assert format_currency(12345678, "CHF") == "CHF 123'456.78"


def test_format_currency_zero():
    assert format_currency(0, "EUR") == "EUR 0.00"


def test_format_currency_under_one_unit():
    assert format_currency(99, "USD") == "USD 0.99"


def test_format_currency_negative():
    assert format_currency(-12345, "CHF") == "-CHF 123.45"


def test_format_currency_decimals_zero():
    """Berater kann decimals=0 setzen fuer ganze Einheiten."""
    assert format_currency(12345678, "CHF", decimals=0) == "CHF 123'457"


def test_format_currency_uppercase_code():
    """Currency-Code wird immer Upper-Case."""
    assert format_currency(100, "eur") == "EUR 1.00"


def test_format_currency_custom_separator():
    assert format_currency(12345678, "USD", thousand_sep=",") == "USD 123,456.78"


def test_supported_currencies_constant():
    """Modul exportiert ein Tupel der unterstuetzten Currencies."""
    assert isinstance(SUPPORTED_CURRENCIES, tuple)
    assert "CHF" in SUPPORTED_CURRENCIES
    assert "EUR" in SUPPORTED_CURRENCIES
