"""H6 -- Asset-Allocation-Grafik (aa-chart.js / aa-chart.css).

Owner-Feedback: die AA-Grafik soll ruhiger und kundenfreundlicher werden. Die
Darstellungslogik liegt als ausgelagerter Monolith-Teil in ``aa-chart.js``
(Bundle, Budget, Verbots-Guards wie die anderen Teile). Fachlich bleibt alles
gleich: Gewichte/Betraege/Bandbreiten kommen unveraendert aus der Engine.

Rundung (H6-Nachtrag, FIDLEG/Dokumentation): dieselbe Zahl muss in Maske, PDF
und Portfolio gleich erscheinen. Die PDFs runden jede Zahl einzeln mit Python
``f"{bps/100:.1f}"``; Maske (aa-chart) und ``fmtPct`` (Portfolio u. a.) werden
hier gegen genau diese Python-Ausgabe fuer alle ganzen bps geprueft. Ergeben die
gerundeten Anteile nicht 100.0 % bzw. ihre Klasse, steht ein Hinweis dabei.
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
from tests.livetest_monolith_js import extract_function
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
var document={documentElement:{},querySelectorAll:function(){return [];},getElementById:function(){return null;}};
function getComputedStyle(){return {getPropertyValue:function(){return '#ffffff';}};}
var strategyState={allocation:{sub_allocations:[{asset_class:'Aktien',sub_asset_class:'Aktien Schweiz',target_weight_bps:3364}]}};
"""


def _node(code: str):
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(code)
        path = handle.name
    try:
        out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    finally:
        Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _run(script: str, prelude: str = ""):
    return _node(HARNESS + prelude + MODULE_PATH.read_text(encoding="utf-8")
                 + "\nvar __r=(function(){" + script + "})();\nconsole.log(JSON.stringify(__r));")


# Foundation-Case-Werte (Engine-Ausgabe, bps) als realistische Eingabe.
ITEMS = """[
 {name:'Liquidität',bps:263,color:AC.liq,amountChf:54023,subs:[{name:'Geldmarktfonds',bps:263}]},
 {name:'Aktien',bps:7477,color:AC.eq,amountChf:1535861,band:{min:6000,max:7500},
  subs:[{name:'Aktien Global',bps:2991},{name:'Aktien Schweiz',bps:3364},{name:'Aktien Europa',bps:748},{name:'Aktien Schwellenlaender',bps:374}]},
 {name:'Obligationen',bps:1091,color:AC.bd,amountChf:224104,subs:[{name:'Obligationen CHF IG',bps:667},{name:'Obligationen Global Hedged',bps:424}]},
 {name:'Alternative',bps:300,color:AC.alt,amountChf:61623,subs:[{name:'Gold / Rohstoffe',bps:300}]},
 {name:'Immobilien',bps:869,color:AC.re,amountChf:178503,subs:[{name:'Immobilien Schweiz',bps:695},{name:'Immobilien Global',bps:174}]}
]"""

_RANGE = range(-10000, 10001)


def _py_pct(bps: int, d: int = 1) -> str:
    """Referenz = PDF-Format (services/pdf: f"{bps/100:.1f}%")."""
    return f"{bps / 100:.{d}f}"


def _mask_and_fmtpct():
    src = read_monolith_bundle()
    code = (HARNESS + MODULE_PATH.read_text(encoding="utf-8") + "\n" + extract_function(src, "fmtNumber")
            + "\n" + extract_function(src, "fmtPct")
            + "\nvar o={mask:[],app:[]};for(var b=-10000;b<=10000;b++){o.mask.push(aaChartPctText(b));o.app.push(fmtPct(b,1));}"
            + "console.log(JSON.stringify(o));")
    return _node(code)


def test_mask_percent_is_identical_to_fmtpct_for_every_integer_bps():
    """Maske == Portfolio/Report (fmtPct, Zahlenformat-Vertrag AA-UX-FORMAT-001)."""
    out = _mask_and_fmtpct()
    diffs = [(b, m, a) for b, m, a in zip(_RANGE, out["mask"], out["app"]) if m != a]
    assert diffs == [], diffs[:5]


