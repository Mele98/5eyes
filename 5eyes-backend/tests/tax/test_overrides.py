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


def test_parse_malformed_returns_empty():
    """Malformed JSON darf nie crashen — gibt {} zurueck."""
    assert parse_overrides_json("{not json") == {}
    assert parse_overrides_json("null") == {}
    assert parse_overrides_json("[1,2,3]") == {}  # nicht-dict


def test_parse_filters_non_string_keys_and_non_numeric_values():
    result = parse_overrides_json('{"good": 50, "bad": "string", "also_good": 25}')
    assert result == {"good": 50.0, "also_good": 25.0}


def test_apply_overrides_none_returns_same_regime():
    r = GenericFlatRateRegime(wealth_tax_bps_pa=50.0)
    r2 = apply_overrides(r, None)
    assert r is r2


def test_apply_overrides_applies_to_regime():
    r = GenericFlatRateRegime(wealth_tax_bps_pa=50.0)
    r2 = apply_overrides(r, '{"wealth_tax_bps_pa": 100}')
    assert r2.wealth_tax_bps_pa == 100.0
    assert r.wealth_tax_bps_pa == 50.0  # Original unveraendert


def test_apply_overrides_malformed_returns_original():
    r = GenericFlatRateRegime(wealth_tax_bps_pa=50.0)
    r2 = apply_overrides(r, "{garbage")
    assert r is r2


def test_validate_all_delegates_to_regime():
    r = GenericFlatRateRegime()
    warnings = validate_all(r, {"wealth_tax_bps_pa": -50})
    assert len(warnings) >= 1
