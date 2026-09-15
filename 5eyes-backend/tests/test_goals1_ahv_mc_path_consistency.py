"""goals-1 (2026-07-24, Formel-Audit): AHV-Pensionsziele im MC-Pfad.

PENSION-AHV-001 (Phase 0, 2026-09): dieses Modul pinnte urspruenglich fest,
dass ein Pensionsausgabe-Goal mit pension_pillar='AHV' im MC-Bericht IMMER
als voll gedeckt (success_rate_pct=100, funded_ratio~1.0) erscheint --
UNABHAENGIG vom tatsaechlich simulierten Portfolio-Pfad. Das war ein reiner
Label-Fake: es gibt keinen Beleg-Mechanismus (kein Betragsfeld in
schemas/wealth.py GoalCreate/-Update) fuer eine tatsaechliche erwartete
AHV-Rente. Audit-Repro: ein CHF 1'000'000/Jahr AHV-Goal ohne jegliches
Portfolio-Vermoegen zeigte trotzdem mc_success=100 / mc_funded_ratio=1.0.

Fix: der fruehe 'pension_state_funded_goal'-Guard in
_monte_carlo_goal_summary liefert jetzt nie mehr True
(_goal_pension_state_funded() liefert immer False, siehe
services/portfolio_engine_reserve.py). Ein AHV-Pensionsausgabe-Goal
durchlaeuft ab sofort exakt denselben MC-Pfad wie ein identisches Goal ohne
pension_pillar (Kontrollgruppe) -- die Tests unten verifizieren das.
"""
from types import SimpleNamespace

from services.portfolio_engine import _monte_carlo_goal_summary, _goal_reserve_for_goal

from test_goal_scoring_horizon import _make_policy

# Niedrige, VOLATILE Pfade -- ein Ausgabenziel dieser Groesse ist hier klar
# unterfinanziert/gefaehrdet, egal ob AHV-gelabelt oder nicht.
_LOW_SPREAD = [k * 10_000 for k in range(1, 21)]  # 10k..200k Rappen
_ANNUAL_PENSION_RAPPEN = 24_000_00  # CHF 24'000 p.a.


def _ahv_pension_goal(probability_pct=None):
    return SimpleNamespace(
        id="ahv-1",
        label="AHV-Altersrente",
        goal_type="Pensionsausgabe",
        goal_scope="Beratungsvermoegen",
        pension_pillar="AHV",
        rank=1,
        hardness="Primaer",
        weight_bps=0,
        probability_pct=probability_pct,
        target_amount_rappen=_ANNUAL_PENSION_RAPPEN,
        target_wealth_rappen=0,
        target_return_bps=0,
        start_date="2027-01-01",
        target_date=None,
        horizon_years=5,
        is_ongoing=1,
        frequency="jaehrlich",
    )


def _non_state_goal():
    """Kontrollgruppe: identische Betraege/Pfade, aber KEIN pension_pillar.
    Nach PENSION-AHV-001 muss das AHV-Goal hierzu IDENTISCH bewertet werden --
    das ist die zentrale Regressionsguard-Aussage dieses Moduls."""
    g = _ahv_pension_goal()
    g.pension_pillar = None
    g.goal_type = "Wiederkehrende_Ausgabe"
    return g


def _summary_for(goal):
    return _monte_carlo_goal_summary(
        goal,
        path_values_by_year=[list(_LOW_SPREAD) for _ in range(6)],
        annualized_return_samples_bps=[300, 400, 500],
        inflation_series_bps=[0] * 6,
        advisory_wealth_rappen=100_000_00,
        total_wealth_rappen=100_000_00,
        start_year=2026,
        horizon_years=5,
        policy=_make_policy(),
    )


