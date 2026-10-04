"""CMA-INFLATION-PATH-DOMAIN-001 (round 40 red test).

``inflation_path_json`` is the one optional CMA JSON payload with NO shared
domain parser. ``correlation_matrix_json`` and
``sub_asset_class_assumptions_json`` are both validated strictly in
``CapitalMarketAssumptionCreate._validate_cma`` via
``parse_correlation_matrix_json`` / ``parse_sub_asset_class_assumptions_json``
(see tests/test_cma_strict_runtime_contract.py) -- but ``inflation_path_json``
is accepted as a free string at the schema layer, and
``services/portfolio_engine_cma.py::_inflation_path_series`` silently
substitutes/coerces/backfills instead of raising on malformed or
out-of-domain input.

Five independent fail-open cases, confirmed by reading the real code
(``_inflation_path_series``, ~line 678 of ``services/portfolio_engine_cma.py``):

1. Malformed JSON string -> ``json.JSONDecodeError`` is caught and
   ``raw_path`` silently falls back to ``{}``; with an empty/absent map the
   function's own fallback constant (70 bps) is returned for every
   requested year instead of raising.
2. A JSON array at the top level -> ``raw_path`` is a non-empty list, so
   ``(raw_path or {}).items()`` is called directly on a ``list`` and raises
   an unhandled ``AttributeError`` deep in the engine instead of a clean
   422 at the API boundary.
3. A boolean value inside the per-year map -> ``int(True) == 1`` is silently
   accepted as "1 bps" inflation for that year (mirrors the exact bug the
   ``_reject_boolean_market_inputs``/``_reject_boolean_advanced_model_parameters``
   validators were added to close for the *other* CMA fields -- but no such
   guard exists for ``inflation_path_json``).
4. An out-of-domain value far below -100% (e.g. -200%) -> no range check at
   all exists for this field (unlike the ``*_return_bps``/``*_vol_bps``
   fields, which are bounded in ``_validate_cma``).
5. A "future-only" path with no coverage for the requested start year ->
   ``fallback = normalized[max(normalized)] if normalized else 70`` seeds
   the running fallback with the value at the **latest/max** year in the
   whole map, and that value is backfilled backward into every year before
   the first real coverage -- not the first/earliest year's value.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from schemas.allocation import CapitalMarketAssumptionCreate
from services.portfolio_engine_cma import _inflation_path_series


def _cma(inflation_path_json: str) -> SimpleNamespace:
    return SimpleNamespace(inflation_path_json=inflation_path_json)


@pytest.mark.xfail(
    strict=True,
    reason="CMA-INFLATION-PATH-DOMAIN-001 — round 40 red test, see audit "
    "2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md "
    "(not committed in this repo)",
)
def test_malformed_json_should_be_rejected_not_silently_defaulted():
    # Schema layer: today this is accepted with no validator for the field.
    with pytest.raises(ValidationError):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01",
            inflation_path_json="not-json",
        )
    # Runtime layer: today this silently returns the constant 70-bps
    # fallback for every year instead of raising/signalling bad input.
    series = _inflation_path_series(_cma("not-json"), years=3, start_year=2026)
    assert series != [70, 70, 70], (
        "malformed JSON must not silently resolve to the hard-coded "
        "70 bps fallback series"
    )


@pytest.mark.xfail(
    strict=True,
    reason="CMA-INFLATION-PATH-DOMAIN-001 — round 40 red test, see audit "
    "2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md "
    "(not committed in this repo)",
)
def test_top_level_json_array_should_be_rejected_not_crash_the_engine():
    # Schema layer: a top-level JSON array is accepted with no validator.
    with pytest.raises(ValidationError):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01",
            inflation_path_json=json.dumps([100, 200]),
        )
    # Runtime layer: today this raises an unhandled AttributeError
    # ('list' object has no attribute 'items') instead of a clean,
    # documented validation failure.
    _inflation_path_series(_cma(json.dumps([100, 200])), years=2, start_year=2026)


@pytest.mark.xfail(
    strict=True,
    reason="CMA-INFLATION-PATH-DOMAIN-001 — round 40 red test, see audit "
    "2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md "
    "(not committed in this repo)",
)
def test_boolean_year_value_should_be_rejected_not_coerced_to_one_bps():
    # Schema layer: no boolean guard exists for inflation_path_json, unlike
    # the sibling _reject_boolean_* validators for other CMA fields.
    with pytest.raises(ValidationError):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01",
            inflation_path_json=json.dumps({"2026": True}),
        )
    # Runtime layer: today int(True) == 1 is silently accepted as 1 bps.
    series = _inflation_path_series(
        _cma(json.dumps({"2026": True})), years=1, start_year=2026
    )
    assert series != [1], (
        "a boolean year value must not be silently coerced into 1 bps "
        "of inflation"
    )


@pytest.mark.xfail(
    strict=True,
    reason="CMA-INFLATION-PATH-DOMAIN-001 — round 40 red test, see audit "
    "2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md "
    "(not committed in this repo)",
)
def test_out_of_domain_negative_inflation_should_be_rejected():
    # Schema layer: -20000 bps (-200%) passes today -- no range check exists
    # for inflation_path_json (unlike *_return_bps/*_vol_bps fields).
    with pytest.raises(ValidationError):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01",
            inflation_path_json=json.dumps({"2026": -20000}),
        )
    # Runtime layer: today -20000 is accepted and returned verbatim.
    series = _inflation_path_series(
        _cma(json.dumps({"2026": -20000})), years=1, start_year=2026
    )
    assert series != [-20000], (
        "an inflation value below -100% must not reach the engine unchanged"
    )


@pytest.mark.xfail(
    strict=True,
    reason="CMA-INFLATION-PATH-DOMAIN-001 — round 40 red test, see audit "
    "2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md "
    "(not committed in this repo)",
)
def test_future_only_path_should_not_backfill_with_the_latest_year_value():
    # Schema layer: a path with zero coverage for the requested start year
    # is accepted with no validator checking for start-year coverage.
    payload = json.dumps({"2030": 100, "2031": 200})
    with pytest.raises(ValidationError):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01",
            inflation_path_json=payload,
        )
    # Runtime layer: today years 2026-2029 (before any real coverage)
    # are silently backfilled with normalized[max(normalized)] == 200
    # (the value for 2031, the LATEST year), not 100 (the FIRST/earliest
    # available year, 2030) and not any explicit "no data" signal.
    series = _inflation_path_series(_cma(payload), years=6, start_year=2026)
    assert series == [100, 100, 100, 100, 100, 200], (
        "years preceding the first real data point must not be silently "
        "backfilled with the latest available year's value"
    )
