"""P5c / N-930-02 (CTO-Entscheid 2026-11-21, H-183-Pruefung): Strategietreue.

Eine neue Strategie (``POST /target-allocation/generate``) entsteht nur durch den
ausdruecklichen Klick «Anlagestrategie berechnen» (bzw. «Neu berechnen» /
«Jetzt berechnen», alle ueber ``refreshStrategyData(true, …)``) oder bei 404
(noch nie berechnet). Klicks mit anderer Absicht -- Bestand speichern/loeschen,
«Empfehlung finalisieren» (``openImplementationRecipe``) und die Bestaetigung
(``confirmImplementationRecipe``) -- laden nur die aktuelle Strategie
(``loadStrategyOnly``). Bei 409 (veraltet): Abbruch, ``dirty``, kein generate,
keine Finalisierung; den Hinweis «Veraltet · Ursache» setzt mandate-view.js.

Vorher riefen diese vier Stellen ``refreshStrategyData(true, true)`` und
ersetzten eine veraltete Strategie still durch einen Entwurf.

Die Funktionen werden aus dem aktuellen Monolith-Bundle extrahiert und in Node
mit Stubs ausgefuehrt (``tests/livetest_monolith_js``), nicht nachgebaut.
Gegenprobe: alter Stand (``refreshStrategyData(true,true)``) -> jeder Fall unten
mit 409 ruft generate auf bzw. ``loadStrategyOnly`` fehlt -> rot.
"""
from __future__ import annotations

from tests.livetest_monolith_js import run_js

FUNCS = [
    "refreshStrategyData", "loadStrategyOnly", "openImplementationRecipe", "confirmImplementationRecipe",
    "savePortfolioHolding", "deletePortfolioHolding", "refreshPortfolioFromStoredState",
    "finalizeLocked", "finalizeErrorText",
]

