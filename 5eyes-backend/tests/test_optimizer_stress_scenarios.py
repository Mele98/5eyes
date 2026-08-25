"""Tests fuer services/optimizer/stress_scenarios.py.

Verifiziert:
- 3 historische Stress-Pfade definiert (1929, 2008, 2020)
- Pad-Funktion: kurzer Stress + langer Horizon -> Padding mit Faktor 1.0
- evaluate_stress_scenarios berechnet end_wealth, min_year_wealth, max_drawdown
- 100% Cash-Allocation hat keinen Drawdown in Stress-Tests
- 100% Equity-Allocation hat hohen Drawdown in 1929-Szenario
- stress_results_to_dict liefert JSON-serialisierbares Format
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.scenario_engine import BUCKET_ORDER, N_BUCKETS
from services.optimizer.stress_scenarios import (
    STRESS_SCENARIOS,
    StressResult,
    _pad_stress_to_horizon,
    evaluate_stress_scenarios,
    stress_results_to_dict,
)


# ============================================================================
# Definitionen
# ============================================================================


def test_three_canonical_scenarios_defined():
    """Spec: 1929 Great Depression, 2008 Financial Crisis, 2020 COVID."""
    assert "great_depression_1929" in STRESS_SCENARIOS
    assert "financial_crisis_2008" in STRESS_SCENARIOS
    assert "covid_inflation_2020_2022" in STRESS_SCENARIOS


def test_each_scenario_has_correct_shape():
    for name, arr in STRESS_SCENARIOS.items():
        assert arr.ndim == 2, f"{name} should be 2D"
        assert arr.shape[1] == N_BUCKETS, f"{name} should have {N_BUCKETS} buckets"
        assert arr.shape[0] >= 1, f"{name} should have at least 1 year"


def test_great_depression_equities_severe_loss_year_1():
    """1929 Y1: Aktien -45% (= Faktor 0.55)."""
    eq_idx = BUCKET_ORDER.index("equities")
    assert STRESS_SCENARIOS["great_depression_1929"][0, eq_idx] < 0.6


def test_2008_equities_v_shape_recovery():
    """2008: Y1 -38%, Y2 +26%."""
    eq_idx = BUCKET_ORDER.index("equities")
    sc = STRESS_SCENARIOS["financial_crisis_2008"]
    assert sc[0, eq_idx] < 0.7  # Y1 negativ
    assert sc[1, eq_idx] > 1.15  # Y2 stark positiv


def test_2022_bonds_lose_value():
    """2022 Inflation/Zins: Bonds -15% (= 0.85). Klassische Risk-Off-Annahme
    falsch in Zinsschock-Szenario."""
    bonds_idx = BUCKET_ORDER.index("bonds")
    sc = STRESS_SCENARIOS["covid_inflation_2020_2022"]
    # Y3 ist 2022
    assert sc[2, bonds_idx] < 0.90


# ============================================================================
# Pad
# ============================================================================


def test_pad_to_longer_horizon_appends_neutral_returns():
    short = np.array([[0.5, 1.0, 1.0, 1.0, 1.0]], dtype=np.float64)
    padded = _pad_stress_to_horizon(short, horizon_years=5)
    assert padded.shape == (5, N_BUCKETS)
    # Erstes Jahr aus Stress
    assert padded[0, 0] == 0.5
    # Spaeter: Faktor 1.0 (= 0% Return)
    assert np.allclose(padded[1:], 1.0)


def test_pad_to_shorter_horizon_truncates():
    long_path = np.full((10, N_BUCKETS), 0.95, dtype=np.float64)
    padded = _pad_stress_to_horizon(long_path, horizon_years=3)
    assert padded.shape == (3, N_BUCKETS)


def test_pad_to_equal_horizon_returns_copy():
    same = np.full((5, N_BUCKETS), 0.95, dtype=np.float64)
    padded = _pad_stress_to_horizon(same, horizon_years=5)
    assert padded.shape == (5, N_BUCKETS)
    assert not np.shares_memory(padded, same)  # ist Copy


# ============================================================================
# evaluate_stress_scenarios
# ============================================================================


def test_100_pct_cash_has_no_drawdown_in_any_scenario():
    """Liquiditaet ueberlebt jede Krise (Faktor ~1.0)."""
    weights = np.array([0, 0, 0, 0, 1.0])  # all liquidity
    results = evaluate_stress_scenarios(
        weights=weights,
        initial_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 10,
        liability_path_rappen=None,
        horizon_years=10,
    )
    for name, r in results.items():
        assert r.max_drawdown_bps <= 100, (
            f"{name}: Liquidity should have ~0 drawdown, got {r.max_drawdown_bps}bps"
        )


def test_100_pct_equity_has_severe_drawdown_in_1929():
    """100% Aktien -> in 1929-Szenario massive Verluste."""
    weights = np.array([1.0, 0, 0, 0, 0])  # all equities
    results = evaluate_stress_scenarios(
        weights=weights,
        initial_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 5,
        liability_path_rappen=None,
        horizon_years=5,
    )
    gd = results["great_depression_1929"]
    # 100% Aktien Y1=-45%, Y2=-25% -> kumuliert ~-58%, also drawdown >= 50%
    assert gd.max_drawdown_bps > 5000, (
        f"100% equity in 1929 should drawdown >50%, got {gd.max_drawdown_bps}bps"
    )


def test_evaluate_returns_stress_result_per_scenario():
    weights = np.array([0.5, 0.3, 0.05, 0.05, 0.10])
    results = evaluate_stress_scenarios(
        weights=weights,
        initial_wealth_rappen=500_000_00,
        cashflow_series_rappen=[0] * 5,
        liability_path_rappen=None,
        horizon_years=5,
    )
    assert len(results) == len(STRESS_SCENARIOS)
    for name, r in results.items():
        assert isinstance(r, StressResult)
        assert r.scenario_name == name
        # End-Wealth muss != initial sein bei Stress
        assert r.end_wealth_rappen != 500_000_00


def test_evaluate_with_liability_subtracts_outflows():
    """Mit Liability 100k in Y2 muss min_year_wealth deutlich unter initial sein.

    Annaherung: 100% Liquiditaet (kleine positive Returns ~1%/J),
    initial 500k, Liability 100k in Y2 -> min wealth ~ 410k bis 420k
    (je nach exakter Liq-Stress-Annahme im Szenario). Erwarten: <=440k um
    Drawdown durch Liability klar zu zeigen.
    """
    weights = np.array([0, 0, 0, 0, 1.0])  # all liquidity
    results = evaluate_stress_scenarios(
        weights=weights,
        initial_wealth_rappen=500_000_00,
        cashflow_series_rappen=[0, 0, 0, 0, 0],
        liability_path_rappen=[0, 100_000_00, 0, 0, 0],
        horizon_years=5,
    )
    for r in results.values():
        # Liability hat klar Effekt: min < initial - 60k (= 440k)
        assert r.min_year_wealth_rappen <= 440_000_00, (
            f"{r.scenario_name}: Liability nicht im Min wealth sichtbar "
            f"({r.min_year_wealth_rappen / 100:,.0f} CHF)"
        )
        # Aber nicht weniger als initial - liability - 5% Liquiditaets-Drift = 395k
        assert r.min_year_wealth_rappen >= 395_000_00, (
            f"{r.scenario_name}: Min wealth zu tief "
            f"({r.min_year_wealth_rappen / 100:,.0f} CHF)"
        )


def test_2008_v_shape_recovery_partial_makeback():
    """2008 V-shape: 100% equity verliert zuerst stark, erholt sich stark."""
    weights = np.array([1.0, 0, 0, 0, 0])
    results = evaluate_stress_scenarios(
        weights=weights,
        initial_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0, 0, 0],
        liability_path_rappen=None,
        horizon_years=3,
    )
    crisis = results["financial_crisis_2008"]
    # End-Wealth = 1M * 0.62 * 1.25 * 1.10 = 852'500
    # NICHT zurueck auf 1M aber besser als min
    assert 700_000_00 < crisis.end_wealth_rappen < 900_000_00
    # Min Wealth = 1M * 0.62 = 620'000 (nach Y1)
    assert crisis.min_year_wealth_rappen < 700_000_00


# ============================================================================
# JSON-Serialisierung
# ============================================================================


def test_stress_results_to_dict_is_json_serializable():
    """Output muss in JSON dump funktionieren (alle Werte primitives)."""
    import json
    weights = np.array([0.5, 0.3, 0.05, 0.05, 0.10])
    results = evaluate_stress_scenarios(
        weights=weights,
        initial_wealth_rappen=500_000_00,
        cashflow_series_rappen=[0] * 5,
        liability_path_rappen=None,
        horizon_years=5,
    )
    serializable = stress_results_to_dict(results)
    json_str = json.dumps(serializable)  # Wirft wenn nicht serializable
    assert "great_depression_1929" in json_str
    parsed = json.loads(json_str)
    for name in STRESS_SCENARIOS:
        assert name in parsed
        assert "end_wealth_rappen" in parsed[name]
        assert "max_drawdown_bps" in parsed[name]


def test_solver_attaches_stress_evaluations_when_converged():
    """End-to-End: Solver-Result hat stress_evaluations gefuellt."""
    from types import SimpleNamespace
    from services.optimizer.solver import run_solver

    cma = SimpleNamespace(
        id="cma-stress-test",
        bonds_chf_ig_return_bps=220, bonds_chf_ig_vol_bps=350,
        bonds_fx_hedged_return_bps=220, bonds_fx_hedged_vol_bps=430,
        equity_ch_return_bps=620, equity_ch_vol_bps=1450,
        equity_intl_return_bps=700, equity_intl_vol_bps=1600,
        real_estate_ch_return_bps=450, real_estate_ch_vol_bps=820,
        alternatives_gold_return_bps=300, alternatives_gold_vol_bps=1200,
        liquidity_return_bps=80, liquidity_vol_bps=20,
        correlation_matrix_json="",
        equities_skewness_bps=0, equities_excess_kurt_bps=0,
        bonds_skewness_bps=0, bonds_excess_kurt_bps=0,
        real_estate_skewness_bps=0, real_estate_excess_kurt_bps=0,
        alternatives_skewness_bps=0, alternatives_excess_kurt_bps=0,
        liquidity_skewness_bps=0, liquidity_excess_kurt_bps=0,
    )
    house_matrix = SimpleNamespace(
        equity_min_bps=4500, equity_max_bps=7000,
        bonds_min_bps=2000, bonds_max_bps=4500,
        real_estate_min_bps=0, real_estate_max_bps=1500,
        alt_min_bps=0, alt_max_bps=1000,
        liq_min_bps=200, liq_max_bps=2000,
    )
    result = run_solver(
        cma=cma, goals=[], house_matrix_row=house_matrix, score_x10=70,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[0] * 5,
        horizon_years=5, n_paths=100, seed=42,
    )
    if result.status == "converged":
        assert result.stress_evaluations is not None
        for name in STRESS_SCENARIOS:
            assert name in result.stress_evaluations
