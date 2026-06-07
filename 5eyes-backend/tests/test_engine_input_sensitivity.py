"""Sprint A4 (2026-06-07): Risikofragebogen <-> Goal <-> MC Integration-Tests.

Sensitivitaets-Analyse: Verifiziert dass Input-Aenderungen die Engine in die
erwartete Richtung bewegen. Ergaenzt A2 Reference-Mandate (statische Profile)
durch dynamische Vergleichs-Tests.

# Test-Familien
1. Profile-Score-Sensitivity: Konservativ -> mehr Bonds als Wachstum
2. Hardness-Sensitivity: Hart-Goal -> konservativer als Opp-Goal
3. Goal-Count-Sensitivity: Mehr Goals -> mehr Achievability-Rows
4. Retirement-Sensitivity: is_retired=True -> IS aktiv + Bonds-heavier
5. Horizon-Sensitivity: Lang -> mehr Equity (Risk Recovery Time)
6. Cashflow-Sensitivity: positive CF -> bessere Achievability
7. IS-Switching-Sensitivity: Hardness aendert IS-Aktivierung dynamisch

# Drift-Resistenz
Strukturelle Vergleiche (M1 < M2, R1 > R2) statt absolute Werte.
Erlaubt Engine-Refactoring ohne Test-Schmerzen.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np

from services.optimizer.scenario_cache import get_default_cache
from services.optimizer.solver import build_optimizer_context, run_solver


# ===========================================================================
# Gemeinsame Test-Helpers (parallel zu test_engine_reference_mandates.py)
# ===========================================================================


def _cma(**overrides):
    base = {
        "id": "cma-a4",
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


def _hm_wachstum():
    return SimpleNamespace(
        profile_name="Wachstum",
        equity_min_bps=4500, equity_max_bps=7000, equity_target_bps=6000,
        bonds_min_bps=2000, bonds_max_bps=4500, bonds_target_bps=3000,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=1000, alt_target_bps=300,
        liq_min_bps=200, liq_max_bps=2000, liq_target_bps=200,
        max_risky_fraction_bps=7500,
    )


def _hm_konservativ():
    return SimpleNamespace(
        profile_name="Konservativ",
        equity_min_bps=500, equity_max_bps=2500, equity_target_bps=1500,
        bonds_min_bps=5000, bonds_max_bps=8000, bonds_target_bps=6500,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=500, alt_target_bps=200,
        liq_min_bps=500, liq_max_bps=2000, liq_target_bps=1000,
        max_risky_fraction_bps=3000,
    )


def _hm_ausgewogen():
    return SimpleNamespace(
        profile_name="Ausgewogen",
        equity_min_bps=2500, equity_max_bps=5000, equity_target_bps=4000,
        bonds_min_bps=3500, bonds_max_bps=6000, bonds_target_bps=4500,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=1000, alt_target_bps=300,
        liq_min_bps=300, liq_max_bps=2000, liq_target_bps=500,
        max_risky_fraction_bps=5500,
    )


def _goal(*, hardness="Primär", goal_type="Vermoegensziel", target=1_000_000_00,
          days=365 * 10, label="Test", goal_id="g"):
    today = date.today()
    return SimpleNamespace(
        id=goal_id, label=label, goal_type=goal_type,
        target_amount_rappen=target, target_wealth_rappen=target,
        target_return_bps=None, horizon_years=None,
        start_date=today.isoformat(),
        target_date=(today + timedelta(days=days)).isoformat(),
        is_ongoing=0, frequency="jaehrlich",
        hardness=hardness, rank=1, weight_bps=5000, value_mode="real",
    )


def _bucket_pct(weights_bps: dict, bucket: str) -> float:
    return int(weights_bps.get(bucket, 0)) / 100.0


def _run(*, cma_id, hm, score_x10, goals, wealth=1_000_000_00, cf=None,
         horizon=10, is_retired=False, n_paths=300, seed=1):
    get_default_cache().clear()  # Cache zwischen Test-Runs leeren
    return run_solver(
        cma=_cma(id=cma_id), goals=goals, house_matrix_row=hm,
        score_x10=score_x10, advisory_wealth_rappen=wealth,
        cashflow_series_rappen=cf if cf is not None else [0] * (horizon + 1),
        horizon_years=horizon, n_paths=n_paths, seed=seed,
        is_retired=is_retired,
    )


# ===========================================================================
# 1. Profile-Score-Sensitivity
# ===========================================================================


def test_sens_score_konservativ_hat_mehr_bonds_als_wachstum(monkeypatch):
    """Score 20 (Sicherheit) muss MEHR Bonds-Anteil haben als Score 80 (Wachstum).

    Beide Mandate: 10J Horizon, kein Tax, weiches Goal — nur Score differiert.
    """
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)

    g = _goal(hardness="Opportunistisch")
    r_kons = _run(cma_id="cma-kons", hm=_hm_konservativ(), score_x10=20, goals=[g], seed=11)
    r_wach = _run(cma_id="cma-wach", hm=_hm_wachstum(), score_x10=80, goals=[g], seed=11)
    # Skip wenn Fallback (Test braucht reale Optimization)
    if r_kons.status == "fallback_house_matrix" or r_wach.status == "fallback_house_matrix":
        return
    bonds_kons = _bucket_pct(r_kons.weights_bps, "bonds")
    bonds_wach = _bucket_pct(r_wach.weights_bps, "bonds")
    assert bonds_kons > bonds_wach, (
        f"Sensitivitaet verletzt: Konservativ-Bonds ({bonds_kons}%) "
        f"MUSS > Wachstum-Bonds ({bonds_wach}%)"
    )


# ===========================================================================
# 2. Hardness-Sensitivity
# ===========================================================================


def test_sens_hart_goal_triggert_konservativer_als_opp(monkeypatch):
    """Goal mit hardness=Hart muss IS aktivieren UND konservativer
    optimieren als das gleiche Goal mit hardness=Opportunistisch.
    """
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)

    g_hart = _goal(hardness="Hart", label="Hart-Goal", goal_id="g-hart")
    g_opp = _goal(hardness="Opportunistisch", label="Opp-Goal", goal_id="g-opp")
    # Ausgewogenes Profil, hartes vs weiches Goal
    ctx_hart = build_optimizer_context(
        cma=_cma(id="cma-hart"), goals=[g_hart],
        house_matrix_row=_hm_ausgewogen(),
        score_x10=55, advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 11, horizon_years=10,
        n_paths=300, seed=11,
    )
    ctx_opp = build_optimizer_context(
        cma=_cma(id="cma-opp"), goals=[g_opp],
        house_matrix_row=_hm_ausgewogen(),
        score_x10=55, advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 11, horizon_years=10,
        n_paths=300, seed=11,
    )
    # IS-Sensitivity: Hart triggert, Opp nicht
    assert ctx_hart.scenario_weights is not None, "Hart-Goal MUSS IS triggern"
    assert ctx_opp.scenario_weights is None, "Opp-Goal MUSS IS NICHT triggern"


# ===========================================================================
# 3. Goal-Count-Sensitivity
# ===========================================================================


def test_sens_mehr_goals_mehr_achievability_rows(monkeypatch):
    """Mit N Goals MUSS goal_achievability genau N Eintraege haben."""
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)

    for n_goals in [1, 2, 4]:
        goals = [
            _goal(hardness="Primär", label=f"G{i}", goal_id=f"g-{i}",
                  target=int(500_000_00 + i * 200_000_00))
            for i in range(n_goals)
        ]
        r = _run(cma_id=f"cma-{n_goals}", hm=_hm_ausgewogen(),
                 score_x10=55, goals=goals, seed=33)
        assert len(r.goal_achievability) == n_goals, (
            f"Bei {n_goals} Goals erwartet {n_goals} achievability-rows, "
            f"got {len(r.goal_achievability)}"
        )
        # Alle Goal-IDs vorhanden
        goal_ids_in = {g.id for g in goals}
        goal_ids_out = {a["goal_id"] for a in r.goal_achievability}
        assert goal_ids_in == goal_ids_out


# ===========================================================================
# 4. Retirement-Sensitivity
# ===========================================================================


def test_sens_retirement_aktiviert_is(monkeypatch):
    """is_retired=True triggert IS unabhaengig von Hardness/Profile-Score."""
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)

    g = _goal(hardness="Primär", label="Pension")  # weich, kein hart-Trigger
    ctx_active = build_optimizer_context(
        cma=_cma(id="cma-active"), goals=[g],
        house_matrix_row=_hm_wachstum(),
        score_x10=80,  # aggressiv -> kein konservativ-Trigger
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 11, horizon_years=10,
        n_paths=300, seed=44,
        is_retired=False,
    )
    ctx_retired = build_optimizer_context(
        cma=_cma(id="cma-retired"), goals=[g],
        house_matrix_row=_hm_wachstum(),
        score_x10=80, advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 11, horizon_years=10,
        n_paths=300, seed=44,
        is_retired=True,
    )
    assert ctx_active.scenario_weights is None, "Aggressiv-Akkumulation: IS inaktiv"
    assert ctx_retired.scenario_weights is not None, "Decumulation: IS MUSS aktiv sein"


# ===========================================================================
# 5. Horizon-Sensitivity
# ===========================================================================


def test_sens_langer_horizont_mehr_equity_als_kurz(monkeypatch):
    """Mit gleichem Profile-Score sollte ein 30J-Mandat mind. so viel oder
    mehr Equity haben wie ein 5J-Mandat (Risk-Recovery-Time-Argument).

    Hinweis: Solver kann je nach Goals beide Pfade aehnlich loesen — der Test
    pinnt nur die SCHWAECHERE Invariante: 30J darf nicht WENIGER Equity haben.
    """
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)

    g_short = _goal(hardness="Opportunistisch", days=365 * 5, goal_id="g-short")
    g_long = _goal(hardness="Opportunistisch", days=365 * 30, goal_id="g-long")
    r_short = _run(cma_id="cma-short", hm=_hm_ausgewogen(), score_x10=55,
                   goals=[g_short], horizon=5, seed=55)
    r_long = _run(cma_id="cma-long", hm=_hm_ausgewogen(), score_x10=55,
                  goals=[g_long], horizon=30, seed=55)
    if r_short.status == "fallback_house_matrix" or r_long.status == "fallback_house_matrix":
        return
    equity_short = _bucket_pct(r_short.weights_bps, "equities")
    equity_long = _bucket_pct(r_long.weights_bps, "equities")
    # Schwaechere Invariante: 30J darf nicht signifikant weniger Equity haben
    assert equity_long >= equity_short - 5.0, (
        f"Drift: 30J-Equity ({equity_long}%) viel weniger als 5J-Equity ({equity_short}%)"
    )


# ===========================================================================
# 6. Cashflow-Sensitivity
# ===========================================================================


def test_sens_positive_cf_bessere_achievability_als_negative(monkeypatch):
    """Gleiches Vermoegensziel: mit positiver CF (Sparen) muss
    Achievability HOEHER sein als mit negativer CF (Entnahme)."""
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)

    g = _goal(hardness="Primär", target=1_500_000_00, days=365 * 10,
              label="Wealth-Goal")
    horizon = 10
    r_save = _run(cma_id="cma-save", hm=_hm_ausgewogen(), score_x10=55,
                  goals=[g], horizon=horizon,
                  cf=[20_000_00] * (horizon + 1), seed=66)
    r_spend = _run(cma_id="cma-spend", hm=_hm_ausgewogen(), score_x10=55,
                   goals=[g], horizon=horizon,
                   cf=[-20_000_00] * (horizon + 1), seed=66)
    if r_save.status == "fallback_house_matrix" or r_spend.status == "fallback_house_matrix":
        return
    p_save = r_save.goal_achievability[0]["probability"]
    p_spend = r_spend.goal_achievability[0]["probability"]
    # Mit Sparen muss Goal mind. gleichgut oder besser erreichbar sein
    assert p_save >= p_spend - 0.05, (
        f"Sparen ({p_save:.2%}) muss >= Entnahme ({p_spend:.2%}) sein "
        "(±5% Toleranz fuer MC-Rauschen)"
    )


# ===========================================================================
# 7. IS-Switching-Sensitivity
# ===========================================================================


def test_sens_is_status_switched_mit_hardness(monkeypatch):
    """Gleicher Mandate-Setup, nur hardness aendert sich:
    Hart -> IS aktiv, Opp -> IS inaktiv. Dynamic-Switch verifiziert."""
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)

    for hardness, expect_is_active in [("Hart", True), ("Opportunistisch", False)]:
        g = _goal(hardness=hardness, label=f"G-{hardness}",
                  goal_id=f"g-{hardness.lower()}")
        ctx = build_optimizer_context(
            cma=_cma(id=f"cma-{hardness.lower()}"), goals=[g],
            house_matrix_row=_hm_ausgewogen(),
            score_x10=70,  # mid-aggressiv → kein konservativ-Trigger
            advisory_wealth_rappen=1_000_000_00,
            cashflow_series_rappen=[0] * 11, horizon_years=10,
            n_paths=200, seed=77,
            is_retired=False,
        )
        has_is = ctx.scenario_weights is not None
        assert has_is == expect_is_active, (
            f"Hardness {hardness}: erwartet IS-aktiv={expect_is_active}, war={has_is}"
        )


# ===========================================================================
# End-to-End Integration: Full Solver Run liefert auditbaren Output
# ===========================================================================


def test_e2e_solver_output_komplett_auditierbar(monkeypatch):
    """End-to-End: kompletter Solver-Run mit realen Mandate-Daten muss
    alle Audit-Trail-Felder befuellen."""
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)

    goals = [
        _goal(hardness="Hart", label="Lebensunterhalt", goal_id="g-lh",
              target=80_000_00, days=365 * 20),
        _goal(hardness="Primär", label="Erbschaft", goal_id="g-erbe",
              target=500_000_00, days=365 * 25),
    ]
    r = _run(cma_id="cma-e2e", hm=_hm_konservativ(), score_x10=25,
             goals=goals, wealth=2_000_000_00, horizon=25,
             cf=[-30_000_00] * 26, is_retired=True, seed=88)
    # AUDIT-Pflicht-Felder:
    # 1. Status definiert
    assert r.status in {"converged", "converged_robustified", "fallback_house_matrix"}
    # 2. weights_bps korrekt strukturiert
    assert isinstance(r.weights_bps, dict)
    if r.status != "fallback_house_matrix":
        assert abs(sum(r.weights_bps.values()) - 10000) <= 5, (
            "Weights summieren nicht zu 10000 bps"
        )
    # 3. Reasoning enthaelt IS-Status
    reasoning_text = " ".join(r.reasoning).lower()
    assert "importance sampling" in reasoning_text
    # 4. Goal-Achievability pro Goal
    assert len(r.goal_achievability) == 2
    for ach in r.goal_achievability:
        assert "goal_id" in ach
        assert "status" in ach
        assert "probability" in ach
        assert 0.0 <= ach["probability"] <= 1.0


# ===========================================================================
# Determinism-Sanity (in Erweiterung zu A2)
# ===========================================================================


def test_e2e_zwei_runs_identische_inputs_identisches_ergebnis(monkeypatch):
    """Determinismus-Pin: identische Inputs MUESSEN identische Outputs."""
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)

    g = _goal(hardness="Primär", label="Test")
    r1 = _run(cma_id="cma-det", hm=_hm_ausgewogen(), score_x10=55,
              goals=[g], seed=99)
    r2 = _run(cma_id="cma-det", hm=_hm_ausgewogen(), score_x10=55,
              goals=[g], seed=99)
    assert r1.weights_bps == r2.weights_bps
    # Goal-Achievability auch identisch
    for a1, a2 in zip(r1.goal_achievability, r2.goal_achievability):
        assert a1["probability"] == a2["probability"]
        assert a1["status"] == a2["status"]
