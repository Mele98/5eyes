"""AA-UX-HONEST-FAN-001 -- "Ehrlicher Faecher" in App und Report identisch.

UX-Audit Asset Allocation, Signature-Verbesserung 1: Endwerte direkt am
rechten Rand ("2.41 Mio. · Median"), Zielmarker als Pille mit
Erfolgswahrscheinlichkeit ("Ruhestand · 82 %"), Klartext-Satz aus P10/P90
des Endjahres, Ziel oberhalb der Skala als "▲ Zielwert über Skala" -- und
nichts davon, solange das Gate (App: Strategie veraltet/keine Strategie;
Report: projections_hidden) greift.

* Falltabelle reporting/src/lib/fanAnnotations.contract.json gegen die
  gleichnamigen Monolith-Funktionen UND gegen fanAnnotations.ts (Node mit
  Type-Stripping): beide muessen die Tabelle exakt treffen.
* Verhalten des Chart.js-Plugins (aaDrawFanAnnotations) mit einem
  aufzeichnenden Fake-Canvas, Klartext-Satz, Zielmarker und Skala-Erweiterung
  werden mit den echten, aus 5eyes_v2.html extrahierten Funktionen
  ausgefuehrt (Node), nicht per Quelltext-Grep.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = ROOT / "5eyes-electron" / "frontend" / "5eyes_v2.html"
LIB = ROOT / "5eyes-electron" / "frontend" / "reporting" / "src" / "lib"
FAN_TS = LIB / "fanAnnotations.ts"
CONTRACT = LIB / "fanAnnotations.contract.json"
NBSP = " "

_TEXT_FNS = (
    "fmtLocaleCH", "fmtNumber", "fmtProbPct", "formatCompactCHFAmount",
    "_fanFinite", "fanEndLabelText", "fanGoalPillText", "fanAboveScaleText",
    "fanRangeSentence", "fanSpreadLabelYs", "fanGoalProbability",
)
_APP_FNS = _TEXT_FNS + (
    "arrMin", "arrMax", "projectionChartValues", "_projAxisConfig",
    "hasVisibleStrategyOutputs", "aaFanAnnotationsHidden", "aaFanGoalMarkers",
    "_aaFanByKey", "renderAaFanRangeSentence", "_aaFanRoundRect",
    "aaDrawFanAnnotations", "syncAaProjectionAxisScales",
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _extract_function(src: str, name: str) -> str:
    match = re.search(r"\nfunction " + re.escape(name) + r"\(", src)
    assert match, f"Funktion {name} fehlt im Monolithen"
    start = match.start() + 1
    i = src.index("{", start)
    depth, j = 1, i + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
    return src[start:j]


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node not available")


def _run_js(fns: tuple[str, ...], body: str):
    _node()
    html = _html()
    script = "\n".join(_extract_function(html, n) for n in fns) + "\n" + body
    proc = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


_CONTRACT_RUNNER = """
var C=__CONTRACT__;
process.stdout.write(JSON.stringify({
  end:C.end_label_cases.map(function(c){return fanEndLabelText(c[0],c[1]);}),
  pill:C.goal_pill_cases.map(function(c){return fanGoalPillText(c[0],c[1]);}),
  pillEst:C.goal_pill_estimate_cases.map(function(c){return fanGoalPillText(c[0],c[1],c[2]);}),
  prob:C.goal_probability_cases.map(function(c){return fanGoalProbability(c[0],c[1]);}),
  above:C.above_scale_cases.map(function(c){return fanAboveScaleText(c[0]);}),
  sentence:C.range_sentence_cases.map(function(c){return fanRangeSentence(c[0],c[1],c[2]);}),
  spread:C.spread_cases.map(function(c){return fanSpreadLabelYs(c[0],c[1],c[2],c[3]);})
}));
"""


def _expected(c: dict) -> dict:
    return {
        "end": [x[2] for x in c["end_label_cases"]],
        "pill": [x[2] for x in c["goal_pill_cases"]],
        "pillEst": [x[3] for x in c["goal_pill_estimate_cases"]],
        "prob": [x[2] for x in c["goal_probability_cases"]],
        "above": [x[1] for x in c["above_scale_cases"]],
        "sentence": [x[3] for x in c["range_sentence_cases"]],
        "spread": [x[4] for x in c["spread_cases"]],
    }


def test_monolith_matches_fan_contract():
    c = _contract()
    out = _run_js(_TEXT_FNS, _CONTRACT_RUNNER.replace("__CONTRACT__", json.dumps(c)))
    assert out == _expected(c)


def test_report_matches_fan_contract_and_monolith(tmp_path):
    _node()
    c = _contract()
    runner = tmp_path / "run_fan_contract.mts"
    runner.write_text(
        "import * as F from " + json.dumps(FAN_TS.as_uri()) + ";\n"
        "const C = " + json.dumps(c) + ";\n"
        "process.stdout.write(JSON.stringify({"
        "end: C.end_label_cases.map((x: any) => F.fanEndLabelText(x[0], x[1])),"
        "pill: C.goal_pill_cases.map((x: any) => F.fanGoalPillText(x[0], x[1])),"
        "pillEst: C.goal_pill_estimate_cases.map((x: any) => F.fanGoalPillText(x[0], x[1], x[2])),"
        "prob: C.goal_probability_cases.map((x: any) => F.fanGoalProbability(x[0], x[1])),"
        "above: C.above_scale_cases.map((x: any) => F.fanAboveScaleText(x[0])),"
        "sentence: C.range_sentence_cases.map((x: any) => F.fanRangeSentence(x[0], x[1], x[2])),"
        "spread: C.spread_cases.map((x: any) => F.fanSpreadLabelYs(x[0], x[1], x[2], x[3]))"
        "}));\n",
        encoding="utf-8",
    )
    # fanAnnotations.ts importiert './format' ohne Endung (Vite-Aufloesung);
    # fuer Node eine Kopie mit expliziter .ts-Endung neben format.ts legen.
    fan_copy = tmp_path / "fanAnnotations.ts"
    fan_copy.write_text(
        FAN_TS.read_text(encoding="utf-8").replace(
            "from './format';", "from " + json.dumps((LIB / "format.ts").as_uri()) + ";"
        ),
        encoding="utf-8",
    )
    runner.write_text(
        runner.read_text(encoding="utf-8").replace(json.dumps(FAN_TS.as_uri()), json.dumps(fan_copy.as_uri())),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", str(runner)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    if proc.returncode != 0 and "strip-types" in proc.stderr:
        pytest.skip("Node ohne Type-Stripping")
    assert proc.returncode == 0, proc.stderr
    rep = json.loads(proc.stdout)
    assert rep == _expected(c)
    mono = _run_js(_TEXT_FNS, _CONTRACT_RUNNER.replace("__CONTRACT__", json.dumps(c)))
    assert rep == mono


# --------------------------------------------------------------------------
# App-Verhalten mit den echten Monolith-Funktionen
# --------------------------------------------------------------------------

_APP_HARNESS = r"""
var calls=[];
function mkCtx(){
  var c={font:'',fillStyle:'',strokeStyle:'',textAlign:'',textBaseline:'',lineWidth:1,globalAlpha:1};
  ['save','restore','beginPath','moveTo','lineTo','stroke','fill','closePath','arc','setLineDash'].forEach(function(k){c[k]=function(){};});
  c.measureText=function(t){return {width:String(t).length*5.6};};
  c.fillText=function(t,x,y){calls.push({t:String(t),x:x,y:y});};
  return c;
}
function _acIsDarkTheme(){return false;}
function chartAxisColor(){return '#5a6577';}
function loadIstHorizonOverride(){return null;}
var sentenceEl={textContent:'',style:{display:''}};
var document={getElementById:function(id){return id==='aa-fan-range-sentence'?sentenceEl:null;}};
var labels=[];for(var y=2026;y<=2050;y++)labels.push(String(y));
function lin(a,b){return labels.map(function(_,i){return Math.round(a+(b-a)*i/(labels.length-1));});}
// Serien in K (Tausend CHF) wie simulationSeriesK: P10 1.6 Mio, Median 2.41 Mio, P90 3.4 Mio
var datasets=[
  {scenarioKey:'p90',data:lin(2000,3400)},
  {scenarioKey:'p50',data:lin(2000,2410),borderColor:'#8A6A1F'},
  {scenarioKey:'p10',data:lin(2000,1600)}
];
var yMax=4000;
function mkChart(goals){
  return {ctx:mkCtx(),chartArea:{left:60,right:500,top:20,bottom:340},
    data:{labels:labels.slice(),datasets:datasets},
    scales:{x:{getPixelForValue:function(i){return 60+i*(440/(labels.length-1));}},
            y:{max:yMax,getPixelForValue:function(v){return 340-(v/yMax)*320;}}},
    $fanGoals:goals};
}
var ALLOC={buckets:[{asset_class:'Aktien'}],goal_analysis:[
  {goal_id:'r',label:'Ruhestand',target_amount_rappen:220000000,target_date:'2040-01-01',path_success_rate_pct:82},
  {goal_id:'s',label:'Stiftung',target_amount_rappen:5000000000,target_date:'2045-06-30',path_success_rate_pct:31},
  {goal_id:'n',label:'Ohne Wert',target_amount_rappen:100000000,target_date:'2030-01-01'},
  {goal_id:'x',label:'Rendite',target_amount_rappen:0,target_date:'2030-01-01',path_success_rate_pct:90},
  {goal_id:'h',label:'Spaeter',target_amount_rappen:100000000,target_date:'2070-01-01',path_success_rate_pct:90},
  {goal_id:'l',label:'Alt',target_amount_rappen:100000000,target_date:'2032-01-01',path_success_rate_pct:57},
  {goal_id:'o',label:'Draussen',target_amount_rappen:100000000,target_date:'2034-01-01',path_success_rate_pct:57}
],goal_achievability:[
  {goal_id:'r',probability:0.79,evaluation_scope:'priority_funded',outside_simulation_horizon:false},
  {goal_id:'l',probability:0.4,evaluation_scope:'legacy_aggregate_unknown'},
  {goal_id:'o',probability:0,evaluation_scope:'priority_funded',outside_simulation_horizon:true},
  {goal_id:null,probability:0.66,evaluation_scope:'joint_plan'}
]};
var strategyState={allocation:ALLOC,dirty:false,staleNotice:null};
var charts={};
"""


def _app(scenario: str):
    return _run_js(_APP_FNS, _APP_HARNESS + scenario)


def test_goal_markers_from_goal_analysis():
    out = _app(
        "process.stdout.write(JSON.stringify(aaFanGoalMarkers(ALLOC,labels)));"
    )
    # Rendite-Ziel ohne CHF-Wert und Ziel jenseits des Horizonts: kein Marker.
    assert [g["id"] for g in out] == ["r", "s", "n", "l", "o"]
    by = {g["id"]: (g["prob"], g["estimate"]) for g in out}
    # CIO-Entscheid: kanonisch goal_achievability (priority_funded) = Report-Wert,
    # NICHT path_success_rate_pct (82) der Simulation.
    assert by["r"] == (79, False)
    assert out[0]["index"] == 14 and out[0]["valueK"] == 2200
    # Keine publizierte Evidenz -> Simulationswert als Schaetzung.
    assert by["s"] == (31, True)
    assert by["l"] == (57, True)  # nur Altbewertung -> Schaetzung
    # Priorisiert, aber ausserhalb des Horizonts -> nur Label.
    assert by["o"] == (None, False)
    assert by["n"] == (None, False)


def test_fresh_strategy_draws_end_labels_pills_and_above_scale():
    out = _app(
        "var ch=mkChart(aaFanGoalMarkers(ALLOC,labels));aaDrawFanAnnotations(ch);"
        "process.stdout.write(JSON.stringify(calls));"
    )
    texts = [c["t"] for c in out]
    assert "3.40 Mio. · P90" in texts
    assert "2.41 Mio. · Median" in texts
    assert "1.60 Mio. · P10" in texts
    assert f"Ruhestand · 79{NBSP}%" in texts
    assert f"Stiftung · ~31{NBSP}%" in texts
    assert "Draussen" in texts
    assert "Ohne Wert" in texts  # keine erfundene Prozentzahl
    assert "▲ CHF 50.00 Mio. über Skala" in texts
    ends = [c for c in out if c["t"].endswith(("· P90", "· Median", "· P10"))]
    # rechts vom Plot (area.right=500) und ohne Ueberlappung
    assert all(c["x"] > 500 for c in ends)
    ys = sorted(c["y"] for c in ends)
    assert all(b - a >= 12 for a, b in zip(ys, ys[1:]))
    assert not any(re.search(r"garant", t, re.I) for t in texts)


def test_stale_strategy_draws_nothing_and_hides_sentence():
    out = _app(
        "strategyState.dirty=true;strategyState.staleNotice='Bandbreiten aktualisiert: Strategie neu berechnen.';"
        "charts.opt=mkChart(aaFanGoalMarkers(ALLOC,labels));"
        "aaDrawFanAnnotations(charts.opt);renderAaFanRangeSentence();"
        "process.stdout.write(JSON.stringify({calls:calls,s:sentenceEl.textContent,d:sentenceEl.style.display}));"
    )
    assert out == {"calls": [], "s": "", "d": "none"}


def test_no_strategy_draws_nothing():
    out = _app(
        "strategyState.allocation=null;aaDrawFanAnnotations(mkChart([]));"
        "process.stdout.write(JSON.stringify(calls));"
    )
    assert out == []


def test_range_sentence_from_end_year_p10_p90():
    out = _app(
        "charts.opt=mkChart([]);renderAaFanRangeSentence();"
        "process.stdout.write(JSON.stringify({s:sentenceEl.textContent,d:sentenceEl.style.display}));"
    )
    assert out == {
        "s": "In 8 von 10 Verläufen liegt Ihr Vermögen 2050 zwischen CHF 1.60 und 3.40 Mio.",
        "d": "",
    }


def test_sentence_needs_p10_p90_fan():
    out = _app(
        "datasets=[{scenarioKey:'p50',data:lin(2000,2410)}];charts.opt=mkChart([]);renderAaFanRangeSentence();"
        "aaDrawFanAnnotations(charts.opt);"
        "process.stdout.write(JSON.stringify({s:sentenceEl.textContent,calls:calls.map(function(c){return c.t;})}));"
    )
    assert out["s"] == ""
    assert out["calls"] == ["2.41 Mio. · Median"]


def test_goal_up_to_twice_fan_max_extends_shared_scale_higher_goal_does_not():
    scenario = (
        "function mk(goals){return {data:{labels:labels.slice(),datasets:datasets},"
        "options:{scales:{y:{}}},update:function(){},$fanGoals:goals};}"
        "function run(goals){charts.opt=mk(goals);charts.aaCurrent=mk([]);"
        "syncAaProjectionAxisScales();return charts.opt.options.scales.y.max;}"
        "var base=run([]);"
        "var near=run([{index:10,valueK:6000}]);"   # < 2x 3400
        "var far=run([{index:10,valueK:50000}]);"   # > 2x 3400
        "process.stdout.write(JSON.stringify({base:base,near:near,far:far,"
        "same:charts.opt.options.scales.y.max===charts.aaCurrent.options.scales.y.max}));"
    )
    out = _app(scenario)
    assert out["near"] > out["base"]
    assert out["near"] >= 6000
    assert out["far"] == out["base"]
    assert out["same"] is True


def test_plugin_wired_to_soll_and_ist_fan_charts_with_label_margin():
    html = _html()
    for chart_id in ("ch-aa-current", "ch-opt"):
        start = html.index(f"const el=document.getElementById('{chart_id}');")
        block = html[start:html.index("});", start)]
        assert "plugins:[aaFanAnnotationPlugin]" in block, chart_id
        assert "aaFanChartOptions(" in block, chart_id
    assert 'id="aa-fan-range-sentence"' in html