def test_mask_percent_equals_pdf_except_documented_exact_ties():
    """Maske == PDF (f"{bps/100:.1f}") fuer alle ganzen bps ausser der dokumentierten
    Altabweichung App <-> PDF bei echten Gleichstaenden |bps| % 100 == 25 (App rundet
    auf, Python auf gerade Ziffer). Angleichung in services/pdf ist Folgepunkt nach H1;
    aendert sich eine Seite, wird dieser Test rot."""
    out = _mask_and_fmtpct()
    diffs = []
    for b, got in zip(_RANGE, out["mask"]):
        num = float(got.replace("\u00a0%", "").replace("\u2212", "-"))
        if num != float(_py_pct(b)):
            diffs.append(b)
    assert diffs == [b for b in _RANGE if abs(b) % 100 == 25]
    assert len(diffs) == 200
    # Beispiel Foundation Case: keine Gleichstaende -> Maske, Portfolio und PDF gleich.
    for bps in (7477, 1091, 869, 300, 263, 3364, 2991, 748, 374, 667, 424, 695, 174):
        assert abs(bps) % 100 != 25


def test_rows_sorted_single_rounding_and_rounding_gap_flags():
    out = _run(
        "var r=aaChartPrepare(" + ITEMS + ");"
        "var t=aaChartPrepare([{name:'Aktien',bps:3333,color:AC.eq},{name:'Obligationen',bps:3333,color:AC.bd},{name:'Immobilien',bps:3334,color:AC.re}]);"
        "return {rows:r.map(function(x){return [x.name,x.pct,x.subs.map(function(s){return [s.name,s.pct,s.seg]}),x.subRoundingGap]}),"
        "gap:r.roundingGap,subGap:r.subRoundingGap,thirds:[t.roundingGap,t.map(function(x){return x.pct})]};"
    )
    rows = out["rows"]
    assert [r[0] for r in rows] == ["Aktien", "Obligationen", "Immobilien", "Alternative", "Liquidität"]
    assert rows[0][1] == "74.8 %"
    # Einzelrundung wie PDF/Portfolio: 33.6 (nicht 33.7); Summe 74.7 neben 74.8 -> Hinweis.
    assert rows[0][2] == [["Aktien Schweiz", "33.6 %", 0], ["Aktien Global", "29.9 %", 1],
                          ["Aktien Europa", "7.5 %", 2], ["Aktien Schwellenlaender", "3.7 %", 3]]
    assert rows[0][3] is True and out["subGap"] is True
    assert out["gap"] is False  # 74.8+10.9+8.7+3.0+2.6 = 100.0
    assert out["thirds"] == [True, ["33.3 %", "33.3 %", "33.3 %"]]
    # Segment-Indizes laufen ueber alle Klassen (Aussenring-Reihenfolge).
    segs = [s[2] for r in rows for s in r[2]]
    assert segs == list(range(len(segs)))


def test_ties_follow_fixed_class_order_and_colors_stay_with_their_class():
    out = _run(
        "var a=aaChartPrepare([{name:'Obligationen',bps:5000,color:AC.bd},{name:'Aktien',bps:5000,color:AC.eq}]);"
        "var c=aaChartPrepare(" + ITEMS + ");"
        "return {a:a.map(function(r){return [r.name,r.color,r.cssColor]}),"
        "c:c.map(function(r){return [r.name,r.color]}),mix0:aaChartMix('#1F3A5F','#FFFFFF',0),mix1:aaChartMix('#1F3A5F','#FFFFFF',1),"
        "shade:[aaChartShadeStep(0,4),aaChartShadeStep(3,4),aaChartShadeStep(0,1)]};"
    )
    assert out["a"] == [["Aktien", "#1F3A5F", "var(--ac-eq)"], ["Obligationen", "#B39455", "var(--ac-bd)"]]
    assert dict(out["c"]) == {"Aktien": "#1F3A5F", "Obligationen": "#B39455", "Immobilien": "#7A4A2E",
                              "Alternative": "#5E6B45", "Liquidität": "#8E97A8"}
    assert out["mix0"] == "#1F3A5F" and out["mix1"] == "#FFFFFF"
    assert out["shade"] == [0, 0.5, 0]


