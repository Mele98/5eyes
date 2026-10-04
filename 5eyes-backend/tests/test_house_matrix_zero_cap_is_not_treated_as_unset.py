from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine import _baseline_target_bands  # noqa: E402


@pytest.mark.xfail(
    strict=True,
    reason=(
        "ZERO-CONSTRAINT-SEMANTICS-001 — round 46 red test, see audit "
        "2026-10-04-house-matrix-policy-constraint-and-retirement-basis-integrity-audit.md "
        "(not committed in this repo)"
    ),
)
def test_explicit_zero_policy_cap_means_true_exclusion_not_unset():
    """An explicit max_real_estate_bps=0 / max_alternatives_bps=0 on the policy
    means "exclude this asset class entirely" (cap = 0 bps). Today's code uses
    `policy.max_real_estate_bps or 10000`, which treats the falsy int 0 the
    same as "not set" and substitutes 10000 (100%, i.e. no cap at all) — so
    the effective max collapses to the house_matrix's own max instead of 0.
    """
    house_matrix = SimpleNamespace(
        equity_target_bps=4800,
        bonds_target_bps=3500,
        real_estate_target_bps=1000,
        alt_target_bps=500,
        liq_target_bps=200,
        equity_min_bps=4000,
        equity_minimum_bps=0,
        bonds_min_bps=2500,
        real_estate_min_bps=0,
        alt_min_bps=0,
        liq_min_bps=0,
        equity_max_bps=5500,
        bonds_max_bps=4500,
        # Deliberately generous house_matrix-side maxima so that, if the
        # policy's explicit zero were honored, min(house_matrix_max, 0) == 0
        # would be the only way to reach the desired effective cap.
        real_estate_max_bps=2000,
        alt_max_bps=2000,
        liq_max_bps=300,
    )
    policy = SimpleNamespace(
        max_real_estate_bps=0,
        max_alternatives_bps=0,
        min_liquidity_bps=0,
    )

    _targets, _minimums, maximums = _baseline_target_bands(house_matrix, policy)

    # Desired behavior: an explicit policy exclusion (0 bps) must survive as
    # the effective cap, not be silently widened back out to the
    # house_matrix's own (much larger) maximum.
    assert maximums["real_estate"] == 0
    assert maximums["alternatives"] == 0
