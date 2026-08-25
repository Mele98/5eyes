"""B5 - Score-Formel hardness-gewichtet konsolidieren.

Wissenschaftlich (Brunel 2003, Das/Markowitz/Scheid/Statman 2010, Vanguard 2015):
- Hartes Ziel (Notreserve, gesetzliche Mindestleistung) = success_rate-dominiert
- Weiches Ziel (Reisefonds, opportunistisch) = funded_ratio-dominiert
- Hybrid mit hardness-abhaengigem alpha:
    Score = alpha * success_rate + (1 - alpha) * funded_ratio_pct
    alpha_hart = 0.8, alpha_primaer = 0.5, alpha_opportunistisch = 0.2

B5.1 _compute_goal_score zentrale Formel
B5.2 hardness=hart -> success_rate dominiert
B5.3 hardness=opportunistisch -> funded dominiert
B5.4 Konsistenz zwischen deterministisch und MC
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.portfolio_engine import _compute_goal_score


# ============================================================================
# B5.1 - Zentrale Funktion existiert + funktioniert
# ============================================================================

def test_b5_compute_goal_score_basic():
    """Score = 0.5 * 100 + 0.5 * 100 = 100 fuer perfekt erreichtes primaeres Ziel."""
    score = _compute_goal_score(success_rate_pct=100, funded_ratio_pct=100, hardness_key="primaer")
    assert score == 100


def test_b5_compute_goal_score_zero():
    """Score = 0 wenn weder success noch funded."""
    score = _compute_goal_score(success_rate_pct=0, funded_ratio_pct=0, hardness_key="primaer")
    assert score == 0


def test_b5_compute_goal_score_clamps_funded_above_100():
    """funded_ratio_pct > 100 wird auf 100 geclampt (Ueber-Erfuellung zaehlt nicht doppelt)."""
    score = _compute_goal_score(success_rate_pct=100, funded_ratio_pct=200, hardness_key="primaer")
    assert score == 100


def test_b5_compute_goal_score_clamps_negative_funded():
    """funded_ratio_pct < 0 wird auf 0 geclampt."""
    score = _compute_goal_score(success_rate_pct=0, funded_ratio_pct=-50, hardness_key="primaer")
    assert score == 0


# ============================================================================
# B5.2 - hardness=hart: success_rate dominiert (alpha=0.8)
# ============================================================================

def test_b5_hard_goal_success_dominant():
    """Hartes Ziel: 90% success, 50% funded -> alpha=0.8 -> 0.8*90 + 0.2*50 = 82."""
    score = _compute_goal_score(success_rate_pct=90, funded_ratio_pct=50, hardness_key="hart")
    assert score == 82


def test_b5_hard_goal_low_success_penalized():
    """Hartes Ziel mit 30% success und 100% funded -> 0.8*30 + 0.2*100 = 44."""
    score = _compute_goal_score(success_rate_pct=30, funded_ratio_pct=100, hardness_key="hart")
    assert score == 44


# ============================================================================
# B5.3 - hardness=opportunistisch: funded dominiert (alpha=0.2)
# ============================================================================

def test_b5_opportunistic_funded_dominant():
    """Opportunistisches Ziel: 30% success, 80% funded -> 0.2*30 + 0.8*80 = 70."""
    score = _compute_goal_score(success_rate_pct=30, funded_ratio_pct=80, hardness_key="opportunistisch")
    assert score == 70


def test_b5_opportunistic_high_funded_high_score():
    """Opportunistisch mit 0% success, 90% funded -> 0.2*0 + 0.8*90 = 72."""
    score = _compute_goal_score(success_rate_pct=0, funded_ratio_pct=90, hardness_key="opportunistisch")
    assert score == 72


# ============================================================================
# B5.4 - Primaer: balanciert (alpha=0.5)
# ============================================================================

def test_b5_primary_balanced():
    """Primaer: 60% success, 80% funded -> 0.5*60 + 0.5*80 = 70."""
    score = _compute_goal_score(success_rate_pct=60, funded_ratio_pct=80, hardness_key="primaer")
    assert score == 70


# ============================================================================
# B5.5 - Unbekannte hardness fallback
# ============================================================================

def test_b5_unknown_hardness_falls_back_to_primary():
    """Unbekannter hardness_key -> primaer (alpha=0.5) als sicherer Default."""
    score = _compute_goal_score(success_rate_pct=80, funded_ratio_pct=60, hardness_key="unbekannt")
    expected = int(round(0.5 * 80 + 0.5 * 60))
    assert score == expected


# ============================================================================
# B5.6 - Score immer in [0, 100]
# ============================================================================

@pytest.mark.parametrize("success,funded,hardness", [
    (100, 100, "hart"),
    (100, 100, "primaer"),
    (100, 100, "opportunistisch"),
    (0, 0, "hart"),
    (0, 0, "primaer"),
    (0, 0, "opportunistisch"),
    (50, 50, "hart"),
    (50, 50, "primaer"),
    (50, 50, "opportunistisch"),
    (200, -50, "hart"),    # extreme out-of-range
    (-50, 200, "opportunistisch"),
])
def test_b5_score_in_zero_hundred(success, funded, hardness):
    score = _compute_goal_score(
        success_rate_pct=success, funded_ratio_pct=funded, hardness_key=hardness
    )
    assert 0 <= score <= 100, f"score={score} outside [0,100]"
