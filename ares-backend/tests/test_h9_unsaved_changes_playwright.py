"""H9 Nachtrag 4 (N-892-06): ungesicherte Eingaben vor dem Logout-Neustart.

Entscheid (Owner-Vertretung): Vor dem frischen Start beim Logout fragt Ares
nach, wenn ungesicherte Eingaben offen sind; zusaetzlich beforeunload. Beim
Sitzungsablauf mit Benutzerwechsel KEIN Dialog (Datenschutz), aber ein Hinweis
nach dem Neustart.

Verhaltenstest in echtem Chromium (echte input-Events) mit den echten Teilen
``unsaved-changes.js`` und ``session-boundary.js`` sowie den echten Monolith-
Funktionen ``doLogout``/``doLogin``/``om``. In den Backend-Shards ohne
Playwright ein sichtbarer Skip; Pflichtlauf im CI-Job "Frontend Reporting
Tests" (ARES_REQUIRE_PLAYWRIGHT=1).
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
window.calls={reload:0,confirm:[],showLogin:0,initApp:0,notice:[]};
window.CONFIRM_ANSWER=false;
window.API={token:'t-A',post:function(path,body){
    if(path==='/auth/login')return Promise.resolve({access_token:'t-B',refresh_token:'r-B',user:window.NEXT_USER});
    return Promise.resolve({});},
  setToken:function(t){this.token=t;return Promise.resolve();},
  setRefreshToken:function(){return Promise.resolve();}};
window.NEXT_USER={id:'u-B',tenant_id:'t1'};
window.uiConfirm=function(o){calls.confirm.push(o.message);return Promise.resolve(window.CONFIRM_ANSWER);};
window.showAppNotice=function(o){calls.notice.push(o.message);return {};};
window.showLogin=function(){calls.showLogin++;};window.showBootstrap=function(){};window.hideLogin=function(){};
window.initApp=function(){calls.initApp++;return Promise.resolve();};
window.ensureFoundationExampleButton=function(){};
window.checkBootstrapStatus=function(){return Promise.resolve({setup_required:false});};
window.enforce2faGate=function(){return Promise.resolve();};window.openForcePasswordChange=function(){};
window.prepareModalBeforeOpen=function(){return true;};
var currentUser=null,currentTenantDefaultPresentationMode=null,bootstrapStatusCache=null;
var riskAssessmentUiDirty=false;
"""

BODY = """<html><body>
<div class="overlay" id="m-es"><div class="modal"><input id="es-name" value=""></div></div>
<div class="overlay" id="m-team"><div class="modal"><input id="team-filter" value=""></div></div>
<input id="login-username" value="advB"><input id="login-password" value="pw">
</body></html>"""


@pytest.fixture()
def page():
    sync_api = _sync_api()
    src = html()
    funcs = "\n".join(extract_function(src, n) for n in ("doLogout", "doLogin", "om"))
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            pg = browser.new_page()
            # Eigener Ursprung (sessionStorage ist auf about:blank gesperrt).
            pg.route("http://ares.test/**", lambda route: route.fulfill(status=200, content_type="text/html", body=BODY))
            pg.goto("http://ares.test/")
            pg.add_script_tag(content=STUBS)
            pg.add_script_tag(content=(FRONTEND_DIR / "session-boundary.js").read_text(encoding="utf-8"))
            pg.add_script_tag(content=(FRONTEND_DIR / "unsaved-changes.js").read_text(encoding="utf-8"))
            pg.add_script_tag(content=funcs + "\nwindow.aresHardResetSession=function(){calls.reload++;aresSessionHardResetInProgress=true;return true;};")
            pg.evaluate("sessionStorage.clear()")
            yield pg
        finally:
            browser.close()


