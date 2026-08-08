"""Regressions-Sperre fuer Roadmap #93: SOLL/IST-Achsen-Sync.

`syncAaProjectionAxisScales()` (5eyes_v2.html) MUSS SOLL (charts.opt) und
IST (charts.aaCurrent) mit identischen X-Labels UND identischer Y-Achse
(type/min/max) versehen -- sonst ist der visuelle Vergleich der beiden
Charts wertlos (siehe Kommentar direkt ueber der Funktion, 2026-06-14-Fix).

Diese Tests pinnen die Konstruktions-Invarianten im Quelltext, statt die
Chart.js-Instanzen tatsaechlich zu rendern (kein Node/DOM-Runtime im
Testbaum -- konsistent mit den uebrigen `test_frontend_*`-Tests, die
ebenfalls auf Quelltext-Assertions statt echter JS-Ausfuehrung setzen).
"""
from pathlib import Path
import re


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _sync_fn_body() -> str:
    html = _html()
    start = html.index("function syncAaProjectionAxisScales()")
    # Naechste Top-Level-Funktion nach syncAaProjectionAxisScales() markiert das Ende.
    end = html.index("function updateProjectionChartsFromSimulation(", start)
    assert start < end
    return html[start:end]


def test_sync_function_exists():
    html = _html()
    assert "function syncAaProjectionAxisScales()" in html


def test_shared_labels_assigned_to_both_charts_identically():
    body = _sync_fn_body()
    # Beide Charts erhalten denselben sharedLabels-Array (per .slice() kopiert,
    # aber aus derselben Quelle) -- nicht je eigene, potenziell abweichende Labels.
    assert "charts.opt.data.labels=sharedLabels.slice();" in body
    assert "charts.aaCurrent.data.labels=sharedLabels.slice();" in body


def test_y_axis_values_combine_both_charts_before_min_max():
    body = _sync_fn_body()
    # min/max MUESSEN aus den Werten BEIDER Charts kombiniert werden -- sonst
    # koennte ein Chart aus der gemeinsamen Skala herausragen.
    assert "projectionChartValues(charts.opt).concat(projectionChartValues(charts.aaCurrent))" in body


def test_y_axis_config_applied_to_both_charts_in_one_shared_loop():
    body = _sync_fn_body()
    # cfg (type/min/max) wird EINMAL berechnet und dann in einer gemeinsamen
    # forEach-Schleife auf beide Charts angewandt -- garantiert Gleichheit
    # durch Konstruktion (kein Pfad, der nur einen Chart aktualisiert).
    loop_match = re.search(
        r"\[charts\.opt,charts\.aaCurrent\]\.forEach\(function\(ch\)\{[^}]*ch\.options\.scales\.y\.type=cfg\.type;"
        r"[^}]*ch\.options\.scales\.y\.min=cfg\.min;[^}]*ch\.options\.scales\.y\.max=cfg\.max;",
        body,
    )
    assert loop_match is not None


def test_both_charts_redrawn_after_axis_sync():
    body = _sync_fn_body()
    # Ohne erneutes .update() auf BEIDEN Charts bleiben angeglichene Achsen
    # unsichtbar (der urspruengliche 2026-06-14-Bug).
    assert "charts.opt.update('none')" in body
    assert "charts.aaCurrent.update('none')" in body


def test_sync_called_after_projection_chart_updates():
    html = _html()
    # syncAaProjectionAxisScales() muss nach dem Neuaufbau der Projektions-Charts
    # aufgerufen werden, sonst arbeitet sie mit veralteten Datenreihen.
    fn_start = html.index("function updateProjectionChartsFromSimulation(")
    fn_end = html.index("\nfunction ", fn_start + 1)
    assert "syncAaProjectionAxisScales();" in html[fn_start:fn_end]