def test_donut_rings_cover_100_percent_and_sub_segments_are_named():
    out = _run(
        "var rows=aaChartPrepare(" + ITEMS + ");var ds=aaChartDonutDatasets(rows,'#FFFFFF');"
        "var p=aaChartDonutDatasets([],'#FFFFFF');var cfg=aaChartDonutConfig();"
        "var tt=cfg.options.plugins.tooltip.callbacks;"
        "return {rings:ds.map(function(d){return [d._aaRing,d.data.reduce(function(a,b){return a+b},0),d.data.length]}),"
        "cls:ds[1].backgroundColor,border:ds[1].borderColor,tip:[ds[1]._aaLabels[0],ds[1]._aaPct[0],ds[1]._aaAmt[0]],"
        "sub:[ds[0]._aaLabels[0],ds[0]._aaPct[0],ds[0]._aaLabels[9]],"
        "subTitle:tt.title([{dataset:ds[0]}]),subLabel:tt.label({dataset:ds[0],dataIndex:0}),"
        "seg0Color:ds[0].backgroundColor[rows[0].subs[1].seg],pending:[p.length,p[0].borderWidth,p[0].data]};"
    )
    assert out["rings"] == [["sub", 10000, 10], ["class", 10000, 5]]
    assert out["cls"][0] == "#1F3A5F" and out["border"] == "#FFFFFF"
    assert out["tip"] == ["Aktien", "74.8 %", "CHF 1'535'861"]
    assert out["sub"] == ["Aktien › Aktien Schweiz", "33.6 %", "Liquidität › Geldmarktfonds"]
    assert out["subTitle"] == "Subanlageklasse (Aussenring)"
    assert out["subLabel"] == "Aktien › Aktien Schweiz · 33.6 %"
    assert out["pending"] == [1, 0, [100]]


def test_incomplete_subclasses_are_not_stretched_to_the_class():
    out = _run(
        "var rows=aaChartPrepare([{name:'Aktien',bps:6000,color:AC.eq,subs:[{name:'Aktien Schweiz',bps:4000}]},"
        "{name:'Obligationen',bps:4000,color:AC.bd}]);var ds=aaChartDonutDatasets(rows,'#FFFFFF');"
        "return {sub:rows[0].subs[0].pct,ring:ds[0].data,lbl:ds[0]._aaLabels,gap:rows[0].subRoundingGap};"
    )
    assert out["sub"] == "40.0 %"  # nicht auf 60 % hochgerechnet
    assert out["ring"] == [4000, 2000, 4000]
    assert out["lbl"][1] == "Aktien › ohne Unterklasse"
    assert out["gap"] is False


def test_reduced_motion_disables_animation():
    out = _run("var a=aaChartDonutConfig().options.animation;REDUCED=true;var b=aaChartDonutConfig().options.animation;"
               "return {a:!!a,b:b,legend:aaChartDonutConfig().options.plugins.legend.display};")
    assert out == {"a": True, "b": False, "legend": False}


def test_legend_shows_percent_chf_bar_on_100_scale_and_reserve():
    out = html_lib.unescape(_run(
        "return aaChartLegendHtml(" + ITEMS + ",{reserveRappen:64588600,strategyBaseRappen:205411400,advisoryRappen:270000000});"
    ))
    names = re.findall(r'class="aa-leg-name">([^<]+)<', out)
    assert names[:5] == ["Aktien", "Obligationen", "Immobilien", "Alternative", "Liquidität"]
    assert "74.8 %" in out and "CHF 1'535'861" in out
    assert '<i style="width:74.77%">' in out  # Balken relativ zu 100 %
    assert 'id="alloc-legend-reserve"' in out and "CHF 645'886" in out
    assert "CHF 2'054'114" in out and "CHF 2'700'000" in out
    assert "Aussenring: Subanlageklassen" in out
    assert "Rundungsdifferenzen" not in out  # Klassen ergeben hier genau 100.0 %
    gap = html_lib.unescape(_run(
        "return aaChartLegendHtml([{name:'Aktien',bps:3333,color:AC.eq},{name:'Obligationen',bps:3333,color:AC.bd},{name:'Immobilien',bps:3334,color:AC.re}],null);"))
    assert "Rundungsdifferenzen möglich" in gap