PRELUDE = r"""
var calls=[];
var __mode=null;           // Antwort von GET current/payload: null=200, sonst HTTP-Status
var __visible=false;
var __recStored=true;      // false = noch keine Empfehlung gespeichert
var __recGenStatus=null;   // Antwort von POST recommendations/generate: null=200, sonst HTTP-Status
var FIDLEG_DETAIL='FIDLEG: Eignungsprüfung fehlt oder ist nicht aktuell — Empfehlung blockiert (require_suitability_before_recommendation=True).';
var strategyState={loading:false,dirty:false,activeMandateId:null,lastGeneratedAt:0,recommendation:null,allocation:null,staleNotice:null};
var currentMandateId='m1';
function getActiveMandateId(){return 'm1';}
function activePageKey(){return 'po';}
function isDemoMandateId(){return false;}
function updateStrategyStatus(text,isError){calls.push(['status',String(text),!!isError]);}
function syncStrategyCalcProgress(){}
async function ensureStrategyReadyRiskForMandate(){return {risk:{id:'r1'}};}
function hasVisibleStrategyOutputs(){return __visible;}
function invalidateStrategyOutputs(){}
function clearPendingStrategyOutputs(){}
function syncStrategyStaleView(){}
function updateProjectionChartsFromSimulation(){}
function renderEngineRuntimePanels(){}
function renderStrategySummary(){}
function applyRecommendationEngineResult(r){strategyState.recommendation=r;}
function applyAllocationEngineResult(){return true;}
function finalizeStrategyOutputs(a,r){strategyState.allocation=a;strategyState.recommendation=r;strategyState.dirty=false;calls.push(['finalize-view']);}
var ALLOC={target_allocation:{id:'ta1',preferences_json:'{}'}};
async function loadCurrentAllocationResult(){
  calls.push(['get','/target-allocation/current/payload']);
  if(__mode){var e=new Error('HTTP '+__mode);e.status=__mode;throw e;}
  return ALLOC;
}
async function loadCurrentRecommendationResult(){return __recStored?{run:{id:'run1',result_status:'Entwurf'}}:null;}
function recommendationPreferencesForStoredAllocation(){return null;}
function collectAllocationPreferencesFromUI(){return {};}
function showStrategyBlocker(){}
async function loadCurrentRiskAssessment(){return null;}
function riskAssessmentReadyForStrategy(){return true;}
function populateRecipeDepotBanks(){}
function eligOverrideReset(){}
function om(id){calls.push(['om',id]);}
function cm(id){calls.push(['cm',id]);}
async function uiConfirm(){return true;}
function refreshAllocationPublication(){}
function printPortfolioPlan(){calls.push(['print']);}
function currentRecommendationRunId(){return 'run1';}
function getInputValue(id){return id==='ap-position-id'?'pos1':(id==='ap-units'?'10':'');}
function parseUnitsMilli(){return 10000;}
function parseCHF(){return 0;}
function setPortfolioHoldingError(){}
function parseApiError(e,f){return f;}
function setPortfolioRefreshButtonState(){}
function renderPortfolioNeutralState(){}
function _silentlyArchiveServerPdf(){}
var API={
  post:function(url){calls.push(['post',String(url)]);
    if(String(url).indexOf('/target-allocation/generate')>=0)return Promise.resolve({target_allocation:{id:'ta2'}});
    if(__recGenStatus&&String(url).indexOf('/recommendations/generate')>=0){
      // wie API.fetch in ares.html: message, status, detail, body
      var err=new Error('API '+__recGenStatus+': '+FIDLEG_DETAIL);err.status=__recGenStatus;err.detail=FIDLEG_DETAIL;
      err.body=JSON.stringify({detail:FIDLEG_DETAIL});return Promise.reject(err);}
    return Promise.resolve({run:{id:'run2'}});},
  get:function(url){calls.push(['get',String(url)]);return Promise.resolve([]);},
  put:function(url){calls.push(['put',String(url)]);return Promise.resolve({});},
  del:function(url){calls.push(['del',String(url)]);return Promise.resolve({});},
  fetch:function(url,opts){calls.push(['fetch',String(url),opts&&opts.method]);return Promise.resolve({});}
};
async function scenario(fn,mode,opts){
  opts=opts||{};
  __mode=mode; __visible=!!opts.visible; calls=[];
  __recStored=opts.recStored!==false; __recGenStatus=opts.recGenStatus||null;
  strategyState.dirty=!!opts.dirty; strategyState.loading=false; strategyState.lastGeneratedAt=opts.fresh?Date.now():0;
  strategyState.activeMandateId='m1'; strategyState.recommendation={run:{id:'run1'}};
  var result;
  try{ result=await fn(); }catch(e){ result='threw:'+(e&&e.message); }
  return {result:result===undefined?null:result, dirty:strategyState.dirty, calls:calls.slice(),
    recommendation:strategyState.recommendation};
}
"""

SCENARIO = r"""
return (async function(){
  var out={};
  var cases={
    load:function(){return loadStrategyOnly(true);},
    open:function(){return openImplementationRecipe();},
    confirm:function(){return confirmImplementationRecipe();},
    save:function(){return savePortfolioHolding();},
    del:function(){return deletePortfolioHolding();},
    portfolio:function(){return refreshPortfolioFromStoredState();},
    click:function(){return refreshStrategyData(true,false);}
  };
  for(var k in cases){
    out[k+'_409']=await scenario(cases[k],409);
    out[k+'_409_dirty_visible']=await scenario(cases[k],409,{dirty:true,visible:true});
    out[k+'_409_cache_fresh']=await scenario(cases[k],409,{fresh:true,visible:true});
    out[k+'_404']=await scenario(cases[k],404);
    out[k+'_200']=await scenario(cases[k],null);
  }
  return out;
})();
"""


def _out() -> dict:
    return run_js(FUNCS, SCENARIO, prelude=PRELUDE)


def _generate(case: dict) -> list:
    return [c for c in case["calls"] if c[0] == "post" and c[1].endswith("/target-allocation/generate")]


def _any_post(case: dict) -> list:
    return [c for c in case["calls"] if c[0] == "post"]


