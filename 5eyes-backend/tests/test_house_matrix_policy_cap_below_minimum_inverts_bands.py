from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine import _baseline_target_bands, _rebalance_to_total  # noqa: E402


def _house_matrix(**overrides) -> SimpleNamespace:
    base = dict(
        equity_target_bps=4800,
        bonds_target_bps=3500,
        real_estate_target_bps=500,
        alt_target_bps=300,
        liq_target_bps=200,
        equity_min_bps=4000,
        equity_minimum_bps=0,
        bonds_min_bps=2500,
        real_estate_min_bps=500,
        alt_min_bps=300,
        liq_min_bps=0,
        equity_max_bps=5500,
        bonds_max_bps=4500,
        real_estate_max_bps=2000,
        alt_max_bps=1000,
        liq_max_bps=300,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "POLICY-ACTIVATION-COMPLETENESS-001 — round 46 red test, see audit "
        "2026-10-04-house-matrix-policy-constraint-and-retirement-basis-integrity-audit.md "
        "(not committed in this repo)"
    ),
)
def test_policy_real_estate_cap_below_house_minimum_must_not_invert_band():
    """A real House-Generate reproduction: House-Matrix minimum for real
    estate is 500 bps, but the mandate's Policy caps real estate at 300 bps
    (below that minimum).

    `_baseline_target_bands` clamps `maximums["real_estate"]` down to the
    Policy cap (300) but leaves `minimums["real_estate"]` at the House-Matrix
    minimum (500) unclamped -- so the dict it returns already has
    min(500) > max(300) for real_estate before `_rebalance_to_total` even
    runs. `_rebalance_to_total` then clamps via
    `max(minimums[key], min(maximums[key], adjusted[key]))`, which -- given
    an inverted band -- always resolves to the (higher) minimum, silently
    persisting an invalid band instead of rejecting it or lowering the
    minimum to respect the cap.

    Desired behaviour (this test encodes it, and is expected to fail until
    fixed): the system must never emit min > max. Either the activation of
    such a Policy/House-Matrix combination must be rejected, or the
    effective minimum must be clamped down to the (lower) cap so that
    min <= target <= max always holds.
    """
    house_matrix = _house_matrix()
    policy = SimpleNamespace(
        max_real_estate_bps=300,
        max_alternatives_bps=1000,
        min_liquidity_bps=0,
    )

    targets, minimums, maximums = _baseline_target_bands(house_matrix, policy)

    # Today's actual (buggy) behaviour, reproduced and locked in as the
    # documented repro numbers from the audit: min/target stay at the
    # House-Matrix minimum (500) while max is clamped to the Policy cap
    # (300) -- an inverted band persists through rebalancing.
    assert minimums["real_estate"] == 500
    assert maximums["real_estate"] == 300

    final_targets = _rebalance_to_total(targets, minimums, maximums)
    assert final_targets["real_estate"] == 500  # min "wins" over max

    # The desired, correct behaviour: the effective band must never invert.
    assert minimums["real_estate"] <= maximums["real_estate"], (
        f"Inverted real-estate band persisted: "
        f"min={minimums['real_estate']} > max={maximums['real_estate']}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "POLICY-ACTIVATION-COMPLETENESS-001 — round 46 red test, see audit "
        "2026-10-04-house-matrix-policy-constraint-and-retirement-basis-integrity-audit.md "
        "(not committed in this repo)"
    ),
)
def test_policy_alternatives_cap_below_house_minimum_must_not_invert_band():
    """Same defect, second documented repro: House-Matrix minimum for
    alternatives is 300 bps, Policy caps alternatives at 200 bps."""
    house_matrix = _house_matrix(alt_min_bps=300, alt_target_bps=300, alt_max_bps=1000)
    policy = SimpleNamespace(
        max_real_estate_bps=2000,
        max_alternatives_bps=200,
        min_liquidity_bps=0,
    )

    targets, minimums, maximums = _baseline_target_bands(house_matrix, policy)

    # Today's actual (buggy) behaviour -- documented repro numbers.
    assert minimums["alternatives"] == 300
    assert maximums["alternatives"] == 200

    final_targets = _rebalance_to_total(targets, minimums, maximums)
    assert final_targets["alternatives"] == 300  # min "wins" over max

    assert minimums["alternatives"] <= maximums["alternatives"], (
        f"Inverted alternatives band persisted: "
        f"min={minimums['alternatives']} > max={maximums['alternatives']}"
    )
