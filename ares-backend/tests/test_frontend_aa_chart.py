"""H6 -- Asset-Allocation-Grafik (aa-chart.js / aa-chart.css).

Owner-Feedback: die AA-Grafik soll ruhiger und kundenfreundlicher werden. Die
Darstellungslogik liegt als ausgelagerter Monolith-Teil in ``aa-chart.js``
(Bundle, Budget, Verbots-Guards wie die anderen Teile). Fachlich bleibt alles
gleich: Gewichte/Betraege/Bandbreiten kommen unveraendert aus der Engine.

Hier wird die Datenaufbereitung in Node gegen die echte Datei geprueft:
Sortierung, Rest-Rundung auf genau 100 % (auch Unterklassen = ihre Klasse),
stabile Farben je Klasse, Torte/Legende/SOLL-Quoten, reduzierte Bewegung.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from tests.monolith_source import FRONTEND_DIR, read_monolith_bundle

MODULE_PATH = FRONTEND_DIR / "aa-chart.js"
CSS_PATH = FRONTEND_DIR / "aa-chart.css"

HARNESS = r"""
var AC={eq:'#1F3A5F',bd:'#B39455',re:'#7A4A2E',alt:'#5E6B45',liq:'#8E97A8',oth:'#6B4E71'};
function assetClassKey(l){var k=String(l||'').toLowerCase();
  if(k.indexOf('aktie')>=0)return 'eq';if(k.indexOf('oblig')>=0)return 'bd';if(k.indexOf('immob')>=0)return 're';
  if(k.indexOf('altern')>=0)return 'alt';if(k.indexOf('liquid')>=0)return 'liq';return 'oth';}
