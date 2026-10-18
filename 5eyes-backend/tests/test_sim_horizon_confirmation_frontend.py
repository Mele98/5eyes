"""SIM-HORIZON-CONFIRM-001 -- Monolith: Banner "Horizont bestaetigen".

CIO-Entscheid (2026-10-17): KEINE automatische Migration gespeicherter
Horizonte (der fruehere Branch-Stand stellte den Alt-Default '10' still auf
Auto um). Stattdessen erscheint fuer jeden Horizont, der VOR SIM-HORIZON-
ALWAYS-EXPLICIT-001 (#611) gespeichert wurde, einmalig ein Banner mit dem
Wert, einem Bestaetigen-Button und optionaler Aenderung.

"Vor der Umstellung" wird aus dem Datenmodell abgeleitet: ab jetzt traegt
jede ausdrueckliche Wahl ``simulation.horizonExplicit=true``; ein
``horizonYears`` OHNE dieses Flag stammt aus der Zeit, als die UI den Wert
immer schrieb. Nach Bestaetigung: Flag im editierbaren Store und -- falls
der Wert der aktuellen Soll-Allokation entspricht -- serverseitiger Vermerk
(``sim_horizon_confirmed_at``), damit das Banner auch nach Reload/Hydration
und auf anderen Geraeten weg bleibt.

Die Tests fuehren die ECHTEN Monolith-Funktionen in Node aus (nur DOM,
localStorage und API sind gefaked).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from services.portfolio_engine import _normalize_preferences  # noqa: E402

HTML_PATH = BACKEND_DIR.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"

_REQUIRED_FUNCTIONS = (
    "cloneJSON",
    "buildDefaultAllocationPreferences",
    "mergeAllocationPreferences",
    "loadAllocationPreferences",
    "persistAllocationPreferences",
    "getInputValue",
    "getCheckboxValue",
    "setSelectValue",
    "setCheckboxValue",
    "setRadioValue",
    "_lifeExpectancyEndYear",
    "_lifeExpectancyHorizonYears",
    "collectAllocationPreferencesFromUI",
    "applyAllocationPreferencesToUI",
    "readSimulationHorizonOverride",
    "setSimulationHorizonSelectValue",
    "bindAllocationPreferenceControls",
)
# Fehlen sie (alter Stand), wird der Test am Verhalten rot, nicht an der Extraktion.
_OPTIONAL_FUNCTIONS = (
    "markSimulationHorizonExplicit",
    "isSimulationHorizonExplicit",
    "simHorizonNeedsConfirmation",
    "simHorizonConfirmedOnServer",
    "hydrateAllocationPreferencesFromServer",
    "renderSimHorizonConfirmBanner",
    "confirmSimHorizonFromBanner",
    # Alt-Stand (automatische Migration) -- wird mitgeladen, falls vorhanden,
    # damit der Reproducer den alten Code wirklich ausfuehrt.
    "readSimHorizonLegacyMarker",
    "writeSimHorizonLegacyMarker",
    "isLegacySimHorizonDefault",
    "runSimHorizonLegacyMigration",
    "markSimHorizonNoticePending",
    "dropLegacySimHorizonFromSnapshot",
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _extract_function(src: str, name: str) -> str | None:
    match = re.search(r"\n(?:async )?function " + re.escape(name) + r"\(", src)
    if not match:
        return None
    start = match.start() + 1
    i = src.index("{", src.index(")", start))
    depth, j = 1, i + 1
    while depth:
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        j += 1
    return src[start:j]


def _horizon_select_options(src: str) -> list[dict]:
    block = re.search(
        r'<select[^>]*id="aa-sim-horizon"[^>]*>(.*?)</select>', src, re.S
    ).group(1)
    return [
        {"value": value, "selected": bool(selected)}
        for value, selected in re.findall(
            r'<option value="([^"]*)"( selected)?[^>]*>', block
        )
    ]


_HARNESS = r"""
var __ls={};
var localStorage={
  get length(){return Object.keys(__ls).length;},
  key:function(i){return Object.keys(__ls)[i]||null;},
  getItem:function(k){return Object.prototype.hasOwnProperty.call(__ls,k)?__ls[k]:null;},
  setItem:function(k,v){__ls[k]=String(v);},
  removeItem:function(k){delete __ls[k];}
};
function __mkEl(id){
  return {id:id,style:{display:'none'},textContent:'',value:'',checked:false,
    classList:{contains:function(){return false;}},
    __handlers:{},
    addEventListener:function(type,fn){(this.__handlers[type]=this.__handlers[type]||[]).push(fn);}};
}
function __mkSelect(id,opts){
  var el=__mkEl(id);
  el.options=[];
  el.appendChild=function(o){this.options.push(o);};
  Object.defineProperty(el,'innerHTML',{get:function(){return '';},set:function(){this.options=[];this._v='';}});
  Object.defineProperty(el,'value',{
    get:function(){return this._v;},
    // Browser-Semantik: Wert ausserhalb der Optionsliste -> ''.
    set:function(v){var s=String(v);this._v=this.options.some(function(o){return String(o.value)===s;})?s:'';}
  });
  opts.forEach(function(o){el.options.push({value:o.value,textContent:o.value});});
  var sel=opts.filter(function(o){return o.selected;})[0]||opts[0];
  el._v=sel?sel.value:'';
  return el;
}
var __els={};
var document={
  getElementById:function(id){
    if(!__els[id]){
      if(id==='aa-sim-horizon')__els[id]=__mkSelect(id,__HORIZON_OPTIONS);
      else if(id==='al-sim-horizon-confirm-select')__els[id]=__mkSelect(id,[]);
      else __els[id]=__mkEl(id);
    }
    return __els[id];
  },
  createElement:function(){return {value:'',textContent:''};},
  querySelectorAll:function(){return [];}
};
function __fire(id,type){
  var el=document.getElementById(id);
  (el.__handlers[type]||[]).forEach(function(fn){fn({target:el});});
}
var currentPersona=null;
var allocationPreferencesCache={};
var allocationPreferenceStoragePrefix='5eyes.allocprefs.';
var strategyState={dirty:false,allocation:null};
function getAllocationPreferenceKey(){return 'mandate:M1';}
function getActiveMandateId(){return 'M1';}
function arrMax(a){return Math.max.apply(null,a);}
function getRadioValue(name,fallback){return fallback;}
function hasCanonicalBandBaseline(){return false;}
function collectBandOverridesFromModal(){return null;}
function updateAllocationPreferencesEntryButton(){}
function updateBandOverrideStatus(){}
// Echte renderAllocationPreferenceSummary ruft den Banner-Renderer auf (siehe
// test_summary_renders_banner); hier nur dieser Teil.
function renderAllocationPreferenceSummary(){
  if(typeof renderSimHorizonConfirmBanner==='function')renderSimHorizonConfirmBanner();
  if(typeof renderSimHorizonMigrationNotice==='function')renderSimHorizonMigrationNotice();
}
var __dirty=[];
function markStrategyDirty(msg){strategyState.dirty=true;__dirty.push(msg);}
var __errors=[];
function showAppError(msg){__errors.push(String(msg));}
var __posts=[];
var __apiFail=false;
var API={post:async function(url,body){
  __posts.push({url:url,body:body});
  if(__apiFail)throw new Error('offline');
  return {target_allocation_id:'TA1',horizon_years:body.horizon_years,
    sim_horizon_confirmed_at:'2026-10-17T10:00:00.000Z',sim_horizon_confirmed_by:'u1',already_confirmed:false};
}};
function __banner(){
  var b=document.getElementById('al-sim-horizon-confirm-banner');
  var s=document.getElementById('al-sim-horizon-confirm-select');
  return {visible:b.style.display!=='none',
    text:document.getElementById('al-sim-horizon-confirm-text').textContent,
    select:s.value,options:(s.options||[]).map(function(o){return o.value;})};
}
function __stored(){var raw=__ls['5eyes.allocprefs.mandate:M1'];return raw?JSON.parse(raw):null;}
function __reload(){allocationPreferencesCache={};strategyState.dirty=false;}
function __open(){applyAllocationPreferencesToUI(loadAllocationPreferences());}
"""


def _run(scenario_js: str, html: str | None = None) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    src = html if html is not None else _html()
    fns = []
    for name in _REQUIRED_FUNCTIONS:
        body = _extract_function(src, name)
        assert body, f"Monolith-Funktion {name} nicht gefunden"
        fns.append(body)
    for name in _OPTIONAL_FUNCTIONS:
        body = _extract_function(src, name)
        if body:
            fns.append(body)
    script = (
        "var __HORIZON_OPTIONS=" + json.dumps(_horizon_select_options(src)) + ";\n"
        + _HARNESS
        + "\n".join(fns)
        + "\n(async function(){" + scenario_js + "})()"
        + ".then(function(out){console.log(JSON.stringify(out));})"
        + ".catch(function(e){console.error(e&&e.stack||e);process.exit(1);});\n"
    )
    res = subprocess.run(
        ["node", "-"], input=script, capture_output=True, text=True,
        timeout=30, check=False, encoding="utf-8",
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def _seed(prefs: dict) -> str:
    return (
        "__ls['5eyes.allocprefs.mandate:M1']="
        + json.dumps(json.dumps(prefs)) + ";"
    )


def _legacy_ta(horizon, confirmed_at=None) -> str:
    ta = {
        "id": "TA1",
        "set_at": "2026-09-01T10:00:00.000Z",
        "preferences_json": json.dumps(
            {"simulation": {"horizonYears": horizon, "stressMultiplier": "1.0"},
             "policy": {"esg": "best_in_class"}}
        ),
        "sim_horizon_confirmed_at": confirmed_at,
    }
    return "strategyState.allocation={target_allocation:" + json.dumps(ta) + "};"


_LEGACY = {"simulation": {"horizonYears": "10", "stressMultiplier": "1.0",
                          "monteCarloRuns": "750"},
           "policy": {"esg": "best_in_class"}}


# ---------------------------------------------------------------------------
# Erkennung "vor der Umstellung" + keine automatische Migration
# ---------------------------------------------------------------------------


def test_legacy_value_shows_banner_and_is_not_migrated():
    out = _run(
        _seed(_LEGACY)
        + "__open();"
        + "return {banner:__banner(),stored:__stored(),prefs:collectAllocationPreferencesFromUI()};"
    )
    assert out["banner"]["visible"], "Alt-Horizont muss das Bestaetigungs-Banner zeigen"
    assert "10 Jahre" in out["banner"]["text"]
    assert out["banner"]["select"] == "10"
    assert "" in out["banner"]["options"], "Banner muss 'Auto' als Aenderung anbieten"
    # CIO-Entscheid: KEINE automatische Migration -- Wert bleibt, wie er war.
    assert out["stored"]["simulation"]["horizonYears"] == "10"
    assert "horizonExplicit" not in out["stored"]["simulation"]
    assert out["prefs"]["simulation"]["horizonYears"] == "10"
    assert "horizonExplicit" not in out["prefs"]["simulation"], (
        "ein unbestaetigter Alt-Wert darf nicht als ausdrueckliche Wahl gesendet werden"
    )


@pytest.mark.parametrize("horizon", ["27", 10, "37"])
def test_any_legacy_horizon_value_needs_confirmation(horizon):
    out = _run(_seed({"simulation": {"horizonYears": horizon}}) + "__open();return __banner();")
    assert out["visible"]
    assert out["select"] == str(horizon), "Wert (auch ausserhalb der Optionsliste) anzeigen"


def test_auto_horizon_shows_no_banner():
    out = _run(_seed({"simulation": {"stressMultiplier": "1.0"}}) + "__open();return __banner();")
    assert not out["visible"]


def test_explicit_horizon_shows_no_banner():
    out = _run(
        _seed({"simulation": {"horizonYears": "15", "horizonExplicit": True}})
        + "__open();return {banner:__banner(),prefs:collectAllocationPreferencesFromUI()};"
    )
    assert not out["banner"]["visible"]
    assert out["prefs"]["simulation"]["horizonExplicit"] is True


def test_select_change_marks_choice_explicit():
    out = _run(
        _seed({"simulation": {"stressMultiplier": "1.0"}})
        + "bindAllocationPreferenceControls();__open();"
        + "document.getElementById('aa-sim-horizon').value='20';__fire('aa-sim-horizon','change');"
        + "return {prefs:collectAllocationPreferencesFromUI(),banner:__banner()};"
    )
    assert out["prefs"]["simulation"]["horizonYears"] == "20"
    assert out["prefs"]["simulation"]["horizonExplicit"] is True
    assert not out["banner"]["visible"]


def test_switching_to_auto_via_select_sends_no_flag():
    out = _run(
        _seed({"simulation": {"horizonYears": "15", "horizonExplicit": True}})
        + "bindAllocationPreferenceControls();__open();"
        + "document.getElementById('aa-sim-horizon').value='';__fire('aa-sim-horizon','change');"
        + "return collectAllocationPreferencesFromUI();"
    )
    assert "horizonYears" not in out["simulation"]
    assert "horizonExplicit" not in out["simulation"]


# ---------------------------------------------------------------------------
# Bestaetigen
# ---------------------------------------------------------------------------


def test_confirm_unchanged_persists_locally_and_on_server_and_stays_hidden():
    out = _run(
        _seed(_LEGACY) + _legacy_ta("10")
        + "__open();var r=await confirmSimHorizonFromBanner();"
        + "var after={result:r,banner:__banner(),stored:__stored(),posts:__posts,dirty:__dirty,"
        + "ta:strategyState.allocation.target_allocation};"
        + "__reload();__open();after.reloaded=__banner();"
        + "after.prefs=collectAllocationPreferencesFromUI();return after;"
    )
    assert out["result"] == {"changed": False, "serverConfirmed": True}
    assert out["posts"] == [{
        "url": "/mandates/M1/target-allocation/current/sim-horizon-confirmation",
        "body": {"horizon_years": 10},
    }]
    assert out["stored"]["simulation"]["horizonYears"] == "10"
    assert out["stored"]["simulation"]["horizonExplicit"] is True
    assert out["ta"]["sim_horizon_confirmed_at"] == "2026-10-17T10:00:00.000Z"
    assert not out["banner"]["visible"]
    assert not out["reloaded"]["visible"], "Banner muss dauerhaft weg bleiben"
    assert out["dirty"] == [], "unveraenderter Wert macht die Strategie nicht veraltet"
    assert out["prefs"]["simulation"]["horizonExplicit"] is True


def test_confirm_survives_server_hydration_on_other_device():
    """Neues Geraet / geleerter Browser: Hydration aus dem Snapshot (ohne Flag)
    plus serverseitige Bestaetigung -> kein Banner."""
    out = _run(
        "var result={target_allocation:{preferences_json:"
        + json.dumps(json.dumps(_LEGACY))
        + ",sim_horizon_confirmed_at:'2026-10-17T10:00:00.000Z'}};"
        + "var snapshotBefore=result.target_allocation.preferences_json;"
        + "hydrateAllocationPreferencesFromServer(result);"
        + "return {banner:__banner(),stored:__stored(),"
        + "snapshotUnchanged:result.target_allocation.preferences_json===snapshotBefore,"
        + "prefs:collectAllocationPreferencesFromUI()};"
    )
    assert not out["banner"]["visible"]
    assert out["stored"]["simulation"]["horizonExplicit"] is True
    assert out["stored"]["simulation"]["horizonYears"] == "10"
    assert out["snapshotUnchanged"]
    assert out["prefs"]["simulation"]["horizonExplicit"] is True


def test_unconfirmed_server_snapshot_hydrates_into_banner_without_migration():
    out = _run(
        "var result={target_allocation:{preferences_json:"
        + json.dumps(json.dumps(_LEGACY))
        + ",set_at:'2026-01-01T00:00:00.000Z',sim_horizon_confirmed_at:null}};"
        + "hydrateAllocationPreferencesFromServer(result);"
        + "return {banner:__banner(),stored:__stored()};"
    )
    assert out["banner"]["visible"]
    assert out["stored"]["simulation"]["horizonYears"] == "10"
    assert "horizonExplicit" not in out["stored"]["simulation"]


def test_confirm_when_server_snapshot_differs_stays_local():
    out = _run(
        _seed(_LEGACY) + _legacy_ta("12")
        + "__open();var r=await confirmSimHorizonFromBanner();"
        + "return {result:r,posts:__posts,banner:__banner(),stored:__stored()};"
    )
    assert out["posts"] == [], "anderer Snapshot-Wert darf nicht serverseitig bestaetigt werden"
    assert out["result"]["serverConfirmed"] is False
    assert out["stored"]["simulation"]["horizonExplicit"] is True
    assert not out["banner"]["visible"]


def test_confirm_server_failure_is_reported_not_silent():
    out = _run(
        _seed(_LEGACY) + _legacy_ta("10") + "__apiFail=true;"
        + "__open();var r=await confirmSimHorizonFromBanner();"
        + "return {result:r,errors:__errors,stored:__stored()};"
    )
    assert out["result"]["serverConfirmed"] is False
    assert out["errors"] and "nicht gespeichert" in out["errors"][0]
    assert out["stored"]["simulation"]["horizonExplicit"] is True


def test_change_in_banner_sets_new_explicit_value_and_marks_dirty():
    out = _run(
        _seed(_LEGACY) + _legacy_ta("10")
        + "__open();document.getElementById('al-sim-horizon-confirm-select').value='15';"
        + "var r=await confirmSimHorizonFromBanner();"
        + "return {result:r,posts:__posts,stored:__stored(),dirty:__dirty,banner:__banner(),"
        + "select:document.getElementById('aa-sim-horizon').value,"
        + "prefs:collectAllocationPreferencesFromUI()};"
    )
    assert out["result"] == {"changed": True, "serverConfirmed": False}
    assert out["posts"] == [], "geaenderter Wert wird mit der naechsten Berechnung gespeichert"
    assert out["stored"]["simulation"]["horizonYears"] == "15"
    assert out["stored"]["simulation"]["horizonExplicit"] is True
    assert out["select"] == "15"
    assert len(out["dirty"]) == 1
    assert not out["banner"]["visible"]
    assert out["prefs"]["simulation"] == {**out["prefs"]["simulation"], "horizonYears": "15", "horizonExplicit": True}


def test_change_to_auto_in_banner_removes_override():
    out = _run(
        _seed(_LEGACY)
        + "__open();document.getElementById('al-sim-horizon-confirm-select').value='';"
        + "var r=await confirmSimHorizonFromBanner();"
        + "return {result:r,stored:__stored(),banner:__banner(),dirty:__dirty,"
        + "prefs:collectAllocationPreferencesFromUI()};"
    )
    assert out["result"]["changed"] is True
    assert "horizonYears" not in out["stored"]["simulation"]
    assert "horizonExplicit" not in out["stored"]["simulation"]
    assert "horizonYears" not in out["prefs"]["simulation"]
    assert not out["banner"]["visible"]
    assert len(out["dirty"]) == 1


# ---------------------------------------------------------------------------
# Kette Monolith -> Schema + HTML-Vertrag
# ---------------------------------------------------------------------------


def test_chain_confirmed_flag_passes_backend_schema():
    prefs = _run(
        _seed(_LEGACY) + "__open();await confirmSimHorizonFromBanner();"
        + "return collectAllocationPreferencesFromUI();"
    )
    normalized = _normalize_preferences(prefs)
    assert normalized["simulation"]["horizonExplicit"] is True
    assert normalized["simulation"]["horizonYears"] == "10"


def test_html_contract_banner_and_no_auto_migration():
    html = _html()
    banner = html.split('id="al-sim-horizon-confirm-banner"', 1)
    assert len(banner) == 2, "Banner 'Horizont bestaetigen' fehlt in der AA-Ansicht"
    block = banner[1].split("</div>\n      <div class=\"pad\">", 1)[0]
    assert "Horizont bestätigen" in block
    assert 'id="al-sim-horizon-confirm-select"' in block
    assert "confirmSimHorizonFromBanner()" in block
    assert "Bestätigen" in block
    summary = _extract_function(html, "renderAllocationPreferenceSummary")
    assert "renderSimHorizonConfirmBanner()" in summary
    for remnant in ("runSimHorizonLegacyMigration", "simHorizonAutoMigration",
                    "al-sim-horizon-migrated-banner"):
        assert remnant not in html, f"Auto-Migrations-Rest {remnant} im Monolith"
