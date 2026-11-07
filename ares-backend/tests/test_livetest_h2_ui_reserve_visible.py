"""Live-Test 2026-11 H2 (App) -- abgezogene Liquiditaetsreserve war unsichtbar.

Befund: Tortenmitte "CHF 150'000 BERATUNG", Klassenbetraege summierten auf
CHF 141'000 (Strategiebasis); mit Mindestreserve 50'000 auf 104'500. Die
Reserve (9'000 bzw. 45'500) stand weder in der Legende noch im Portfolio,
das Portfolio nannte 141'000 "Beratungsvermoegen total".

Getestet werden die echten Monolith-Funktionen (Node): Legende und
Portfolio-Kopf muessen die Reserve als eigene Zeile zeigen; Legende +
Reserve summieren auf das Beratungsvermoegen. Berechnung unveraendert.
"""
from __future__ import annotations

from tests.livetest_monolith_js import run_js

ALLOCATION = """
var strategyState={allocation:{advisory_wealth_rappen:15000000,strategy_base_rappen:10450000,
  buckets:[{asset_class:'Aktien'}]}};
var alloc=[
 {n:'Aktien',c:'#1',soll:46.7,chfTarget:48791},{n:'Obligationen',c:'#2',soll:39.0,chfTarget:40755},
 {n:'Immobilien',c:'#3',soll:5.0,chfTarget:5225},{n:'Alternative',c:'#4',soll:5.0,chfTarget:5225},
 {n:'Liquidität',c:'#5',soll:4.3,chfTarget:4504}];
var TOTAL=150000;
function currentAllocationInputSnapshot(){return {advisoryRappen:15000000};}
function donutCenterValueHtml(t){return 'CHF '+t;}
"""

PO_STUBS = """
function liveRebalancingPayload(){return null;}
function portfolioPriceQualityMeta(){return {label:'EOD',sub:'',color:''};}
function renderPortfolioRebalancingSummary(){}
function renderRecommendationWarnings(){}
function renderPortfolioSections(){}
function renderActionCards(){}
function renderEngineRuntimePanels(){}
function renderStrategySummary(){}
function normalizeVisibleMojibake(){}
"""


def test_donut_legend_lists_reserve_and_sums_to_advisory_wealth():
    out = run_js(
        ("buildDLegend",),
        "buildDLegend(); return {leg: document.getElementById('dnleg').innerHTML,"
        " center: document.getElementById('qs:.dcv').innerHTML};",
        prelude=ALLOCATION,
        optional=("allocationReserveBreakdown",),
    )
    leg = out["leg"]
    assert "Liquiditätsreserve" in leg, "Reserve fehlt in der Legende"
    assert "CHF 45'500" in leg
    # Klassen 104'500 + Reserve 45'500 = Tortenmitte 150'000
    assert out["center"] == "CHF 150000"
    assert "CHF 104'500" in leg and "CHF 150'000" in leg


def test_portfolio_header_shows_advisory_total_and_reserve():
    out = run_js(
        ("applyRecommendationEngineResult",),
        """
        strategyState.allocation.strategy_base_rappen=14100000;
        applyRecommendationEngineResult({advisory_wealth_rappen:15000000,investable_advisory_wealth_rappen:14100000,
          positions:[{}],average_ter_bps:23,warnings:[]});
        return {head: document.getElementById('po-advisory-wealth').textContent,
                note: document.getElementById('po-reserve-note').textContent,
                foot: document.getElementById('po-total-footer').textContent,
                footLabel: document.getElementById('po-total-footer-label').textContent};
        """,
        prelude=ALLOCATION + PO_STUBS,
        optional=("allocationReserveBreakdown", "renderPortfolioReserveNote"),
    )
    assert out["head"] == "CHF 150'000", "Kopf nennt das Umsetzungsvolumen als Beratungsvermoegen"
    assert "Liquiditätsreserve" in out["note"] and "CHF 9'000" in out["note"]
    assert out["foot"] == "CHF 141'000"
    assert "Strategiebasis" in out["footLabel"]
