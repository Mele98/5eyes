"""Round 53 red test for audit finding NS-CURVE-QUOTE-NORMALIZATION-001
(docs/audits/2026-10-04-bond-curve-quotation-sleeve-and-return-semantics-integrity-audit.md).

Finding: services/jurisdiction/data_pipeline.py registers the US yield curve
from FRED "Daily Treasury Par Yield Curve Rates" (DGS3MO..DGS30 -- officially
documented as semi-annual Bond-Equivalent-Yield par yields) and the DE/EU
curve from the ECB SDW "YC" dataflow, data-type "SV_C_YM" (spot rate,
**continuous compounding**, per data_pipeline.py's own registry comment at
_YIELD_CURVE_REGISTRY["DE"]). Both are reduced by
fetch_yield_curve_for_jurisdiction() to plain (maturity_years, yield_bps)
tuples -- no curve_type/compounding/day_count field anywhere -- and both are
then fed through the IDENTICAL services/rates/nelson_siegel.py::
fit_nelson_siegel(maturities_years, yields_bps, *, lambda_init, lambda_fixed)
call, which has no parameter of any kind distinguishing BEY-par quotes from
continuously-compounded zero quotes.

A 5.00% semi-annual BEY par yield and a 5.00% continuously-compounded zero
rate are NOT the same effective annual rate:
    BEY:        (1 + 0.05/2)**2 - 1        = 5.0625 %
    Continuous: exp(0.05) - 1              = 5.1271 %
(a ~6.46 bps gap from compounding convention alone -- before even considering
that par-yield -> zero-rate conversion requires a bootstrap, not just a
compounding-convention conversion).

This test seeds the real fetch_yield_curve_for_jurisdiction() path (via the
established monkeypatch-the-provider-factory pattern from
tests/test_cma_data_pipeline.py -- no live network access) with IDENTICAL
raw numeric quotes (5.00% flat) for both a US-like and a DE-like curve, and
calls the REAL fit_nelson_siegel() on both. A correct implementation would
have to convert one convention before fitting, so the two resulting curves'
short rates would differ. The real pipeline does not do this: it treats both
inputs as the same kind of number, so the two curves come out numerically
IDENTICAL.

Both assertions below currently FAIL for exactly this reason -- xfail(strict).
"""
from __future__ import annotations

import inspect
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from main import app  # noqa: F401  (establishes app context like sibling tests)
from services.market_data import MacroPoint
from services.rates.nelson_siegel import fit_nelson_siegel
import services.jurisdiction.data_pipeline as dp


class _FakeProvider:
    """Same no-network fake provider pattern as
    tests/test_cma_data_pipeline.py::_FakeProvider -- returns pre-seeded
    MacroPoint rows instead of making a live FRED/ECB call."""

    def __init__(self, points_by_series):
        self._points_by_series = points_by_series

    def get_series(self, series_code, start, end):
        return self._points_by_series.get(series_code, [])


def _flat_provider(series_codes, value_pct):
    """Builds a fake provider returning the SAME raw percentage quote
    (e.g. 5.00) for every maturity in series_codes -- used so the only
    difference between the US and DE curve below is the documented
    quotation convention (BEY par vs continuously-compounded zero), not the
    raw numbers."""
    pt = MacroPoint(date=date(2026, 7, 1), value=Decimal(str(value_pct)), series_code="X")
    return _FakeProvider({code: [pt] for code in series_codes})


