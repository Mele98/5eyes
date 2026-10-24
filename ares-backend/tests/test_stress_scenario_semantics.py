"""STRESS-SEMANTICS-001: Stress-Tests messen die Krise, nicht das Padding.

Befund (realer Mandant, A = CHF 2.154 Mio, Horizont 41 J., Gewichte
Aktien .708 / Bonds .121 / Immobilien .1033 / Alts .03 / Liq .0377):
``evaluate_stress_scenarios`` padded jeden 3-5-jaehrigen Krisenpfad mit
Faktor 1.0 (0 % nominal) auf den vollen Horizont, laesst die Kunden-
Cashflows/Ziel-Ausgaben darueberlaufen und rechnete ``max_drawdown_bps``
peak-to-trough auf diesem flussbehafteten VERMOEGENS-Pfad (der negativ
werden darf). Ergebnis: Max-Drawdown 515 % / 427 % / 419 % -- und die
KONTROLLE ganz ohne Krise (alle Faktoren 1.0) zeigte 396 %. Die Tabelle mass
also Padding + Entnahmen, nicht die Krise; ein Portfolio-Drawdown > 100 %
ist mathematisch unmoeglich.

Soll-Semantik:
- ``max_drawdown_bps`` = groesster peak-to-trough-Verlust des FLUSSFREIEN
  Portfolio-Indexes (cumprod(weights @ factors)), immer in [0, 10000].
- ``cumulative_return_bps`` = flussfreie kumulierte Portfolio-Rendite ueber
  die Krisenjahre.
- ``baseline_end_wealth_rappen`` = derselbe Vermoegens-Lauf (gleiche Flows,
  gleiches Padding) OHNE Krise; ``crisis_impact_end_wealth_rappen`` =
  end_wealth - baseline_end_wealth = was die Krise selbst kostet.

Erwartungswerte werden hier von Hand bzw. aus den Faktor-Tabellen per
expliziter Schleife hergeleitet, nicht aus der Produktion abgeleitet.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.scenario_engine import N_BUCKETS
from services.optimizer.stress_scenarios import (
    STRESS_SCENARIOS,
    evaluate_stress_scenarios,
    stress_results_to_dict,
)

# Realer Mandant aus dem Befund
MANDATE_WEIGHTS = np.array([0.708, 0.121, 0.1033, 0.03, 0.0377])
MANDATE_WEALTH_RAPPEN = 2_154_000_00
HORIZON = 41
# Grosse Entnahmen: ~250k/J -> Vermoegen wird mitten im Horizont negativ.
HEAVY_WITHDRAWALS = [-250_000_00] * HORIZON

ALL_EQUITY = np.array([1.0, 0.0, 0.0, 0.0, 0.0])

NO_CRISIS = {"no_crisis_control": np.ones((3, N_BUCKETS), dtype=np.float64)}


def _scenarios_with_control() -> dict[str, np.ndarray]:
    scen = dict(STRESS_SCENARIOS)
    scen.update(NO_CRISIS)
    return scen


def _hand_index_drawdown_bps(weights, factors) -> tuple[float, float]:
    """Flussfreier Portfolio-Index, explizit Jahr fuer Jahr (kein numpy-cumprod).

    Returns (max_drawdown_bps, cumulative_return_bps) als float.
    """
    index = 1.0
    peak = 1.0
    max_dd = 0.0
    for row in factors:
        growth = sum(float(w) * float(f) for w, f in zip(weights, row))
        index *= growth
        peak = max(peak, index)
        max_dd = max(max_dd, (peak - index) / peak)
    return max_dd * 10000.0, (index - 1.0) * 10000.0


# ---------------------------------------------------------------------------
# 1. Kern-Reproducer: Drawdown > 100 % bei Entnahmen ist unmoeglich
# ---------------------------------------------------------------------------


def test_drawdown_is_bounded_even_when_withdrawals_drive_wealth_negative():
    results = evaluate_stress_scenarios(
        weights=MANDATE_WEIGHTS,
        initial_wealth_rappen=MANDATE_WEALTH_RAPPEN,
        cashflow_series_rappen=HEAVY_WITHDRAWALS,
        liability_path_rappen=None,
        horizon_years=HORIZON,
    )
    for name, r in results.items():
        # Vorbedingung: das Vermoegen wird tatsaechlich negativ (Lebensluecke)
        assert r.end_wealth_rappen < 0, name
        assert 0 <= r.max_drawdown_bps <= 10000, (
            f"{name}: Max-Drawdown {r.max_drawdown_bps} bps > 100 % -- misst "
            "Entnahmen statt Portfolio-Verlust"
        )


def test_mandate_drawdowns_match_flow_free_portfolio_index():
    """Befund-Zahlen: 49.0 % / 29.7 % / 15.3 % fuer die Mandats-Gewichte."""
    results = evaluate_stress_scenarios(
        weights=MANDATE_WEIGHTS,
        initial_wealth_rappen=MANDATE_WEALTH_RAPPEN,
        cashflow_series_rappen=HEAVY_WITHDRAWALS,
        liability_path_rappen=None,
        horizon_years=HORIZON,
    )
    expected_pct = {
        "great_depression_1929": 49.0,
        "financial_crisis_2008": 29.7,
        "covid_inflation_2020_2022": 15.3,
    }
    for name, pct in expected_pct.items():
        hand_dd, hand_cum = _hand_index_drawdown_bps(
            MANDATE_WEIGHTS, STRESS_SCENARIOS[name]
        )
        assert round(hand_dd / 100, 1) == pct  # Befund-Zahl selbst nachgerechnet
        r = results[name]
        assert abs(r.max_drawdown_bps - hand_dd) <= 1, (name, r.max_drawdown_bps, hand_dd)
        assert abs(r.cumulative_return_bps - hand_cum) <= 1, (name, r.cumulative_return_bps, hand_cum)


# ---------------------------------------------------------------------------
# 2. Kontrolle ohne Krise muss von der Krise unterscheidbar sein
# ---------------------------------------------------------------------------


def test_no_crisis_control_shows_zero_drawdown_and_zero_impact():
    results = evaluate_stress_scenarios(
        weights=MANDATE_WEIGHTS,
        initial_wealth_rappen=MANDATE_WEALTH_RAPPEN,
        cashflow_series_rappen=HEAVY_WITHDRAWALS,
        liability_path_rappen=None,
        horizon_years=HORIZON,
        scenarios=_scenarios_with_control(),
    )
    control = results["no_crisis_control"]
    assert control.max_drawdown_bps == 0, (
        f"Kontrolle ohne Krise zeigt {control.max_drawdown_bps} bps Drawdown -- "
        "der Wert misst Padding/Entnahmen, nicht die Krise"
    )
    assert control.cumulative_return_bps == 0
    assert control.crisis_impact_end_wealth_rappen == 0
    assert control.baseline_end_wealth_rappen == control.end_wealth_rappen
    # Jede echte Krise kostet etwas und hat einen Drawdown > 0
    for name in STRESS_SCENARIOS:
        assert results[name].max_drawdown_bps > 0, name
        assert results[name].crisis_impact_end_wealth_rappen < 0, name
        # Baseline ist szenariounabhaengig (gleiche Flows, gleiches Padding)
        assert results[name].baseline_end_wealth_rappen == control.end_wealth_rappen


# ---------------------------------------------------------------------------
# 3. Von Hand: 100 % Aktien
# ---------------------------------------------------------------------------


def test_all_equity_2008_by_hand():
    """Index 0.62 -> 0.62*1.25 = 0.775 -> 0.775*1.10 = 0.8525.

    Peak bleibt 1.0 (Start), Trough 0.62 -> Max-DD 38 % = 3800 bps.
    Kumuliert 0.8525 - 1 = -14.75 % = -1475 bps.
    Krisen-Effekt bei Entnahmen erst NACH den Krisenjahren: das Vermoegen
    ist waehrend der Krise positiv, danach Faktor 1.0 in Krise und Baseline,
    also bleibt die Differenz additiv: A * (0.8525 - 1).
    """
    A = 1_000_000_00
    horizon = 20
    flows = [0, 0, 0] + [-150_000_00] * (horizon - 3)  # Vermoegen wird negativ
    r = evaluate_stress_scenarios(
        weights=ALL_EQUITY,
        initial_wealth_rappen=A,
        cashflow_series_rappen=flows,
        liability_path_rappen=None,
        horizon_years=horizon,
    )["financial_crisis_2008"]
    assert r.max_drawdown_bps == 3800
    assert r.cumulative_return_bps == -1475
    assert r.baseline_end_wealth_rappen == A - 17 * 150_000_00
    assert r.crisis_impact_end_wealth_rappen == -147_500_00
    assert r.end_wealth_rappen == r.baseline_end_wealth_rappen - 147_500_00


def test_all_equity_1929_by_hand():
    """0.55 -> 0.4125 -> 0.37125 -> 0.3898125 -> 0.42879375.

    Trough 0.37125 gegen Peak 1.0 -> 62.875 % = 6287.5 bps (+-1 Rundung).
    Kumuliert 0.42879375 - 1 = -57.120625 % = -5712.0625 bps -> -5712.
    """
    r = evaluate_stress_scenarios(
        weights=ALL_EQUITY,
        initial_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[-400_000_00] * 10,
        liability_path_rappen=None,
        horizon_years=10,
    )["great_depression_1929"]
    assert abs(r.max_drawdown_bps - 6287.5) <= 1
    assert r.cumulative_return_bps == -5712


def test_peak_inside_crisis_path_counts():
    """Drawdown vom Zwischen-Hoch: COVID 100 % Aktien 0.90 -> 1.08 -> 0.8856.

    Peak 1.08 (Jahr 2), Trough 0.8856 -> (1.08-0.8856)/1.08 = 18 % = 1800 bps.
    """
    r = evaluate_stress_scenarios(
        weights=ALL_EQUITY,
        initial_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 4,
        liability_path_rappen=None,
        horizon_years=4,
    )["covid_inflation_2020_2022"]
    assert r.max_drawdown_bps == 1800


def test_dict_carries_new_fields_and_keeps_old_ones():
    results = evaluate_stress_scenarios(
        weights=MANDATE_WEIGHTS,
        initial_wealth_rappen=MANDATE_WEALTH_RAPPEN,
        cashflow_series_rappen=HEAVY_WITHDRAWALS,
        liability_path_rappen=None,
        horizon_years=HORIZON,
    )
    payload = stress_results_to_dict(results)
    for name in STRESS_SCENARIOS:
        row = payload[name]
        for key in (
            "scenario_name",
            "end_wealth_rappen",
            "min_year_wealth_rappen",
            "max_drawdown_bps",
            "cumulative_return_bps",
            "baseline_end_wealth_rappen",
            "crisis_impact_end_wealth_rappen",
        ):
            assert key in row, (name, key)
            if key != "scenario_name":
                assert isinstance(row[key], int), (name, key)