def test_quota_rows_band_marker_ring_swatches_and_rounding_note():
    out = _run(
        "var it=" + ITEMS + ";it[1].groupKey='table:Aktien';it[1].expanded=true;return aaChartQuotaHtml(it);"
    )
    assert out.index(">Aktien<") < out.index(">Obligationen<") < out.index(">Liquidität<")
    assert 'aria-label="Aktien: Bandbreite 60.0–75.0 %, Ziel 74.8 %"' in out
    assert 'class="aa-band-range" style="left:60%;width:15%"' in out
    assert 'class="aa-band-mark" style="left:74.77%"' in out
    assert 'data-allocation-group="table%3AAktien" aria-expanded="true"' in out
    assert "toggleAllocationTableGroup(decodeURIComponent(this.getAttribute(" in out
    # Unterklasse = Segment im Aussenring (gleiche Farbe, gleicher Index).
    assert '<div class="aa-q-sub" data-aa-seg="0">' in out and "33.6 %" in out
    assert "color-mix(in srgb, var(--ac-eq) 50%, var(--surface))" in out
    assert "Aussenring der Torte" in out
    assert "Rundungsdifferenzen möglich" in out  # 33.6+29.9+7.5+3.7 = 74.7 neben 74.8


def test_pending_state_names_reason_and_offers_action_without_auto_run():
    out = _run(
        "return {stale:aaChartPendingHtml({notice:'Eingaben geändert: Strategie neu berechnen.',riskReady:true,baseText:'CHF 150\\'000'}),"
        "fresh:aaChartPendingHtml({notice:'',riskReady:true,baseText:'CHF 1'}),risk:aaChartPendingHtml({riskReady:false})};"
    )
    stale = html_lib.unescape(out["stale"])
    assert "Strategie veraltet" in stale and "Eingaben geändert" in stale and "CHF 150'000" in stale
    assert 'onclick="calculateInvestmentStrategy()"' in stale
    assert "noch nicht berechnet" in out["fresh"]
    assert "Risikoprofil fehlt" in out["risk"] and "go(" in out["risk"] and "calculateInvestmentStrategy" not in out["risk"]
    js = MODULE_PATH.read_text(encoding="utf-8")
    # Nur auf Klick: keine Berechnung beim Rendern.
    assert js.count("calculateInvestmentStrategy(") == 1


def test_context_card_keeps_every_statement_as_rows():
    out = _run(
        "var f=function(r){return 'CHF '+fmtLocaleCH(r/100);};"
        "return {a:aaChartContextHtml({rein:617000000,found:300000000,nonPos:false,uncovered:0,ber:270000000,base:205411400,reserve:64588600},f),"
        "b:aaChartContextHtml({rein:0,found:0,nonPos:true,uncovered:3000000,ber:10000000,base:10000000,reserve:0},f)};"
    )
    a = html_lib.unescape(out["a"])
    for label, value in (("Reinvermögen (gesamt, netto aller Verbindlichkeiten)", "CHF 6'170'000"),
                         ("davon Eigenheim-Fundament", "CHF 3'000'000"), ("Beratungsvermögen", "CHF 2'700'000"),
                         ("davon in der Anlagestrategie (diese Torte)", "CHF 2'054'114"),
                         ("Liquiditätsreserve ausserhalb der Anlagestrategie", "CHF 645'886")):
        assert f"<span>{label}</span><strong>{value}</strong>" in a, label
    b = html_lib.unescape(out["b"])
    assert "Verbindlichkeiten übersteigen die Aktiven – ungedeckte Schulden CHF 30'000. Kein positives Reinvermögen." in b
    assert "<span>Optimierbares Beratungsvermögen (diese Torte)</span><strong>CHF 100'000</strong>" in b


