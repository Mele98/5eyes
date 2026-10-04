"""NS-BOND-SLEEVE-COLLAPSE-001 and NS-YIELD-RETURN-HORIZON-001 -- round 50 red tests.

See docs/audits/2026-10-04-bond-curve-quotation-sleeve-and-return-semantics-integrity-audit.md
(Kontrollrunde 49 per the audit's own numbering).

NS-BOND-SLEEVE-COLLAPSE-001
-----------------------------
Confirmed by direct reading of services/portfolio_engine_cma.py:

    def _apply_cma_market_adjustments(returns, cma):
        ...
        ns_bonds = _compute_bonds_return_from_nelson_siegel(cma)
        if ns_bonds is not None:
            adjusted["bonds"] = int(round(ns_bonds))   # <-- full REPLACEMENT

This runs AFTER `_weighted_bucket_metrics()` has already correctly computed
a sub-allocation-weighted "bonds" return from the real CHF-IG/Global-Hedged/
High-Yield/Emerging mix (confirmed: `returns[bucket] = int(round(weighted_ret_bps[bucket] / ws))`
immediately before `_apply_cma_market_adjustments` is called). Note the
asymmetry with equities, which is adjusted ADDITIVELY
(`adjusted["equities"] + kgv_adj`) and therefore preserves the underlying
sub-allocation differentiation -- bonds alone get a full overwrite.

The audit's own reproduction, using the exact test fixture values already
in this test suite (CHF IG=180bps, High Yield=420bps, NS beta0=400/beta1=-150/
beta2=50/lambda=0.6): 100% IG, 100% HY and 80/20 IG/HY all collapse to the
identical adjusted bonds return once Nelson-Siegel is active, even though
their weighted-pre-adjustment values are 180, 420 and 228 respectively.

NS-YIELD-RETURN-HORIZON-001
------------------------------
Confirmed by direct reading: `_compute_bonds_return_from_nelson_siegel(cma)`
takes only `cma`, no horizon/duration/holding-period argument, and the
production constant `NELSON_SIEGEL_DEFAULT_MATURITY_YEARS = 5.0`
(services/cma_validation.py) is the only maturity ever read from the fitted
curve. The existing `bondsDuration` preference ("Kurzfristig"/"Gemischt"/
"Langfristig") is never passed into this function, so a client whose bond
sleeve duration preference is short-term or long-term gets the identical
bond return as a medium-term client -- the model is proven horizon-sensitive
(different yields at 2/5/10 years) but the production call site never
expresses which one applies.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from models.allocation import CapitalMarketAssumption


def _make_cma_with_ns(**overrides):
    """Same bond sub-allocation values as the audit's own reproduction and
    as the existing tests/test_audit_z4_weighted_metrics.py fixture (CHF
    IG=180, Global Hedged=220, High Yield=420 bps), plus active
    Nelson-Siegel curve parameters (beta0=400, beta1=-150, beta2=50,
    lambda=0.6 -- the audit's own reproduction values)."""
    sub_assumptions = {
        "Obligationen CHF IG": {"asset_class": "Obligationen", "expected_return_bps": 180, "expected_volatility_bps": 350},
        "Obligationen Global Hedged": {"asset_class": "Obligationen", "expected_return_bps": 220, "expected_volatility_bps": 450},
        "Obligationen High Yield": {"asset_class": "Obligationen", "expected_return_bps": 420, "expected_volatility_bps": 950},
    }
    base = dict(
        id="cma-r50-ns", assumption_set_name="Test", version=1, valid_from="2026-01-01",
        is_current=1,
        bonds_chf_ig_return_bps=180, bonds_chf_ig_vol_bps=350,
        bonds_fx_hedged_return_bps=220, bonds_fx_hedged_vol_bps=450,
        equity_ch_return_bps=500, equity_ch_vol_bps=1450,
        equity_intl_return_bps=700, equity_intl_vol_bps=1500,
        real_estate_ch_return_bps=330, real_estate_ch_vol_bps=820,
        alternatives_gold_return_bps=300, alternatives_gold_vol_bps=1200,
        liquidity_return_bps=80, liquidity_vol_bps=15,
        sub_asset_class_assumptions_json=json.dumps(sub_assumptions),
        bonds_ns_beta0_bps=400, bonds_ns_beta1_bps=-150,
        bonds_ns_beta2_bps=50, bonds_ns_lambda_x100=60,
        created_by="advisor-1",
        created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
    )
    base.update(overrides)
    return CapitalMarketAssumption(**base)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "NS-BOND-SLEEVE-COLLAPSE-001 -- round 50 red test (active "
        "Nelson-Siegel adjustment fully overwrites the weighted bonds "
        "bucket return, destroying sleeve differentiation between CHF IG, "
        "Global Hedged, High Yield and Emerging), see audit "
        "docs/audits/2026-10-04-bond-curve-quotation-sleeve-and-return-semantics-integrity-audit.md"
    ),
)
def test_active_nelson_siegel_preserves_bond_sleeve_differentiation():
    """100% CHF IG, 100% High Yield and an 80/20 IG/HY mix must keep
    DIFFERENT bond-bucket returns once Nelson-Siegel is active, exactly as
    they do when it is inactive (180 / 420 / 228 bps respectively).
    Production today collapses all three to the identical NS 5-year value."""
    from services.portfolio_engine import _weighted_bucket_metrics

    cma = _make_cma_with_ns()

    subs_100_ig = [
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen CHF IG", "target_weight_bps": 10000, "rationale": ""},
    ]
    subs_100_hy = [
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen High Yield", "target_weight_bps": 10000, "rationale": ""},
    ]
    subs_80_20 = [
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen CHF IG", "target_weight_bps": 8000, "rationale": ""},
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen High Yield", "target_weight_bps": 2000, "rationale": ""},
    ]

    returns_ig, _ = _weighted_bucket_metrics(cma, subs_100_ig)
    returns_hy, _ = _weighted_bucket_metrics(cma, subs_100_hy)
    returns_mix, _ = _weighted_bucket_metrics(cma, subs_80_20)

    bonds_ig = returns_ig["bonds"]
    bonds_hy = returns_hy["bonds"]
    bonds_mix = returns_mix["bonds"]

    assert bonds_ig != bonds_hy, (
        f"100% IG ({bonds_ig} bps) and 100% HY ({bonds_hy} bps) must remain "
        f"economically different once NS is active"
    )
    assert bonds_ig < bonds_mix < bonds_hy, (
        f"the 80/20 mix ({bonds_mix} bps) must lie strictly between pure IG "
        f"({bonds_ig} bps) and pure HY ({bonds_hy} bps)"
    )


