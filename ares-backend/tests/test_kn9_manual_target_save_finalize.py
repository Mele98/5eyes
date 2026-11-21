"""KN9 / N-933R-02 und KN9a / N-934-03 (CTO-Entscheide).

Eine gespeicherte manuelle Soll-Allokation ist eine bewusste Entscheidung des
Beraters und gilt als aktuelle Strategie. Nach erfolgreichem Speichern
(``saveManualTargetAllocationFromModal`` -> ``afterManualTargetSave``) faellt
der Anteil «manuelle Allokation geaendert» (Bandbreiten/Soll-Quoten,
``markStrategyDirty(…, 'manual')``) weg. N-934-03: ein dirty aus ANDEREN
ungespeicherten Aenderungen (Praeferenzen, Tilts, Restriktionen -- nicht in der
manuellen Soll-Allokation enthalten, der Server uebernimmt die Praeferenzen der
bisherigen Allokation) bleibt erhalten; Finalisieren bleibt dann gesperrt und
der Hinweis nennt nur «Anlagestrategie berechnen».
Schlaegt das Speichern fehl, bleibt der vorherige Zustand. Die Server-Pruefungen
beim Finalisieren bleiben unveraendert (nicht Teil dieses Tests).

Echte Funktionen aus dem Monolith-Bundle in Node (``tests/livetest_monolith_js``):
``markStrategyDirty`` (Quelle), ``saveManualTargetAllocationFromModal``,
``afterManualTargetSave``, ``finalizeLocked``.
Gegenproben: Zeile aus KN9 (dirty=false ohne Bedingung) -> der Fall «Tilt
geaendert» wird rot; alter Stand vor KN9 (markStrategyDirty nach dem
Speichern) -> der Fall «nur manuell» wird rot.
"""
from __future__ import annotations

import re

from tests.livetest_monolith_js import extract_function, html, run_js

FUNCS = ["markStrategyDirty", "saveManualTargetAllocationFromModal", "afterManualTargetSave", "finalizeLocked"]

PRELUDE = r"""
var calls=[];
var __saveFails=false;
var strategyState={dirty:false,staleNotice:'',manualSaveRef:null};
function computeManualTargetSaveValidation(){return {valid:true,values:{equities:5000},reason:'Kundenwunsch (fiktiv)'};}
function renderManualTargetSaveState(check,msg,isError){calls.push(['save-state',String(msg||''),!!isError]);}
function getActiveMandateId(){return 'm1';}
function isDemoMandateId(){return false;}
function buildManualTargetAllocationPayload(v){return {values:v};}
function currentManualSaveContext(){return {id:'ta1'};}
function manualTargetSaveErrorText(e){return 'Fehler: '+(e&&e.message);}
function clearPendingStrategyOutputs(){}
function hasVisibleStrategyOutputs(){return true;}
function invalidateStrategyOutputs(){}
function syncStrategyStaleView(){calls.push(['stale-view',strategyState.dirty]);}
function syncPortfolioUmsetzenButtonVisibility(){calls.push(['umsetzen-visibility']);}
function updateStrategyStatus(text,isError){calls.push(['status',String(text),!!isError]);}
var API={post:function(url){calls.push(['post',String(url)]);
  if(__saveFails){var e=new Error('API 409: Konflikt');e.status=409;return Promise.reject(e);}
  return Promise.resolve({id:'ta2',version:3,manual_override_warnings:[]});}};
"""

# Faelle: Ausgangszustand nach berechneter Strategie (dirty=false), dann
# lokale Aenderungen ueber den echten markStrategyDirty.
SCENARIO = r"""
return (async function(){
  async function run(marks, fails){
    calls=[]; __saveFails=!!fails;
    strategyState.dirty=false; strategyState.dirtyOther=false; strategyState.staleNotice='';
    marks.forEach(function(m){markStrategyDirty(m[0],false,m[1]);});
    calls=[];
    var saved=await saveManualTargetAllocationFromModal();
    var r={saved:saved,dirty:strategyState.dirty,notice:strategyState.staleNotice};
    r.save_calls=calls.slice();
    calls=[];
    r.locked=finalizeLocked();
    r.hints=calls.filter(function(c){return c[0]==='status'&&c[2];}).map(function(c){return c[1];});
    return r;
  }
  var out={};
  out.manual_only=await run([['Bandbreiten angepasst: Strategie neu berechnen.','manual']]);
  out.tilt_and_manual=await run([['Tilt geändert: Strategie neu berechnen.'],
                                 ['Bandbreiten angepasst: Strategie neu berechnen.','manual']]);
  out.manual_then_tilt=await run([['Bandbreiten angepasst: Strategie neu berechnen.','manual'],
                                  ['Restriktion geändert: Strategie neu berechnen.']]);
  calls=[]; __saveFails=false; strategyState.dirty=true; strategyState.dirtyOther=undefined;
  out.initial_dirty={saved:await saveManualTargetAllocationFromModal(),dirty:strategyState.dirty};
  out.failed_manual=await run([['Bandbreiten angepasst: Strategie neu berechnen.','manual']], true);
  return out;
})();
"""


