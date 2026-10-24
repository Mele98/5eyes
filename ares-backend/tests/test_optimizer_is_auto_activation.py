"""Sprint P1 (2026-06-06): Importance-Sampling Auto-Aktivierung im Solver.

Verifiziert die End-to-End-Verdrahtung der IS-Auto-Decision-Logik:
- decide_is_for_context entscheidet richtig fuer (score_x10, goals, retired)
- build_optimizer_context setzt context.scenario_weights iff IS aktiv
- chance_constraint_penalty respektiert weights bei der Probability-Berechnung
- Cache speichert STD und IS getrennt
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.importance_sampling import (
    decide_is_for_context,
    should_auto_enable_is,
)


# ---------------------------------------------------------------------------
# Helpers (parallel zu tests/test_optimizer_context.py)
# ---------------------------------------------------------------------------

def _cma(**overrides):
    base = {
        "id": "cma-p1",
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


def _goal(
    *,
    goal_id: str = "goal-p1",
    label: str = "Test-Ziel",
    hardness: str = "Primär",
    goal_type: str = "Vermögensziel",
):
    today = date.today()
    return SimpleNamespace(
        id=goal_id, label=label, goal_type=goal_type,
        target_amount_rappen=1_200_000_00,
        target_wealth_rappen=1_200_000_00, target_return_bps=None,
        horizon_years=None,
        start_date=today.isoformat(),
        target_date=(today + timedelta(days=365 * 8)).isoformat(),
        is_ongoing=0, frequency="jährlich",
        hardness=hardness, rank=1, weight_bps=5000, value_mode="real",
    )


def _goal_liability(
    *,
    goal_id: str = "g_test",
    label: str = "Test",
    target_kind: str = "wealth_at_t",
    target_year_index: int = 5,
    target_amount_rappen: int = 1_200_000_00,
    weight_bps: int = 10000,
    hardness_key: str = "primaer",
    horizon: int = 10,
) -> GoalLiability:
    return GoalLiability(
        goal_id=goal_id, label=label, goal_type="Vermögensziel",
        target_kind=target_kind,
        target_amount_rappen=int(target_amount_rappen),
        target_year_index=int(target_year_index),
        liability_path_rappen=[0] * horizon,
        hardness_key=hardness_key, weight_bps=weight_bps,
    )


# ---------------------------------------------------------------------------
# Unit-Tests fuer should_auto_enable_is
# ---------------------------------------------------------------------------

def test_auto_enable_konservatives_profil_triggert_is():
    ok, reason = should_auto_enable_is(
        score_x10=20, has_hart_goal=False, is_retired=False,
    )
    assert ok is True
    assert "konservativ" in reason.lower()


def test_auto_enable_decumulation_triggert_is():
    ok, reason = should_auto_enable_is(
        score_x10=70, has_hart_goal=False, is_retired=True,
    )
    assert ok is True
    assert "decumulation" in reason.lower() or "sequence" in reason.lower()


def test_auto_enable_hart_goal_triggert_is():
    ok, reason = should_auto_enable_is(
        score_x10=80, has_hart_goal=True, is_retired=False,
    )
    assert ok is True
    assert "hart" in reason.lower() or "ziel" in reason.lower()


def test_auto_enable_aggressiv_wachstum_kein_is():
    ok, reason = should_auto_enable_is(
        score_x10=80, has_hart_goal=False, is_retired=False,
    )
    assert ok is False
    assert "standard" in reason.lower()


def test_auto_enable_kombinierte_trigger_listet_alle():
    ok, reason = should_auto_enable_is(
        score_x10=15, has_hart_goal=True, is_retired=True,
    )
    assert ok is True
    assert "konservativ" in reason.lower()
    assert "decumulation" in reason.lower() or "sequence" in reason.lower()
    assert "hart" in reason.lower() or "ziel" in reason.lower()


def test_auto_enable_threshold_grenze_eingeschlossen():
    ok, _ = should_auto_enable_is(
        score_x10=30, has_hart_goal=False, is_retired=False,
    )
    assert ok is True


def test_auto_enable_threshold_grenze_plus_eins_inaktiv():
    ok, _ = should_auto_enable_is(
        score_x10=31, has_hart_goal=False, is_retired=False,
    )
    assert ok is False


# ---------------------------------------------------------------------------
# decide_is_for_context — respektiert Settings
# ---------------------------------------------------------------------------

def test_decide_force_on_via_setting(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", True, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    ok, reason = decide_is_for_context(
        score_x10=99, has_hart_goal=False, is_retired=False,
    )
    assert ok is True
    assert "force-on" in reason.lower()


def test_decide_auto_disabled_und_no_force_kein_is(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", False, raising=False)
    ok, reason = decide_is_for_context(
        score_x10=15, has_hart_goal=True, is_retired=True,
    )
    assert ok is False
    assert "disabled" in reason.lower() or "not set" in reason.lower()


def test_decide_auto_enable_default_true(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    ok, _ = decide_is_for_context(
        score_x10=20, has_hart_goal=False, is_retired=False,
    )
    assert ok is True


# ---------------------------------------------------------------------------
# End-to-End: build_optimizer_context setzt scenario_weights
# ---------------------------------------------------------------------------

def test_build_context_konservativ_aktiviert_is(monkeypatch):
    """Konservativer Score → IS aktiv → scenario_weights gesetzt."""
    from config import settings
    from services.optimizer.solver import build_optimizer_context
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    # The growth-profile fixture has a 45% equity floor and cannot satisfy a
    # 20% risky cap. Use feasible bands so this test isolates IS activation.
    house = _house_matrix()
    house.equity_min_bps = 0
    house.bonds_min_bps = 0
    house.real_estate_min_bps = 0
    house.alt_min_bps = 0
    house.liq_max_bps = 8000
    ctx = build_optimizer_context(
        cma=_cma(id="cma-konservativ-p1"),
        goals=[_goal()],
        house_matrix_row=house,
        score_x10=20,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 11,
        horizon_years=10,
        n_paths=200,
        seed=42,
    )
    assert ctx.scenario_weights is not None
    assert ctx.scenario_weights.shape == (200,)
    assert not np.allclose(ctx.scenario_weights, 1.0)


def test_build_context_aggressiv_ohne_hart_kein_is(monkeypatch):
    from config import settings
    from services.optimizer.solver import build_optimizer_context
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    ctx = build_optimizer_context(
        cma=_cma(id="cma-aggressiv-p1"),
        goals=[_goal(hardness="Opportunistisch")],
        house_matrix_row=_house_matrix(),
        score_x10=85,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 11,
        horizon_years=10,
        n_paths=200,
        seed=42,
    )
    assert ctx.scenario_weights is None


def test_build_context_hart_goal_aktiviert_is(monkeypatch):
    from config import settings
    from services.optimizer.solver import build_optimizer_context
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    ctx = build_optimizer_context(
        cma=_cma(id="cma-hart-p1"),
        goals=[_goal(hardness="Hart")],
        house_matrix_row=_house_matrix(),
        score_x10=85,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 11,
        horizon_years=10,
        n_paths=200,
        seed=42,
    )
    assert ctx.scenario_weights is not None


def test_build_context_decumulation_aktiviert_is(monkeypatch):
    from config import settings
    from services.optimizer.solver import build_optimizer_context
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    ctx = build_optimizer_context(
        cma=_cma(id="cma-pensionaer-p1"),
        goals=[_goal(hardness="Primär")],
        house_matrix_row=_house_matrix(),
        score_x10=85,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 11,
        horizon_years=10,
        n_paths=200,
        seed=42,
        is_retired=True,
    )
    assert ctx.scenario_weights is not None


# ---------------------------------------------------------------------------
# Chance-Constraint-Penalty respektiert weights
# ---------------------------------------------------------------------------

def test_chance_constraint_weighted_vs_unweighted_differ():
    """Nicht-triviale Weights muessen Probability beeinflussen."""
    from services.optimizer.objective import chance_constraint_penalty

    rng = np.random.default_rng(42)
    n_paths = 500
    horizon = 10
    wealth_paths = 1_000_000_00 * np.exp(
        rng.standard_normal((n_paths, horizon)) * 0.15
    ).cumprod(axis=1)
    goal = _goal_liability(
        target_amount_rappen=int(1_200_000_00),
        target_year_index=horizon - 1,
        horizon=horizon,
        hardness_key="hart",
    )
    nontrivial_weights = np.exp(rng.standard_normal(n_paths) * 0.5)
    _, ach_unweighted = chance_constraint_penalty(
        wealth_paths, [goal], 1_000_000_00,
    )
    _, ach_weighted = chance_constraint_penalty(
        wealth_paths, [goal], 1_000_000_00,
        weights=nontrivial_weights,
    )
    assert ach_unweighted[0]["goal_id"] == ach_weighted[0]["goal_id"]
    assert ach_unweighted[0]["probability"] != ach_weighted[0]["probability"]


def test_chance_constraint_weighted_returns_uniform_when_weights_all_one():
    """Backwards-Compat: weights=ones liefert identische Probability."""
    from services.optimizer.objective import chance_constraint_penalty

    rng = np.random.default_rng(7)
    n_paths = 200
    horizon = 5
    wealth_paths = 1_000_000_00 * np.exp(
        rng.standard_normal((n_paths, horizon)) * 0.1
    ).cumprod(axis=1)
    goal = _goal_liability(
        target_amount_rappen=int(1_100_000_00),
        target_year_index=horizon - 1,
        horizon=horizon,
    )
    _, ach_un = chance_constraint_penalty(wealth_paths, [goal], 1_000_000_00)
    _, ach_w = chance_constraint_penalty(
        wealth_paths, [goal], 1_000_000_00, weights=np.ones(n_paths),
    )
    assert ach_un[0]["probability"] == pytest.approx(ach_w[0]["probability"], abs=1e-9)


def test_chance_constraint_weights_negative_sum_raises():
    from services.optimizer.objective import chance_constraint_penalty
    wealth_paths = np.ones((10, 5)) * 1_000_000_00
    goal = _goal_liability(
        target_amount_rappen=int(900_000_00), target_year_index=4, horizon=5,
    )
    with pytest.raises(ValueError, match="Sum-of-weights"):
        chance_constraint_penalty(
            wealth_paths, [goal], 1_000_000_00, weights=np.zeros(10),
        )


def test_chance_constraint_weights_wrong_shape_raises():
    from services.optimizer.objective import chance_constraint_penalty
    wealth_paths = np.ones((10, 5)) * 1_000_000_00
    goal = _goal_liability(
        target_amount_rappen=int(900_000_00), target_year_index=4, horizon=5,
    )
    with pytest.raises(ValueError, match="weights.shape"):
        chance_constraint_penalty(
            wealth_paths, [goal], 1_000_000_00, weights=np.ones(99),
        )


# ---------------------------------------------------------------------------
# Cache separiert STD und IS
# ---------------------------------------------------------------------------

def test_cache_std_vs_is_have_distinct_slots():
    from services.optimizer.scenario_cache import (
        ScenarioCache,
        build_scenario_paths_cached,
        build_scenario_paths_with_weights_cached,
    )
    from services.optimizer.scenario_engine import ScenarioInputs

    inputs = ScenarioInputs(
        mu_bps=np.array([50, 200, 600, 700, 400], dtype=np.float64),
        sigma_bps=np.array([100, 500, 1800, 2000, 1500], dtype=np.float64),
        skew_bps=np.zeros(5), excess_kurt_bps=np.zeros(5), cholesky=np.eye(5),
    )
    cache = ScenarioCache(max_size=8)
    std_paths = build_scenario_paths_cached(
        inputs, cma_id="t1", horizon_years=5, n_paths=100, seed=1, cache=cache,
    )
    shift = np.array([0.0, 0.0, -0.5, -0.5, 0.0])
    is_paths, is_weights = build_scenario_paths_with_weights_cached(
        inputs, cma_id="t1", horizon_years=5, n_paths=100, seed=1,
        shift_vector=shift, cache=cache,
    )
    assert not np.allclose(std_paths, is_paths), (
        "IS-Pfade waren identisch zu STD — IS hat keinen Effekt"
    )
    assert not np.allclose(is_weights, 1.0)
    assert len(cache) == 2


def test_cache_is_zero_shift_falls_back_to_std():
    from services.optimizer.scenario_cache import (
        ScenarioCache,
        build_scenario_paths_with_weights_cached,
    )
    from services.optimizer.scenario_engine import ScenarioInputs

    inputs = ScenarioInputs(
        mu_bps=np.array([50, 200, 600, 700, 400], dtype=np.float64),
        sigma_bps=np.array([100, 500, 1800, 2000, 1500], dtype=np.float64),
        skew_bps=np.zeros(5), excess_kurt_bps=np.zeros(5), cholesky=np.eye(5),
    )
    cache = ScenarioCache(max_size=4)
    paths, weights = build_scenario_paths_with_weights_cached(
        inputs, cma_id="t2", horizon_years=3, n_paths=50, seed=99,
        shift_vector=np.zeros(5), cache=cache,
    )
    assert weights.shape == (50,)
    assert np.allclose(weights, 1.0)


# ---------------------------------------------------------------------------
# Solver End-to-End mit IS-Aktivierung
# ---------------------------------------------------------------------------

def test_solver_reasoning_dokumentiert_is_status(monkeypatch):
    """OptimizerResult.reasoning muss IS-Status nennen — Audit-Trail-Pflicht."""
    from config import settings
    from services.optimizer.solver import run_solver
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    result = run_solver(
        cma=_cma(id="cma-reasoning-p1"),
        goals=[_goal(hardness="Hart")],
        house_matrix_row=_house_matrix(),
        score_x10=85,  # aggressiv, hart-Goal trumpft
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 11,
        horizon_years=10,
        n_paths=200,
        seed=42,
    )
    reasoning_text = " ".join(result.reasoning).lower()
    assert "importance sampling" in reasoning_text
    assert "aktiv" in reasoning_text or "inaktiv" in reasoning_text