def test_positive_control_sleeve_differentiation_without_active_ns():
    """Positive control: without NS parameters set (inactive model), the
    existing, already-correct weighted bucket logic keeps IG/HY sleeves
    differentiated (180 / 420 / 228 bps) -- this must be preserved by any
    future fix."""
    from services.portfolio_engine import _weighted_bucket_metrics

    cma = _make_cma_with_ns(
        bonds_ns_beta0_bps=None, bonds_ns_beta1_bps=None,
        bonds_ns_beta2_bps=None, bonds_ns_lambda_x100=None,
    )
    subs_100_ig = [
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen CHF IG", "target_weight_bps": 10000, "rationale": ""},
    ]
    subs_100_hy = [
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen High Yield", "target_weight_bps": 10000, "rationale": ""},
    ]
    subs_80_20 = [
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen CHF IG", "target_weight_bps": 8000, "rationale": ""},
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen High Yield", "target_weight_bps": 2000, "rationale": ""},
    ]
    returns_ig, _ = _weighted_bucket_metrics(cma, subs_100_ig)
    returns_hy, _ = _weighted_bucket_metrics(cma, subs_100_hy)
    returns_mix, _ = _weighted_bucket_metrics(cma, subs_80_20)

    assert returns_ig["bonds"] == pytest.approx(180, abs=1)
    assert returns_hy["bonds"] == pytest.approx(420, abs=1)
    assert returns_mix["bonds"] == pytest.approx(228, abs=1)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "NS-YIELD-RETURN-HORIZON-001 -- round 50 red test "
        "(_compute_bonds_return_from_nelson_siegel takes no "
        "duration/holding-period argument; bondsDuration preference never "
        "reaches the NS maturity selection, so short-/medium-/long-term "
        "clients all get the identical fixed 5-year yield), see audit "
        "docs/audits/2026-10-04-bond-curve-quotation-sleeve-and-return-semantics-integrity-audit.md"
    ),
)
def test_bond_duration_preference_should_select_different_ns_maturity():
    """A 'Kurzfristig' (short-term) and a 'Langfristig' (long-term) bond
    duration preference must materialize DIFFERENT expected returns from
    the same Nelson-Siegel curve (the curve is proven maturity-sensitive:
    2y/5y/10y give genuinely different yields). Today's production call
    has no parameter through which a duration preference could possibly
    change the result -- it is always exactly the 5-year point."""
    from services.rates.nelson_siegel import NelsonSiegelCurve
    from services.optimizer.scenario_engine import _compute_bonds_return_from_nelson_siegel

    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-150, beta2_bps=50, lambda_=0.6)
    yield_2y = curve.yield_at(2.0)
    yield_5y = curve.yield_at(5.0)
    yield_10y = curve.yield_at(10.0)
    assert yield_2y != yield_5y != yield_10y, (
        "sanity check: the curve itself is genuinely maturity-sensitive"
    )

    cma_short = _make_cma_with_ns()
    cma_long = _make_cma_with_ns()

    # There is no production parameter to express "this client's bond
    # sleeve duration preference is Kurzfristig vs Langfristig" -- both
    # calls below are therefore byte-identical in production, which is
    # exactly the bug.
    bond_return_short_term_client = _compute_bonds_return_from_nelson_siegel(cma_short)
    bond_return_long_term_client = _compute_bonds_return_from_nelson_siegel(cma_long)

    assert bond_return_short_term_client != bond_return_long_term_client, (
        "a short-term and a long-term bond duration preference must not "
        "materialize the identical expected return from a maturity-"
        "sensitive yield curve"
    )
