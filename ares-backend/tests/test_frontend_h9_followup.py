"""H9 Nachtrag 1 (Pruefrunde H9 61d8d69d): N-892-01/-02/-04 und Demo-IST-Pfad.

Echte Funktionen aus dem Monolithen-Bundle (``ares.html`` plus die ausgelagerten
Teile ``ist-projection-gate.js`` und ``session-boundary.js``) laufen in Node.
Die Live-Belege (Playwright, zwei Benutzer/zwei Tenants, Aenderung per API in
derselben Sitzung) stehen im Handoff H-150 Nachtrag 1.
"""
from __future__ import annotations

from tests.livetest_monolith_js import extract_function, html, run_js
from tests.monolith_source import FRONTEND_DIR


def _module(name: str) -> str:
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# N-892-02: Sitzungsgrenze (Logout / anderer Benutzer)
# ---------------------------------------------------------------------------

SESSION_PRELUDE = r"""
var calls={reload:0,showLogin:0,initApp:0,hideLogin:0,bootstrap:0};
window.location={reload:function(){calls.reload++;}};
var currentUser=null,currentTenantDefaultPresentationMode=null,bootstrapStatusCache=null;
var API={token:'t-A',refresh:'r-A',post:function(path,body){
    if(path==='/auth/login')return Promise.resolve({access_token:'t-'+body.username,refresh_token:'r-'+body.username,
      user:NEXT_USER});
    return Promise.resolve({});},
  setToken:function(t){this.token=t;return Promise.resolve();},
  setRefreshToken:function(t){this.refresh=t;return Promise.resolve();}};
var NEXT_USER=null;
function showLogin(){calls.showLogin++;}
function showBootstrap(){calls.bootstrap++;}
function hideLogin(){calls.hideLogin++;}
function initApp(){calls.initApp++;return Promise.resolve();}
function ensureFoundationExampleButton(){}
function checkBootstrapStatus(){return Promise.resolve({setup_required:false});}
function enforce2faGate(){return Promise.resolve();}
function openForcePasswordChange(){}
document.getElementById('login-username').value='advB';
document.getElementById('login-password').value='pw';
"""


def _session(scenario: str):
    return run_js(("doLogout", "doLogin"), scenario,
                  prelude=SESSION_PRELUDE + "\n" + _module("session-boundary.js"))


def test_logout_hard_resets_instead_of_keeping_mandate_state():
    out = _session(
        "markAresSessionPrincipal({id:'u-A',tenant_id:'t1'});"
        "return doLogout().then(function(){return {reload:calls.reload,showLogin:calls.showLogin,"
        "token:API.token,refresh:API.refresh};});"
    )
    # Tokens geraeumt, dann frischer Start (kein Weiterleben des Mandatszustands).
    assert out == {"reload": 1, "showLogin": 0, "token": None, "refresh": None}


def test_login_of_other_user_same_tenant_restarts_before_loading_data():
    out = _session(
        "markAresSessionPrincipal({id:'u-A',tenant_id:'t1'});NEXT_USER={id:'u-B',tenant_id:'t1'};"
        "return doLogin().then(function(){return {reload:calls.reload,initApp:calls.initApp,"
        "hideLogin:calls.hideLogin,token:API.token};});"
    )
    assert out == {"reload": 1, "initApp": 0, "hideLogin": 0, "token": "t-advB"}


def test_login_of_user_in_other_tenant_restarts_before_loading_data():
    out = _session(
        "markAresSessionPrincipal({id:'u-A',tenant_id:'t1'});NEXT_USER={id:'u-A',tenant_id:'t2'};"
        "return doLogin().then(function(){return {reload:calls.reload,initApp:calls.initApp};});"
    )
    assert out == {"reload": 1, "initApp": 0}


def test_relogin_of_same_user_after_expiry_keeps_working_without_restart():
    out = _session(
        "markAresSessionPrincipal({id:'u-A',tenant_id:'t1'});NEXT_USER={id:'u-A',tenant_id:'t1'};"
        "return doLogin().then(function(){return {reload:calls.reload,initApp:calls.initApp};});"
    )
    assert out == {"reload": 0, "initApp": 1}


def test_first_login_in_fresh_page_loads_normally():
    out = _session(
        "NEXT_USER={id:'u-B',tenant_id:'t1'};"
        "return doLogin().then(function(){return {reload:calls.reload,initApp:calls.initApp,"
        "principal:aresSessionPrincipal};});"
    )
    assert out == {"reload": 0, "initApp": 1, "principal": "u-B|t1"}


def test_stored_session_boot_and_bootstrap_mark_the_principal():
    src = html()
    boot = src.split("document.addEventListener('DOMContentLoaded'", 1)[1][:6000]
    assert "markAresSessionPrincipal(me)" in boot
    assert "markAresSessionPrincipal(data.user)" in extract_function(src, "doBootstrap") \
        if "function doBootstrap(" in src else "markAresSessionPrincipal(data.user)" in src


