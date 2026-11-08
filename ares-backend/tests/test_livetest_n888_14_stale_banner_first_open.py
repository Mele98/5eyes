"""N-888-14 (Pruefrunde ESG 040388f6, Dok. 86 ab Z. 9705): Veraltet-Banner
beim ERSTEN Oeffnen der Asset Allokation nach dem Login.

Befund: der ``go``-Wrapper las den Server-Status sofort; das danach
laufende Hydrieren der gespeicherten Allokation (loadClientById ->
``loadCurrentAllocationResult`` -> ``strategyState.dirty=false``, Banner
aus) setzte ihn zurueck, "Portfolio umsetzen" wurde wieder sichtbar.

Fix (sustainability-preferences.js): Status wird gemerkt (``SUST.stale``),
nach jedem ``loadCurrentAllocationResult`` (nach dem Aufrufer) neu gelesen
und angewandt; ``syncPortfolioUmsetzenButtonVisibility`` blendet den Button
mit derselben Bedingung aus.

Browser-Test (Playwright + echtes Modul + echte Monolith-Funktion
``syncPortfolioUmsetzenButtonVisibility``): neuer Login, erstes Oeffnen ->
Banner sichtbar, Button unsichtbar. Pflichtlauf im CI-Job "Frontend
Reporting Tests" (``ARES_REQUIRE_PLAYWRIGHT=1``), sonst sichtbarer Skip.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.livetest_monolith_js import HTML_PATH, extract_function, html

MODULE = HTML_PATH.parent / "sustainability-preferences.js"
NOTICE = "Anlagestrategie veraltet: Sie hält die Ausschlusswünsche (Tabak) nicht ein."


def _playwright_sync_api():
    if os.environ.get("ARES_REQUIRE_PLAYWRIGHT") == "1":
        import playwright.sync_api as sync_api  # Pflicht: ImportError ist rot

        return sync_api
    return pytest.importorskip(
        "playwright.sync_api",
        reason="Playwright fehlt; Pflichtlauf im CI-Job 'Frontend Reporting Tests' (N-888-14)",
    )


# Minimaler Monolith-Ersatz: Hydrierung wie loadClientById (setzt dirty=false
# und blendet das Banner NACH dem Laden aus), markStrategyDirty wie im
# Monolithen (dirty, staleNotice, Banner), API liefert "veraltet".
HARNESS = r"""
var strategyState={dirty:false,staleNotice:null,allocation:{buckets:[{k:1}]}};
var currentMandateId='m-1';
function getActiveMandateId(){return currentMandateId;}
function isDemoMandateId(){return false;}
var STALE={'m-1':true,'m-bad':true,'m-ok':false};
var API={get:function(path){var bad=STALE[decodeURIComponent(path.split('/')[2])];
  return new Promise(function(r){setTimeout(function(){
  r(bad?{allocation_floor_status:'violated',allocation_stale_notice:%NOTICE%}
       :{allocation_floor_status:'ok',allocation_stale_notice:null});},20);});}};
function om(id){document.getElementById(id).classList.add('open');}
function openPortfolioUmsetzenModal(){om('m-pu');}
async function switchMandate(mid){currentMandateId=mid;await loadClientById();await go('al');}
function syncStrategyStaleView(){
  var b=document.getElementById('al-dirty-banner');
  var n=strategyState.dirty&&strategyState.staleNotice;
  b.style.display=n?'flex':'none';b.textContent=n||'';
}
function markStrategyDirty(message){strategyState.dirty=true;strategyState.staleNotice=message;
  syncPortfolioUmsetzenButtonVisibility();syncStrategyStaleView();}
