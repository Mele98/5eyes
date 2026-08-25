"""Sprint B Batch 3 - B5 Time-Bucket-Reserve.

Verifiziert:
- _time_bucket_reserve_factor: 100/80/35/0 fuer <=1J / 1-3J / 3-7J / >7J
- _time_bucket_label: korrekte Bucket-Labels
- _compute_reserve_for_inputs respektiert RESERVE_BUCKET_MODE=time_bucket
- _goal_reserve_for_goal liefert kongruente Werte (Scoring-Reserve = Tilt-Reserve)
- Default-Mode unveraendert (kein env -> legacy stufen)
- Reasoning enthaelt Bucket-Label nur im time_bucket-Mode
- smooth-decay (A4) hat Vorrang vor time_bucket wenn beide gesetzt
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.portfolio_engine as pe


@contextmanager
def _env(**overrides):
    """Setzt env-vars temporaer; loescht zuvor gesetzte Werte sauber."""
    saved: dict[str, str | None] = {}
    try:
        for key, value in overrides.items():
            saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, prev in saved.items():
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev


def _spending_goal(target_rappen: int = 5_000_000, years: int = 2, label: str = "G"):
    from datetime import date, timedelta
    today = date.today()
    target_date = (today + timedelta(days=365 * years)).isoformat()
    return SimpleNamespace(
        id=f"g-{years}", goal_type="Einmalige_Ausgabe",
        target_amount_rappen=target_rappen, frequency=None,
        start_date=None, target_date=target_date,
        horizon_years=years, is_ongoing=0, label=label,
    )


# ============================================================================
# B5 reine Helper-Tests
# ============================================================================


@pytest.mark.parametrize(
    "years,expected_factor,expected_label",
    [
        (0, 1.00, "≤1J"),
        (1, 1.00, "≤1J"),
        (2, 0.80, "1-3J"),
        (3, 0.80, "1-3J"),
        (4, 0.35, "3-7J"),
        (7, 0.35, "3-7J"),
        (8, 0.00, ">7J"),
        (20, 0.00, ">7J"),
    ],
)
def test_b5_factor_and_label(years, expected_factor, expected_label):
    assert pe._time_bucket_reserve_factor(years) == pytest.approx(expected_factor)
    assert pe._time_bucket_label(years) == expected_label


def test_b5_factor_handles_none_and_negative():
    assert pe._time_bucket_reserve_factor(None) == pytest.approx(1.0)
    assert pe._time_bucket_reserve_factor(-3) == pytest.approx(1.0)
    assert pe._time_bucket_label(None) == "≤1J"


# ============================================================================
# B5 Mode-Switch in _compute_reserve_for_inputs
# ============================================================================


def test_b5_default_mode_unchanged():
    """Ohne env -> legacy stufen Verhalten unveraendert (Backwards-Compat)."""
    with _env(RESERVE_BUCKET_MODE=None, RESERVE_DECAY_MODE=None):
        # 2J Goal, 50k -> stufen: <=3J = 100% = 50k
        needed_legacy, _ = pe._compute_reserve_for_inputs(
            goals=[_spending_goal(target_rappen=5_000_000, years=2)],
            limits_prefs={}, asset_class_prefs={},
            recurring_net_cashflow_rappen=0,
            recurring_cashflow_projection_series_rappen=[0]*7,
            advisory_wealth_rappen=10_000_000,
            saa_liquidity_ceiling_bps=1000,
        )
        assert needed_legacy == 5_000_000


def test_b5_mode_uses_time_bucket_factor():
    """Mit RESERVE_BUCKET_MODE=time_bucket: 2J Goal 50k -> 80% = 40k."""
    with _env(RESERVE_BUCKET_MODE="time_bucket", RESERVE_DECAY_MODE=None):
        needed, _ = pe._compute_reserve_for_inputs(
            goals=[_spending_goal(target_rappen=5_000_000, years=2)],
            limits_prefs={}, asset_class_prefs={},
            recurring_net_cashflow_rappen=0,
            recurring_cashflow_projection_series_rappen=[0]*7,
            advisory_wealth_rappen=10_000_000,
            saa_liquidity_ceiling_bps=1000,
        )
        assert needed == 4_000_000  # 50k * 0.80


def test_b5_mode_long_horizon_zero_reserve():
    """Mit time_bucket Mode: 10J Goal -> 0% Reserve."""
    with _env(RESERVE_BUCKET_MODE="time_bucket", RESERVE_DECAY_MODE=None):
        needed, _ = pe._compute_reserve_for_inputs(
            goals=[_spending_goal(target_rappen=5_000_000, years=10)],
            limits_prefs={}, asset_class_prefs={},
            recurring_net_cashflow_rappen=0,
            recurring_cashflow_projection_series_rappen=[0]*7,
            advisory_wealth_rappen=10_000_000,
            saa_liquidity_ceiling_bps=1000,
        )
        assert needed == 0


def test_b5_mode_one_year_full_reserve():
    """Mit time_bucket Mode: 1J Goal -> 100% Reserve."""
    with _env(RESERVE_BUCKET_MODE="time_bucket", RESERVE_DECAY_MODE=None):
        needed, _ = pe._compute_reserve_for_inputs(
            goals=[_spending_goal(target_rappen=5_000_000, years=1)],
            limits_prefs={}, asset_class_prefs={},
            recurring_net_cashflow_rappen=0,
            recurring_cashflow_projection_series_rappen=[0]*7,
            advisory_wealth_rappen=10_000_000,
            saa_liquidity_ceiling_bps=1000,
        )
        assert needed == 5_000_000


def test_b5_reasoning_mentions_bucket_label():
    """Reasoning-Text enthaelt Bucket-Label, nicht den legacy-Text."""
    with _env(RESERVE_BUCKET_MODE="time_bucket", RESERVE_DECAY_MODE=None):
        reasoning: list[str] = []
        pe._compute_reserve_for_inputs(
            goals=[_spending_goal(target_rappen=5_000_000, years=5, label="Auto")],
            limits_prefs={}, asset_class_prefs={},
            recurring_net_cashflow_rappen=0,
            recurring_cashflow_projection_series_rappen=[0]*7,
            advisory_wealth_rappen=10_000_000,
            saa_liquidity_ceiling_bps=1000,
            reasoning=reasoning,
        )
        joined = " ".join(reasoning)
        assert "3-7J" in joined
        assert "Zeit-Bucket" in joined
        assert "Auto" in joined


def test_b5_reasoning_legacy_text_in_default_mode():
    """Default-Mode behaelt legacy 'kurzfristiger Liquiditaetsbedarf' Text."""
    with _env(RESERVE_BUCKET_MODE=None, RESERVE_DECAY_MODE=None):
        reasoning: list[str] = []
        pe._compute_reserve_for_inputs(
            goals=[_spending_goal(target_rappen=5_000_000, years=2, label="Auto")],
            limits_prefs={}, asset_class_prefs={},
            recurring_net_cashflow_rappen=0,
            recurring_cashflow_projection_series_rappen=[0]*7,
            advisory_wealth_rappen=10_000_000,
            saa_liquidity_ceiling_bps=1000,
            reasoning=reasoning,
        )
        joined = " ".join(reasoning)
        assert "Zeit-Bucket" not in joined
        assert "kurzfristiger Liquiditaetsbedarf" in joined


def test_b5_smooth_decay_takes_precedence():
    """Wenn beide Mode-Flags gesetzt sind, gewinnt smooth-decay (A4 zuerst geprueft)."""
    with _env(RESERVE_BUCKET_MODE="time_bucket", RESERVE_DECAY_MODE="smooth"):
        # 2J Goal: smooth = 0.95 * 50k = 47'500; time_bucket = 0.80 * 50k = 40'000
        needed, _ = pe._compute_reserve_for_inputs(
            goals=[_spending_goal(target_rappen=5_000_000, years=2)],
            limits_prefs={}, asset_class_prefs={},
            recurring_net_cashflow_rappen=0,
            recurring_cashflow_projection_series_rappen=[0]*7,
            advisory_wealth_rappen=10_000_000,
            saa_liquidity_ceiling_bps=1000,
        )
        assert needed == 4_750_000  # 50k * 0.95 (smooth-decay-factor fuer y=2)


# ============================================================================
# B5 Konsistenz mit _goal_reserve_for_goal (Scoring-Pfad)
# ============================================================================


@pytest.mark.parametrize("years,expected_rappen", [
    (1, 5_000_000),
    (2, 4_000_000),
    (5, 1_750_000),
    (10, 0),
])
def test_b5_goal_reserve_matches_compute_reserve(years, expected_rappen):
    """Scoring-Pfad muss exakt gleiches Reserve-Volumen liefern wie Tilt-Pfad."""
    with _env(RESERVE_BUCKET_MODE="time_bucket", RESERVE_DECAY_MODE=None):
        goal = _spending_goal(target_rappen=5_000_000, years=years)
        scoring_reserve = pe._goal_reserve_for_goal(goal)
        assert scoring_reserve == expected_rappen

        tilt_reserve, _ = pe._compute_reserve_for_inputs(
            goals=[goal],
            limits_prefs={}, asset_class_prefs={},
            recurring_net_cashflow_rappen=0,
            recurring_cashflow_projection_series_rappen=[0]*7,
            advisory_wealth_rappen=10_000_000,
            saa_liquidity_ceiling_bps=1000,
        )
        assert tilt_reserve == expected_rappen


# ============================================================================
# B5 Backwards-Compat: B2-Schloss kombiniert mit Time-Bucket
# ============================================================================


def test_b5_combines_with_b2_unlock():
    """Time-Bucket Reserve + B2 unlocked_other_assets -> external Reserve reduziert."""
    with _env(RESERVE_BUCKET_MODE="time_bucket", RESERVE_DECAY_MODE=None):
        # 2J Goal 50k -> reserve_needed = 0.80 * 50k = 40k
        # advisory 100k, saa-cap 10% (=10k) -> external = 30k uncapped
        # unlocked = 20k -> external = 10k
        needed, ext = pe._compute_reserve_for_inputs(
            goals=[_spending_goal(target_rappen=5_000_000, years=2)],
            limits_prefs={}, asset_class_prefs={},
            recurring_net_cashflow_rappen=0,
            recurring_cashflow_projection_series_rappen=[0]*7,
            advisory_wealth_rappen=10_000_000,
            saa_liquidity_ceiling_bps=1000,
            unlocked_other_assets_rappen=2_000_000,
        )
        assert needed == 4_000_000
        # external_uncapped = 4M - 1M = 3M; absorbed 2M -> 1M
        assert ext == 1_000_000
