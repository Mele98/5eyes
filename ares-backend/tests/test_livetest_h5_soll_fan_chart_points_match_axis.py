"""Live-Test 2026-11 H5 -- SOLL-Prognose zeichnete Start/Median falsch.

Befund: Daten korrekt (Start 150, Median-Ende 171, P90 258, P10 109 in TCHF),
Randlabels korrekt, aber gezeichnet startete die Linie bei ~215k
(``getPixelForValue(150)=229.5``, Datenpunkt bei y=139); P90 lief oben aus dem
Diagramm.

Ursache (mit echtem Chart.js 4.4.1 nachgestellt): ``upgradeFanChartWithMonteCarlo``
ruft ``charts.opt.update()`` (animiert -- Zielpixel auf der ALTEN y-Skala),
direkt danach setzt ``syncAaProjectionAxisScales`` min/max neu und ruft
``update('none')``. ``update('none')`` bricht die laufende Animation nicht ab;
sie ueberschreibt die neu berechneten Punkte und endet auf den alten Zielen.
Die gemessene Verzerrung (gezeichnet = 1.68*Wert - 35) entspricht exakt einer
alten Skala 50..200 auf neuer Skala 50..300.

Tests:
1. Verhalten (lokal, Playwright + echtes vendor/chart.min.js + echte Monolith-
   Funktionen): nach der Sequenz liegen die Punkte auf ``getPixelForValue``.
   Pruefrunde #858 N-858-4: In der CI laeuft er im Job "Frontend Reporting
   Tests" mit installiertem Playwright/Chromium und ``ARES_REQUIRE_PLAYWRIGHT=1``
   -- dort ist ein fehlendes Playwright ROT statt ein stiller Skip. In den
   Backend-Shards (ohne Playwright) bleibt er ein sichtbarer Skip mit Grund.
2. Quelltext-Vertrag: die Achsen-Synchronisierung stoppt laufende Animationen.
3. CI-Gate: der Workflow muss diesen Test mit Playwright-Pflicht ausfuehren.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from tests.livetest_monolith_js import HTML_PATH, extract_function, has_function, html

CHART_JS = HTML_PATH.parent / "vendor" / "chart.min.js"


def test_axis_sync_stops_running_animation_before_settled_update():
    src = html()
    helper = extract_function(src, "chartUpdateSettled")
    assert helper.index(".stop()") < helper.index("update('none')")
    body = extract_function(src, "syncAaProjectionAxisScales")
    assert "chartUpdateSettled(charts.opt)" in body
    assert "chartUpdateSettled(charts.aaCurrent)" in body
    assert not re.search(r"charts\.(opt|aaCurrent)\.update\('none'\)", body)


FUNCS = ("projectionChartValues", "arrMin", "arrMax", "_projAxisConfig", "syncAaProjectionAxisScales")


def _playwright_sync_api():
    if os.environ.get("ARES_REQUIRE_PLAYWRIGHT") == "1":
        import playwright.sync_api as sync_api  # Pflicht: ImportError ist rot

        return sync_api
    return pytest.importorskip(
        "playwright.sync_api",
        reason="Playwright fehlt; Pflichtlauf mit Chromium im CI-Job 'Frontend Reporting Tests' (N-858-4)",
    )


def test_ci_runs_this_behaviour_test_with_playwright_required():
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = workflow[workflow.index("\n  vitest:"):]
    assert "playwright install --with-deps chromium" in job
    assert 'ARES_REQUIRE_PLAYWRIGHT: "1"' in job
    assert "tests/test_livetest_h5_soll_fan_chart_points_match_axis.py" in job


def test_fan_points_land_on_axis_pixels_with_real_chartjs():
    sync_api = _playwright_sync_api()
    src = html()
    names = [n for n in FUNCS if has_function(n, src)] + (
        ["chartUpdateSettled"] if has_function("chartUpdateSettled", src) else []
    )
    js_funcs = "\n".join(extract_function(src, n) for n in names)
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1000, "height": 700})
            page.set_content(
                "<html><body><div style='width:700px;height:320px'><canvas id=o></canvas></div>"
                "<div style='width:700px;height:320px'><canvas id=c></canvas></div></body></html>"
            )
            page.add_script_tag(path=str(CHART_JS))
            page.add_script_tag(content=(
                "function loadIstHorizonOverride(){return null;}\n"
                "function renderAaFanRangeSentence(){}\n" + js_funcs
            ))
            result = page.evaluate("""() => new Promise(done => {
              const mk = (id, data) => new Chart(document.getElementById(id).getContext('2d'), {type:'line',
                data:{labels:[2026,2027,2028,2029], datasets:[{data}]},
                options:{responsive:true, maintainAspectRatio:false, scales:{y:{}}}});
              window.charts = {opt: mk('o', [150,160,165,171]), aaCurrent: mk('c', [150,150,150,150])};
              syncAaProjectionAxisScales();
              setTimeout(() => {
                // wie upgradeFanChartWithMonteCarlo: Faecher setzen, animiert updaten, Achsen syncen
                charts.opt.data.datasets = [{data:[150,200,230,258], fill:'+1'}, {data:[150,155,165,171], fill:'+1'}, {data:[150,130,120,109]}];
                charts.opt.update();
                syncAaProjectionAxisScales();
                setTimeout(() => {
                  const y = charts.opt.scales.y, m = charts.opt.getDatasetMeta(1);
                  done({start: [m.data[0].y, y.getPixelForValue(150)], end: [m.data[3].y, y.getPixelForValue(171)],
                        min: y.min, max: y.max});
                }, 2500);
              }, 1500);
            })""")
        finally:
            browser.close()
    assert result["max"] >= 258
    assert abs(result["start"][0] - result["start"][1]) < 1.0, result
    assert abs(result["end"][0] - result["end"][1]) < 1.0, result