def test_monolith_delegates_donut_legend_quota_and_context_to_aa_chart():
    html = read_monolith_bundle()
    assert "function aaChartPrepare(" in html  # Teil des Bundles
    assert "charts.dn=new Chart(el.getContext('2d'),aaChartDonutConfig());" in html
    sync = html.split("function syncAllocationDonutFromStrategyState(", 1)[1].split("\nlet charts=", 1)[0]
    assert "aaChartApplyDonut(charts.dn,hasStrategy)" in sync and "aaChartContextHtml(" in sync
    legend = html.split("function buildDLegend(){", 1)[1].split("function syncAllocationDonutFromStrategyState", 1)[0]
    assert "aaChartLegendHtml(" in legend and "aaChartPendingHtml(" in legend
    at = html.split("function buildAT(){", 1)[1].split("\n}", 1)[0]
    assert "aaChartQuotaHtml(aaChartAllocItems())" in at
    stale = html.split("function syncStrategyStaleView(){", 1)[1].split("\n}", 1)[0]
    assert "buildDLegend()" in stale
    assert "syncAllocationDonutFromStrategyState();" in html.split("function refreshThemedChartColors(){", 1)[1].split("\nfunction ", 1)[0]
    # Kennzahlen-Karte mit kurzem Satz (Aussage unveraendert, linksbuendig).
    card = html.split('<div class="aa-ctx-card">', 1)[1].split("</div></div>", 1)[0]
    assert 'id="alloc-rein-context"' in card and "umgeschichtet werden kann" in card
    for word in ("Beratungsvermögen", "Fundament", "Reinvermögen", "Strategie, Ziele und Kennzahlen", "Reinvermögens-Kurve"):
        assert word in card, word


def test_aa_chart_files_stay_self_contained_and_neutral():
    js = MODULE_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")
    for text in (js, css):
        assert not re.search(r"https?://|//cdn|@import", text), "keine externen Verweise"
        assert "localStorage" not in text and "sessionStorage" not in text
        assert "box-shadow:0 10px" not in text  # keine Schatten-Spielereien
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", css)  # nur Ares-Tokens im CSS
    assert "prefers-reduced-motion" in css and "aaChartReducedMotion" in js


ZERO_ITEMS = """[
 {name:'Aktien',bps:6000,color:AC.eq,band:{min:5000,max:7000},subs:[{name:'Aktien Schweiz',bps:6000}]},
 {name:'Alternative',bps:0,color:AC.alt,band:{min:0,max:1000}},
 {name:'Obligationen',bps:4000,color:AC.bd,band:{min:3000,max:5000}},
 {name:'Immobilien',bps:0,color:AC.re}
]"""


def test_zero_percent_class_with_band_stays_in_quotas_but_not_in_donut_or_legend():
    """N-882-01: einheitlich -- Torte/Legende ohne 0-%-Klassen, SOLL-Quoten mit Band behalten."""
    out = _run(
        "var q=aaChartQuotaHtml(" + ZERO_ITEMS + ");var l=aaChartLegendHtml(" + ZERO_ITEMS + ",null);"
        "var ds=aaChartDonutDatasets(aaChartPrepare(" + ZERO_ITEMS + "),'#FFFFFF');"
        "var qr=aaChartPrepare(" + ZERO_ITEMS + ",true);"
        "return {q:q,l:l,labels:ds.map(function(d){return d._aaLabels}),"
        "rows:qr.map(function(r){return [r.name,r.pct,r.soloSeg,r.subs.map(function(s){return s.seg})]})};"
    )
    q = out["q"]
    assert ">Alternative<" in q and 'aria-label="Alternative: Bandbreite 0.0–10.0 %, Ziel 0.0 %"' in q
    assert ">Immobilien<" not in q  # ohne Band keine Zeile
    assert q.index(">Obligationen<") < q.index(">Alternative<")  # 0 % am Ende
    assert ">Alternative<" not in out["l"]
    assert all("Alternative" not in "".join(lbls) for lbls in out["labels"])
    # 0-%-Zeile belegt keinen Segment-Index (Quoten-Hover bleibt deckungsgleich mit der Torte).
    assert out["rows"] == [["Aktien", "60.0 %", None, [0]], ["Obligationen", "40.0 %", 1, []],
                           ["Alternative", "0.0 %", None, []]]