def test_input_in_open_customer_form_is_unsaved_other_dialogs_are_not(page):
    page.evaluate("om('m-team');document.getElementById('m-team').classList.add('open')")
    page.fill("#team-filter", "x")  # kein Kundenformular
    assert page.evaluate("hasAresUnsavedChanges()") is False
    page.evaluate("om('m-es');document.getElementById('m-es').classList.add('open')")
    assert page.evaluate("hasAresUnsavedChanges()") is False
    page.fill("#es-name", "Muster")
    assert page.evaluate("aresUnsavedSources()") == ["Stammdaten"]
    # Schliessen (speichern/abbrechen) bzw. neu oeffnen setzt zurueck.
    page.evaluate("document.getElementById('m-es').classList.remove('open')")
    assert page.evaluate("hasAresUnsavedChanges()") is False
    page.evaluate("om('m-es');document.getElementById('m-es').classList.add('open')")
    assert page.evaluate("hasAresUnsavedChanges()") is False


def test_risk_questionnaire_dirty_flag_counts(page):
    page.evaluate("riskAssessmentUiDirty=true")
    assert page.evaluate("aresUnsavedSources()") == ["Risikoprofil-Fragebogen"]


def test_logout_with_unsaved_changes_asks_and_cancel_keeps_session(page):
    page.evaluate("om('m-es');document.getElementById('m-es').classList.add('open')")
    page.fill("#es-name", "Muster")
    out = page.evaluate("CONFIRM_ANSWER=false; doLogout().then(()=>({reload:calls.reload,confirm:calls.confirm,token:API.token}))")
    assert out["reload"] == 0 and out["token"] == "t-A"
    assert out["confirm"] and out["confirm"][0].startswith("Ungespeicherte Änderungen gehen verloren – trotzdem abmelden?")
    assert "Stammdaten" in out["confirm"][0]


def test_logout_confirmed_restarts(page):
    page.evaluate("om('m-es');document.getElementById('m-es').classList.add('open')")
    page.fill("#es-name", "Muster")
    out = page.evaluate("CONFIRM_ANSWER=true; doLogout().then(()=>({reload:calls.reload,token:API.token}))")
    assert out == {"reload": 1, "token": None}


def test_logout_without_unsaved_changes_does_not_ask(page):
    out = page.evaluate("doLogout().then(()=>({reload:calls.reload,confirm:calls.confirm.length}))")
    assert out == {"reload": 1, "confirm": 0}


def test_beforeunload_guard_only_with_unsaved_changes_and_not_on_intended_restart(page):
    assert page.evaluate("aresBeforeUnloadGuard({preventDefault(){}})") is None
    page.evaluate("riskAssessmentUiDirty=true")
    assert page.evaluate("aresBeforeUnloadGuard({preventDefault(){}})") == ""
    page.evaluate("aresSessionHardResetInProgress=true")
    assert page.evaluate("aresBeforeUnloadGuard({preventDefault(){}})") is None


def test_session_expiry_user_switch_no_dialog_but_notice_after_restart(page):
    page.evaluate("riskAssessmentUiDirty=true;markAresSessionPrincipal({id:'u-A',tenant_id:'t1'})")
    out = page.evaluate("doLogin().then(()=>({reload:calls.reload,confirm:calls.confirm.length,"
                        "flag:sessionStorage.getItem('ares.unsavedDiscarded')}))")
    assert out == {"reload": 1, "confirm": 0, "flag": "1"}
    # Nach dem Neustart (Boot) einmaliger Hinweis.
    shown = page.evaluate("[aresShowDiscardNoticeIfAny(), calls.notice.slice(), aresShowDiscardNoticeIfAny()]")
    assert shown[0] is True and shown[2] is False
    assert "verworfen" in shown[1][0]


def test_monolith_wiring():
    src = html()
    logout = extract_function(src, "doLogout")
    assert logout.index("aresConfirmDiscardBeforeLogout") < logout.index("API.post('/auth/logout'")
    assert "aresRememberDiscardedForNotice()" in extract_function(src, "doLogin")
    assert "aresUnsavedModalOpened(id)" in extract_function(src, "om")
    boot = src.split("document.addEventListener('DOMContentLoaded'", 1)[1][:7000]
    assert "aresShowDiscardNoticeIfAny()" in boot


def test_ci_runs_this_behaviour_test_with_playwright_required():
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = workflow[workflow.index("\n  vitest:"):]
    assert "tests/test_h9_unsaved_changes_playwright.py" in job
