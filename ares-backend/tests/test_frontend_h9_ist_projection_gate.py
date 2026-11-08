"""H9 -- Vermoegensentwicklung "heute" ohne erfundene optimierte Kurve.

Owner-Vorgabe (2026-11-08): Im Vermoegens-/Cashflow-Schritt (Grafik ``#ch-ist``,
VOR Risikoprofil und Asset Allocation) erscheint die verbesserte/optimierte
Kurve nur, wenn fuer das Mandat eine gueltige, nicht veraltete Strategie
existiert (berechnete Soll-Allokation mit Simulation + aktuelles Risikoprofil +
kein offener Stale-Hinweis). Sonst nur die IST-Entwicklung -- ohne Default-
Profil und ohne pauschale Mehrrendite.

Die Tests fuehren die echten Funktionen aus dem Monolithen-Bundle
(``ares.html`` + ``ist-projection-gate.js``) in Node aus.
"""
from __future__ import annotations

import pytest
from tests.livetest_monolith_js import html, run_js
from tests.monolith_source import FRONTEND_DIR

GATE_FUNCS = (
    "istProjectionStrategyValid",
    "istProjectionHasOverlay",
    "renderIstStrategyOverview",
    "renderIstWithoutStrategy",
    "syncIstProjectionStrategyGate",
)

PRELUDE = r"""
var calls={overview:0,wealthOnly:0};
function mkChart(){return {data:{labels:[],datasets:[{label:'x',data:[]}]},options:{plugins:{legend:{display:false}}},
  update:function(){this.updated=(this.updated||0)+1;}};}
var charts={ist:mkChart(),opt:null,aaCurrent:null};
function loadIstHorizonOverride(){return null;}
function projectionHorizonYears(){return 3;}
function projectionYearLabels(r,h,labels){return labels||['2026','2027','2028','2029'];}
function buildCurrentBaselineProjection(){return {seriesK:[100,101,102,103],projectedRappen:10300000000};}
function buildCurrentWealthProjection(){return {seriesK:[500,505,510,515],labels:['2026','2027','2028','2029'],
  projectedRappen:51500000000,expectedReturnBps:250,cagrBps:240,annualNetCashflowRappen:0};}
function buildImprovedTotalProjectionFromStrategy(){return {projectedRappen:53000000000,cagrBps:300};}
function simulationCagrBps(){return 410;}
function projectionHorizonYearLabel(){return '2029';}
function sollColor(){return '#1e4b8f';}
function applyDepletionMarkerToDataset(){}
function syncIstProjectionAxisScale(){}
function refreshIstGoalMarkers(){}
function normalizeProjectionChartsPresentation(){}
function syncAaProjectionAxisScales(){}
function wireProjectionChartHoverSync(){}
function renderOverviewProjectionSummary(c){calls.overview++;calls.lastTarget=c.targetProjectedRappen;}
function renderCurrentWealthOnlyProjectionSummary(){calls.wealthOnly++;}
var ALLOC={buckets:[{asset_class:'Aktien'}],simulation:{year_labels:['2026','2027','2028','2029'],
  target_mix_series_rappen:[10000000000,10600000000,11200000000,11800000000]}};
var strategyState=null;
var RISK={id:'ra-1',is_current:1};
"""

NEEDED = ("updateProjectionChartsFromSimulation", "simulationPayload", "simulationSeriesK")


def _run(scenario: str):
    return run_js(NEEDED, scenario, prelude=PRELUDE, optional=GATE_FUNCS)


def _overlay_after(state_js: str):
    return _run(
        "strategyState=" + state_js + ";"
        "updateProjectionChartsFromSimulation(strategyState.allocation);"
        "return {n:charts.ist.data.datasets.length,labels:charts.ist.data.datasets.map(function(d){return d.label;})};"
    )


def test_no_improved_curve_without_risk_profile():
    """Soll-Allokation (z. B. Altbestand) ohne gueltiges Risikoprofil -> nur IST."""
    out = _overlay_after("{allocation:ALLOC,risk:null,dirty:false}")
    assert out["n"] == 1, out
    assert out["labels"] == ["Ist-Situation (Gesamtvermögen)"]


def test_no_improved_curve_while_strategy_is_stale():
    out = _overlay_after("{allocation:ALLOC,risk:RISK,dirty:true,staleNotice:'Risikoprofil geändert'}")
    assert out["n"] == 1, out


def test_no_improved_curve_without_strategy():
    out = _overlay_after("{allocation:null,risk:RISK,dirty:true}")
    assert out["n"] == 1, out


