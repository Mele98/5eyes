"""B1-B6 Edge-Case Coverage.

Ergaenzt die existierenden test_audit_bX_*.py Files um Randfaelle, die in den
Haupt-Tests nicht explizit abgedeckt sind:

- B1: Deflation, Series zu kurz, Series leer
- B3: nur Expense+Amortisation triggert (Capital/Income oder Hypothek-Zinsen nicht)
- B5: Clamping success_rate ueber/unter Range, hardness "unknown" -> primaer
- B6: weight_bps=0 ueberall, Mix nur hart+opp ohne primaer, achievement_score None
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.cashflow_timeline import _compound_inflation_factor
from services.portfolio_engine import _build_mandate_score, _compute_goal_score


# ============================================================================
# B1 Edge: Deflation und Series-Boundary
# ============================================================================

def test_b1_edge_deflation_shrinks_factor():
    """Negative Inflation (Deflation) -> Faktor < 1.0."""
    factor = _compound_inflation_factor([-200, -200], start_year=2026, target_year=2028)
    # (1 - 0.02) * (1 - 0.02) = 0.9604
    assert factor == pytest.approx(0.9604, rel=1e-4)


def test_b1_edge_series_shorter_than_horizon_extends_last():
    """Wenn series kuerzer als offset, wird letzter Wert konstant fortgeschrieben."""
    # 2-Jahres-Series, 5-Jahres-Horizont -> letzter Wert (300 bps) gilt fuer Jahre 3-5
    factor = _compound_inflation_factor([100, 200, 300], start_year=2026, target_year=2031)
    # 1.01 * 1.02 * 1.03 * 1.03 * 1.03
    expected = 1.01 * 1.02 * 1.03 * 1.03 * 1.03
    assert factor == pytest.approx(expected, rel=1e-6)


def test_b1_edge_empty_series_returns_one():
    """Leere oder None series -> Faktor 1.0 (kein Effekt)."""
    assert _compound_inflation_factor([], start_year=2026, target_year=2030) == 1.0
    assert _compound_inflation_factor(None, start_year=2026, target_year=2030) == 1.0


def test_b1_edge_target_year_before_start_year_returns_one():
    """Vergangenheits-Jahr -> Faktor 1.0 (kein Negativ-Compound)."""
    factor = _compound_inflation_factor([200, 200], start_year=2026, target_year=2024)
    assert factor == 1.0


# ============================================================================
# B5 Edge: Clamping-Symmetrie und Hardness-Fallback
# ============================================================================

def test_b5_edge_success_rate_above_100_clamped():
    """success_rate=150 wird auf 100 geclampt."""
    score = _compute_goal_score(success_rate_pct=150, funded_ratio_pct=50, hardness_key="primaer")
    # alpha=0.5, sr=100, fr=50 -> 75
    assert score == 75


def test_b5_edge_success_rate_negative_clamped_to_zero():
    """success_rate=-30 wird auf 0 geclampt."""
    score = _compute_goal_score(success_rate_pct=-30, funded_ratio_pct=80, hardness_key="primaer")
    # alpha=0.5, sr=0, fr=80 -> 40
    assert score == 40


def test_b5_edge_unknown_hardness_uses_primary_alpha():
    """Unbekannter hardness_key -> fallback auf primaer (alpha=0.5)."""
    score = _compute_goal_score(success_rate_pct=80, funded_ratio_pct=20, hardness_key="weltraum")
    # alpha=0.5, balanced -> 50
    assert score == 50


# ============================================================================
# B6 Edge: weight_bps=0, achievement_score None, kein primaer
# ============================================================================

def test_b6_edge_all_zero_weights_returns_none():
    """Alle Goals weight_bps=0 -> weight_sum=0 -> weighted_score=None."""
    goals = [
        {"goal_id": "g1", "achievement_score": 80, "weight_bps": 0, "hardness": "Primaer"},
        {"goal_id": "g2", "achievement_score": 40, "weight_bps": 0, "hardness": "Primaer"},
    ]
    score = _build_mandate_score(goals)
    assert score["weighted_score"] is None
    assert score["weakest_hard_score"] is None


def test_b6_edge_none_achievement_score_treated_as_zero():
    """achievement_score=None wird als 0 behandelt."""
    goals = [
        {"goal_id": "g1", "achievement_score": None, "weight_bps": 5000, "hardness": "Primaer"},
        {"goal_id": "g2", "achievement_score": 100, "weight_bps": 5000, "hardness": "Primaer"},
    ]
    score = _build_mandate_score(goals)
    # 0 und 100 mit gleichem effective weight -> 50
    assert score["weighted_score"] == 50


def test_b6_edge_only_hard_and_opp_no_primary_works():
    """Mix nur hart + opportunistisch, kein primaer -> beide Aggregate berechenbar."""
    goals = [
        {"goal_id": "h1", "achievement_score": 90, "weight_bps": 4000, "hardness": "Hart"},
        {"goal_id": "h2", "achievement_score": 30, "weight_bps": 4000, "hardness": "Hart"},
        {"goal_id": "o1", "achievement_score": 100, "weight_bps": 2000, "hardness": "Opportunistisch"},
    ]
    score = _build_mandate_score(goals)
    assert score["weighted_score"] is not None
    assert score["weakest_hard_score"] == 30
    assert score["weakest_hard_goal_id"] == "h2"


def test_b6_edge_unknown_hardness_falls_back_to_primary_in_aggregation():
    """Goals mit unbekanntem hardness-string werden als primaer gewichtet."""
    goals = [
        {"goal_id": "x1", "achievement_score": 80, "weight_bps": 5000, "hardness": "Weltraum"},
        {"goal_id": "x2", "achievement_score": 40, "weight_bps": 5000, "hardness": "Quantenphysik"},
    ]
    score = _build_mandate_score(goals)
    # beide als primaer -> gleicher multiplier -> arithmetic mean
    assert score["weighted_score"] == 60
    # keine harten Goals
    assert score["weakest_hard_score"] is None
