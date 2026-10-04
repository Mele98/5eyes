"""CMA-EFFECTIVE-DATE-001 -- backward-fill-from-future inflation leak.

Repro for the round-40 audit finding (audit doc
2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md, not
committed in this worktree).

`services/portfolio_engine_cma.py::_inflation_path_series` builds its
`fallback` seed from ``normalized[max(normalized)]`` -- the value tied to the
LARGEST year key present in the parsed ``inflation_path_json`` dict -- before
it ever walks the requested year range. When the requested years are all
strictly *before* every real data point (i.e. there is zero coverage for the
requested range), this seed is nevertheless carried forward and emitted for
every requested year, even though it is the MOST FUTURE value in the stored
path, not the earliest/first one.

Concretely: an inflation path of ``{"2099": 100, "2100": 900}`` (values are
already basis points -- see the direct ``int(raw_value)`` assignment into
``normalized[year]`` with no further scaling, and the hard-coded ultimate
default of ``70`` bps if the dict is empty) requested for years 2026-2029 --
73 years before the first real entry -- incorrectly backfills using the
*2100* value (900 bps = 9%), not the 2099 value (100 bps = 1%), for every one
of the four requested years. Desired behavior: since none of 2026-2029 has
any real coverage at all, the function must not silently backfill a
non-zero, arbitrary *future* value -- at minimum it must not use the
max-year's value, and ideally should flag "no coverage" or fall back to a
documented zero/baseline.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine_cma import _inflation_path_series  # noqa: E402


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CMA-EFFECTIVE-DATE-001 -- round 40 red test, see audit "
        "2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md "
        "(not committed in this repo)"
    ),
)
def test_inflation_path_series_does_not_backfill_from_future_max_year():
    """Years 2026-2029 have NO coverage; the only stored points are 2099/2100.

    The current implementation seeds its carry-forward `fallback` from
    ``normalized[max(normalized)]`` (the 2100 entry, 900 bps) and emits that
    for every one of the four requested years -- before it ever reaches a
    real data point. That is backward-filling a 73-years-in-the-future value
    into the present, which is the bug under test.
    """
    cma = SimpleNamespace(
        inflation_path_json=json.dumps({"2099": 100, "2100": 900}),
    )

    series = _inflation_path_series(cma, years=4, start_year=2026)

    # Document the actual (buggy) behavior observed when running this test
    # red, so the assertion failure is self-explanatory without re-deriving
    # it: the engine currently returns [900, 900, 900, 900] -- the *2100*
    # (max-year, future) value -- for 2026, 2027, 2028 and 2029 alike.
    actual_buggy_values = [900, 900, 900, 900]
    assert series == actual_buggy_values, (
        "Expected behavior changed -- re-verify the current buggy output "
        f"before updating this fixture. Observed: {series}"
    )

    # Desired behavior: none of 2026-2029 has any real coverage (the first
    # real entry, 2099, is 73 years in the future), so the function must not
    # silently backfill the stored MAX-YEAR value (900 bps, from 2100) for
    # years that long predate any real data. At minimum, it must not equal
    # the max-year's value for every requested year.
    assert series != [900, 900, 900, 900], (
        "CMA-EFFECTIVE-DATE-001: _inflation_path_series backfilled the "
        "MAXIMUM-year (most future, 2100=900bps) inflation value into "
        "years 2026-2029, which have zero real coverage and are 73 years "
        "before the first stored data point (2099). Expected: no coverage "
        "-> do not emit a non-zero, arbitrary future value (raise, flag, "
        "or default to a documented zero/baseline instead of "
        f"normalized[max(normalized)]). Actual series: {series}"
    )
