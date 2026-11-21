"""KN9 / N-933R-02 (CTO-Entscheid, H-186-Pruefung Nachpruefung Fixrunde 1).

Eine gespeicherte manuelle Soll-Allokation ist eine bewusste Entscheidung des
Beraters und gilt als aktuelle Strategie. Nach erfolgreichem Speichern
(``saveManualTargetAllocationFromModal``) ist die Strategie nicht mehr «dirty»,
Finalisieren ist ohne Neuberechnung moeglich (``finalizeLocked`` -> false).
Schlaegt das Speichern fehl, bleibt der vorherige Zustand. Die Server-Pruefungen
beim Finalisieren bleiben unveraendert (nicht Teil dieses Tests).

Echte Funktionen aus dem Monolith-Bundle in Node (``tests/livetest_monolith_js``).
Gegenprobe: alter Stand (``markStrategyDirty(…)`` nach dem Speichern) -> dirty
true, ``finalizeLocked`` sperrt -> rot (``test_counterprobe_old_save_line``).
"""
from __future__ import annotations

from tests.livetest_monolith_js import run_js

FUNCS = ["saveManualTargetAllocationFromModal", "finalizeLocked"]

PRELUDE = r"""
var calls=[];
var __saveFails=false;
var strategyState={dirty:true,staleNotice:'Eingaben geändert: Strategie neu berechnen.',manualSaveRef:null};
function computeManualTargetSaveValidation(){return {valid:true,values:{equities:5000},reason:'Kundenwunsch (fiktiv)'};}
function renderManualTargetSaveState(check,msg,isError){calls.push(['save-state',String(msg||''),!!isError]);}
function getActiveMandateId(){return 'm1';}
function isDemoMandateId(){return false;}
function buildManualTargetAllocationPayload(v){return {values:v};}
function currentManualSaveContext(){return {id:'ta1'};}
function manualTargetSaveErrorText(e){return 'Fehler: '+(e&&e.message);}
function markStrategyDirty(msg){strategyState.dirty=true;strategyState.staleNotice=msg;calls.push(['dirty',String(msg)]);}
function syncStrategyStaleView(){calls.push(['stale-view',strategyState.dirty]);}
function syncPortfolioUmsetzenButtonVisibility(){calls.push(['umsetzen-visibility']);}
function updateStrategyStatus(text,isError){calls.push(['status',String(text),!!isError]);}
var API={post:function(url){calls.push(['post',String(url)]);
  if(__saveFails){var e=new Error('API 409: Konflikt');e.status=409;return Promise.reject(e);}
  return Promise.resolve({id:'ta2',version:3,manual_override_warnings:[]});}};
"""

SCENARIO = r"""
return (async function(){
  var out={};
  calls=[]; __saveFails=false; strategyState.dirty=true;
  out.saved=await saveManualTargetAllocationFromModal();
  out.dirty_after_save=strategyState.dirty;
  out.locked_after_save=finalizeLocked();
  out.calls_ok=calls.slice();
  calls=[]; __saveFails=true; strategyState.dirty=true;
  out.failed=await saveManualTargetAllocationFromModal();
  out.dirty_after_fail=strategyState.dirty;
  out.locked_after_fail=finalizeLocked();
  out.calls_fail=calls.slice();
  return out;
})();
"""


def test_saved_manual_allocation_is_the_current_strategy_and_finalising_is_open():
    out = run_js(FUNCS, SCENARIO, prelude=PRELUDE)
    assert out["saved"] is True
    assert out["dirty_after_save"] is False
    assert out["locked_after_save"] is False
    calls = out["calls_ok"]
    assert ["post", "/mandates/m1/target-allocation"] in calls
    assert not [c for c in calls if c[0] == "dirty"], calls
    assert ["stale-view", False] in calls and ["umsetzen-visibility"] in calls
    assert any(c[0] == "status" and "Manuelle Soll-Allokation gespeichert" in c[1] and not c[2]
               for c in calls), calls


def test_failed_save_keeps_the_lock_and_the_hint_names_existing_actions():
    out = run_js(FUNCS, SCENARIO, prelude=PRELUDE)
    assert out["failed"] is False
    assert out["dirty_after_fail"] is True and out["locked_after_fail"] is True
    hints = [c[1] for c in out["calls_fail"] if c[0] == "status" and c[2]]
    assert any("Zuerst «Anlagestrategie berechnen» oder die manuelle Soll-Allokation speichern" in h
               for h in hints), hints
    assert not any("verwerfen" in h for h in hints), hints


def test_counterprobe_old_save_line():
    """Gegenprobe: mit der alten Zeile (markStrategyDirty nach dem Speichern)
    bleibt die Finalisierung gesperrt."""
    from tests.livetest_monolith_js import extract_function, html

    src = extract_function(html(), "saveManualTargetAllocationFromModal")
    new = ("strategyState.dirty=false;strategyState.staleNotice='';syncStrategyStaleView();"
           "syncPortfolioUmsetzenButtonVisibility();")
    assert new in src
    old_src = src.replace(new, "markStrategyDirty('Manuelle Soll-Allokation gespeichert',false);")
    script = PRELUDE + old_src + "\n" + extract_function(html(), "finalizeLocked") + "\n"
    out = run_js([], SCENARIO, prelude=script)
    assert out["dirty_after_save"] is True and out["locked_after_save"] is True
