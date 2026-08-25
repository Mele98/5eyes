"""apply_overrides + parse_overrides_json Tests."""
from __future__ import annotations

import pytest

from services.tax.overrides import (
    apply_overrides,
    parse_overrides_json,
    validate_all,
)
from services.tax.regimes.generic import GenericFlatRateRegime


def test_parse_none_returns_empty():
    assert parse_overrides_json(None) == {}


def test_parse_empty_string_returns_empty():
    assert parse_overrides_json("") == {}


def test_parse_valid_json():
    result = parse_overrides_json('{"wealth_tax_bps_pa": 75}')
    assert result == {"wealth_tax_bps_pa": 75.0}


@pytest.mark.parametrize("payload", ["{not json", "null", "[1,2,3]"])
def test_parse_configured_malformed_payload_fails_closed(payload):
    with pytest.raises(ValueError, match="tax overrides"):
        parse_overrides_json(payload)


@pytest.mark.parametrize(
    "payload",
    [
        '{"wealth_tax_bps_pa": "50"}',
        '{"wealth_tax_bps_pa": true}',
        '{"wealth_tax_bps_typo": 50}',
        '{"wealth_tax_bps_pa": NaN}',
    ],
)
def test_parse_rejects_non_numeric_boolean_unknown_and_non_finite_values(payload):
    with pytest.raises(ValueError, match="tax overrides"):
        parse_overrides_json(payload)


_SUPPORTED_RATE_KEYS = (
    "wealth_tax_bps_pa",
    "dividend_tax_bps",
    "interest_tax_bps",
    "capital_gains_tax_bps",
    "pension_lumpsum_tax_bps",
    "inheritance_tax_bps_default",
)


@pytest.mark.parametrize("key", _SUPPORTED_RATE_KEYS)
@pytest.mark.parametrize("value", [-0.0001, -1, 10_000.0001, 10_001])
def test_parse_rejects_rates_outside_zero_to_one_hundred_percent(key, value):
    with pytest.raises(ValueError, match="0.*10000"):
        parse_overrides_json(f'{{"{key}": {value}}}')


@pytest.mark.parametrize("key", _SUPPORTED_RATE_KEYS)
@pytest.mark.parametrize("value", [0, 10_000])
def test_parse_accepts_inclusive_zero_and_one_hundred_percent_boundaries(key, value):
    assert parse_overrides_json(f'{{"{key}": {value}}}') == {key: float(value)}


def test_apply_overrides_none_returns_same_regime():
    r = GenericFlatRateRegime(wealth_tax_bps_pa=50.0)
    r2 = apply_overrides(r, None)
    assert r is r2


def test_apply_overrides_applies_to_regime():
    r = GenericFlatRateRegime(wealth_tax_bps_pa=50.0)
    r2 = apply_overrides(r, '{"wealth_tax_bps_pa": 100}')
    assert r2.wealth_tax_bps_pa == 100.0
    assert r.wealth_tax_bps_pa == 50.0  # Original unveraendert


def test_apply_overrides_malformed_fails_closed():
    r = GenericFlatRateRegime(wealth_tax_bps_pa=50.0)
    with pytest.raises(ValueError, match="tax overrides"):
        apply_overrides(r, "{garbage")


def test_apply_overrides_rejects_negative_rate_instead_of_creating_tax_income():
    r = GenericFlatRateRegime(dividend_tax_bps=2500.0)
    with pytest.raises(ValueError, match="0.*10000"):
        apply_overrides(r, '{"dividend_tax_bps": -2500}')


def test_validate_all_delegates_to_regime():
    r = GenericFlatRateRegime()
    warnings = validate_all(r, {"wealth_tax_bps_pa": 6000})
    assert len(warnings) >= 1


def test_validate_all_rejects_invalid_rate_before_regime_warning_layer():
    r = GenericFlatRateRegime()
    with pytest.raises(ValueError, match="0.*10000"):
        validate_all(r, {"wealth_tax_bps_pa": -50})