ACTIONS = ("load", "open", "confirm", "save", "del")


def test_actions_with_other_intent_never_regenerate_a_stale_strategy():
    out = _out()
    for action in ACTIONS:
        for variant in ("409", "409_dirty_visible", "409_cache_fresh"):
            case = out[f"{action}_{variant}"]
            assert _generate(case) == [], (action, variant, case)
            assert case["dirty"] is True, (action, variant, case)


def test_stale_strategy_blocks_finalisation_and_the_recipe_modal():
    out = _out()
    for variant in ("409", "409_dirty_visible", "409_cache_fresh"):
        assert ["om", "m-ums"] not in out[f"open_{variant}"]["calls"], variant
        confirm = out[f"confirm_{variant}"]
        assert not [c for c in confirm["calls"] if c[0] == "fetch" and "/finalize" in c[1]], (variant, confirm)
        assert ["print"] not in confirm["calls"], variant
    assert out["load_409"]["result"] is False


def test_holding_save_and_delete_do_not_claim_a_new_drift_when_stale():
    out = _out()
    for action in ("save", "del"):
        statuses = [c[1] for c in out[f"{action}_409"]["calls"] if c[0] == "status"]
        assert not any("Live-Drift" in s for s in statuses), (action, statuses)


def test_current_strategy_loads_without_generate_and_finalises():
    out = _out()
    for action in ACTIONS:
        assert _generate(out[f"{action}_200"]) == [], action
    assert ["om", "m-ums"] in out["open_200"]["calls"]
    assert [c for c in out["confirm_200"]["calls"] if c[0] == "fetch" and "/finalize" in c[1]]
    assert out["load_200"]["result"] is True and out["load_200"]["dirty"] is False


def test_pending_local_changes_stay_marked_after_a_successful_load():
    out = _out()
    case = run_js(FUNCS, r"""
return (async function(){ return await scenario(function(){return loadStrategyOnly(true);},null,{dirty:true,visible:true}); })();
""", prelude=PRELUDE)
    assert _generate(case) == [], case
    assert case["result"] is True and case["dirty"] is True, case
    assert out["load_200"]["dirty"] is False


def test_never_computed_404_still_computes_and_the_explicit_click_always_does():
    """Positivkontrollen: der Stub erkennt generate (404 bzw. ausdruecklicher Klick)."""
    out = _out()
    assert len(_generate(out["load_404"])) == 1, out["load_404"]
    for variant in ("409", "404", "200"):
        assert len(_generate(out[f"click_{variant}"])) == 1, variant


def test_portfolio_generate_on_a_stale_strategy_posts_nothing():
    """«Portfolio generieren» / Seitenwechsel auf Portfolio: bei 409 weder ein
    Strategie- noch ein Portfolio-Neulauf (recommendations/generate nur fuer die
    gueltige aktuelle Soll-Allokation)."""
    out = _out()
    assert _any_post(out["portfolio_409"]) == [], out["portfolio_409"]
    assert _generate(out["portfolio_200"]) == []


NO_REC_SCENARIO = r"""
return (async function(){
  var out={};
  var cases={
    open:function(){return openImplementationRecipe();},
    confirm:function(){return confirmImplementationRecipe();},
    save:function(){return savePortfolioHolding();},
    del:function(){return deletePortfolioHolding();}
  };
  for(var k in cases){
    out[k+'_ok']=await scenario(cases[k],null,{recStored:false});
    out[k+'_rec409']=await scenario(cases[k],null,{recStored:false,recGenStatus:409});
    out[k+'_pending']=await scenario(cases[k],null,{dirty:true,visible:true});
  }
  return out;
})();
"""


def _no_rec_out() -> dict:
    return run_js(FUNCS, NO_REC_SCENARIO, prelude=PRELUDE)


def _rec_generate(case: dict) -> list:
    return [c for c in case["calls"] if c[0] == "post" and c[1].endswith("/recommendations/generate")]


