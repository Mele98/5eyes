"""AA-UX-NUMBERS-001 -- Zahlen und Begriffe der Asset-Allocation-Ansicht.

Grundlage: UX-Audit Asset Allocation (origin/develop 3e9cfe3), P0-Befunde 1, 2,
4, 5 und 7. Diese Datei fuehrt die ECHTEN Monolith-Funktionen aus
``5eyes_v2.html`` in Node aus (nur DOM/Charts sind gefaked) und prueft:

1. ``formatCompactCHF``: CHF 2'850'000 -> "CHF 2.85 Mio." (vorher "CHF 2'85 Mio",
   der Apostroph ist in der Schweiz der Tausendertrenner). Kein statischer
   Fantasie-Platzhalter "CHF 2.85M" im Donut.
2. P90/P10 heissen "Guenstiges / Mittleres / Unguenstiges Szenario" statt
   "Best/Worst Case" (P10 ist keine Untergrenze), plus Fussnote; die
   Median-Differenz SOLL - IST wird neutral (nicht gruen) und als Differenz
   der Mediane ausgewiesen.
3. Die Wachstums-Zeile vergleicht SOLL und IST aus DERSELBEN Quelle
   (Monte-Carlo-Median-Pfad), nicht SOLL deterministisch vs. IST MC-Median.
4. Die Endwerte der Kennzahlen-Tabelle werden am gewaehlten Anzeige-Horizont
   gelesen und tragen das Jahr; kein hart codierter Fallback '2033'.
5. Das "Stressband" ist ehrlich als Volatilitaets-Multiplikator benannt
   (keine Krisennamen), sichtbare ASCII-Umlaute in der AA-Ansicht korrigiert.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HTML_PATH = (
    Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _extract_function(src: str, name: str) -> str:
    match = re.search(r"\n(?:async )?function " + re.escape(name) + r"\(", src)
    assert match, f"Funktion {name} fehlt im Monolithen"
    start = match.start() + 1
    i = src.index("{", start)
    depth, j = 1, i + 1
    while depth:
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        j += 1
    return src[start:j]


_FAKE_DOM = r"""
var __els={};
function __mkEl(id){
  return {id:id,textContent:'',innerHTML:'',title:'',style:{},
    previousElementSibling:null,
    setAttribute:function(k,v){this['attr_'+k]=String(v);},
    getAttribute:function(k){return this['attr_'+k]==null?null:this['attr_'+k];}};
}
var document={
  getElementById:function(id){if(!__els[id])__els[id]=__mkEl(id);return __els[id];},
  querySelector:function(sel){return document.getElementById('qs:'+sel);}
};
var __override=null;
function loadIstHorizonOverride(){return __override;}
function syncAaProjectionAxisScales(){}
function resultCashflowProjectionComponentSeries(){return [];}
function resultCashflowProjectionSeriesRappen(){return [];}
function escapeHtml(s){return String(s);}
var charts={};
function __mkChart(){return {data:{labels:[],datasets:[]},options:{plugins:{legend:{}}},update:function(){}};}
"""


def _run(names: tuple[str, ...], scenario_js: str):
    if shutil.which("node") is None:
        pytest.skip("node not available")
    src = _html()
    fns = "\n".join(_extract_function(src, name) for name in names)
    script = _FAKE_DOM + fns + "\nvar __out=(function(){" + scenario_js + "})();\nprocess.stdout.write(JSON.stringify(__out));"
    proc = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# Befund 1: formatCompactCHF + Donut-Platzhalter
# ---------------------------------------------------------------------------

_FMT = ("formatCompactCHFAmount", "formatCompactCHF")


def test_format_compact_chf_uses_point_as_decimal_separator():
    out = _run(
        _FMT,
        "return {a:formatCompactCHF(2850000),b:formatCompactCHF(1234567.8),"
        "c:formatCompactCHF(12500000),d:formatCompactCHF(1000000),"
        "e:formatCompactCHF(-2850000),f:formatCompactCHF(0),"
        "g:formatCompactCHF(12000),ref:(12000).toLocaleString('de-CH')};",
    )
    assert out["a"] == "CHF 2.85 Mio."
    assert out["b"] == "CHF 1.23 Mio."
    assert out["c"] == "CHF 12.50 Mio."
    assert out["d"] == "CHF 1.00 Mio."
    # Negative Millionen werden ebenfalls kompakt formatiert (vorher "CHF -2'850'000").
    assert out["e"] == "CHF −2.85 Mio."
    assert out["f"] == "CHF 0"
    # Unter 1 Mio.: unveraendert die de-CH-Tausendergruppierung der Laufzeit
    # (konsistent mit allen anderen toLocaleString('de-CH')-Formatern).
    assert out["g"] == "CHF " + out["ref"]
    for value in (out["a"], out["b"], out["c"]):
        assert "'" not in value and "’" not in value, value


def test_donut_center_has_no_fantasy_placeholder_and_uses_formatter():
    html = _html()
    assert "2.85M" not in html, "statischer Fantasiewert 'CHF 2.85M' im Donut"
    assert '<div class="dcv">—</div>' in html
    out = _run(
        _FMT + ("donutCenterValueHtml",),
        "return {a:donutCenterValueHtml(2850000),b:donutCenterValueHtml(0),"
        "c:donutCenterValueHtml(null),d:donutCenterValueHtml(450000),ref:(450000).toLocaleString('de-CH')};",
    )
    assert out["a"] == "CHF<br>2.85 Mio."
    assert out["b"] == "—"
    assert out["c"] == "—"
    assert out["d"] == "CHF<br>" + out["ref"]
    body = _extract_function(html, "buildDLegend")
    assert "donutCenterValueHtml(" in body
    assert ".replace('.',\"'\")" not in body


# ---------------------------------------------------------------------------
# Befund 2: Szenario-Benennung + Fussnote + neutrale Median-Differenz
# ---------------------------------------------------------------------------

_P90 = "Günstiges Szenario (P90)"
_P50 = "Mittleres Szenario (Median)"
_P10 = "Ungünstiges Szenario (P10)"

_MC_RESULT_JS = r"""
var years=[];for(var y=2026;y<=2056;y++)years.push(y);
function ser(start,step){return years.map(function(_,i){return start+step*i;});}
var result={
  external_reserve_rappen:0,
  simulation:{year_labels:years,target_mix_series_rappen:ser(100000000,9000000)},
  monte_carlo:{year_labels:years,
    target_p90_series_rappen:ser(100000000,8000000),
    target_p50_series_rappen:ser(100000000,5000000),
    target_p10_series_rappen:ser(100000000,2000000),
    current_p90_series_rappen:ser(100000000,6000000),
    current_p50_series_rappen:ser(100000000,3000000),
    current_p10_series_rappen:ser(100000000,1000000)}
};
"""

_CHART_FNS = (
    "aaScenarioLabel",
    "simulationPayload",
    "monteCarloPayload",
    "simulationSeriesK",
    "aaReserveSockelRappen",
    "upgradeFanChartWithMonteCarlo",
    "upgradeCurrentAaChartWithMonteCarlo",
)


def test_fan_charts_use_scenario_names_not_best_worst_case():
    out = _run(
        _CHART_FNS,
        _MC_RESULT_JS
        + "charts.opt=__mkChart();charts.aaCurrent=__mkChart();"
        "upgradeFanChartWithMonteCarlo(result);upgradeCurrentAaChartWithMonteCarlo(result);"
        "return {opt:charts.opt.data.datasets.map(function(d){return [d.label,d.scenarioKey];}),"
        "cur:charts.aaCurrent.data.datasets.map(function(d){return [d.label,d.scenarioKey];})};",
    )
    expected = [[_P90, "p90"], [_P50, "p50"], [_P10, "p10"]]
    assert out["opt"] == expected
    assert out["cur"] == expected


def test_no_best_worst_case_wording_left_in_monolith():
    html = _html()
    for bad in ("Best Case", "Worst Case", "Hauptszenario", "Best&nbsp;/&nbsp;Haupt&nbsp;/&nbsp;Worst"):
        assert bad not in html, f"alter Begriff noch vorhanden: {bad}"
    # Aria-Labels der vier Faecher-Canvas nennen die neuen Szenarien.
    for canvas_id in ("ch-opt", "ch-aa-current", "ch-sollist-soll", "ch-sollist-ist"):
        m = re.search(r'<canvas id="' + canvas_id + r'"[^>]*aria-label="([^"]*)"', html)
        assert m, canvas_id
        assert _P90 in m.group(1) and _P10 in m.group(1), (canvas_id, m.group(1))
    # Der Vergleichs-Dialog sucht den Median-Datensatz ueber den Schluessel.
    body = _extract_function(html, "_renderSollIstCompare")
    assert "scenarioKey==='p50'" in body


def test_fan_footnote_present():
    html = _html()
    note = "In 8 von 10 simulierten Verläufen liegt das Vermögen zwischen P10 und P90; keine Garantie."
    assert html.count(note) >= 2, "Fussnote fehlt unter Faecher (AA-Ansicht + Vergleichsdialog)"


# ---------------------------------------------------------------------------
# Befunde 2/3/4: Kennzahlen-Tabelle (Endwerte, Wachstum, Median-Differenz)
# ---------------------------------------------------------------------------

_TABLE_FNS = (
    "formatCompactCHFAmount",
    "formatCompactCHF",
    "setText",
    "simulationPayload",
    "monteCarloPayload",
    "simulationCagrBps",
    "aaProjectionHorizonCut",
    "aaSeriesValueAt",
    "aaReserveSockelRappen",
    "renderAaProjectionEndValues",
)

_READ_TABLE_JS = r"""
renderAaProjectionEndValues(result);
function t(id){return document.getElementById(id).textContent;}
return {
  median:t('aa-proj-median'), curMedian:t('aa-proj-current-median'),
  p90:t('aa-proj-p90'), p10:t('aa-proj-p10'),
  cagr:t('aa-proj-cagr'), curCagr:t('aa-proj-current-cagr'),
  delta:t('aa-proj-delta-value'), deltaColor:document.getElementById('aa-proj-delta-value').style.color,
  deltaLabel:t('aa-proj-delta-label'),
  lblMedian:t('aa-proj-lbl-median'), lblP90:t('aa-proj-lbl-p90'), lblP10:t('aa-proj-lbl-p10'),
  simEnd:t('aa-horizon-sim-end'),
  r200:formatCompactCHF(200000), r600:formatCompactCHF(600000)
};
"""


def test_end_values_full_horizon_without_override():
    out = _run(_TABLE_FNS, _MC_RESULT_JS + "__override=null;" + _READ_TABLE_JS)
    # 30 Jahre: SOLL-Median 1 Mio + 30*50k = 2.5 Mio
    assert out["median"] == "CHF 2.50 Mio."
    assert out["curMedian"] == "CHF 1.90 Mio."
    assert out["p90"] == "CHF 3.40 Mio."
    assert out["p10"] == "CHF 1.60 Mio."
    assert out["lblMedian"] == "Endwert 2056 – Mittleres Szenario (Median)"
    assert out["lblP90"] == "Endwert 2056 – " + _P90
    assert out["lblP10"] == "Endwert 2056 – " + _P10
    assert out["simEnd"] == ""


def test_end_values_read_at_display_horizon_override():
    """Override 10 Jahre: Faecher endet 2036 -> Tabelle MUSS den Wert 2036 zeigen
    (vorher: immer letzter Wert der ungekuerzten Reihe, also 2056)."""
    out = _run(_TABLE_FNS, _MC_RESULT_JS + "__override=10;" + _READ_TABLE_JS)
    assert out["median"] == "CHF 1.50 Mio."  # 1 Mio + 10*50k
    assert out["curMedian"] == "CHF 1.30 Mio."
    assert out["p90"] == "CHF 1.80 Mio."
    assert out["p10"] == "CHF 1.20 Mio."
    assert out["lblMedian"].startswith("Endwert 2036 ")
    assert out["lblP90"].startswith("Endwert 2036 ")
    assert "2056" in out["simEnd"] and "2036" in out["simEnd"]
    assert out["delta"] == "+" + out["r200"]


def test_growth_row_compares_same_quantity_for_soll_and_ist():
    """SOLL- und IST-Wachstum beide aus dem MC-Median-Pfad (gleiche Quelle) und
    bis zum angezeigten Horizont. Die deterministische Mix-Reihe (hier steiler:
    +90k/Jahr) darf die SOLL-Zelle NICHT mehr speisen."""
    out = _run(_TABLE_FNS, _MC_RESULT_JS + "__override=null;" + _READ_TABLE_JS)
    # CAGR SOLL-Median: (2.5)^(1/30)-1 = 3.10 %; IST-Median: (1.9)^(1/30)-1 = 2.16 %
    assert out["cagr"] == "3.10%"
    assert out["curCagr"] == "2.16%"
    out10 = _run(_TABLE_FNS, _MC_RESULT_JS + "__override=10;" + _READ_TABLE_JS)
    # (1.5)^(1/10)-1 = 4.14 %; (1.3)^(1/10)-1 = 2.66 %
    assert out10["cagr"] == "4.14%"
    assert out10["curCagr"] == "2.66%"


def test_reserve_sockel_added_to_soll_end_values_and_growth():
    """Liquiditaetsreserve (vom Backend aus dem SOLL-Startkapital herausgerechnet)
    wird wie in der Grafik auf die SOLL-Werte aufgeschlagen -- auch am Override."""
    out = _run(
        _TABLE_FNS,
        _MC_RESULT_JS + "result.external_reserve_rappen=20000000;__override=10;" + _READ_TABLE_JS,
    )
    assert out["median"] == "CHF 1.70 Mio."  # 1.5 Mio + 0.2 Mio Reserve
    assert out["p90"] == "CHF 2.00 Mio."
    assert out["p10"] == "CHF 1.40 Mio."
    assert out["curMedian"] == "CHF 1.30 Mio."  # IST ohne Aufschlag
    # (1.7/1.2)^(1/10)-1 = 3.54 %
    assert out["cagr"] == "3.54%"


def test_reserve_sockel_not_added_twice_for_economic_basis_payloads():
    """RESERVE-FUNDING-LEDGER-001: enthaelt der SOLL-Pfad das Reservekonto
    bereits (reserve_accounting_basis), darf die Reserve nicht nochmals
    aufgeschlagen werden."""
    out = _run(
        _TABLE_FNS,
        _MC_RESULT_JS
        + "result.external_reserve_rappen=20000000;"
        + "result.monte_carlo.reserve_accounting_basis='economic_total_incl_external_reserve_v1';"
        + "__override=10;" + _READ_TABLE_JS,
    )
    assert out["median"] == "CHF 1.50 Mio."
    assert out["p90"] == "CHF 1.80 Mio."
    assert out["p10"] == "CHF 1.20 Mio."


def test_median_difference_is_neutral_and_labelled_as_difference_of_medians():
    out = _run(_TABLE_FNS, _MC_RESULT_JS + "__override=null;" + _READ_TABLE_JS)
    assert out["delta"] == "+" + out["r600"]
    assert out["deltaColor"] == "var(--n7)", "Median-Differenz darf nicht gruen/rot eingefaerbt sein"
    assert "Differenz der Median-Endwerte" in out["deltaLabel"]
    assert "2056" in out["deltaLabel"]
    html = _html()
    assert "nicht der Median der Differenz" in html
    # Statische Box nicht mehr gruen.
    m = re.search(r'<span id="aa-proj-delta-value" style="([^"]*)"', html)
    assert m and "var(--pos)" not in m.group(1)


def test_return_rows_are_unambiguously_named():
    html = _html()
    assert "Wachstum p.a. (CAGR Median)" not in html
    assert "Erwartete Rendite p.a. (P50)" not in html
    assert "Rendite p.a. (Median, zeitgewichtet)" in html
    assert "Vermögenswachstum p.a. (Mittleres Szenario, inkl. Cashflows)" in html


# ---------------------------------------------------------------------------
# Befund 5: Horizont-Fallback und Benennung der beiden Regler
# ---------------------------------------------------------------------------


def test_no_hardcoded_2033_fallback():
    assert "'2033'" not in _html()


def test_projection_horizon_year_label_derived_from_data():
    out = _run(
        ("simulationPayload", "projectionHorizonYearLabel"),
        "return {a:projectionHorizonYearLabel({simulation:{target_mix_series_rappen:[1,2],year_labels:[2026,2027,2041]}}),"
        "b:projectionHorizonYearLabel(null),c:projectionHorizonYearLabel({simulation:{target_mix_series_rappen:[],year_labels:[]}})};",
    )
    assert out == {"a": "2041", "b": "", "c": ""}


def test_two_horizon_controls_are_named_distinctly():
    html = _html()
    bar = html[html.index('id="aa-horizon-bar"'):html.index('id="aa-horizon-mode"')]
    assert ">Grafik-Ausschnitt<" in bar
    assert ">Prognose-Horizont<" not in bar
    sim = html[html.index('id="aa-simulation-card"'):html.index('id="aa-sim-horizon"')]
    assert "Prognose-Horizont (Simulation)" in sim
    # Bestehende Zusicherung (test_frontend_aa_horizon_control) bleibt erhalten.
    assert "ändert nur die Grafik-Länge, nicht die Renditen" in html
    assert 'id="aa-horizon-sim-end"' in html


def test_horizon_change_rerenders_table_end_values():
    html = _html()
    assert "renderAaProjectionEndValues(" in _extract_function(html, "applyIstHorizonOverride")
    # saveAaHorizon kappt synchron ueber _truncateProjectionChartsTo -> dort mit.
    assert "_truncateProjectionChartsTo(years)" in _extract_function(html, "saveAaHorizon")
    assert "renderAaProjectionEndValues(" in _extract_function(html, "_truncateProjectionChartsTo")


# ---------------------------------------------------------------------------
# Befund 7: Stressband ehrlich benennen + Umlaute
# ---------------------------------------------------------------------------


def _select_block(html: str, select_id: str) -> str:
    return re.search(r'<select[^>]*id="' + select_id + r'"[^>]*>.*?</select>', html, re.S).group(0)


def test_stress_options_are_volatility_multipliers_without_crisis_names():
    block = _select_block(_html(), "aa-sim-stress")
    values = re.findall(r'value="([0-9.]+)"', block)
    assert values == ["0.75", "1.0", "1.5", "1.6", "1.8", "2.0"], "Werte (Backend-Vertrag) unveraendert"
    for crisis in ("Corona", "Finanzkrise", "2008", "2020", "Zinsschock", "Stagflation"):
        assert crisis not in block, f"Krisenname im Volatilitaets-Regler: {crisis}"
    assert "Volatilität ×1.8 (stark erhöht)" in block
    assert "Volatilität ×1.0 (normal)" in block
    assert re.search(r'value="1\.0" selected', block)
    # Die echte historische Stress-Tabelle behaelt ihre Krisennamen.
    assert "financial_crisis_2008:'Finanzkrise 2008'" in _html()


def test_visible_aa_texts_have_real_umlauts():
    html = _html()
    stress = _select_block(html, "aa-sim-stress")
    rebal = _select_block(html, "aa-sim-rebalance")
    for bad in ("Erhoeht", "Volatilitaets", "Jaehrlich"):
        assert bad not in stress + rebal, bad
    assert ">Jährlich auf Soll<" in rebal
    assert 'value="calendar"' in rebal, "gespeicherter Key unveraendert"
    assert "Mandat-Einstellungen: Mortalität, Rentenalter, Lebenserwartung\">Mandat-Einstellungen" in html
