"""H11 (Hygiene-Folgepunkt H9): Rueckfrage beim Mandatswechsel mit ungesicherten Eingaben.

Befund (Pruefrunde H9, Hinweis): Ein Mandatswechsel (``loadClientById``)
verwarf eine ungespeicherte Fragebogen-, Formular- oder ESG-Eingabe ohne
Rueckfrage (``hydrateRiskQuestionnaire`` setzt ``riskAssessmentUiDirty=false``,
die ESG-Karte #sust-card wird neu aufgebaut). Wie beim Logout fragt Ares jetzt
nach; "Abbrechen" behaelt Mandat und Eingabe, "Trotzdem wechseln" wechselt.

Verhaltenstest in echtem Chromium (echte input-/change-Events) mit dem echten
Teil ``unsaved-changes.js`` und der echten Monolith-Funktion
``loadClientById`` (Nachladen per API bleibt haengend, gemessen wird nur, ob
der Wechsel beginnt). Pflichtlauf im CI-Job mit ARES_REQUIRE_PLAYWRIGHT=1; die
Rueckfrage in der echten App belegt zusaetzlich
``test_livetest_e2a_sustainability_flow`` (Entwurf auf A, Wechsel auf B).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.livetest_monolith_js import extract_function, html
from tests.monolith_source import FRONTEND_DIR


def _sync_api():
    if os.environ.get("ARES_REQUIRE_PLAYWRIGHT") == "1":
        import playwright.sync_api as sync_api  # Pflicht: ImportError ist rot

        return sync_api
    return pytest.importorskip("playwright.sync_api", reason="Playwright fehlt; Pflichtlauf im CI-Job 'Frontend Reporting Tests'")


STUBS = r"""
window.calls={confirm:[],get:[],hydrate:0};
window.CONFIRM_ANSWER=false;
window.API={get:function(path){calls.get.push(path);return new Promise(function(){});}};
window.uiConfirm=function(o){calls.confirm.push(o.message);return Promise.resolve(window.CONFIRM_ANSWER);};
window.prepareModalBeforeOpen=function(){return true;};
var riskAssessmentUiDirty=false;
var liveClientLoadToken=0,liveClients=[{id:'c-A'},{id:'c-B'}];
var currentClientId='c-A',currentMandateId='m-A',currentMandateData={},currentGoals=[],_currentGoalsLoadedOnce=true;
var currentCashflows=[],currentCashflowSummary=null,currentWealthSummary=null,currentCashflowProjection=null;
var currentWealthPositions=[],currentPortfolioPositions=[],riskHorizonTouched=false,currentReviewState=null,strategyState=null;
function hydrateRiskQuestionnaire(){calls.hydrate++;riskAssessmentUiDirty=false;}
function renderRiskSummary(){} function resetCurrentProjectionCharts(){} function renderEngineRuntimePanels(){}
function renderPortfolioSections(){} function syncAllocationPendingViews(){}
"""

BODY = """<html><body>
<div class="overlay" id="m-es"><div class="modal"><input id="es-name" value=""></div></div>
<div id="sust-card"><label><input type="radio" id="sust-q1-yes" name="sust-q1" value="yes"> Ja</label></div>
</body></html>"""

SWITCH = ("CONFIRM_ANSWER=%s; loadClientById('c-B'); new Promise(r=>setTimeout(r,50)).then(()=>"
          "({current:currentClientId,confirm:calls.confirm.slice(),get:calls.get.length,hydrate:calls.hydrate,"
          "unsaved:aresUnsavedSources()}))")


@pytest.fixture()
def page():
    sync_api = _sync_api()
    src = html()
    funcs = "\n".join(extract_function(src, n) for n in ("loadClientById", "om"))
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            pg = browser.new_page()
            pg.route("http://ares.test/**", lambda route: route.fulfill(status=200, content_type="text/html", body=BODY))
            pg.goto("http://ares.test/")
            pg.add_script_tag(content=STUBS)
            pg.add_script_tag(content=(FRONTEND_DIR / "unsaved-changes.js").read_text(encoding="utf-8"))
            pg.add_script_tag(content=funcs)
            yield pg
        finally:
            browser.close()


def test_switch_with_unsaved_esg_input_asks_and_cancel_keeps_mandate_and_input(page):
    page.check("#sust-q1-yes")
    out = page.evaluate(SWITCH % "false")
    assert out["confirm"] and out["confirm"][0].startswith(
        "Ungespeicherte Änderungen gehen verloren – trotzdem Mandat wechseln?"), out
    assert "Nachhaltigkeit" in out["confirm"][0]
    # Abbrechen: kein Wechsel, nichts nachgeladen, Eingabe bleibt offen.
    assert out["current"] == "c-A" and out["get"] == 0 and out["hydrate"] == 0
    assert out["unsaved"] == ["Nachhaltigkeit"]
    assert page.is_checked("#sust-q1-yes")


def test_switch_with_unsaved_questionnaire_confirmed_switches(page):
    page.evaluate("riskAssessmentUiDirty=true")
    out = page.evaluate(SWITCH % "true")
    assert len(out["confirm"]) == 1 and "Risikoprofil-Fragebogen" in out["confirm"][0]
    assert out["current"] == "c-B" and out["get"] > 0 and out["hydrate"] == 1
    assert out["unsaved"] == []


def test_switch_with_unsaved_customer_form_lists_it(page):
    page.evaluate("om('m-es');document.getElementById('m-es').classList.add('open')")
    page.fill("#es-name", "Muster")
    out = page.evaluate(SWITCH % "false")
    assert "Stammdaten" in out["confirm"][0] and out["current"] == "c-A"


def test_confirmed_switch_clears_esg_marker_for_the_next_mandate(page):
    page.check("#sust-q1-yes")
    out = page.evaluate(SWITCH % "true")
    assert out["current"] == "c-B" and out["unsaved"] == []


def test_switch_without_unsaved_input_does_not_ask(page):
    out = page.evaluate(SWITCH % "false")
    assert out["confirm"] == [] and out["current"] == "c-B" and out["get"] > 0


def test_guard_is_the_first_step_of_load_client_by_id():
    fn = extract_function(html(), "loadClientById")
    assert fn.index("aresClientSwitchAllowed()") < fn.index("++liveClientLoadToken") < fn.index("hydrateRiskQuestionnaire(null)")
    assert fn.index("aresClientSwitchAllowed()") < fn.index("loadPersona(")


def test_ci_runs_this_behaviour_test_with_playwright_required():
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = workflow[workflow.index("\n  vitest:"):]
    assert "tests/test_h11_client_switch_unsaved_playwright.py" in job