def _finalize_fetch(case: dict) -> list:
    return [c for c in case["calls"] if c[0] == "fetch" and "/finalize" in c[1]]


def test_valid_strategy_without_recommendation_generates_and_finalises():
    """P5c Fixrunde 1 (CTO-Entscheid 3, Probe A des Pruefers): gueltige
    Strategie, noch keine Empfehlung -> genau ein recommendations/generate fuer
    die aktuelle Soll-Allokation, kein target-allocation/generate, Modal oeffnet,
    die Bestaetigung finalisiert den neuen Lauf."""
    out = _no_rec_out()
    opened = out["open_ok"]
    assert len(_rec_generate(opened)) == 1 and _generate(opened) == [], opened
    assert ["finalize-view"] in opened["calls"] and ["om", "m-ums"] in opened["calls"], opened
    confirm = out["confirm_ok"]
    assert len(_rec_generate(confirm)) == 1 and _generate(confirm) == [], confirm
    assert _finalize_fetch(confirm) == [
        ["fetch", "/mandates/m1/recommendations/run2/finalize?confirm_valuations_current=true", "PUT"]
    ], confirm
    statuses = [c[1] for c in confirm["calls"] if c[0] == "status"]
    assert any(s.startswith("Empfehlung finalisiert") for s in statuses), statuses
    assert confirm["dirty"] is False


def test_recommendation_generate_conflict_is_shown_and_never_marks_the_strategy_stale():
    """N-933-02 (CTO-Entscheid 2): ein 409 aus recommendations/generate (z. B.
    FIDLEG-Eignung) ist kein «veraltet». Die Meldung des Servers erscheint, das
    Modal oeffnet nicht, nichts wird finalisiert, dirty bleibt false, kein
    target-allocation/generate. Gegenprobe: alter Stand (ein gemeinsames try)
    -> stumm, dirty=true -> rot."""
    out = _no_rec_out()
    for action in ("open", "confirm", "save", "del"):
        case = out[f"{action}_rec409"]
        assert len(_rec_generate(case)) == 1, (action, case)
        assert _generate(case) == [], (action, case)
        assert case["dirty"] is False, (action, case)
        assert ["om", "m-ums"] not in case["calls"], (action, case)
        assert _finalize_fetch(case) == [], (action, case)
        errors = [c[1] for c in case["calls"] if c[0] == "status" and c[2]]
        assert "Empfehlung konnte nicht erzeugt werden: " + (
            "FIDLEG: Eignungsprüfung fehlt oder ist nicht aktuell — Empfehlung blockiert "
            "(require_suitability_before_recommendation=True).") in errors, (action, case["calls"])


def test_finalising_is_locked_while_local_strategy_changes_are_pending():
    """N-933-04 (CTO-Entscheid 5): solange ungespeicherte lokale Aenderungen an
    der Strategie bestehen (dirty), ist «Empfehlung finalisieren» gesperrt --
    kein Laden, kein Modal, keine Finalisierung, Hinweis sichtbar. Bestand
    speichern/loeschen bleiben moeglich (nur Laden). Gegenprobe: ohne Sperre
    oeffnet das Modal und die gespeicherte Strategie wird finalisiert -> rot."""
    out = _no_rec_out()
    for action in ("open", "confirm"):
        case = out[f"{action}_pending"]
        assert ["om", "m-ums"] not in case["calls"], (action, case)
        assert _finalize_fetch(case) == [] and _any_post(case) == [], (action, case)
        assert not [c for c in case["calls"] if c[0] == "get"], (action, case)
        assert case["dirty"] is True, (action, case)
        errors = [c[1] for c in case["calls"] if c[0] == "status" and c[2]]
        assert any("Zuerst «Anlagestrategie berechnen» oder die manuelle Soll-Allokation speichern" in e for e in errors), errors
    for action in ("save", "del"):
        case = out[f"{action}_pending"]
        assert ["get", "/target-allocation/current/payload"] in case["calls"], (action, case)
        assert _generate(case) == [], (action, case)
