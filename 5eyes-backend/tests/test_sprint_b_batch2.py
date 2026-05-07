"""Sprint B Batch 2 — B2 Anderes-Vermoegen Schloss-Mechanismus.

Verifiziert:
- _compute_reserve_for_inputs respektiert unlocked_other_assets_rappen
- 0 unlocked → unveraendertes Verhalten (backwards-compat)
- unlocked >= external_reserve → external_reserve = 0
- unlocked partial → external_reserve teilweise reduziert
- Reasoning ergaenzt nur wenn absorbed > 0
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.portfolio_engine as pe


def _spending_goal(target_rappen: int = 5_000_00, years: int = 2):
    """Hilfs-Goal: Einmalige Ausgabe in 'years' Jahren."""
    from datetime import date, timedelta
    today = date.today()
    target_date = (today + timedelta(days=365 * years)).isoformat()
    return SimpleNamespace(
        id="g-test", goal_type="Einmalige_Ausgabe",
        target_amount_rappen=target_rappen, frequency=None,
        start_date=None, target_date=target_date,
        horizon_years=years, is_ongoing=0, label="Reisefonds",
    )


# ============================================================================
# B2: Schloss reduziert externe Reserve
# ============================================================================


def test_b2_no_unlock_no_change():
    """Default 0 unlocked: gleiche externe Reserve wie vor B2."""
    needed_a, ext_a = pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,  # 100k
        saa_liquidity_ceiling_bps=1000,  # 10%
        unlocked_other_assets_rappen=0,
    )
    needed_b, ext_b = pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    assert needed_a == needed_b
    assert ext_a == ext_b


def test_b2_full_unlock_zeroes_external():
    """unlocked >= external_reserve_needed → external = 0."""
    # Goal 50k in 2J, advisory 100k, saa-cap 10% (=10k) → external = ~40k
    # unlocked = 100k → external = 0
    needed, ext = pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
        unlocked_other_assets_rappen=10_000_000,
    )
    assert ext == 0


def test_b2_partial_unlock_partially_reduces():
    """unlocked < external_reserve → external teilweise reduziert."""
    # Setup: goal 50k in 2J, advisory 100k, saa-cap 10% (10k)
    # → reserve_needed = 50k, external_uncapped = 50k - 10k = 40k
    needed_full, ext_full = pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
        unlocked_other_assets_rappen=0,
    )
    # 20k unlocked → external = 40k - 20k = 20k
    needed_part, ext_part = pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
        unlocked_other_assets_rappen=2_000_000,  # 20k unlocked
    )
    assert needed_part == needed_full  # reserve_needed gleich
    assert 0 < ext_part < ext_full  # external strikt reduziert
    assert ext_part == ext_full - 2_000_000  # exakter Diff


def test_b2_reasoning_only_when_absorbed():
    """Reasoning bekommt unlock-Eintrag NUR wenn tatsaechlich absorbed > 0."""
    reasoning_with = []
    pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
        reasoning=reasoning_with,
        unlocked_other_assets_rappen=2_000_000,
    )
    joined = " ".join(reasoning_with)
    assert "Goal-Funding-Schloss" in joined or "Schloss" in joined

    # Ohne unlock: kein Schloss-Reasoning
    reasoning_without = []
    pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
        reasoning=reasoning_without,
        unlocked_other_assets_rappen=0,
    )
    assert "Schloss" not in " ".join(reasoning_without)


def test_b2_unlock_negative_clamped():
    """unlocked_other_assets_rappen < 0: defensive clamp auf 0."""
    needed_a, ext_a = pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
        unlocked_other_assets_rappen=-5_000_000,
    )
    # Sollte gleich sein wie bei 0
    needed_b, ext_b = pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
        unlocked_other_assets_rappen=0,
    )
    assert ext_a == ext_b