async function loadCurrentAllocationResult(mid){
  await new Promise(function(r){setTimeout(r,60);});
  return {buckets:[{k:1}]};
}
async function loadClientById(){
  var hydrated=await loadCurrentAllocationResult(currentMandateId);
  if(hydrated){strategyState.dirty=false;document.getElementById('al-dirty-banner').style.display='none';
    syncPortfolioUmsetzenButtonVisibility();}
}
async function go(p){document.body.dataset.page=p;return null;}
function loadCurrentRiskAssessment(){return Promise.resolve(null);}
function openAllocationPreferencesModal(){}
"""


def test_banner_visible_and_button_hidden_on_first_open_after_login():
    sync_api = _playwright_sync_api()
    sync_button = extract_function(html(), "syncPortfolioUmsetzenButtonVisibility")
    harness = HARNESS.replace("%NOTICE%", repr(NOTICE)) + "\n" + sync_button
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(
                "<html><body><div id='page-rp'><div class='cnav'></div></div>"
                "<div id='al-dirty-banner' style='display:none'></div>"
                "<button id='btn-portfolio-umsetzen' onclick='openPortfolioUmsetzenModal()'>Portfolio umsetzen</button>"
                "<div id='m-pu' class='overlay'></div></body></html>"
            )
            page.add_script_tag(content=harness)
            page.add_script_tag(path=str(MODULE))
            # Neuer Login: Mandat laden (Hydrierung) und SOFORT die AA oeffnen.
            result = page.evaluate("""() => new Promise(done => {
              loadClientById();
              go('al');
              setTimeout(() => {
                const b = document.getElementById('al-dirty-banner');
                const u = document.getElementById('btn-portfolio-umsetzen');
                done({banner: getComputedStyle(b).display, text: b.textContent,
                      button: getComputedStyle(u).display, disabled: u.disabled,
                      dirty: strategyState.dirty});
              }, 600);
            })""")
        finally:
            browser.close()
    assert result["banner"] == "flex", result
    assert "Tabak" in result["text"]
    assert result["button"] == "none" and result["disabled"] is True, result
    assert result["dirty"] is True


def test_ci_runs_this_behaviour_test_with_playwright_required():
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = workflow[workflow.index("\n  vitest:"):]
    assert 'ARES_REQUIRE_PLAYWRIGHT: "1"' in job
    assert "tests/test_livetest_n888_14_stale_banner_first_open.py" in job


def test_button_state_follows_the_current_mandate_without_residue():
    """N-888-16: verletzt -> sauber: Button sichtbar UND aktiv (Klick oeffnet
    m-pu); sauber -> verletzt: ausgeblendet. Keine globale Restwirkung."""
    sync_api = _playwright_sync_api()
    sync_button = extract_function(html(), "syncPortfolioUmsetzenButtonVisibility")
    harness = HARNESS.replace("%NOTICE%", repr(NOTICE)) + "\n" + sync_button
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(
                "<html><body><div id='page-rp'><div class='cnav'></div></div>"
                "<div id='al-dirty-banner' style='display:none'></div>"
                "<button id='btn-portfolio-umsetzen' onclick='openPortfolioUmsetzenModal()'>Portfolio umsetzen</button>"
                "<div id='m-pu' class='overlay'></div></body></html>"
            )
            page.add_script_tag(content=harness)
            page.add_script_tag(path=str(MODULE))
            state = ("() => {const u=document.getElementById('btn-portfolio-umsetzen');"
                     "return {display:getComputedStyle(u).display, disabled:u.disabled};}")
            page.evaluate("switchMandate('m-bad')")
            page.wait_for_timeout(500)
            bad = page.evaluate(state)
            page.evaluate("switchMandate('m-ok')")
            page.wait_for_timeout(500)
            ok = page.evaluate(state)
            page.click("#btn-portfolio-umsetzen")
            opened = page.evaluate("document.getElementById('m-pu').classList.contains('open')")
            page.evaluate("document.getElementById('m-pu').classList.remove('open')")
            page.evaluate("switchMandate('m-bad')")
            page.wait_for_timeout(500)
            bad_again = page.evaluate(state)
        finally:
            browser.close()
    assert bad == {"display": "none", "disabled": True}, bad
    assert ok["display"] != "none" and ok["disabled"] is False, ok
    assert opened is True
    assert bad_again == {"display": "none", "disabled": True}, bad_again
