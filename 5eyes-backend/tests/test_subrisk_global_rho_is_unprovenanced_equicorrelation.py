"""SUBRISK-GLOBAL-RHO-MODEL-001 -- round 53 red test.

See audit docs/audits/2026-10-05-sub-asset-risk-aggregation-cache-and-
replay-integrity-audit.md (Kontrollrunde 51 per the audit's own numbering).

Confirmed by direct reading of config.py and services/portfolio_engine_cma.py:

    # config.py:377
    sub_class_intra_correlation: float = 1.0

    # config.py:406-415 -- the ONLY validation is a bare range check
    @field_validator('sub_class_intra_correlation')
    @classmethod
    def validate_sub_class_intra_correlation(cls, value: float) -> float:
        v = float(value)
        if v < 0.0 or v > 1.0:
            raise ValueError(...)
        return v

    # services/portfolio_engine_cma.py:522 (_weighted_bucket_metrics)
    intra_rho = float(getattr(settings, "sub_class_intra_correlation", 1.0))
    use_intra_diversification = intra_rho < 1.0
    ...
    variance += 2 * wf_i * wf_j * intra_rho * sigma_i * sigma_j

A single global deployment-config float is applied as the EQUICORRELATION
between every pair of sub-asset-classes in every bucket (Equity-CH/Equity-
Global, Equity-Global/Equity-EM, Bonds-CHF-IG/Bonds-High-Yield -- all pairs,
all buckets, identical rho). The value has no source, no jurisdiction
binding, no time-period/as-of-date, and no approval workflow -- unlike CMA
assumption sets (see CMA-APPROVAL-PREFLIGHT-001, round 50) there is no
provenance object a reviewer signed off on. Yet it materially changes the
bucket volatility the solver optimizes against (see the numeric
reproduction below).

This test suite:
  1. Reproduces the audit's own numeric table using the EXACT sub-CMA
     fixture values from tests/test_audit_z4_weighted_metrics.py
     (_make_cma helper pattern: Equity CH/Global/EM vol 1450/1500/1900 bps
     at 30/30/40 mix; Bonds CHF-IG/High-Yield vol 350/950 bps at 80/20 mix).
  2. Asserts (RED, xfail strict) that changing ONLY this global setting,
     with CMA/sub-allocation/returns/vols held fully constant, requires
     some approved/sourced provenance binding before it is allowed to
     change the computed bucket volatility -- production has no such gate
     at all, so the assertion fails for exactly this documented reason.
  3. A non-xfail positive control documenting the real magnitude of the
     (unprovenanced) sensitivity itself, independent of the governance gap.
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
from config import settings
from services.portfolio_engine_cma import _weighted_bucket_metrics


def _make_cma(**overrides):
    """Same sub-CMA fixture pattern as tests/test_audit_z4_weighted_metrics.py
    (_make_cma), with the vol values the audit's own reproduction uses:
    Equity CH 1450bps, Global 1500bps, EM 1900bps; Bonds CHF IG 350bps,
    High Yield 950bps."""
    sub_assumptions = {
        "Aktien Schweiz": {"asset_class": "Aktien", "expected_return_bps": 500, "expected_volatility_bps": 1450},
        "Aktien Global": {"asset_class": "Aktien", "expected_return_bps": 700, "expected_volatility_bps": 1500},
        "Aktien Schwellenlaender": {"asset_class": "Aktien", "expected_return_bps": 900, "expected_volatility_bps": 1900},
        "Obligationen CHF IG": {"asset_class": "Obligationen", "expected_return_bps": 180, "expected_volatility_bps": 350},
        "Obligationen High Yield": {"asset_class": "Obligationen", "expected_return_bps": 420, "expected_volatility_bps": 950},
    }
    base = dict(
        id="cma-subrisk-r53", assumption_set_name="Test", version=1, valid_from="2026-01-01",
        is_current=1,
        bonds_chf_ig_return_bps=180, bonds_chf_ig_vol_bps=350,
        bonds_fx_hedged_return_bps=220, bonds_fx_hedged_vol_bps=450,
        equity_ch_return_bps=500, equity_ch_vol_bps=1450,
        equity_intl_return_bps=700, equity_intl_vol_bps=1500,
        real_estate_ch_return_bps=330, real_estate_ch_vol_bps=820,
        alternatives_gold_return_bps=300, alternatives_gold_vol_bps=1200,
        liquidity_return_bps=80, liquidity_vol_bps=15,
        sub_asset_class_assumptions_json=json.dumps(sub_assumptions),
        created_by="advisor-1",
        created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
    )
    base.update(overrides)
    return CapitalMarketAssumption(**base)


def _equity_and_bond_sub_allocations():
    """Equity 30/30/40 CH/Global/EM; Bonds 80/20 CHF-IG/High-Yield -- the
    exact mixes used in the audit's reproduction table."""
    return [
        {"asset_class": "Aktien", "sub_asset_class": "Aktien Schweiz", "target_weight_bps": 3000, "rationale": ""},
        {"asset_class": "Aktien", "sub_asset_class": "Aktien Global", "target_weight_bps": 3000, "rationale": ""},
        {"asset_class": "Aktien", "sub_asset_class": "Aktien Schwellenlaender", "target_weight_bps": 4000, "rationale": ""},
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen CHF IG", "target_weight_bps": 8000, "rationale": ""},
        {"asset_class": "Obligationen", "sub_asset_class": "Obligationen High Yield", "target_weight_bps": 2000, "rationale": ""},
    ]