function assetClassCssVar(l){return 'var(--ac-'+assetClassKey(l)+')';}
function fmtLocaleCH(n){var s=String(Math.round(Math.abs(Number(n)||0)));return (Number(n)<0?'-':'')+s.replace(/\B(?=(\d{3})+(?!\d))/g,"'");}
function formatRappen(r){return 'CHF '+fmtLocaleCH(Number(r||0)/100);}
var REDUCED=false;
var window={matchMedia:function(q){return {matches:REDUCED&&q.indexOf('reduce')>=0};}};
var __active=[];
var document={documentElement:{},querySelectorAll:function(){return [];},getElementById:function(){return null;}};
function getComputedStyle(){return {getPropertyValue:function(){return '#ffffff';}};}
var strategyState={allocation:{sub_allocations:[{asset_class:'Aktien',sub_asset_class:'Aktien Schweiz',target_weight_bps:3364}]}};
"""


def _run(script: str):
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    code = HARNESS + MODULE_PATH.read_text(encoding="utf-8") + "\nvar __r=(function(){" + script + "})();\nconsole.log(JSON.stringify(__r));"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(code)
        path = handle.name
    try:
        out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    finally:
        Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# Foundation-Case-Werte (Engine-Ausgabe, bps) als realistische Eingabe.
ITEMS = """[
 {name:'Liquidität',bps:263,color:AC.liq,amountChf:54023,subs:[{name:'Geldmarktfonds',bps:263}]},
 {name:'Aktien',bps:7477,color:AC.eq,amountChf:1535861,band:{min:6000,max:7500},
  subs:[{name:'Aktien Global',bps:2991},{name:'Aktien Schweiz',bps:3364},{name:'Aktien Europa',bps:748},{name:'Aktien Schwellenlaender',bps:374}]},
 {name:'Obligationen',bps:1091,color:AC.bd,amountChf:224104,subs:[{name:'Obligationen CHF IG',bps:667},{name:'Obligationen Global Hedged',bps:424}]},
 {name:'Alternative',bps:300,color:AC.alt,amountChf:61623,subs:[{name:'Gold / Rohstoffe',bps:300}]},
 {name:'Immobilien',bps:869,color:AC.re,amountChf:178503,subs:[{name:'Immobilien Schweiz',bps:695},{name:'Immobilien Global',bps:174}]}
]"""


def test_rows_sorted_by_weight_and_rounded_to_exactly_100():
    out = _run("var r=aaChartPrepare(" + ITEMS + ");return r.map(function(x){return [x.name,x.tenths,x.pct,x.subs.map(function(s){return [s.name,s.tenths]})];});")
    assert [r[0] for r in out] == ["Aktien", "Obligationen", "Immobilien", "Alternative", "Liquidität"]
    assert sum(r[1] for r in out) == 1000
    assert out[0][2] == "74.8 %"
    # Unterklassen ergeben genau ihre Klasse (vorher 33.6+29.9+7.5+3.7 = 74.7 neben 74.8).
    for _name, tenths, _pct, subs in out:
        assert sum(t for _n, t in subs) == tenths
    assert [n for n, _t in out[0][3]] == ["Aktien Schweiz", "Aktien Global", "Aktien Europa", "Aktien Schwellenlaender"]


def test_largest_remainder_property_on_many_inputs():
    out = _run(
        """
        var seed=7,bad=[];function rnd(){seed=(seed*1103515245+12345)%2147483648;return seed/2147483648;}
        for(var t=0;t<400;t++){
          var n=2+Math.floor(rnd()*8),w=[],left=10000;
          for(var i=0;i<n-1;i++){var v=Math.floor(rnd()*left*0.7);w.push(v);left-=v;}w.push(left);
          var r=aaChartRoundTenths(w),s=r.reduce(function(a,b){return a+b;},0);
          if(s!==1000)bad.push(['sum',w,r]);
          w.forEach(function(v,i){if(Math.abs(r[i]*10-v)>=10)bad.push(['dev',w,r]);if(v===0&&r[i]!==0)bad.push(['zero',w,r]);});
        }
        return {bad:bad.slice(0,3),thirds:aaChartRoundTenths([3333,3333,3334]),empty:aaChartRoundTenths([0,0]),target:aaChartRoundTenths([1,1,1],7)};
        """
    )
    assert out["bad"] == []
    assert out["thirds"] == [333, 333, 334]
    assert out["empty"] == [0, 0]
    assert sum(out["target"]) == 7


def test_ties_follow_fixed_class_order_and_colors_stay_with_their_class():
    out = _run(
        "var a=aaChartPrepare([{name:'Obligationen',bps:5000,color:AC.bd},{name:'Aktien',bps:5000,color:AC.eq}]);"
        "var b=aaChartPrepare([{name:'Aktien',bps:5000,color:AC.eq},{name:'Obligationen',bps:5000,color:AC.bd}]);"
        "var c=aaChartPrepare(" + ITEMS + ");"
        "return {a:a.map(function(r){return [r.name,r.color,r.cssColor]}),b:b.map(function(r){return r.name}),"
        "c:c.map(function(r){return [r.name,r.color]}),mix0:aaChartMix('#1F3A5F','#FFFFFF',0),mix1:aaChartMix('#1F3A5F','#FFFFFF',1),"
        "shade:[aaChartShadeStep(0,4),aaChartShadeStep(3,4),aaChartShadeStep(0,1)]};"
    )
    assert out["a"] == [["Aktien", "#1F3A5F", "var(--ac-eq)"], ["Obligationen", "#B39455", "var(--ac-bd)"]]
    assert out["b"] == ["Aktien", "Obligationen"]
    assert dict(out["c"]) == {"Aktien": "#1F3A5F", "Obligationen": "#B39455", "Immobilien": "#7A4A2E",
                              "Alternative": "#5E6B45", "Liquidität": "#8E97A8"}
    assert out["mix0"] == "#1F3A5F" and out["mix1"] == "#FFFFFF"
    assert out["shade"] == [0, 0.5, 0]


def test_donut_rings_cover_the_same_100_percent_and_pending_has_no_gap():
    out = _run(
        "var rows=aaChartPrepare(" + ITEMS + ");var ds=aaChartDonutDatasets(rows,'#FFFFFF');"
        "var p=aaChartDonutDatasets([],'#FFFFFF');"
        "return {rings:ds.map(function(d){return [d._aaRing,d.data.reduce(function(a,b){return a+b},0),d.data.length]}),"
        "cls:ds[1].backgroundColor,border:ds[1].borderColor,tip:[ds[1]._aaLabels[0],ds[1]._aaPct[0],ds[1]._aaAmt[0]],"
        "subLabel:ds[0]._aaLabels[0],pending:[p.length,p[0].borderWidth,p[0].data]};"
    )
    assert out["rings"] == [["sub", 10000, 10], ["class", 10000, 5]]
    assert out["cls"][0] == "#1F3A5F"
    assert out["border"] == "#FFFFFF"
    assert out["tip"] == ["Aktien", "74.8 %", "CHF 1'535'861"]
    assert out["subLabel"] == "Aktien · Aktien Schweiz"
    assert out["pending"] == [1, 0, [100]]


def test_incomplete_subclasses_are_not_stretched_to_the_class():
    out = _run(
        "var rows=aaChartPrepare([{name:'Aktien',bps:6000,color:AC.eq,subs:[{name:'Aktien Schweiz',bps:4000}]},"
        "{name:'Obligationen',bps:4000,color:AC.bd}]);var ds=aaChartDonutDatasets(rows,'#FFFFFF');"
        "return {sub:rows[0].subs[0].tenths,ring:ds[0].data,lbl:ds[0]._aaLabels};"
    )
    assert out["sub"] == 400  # 40.0 %, nicht auf 60 % hochgerechnet
    assert out["ring"] == [4000, 2000, 4000]
    assert out["lbl"][1] == "Aktien · ohne Unterklasse"


def test_reduced_motion_disables_animation():
    out = _run("var a=aaChartDonutConfig().options.animation;REDUCED=true;var b=aaChartDonutConfig().options.animation;"
               "return {a:!!a,b:b,legend:aaChartDonutConfig().options.plugins.legend.display};")
    assert out == {"a": True, "b": False, "legend": False}


def test_legend_shows_percent_and_chf_sorted_with_reserve_and_ring_note():
    out = _run(
        "return aaChartLegendHtml(" + ITEMS + ",{reserveRappen:64588600,strategyBaseRappen:205411400,advisoryRappen:270000000});"
    )
    out = html_lib.unescape(out)
    names = re.findall(r'class="aa-leg-name">([^<]+)<', out)
    assert names[:5] == ["Aktien", "Obligationen", "Immobilien", "Alternative", "Liquidität"]
    assert "74.8 %" in out and "CHF 1'535'861" in out
    assert 'id="alloc-legend-reserve"' in out and "CHF 645'886" in out
    assert "CHF 2'054'114" in out and "CHF 2'700'000" in out
    assert "Aussenring: Subanlageklassen" in out
    assert 'style="--aa-c:var(--ac-eq)"' in out


def test_quota_rows_show_band_with_target_marker_and_keep_toggle():
    out = _run(
        "var it=" + ITEMS + ";it[1].groupKey='table:Aktien';it[1].expanded=true;return aaChartQuotaHtml(it);"
    )
    assert out.index(">Aktien<") < out.index(">Obligationen<") < out.index(">Liquidität<")
    assert 'aria-label="Aktien: Bandbreite 60.0–75.0 %, Ziel 74.8 %"' in out
    assert 'class="aa-band-range" style="left:60%;width:15%"' in out
    assert 'class="aa-band-mark" style="left:74.77%"' in out
    assert 'data-allocation-group="table%3AAktien" aria-expanded="true"' in out
    assert "toggleAllocationTableGroup(decodeURIComponent(this.getAttribute(" in out
    assert "33.7 %" in out  # Unterklassen per Rest-Rundung auf 74.8 %
    assert "color-mix(in srgb, var(--ac-eq) 50%, var(--surface))" in out


def test_monolith_delegates_donut_legend_and_quota_to_aa_chart():
    html = read_monolith_bundle()
    assert "function aaChartPrepare(" in html  # Teil des Bundles
    assert "charts.dn=new Chart(el.getContext('2d'),aaChartDonutConfig());" in html
    sync = html.split("function syncAllocationDonutFromStrategyState(", 1)[1].split("\nlet charts=", 1)[0]
    assert "aaChartApplyDonut(charts.dn,hasStrategy)" in sync
    legend = html.split("function buildDLegend(){", 1)[1].split("function syncAllocationDonutFromStrategyState", 1)[0]
    assert "aaChartLegendHtml(" in legend
    at = html.split("function buildAT(){", 1)[1].split("\n}", 1)[0]
    assert "aaChartQuotaHtml(aaChartAllocItems())" in at
    # refreshThemedChartColors laeuft weiter ueber syncAllocationDonutFromStrategyState.
    assert "syncAllocationDonutFromStrategyState();" in html.split("function refreshThemedChartColors(){", 1)[1].split("\nfunction ", 1)[0]


def test_aa_chart_files_stay_self_contained_and_neutral():
    js = MODULE_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")
    for text in (js, css):
        assert not re.search(r"https?://|//cdn|@import", text), "keine externen Verweise"
        assert "localStorage" not in text and "sessionStorage" not in text
        assert "box-shadow:0 10px" not in text  # keine Schatten-Spielereien
    # Nur Ares-Tokens fuer Flaechen/Text (keine fest verdrahteten Hex-Farben im CSS).
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", css)
    assert "prefers-reduced-motion" in css and "aaChartReducedMotion" in js
