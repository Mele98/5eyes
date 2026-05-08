"""Sprint B Batch 4 - B6 Conditional Goals (probability_pct).

Verifiziert:
- _goal_probability_factor: liefert prob/100, default 1.0
- Reserve in _compute_reserve_for_inputs wird linear mit prob/100 skaliert
- _goal_reserve_for_goal liefert kongruenten Wert
- Reasoning erwaehnt Bedingung NUR wenn prob < 100
- Backwards-compat: kein probability_pct Attr -> 1.0
- Schema-Validierung: 0-100 erlaubt, -1 / 101 abgelehnt
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.portfolio_engine as pe
from schemas.wealth import GoalCreate, GoalUpdate


def _spending_goal(target_rappen: int = 5_000_000, years: int = 2,
                   probability_pct: int | None = None, label: str = "G"):
    from datetime import date, timedelta
    today = date.today()
    target_date = (today + timedelta(days=365 * years)).isoformat()
    g = SimpleNamespace(
        id=f"g-{years}", goal_type="Einmalige_Ausgabe",
        target_amount_rappen=target_rappen, frequency=None,
        start_date=None, target_date=target_date,
        horizon_years=years, is_ongoing=0, label=label,
    )
    if probability_pct is not None:
        g.probability_pct = probability_pct
    return g


# ============================================================================
# Helper-Tests
# ============================================================================


@pytest.mark.parametrize("pct,expected", [
    (None, 1.0),
    (100, 1.0),
    (75, 0.75),
    (50, 0.5),
    (25, 0.25),
    (0, 0.0),
])
def test_b6_probability_factor(pct, expected):
    g = _spending_goal(probability_pct=pct)
    assert pe._goal_probability_factor(g) == pytest.approx(expected)


def test_b6_probability_factor_missing_attr_defaults_to_one():
    """Backwards-compat: alte Goals ohne probability_pct Attr -> 1.0."""
    g = _spending_goal()  # kein probability_pct gesetzt
    if hasattr(g, "probability_pct"):
        delattr(g, "probability_pct")
    assert pe._goal_probability_factor(g) == 1.0


@pytest.mark.parametrize("invalid", ["abc", object()])
def test_b6_probability_factor_garbage_defaults_to_one(invalid):
    g = _spending_goal(probability_pct=invalid)
    assert pe._goal_probability_factor(g) == 1.0


def test_b6_probability_factor_clamps_out_of_range():
    """Defensive Clamp falls DB einen Out-of-Range Wert hat."""
    assert pe._goal_probability_factor(_spending_goal(probability_pct=150)) == 1.0
    assert pe._goal_probability_factor(_spending_goal(probability_pct=-10)) == 0.0


def test_b6_is_conditional_helper():
    assert pe._goal_is_conditional(_spending_goal(probability_pct=50)) is True
    assert pe._goal_is_conditional(_spending_goal(probability_pct=100)) is False
    assert pe._goal_is_conditional(_spending_goal()) is False


# ============================================================================
# Reserve-Pfad: probability skaliert linear
# ============================================================================


def test_b6_reserve_default_unchanged():
    """Default (kein prob_pct gesetzt) -> Reserve identisch zu pre-B6."""
    needed_default, _ = pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    needed_explicit, _ = pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2, probability_pct=100)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    assert needed_default == 5_000_000
    assert needed_explicit == 5_000_000


def test_b6_reserve_half_probability_halves():
    """50% Wahrscheinlichkeit -> Reserve halbiert."""
    needed, _ = pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2, probability_pct=50)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    assert needed == 2_500_000


def test_b6_reserve_zero_probability_zero():
    """0% -> kein Reserve-Beitrag aus diesem Goal."""
    needed, _ = pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2, probability_pct=0)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    assert needed == 0


def test_b6_reserve_max_across_certain_and_conditional():
    """Sicheres Ziel (100%) + bedingtes (30%) -> max() greift wie bisher."""
    needed, _ = pe._compute_reserve_for_inputs(
        goals=[
            _spending_goal(target_rappen=3_000_000, years=2, probability_pct=100, label="A"),
            _spending_goal(target_rappen=10_000_000, years=2, probability_pct=30, label="B"),
        ],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    # B: 100k * 0.30 = 30k; A: 30k. max=30k
    assert needed == 3_000_000


# ============================================================================
# Reasoning-Text
# ============================================================================


def test_b6_reasoning_mentions_conditional_when_below_100():
    reasoning: list[str] = []
    pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2, probability_pct=60, label="Auto")],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
        reasoning=reasoning,
    )
    joined = " ".join(reasoning)
    assert "bedingt" in joined
    assert "60%" in joined
    assert "Auto" in joined


def test_b6_reasoning_silent_when_certain():
    reasoning: list[str] = []
    pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2, probability_pct=100, label="Auto")],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
        reasoning=reasoning,
    )
    assert "bedingt" not in " ".join(reasoning)


# ============================================================================
# Scoring-Pfad konsistent zu Reserve-Pfad
# ============================================================================


@pytest.mark.parametrize("pct,expected", [
    (100, 5_000_000),
    (50, 2_500_000),
    (0, 0),
])
def test_b6_goal_reserve_for_goal_matches_compute_reserve(pct, expected):
    goal = _spending_goal(target_rappen=5_000_000, years=2, probability_pct=pct)
    scoring = pe._goal_reserve_for_goal(goal)
    assert scoring == expected

    tilt, _ = pe._compute_reserve_for_inputs(
        goals=[goal],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    assert tilt == expected


# ============================================================================
# Schema-Validierung
# ============================================================================


def _valid_create_kwargs(**overrides):
    base = dict(
        goal_family="Cashflow",
        goal_type="Einmalige_Ausgabe",
        label="Test",
        rank=1,
        target_amount_rappen=1_000_000,
        horizon_years=2,
    )
    base.update(overrides)
    return base


def test_b6_schema_default_is_100():
    g = GoalCreate(**_valid_create_kwargs())
    assert g.probability_pct == 100


def test_b6_schema_accepts_full_range():
    for pct in (0, 1, 50, 99, 100):
        g = GoalCreate(**_valid_create_kwargs(probability_pct=pct))
        assert g.probability_pct == pct


@pytest.mark.parametrize("invalid", [-1, -10, 101, 150])
def test_b6_schema_rejects_out_of_range(invalid):
    with pytest.raises(ValidationError):
        GoalCreate(**_valid_create_kwargs(probability_pct=invalid))


def test_b6_update_schema_optional():
    """GoalUpdate.probability_pct ist Optional (None erlaubt = unchanged)."""
    g = GoalUpdate()
    assert g.probability_pct is None
    g2 = GoalUpdate(probability_pct=42)
    assert g2.probability_pct == 42


@pytest.mark.parametrize("invalid", [-1, 101])
def test_b6_update_schema_validates_range(invalid):
    with pytest.raises(ValidationError):
        GoalUpdate(probability_pct=invalid)