# ============================================================================
# RED -- SUBRISK-GLOBAL-RHO-MODEL-001: no provenance/approval gate exists
# ============================================================================

@pytest.mark.xfail(
    strict=True,
    reason=(
        "SUBRISK-GLOBAL-RHO-MODEL-001 -- round 53 red test, see audit "
        "docs/audits/2026-10-05-sub-asset-risk-aggregation-cache-and-replay-"
        "integrity-audit.md"
    ),
)
def test_changing_global_rho_requires_provenance_or_approval(monkeypatch):
    """Changing ONLY settings.sub_class_intra_correlation (CMA, sub-
    allocation weights, returns and vols all held fully constant) must be
    refused, or must require an approved/sourced provenance record binding
    this correlation value to a jurisdiction, CMA version and as-of date --
    analogous to the CMA-APPROVAL-PREFLIGHT-001 gate already required for
    CMA assumption sets. Production has no such gate whatsoever:
    _weighted_bucket_metrics() reads the bare deployment float directly
    (services/portfolio_engine_cma.py:522) and silently applies it as an
    equicorrelation rho to every sub-asset pair in every bucket, with no
    way to even express that the value is unprovenanced. This assertion
    therefore fails today for exactly that reason: no exception is raised
    and no provenance object is required."""
    cma = _make_cma()
    subs = _equity_and_bond_sub_allocations()

    # rho=1.0 (the backwards-compatible default) is a no-op for the
    # equicorrelation branch, so pick an off-default value to exercise the
    # real diversification path -- this is precisely the unprovenanced
    # global deployment setting the audit flags.
    monkeypatch.setattr(settings, "sub_class_intra_correlation", 0.5)

    with pytest.raises((ValueError, PermissionError, RuntimeError, AttributeError)):
        # Correct behavior would refuse to use an unprovenanced global rho
        # (or demand an approved SubAssetCovarianceEvidence-style record).
        # Today this call succeeds silently and returns a bucket volatility
        # that differs materially from the rho=1.0 baseline -- see the
        # positive control below for the exact magnitude.
        _weighted_bucket_metrics(cma, subs)


# ============================================================================
# Positive control -- document the real magnitude of the unprovenanced
# sensitivity itself (not xfail: this documents current, reproducible
# behavior, independent of the governance gap above).
# ============================================================================

def test_global_rho_materially_changes_bucket_volatility_positive_control(monkeypatch):
    """Positive control reproducing (at least) two of the audit's four
    data points exactly, using the real _weighted_bucket_metrics()
    function with the documented sub-CMA fixture and sub-allocation mix.

    Audit's reproduction table (Equity 30/30/40 CH/Global/EM @ 1450/1500/
    1900 bps vol; Bonds 80/20 CHF-IG/High-Yield @ 350/950 bps vol):

        rho=1.0: Equity-Bucket 1645bps, Bond-Bucket 470bps
        rho=0.8: Equity-Bucket 1536bps, Bond-Bucket 447bps
        rho=0.5: Equity-Bucket 1356bps, Bond-Bucket 410bps
        rho=0.0: Equity-Bucket  985bps, Bond-Bucket 338bps

    Note rho=1.0 collapses to the plain weighted-average vol branch
    (use_intra_diversification = intra_rho < 1.0 is False), which the
    production code already computes identically regardless of this
    setting -- it is reproduced here as the baseline, not as evidence of
    the setting's own effect; rho=0.8/0.5/0.0 are the branch this audit
    finding is actually about.
    """
    cma = _make_cma()
    subs = _equity_and_bond_sub_allocations()

    results_by_rho: dict[float, tuple[int, int]] = {}
    for rho in (1.0, 0.8, 0.5, 0.0):
        monkeypatch.setattr(settings, "sub_class_intra_correlation", rho)
        _, vols = _weighted_bucket_metrics(cma, subs)
        results_by_rho[rho] = (vols["equities"], vols["bonds"])

    # rho=1.0 baseline (plain weighted average, Fix M1 branch inactive).
    assert results_by_rho[1.0] == pytest.approx((1645, 470), abs=1)
    # rho=0.0 (fully diversified block-diagonal floor) -- the two most
    # extreme, clearly distinguishable points from the audit's table.
    assert results_by_rho[0.0] == pytest.approx((985, 338), abs=1)

    # Monotonicity + materiality: strictly decreasing in rho, and the
    # swing from rho=1.0 to rho=0.0 is large (hundreds of bps), confirming
    # this single unprovenanced global float is not a cosmetic input.
    equity_vols = [results_by_rho[r][0] for r in (1.0, 0.8, 0.5, 0.0)]
    bond_vols = [results_by_rho[r][1] for r in (1.0, 0.8, 0.5, 0.0)]
    assert equity_vols == sorted(equity_vols, reverse=True)
    assert bond_vols == sorted(bond_vols, reverse=True)
    assert equity_vols[0] - equity_vols[-1] > 600, (
        f"expected a >600bps swing across rho in [0,1], got "
        f"{equity_vols[0] - equity_vols[-1]}"
    )
    assert bond_vols[0] - bond_vols[-1] > 100, (
        f"expected a >100bps swing across rho in [0,1], got "
        f"{bond_vols[0] - bond_vols[-1]}"
    )
