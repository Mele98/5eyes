"""Live-Test 2026-11 M8/M9 (App) -- Prognose und Horizont im Review.

Befund: Prognose 2041 im Review CHF 160'944, in der AA-Grafik (Median)
CHF 171'000, im PDF CHF 170'504. Der Review las den deterministischen
Mix-Pfad (``simulation.target_mix_series_rappen``), Grafik und PDF den
Monte-Carlo-Median. Soll: eine Quelle (MC-Median inkl. Reserve-Sockel,
identisch zu ``renderAaProjectionEndValues`` und dem PDF), mit Jahr und
"Median" beschriftet. Horizont-Kachel nennt ihre Basis (Risikoprofil).
"""
from __future__ import annotations

from tests.livetest_monolith_js import html, run_js

PAYLOAD = """
var result={advisory_wealth_rappen:15000000,expected_return_bps:423,external_reserve_rappen:900000,
  simulation:{year_labels:[2026,2041],target_mix_series_rappen:[15000000,16094442]},
  monte_carlo:{year_labels:[2026,2041],reserve_accounting_basis:'economic_total_incl_external_reserve_v1',
    target_p50_series_rappen:[15000000,17050444]}};
"""

FUNCS = ("_rvHeroCommonChips", "simulationPayload", "monteCarloPayload", "simulationTerminalRappen",
         "projectionHorizonYearLabel", "projectionEndOfYearText", "aaReserveSockelRappen")


def test_review_chip_uses_monte_carlo_median_like_chart_and_pdf():
    out = run_js(FUNCS, PAYLOAD + "return _rvHeroCommonChips(result,[],[],[]);",
                 prelude="function projectionValueRappen(){return 0;}",
                 optional=("strategyMedianProjectionRappen",))
    chip = next(c for c in out if c.startswith("Prognose"))
    assert "170'504" in chip, chip  # MC-Median (wie PDF), nicht 160'944
    assert "Ende 2040" in chip and "Median" in chip  # H9 N2: Label 2041 = Ende 2040


def test_review_chip_does_not_add_reserve_twice_for_economic_basis():
    out = run_js(FUNCS, PAYLOAD + "delete result.monte_carlo.reserve_accounting_basis;"
                 "return _rvHeroCommonChips(result,[],[],[]);",
                 prelude="function projectionValueRappen(){return 0;}",
                 optional=("strategyMedianProjectionRappen",))
    chip = next(c for c in out if c.startswith("Prognose"))
    assert "179'504" in chip, chip  # alter Payload: Sockel wie in der Grafik addiert


def test_review_horizon_tile_names_basis():
    assert "Anlagehorizont (Risikoprofil)</div><div id=\"sr-horizon\"" in html()