# ---------------------------------------------------------------------------
# N-892-01: Server-Wahrheit beim Oeffnen der Seite / Fensterfokus
# ---------------------------------------------------------------------------

GATE_PRELUDE = r"""
var calls={overview:0,wealthOnly:0,dirty:[],reloaded:0};
function mkChart(){return {data:{labels:[],datasets:[{label:'x',data:[]}]},options:{plugins:{legend:{display:false}}},
  update:function(){}};}
var charts={ist:mkChart(),opt:null,aaCurrent:null};
function loadIstHorizonOverride(){return null;}
function projectionHorizonYears(){return 3;}
function projectionYearLabels(r,h,labels){return labels||['2026','2027','2028','2029'];}
function buildCurrentBaselineProjection(){return {seriesK:[100,101,102,103],projectedRappen:10300000000};}
var IST_LABELS=['2026','2027','2028','2029'];
function buildCurrentWealthProjection(scope,years,labels){
  var L=(years==null)?IST_LABELS:(labels||IST_LABELS.slice(0,years+1));
  return {seriesK:L.map(function(_,i){return 500+5*i;}),labels:L,projectedRappen:(500+5*(L.length-1))*100000,
    expectedReturnBps:250,cagrBps:240,annualNetCashflowRappen:0};}
function buildImprovedTotalProjectionFromStrategy(){return {projectedRappen:53000000000,cagrBps:300};}
function simulationCagrBps(){return 410;}
function projectionHorizonYearLabel(sim){var l=sim&&sim.year_labels;return l&&l.length?String(l[l.length-1]):'';}
function sollColor(){return '#1e4b8f';}
function applyDepletionMarkerToDataset(){}
function syncIstProjectionAxisScale(){}
function refreshIstGoalMarkers(){}
function normalizeProjectionChartsPresentation(){}
function syncAaProjectionAxisScales(){}
function wireProjectionChartHoverSync(){}
function renderOverviewProjectionSummary(c){calls.overview++;}
function renderCurrentWealthOnlyProjectionSummary(){calls.wealthOnly++;}
function markStrategyDirty(msg){strategyState.dirty=true;strategyState.staleNotice=msg;calls.dirty.push(msg);}
function isDemoMandateId(){return false;}
var MID='m-A';
function getActiveMandateId(){return MID;}
var ALLOC={target_allocation:{id:'ta-1',set_at:'2026-11-11T10:00:00'},buckets:[{asset_class:'Aktien'}],
  simulation:{year_labels:['2026','2027','2028','2029'],
  target_mix_series_rappen:[10000000000,10600000000,11200000000,11800000000]}};
var RISK={id:'ra-1',is_current:1};
var strategyState={allocation:ALLOC,risk:RISK,dirty:false,staleNotice:null};
var SERVER={mode:'ok'};
var API={get:function(path){
  if(SERVER.mode==='ok')return Promise.resolve(ALLOC);
  if(SERVER.mode==='other')return Promise.resolve({target_allocation:{id:'ta-2',set_at:'2026-11-11T11:00:00'}});
  var e=new Error('x');e.status=SERVER.mode==='409'?409:(SERVER.mode==='500'?500:0);return Promise.reject(e);}};
function loadCurrentAllocationResult(){calls.reloaded++;return Promise.resolve(null);}
"""

NEEDED = ("updateProjectionChartsFromSimulation", "simulationPayload", "simulationSeriesK")


def _gate(scenario: str):
    return run_js(NEEDED, scenario, prelude=GATE_PRELUDE + "\n" + _module("ist-projection-gate.js"))


def _n():
    return "charts.ist.data.datasets.length"


def test_server_rejects_strategy_changed_elsewhere_curve_disappears():
    out = _gate(
        "updateProjectionChartsFromSimulation(ALLOC);var before=" + _n() + ";"
        "SERVER.mode='409';var p=recheckIstProjectionWithServer();var during=" + _n() + ";"
        "return p.then(function(r){return {before:before,during:during,result:r,after:" + _n() + ","
        "dirty:calls.dirty.length,valid:istProjectionStrategyValid()};});"
    )
    assert out == {"before": 2, "during": 1, "result": "invalid", "after": 1, "dirty": 1, "valid": False}


def test_server_confirms_same_strategy_curve_returns_after_check():
    out = _gate(
        "updateProjectionChartsFromSimulation(ALLOC);"
        "var p=recheckIstProjectionWithServer();var during=" + _n() + ";"
        "return p.then(function(r){return {during:during,result:r,after:" + _n() + "};});"
    )
    assert out == {"during": 1, "result": "ok", "after": 2}


def test_network_or_server_error_fails_closed_without_marking_dirty():
    out = _gate(
        "updateProjectionChartsFromSimulation(ALLOC);SERVER.mode='500';"
        "return recheckIstProjectionWithServer().then(function(r){return {result:r,after:" + _n() + ","
        "dirty:calls.dirty.length};});"
    )
    assert out == {"result": "invalid", "after": 1, "dirty": 0}