def test_canvas_mouseleave_resets_highlight_and_note_has_no_pdf_claim():
    js = MODULE_PATH.read_text(encoding="utf-8")
    apply_fn = js.split("function aaChartApplyDonut(", 1)[1].split("\nfunction ", 1)[0]
    assert "addEventListener('mouseleave'" in apply_fn and "aaChartMarkLegend(-1,-1)" in apply_fn
    note = _run("return aaChartRoundingNote();")
    assert note.startswith("Rundungsdifferenzen möglich") and "PDF" not in note


def test_small_text_contrast_tokens_and_compact_band_below_760px():
    css = CSS_PATH.read_text(encoding="utf-8")
    for sel in (".alloc-donut-card .section-kicker{", ".dcl{", ".aa-leg-head{"):
        rule = css.split(sel, 1)[1].split("}", 1)[0]
        assert "color:var(--n5)" in rule, sel  # Dark: 6.4:1 auf --surface
    mobile = css.split("@media(max-width:760px)", 1)[1].split("\n", 1)[0]
    assert ".aa-q-row .aa-band{display:none" not in mobile and ".aa-q-row .aa-band{grid-column:2/4" in mobile


def test_hover_on_zero_quota_row_activates_nothing_and_resets_marks():
    """N-882-07: 0-%-Quotenzeile ohne Segment -> kein Segment, Markierungen zurueck,
    auch wenn Chart.js beim Aktivieren wirft (Markierung ausserhalb des try)."""
    out = _run(
        """
        var quota=aaChartQuotaHtml(""" + ZERO_ITEMS + """);
        var zeroRow=(quota.match(/data-aa-row="(\d+)"[^>]*>(?:(?!<\/button>).)*>Alternative</)||[])[1];
        var ds=aaChartDonutDatasets(aaChartPrepare(""" + ZERO_ITEMS + """),'#FFFFFF');
        var T=function(r,s){return aaChartHoverTarget(ds,r,s);};
        var res={zeroRow:zeroRow,zero:T(zeroRow,null),valid:T('1',null),seg:T(null,'0'),segOut:T(null,'7'),junk:T('x',null),none:T(null,null)};
        // Integration: Handler mit Fake-Host/-Chart; Chart wirft beim zweiten Aufruf.
        var handlers={},marks=[],actives=[],calls=0;
        aaChartMarkLegend=function(r,s){marks.push([r,s]);};
        document.getElementById=function(){return {dataset:{},addEventListener:function(n,f){handlers[n]=f;}};};
        var chart={data:{datasets:ds},width:200,height:200,update:function(){},
          setActiveElements:function(a){calls++;actives.push(a);if(calls===2)throw new Error('chart');}};
        aaChartBindHover('at',chart);
        var el=function(attr,val){var o={getAttribute:function(k){return k===attr?val:null;}};
          o.closest=function(sel){return sel.indexOf(attr)>=0?o:null;};return o;};
        handlers.mouseover({target:el('data-aa-row','0')});
        handlers.mouseover({target:el('data-aa-row',zeroRow)});
        res.marks=marks;res.actives=actives.map(function(a){return a.length;});
        return res;
        """
    )
    assert out["zeroRow"] == "2"
    assert out["zero"] == {"active": [], "row": -1, "seg": -1}
    assert out["valid"]["active"] == [{"datasetIndex": 1, "index": 1}] and out["valid"]["row"] == 1
    assert out["seg"] == {"active": [{"datasetIndex": 0, "index": 0}], "row": 0, "seg": 0}
    assert out["segOut"]["active"] == [] and out["junk"]["active"] == [] and out["none"]["active"] == []
    # Erst Aktien markiert, dann 0-%-Zeile: Markierung zurueckgesetzt trotz Chart-Fehler.
    assert out["marks"] == [[0, -1], [-1, -1]]
    assert out["actives"] == [1, 0]
