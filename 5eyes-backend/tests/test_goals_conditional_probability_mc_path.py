"""2026-07-24 (Formel-Audit, Folgefund zu goals-1): bedingte Ausgabenziele
(probability_pct < 100, Sprint B6) wurden im MC-Pfad
(_monte_carlo_goal_summary) nie mit dem Wahrscheinlichkeitsfaktor
gewichtet -- der deterministische Pfad (_goal_reserve_for_goal) tat das
bereits. Ein 50%-wahrscheinliches Ausgabenziel sah im MC-Bericht aus wie
ein sicheres (100%) Ziel. Fix: dasselbe target * _goal_probability_factor
wie im deterministischen Pfad.
"""
from types import SimpleNamespace

from services.portfolio_engine import _monte_carlo_goal_summary, _goal_reserve_for_goal

from test_goal_scoring_horizon import _make_policy

# Portfolio-Pfade genau auf Hoehe des UNGEWICHTETEN Ziels (24'000) --
# ohne Fix: success=100% (Ziel==Pfad). Mit 50%-Gewichtung sollte das Ziel
# auf 12'000 sinken -> Pfad uebertrifft es klar -> weiterhin success=100%,
# aber mit einem deutlich hoeheren funded_ratio (Pfad/Ziel statt 1:1).
_SPREAD = [24_000_00] * 20
_ANNUAL_AMOUNT_RAPPEN = 24_000_00


def _conditional_expense_goal(probability_pct):
    return SimpleNamespace(
        id="cond-1",
        label="Bedingte Ausgabe",
        goal_type="Einmalige_Ausgabe",
        pension_pillar=None,
        probability_pct=probability_pct,
        rank=1,
        hardness="Primaer",
        weight_bps=0,
        target_amount_rappen=_ANNUAL_AMOUNT_RAPPEN,
        target_wealth_rappen=0,
        target_return_bps=0,
        start_date="2027-01-01",
        target_date="2027-06-01",
        horizon_years=5,
        is_ongoing=0,
        frequency=None,
    )


def _summary_for(goal):
    return _monte_carlo_goal_summary(
        goal,
        path_values_by_year=[list(_SPREAD) for _ in range(6)],
        annualized_return_samples_bps=[300, 400, 500],
        inflation_series_bps=[0] * 6,
        advisory_wealth_rappen=100_000_00,
        total_wealth_rappen=100_000_00,
        start_year=2026,
        horizon_years=5,
        policy=_make_policy(),
    )


def test_unconditional_goal_unaffected_baseline():
    """probability_pct=None (=100%) -> unveraendertes Verhalten, funded_ratio=1.0."""
    summary = _summary_for(_conditional_expense_goal(None))
    assert summary["funded_ratio_p50"] == 1.0
    assert summary["success_rate_pct"] == 100


def test_conditional_goal_target_scaled_down_by_probability():
    """50%-wahrscheinliches Ziel: derselbe Portfolio-Pfad deckt jetzt das
    HALBIERTE Ziel doppelt -> funded_ratio_p50 muss ~2.0 sein statt 1.0."""
    summary = _summary_for(_conditional_expense_goal(50))
    assert summary["funded_ratio_p50"] == 2.0
    assert summary["success_rate_pct"] == 100


def test_conditional_goal_matches_deterministic_reserve_scaling():
    """Der MC-Pfad muss dieselbe Skalierung nutzen wie
    _goal_reserve_for_goal() im deterministischen Pfad."""
    goal = _conditional_expense_goal(30)
    deterministic_available = _goal_reserve_for_goal(goal)
    assert deterministic_available == int(round(_ANNUAL_AMOUNT_RAPPEN * 0.30))
    # MC-Ziel (vor int()-Rundung) folgt derselben Skala: Pfad/Ziel = 1/0.30.
    summary = _summary_for(goal)
    assert summary["funded_ratio_p50"] == round(1 / 0.30, 4)


def test_pension_state_funded_ahv_goal_unaffected_by_this_change():
    """Regressionsschutz: der heute Nacht zuvor gefixte goals-1-Zweig (AHV,
    unbedingt/100% wahrscheinlich) nutzt einen eigenen fruehen Guard und darf
    durch diesen Folge-Fix nicht beeinflusst werden. (Ein BEDINGTES AHV-Goal
    zeigt korrekterweise success=0 bei <100% Wahrscheinlichkeit -- das prueft
    bereits test_conditional_ahv_goal_is_not_silently_100_percent in
    test_goals1_ahv_mc_path_consistency.py, hier testen wir bewusst den
    unbedingten Fall.)"""
    goal = _conditional_expense_goal(None)
    goal.goal_type = "Pensionsausgabe"
    goal.pension_pillar = "AHV"
    goal.frequency = "jaehrlich"
    goal.is_ongoing = 1
    summary = _summary_for(goal)
    assert summary["success_rate_pct"] == 100
    assert summary["score"] == 100