def _out():
    return run_js(FUNCS, SCENARIO, prelude=PRELUDE)


def test_only_manual_change_saved_means_current_strategy_and_finalising_is_open():
    case = _out()["manual_only"]
    assert case["saved"] is True
    assert case["dirty"] is False and case["notice"] == ""
    assert case["locked"] is False
    calls = case["save_calls"]
    assert ["post", "/mandates/m1/target-allocation"] in calls
    assert ["stale-view", False] in calls and ["umsetzen-visibility"] in calls
    assert any(c[0] == "status" and "Manuelle Soll-Allokation gespeichert: die angezeigten Kennzahlen" in c[1]
               and not c[2] for c in calls), calls


def test_initial_dirty_without_a_source_is_cleared_by_the_save():
    """Startzustand dirty=true (vor dem Laden, ohne markStrategyDirty) -- wie
    im Band-Editor-Harness: keine andere Aenderung bekannt."""
    case = _out()["initial_dirty"]
    assert case["saved"] is True and case["dirty"] is False


def test_other_unsaved_change_keeps_dirty_after_the_manual_save():
    """N-934-03: ein Tilt bzw. eine Restriktion (nicht in der manuellen
    Soll-Allokation enthalten) bleibt markiert, egal in welcher Reihenfolge."""
    out = _out()
    for key in ("tilt_and_manual", "manual_then_tilt"):
        case = out[key]
        assert case["saved"] is True, key
        assert case["dirty"] is True, key
        assert "nicht in der manuellen Soll-Allokation enthalten" in case["notice"], key
        assert case["locked"] is True, key
        # Der Hinweis nennt nur den Weg, der die Aenderung wirklich uebernimmt.
        assert case["hints"] == ["Finalisieren gesperrt: ungespeicherte Änderungen an der Strategie. "
                                 "Zuerst «Anlagestrategie berechnen»."], (key, case["hints"])
        assert any(c[0] == "status" and "Weitere ungespeicherte Änderungen" in c[1] and not c[2]
                   for c in case["save_calls"]), (key, case["save_calls"])
        assert ["stale-view", True] in case["save_calls"], key


def test_failed_save_keeps_the_lock_and_the_hint_names_existing_actions():
    case = _out()["failed_manual"]
    assert case["saved"] is False
    assert case["dirty"] is True and case["locked"] is True
    assert any("Zuerst «Anlagestrategie berechnen» oder die manuelle Soll-Allokation speichern" in h
               for h in case["hints"]), case["hints"]
    assert not any("verwerfen" in h for h in case["hints"]), case["hints"]


def _run_with(save_src: str, after_src: str | None = None):
    src = html()
    parts = [extract_function(src, "markStrategyDirty"), save_src,
             after_src if after_src is not None else extract_function(src, "afterManualTargetSave"),
             extract_function(src, "finalizeLocked")]
    return run_js([], SCENARIO, prelude=PRELUDE + "\n".join(parts) + "\n")


def test_counterprobe_unconditional_reset_loses_the_other_change():
    """Gegenprobe N-934-03: mit der Zeile aus KN9 (dirty=false ohne Bedingung)
    waere der Tilt-Fall nicht mehr gesperrt."""
    old_after = ("function afterManualTargetSave(){strategyState.dirty=false;strategyState.staleNotice='';"
                 "syncStrategyStaleView();syncPortfolioUmsetzenButtonVisibility();}")
    out = _run_with(extract_function(html(), "saveManualTargetAllocationFromModal"), old_after)
    assert out["tilt_and_manual"]["dirty"] is False and out["tilt_and_manual"]["locked"] is False


def test_counterprobe_old_save_line():
    """Gegenprobe N-933R-02: mit der alten Zeile (markStrategyDirty nach dem
    Speichern) bleibt auch der Fall «nur manuell» gesperrt."""
    src = extract_function(html(), "saveManualTargetAllocationFromModal")
    new = "afterManualTargetSave();"
    assert new in src
    old_src = src.replace(new, "markStrategyDirty('Manuelle Soll-Allokation gespeichert',false);")
    out = _run_with(old_src)
    assert out["manual_only"]["dirty"] is True and out["manual_only"]["locked"] is True


def test_band_editor_changes_are_marked_as_manual_and_others_are_not():
    """Nur die Bandbreiten-Aenderungen des Editors (Inhalt der manuellen
    Soll-Allokation) tragen die Quelle 'manual'."""
    src = html()
    for message in ("Bandbreiten aktualisiert: Strategie neu berechnen.",
                    "Bandbreiten angepasst: Strategie neu berechnen.",
                    "Individuelle Bandbreiten zurückgesetzt: Strategie neu berechnen."):
        assert f"markStrategyDirty('{message}',0,'manual')" in src, message
    assert len(re.findall(r"markStrategyDirty\([^;]*,'manual'\);", src)) == 3
    assert "markStrategyDirty(strategyBlockDirtyMessage(el));" in src  # Tilts/Praeferenzen: andere Quelle
    assert "markStrategyDirty('Begründung der Bandbreiten-Abweichung geändert: Strategie neu berechnen.');" in src