def test_valid_strategy_keeps_improved_curve():
    out = _overlay_after("{allocation:ALLOC,risk:RISK,dirty:false,staleNotice:null}")
    assert out["n"] == 2, out
    assert out["labels"][1] == "Verbesserte Situation (SOLL)"


def test_stale_marking_removes_curve_and_recalc_restores_it():
    out = _run(
        "strategyState={allocation:ALLOC,risk:RISK,dirty:false,staleNotice:null};"
        "updateProjectionChartsFromSimulation(ALLOC);var before=charts.ist.data.datasets.length;"
        "strategyState.dirty=true;strategyState.staleNotice='Eingaben geändert';"
        "syncIstProjectionStrategyGate();var stale=charts.ist.data.datasets.length;var wo=calls.wealthOnly;"
        "strategyState.dirty=false;strategyState.staleNotice=null;"
        "syncIstProjectionStrategyGate();"
        "return {before:before,stale:stale,after:charts.ist.data.datasets.length,wealthOnly:wo,overview:calls.overview};"
    )
    assert out == {"before": 2, "stale": 1, "after": 2, "wealthOnly": 1, "overview": 1}


def test_mandate_switch_a_b_a_does_not_leak_improved_curve():
    """Mandatswechsel A (gueltige Strategie) -> B (ohne Strategie) -> A.

    Spiegelt loadClientById: strategyState wird fuer B zurueckgesetzt
    (allocation/risk null, dirty) und syncStrategyStaleView ruft das Gate; die
    Hydration von A setzt dirty=false und ruft das Gate erneut.
    """
    out = _run(
        "strategyState={allocation:ALLOC,risk:RISK,dirty:false,staleNotice:null};"
        "updateProjectionChartsFromSimulation(ALLOC);var a1=charts.ist.data.datasets.length;"
        "strategyState={allocation:null,recommendation:null,risk:null,dirty:true,staleNotice:null};"
        "syncIstProjectionStrategyGate();var b=charts.ist.data.datasets.length;"
        
        "updateProjectionChartsFromSimulation({simulation:ALLOC.simulation,buckets:ALLOC.buckets});"
        "var bAfterLateSim=charts.ist.data.datasets.length;"
        "strategyState={allocation:ALLOC,risk:RISK,dirty:false,staleNotice:null};"
        "syncIstProjectionStrategyGate();"
        "return {a1:a1,b:b,bAfterLateSim:bAfterLateSim,a2:charts.ist.data.datasets.length};"
    )
    assert out == {"a1": 2, "b": 1, "bAfterLateSim": 1, "a2": 2}, out


def test_overview_kpis_only_with_valid_strategy():
    out = _run(
        "strategyState={allocation:ALLOC,risk:null,dirty:false};"
        "renderIstStrategyOverview(ALLOC);var a={o:calls.overview,w:calls.wealthOnly,"
        "rein:document.getElementById('ub-return-rein').textContent};"
        "strategyState.risk=RISK;renderIstStrategyOverview(ALLOC);"
        "return {a:a,o:calls.overview,rein:document.getElementById('ub-return-rein').textContent,"
        "beratung:document.getElementById('ub-return-beratung').textContent};"
    )
    assert out["a"] == {"o": 0, "w": 1, "rein": ""}
    assert out["o"] == 1
    assert out["rein"] == "300.0 %" and out["beratung"] == "410.0 %"  # FAKE_DOM-fmtPct ohne bps-Skalierung


def test_no_invented_improvement_assumptions_in_bundle():
    """Keine pauschale Mehrrendite (Demo +1.2 pp) und kein 4.5-%-Platzhalterpfad."""
    src = html()
    assert "improvedRate" not in src
    assert "Math.pow(1.045" not in src
    assert ">CHF 6.1 Mio</div>" not in src and ">+700k</div>" not in src
    # Die Kennzahlen der verbesserten Situation laufen nur ueber das Gate.
    apply_src = src.split("function applyAllocationEngineResult(", 1)[1].split("\nfunction ", 1)[0]
    assert "renderOverviewProjectionSummary(" not in apply_src
    assert "renderIstStrategyOverview(result)" in apply_src


def test_wealth_only_summary_text_does_not_claim_an_improved_situation():
    src = html()
    body = src.split("function renderCurrentWealthOnlyProjectionSummary(", 1)[1].split("\nfunction ", 1)[0]
    assert "uebernimmt nur die optimierte" not in body
    assert "setText('ub-return-rein'" in body


@pytest.mark.parametrize("name", GATE_FUNCS)
def test_gate_lives_in_extracted_part(name):
    module = (FRONTEND_DIR / "ist-projection-gate.js").read_text(encoding="utf-8")
    assert f"function {name}(" in module
