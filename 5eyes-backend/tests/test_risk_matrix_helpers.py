"""Sprint U-105 (2026-06-06): Coverage-Lifts fuer services/risk_matrix.py.

Pure-Funktions-Tests ohne DB-Fixtures, damit die Coverage des Moduls
von 74% in Richtung 95%+ steigt.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.risk_matrix import (
    RiskBudgetExceeded,
    _hardness_key,
    assert_risk_budget_ok,
    bucket_risky_fraction_bps_from_building_blocks,
    classify_limiting_factor,
    compute_portfolio_risky_fraction_bps,
    score_bucket_from_assessment,
)


# ---------------------------------------------------------------------------
# score_bucket_from_assessment
# ---------------------------------------------------------------------------

def test_score_uses_override_when_overridden():
    a = SimpleNamespace(is_overridden=1, override_score_x10=70, final_score_x10=40)
    assert score_bucket_from_assessment(a) == 7


def test_score_falls_back_to_final_when_not_overridden():
    a = SimpleNamespace(is_overridden=0, override_score_x10=70, final_score_x10=40)
    assert score_bucket_from_assessment(a) == 4


def test_score_falls_back_to_final_when_override_none():
    a = SimpleNamespace(is_overridden=1, override_score_x10=None, final_score_x10=80)
    assert score_bucket_from_assessment(a) == 8


def test_score_raises_when_both_scores_none():
    a = SimpleNamespace(is_overridden=0, override_score_x10=None, final_score_x10=None)
    with pytest.raises(ValueError, match="Risikoprofil-Score"):
        score_bucket_from_assessment(a)


def test_score_clamps_to_1_minimum():
    a = SimpleNamespace(is_overridden=0, override_score_x10=None, final_score_x10=5)
    assert score_bucket_from_assessment(a) == 1


def test_score_clamps_to_10_maximum():
    a = SimpleNamespace(is_overridden=0, override_score_x10=None, final_score_x10=120)
    assert score_bucket_from_assessment(a) == 10


# ---------------------------------------------------------------------------
# compute_portfolio_risky_fraction_bps
# ---------------------------------------------------------------------------

def test_risky_fraction_empty_allocation_zero():
    assert compute_portfolio_risky_fraction_bps({}, []) == 0


def test_risky_fraction_pure_liquidity_zero():
    # Mit leeren building_blocks ist die rf_by_bucket aus
    # bucket_risky_fractions_from_building_blocks komplett 0 -> Resultat 0.
    alloc = {"liquidity": 10000, "equities": 0, "bonds": 0, "real_estate": 0, "alternatives": 0}
    assert compute_portfolio_risky_fraction_bps(alloc, []) == 0


# ---------------------------------------------------------------------------
# bucket_risky_fraction_bps_from_building_blocks
# ---------------------------------------------------------------------------

def test_bucket_rf_empty_building_blocks_uses_defaults():
    """Ohne BuildingBlocks faellt jeder Bucket auf DEFAULT_BUCKET_RISKY_FRACTION."""
    result = bucket_risky_fraction_bps_from_building_blocks([])
    # Liquidity ist immer 0% risky (defensiv-Default)
    assert result["liquidity"] == 0
    # Equities sind im Default ~100% risky -> > 0
    assert result["equities"] > 0
    # Alle bps-Werte im gueltigen [0, 10000] Bereich
    for bucket in ("equities", "bonds", "real_estate", "alternatives", "liquidity"):
        assert 0 <= result[bucket] <= 10000


# ---------------------------------------------------------------------------
# assert_risk_budget_ok / RiskBudgetExceeded
# ---------------------------------------------------------------------------

def test_assert_risk_budget_pass_when_under_max():
    assert_risk_budget_ok(realized_risky_bps=5000, max_risky_bps=6000)


def test_assert_risk_budget_pass_when_equal_to_max():
    assert_risk_budget_ok(realized_risky_bps=6000, max_risky_bps=6000)


def test_assert_risk_budget_raises_when_over():
    with pytest.raises(RiskBudgetExceeded) as exc:
        assert_risk_budget_ok(realized_risky_bps=6500, max_risky_bps=6000)
    assert exc.value.realized_bps == 6500
    assert exc.value.max_bps == 6000


def test_assert_risk_budget_slack_allows_overshoot():
    """Mit slack_bps=200 erlaubt 6200 trotz max=6000."""
    assert_risk_budget_ok(realized_risky_bps=6200, max_risky_bps=6000, slack_bps=200)


def test_assert_risk_budget_slack_still_raises_above_threshold():
    with pytest.raises(RiskBudgetExceeded):
        assert_risk_budget_ok(realized_risky_bps=6300, max_risky_bps=6000, slack_bps=200)


def test_risk_budget_exceeded_message_format():
    err = RiskBudgetExceeded(6500, 6000)
    assert "6500" in str(err)
    assert "6000" in str(err)


# ---------------------------------------------------------------------------
# _hardness_key
# ---------------------------------------------------------------------------

def test_hardness_key_normalizes_hart():
    assert _hardness_key("Hart") == "hart"
    assert _hardness_key("hard") == "hart"
    assert _hardness_key("HART") == "hart"


def test_hardness_key_normalizes_primaer():
    assert _hardness_key("Primär") == "primär"
    assert _hardness_key("primaer") == "primär"
    assert _hardness_key("primary") == "primär"


def test_hardness_key_normalizes_opportunistisch():
    assert _hardness_key("Opportunistisch") == "opportunistisch"
    assert _hardness_key("opportunistic") == "opportunistisch"
    assert _hardness_key("opp") == "opportunistisch"


def test_hardness_key_none_yields_empty():
    assert _hardness_key(None) == ""


def test_hardness_key_unknown_preserves_lowercased():
    assert _hardness_key("Sonstiges") == "sonstiges"


# ---------------------------------------------------------------------------
# classify_limiting_factor
# ---------------------------------------------------------------------------

def _base_kwargs():
    return dict(
        allocation_bps={"liquidity": 1000},
        risky_fraction=5000,
        max_risky_fraction=6000,
        min_liquidity_bps=500,
        bands={},
        achievability=[],
        optimization_status="converged",
    )


def test_classify_solver_konvergenz_when_fallback():
    kwargs = _base_kwargs()
    kwargs["optimization_status"] = "fallback_house_matrix"
    assert classify_limiting_factor(**kwargs) == "solver_konvergenz"


def test_classify_zielkonflikt_when_2_hart_nicht_erreicht():
    kwargs = _base_kwargs()
    kwargs["achievability"] = [
        {"status": "nicht_erreichbar", "hardness": "hart"},
        {"status": "nicht_erreichbar", "hardness": "Primaer"},
    ]
    assert classify_limiting_factor(**kwargs) == "zielkonflikt"


def test_classify_risikoprofil_when_1_unreachable_and_near_max():
    kwargs = _base_kwargs()
    kwargs["achievability"] = [{"status": "nicht_erreichbar", "hardness": "hart"}]
    kwargs["risky_fraction"] = 5960  # >= max(6000) - 50
    assert classify_limiting_factor(**kwargs) == "risikoprofil"


def test_classify_liquiditaetsreserve_when_at_min():
    kwargs = _base_kwargs()
    kwargs["allocation_bps"] = {"liquidity": 500}  # = min_liquidity_bps + 1 - 1
    kwargs["min_liquidity_bps"] = 500
    assert classify_limiting_factor(**kwargs) == "liquiditaetsreserve"


def test_classify_bandbreite_default():
    kwargs = _base_kwargs()
    kwargs["allocation_bps"] = {"liquidity": 9000}  # > min
    assert classify_limiting_factor(**kwargs) == "bandbreite"


def test_classify_ignores_unreachable_when_opportunistisch():
    """Opportunistische Goals werden nicht zur Zielkonflikt-Erkennung gezaehlt."""
    kwargs = _base_kwargs()
    kwargs["achievability"] = [
        {"status": "nicht_erreichbar", "hardness": "Opportunistisch"},
        {"status": "nicht_erreichbar", "hardness": "Opportunistisch"},
    ]
    # Trotz 2 nicht_erreichbar -> nicht 'zielkonflikt' weil opportunistisch
    assert classify_limiting_factor(**kwargs) != "zielkonflikt"