def test_yield_curve_points_carry_no_quote_basis_metadata(monkeypatch):
    """Both jurisdictions reduce to bare (maturity_years, yield_bps) tuples.
    If normalization existed, a curve-type/compounding/day-count tag would
    have to survive onto these points so fit_nelson_siegel() could act on
    it. It does not: the tuple is always exactly 2 fields wide."""
    us_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["US"][1]]
    de_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["DE"][1]]
    monkeypatch.setattr(dp, "_build_fred_provider", lambda: _flat_provider(us_codes, 5.0))
    monkeypatch.setattr(dp, "_build_ecb_provider", lambda: _flat_provider(de_codes, 5.0))

    us_points = dp.fetch_yield_curve_for_jurisdiction("US")
    de_points = dp.fetch_yield_curve_for_jurisdiction("DE")

    for point in us_points + de_points:
        assert len(point) == 2, (
            "expected a (maturity_years, yield_bps) pair with no quote-basis "
            f"metadata, got {point!r} with {len(point)} fields"
        )

    # The only thing distinguishing a BEY-par 5.00% US point from a
    # continuously-compounded-zero 5.00% DE point should, in a normalized
    # pipeline, be SOME explicit tag surviving on the tuple. There is none --
    # the US and DE points at the shared 5/10/30y maturities are byte-for-byte
    # identical despite representing different rate conventions.
    us_by_maturity = dict(us_points)
    de_by_maturity = dict(de_points)
    shared_maturities = sorted(set(us_by_maturity) & set(de_by_maturity))
    assert shared_maturities, "fixture setup error: expected overlapping maturities"
    assert all(
        us_by_maturity[m] == de_by_maturity[m] for m in shared_maturities
    ), "expected the raw points to already be indistinguishable (no basis tag)"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "NS-CURVE-QUOTE-NORMALIZATION-001 -- round 53 red test, see audit "
        "docs/audits/2026-10-04-bond-curve-quotation-sleeve-and-return-semantics-integrity-audit.md"
    ),
)
def test_fit_nelson_siegel_has_no_curve_type_or_compounding_parameter():
    """If the pipeline normalized quote basis before fitting, fit_nelson_siegel
    (or some wrapper around it in the real call path) would need to know
    which convention it is being handed -- i.e. accept a curve_type/
    compounding/day_count-style keyword. It does not: introspect the REAL,
    currently-imported function and confirm no such parameter exists."""
    params = inspect.signature(fit_nelson_siegel).parameters
    basis_param_names = {
        name
        for name in params
        if any(
            token in name.lower()
            for token in ("curve_type", "compound", "day_count", "quote_basis", "basis")
        )
    }
    assert basis_param_names, (
        "expected fit_nelson_siegel() to accept a curve-type/compounding/"
        f"day-count parameter to distinguish quote conventions, but its real "
        f"signature is {inspect.signature(fit_nelson_siegel)} -- no such "
        f"parameter exists anywhere in the call path"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "NS-CURVE-QUOTE-NORMALIZATION-001 -- round 53 red test, see audit "
        "docs/audits/2026-10-04-bond-curve-quotation-sleeve-and-return-semantics-integrity-audit.md"
    ),
)
def test_identical_raw_quotes_different_conventions_yield_different_short_rate(monkeypatch):
    """Numeric angle (strongest form of this finding): feed the REAL
    fetch_yield_curve_for_jurisdiction() + fit_nelson_siegel() call path a
    flat 5.00% curve labelled as US (FRED, documented semi-annual BEY par
    yield) and the SAME flat 5.00% raw numbers labelled as DE (ECB, documented
    continuously-compounded zero rate per the registry comment).

    5.00% BEY par  -> effective annual rate (1+0.05/2)**2 - 1 = 5.0625 %
    5.00% continuous zero -> effective annual rate exp(0.05) - 1 = 5.1271 %

    A correct, convention-aware pipeline would convert one of these before
    fitting, so NelsonSiegelCurve.short_rate_bps() would differ between the
    two fitted curves by roughly that ~6.46 bps gap. The real pipeline applies
    NO such conversion anywhere in the call path (see the sibling tests above
    confirming the tuples and the fit_nelson_siegel() signature carry no
    distinguishing basis information) -- it fits the identical raw numbers
    through the identical function and gets the identical curve back.
    """
    us_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["US"][1]]
    de_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["DE"][1]]
    monkeypatch.setattr(dp, "_build_fred_provider", lambda: _flat_provider(us_codes, 5.0))
    monkeypatch.setattr(dp, "_build_ecb_provider", lambda: _flat_provider(de_codes, 5.0))

    us_points = dp.fetch_yield_curve_for_jurisdiction("US")  # "BEY par" per FRED docs
    de_points = dp.fetch_yield_curve_for_jurisdiction("DE")  # "continuous zero" per ECB docs

    # lambda_fixed=True: a documented, supported fit_nelson_siegel() option
    # (see its docstring: "typisch True fuer Vergleichbarkeit ueber Zeit").
    # Used here only to sidestep the unrelated 1D lambda-search's scipy
    # bracketing degeneracy on a perfectly flat input curve -- it does not
    # touch the quote-basis question this test is about at all.
    us_curve = fit_nelson_siegel(
        np.array([m for m, _ in us_points], dtype=np.float64),
        np.array([y for _, y in us_points], dtype=np.float64),
        lambda_fixed=True,
    )
    de_curve = fit_nelson_siegel(
        np.array([m for m, _ in de_points], dtype=np.float64),
        np.array([y for _, y in de_points], dtype=np.float64),
        lambda_fixed=True,
    )

    us_short_rate_bps = us_curve.short_rate_bps()
    de_short_rate_bps = de_curve.short_rate_bps()

    # This is what a quote-basis-normalized implementation would guarantee:
    # a BEY par yield and a continuously-compounded zero rate of the same
    # raw magnitude should resolve to short rates roughly ~6.46 bps apart
    # (see module docstring). A tolerance of 1 bps is far above the ~1e-12
    # bps floating-point noise of the identical-input fit below, and far
    # below the expected real convention gap -- so this is not a flaky
    # near-equality check.
    assert abs(us_short_rate_bps - de_short_rate_bps) > 1.0, (
        "expected the US (BEY par) and DE (continuous zero) short rates to "
        "differ by roughly the ~6.46 bps compounding-convention gap after "
        f"convention-aware normalization, but got US={us_short_rate_bps} bps "
        f"vs DE={de_short_rate_bps} bps (difference "
        f"{abs(us_short_rate_bps - de_short_rate_bps):.6f} bps) -- the "
        "pipeline fit the identical raw 5.00% numbers through "
        "fit_nelson_siegel() with no compounding/quote-basis conversion at "
        "all, so a BEY par yield and a continuously-compounded zero rate of "
        "the same raw magnitude are silently treated as the same number"
    )