def test_ahv_goal_no_longer_auto_covered_in_mc_path():
    """Audit-Repro (PENSION-AHV-001): ein unconditional AHV-Goal (probability_pct
    =None -> 100%) darf NICHT mehr automatisch Score=100/success=100 zeigen,
    wenn der simulierte Portfolio-Pfad das Ziel klar verfehlt. Vorher (Sprint
    B3/goals-1) lieferte exakt diese Eingabe success_rate_pct=100, score=100,
    pessimistic_shortfall_rappen=0 -- rein aus dem pension_pillar='AHV'-Label."""
    summary = _summary_for(_ahv_pension_goal())
    assert summary["success_rate_pct"] == 0
    assert summary["score"] == 0
    assert summary["funded_ratio_p50"] == 0.0109
    assert summary["pessimistic_shortfall_rappen"] == 9_542_500


def test_ahv_goal_mc_summary_matches_non_pillar_control():
    """Kernaussage von PENSION-AHV-001: pension_pillar='AHV' darf das
    MC-Ergebnis in KEINEM Feld mehr veraendern. Das AHV-Goal und die
    Kontrollgruppe (identische Betraege/Pfade, kein pension_pillar) muessen
    bit-identisch bewertet werden."""
    summary_ahv = _summary_for(_ahv_pension_goal())
    summary_control = _summary_for(_non_state_goal())
    comparable_fields = (
        "success_rate_pct", "funded_ratio_p50", "median_achievement_pct",
        "pessimistic_shortfall_rappen", "projected_value_p10_rappen",
        "projected_value_p25_rappen", "projected_value_p50_rappen",
        "projected_value_p90_rappen", "score", "evaluation_note",
    )
    for field in comparable_fields:
        assert summary_ahv[field] == summary_control[field], field


def test_conditional_ahv_goal_is_not_silently_100_percent():
    """Ein bedingtes/unsicheres AHV-Goal (probability_pct<100) darf NICHT
    trotzdem blind auf 100% gesetzt werden. Nach PENSION-AHV-001 gilt
    dasselbe zusaetzlich schon fuer den UNBEDINGTEN Fall (siehe Test oben) --
    hier verifizieren wir, dass die Sprint-B6-Wahrscheinlichkeitsgewichtung
    (Bedingte Goals) durch den PENSION-AHV-001-Fix nicht kaputtgegangen ist."""
    goal = _ahv_pension_goal(probability_pct=50)
    summary = _summary_for(goal)
    assert summary["success_rate_pct"] == 0
    # Nicht mehr 0.5 (das war der alte, staatlich-gedeckte deterministische
    # Formel-Wert) -- der MC-Pfad bewertet jetzt den tatsaechlichen
    # (schwachen) Portfolio-Pfad gegen das (wahrscheinlichkeitsgewichtete)
    # Ziel, konsistent zur Kontrollgruppe.
    assert summary["funded_ratio_p50"] == 0.0219
    assert summary["pessimistic_shortfall_rappen"] == 4_742_500
    # Kontrollgruppe (kein pension_pillar) bei gleicher Wahrscheinlichkeit
    # muss identisch sein.
    control = _ahv_pension_goal(probability_pct=50)
    control.pension_pillar = None
    control.goal_type = "Wiederkehrende_Ausgabe"
    assert _summary_for(control)["funded_ratio_p50"] == summary["funded_ratio_p50"]


def test_non_state_funded_goal_unaffected_by_fix():
    """Kontrollgruppe: ein normales Ausgabenziel (kein pension_pillar) bleibt
    weiterhin voll portfolio-abhaengig -- bei diesen schwachen Pfaden also
    klar NICHT voll gedeckt (unveraendert durch PENSION-AHV-001, das nur den
    AHV-Sonderfall betrifft, der jetzt entfernt ist)."""
    summary = _summary_for(_non_state_goal())
    assert summary["score"] < 100


def test_ahv_pillar_label_survives_independently_of_funding_math():
    """PENSION-AHV-001 entfernt nur den Funding-Automatismus, NICHT das
    pension_pillar-Metadatenfeld selbst -- _goal_reserve_for_goal() (der
    deterministische Reserve-Pfad) bleibt fuer AHV weiterhin aufrufbar und
    liefert einen sinnvollen (nicht mehr privilegierten) Wert."""
    goal = _ahv_pension_goal(probability_pct=70)
    assert goal.pension_pillar == "AHV"
    reserve_value = _goal_reserve_for_goal(goal)
    assert reserve_value >= 0
