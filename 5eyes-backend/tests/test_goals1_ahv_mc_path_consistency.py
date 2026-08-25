"""goals-1 (2026-07-24, Formel-Audit): AHV-Pensionsziele im MC-Pfad.

Der deterministische Pfad (`_goal_reserve_for_goal`, Sprint B3) behandelt ein
Pensionsausgabe-Goal mit staatlicher Saeule (pension_pillar="AHV") als voll
gedeckt -- die AHV-Rente deckt die Auszahlung, kein Portfolio-Asset noetig.
`_monte_carlo_goal_summary` rief `_goal_pension_state_funded` vorher nie ab
und bewertete dasselbe Goal wie ein normales Ausgabenziel, das komplett aus
dem simulierten Portfolio finanziert werden muss -- der MC-Bericht zeigte
dadurch einen unabhaengig (und typischerweise niedrigeren) Score als der
deterministische Bericht fuer IDENTISCHES Goal. Fix: frueher Guard,
spiegelt _goal_reserve_for_goal exakt.
"""
from types import SimpleNamespace

from services.portfolio_engine import _monte_carlo_goal_summary, _goal_reserve_for_goal

from test_goal_scoring_horizon import _make_policy

# Niedrige, VOLATILE Pfade -- ein normales (nicht staatlich gedecktes)
# Ausgabenziel dieser Groesse waere hier klar unterfinanziert/gefaehrdet.
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
    """Kontrollgruppe: identische Betraege/Pfade, aber KEIN pension_pillar
    -> muss weiterhin normal (portfolio-abhaengig) bewertet werden."""
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


def test_ahv_goal_is_treated_as_fully_covered_in_mc_path():
    """Unconditional AHV-Goal (probability_pct=None -> 100%) muss Score=100
    und success_rate_pct=100 zeigen, UNABHAENGIG vom (hier bewusst schwachen)
    simulierten Portfolio-Pfad."""
    summary = _summary_for(_ahv_pension_goal())
    assert summary["success_rate_pct"] == 100
    assert summary["score"] == 100
    assert summary["pessimistic_shortfall_rappen"] == 0


def test_ahv_goal_matches_deterministic_reserve_formula():
    """MC-Pfad und deterministischer Pfad (_goal_reserve_for_goal) muessen
    fuer dasselbe AHV-Goal auf denselben 'gedeckten Betrag' kommen --
    das ist der Kern der behobenen Inkonsistenz."""
    goal = _ahv_pension_goal(probability_pct=70)
    summary = _summary_for(goal)
    deterministic_available = _goal_reserve_for_goal(goal)
    assert deterministic_available == int(round(_ANNUAL_PENSION_RAPPEN * 0.70))
    assert summary["funded_ratio_p50"] == round(deterministic_available / _ANNUAL_PENSION_RAPPEN, 4)


def test_conditional_ahv_goal_is_not_silently_100_percent():
    """Ein bedingtes/unsicheres AHV-Goal (probability_pct<100) darf NICHT
    trotzdem blind auf 100% gesetzt werden -- der Fix darf die
    Wahrscheinlichkeits-Gewichtung (Sprint B6) nicht wegfixen."""
    goal = _ahv_pension_goal(probability_pct=50)
    summary = _summary_for(goal)
    assert summary["success_rate_pct"] == 0  # 50% < 100% Ziel -> binaer nicht erreicht
    assert summary["funded_ratio_p50"] == 0.5
    assert summary["pessimistic_shortfall_rappen"] == _ANNUAL_PENSION_RAPPEN - int(round(_ANNUAL_PENSION_RAPPEN * 0.5))


def test_non_state_funded_goal_unaffected_by_fix():
    """Kontrollgruppe: ein normales Ausgabenziel (kein pension_pillar) bleibt
    weiterhin voll portfolio-abhaengig -- bei diesen schwachen Pfaden also
    klar NICHT voll gedeckt (Gegenbeweis, dass der Fix nicht zu breit greift)."""
    summary = _summary_for(_non_state_goal())
    assert summary["score"] < 100
