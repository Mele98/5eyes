"""V3 Sprint 1b Tests: OptimizerContext + evaluate_weights.

Plan §5.2: Wiederverwendbare Evaluation beliebiger Gewichtungen unter denselben
Szenarien, damit Methodenvergleich Apples-to-Apples funktioniert.

Verifiziert:
- build_optimizer_context liefert deterministisch identische Contexts bei
  gleichen Inputs (gleiche scenarios, liabilities, bounds).
- evaluate_weights ist deterministisch fuer gleichen Context + gleiche Gewichte.
- evaluate_weights matcht run_solver.objective_value Apples-to-Apples
  (Plan §8.2 Test).
- evaluate_weights respektiert is_feasible/Bounds.
- Terminal-Wealth p10/p50/p90 sind Integer in Rappen.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.scenario_engine import BUCKET_ORDER
from services.optimizer.solver import (
    OptimizerContext,
    OptimizerEvaluation,
    build_optimizer_context,
    deterministic_seed,
    evaluate_weights,
    run_solver,
)


# ============================================================================
# Fixtures
# ============================================================================


def _cma(**overrides):
    base = {
        "id": "cma-ctx",
        "bonds_chf_ig_return_bps": 220, "bonds_chf_ig_vol_bps": 350,
        "bonds_fx_hedged_return_bps": 220, "bonds_fx_hedged_vol_bps": 430,
        "equity_ch_return_bps": 620, "equity_ch_vol_bps": 1450,
        "equity_intl_return_bps": 700, "equity_intl_vol_bps": 1600,
        "real_estate_ch_return_bps": 450, "real_estate_ch_vol_bps": 820,
        "alternatives_gold_return_bps": 300, "alternatives_gold_vol_bps": 1200,
        "liquidity_return_bps": 80, "liquidity_vol_bps": 20,
        "correlation_matrix_json": "",
        "equities_skewness_bps": -3000, "equities_excess_kurt_bps": 15000,
        "bonds_skewness_bps": 0, "bonds_excess_kurt_bps": 0,
        "real_estate_skewness_bps": 0, "real_estate_excess_kurt_bps": 0,
        "alternatives_skewness_bps": 0, "alternatives_excess_kurt_bps": 0,
        "liquidity_skewness_bps": 0, "liquidity_excess_kurt_bps": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _house_matrix():
    return SimpleNamespace(
        profile_name="Wachstumsorientiert",
        equity_min_bps=4500, equity_max_bps=7000, equity_target_bps=6000,
        bonds_min_bps=2000, bonds_max_bps=4500, bonds_target_bps=3000,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=1000, alt_target_bps=300,
        liq_min_bps=200, liq_max_bps=2000, liq_target_bps=200,
        max_risky_fraction_bps=7500,
    )


def _pension_goal():
    today = date.today()
    return SimpleNamespace(
        id="goal-pension-ctx", label="Pension",
        goal_type="Pensionsausgabe",
        target_amount_rappen=24_000_00,
        target_wealth_rappen=None, target_return_bps=None,
        horizon_years=None,
        start_date=(today + timedelta(days=365 * 5)).isoformat(),
        target_date=(today + timedelta(days=365 * 25)).isoformat(),
        is_ongoing=0, frequency="jährlich",
        hardness="Hart", rank=1, weight_bps=5000,
        value_mode="real",
    )


def _ctx(**overrides):
    base = dict(
        cma=_cma(),
        goals=[_pension_goal()],
        house_matrix_row=_house_matrix(),
        score_x10=70,
        advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[20_000_00] * 10,
        horizon_years=10,
        n_paths=500,  # kleinere n_paths fuer Test-Speed
        seed=4242,
    )
    base.update(overrides)
    return build_optimizer_context(**base)


# ============================================================================
# build_optimizer_context: Determinismus + Inputs
# ============================================================================


def test_build_context_with_explicit_seed_is_deterministic():
    a = _ctx(seed=12345)
    b = _ctx(seed=12345)
    assert a.seed == 12345 and b.seed == 12345
    assert a.cma_id == b.cma_id
    assert a.horizon_years == b.horizon_years
    assert a.n_paths == b.n_paths
    assert a.advisory_wealth_rappen == b.advisory_wealth_rappen
    np.testing.assert_array_equal(a.return_paths, b.return_paths)
    np.testing.assert_array_equal(a.aggregated_liability_path, b.aggregated_liability_path)
    assert a.bounds == b.bounds


def test_build_context_seed_none_uses_deterministic_seed():
    expected = deterministic_seed(
        "cma-ctx",
        "goal-pension-ctx",
        70,
        10,
        500,
    )
    ctx = _ctx(seed=None)
    assert ctx.seed == expected


def test_build_context_different_seeds_produce_different_paths():
    a = _ctx(seed=11111)
    b = _ctx(seed=22222)
    # Probabilistisch: bei 500 Pfaden / 5 Buckets / 10J fast unmoeglich gleich
    assert not np.array_equal(a.return_paths, b.return_paths)


def test_build_context_carries_score_and_risky_fraction_map():
    rf = {"equities": 0.85, "bonds": 0.20, "real_estate": 0.55,
          "alternatives": 0.55, "liquidity": 0.0}
    ctx = _ctx(score_x10=55, risky_fraction_per_bucket=rf)
    assert ctx.score_x10 == 55
    assert ctx.risky_fraction_per_bucket == rf


# ============================================================================
# evaluate_weights: Determinismus + Apples-to-Apples
# ============================================================================


def _hm_default_weights() -> dict[str, int]:
    return {
        "equities": 6000, "bonds": 3000, "real_estate": 500,
        "alternatives": 300, "liquidity": 200,
    }


def test_evaluate_weights_deterministic_for_same_context():
    ctx = _ctx(seed=777)
    weights = _hm_default_weights()
    a = evaluate_weights(ctx, weights)
    b = evaluate_weights(ctx, weights)
    assert a.objective_value == b.objective_value
    assert a.terminal_wealth_p50_rappen == b.terminal_wealth_p50_rappen
    assert a.feasible == b.feasible


def test_evaluate_weights_returns_optimizer_evaluation():
    ctx = _ctx()
    ev = evaluate_weights(ctx, _hm_default_weights())
    assert isinstance(ev, OptimizerEvaluation)
    assert isinstance(ev.weights_bps, dict)
    assert set(ev.weights_bps.keys()) == set(BUCKET_ORDER)
    assert sum(ev.weights_bps.values()) == 10000  # _weights_to_bps_dict normiert
    assert isinstance(ev.objective_value, float)
    assert ev.terminal_wealth_p10_rappen is not None
    assert ev.terminal_wealth_p50_rappen is not None
    assert ev.terminal_wealth_p90_rappen is not None


def test_evaluate_weights_matches_run_solver_objective_for_solver_weights():
    """Plan §8.2: Apples-to-Apples-Test."""
    cma = _cma()
    goals = [_pension_goal()]
    house = _house_matrix()
    seed = 9876
    ctx = build_optimizer_context(
        cma=cma, goals=goals, house_matrix_row=house,
        score_x10=70, advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[20_000_00] * 10,
        horizon_years=10, n_paths=500, seed=seed,
    )
    result = run_solver(
        cma=cma, goals=goals, house_matrix_row=house,
        score_x10=70, advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[20_000_00] * 10,
        horizon_years=10, n_paths=500, seed=seed,
    )
    if result.status == "fallback_house_matrix":
        pytest.skip("Solver fallback in dieser Konfiguration; Apples-to-Apples nicht messbar.")
    evaluation = evaluate_weights(ctx, result.weights_bps)
    assert evaluation.objective_value == pytest.approx(result.objective_value, rel=1e-8)


def test_evaluate_weights_constraint_violations_for_invalid_weights():
    ctx = _ctx()
    bad = {"equities": 9500, "bonds": 0, "real_estate": 0,
           "alternatives": 0, "liquidity": 500}
    ev = evaluate_weights(ctx, bad)
    # Equity > equity_max_bps + Liquidity unter score-cap konkret bricht
    # mind. eine constraint -> feasible=False oder violations nicht-leer.
    assert ev.feasible is False or ev.constraint_violations


def test_evaluate_weights_terminal_wealth_quantiles_are_int_rappen():
    ctx = _ctx()
    ev = evaluate_weights(ctx, _hm_default_weights())
    assert isinstance(ev.terminal_wealth_p10_rappen, int)
    assert isinstance(ev.terminal_wealth_p50_rappen, int)
    assert isinstance(ev.terminal_wealth_p90_rappen, int)
    assert ev.terminal_wealth_p10_rappen <= ev.terminal_wealth_p50_rappen
    assert ev.terminal_wealth_p50_rappen <= ev.terminal_wealth_p90_rappen


def test_evaluate_weights_normalizes_unsummed_input():
    """Wenn Caller nicht exakt 10000 bps liefert, werden die Gewichte normiert."""
    ctx = _ctx()
    raw = {"equities": 600, "bonds": 300, "real_estate": 50,
           "alternatives": 30, "liquidity": 20}  # Summe = 1000 statt 10000
    ev = evaluate_weights(ctx, raw)
    assert sum(ev.weights_bps.values()) == 10000


def test_run_solver_objective_value_matches_evaluate_weights_post_round():
    """run_solver returnt objective post-rounding; externer evaluate_weights
    matcht das exakt (Sprint 1b Praezisions-Garantie)."""
    cma = _cma()
    goals = [_pension_goal()]
    house = _house_matrix()
    seed = 4711
    ctx = build_optimizer_context(
        cma=cma, goals=goals, house_matrix_row=house,
        score_x10=70, advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[20_000_00] * 10,
        horizon_years=10, n_paths=500, seed=seed,
    )
    result = run_solver(
        cma=cma, goals=goals, house_matrix_row=house,
        score_x10=70, advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[20_000_00] * 10,
        horizon_years=10, n_paths=500, seed=seed,
    )
    if result.status == "fallback_house_matrix":
        pytest.skip("Solver fallback; Pruefung nicht anwendbar.")
    ev = evaluate_weights(ctx, result.weights_bps)
    # rel=1e-12 = praktisch bit-identisch (post-rounding kongruent)
    assert ev.objective_value == pytest.approx(result.objective_value, rel=1e-12, abs=1e-12)