def test_other_strategy_on_server_is_loaded_instead_of_showing_the_old_curve():
    out = _gate(
        "updateProjectionChartsFromSimulation(ALLOC);SERVER.mode='other';"
        "return recheckIstProjectionWithServer().then(function(r){return {result:r,after:" + _n() + ","
        "reloaded:calls.reloaded};});"
    )
    assert out == {"result": "replaced", "after": 1, "reloaded": 1}


def test_result_of_previous_mandate_is_discarded():
    out = _gate(
        "updateProjectionChartsFromSimulation(ALLOC);SERVER.mode='409';"
        "var p=recheckIstProjectionWithServer();MID='m-B';"
        "return p.then(function(r){return {result:r,dirty:calls.dirty.length};});"
    )
    assert out == {"result": None, "dirty": 0}


def test_recheck_runs_when_opening_the_page_and_on_window_focus():
    src = html()
    go = extract_function(src, "go")
    assert "if(p==='cf'&&typeof recheckIstProjectionWithServer==='function')recheckIstProjectionWithServer();" in go
    module = _module("ist-projection-gate.js")
    assert "window.addEventListener('focus',istProjectionRecheckIfVisible)" in module
    assert "activePageKey()==='cf'" in module


# ---------------------------------------------------------------------------
# Demo-IST-Pfad in initCharts entfernt
# ---------------------------------------------------------------------------

def test_init_charts_has_no_invented_ist_path():
    body = extract_function(html(), "initCharts")
    for needle in ("buildBaselineProjectionFromInputs", "demoCashflows", "2848000", "8500000", "startRappen"):
        assert needle not in body, needle
    assert "const ist=yr.map(function(){return null;});" in body


# ---------------------------------------------------------------------------
# N-892-04: IST-Horizont unabhaengig vom Strategie-Zustand
# ---------------------------------------------------------------------------

def test_ist_line_keeps_full_ist_horizon_with_strategy_and_soll_ends_with_simulation():
    out = _gate(
        "IST_LABELS=['2026','2027','2028','2029','2030','2031'];"
        "updateProjectionChartsFromSimulation(ALLOC);var c=charts.ist.data;"
        "return {labels:c.labels,ist:c.datasets[0].data.length,soll:c.datasets[1].data};"
    )
    assert out["labels"] == ["2026", "2027", "2028", "2029", "2030", "2031"]
    assert out["ist"] == 6
    assert out["soll"][:4] == [100400, 106404, 112408, 118412] and out["soll"][4:] == [None, None]


def test_ist_horizon_identical_without_and_with_strategy():
    out = _gate(
        "IST_LABELS=['2026','2027','2028','2029','2030','2031'];"
        "strategyState.risk=null;updateProjectionChartsFromSimulation(ALLOC);var a=charts.ist.data.labels.slice();"
        "strategyState.risk=RISK;updateProjectionChartsFromSimulation(ALLOC);"
        "return {without:a,with:charts.ist.data.labels};"
    )
    assert out["without"] == out["with"]


def test_tiles_name_their_year_and_ist_tile_is_stable():
    out = _gate(
        "IST_LABELS=['2026','2027','2028','2029','2030','2031'];"
        "renderIstStrategyOverview(ALLOC);"
        "var t=function(id){return document.getElementById(id).textContent;};"
        "var withS={ist:t('ub-ist-terminal'),optL:t('ub-opt-terminal-label'),"
        "deltaL:t('ub-delta-terminal-label'),note:t('ub-projection-note')};"
        "strategyState.risk=null;charts.ist.data.labels=IST_LABELS.slice();renderIstStrategyOverview(ALLOC);"
        "return {withS:withS,optL:t('ub-opt-terminal-label')};"
    )
    w = out["withS"]
    assert w["ist"] == "CHF 525'000"  # IST am IST-Horizontende (2031 = Ende 2030), nicht am Simulationsende
    assert w["optL"] == "Verbessert Ende 2028" and w["deltaL"] == "Mehrwert Ende 2028"
    assert w["note"].startswith("Bis Ende 2030 ") and "bis Ende 2028" in w["note"]
    assert out["optL"] == "Verbessert"


def test_note_names_last_cashflow_year_not_the_valuation_label():
    """Label 2061 = Stand nach dem letzten Cashflow-Jahr 2060 (valid_until inklusiv);
    angezeigt wird "Ende 2060" wie die Horizont-Anzeige "= bis 2060"."""
    src = html()
    body = extract_function(src, "renderCurrentWealthOnlyProjectionSummary")
    assert "istProjectionEndYearLabel(" in body and "'Bis Ende '" in body
    out = _gate("return [istProjectionEndYearLabel('2061'),istProjectionEndYearLabel(2041)];")
    assert out == ["2060", "2040"]
