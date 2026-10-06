"""Round 53 red test for CMA-BOND-HOME-IG-PROXY-001 (Kontrollrunde 49).

Audit doc: docs/audits/2026-10-04-bond-curve-quotation-sleeve-and-return-semantics-integrity-audit.md

Finding: services/jurisdiction/data_pipeline.py::compute_cma_candidate_for_jurisdiction()
fits a sovereign/AAA-government yield curve (US Treasury DGS* series for US,
ECB Euro-area-AAA government series for DE -- see dp._YIELD_CURVE_REGISTRY,
both pure government/risk-free series, no corporate bond series anywhere in
the registry) and stores the 5-year Nelson-Siegel-fitted point of THAT curve
DIRECTLY as bonds_home_ig_return_bps:

    bonds_home_ig_return_bps = int(round(float(curve.yield_at(5.0))))

But docs/cma_import_workflow.md (around line 72) documents "Bonds CHF IG" as
"Schweizer Staats-/Untern.-Bonds Investment Grade" -- i.e. government AND
corporate bonds, a credit-bearing concept. services/product_exposures.py
confirms the admin-facing "Home IG" / "Obligationen Global Hedged" concept is
a fund/aggregate bond PRODUCT ("Bonds Govt+Corp IG"), not a single government
security.

So a pure risk-free sovereign yield is being persisted as if it already were
the complete expected return of an Investment-Grade bond fund/sleeve. No
credit spread, management fee, liquidity premium, or FX-hedge-cost component
is added anywhere in compute_cma_candidate_for_jurisdiction().

This test builds a known flat-ish DE government yield curve via the exact
monkeypatch pattern tests/test_cma_data_pipeline.py already uses
(_FakeProvider + monkeypatch.setattr(dp, "_build_ecb_provider", ...)),
independently re-fits the SAME points with the real fit_nelson_siegel() to
get the raw sovereign 5y yield, calls the real
compute_cma_candidate_for_jurisdiction(), and asserts the persisted
bonds_home_ig_return_bps differs from that raw sovereign yield by at least a
minimal IG credit-spread amount. It currently does not differ at all -- the
two values are identical by construction (same formula, same inputs) --
so the assertion fails for exactly the documented reason.
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from main import app  # noqa: F401
from services.market_data import MacroPoint
import services.jurisdiction.data_pipeline as dp
from services.rates.nelson_siegel import fit_nelson_siegel

# Minimal IG corporate-over-government credit spread any real "Bonds Home IG
# fund" sleeve should carry over the pure sovereign curve it is benchmarked
# against (conservative floor, far below typical IG spreads of 60-150bps).
_MIN_EXPECTED_IG_CREDIT_SPREAD_BPS = 20


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cma_bond_home_ig_credit_spread.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class _FakeProvider:
    def __init__(self, points_by_series):
        self._points_by_series = points_by_series

    def get_series(self, series_code, start, end):
        return self._points_by_series.get(series_code, [])


def _points(*values_pct):
    return [MacroPoint(date=date(2026, 7, 1), value=Decimal(str(v)), series_code="X") for v in values_pct]


def _full_curve_provider(series_codes, values_pct):
    return _FakeProvider({code: _points(v)[:1] for code, v in zip(series_codes, values_pct)})


# Same DE Euro-area-AAA-government curve values as the sibling test file's
# _patch_full_de_curve() helper (tests/test_cma_data_pipeline.py) -- reusing
# the established mocking pattern, not inventing a new one.
_DE_CURVE_YIELDS_PCT = [2.0, 2.3, 2.6, 2.9, 3.1]


def _patch_full_de_curve(monkeypatch):
    series_codes = [c for _, c in dp._YIELD_CURVE_REGISTRY["DE"][1]]
    provider = _full_curve_provider(series_codes, _DE_CURVE_YIELDS_PCT)
    monkeypatch.setattr(dp, "_build_ecb_provider", lambda: provider)


def _raw_sovereign_5y_yield_bps() -> int:
    """Independently re-fits the SAME DE curve points with the real
    fit_nelson_siegel() to get the pure government 5y yield (bps), without
    going through compute_cma_candidate_for_jurisdiction()."""
    maturities = np.array([m for m, _ in dp._YIELD_CURVE_REGISTRY["DE"][1]], dtype=np.float64)
    yields_bps = np.array([v * 100.0 for v in _DE_CURVE_YIELDS_PCT], dtype=np.float64)
    curve = fit_nelson_siegel(maturities, yields_bps)
    return int(round(float(curve.yield_at(5.0))))


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CMA-BOND-HOME-IG-PROXY-001 -- round 53 red test, see audit "
        "docs/audits/2026-10-04-bond-curve-quotation-sleeve-and-return-semantics-integrity-audit.md"
    ),
)
def test_bonds_home_ig_return_includes_credit_spread_over_pure_sovereign_yield(
    session_factory, monkeypatch
):
    _patch_full_de_curve(monkeypatch)
    # No PE proxy needed for this assertion; keep equity side irrelevant.
    monkeypatch.setattr(dp, "_fetch_pe_ticker_info", lambda ticker: {})

    raw_sovereign_5y_bps = _raw_sovereign_5y_yield_bps()

    with session_factory() as db:
        cma = dp.compute_cma_candidate_for_jurisdiction(db, "DE", "2026-07-30")
        db.commit()

        persisted_bonds_home_ig_bps = cma.bonds_home_ig_return_bps
        assert persisted_bonds_home_ig_bps is not None

        # "Bonds Home IG" is documented (docs/cma_import_workflow.md) as a
        # government-AND-corporate Investment-Grade bond concept, and the
        # admin-facing product universe (services/product_exposures.py)
        # models it as a fund/aggregate ("Bonds Govt+Corp IG"), not a bare
        # government security. A real IG fund/sleeve return must therefore
        # sit measurably above the pure sovereign curve it is fitted from.
        credit_spread_bps = persisted_bonds_home_ig_bps - raw_sovereign_5y_bps
        assert credit_spread_bps >= _MIN_EXPECTED_IG_CREDIT_SPREAD_BPS, (
            f"bonds_home_ig_return_bps ({persisted_bonds_home_ig_bps}) is not "
            f"distinguishable from the raw fitted sovereign/AAA-government 5y "
            f"yield ({raw_sovereign_5y_bps}, same Nelson-Siegel fit over the "
            f"same ECB Euro-area-AAA points) -- no credit-spread/fee/liquidity "
            f"component was added, so a pure risk-free government yield is "
            f"being persisted as the complete expected return of an "
            f"Investment-Grade bond fund/sleeve."
        )
