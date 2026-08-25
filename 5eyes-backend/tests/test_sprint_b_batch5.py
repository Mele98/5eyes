"""Sprint B Batch 5 - B3 Vorsorge-Differenziert (pension_pillar).

Verifiziert (Phase 1: Metadata + AHV staatlich gedeckt):
- _goal_pension_pillar liefert die Saeule oder None bei ungueltig
- _goal_pension_state_funded: nur True fuer AHV + Pensionsausgabe-Goal-Type
- AHV-Goal traegt 0 zur Reserve bei + Reasoning erklaert es
- AHV-Goal liefert volle target_amount in _goal_reserve_for_goal (Score 100%)
- BVG/3a/1e/FZG aendern Engine-Verhalten NICHT (Phase 1 = Metadata only)
- Backwards-compat: Goals ohne pension_pillar -> kein Verhalten-Drift
- Schema-Validierung: nur AHV/BVG/3a/1e/FZG erlaubt
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


def _pension_goal(target_rappen: int = 5_000_000, years: int = 10,
                  pension_pillar: str | None = None, label: str = "Pension"):
    from datetime import date, timedelta
    today = date.today()
    target_date = (today + timedelta(days=365 * years)).isoformat()
    g = SimpleNamespace(
        id=f"g-pension-{years}", goal_type="Pensionsausgabe",
        target_amount_rappen=target_rappen, frequency="jaehrlich",
        start_date=target_date, target_date=None,
        horizon_years=years, is_ongoing=1, label=label,
    )
    if pension_pillar is not None:
        g.pension_pillar = pension_pillar
    return g


def _spending_goal(target_rappen: int = 5_000_000, years: int = 2,
                   pension_pillar: str | None = None, label: str = "G"):
    from datetime import date, timedelta
    today = date.today()
    target_date = (today + timedelta(days=365 * years)).isoformat()
    g = SimpleNamespace(
        id=f"g-spend-{years}", goal_type="Einmalige_Ausgabe",
        target_amount_rappen=target_rappen, frequency=None,
        start_date=None, target_date=target_date,
        horizon_years=years, is_ongoing=0, label=label,
    )
    if pension_pillar is not None:
        g.pension_pillar = pension_pillar
    return g


# ============================================================================
# Helper-Tests
# ============================================================================


@pytest.mark.parametrize("pillar,expected", [
    ("AHV", "AHV"),
    ("BVG", "BVG"),
    ("3a", "3a"),
    ("1e", "1e"),
    ("FZG", "FZG"),
    (None, None),
    ("", None),
    ("garbage", None),
    ("ahv", None),  # case-sensitive
])
def test_b3_pension_pillar_helper(pillar, expected):
    g = _pension_goal(pension_pillar=pillar)
    assert pe._goal_pension_pillar(g) == expected


def test_b3_pension_pillar_missing_attr():
    g = _pension_goal()  # ohne pension_pillar gesetzt
    if hasattr(g, "pension_pillar"):
        delattr(g, "pension_pillar")
    assert pe._goal_pension_pillar(g) is None


@pytest.mark.parametrize("pillar,goal_factory,expected", [
    ("AHV", _pension_goal, True),
    ("BVG", _pension_goal, False),
    ("3a", _pension_goal, False),
    ("1e", _pension_goal, False),
    ("FZG", _pension_goal, False),
    (None, _pension_goal, False),
    # AHV pillar auf nicht-Pensionsausgabe -> nicht state-funded
    ("AHV", _spending_goal, False),
])
def test_b3_state_funded_only_for_ahv_pension(pillar, goal_factory, expected):
    g = goal_factory(pension_pillar=pillar)
    assert pe._goal_pension_state_funded(g) is expected


# ============================================================================
# Reserve-Pfad: AHV traegt 0 bei
# ============================================================================


def test_b3_ahv_pension_contributes_zero_reserve():
    """AHV Pensionsausgabe-Goal -> reserve_needed = 0 (state pays)."""
    needed, _ = pe._compute_reserve_for_inputs(
        goals=[_pension_goal(target_rappen=5_000_000, years=2, pension_pillar="AHV")],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    assert needed == 0


def test_b3_bvg_pension_contributes_normally():
    """BVG Pensionsausgabe -> Engine-Phase-1: kein Sondercase, normaler Reserve-Beitrag."""
    needed, _ = pe._compute_reserve_for_inputs(
        goals=[_pension_goal(target_rappen=5_000_000, years=2, pension_pillar="BVG")],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    # _annualize_goal_amount * legacy 100% (years<=3)
    assert needed > 0


def test_b3_ahv_pension_reasoning_explains():
    """Reasoning enthaelt klaren Hinweis auf staatliche Saeule."""
    reasoning: list[str] = []
    pe._compute_reserve_for_inputs(
        goals=[_pension_goal(target_rappen=5_000_000, years=2, pension_pillar="AHV", label="Rente")],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
        reasoning=reasoning,
    )
    joined = " ".join(reasoning)
    assert "AHV" in joined
    assert "staatliche" in joined.lower() or "Saeule" in joined
    assert "Rente" in joined


def test_b3_no_pillar_default_unchanged():
    """Ohne pension_pillar -> Verhalten identisch zu pre-B3."""
    needed_with_attr, _ = pe._compute_reserve_for_inputs(
        goals=[_pension_goal(target_rappen=5_000_000, years=2, pension_pillar=None)],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    g_no_attr = _pension_goal(target_rappen=5_000_000, years=2)
    if hasattr(g_no_attr, "pension_pillar"):
        delattr(g_no_attr, "pension_pillar")
    needed_no_attr, _ = pe._compute_reserve_for_inputs(
        goals=[g_no_attr],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    assert needed_with_attr == needed_no_attr
    assert needed_with_attr > 0


def test_b3_ahv_pillar_on_spending_goal_no_skip():
    """AHV-Pillar auf Einmalige_Ausgabe (nicht Pensionsausgabe) -> kein Skip."""
    needed, _ = pe._compute_reserve_for_inputs(
        goals=[_spending_goal(target_rappen=5_000_000, years=2, pension_pillar="AHV")],
        limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0]*7,
        advisory_wealth_rappen=10_000_000,
        saa_liquidity_ceiling_bps=1000,
    )
    assert needed == 5_000_000


# ============================================================================
# Scoring-Pfad: AHV liefert volle target zurueck (funded_ratio=100%)
# ============================================================================


def test_b3_goal_reserve_for_goal_ahv_returns_full_target():
    """AHV-Goal -> _goal_reserve_for_goal liefert volle target_amount (Score 100%)."""
    g = _pension_goal(target_rappen=12_000_000, years=2, pension_pillar="AHV")
    # _annualize_goal_amount fuer Pensionsausgabe yearly = full amount
    expected = pe._annualize_goal_amount(g)
    assert pe._goal_reserve_for_goal(g) == expected
    assert expected > 0


def test_b3_goal_reserve_for_goal_bvg_uses_legacy_logic():
    """BVG-Goal -> normale legacy-Reserve-Logik (Phase 1)."""
    g_bvg = _pension_goal(target_rappen=12_000_000, years=2, pension_pillar="BVG")
    g_none = _pension_goal(target_rappen=12_000_000, years=2)
    if hasattr(g_none, "pension_pillar"):
        delattr(g_none, "pension_pillar")
    # Phase 1: BVG ohne Sondercase
    assert pe._goal_reserve_for_goal(g_bvg) == pe._goal_reserve_for_goal(g_none)


def test_b3_ahv_with_probability_combines():
    """AHV + probability: voll erfuellt skaliert mit Wahrscheinlichkeit."""
    g = _pension_goal(target_rappen=12_000_000, years=2, pension_pillar="AHV")
    g.probability_pct = 50
    # state-funded liefert base_target * prob_factor
    expected = int(round(pe._annualize_goal_amount(g) * 0.5))
    assert pe._goal_reserve_for_goal(g) == expected


# ============================================================================
# Schema-Validierung
# ============================================================================


def _valid_pension_kwargs(**overrides):
    base = dict(
        goal_family="Cashflow",
        goal_type="Pensionsausgabe",
        label="Test",
        rank=1,
        target_amount_rappen=1_000_000,
        horizon_years=10,
        is_ongoing=True,
        frequency="jaehrlich",
        start_date="2035-01-01",
    )
    base.update(overrides)
    return base


@pytest.mark.parametrize("pillar", ["AHV", "BVG", "3a", "1e", "FZG"])
def test_b3_schema_accepts_valid_pillars(pillar):
    g = GoalCreate(**_valid_pension_kwargs(pension_pillar=pillar))
    assert g.pension_pillar == pillar


def test_b3_schema_default_is_none():
    g = GoalCreate(**_valid_pension_kwargs())
    assert g.pension_pillar is None


@pytest.mark.parametrize("invalid", ["AHV1", "ahv", "Pillar2", "", "1a"])
def test_b3_schema_rejects_invalid_pillar(invalid):
    with pytest.raises(ValidationError):
        GoalCreate(**_valid_pension_kwargs(pension_pillar=invalid))


def test_b3_update_schema_accepts_pillar_or_none():
    g = GoalUpdate(pension_pillar="3a")
    assert g.pension_pillar == "3a"
    g2 = GoalUpdate()
    assert g2.pension_pillar is None
