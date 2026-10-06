"""CMA-EQUITY-RETURN-DECOMPOSITION-001 (Kontrollrunde 48, round 53 red test):

services/jurisdiction/data_pipeline.py::compute_cma_candidate_for_jurisdiction()
computes the data-derived equity return as

    equity_home_return_bps = round(risk_free_bps + kgv_adjustment_bps)

(see data_pipeline.py line ~331), where:
    risk_free_bps      = NelsonSiegelCurve.short_rate_bps() (fitted from the
                          real yield curve points)
    kgv_adjustment_bps = KGVMeanReversionModel(...).expected_annual_return_
                          adjustment_bps(horizon_years) (mean-reversion
                          valuation adjustment)

There is NO separate equity-risk-premium, earnings-yield, dividend/buyback-
yield, or growth component anywhere in that formula or in this module (grep
confirms no `equity_risk_premium`, `risk_premium_bps`, `earnings_yield`, or
`dividend_yield` identifier exists in services/jurisdiction/data_pipeline.py).

Contrast: models/allocation.py::CapitalMarketAssumption already has a
`real_estate_risk_premium_bps` and an `alternatives_risk_premium_bps` field
for the OTHER asset classes -- i.e. the project's own data model already
has a "<asset>_risk_premium_bps" pattern, which the equity data-derived path
conspicuously lacks. A KGV-overvaluation-driven mean-reversion adjustment can
push the result arbitrarily negative (as reproduced below) even though a
long-run equity allocation should structurally carry a positive risk premium
over the risk-free rate.

This file reproduces the audit's worked numeric example directly via the
real, network-free core compute functions (no DB, no fetch_* mocking needed --
NelsonSiegelCurve/fit_nelson_siegel and KGVMeanReversionModel both take
already-fetched plain values, exactly like data_pipeline.py's own call path
at line ~316 and ~324-331).

Audit doc: docs/audits/2026-10-04-jurisdiction-cma-equity-measurement-snapshot-and-approval-integrity-audit.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.equity_valuation.mean_reversion import KGVMeanReversionModel
from services.rates.nelson_siegel import fit_nelson_siegel
import services.jurisdiction.data_pipeline as dp

# Audit's worked example (Kontrollrunde 48):
#   maturities = [1, 2, 5, 10, 30], yields_bps = [200, 230, 260, 290, 310]
#   trailingPE = 22, fair CAPE = 16, alpha = 0.15, horizon = 10
_MATURITIES_YEARS = np.array([1.0, 2.0, 5.0, 10.0, 30.0], dtype=np.float64)
_YIELDS_BPS = np.array([200.0, 230.0, 260.0, 290.0, 310.0], dtype=np.float64)
_TRAILING_PE = 22.0


def _compute_components():
    """Mirrors compute_cma_candidate_for_jurisdiction()'s equity-return call
    path (data_pipeline.py ~line 311-331) using the exact same production
    functions, constants, and defaults (_GENERIC_SHILLER_CAPE_FAIR_VALUE=16.0,
    _KGV_ALPHA_DEFAULT=0.15, _KGV_HORIZON_YEARS=10), with plain pre-fetched
    inputs instead of live yield-curve/PE network calls."""
    curve = fit_nelson_siegel(_MATURITIES_YEARS, _YIELDS_BPS)
    risk_free_bps = curve.short_rate_bps()

    model = KGVMeanReversionModel(
        kgv_current=_TRAILING_PE,
        kgv_fair=dp._GENERIC_SHILLER_CAPE_FAIR_VALUE,
        alpha=dp._KGV_ALPHA_DEFAULT,
    )
    kgv_adjustment_bps = model.expected_annual_return_adjustment_bps(
        dp._KGV_HORIZON_YEARS
    )
    equity_home_return_bps = int(round(risk_free_bps + kgv_adjustment_bps))
    return risk_free_bps, kgv_adjustment_bps, equity_home_return_bps


# ---------------------------------------------------------------------------
# Positive control: the two components that DO exist today are each correctly
# computed and summed -- proves the call path/harness above is sound, this is
# not a setup artifact.
# ---------------------------------------------------------------------------


def test_positive_control_risk_free_and_kgv_adjustment_sum_to_equity_return():
    risk_free_bps, kgv_adjustment_bps, equity_home_return_bps = _compute_components()

    # Nelson-Siegel short rate fitted from the audit's curve points.
    assert risk_free_bps == pytest.approx(172.6757, abs=0.01)

    # KGV mean-reversion adjustment: alpha=0.15, kgv_current=22, kgv_fair=16,
    # horizon=10 -> dampening = max(0.3, 1 - 0.03*10) = 0.7
    #   base = 0.15 * (16-22)/16 * 10000 = -562.5
    #   adj  = -562.5 * 0.7 = -393.75
    assert kgv_adjustment_bps == pytest.approx(-393.75, abs=0.01)

    # The production formula is EXACTLY this sum, nothing else.
    assert equity_home_return_bps == int(round(risk_free_bps + kgv_adjustment_bps))
    assert equity_home_return_bps == -221


# ---------------------------------------------------------------------------
# Red test: no distinguishable, non-zero equity-risk-premium component exists.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CMA-EQUITY-RETURN-DECOMPOSITION-001 -- round 53 red test, see audit "
        "docs/audits/2026-10-04-jurisdiction-cma-equity-measurement-snapshot-"
        "and-approval-integrity-audit.md"
    ),
)
def test_equity_home_return_bps_includes_a_nonzero_risk_premium_component():
    risk_free_bps, kgv_adjustment_bps, equity_home_return_bps = _compute_components()

    # There is no `equity_risk_premium_bps` (or similarly named) attribute
    # anywhere on the module to hold such a component...
    assert hasattr(dp, "compute_equity_risk_premium_bps") or hasattr(
        dp, "equity_risk_premium_bps"
    )

    # ...and the formula itself would need to differ from the bare sum of
    # risk_free_bps + kgv_adjustment_bps by some nonzero risk-premium amount.
    # Today it is EXACTLY that sum (equity_home_return_bps == -221, with a
    # clearly overvalued market and NO risk premium ever added), so this
    # assertion fails for the documented reason, not a setup error.
    implied_risk_premium_bps = equity_home_return_bps - (
        risk_free_bps + kgv_adjustment_bps
    )
    assert implied_risk_premium_bps != 0
