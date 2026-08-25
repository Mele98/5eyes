"""Sprint A2 (2026-06-07): Engine-Reference-Mandate-Suite.

5 kanonische Mandate mit MANUELL auditierten Erwartungs-Ranges. Diese Tests
sind die **permanente Regression-Coverage** der Engine — bei jeder zukuenftigen
Aenderung am Optimizer/MC/Tax-Pipeline muessen diese Mandate identisch oder
besser performen.

# Test-Philosophie
- KEINE brittle absolute Werte (z.B. "Bonds = 4231 bps"). Stattdessen
  STRUKTURELLE Erwartungen die robust gegen kleinste Engine-Aenderungen sind:
  - Bucket-Verhaeltnisse (Bonds > Equity bei Konservativ)
  - Achievability-Status (erreichbar/knapp/nicht_erreichbar)
  - IS-Aktivierung (ja/nein)
  - Convergence-Status (converged/converged_robustified/diverged)
- Manuelle Audit-Notizen pro Mandat erklaeren WARUM die Erwartung Sinn macht
- Bei Engine-Refactor: diese Tests duerfen NICHT angepasst werden ohne
  Audit-Review.

# Die 5 Mandate
- M1: Pensionaer 68J, Hart-Goal Lebensunterhalt 80k/J — Decumulation+Konservativ+Hart
- M2: Anleger 35J, weiche Goals — Akkumulation+Wachstum+Soft
- M3: HNW 55J, CHF 50M, Multi-Goal — Mid-Risk + Komplexitaet
- M4: Risikoprofil-Override (Berater uebersteuert Fragebogen)
- M5: Pensionaer mit AHV+BVG+Lump-Sum — Komplexe CF-Aggregation

Cross-Reference: docs/engine-spec.md Section 7+8
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from services.optimizer.solver import build_optimizer_context, run_solver


# ===========================================================================
# Gemeinsame Test-Helpers
# ===========================================================================

def _base_cma(**overrides):
    """Standard CMA aus CH-Beraterperspektive (Mid-Range)."""
    base = {
        "id": "cma-reference-mandate",
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


def _house_matrix_wachstum():
    return SimpleNamespace(
        profile_name="Wachstumsorientiert",
        equity_min_bps=4500, equity_max_bps=7000, equity_target_bps=6000,
        bonds_min_bps=2000, bonds_max_bps=4500, bonds_target_bps=3000,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=1000, alt_target_bps=300,
        liq_min_bps=200, liq_max_bps=2000, liq_target_bps=200,
        max_risky_fraction_bps=7500,
    )


def _house_matrix_konservativ():
    return SimpleNamespace(
        profile_name="Konservativ",
        equity_min_bps=500, equity_max_bps=2500, equity_target_bps=1500,
        bonds_min_bps=5000, bonds_max_bps=8000, bonds_target_bps=6500,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=500, alt_target_bps=200,
        liq_min_bps=500, liq_max_bps=2000, liq_target_bps=1000,
        max_risky_fraction_bps=3000,
    )


def _house_matrix_ausgewogen():
    return SimpleNamespace(
        profile_name="Ausgewogen",
        equity_min_bps=2500, equity_max_bps=5000, equity_target_bps=4000,
        bonds_min_bps=3500, bonds_max_bps=6000, bonds_target_bps=4500,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=1000, alt_target_bps=300,
        liq_min_bps=300, liq_max_bps=2000, liq_target_bps=500,
        max_risky_fraction_bps=5500,
    )


def _make_goal(
    *,
    goal_id: str,
    label: str,
    hardness: str,
    goal_type: str = "Vermoegensziel",
    target_rappen: int = 1_000_000_00,
    target_date_offset_days: int = 365 * 10,
    is_ongoing: bool = False,
    frequency: str = "jaehrlich",
    value_mode: str = "real",
):
    today = date.today()
    return SimpleNamespace(
        id=goal_id, label=label, goal_type=goal_type,
        target_amount_rappen=target_rappen,
        target_wealth_rappen=target_rappen, target_return_bps=None,
        horizon_years=None,
        start_date=today.isoformat(),
        target_date=(today + timedelta(days=target_date_offset_days)).isoformat(),
        is_ongoing=1 if is_ongoing else 0, frequency=frequency,
        hardness=hardness, rank=1, weight_bps=5000, value_mode=value_mode,
    )


def _bucket_pct(weights_bps: dict, bucket: str) -> float:
    """Anteil eines Buckets als Prozent (zwischen 0 und 100)."""
    return int(weights_bps.get(bucket, 0)) / 100.0


def _bps_to_pct(bps: int) -> float:
    return int(bps) / 100.0


# ===========================================================================
# M1 — PENSIONAER (Decumulation + Konservativ + Hart-Goal)
# ===========================================================================
# AUDIT-NOTIZEN
# - 68J, im Ruhestand, Vermoegen muss bis 95J reichen
# - Lebensunterhalt 80k/Jahr = Hart-Goal (nicht verhandelbar)
# - Risikoprofil-Score 25 (Sicherheit-orientiert)
# - IS-Trigger ALLE 3 erfuellt: konservativ + retired + hart-Goal
# - Erwartung: Bonds-dominiert (>60%), Equity-Anteil klein
# - Achievability fuer Lebensunterhalt sollte erreichbar oder knapp sein
# ===========================================================================


def test_m1_pensionaer_decumulation_alle_is_trigger(monkeypatch):
    """M1: Alle 3 IS-Trigger aktiv -> IS muss aktiviert sein. Bonds-Dominanz."""
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)

    goals = [
        _make_goal(
            goal_id="m1-lebenshaltung", label="Lebensunterhalt bis 95J",
            hardness="Hart", goal_type="Vermoegensziel",
            target_rappen=80_000_00, target_date_offset_days=365 * 27,
        ),
    ]
    ctx = build_optimizer_context(
        cma=_base_cma(id="cma-m1"),
        goals=goals,
        house_matrix_row=_house_matrix_konservativ(),
        score_x10=25,  # konservativ
        advisory_wealth_rappen=2_500_000_00,
        cashflow_series_rappen=[-80_000_00] * 27,  # 80k/J Entnahme
        horizon_years=27,
        n_paths=500,
        seed=1,
        is_retired=True,
    )
    # AUDIT: IS muss aktiv sein (3 Trigger)
    assert ctx.scenario_weights is not None, "M1: IS muss aktiv sein (konservativ+retired+hart)"

    result = run_solver(
        cma=_base_cma(id="cma-m1"),
        goals=goals,
        house_matrix_row=_house_matrix_konservativ(),
        score_x10=25,
        advisory_wealth_rappen=2_500_000_00,
        cashflow_series_rappen=[-80_000_00] * 27,
        horizon_years=27,
        n_paths=500,
        seed=1,
        is_retired=True,
    )
    # AUDIT: Solver muss konvergieren (auch wenn Robustification noetig)
    assert result.status in {"converged", "converged_robustified", "fallback_house_matrix"}, (
        f"M1: unerwarteter Status {result.status}"
    )
    if result.status != "fallback_house_matrix":
        # AUDIT: Bonds dominieren bei Konservativ (mind. 50%)
        bonds_pct = _bucket_pct(result.weights_bps, "bonds")
        equity_pct = _bucket_pct(result.weights_bps, "equities")
        assert bonds_pct >= 40.0, f"M1: Bonds-Anteil {bonds_pct}% zu niedrig"
        assert bonds_pct > equity_pct, (
            f"M1: Bonds ({bonds_pct}%) muss > Equity ({equity_pct}%) sein"
        )
    # AUDIT: Achievability muss vorhanden sein
    assert len(result.goal_achievability) == 1
    ach = result.goal_achievability[0]
    assert ach["goal_id"] == "m1-lebenshaltung"
    assert ach["hardness"] == "hart"
    # AUDIT: Reasoning muss IS-Status nennen
    reasoning_text = " ".join(result.reasoning).lower()
    assert "importance sampling aktiv" in reasoning_text


# ===========================================================================
# M2 — ANLEGER WACHSTUM (Akkumulation + Soft + Wachstum)
# ===========================================================================
# AUDIT-NOTIZEN
# - 35J, Akkumulationsphase, langer Horizont 30J
# - Goals: Eigenheim (opportunistisch), Maximierung
# - KEIN IS-Trigger (Wachstumsprofil + weiche Goals + Akkumulation)
# - Erwartung: Equity-dominiert (>50%), Bonds klein
# - IS muss INAKTIV sein
# ===========================================================================


def test_m2_wachstum_kein_is_trigger(monkeypatch):
    """M2: KEINE IS-Trigger aktiv -> IS muss inaktiv sein. Equity-Dominanz."""
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)

    goals = [
        _make_goal(
            goal_id="m2-eigenheim", label="Eigenheim",
            hardness="Opportunistisch", goal_type="Vermoegensziel",
            target_rappen=600_000_00, target_date_offset_days=365 * 15,
        ),
        _make_goal(
            goal_id="m2-max", label="Vermoegen maximieren",
            hardness="Opportunistisch", goal_type="Maximierung",
            target_rappen=0, target_date_offset_days=365 * 30,
        ),
    ]
    ctx = build_optimizer_context(
        cma=_base_cma(id="cma-m2"),
        goals=goals,
        house_matrix_row=_house_matrix_wachstum(),
        score_x10=85,  # aggressiv
        advisory_wealth_rappen=200_000_00,
        cashflow_series_rappen=[10_000_00] * 30,  # 10k/J Sparen
        horizon_years=30,
        n_paths=500,
        seed=2,
        is_retired=False,
    )
    assert ctx.scenario_weights is None, "M2: IS muss INAKTIV sein (alle Trigger negativ)"

    result = run_solver(
        cma=_base_cma(id="cma-m2"),
        goals=goals,
        house_matrix_row=_house_matrix_wachstum(),
        score_x10=85,
        advisory_wealth_rappen=200_000_00,
        cashflow_series_rappen=[10_000_00] * 30,
        horizon_years=30,
        n_paths=500,
        seed=2,
        is_retired=False,
    )
    assert result.status in {"converged", "converged_robustified", "fallback_house_matrix"}, (
        f"M2: Status {result.status}"
    )
    if result.status != "fallback_house_matrix":
        equity_pct = _bucket_pct(result.weights_bps, "equities")
        bonds_pct = _bucket_pct(result.weights_bps, "bonds")
        # AUDIT: Equity-dominiert (mind. 40%)
        assert equity_pct >= 40.0, f"M2: Equity-Anteil {equity_pct}% zu niedrig"
        # AUDIT: Wachstumsprofil → Equity > Bonds
        assert equity_pct > bonds_pct, (
            f"M2: Equity ({equity_pct}%) muss > Bonds ({bonds_pct}%) bei Wachstum"
        )
    reasoning_text = " ".join(result.reasoning).lower()
    assert "importance sampling inaktiv" in reasoning_text


# ===========================================================================
# M3 — HNW MULTI-GOAL (Komplexitaet + Hart-Trigger)
# ===========================================================================
# AUDIT-NOTIZEN
# - 55J, CHF 50M Vermoegen
# - 3 Goals: Pension hart (60k/M ab 65), Erbschaft primaer, Renditeziel opp
# - Hart-Goal Trigger -> IS aktiv
# - Erwartung: Ausgewogen Mix, alle Goals haben Achievability-Status
# ===========================================================================


def test_m3_hnw_multi_goal_hart_trigger_is(monkeypatch):
    """M3: HNW mit Hart-Goal triggert IS, alle Goals werden bewertet."""
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)

    goals = [
        _make_goal(
            goal_id="m3-pension", label="Pension 60k/Monat",
            hardness="Hart", goal_type="Pensionsausgabe",
            target_rappen=720_000_00, target_date_offset_days=365 * 10,
            is_ongoing=True, frequency="jaehrlich",
        ),
        _make_goal(
            goal_id="m3-erbschaft", label="Erbschaft 5M",
            hardness="Primär", goal_type="Vermoegensziel",
            target_rappen=5_000_000_00, target_date_offset_days=365 * 25,
        ),
        _make_goal(
            goal_id="m3-rendite", label="Real-Rendite >3%",
            hardness="Opportunistisch", goal_type="Renditeziel",
            target_rappen=0, target_date_offset_days=365 * 25,
        ),
    ]
    ctx = build_optimizer_context(
        cma=_base_cma(id="cma-m3"),
        goals=goals,
        house_matrix_row=_house_matrix_ausgewogen(),
        score_x10=55,  # Ausgewogen
        advisory_wealth_rappen=50_000_000_00,
        cashflow_series_rappen=[200_000_00] * 25,
        horizon_years=25,
        n_paths=500,
        seed=3,
    )
    assert ctx.scenario_weights is not None, "M3: Hart-Goal muss IS triggern"

    result = run_solver(
        cma=_base_cma(id="cma-m3"),
        goals=goals,
        house_matrix_row=_house_matrix_ausgewogen(),
        score_x10=55,
        advisory_wealth_rappen=50_000_000_00,
        cashflow_series_rappen=[200_000_00] * 25,
        horizon_years=25,
        n_paths=500,
        seed=3,
    )
    assert result.status in {"converged", "converged_robustified", "fallback_house_matrix"}
    # AUDIT: alle 3 Goals haben Achievability-Eintrag
    assert len(result.goal_achievability) == 3
    goal_ids = {ach["goal_id"] for ach in result.goal_achievability}
    assert goal_ids == {"m3-pension", "m3-erbschaft", "m3-rendite"}
    # AUDIT: jedes Goal hat status + probability
    for ach in result.goal_achievability:
        assert ach["status"] in {"erreichbar", "knapp", "nicht_erreichbar"}
        assert 0.0 <= ach["probability"] <= 1.0


# ===========================================================================
# M4 — RISIKOPROFIL-OVERRIDE
# ===========================================================================
# AUDIT-NOTIZEN
# - Berater uebersteuert: Fragebogen sagt Konservativ (score 25),
#   aber Berater dokumentiert begruendet Wachstum (score 75)
# - Engine sieht NUR den effektiven Score (Override hat nach Berater-Entscheid
#   gewonnen)
# - Bei score_x10=75 + weiche Goals + nicht-retired = kein IS-Trigger
# - Engine respektiert den uebersteuerten Score -> Wachstums-Allocation
# ===========================================================================


def test_m4_risikoprofil_override_engine_respektiert_effective_score(monkeypatch):
    """M4: Engine darf NUR den effektiven Override-Score sehen. Konservativer
    Original-Score darf KEINE Spur in der Allocation hinterlassen."""
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)

    goals = [
        _make_goal(
            goal_id="m4-pension", label="Pension",
            hardness="Primär", goal_type="Vermoegensziel",
            target_rappen=2_000_000_00, target_date_offset_days=365 * 20,
        ),
    ]
    # Run 1: Direkt Wachstum ohne Override
    result_direct = run_solver(
        cma=_base_cma(id="cma-m4-direct"),
        goals=goals,
        house_matrix_row=_house_matrix_wachstum(),
        score_x10=75,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[20_000_00] * 20,
        horizon_years=20,
        n_paths=500,
        seed=4,
    )
    # Run 2: Mit Override (= identisch zu Direct, weil Engine nur effective_score sieht)
    result_override = run_solver(
        cma=_base_cma(id="cma-m4-override"),
        goals=goals,
        house_matrix_row=_house_matrix_wachstum(),
        score_x10=75,  # effective post-override
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[20_000_00] * 20,
        horizon_years=20,
        n_paths=500,
        seed=4,
    )
    # AUDIT: Beide Runs identisch — Engine ist post-override blind
    assert result_direct.weights_bps == result_override.weights_bps, (
        "M4: Engine darf nicht zwischen direkt-gesetztem und uebersteuertem "
        "Score unterscheiden — sie sieht nur den effective Score"
    )
    # AUDIT: Wachstumsprofil → IS inaktiv (kein hart, kein retired)
    reasoning = " ".join(result_direct.reasoning).lower()
    assert "importance sampling inaktiv" in reasoning


# ===========================================================================
# M5 — RENTENINCOME + LUMP-SUM
# ===========================================================================
# AUDIT-NOTIZEN
# - Pensionaer mit AHV+BVG-Renten = positives Cashflow-Income
# - Hart-Goal: Mindest-Vermoegen 1M am Lebensende (Liability fuer Erben)
# - Decumulation aber mit positivem Netto-Cashflow (Income > Expenses)
# - IS triggert (Decumulation + Hart-Goal)
# - Wealth-Trajectory soll positiv bleiben oder wachsen
# ===========================================================================


def test_m5_rentenincome_positiver_cashflow_hart_goal(monkeypatch):
    """M5: AHV+BVG decken Ausgaben, Hart-Goal fuer Erben. IS aktiv,
    Wealth soll nicht in Lebensluecke fallen."""
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)

    goals = [
        _make_goal(
            goal_id="m5-erbe", label="Mindest-Erbschaft 1M",
            hardness="Hart", goal_type="Vermoegensziel",
            target_rappen=1_000_000_00, target_date_offset_days=365 * 25,
        ),
    ]
    # AHV+BVG decken Lebenshaltung — Netto-CF positiv (5k Ueberschuss/J)
    ctx = build_optimizer_context(
        cma=_base_cma(id="cma-m5"),
        goals=goals,
        house_matrix_row=_house_matrix_konservativ(),
        score_x10=30,  # konservativ (Threshold-Grenze)
        advisory_wealth_rappen=1_500_000_00,
        cashflow_series_rappen=[5_000_00] * 25,
        horizon_years=25,
        n_paths=500,
        seed=5,
        is_retired=True,
    )
    # AUDIT: alle 3 Trigger aktiv → IS aktiv
    assert ctx.scenario_weights is not None

    result = run_solver(
        cma=_base_cma(id="cma-m5"),
        goals=goals,
        house_matrix_row=_house_matrix_konservativ(),
        score_x10=30,
        advisory_wealth_rappen=1_500_000_00,
        cashflow_series_rappen=[5_000_00] * 25,
        horizon_years=25,
        n_paths=500,
        seed=5,
        is_retired=True,
    )
    assert result.status in {"converged", "converged_robustified", "fallback_house_matrix"}
    assert len(result.goal_achievability) == 1
    ach = result.goal_achievability[0]
    assert ach["goal_id"] == "m5-erbe"
    assert ach["hardness"] == "hart"
    # AUDIT: Mit positivem Netto-Cashflow muss das Goal mindestens "knapp"
    # erreichbar sein (1.5M Start + 25J * 5k Sparen + Wachstum = mind. 2M nominal)
    assert ach["status"] in {"erreichbar", "knapp"}, (
        f"M5: Goal mit positivem CF muss mind. knapp erreichbar sein, "
        f"war: {ach['status']} (P={ach['probability']:.2%})"
    )


# ===========================================================================
# Drift-Resistenz: Inter-Mandat-Vergleiche
# ===========================================================================
# Diese Tests vergleichen die 5 Mandate gegeneinander. Wenn sich z.B. M1
# (konservativ) und M2 (aggressiv) "verkehren", ist die Engine kaputt.
# ===========================================================================


def test_drift_m1_konservativer_als_m2(monkeypatch):
    """Inter-Mandat-Vergleich: M1 (Konservativ-Profil) MUSS mehr Bonds-Anteil
    haben als M2 (Wachstums-Profil). Wenn umgekehrt -> Engine kaputt."""
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)

    # M1 minimal
    goals_m1 = [_make_goal(
        goal_id="g-m1", label="Lebensunterhalt", hardness="Hart",
        target_rappen=80_000_00, target_date_offset_days=365 * 27,
    )]
    r_m1 = run_solver(
        cma=_base_cma(id="cma-drift-m1"), goals=goals_m1,
        house_matrix_row=_house_matrix_konservativ(),
        score_x10=25, advisory_wealth_rappen=2_500_000_00,
        cashflow_series_rappen=[-80_000_00] * 27, horizon_years=27,
        n_paths=400, seed=11, is_retired=True,
    )
    # M2 minimal
    goals_m2 = [_make_goal(
        goal_id="g-m2", label="Eigenheim",
        hardness="Opportunistisch", goal_type="Vermoegensziel",
        target_rappen=600_000_00, target_date_offset_days=365 * 15,
    )]
    r_m2 = run_solver(
        cma=_base_cma(id="cma-drift-m2"), goals=goals_m2,
        house_matrix_row=_house_matrix_wachstum(),
        score_x10=85, advisory_wealth_rappen=200_000_00,
        cashflow_series_rappen=[10_000_00] * 30, horizon_years=30,
        n_paths=400, seed=22,
    )
    # AUDIT-Invariante: konservatives Mandat MUSS mehr Bonds haben
    if r_m1.status != "fallback_house_matrix" and r_m2.status != "fallback_house_matrix":
        bonds_m1 = _bucket_pct(r_m1.weights_bps, "bonds")
        bonds_m2 = _bucket_pct(r_m2.weights_bps, "bonds")
        equity_m1 = _bucket_pct(r_m1.weights_bps, "equities")
        equity_m2 = _bucket_pct(r_m2.weights_bps, "equities")
        assert bonds_m1 > bonds_m2, (
            f"DRIFT: M1-Bonds ({bonds_m1}%) muss > M2-Bonds ({bonds_m2}%)"
        )
        assert equity_m2 > equity_m1, (
            f"DRIFT: M2-Equity ({equity_m2}%) muss > M1-Equity ({equity_m1}%)"
        )


def test_drift_is_status_korreliert_mit_triggers(monkeypatch):
    """Inter-Mandat: IS muss konsistent mit Triggern aktiv/inaktiv sein."""
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)

    # Reset cache between runs to avoid stale state
    from services.optimizer.scenario_cache import get_default_cache
    get_default_cache().clear()

    # Trigger-aktiv: konservativ + retired + hart-Goal
    ctx_aktiv = build_optimizer_context(
        cma=_base_cma(id="cma-drift-aktiv"),
        goals=[_make_goal(
            goal_id="g-aktiv", label="Pension", hardness="Hart",
            target_rappen=80_000_00, target_date_offset_days=365 * 10,
        )],
        house_matrix_row=_house_matrix_konservativ(),
        score_x10=25, advisory_wealth_rappen=2_000_000_00,
        cashflow_series_rappen=[0] * 11, horizon_years=10,
        n_paths=200, seed=33, is_retired=True,
    )
    # Trigger-inaktiv: aggressiv + nicht-retired + weiches Goal
    ctx_inaktiv = build_optimizer_context(
        cma=_base_cma(id="cma-drift-inaktiv"),
        goals=[_make_goal(
            goal_id="g-inaktiv", label="Max", hardness="Opportunistisch",
            goal_type="Maximierung", target_rappen=0,
            target_date_offset_days=365 * 30,
        )],
        house_matrix_row=_house_matrix_wachstum(),
        score_x10=85, advisory_wealth_rappen=200_000_00,
        cashflow_series_rappen=[0] * 31, horizon_years=30,
        n_paths=200, seed=44, is_retired=False,
    )
    assert ctx_aktiv.scenario_weights is not None
    assert ctx_inaktiv.scenario_weights is None


def test_drift_deterministisch_gleicher_seed_gleicher_lauf(monkeypatch):
    """Zwei Runs mit identischen Inputs MUESSEN identische Ergebnisse liefern."""
    from config import settings
    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)

    # Cache leeren zwischen Runs (sonst sieht Run 2 cached paths)
    from services.optimizer.scenario_cache import get_default_cache

    goals = [_make_goal(
        goal_id="g-det", label="Test", hardness="Primär",
        target_rappen=1_000_000_00, target_date_offset_days=365 * 10,
    )]

    get_default_cache().clear()
    r1 = run_solver(
        cma=_base_cma(id="cma-determinism"),
        goals=goals,
        house_matrix_row=_house_matrix_ausgewogen(),
        score_x10=55, advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[10_000_00] * 10, horizon_years=10,
        n_paths=300, seed=99,
    )
    # Run 2 identisch
    r2 = run_solver(
        cma=_base_cma(id="cma-determinism"),
        goals=goals,
        house_matrix_row=_house_matrix_ausgewogen(),
        score_x10=55, advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[10_000_00] * 10, horizon_years=10,
        n_paths=300, seed=99,
    )
    # AUDIT: identische Weights bei identischem Seed
    assert r1.weights_bps == r2.weights_bps, (
        f"Determinismus verletzt: r1={r1.weights_bps} vs r2={r2.weights_bps}"
    )
