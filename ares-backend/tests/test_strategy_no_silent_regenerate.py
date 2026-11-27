"""H-185 / CTO-Entscheid 2026-11-21: keine stille Neuberechnung im Classic-UI.

Befund (KN3-U-Livetest Zeile 324, H-185): ``refreshStrategyData()`` lief im
Zweig «nicht dirty» bei 409 (gespeicherte Soll-Allokation veraltet) und bei
jedem anderen Ladefehler ausser 404 weiter in ``POST /target-allocation/generate``
und ersetzte die veraltete Strategie ohne Klick durch einen neuen Entwurf.
Das verletzt die Strategietreue (keine Neuberechnung ohne Ausloeser durch den
Berater).

Vertrag:

* 404 (noch nie berechnet): automatische Berechnung wie bisher (Positivkontrolle).
* 409 (veraltet): ``strategyState.dirty = true``, Rueckgabe ``false``, kein
  generate-Aufruf. Der Hinweis «Veraltet · Ursache» kommt aus mandate-view.js.
* jeder andere Fehler: Fehlermeldung, kein generate-Aufruf.

Die Funktion wird aus dem aktuellen Monolithen extrahiert und in Node mit
Stubs ausgefuehrt (``tests/livetest_monolith_js``), nicht nachgebaut.
Gegenprobe: alter catch-Zweig -> 409 und 500 rufen generate auf -> rot.
"""
from __future__ import annotations

from tests.livetest_monolith_js import run_js

PRELUDE = r"""
var calls=[];
var __mode=null;
var strategyState={loading:false,dirty:false,activeMandateId:null,lastGeneratedAt:0,recommendation:null,allocation:null};
function getActiveMandateId(){return 'm1';}
function activePageKey(){return 'al';}
function isDemoMandateId(){return false;}
function updateStrategyStatus(text,isError){calls.push(['status',String(text),!!isError]);}
function syncStrategyCalcProgress(){}
async function ensureStrategyReadyRiskForMandate(){return {risk:{id:'r1'}};}
function hasVisibleStrategyOutputs(){return false;}
function invalidateStrategyOutputs(){}
async function loadCurrentAllocationResult(){
  if(__mode){var e=new Error('HTTP '+__mode);e.status=__mode;throw e;}
  return null;
}
async function loadCurrentRecommendationResult(){return null;}
function collectAllocationPreferencesFromUI(){return {};}
function showStrategyBlocker(){}
async function loadCurrentRiskAssessment(){return null;}
var API={
  post:function(url){calls.push(['post',String(url)]);var e=new Error('stub');e.status=599;return Promise.reject(e);},
  get:function(url){calls.push(['get',String(url)]);return Promise.resolve([]);}
};
"""

SCENARIO = r"""
async function run(mode){
  __mode=mode; calls=[]; strategyState.dirty=false; strategyState.loading=false;
  var result;
  try{ result=await refreshStrategyData(false,false); }catch(e){ result='threw'; }
  return {result:result, dirty:strategyState.dirty, calls:calls.slice()};
}
return (async function(){
  return {c409:await run(409), c500:await run(500), c404:await run(404)};
})();
"""


def _generate_calls(case: dict) -> list:
    return [c for c in case["calls"] if c[0] == "post" and c[1].endswith("/target-allocation/generate")]


def test_stale_allocation_409_never_triggers_generate():
    out = run_js(["refreshStrategyData"], SCENARIO, prelude=PRELUDE)
    c409 = out["c409"]
    assert _generate_calls(c409) == [], c409
    assert c409["result"] is False and c409["dirty"] is True, c409


def test_other_load_errors_show_message_without_generate():
    out = run_js(["refreshStrategyData"], SCENARIO, prelude=PRELUDE)
    c500 = out["c500"]
    assert _generate_calls(c500) == [], c500
    assert c500["result"] is False, c500
    assert any(c[0] == "status" and c[2] and "nicht geladen" in c[1] for c in c500["calls"]), c500


def test_never_computed_404_still_computes_automatically():
    """Positivkontrolle: der Stub erkennt einen generate-Aufruf."""
    out = run_js(["refreshStrategyData"], SCENARIO, prelude=PRELUDE)
    assert len(_generate_calls(out["c404"])) == 1, out["c404"]
