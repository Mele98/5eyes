"""KN-U (Dok. 117): statische Vertraege der Classic-Berateroberflaeche.

Ergaenzt die Verhaltens-Tests (test_kn_u_frontend_units.py, Livetest
test_livetest_kn_u_ui.py) um Quelltext-Pruefungen, die ohne Browser laufen.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.monolith_source import EXTRACTED_PARTS, read_monolith_bundle

FRONTEND = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend"
COMMENTS = re.compile(r"<!--.*?-->|/\*.*?\*/|(?<![:'\"\\])//[^\n]*", re.S)


def _visible_source() -> str:
    """Bundle ohne Kommentare (Kommentare duerfen ASCII-Umschrift behalten)."""
    return COMMENTS.sub("", read_monolith_bundle())


def _fn(src: str, name: str) -> str:
    start = src.index("function " + name + "(")
    nxt = re.search(r"\n(?:async )?function |\n  function ", src[start + 10:])
    return src[start: start + 10 + (nxt.start() if nxt else 4000)]


def test_part_registered_before_sustainability_preferences():
    names = [n for n, _k in EXTRACTED_PARTS]
    assert "mandate-view.js" in names
    assert names.index("mandate-view.js") == names.index("advisor-guidance.js") + 1
    assert names[-1] == "sustainability-preferences.js"


def test_e2e2_01_reset_hooks_on_every_mandate_switch():
    html = read_monolith_bundle()
    load = _fn(html, "loadClientById")
    assert load.index("aresClientSwitchAllowed") < load.index("aresResetMandateView"), "Reset erst nach der Wechsel-Rueckfrage"
    new = _fn(html, "showNewClientScreen")
    assert "aresResetMandateView" in new
    assert "aresResetMandateView" in html[html.index("function loadPersona("):html.index("function loadPersona(") + 400]
    # Ohne Allokation werden die Review-Kacheln aus dem aktiven Mandat gesetzt (nicht "return").
    mod = (FRONTEND / "mandate-view.js").read_text(encoding="utf-8")
    assert "if (!alloc()) { clearStrategySummaryForDirtyState(); return; }" in mod
    assert html.count("function clearStrategySummaryForDirtyState(") == 1, "zwei Quellen fuer die Review-Kacheln"


def test_e2e2_02_banner_below_header():
    mod = (FRONTEND / "mandate-view.js").read_text(encoding="utf-8")
    assert "#pg-egress-banner{position:fixed!important;top:48px!important" in mod
    assert "z-index:150!important" in mod  # unter der Kopfzeile (z-index 200)
    css = (FRONTEND / "ares.css").read_text(encoding="utf-8")
    assert ".topbar{height:48px" in css and "z-index:200" in css[css.index(".topbar{"):css.index(".topbar{") + 200]


def test_e2e2_06_new_mandate_keeps_full_response():
    html = read_monolith_bundle()
    new = _fn(html, "showNewClientScreen")
    assert "currentMandateData = {id: currentMandateId || null, mandate_type: mType};" not in new
    assert "currentMandateData.id===currentMandateId" in new


def test_e2e2_07_fx_open_metrics_and_n917_08_group_sums():
    html = read_monolith_bundle()
    assert "Noch keine Advisory-Position" not in html
    assert "aresSnapshotAmount(snapshot,'advisory')" in html and "aresSnapshotAmount(snapshot,'net')" in html
    assert "fmt(sub,positionsCurrency(" not in html and "fmt(derSum(arr),positionsCurrency(arr))" not in html
    assert "aresCcySum(fmt,sub," in html and "aresCcySum(fmt,derSum(arr),arr," in html


def test_e2e2_08_every_typed_reason_is_shown():
    src = (FRONTEND / "ist-projection-basis.js").read_text(encoding="utf-8")
    assert "detail.reason_code==='IST_PROJECTION_BASIS_UNAVAILABLE'&&detail.message" not in src
    assert "st.reason=(detail&&detail.message)" in src


def test_e2e2_11_12_umlauts_and_no_sharp_s_in_visible_texts():
    vis = _visible_source()
    # E2E2-12: kein "ß" (einzige Ausnahme: die Umschrift-Funktion fuer Dateinamen).
    assert [line for line in vis.splitlines() if "ß" in line and "replace(/ß/g" not in line] == []
    # E2E2-11: kaputte Woerter und die in Dok. 117 genannten Umschriften.
    for broken in ("Zuflusse erfasst", "Vermogenszuflusse", "Abflusse erfasst"):
        assert broken not in vis, broken
    for word in ("FINMA Eignungspruefung", "Primaer – wichtiges", "Primaer - wichtiges", "bleibt verfuegbar",
                 "abzueglich Ausgaben", "Naechstes Gespraech", "Entwurf oeffnen", "Entwuerfe", "gefuehrt",
                 "Bitte zuerst ein Mandat oeffnen", "spaeter entscheiden"):
        assert word not in vis, word


def test_e2e2_14_no_technical_terms_in_advisor_texts():
    vis = _visible_source()
    for term in ("MC-Pfade", "BFS-Mortalitaet", "Strategy-Run", "House-View", "zwischen P10 und P90", "' / MC '",
                 "Solver-Trace", "Advisory-Position", "rechnet keine Kurse um", "Asset-Class-Jahresrenditen",
                 "Multi-Currency-Support", "FX-Rates speichern", "Quelle Manual", "Terminal Value",
                 "Global Hedged Rendite", ">Shadow-Aggregat<"):
        assert term not in vis, term
    assert vis.count("aresTerm(") >= 4


def test_e2e_11_horizon_label_uses_end_of_year_text():
    html = read_monolith_bundle()
    assert "'= auto bis '+String(simEnd).slice(0,4)" not in html
    assert "'= auto bis '+projectionEndOfYearText(simEnd)+' (Simulationshorizont)'" in html


def test_e2e_17_no_empty_hint_next_to_new_mandate_and_no_endless_loading():
    html = read_monolith_bundle()
    side = html[html.index("function addToSidebar(cid, warnLabel)"):html.index("function addToSidebar(cid, warnLabel)") + 600]
    assert "sbl.querySelectorAll('.sb-empty').forEach" in side
    static = html[:html.index("<script>", html.index('<div class="layout">'))] if '<div class="layout">' in html else html
    assert "Die Ausgaben werden geladen." not in html
    assert ">Wird geladen …<" not in static


def test_e2e2_15_fx_editor_source_label():
    fx = (FRONTEND / "fx-rates-editor.js").read_text(encoding="utf-8")
    ag = (FRONTEND / "advisor-guidance.js").read_text(encoding="utf-8")
    assert "escapeHtml(fxSourceText(entry.source))" in fx and "Kurs geprüft (Quelle manuell, Datum heute)" in fx
    assert "esc(fxSourceText(r.source)" in ag
    assert "'saveFxQuickEditor', 'saveAdminFxRates'" in (FRONTEND / "mandate-view.js").read_text(encoding="utf-8")


def test_n918_01_reset_neutralizes_all_outputs_first():
    mod = (FRONTEND / "mandate-view.js").read_text(encoding="utf-8")
    body = mod[mod.index("function resetOutputs()"):mod.index("function resetDom()")]
    for call in ("invalidateStrategyOutputs()", "renderPortfolioNeutralState(", "renderPortfolioSections([])"):
        assert call in body, call
    assert mod.index("resetOutputs();") > mod.index("function resetDom()")


def test_n918_03_header_buttons_never_cover_steps():
    mod = (FRONTEND / "mandate-view.js").read_text(encoding="utf-8")
    assert "'.topbar .tr{flex-shrink:0}'" in mod
    assert "@media(max-width:1440px)" in mod and ".tstep:not(.active){font-size:0" in mod


def test_n918_04_texts():
    vis = _visible_source()
    for word in ("3a-Bezuegen", "-abfluesse mit", "-abfluesse.", "Externe Depot-Aenderung", "Zielaenderung",
                 "Global währungsgesichert Rendite", "'House View laden'", ">House View für"):
        assert word not in vis, word
    assert "Endvermögen (mittlerer Verlauf) '+projectionHorizonYearLabel(sim)" in vis
