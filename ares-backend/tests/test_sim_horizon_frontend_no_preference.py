"""SIM-HORIZON-FROM-RISK-PROFILE-001 -- Monolith: kein Prognose-Horizont als Praeferenz.

CIO-Entscheid (2026-10-18): "Horizont bestaetigen" und die Horizont-Auswahl in
der Asset-Allocation-Ansicht sind entfernt. Der Horizont wird im Risikoprofil
hergeleitet und vom Backend uebernommen (max(7, Risikoprofil, Ziele,
Lebenserwartung)); der Berater trifft dazu keine Entscheidung mehr.

Vorgaenger (umgeschrieben, Invarianten uebernommen):
* SIM-HORIZON-ALWAYS-EXPLICIT-001 (#611): ein unberuehrter Select durfte keinen
  Override senden -- gilt weiter, jetzt fuer JEDEN Zustand.
* SIM-HORIZON-CONFIRM-001 (#622): Banner/Bestaetigung -- entfernt; Alt-Werte
  aus localStorage und Server-Snapshot duerfen weder angezeigt noch
  zurueckgesendet werden.

Die Datei fuehrt die ECHTEN Monolith-Funktionen in Node aus (DOM,
localStorage und Umgebung sind gefaked) und reicht deren Ausgabe durch die
echte Backend-Kette (`_normalize_preferences` -> `_simulation_horizon_years`).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from services.portfolio_engine import _normalize_preferences  # noqa: E402
from services.portfolio_engine_mc_simulation import (  # noqa: E402
    _simulation_horizon_years,
)

HTML_PATH = BACKEND_DIR.parent / "ares-desktop" / "frontend" / "ares.html"

_REQUIRED_FUNCTIONS = (
    "cloneJSON",
    "buildDefaultAllocationPreferences",
    "mergeAllocationPreferences",
    "loadAllocationPreferences",
    "persistAllocationPreferences",
    "hydrateAllocationPreferencesFromServer",
    "getInputValue",
    "getCheckboxValue",
    "setSelectValue",
    "setCheckboxValue",
    "setRadioValue",
    "_lifeExpectancyEndYear",
    "_lifeExpectancyHorizonYears",
    "collectAllocationPreferencesFromUI",
    "applyAllocationPreferencesToUI",
    # ESG-PREMIUM-CRITERIA-001: von collect/apply aufgerufene Begruendungs-Helfer.
    "collectTiltReasonsFromUI",
    "syncTiltReasonVisibility",
    "simulationPayload",
)
# Neue Helfer bzw. Alt-Stand (#611/#622). Fehlen sie, wird der Test NICHT an
# der Extraktion rot, sondern am Verhalten -- so laeuft der Reproducer auch
# gegen den alten Code.
_OPTIONAL_FUNCTIONS = (
    "stripLegacySimulationHorizon",
    "renderSimulationHorizonInfo",
    "readSimulationHorizonOverride",
    "setSimulationHorizonSelectValue",
    "applyMandateHorizonToSimulationFields",
    "markSimulationHorizonExplicit",
    "isSimulationHorizonExplicit",
    "simHorizonNeedsConfirmation",
    "simHorizonConfirmedOnServer",
    "renderSimHorizonConfirmBanner",
    "confirmSimHorizonFromBanner",
)
_OPTIONAL_GLOBALS = ("LEGACY_SIMULATION_HORIZON_KEYS",)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _extract_function(src: str, name: str) -> str | None:
    match = re.search(r"\n(?:async )?function " + re.escape(name) + r"\(", src)
    if not match:
        return None
    start = match.start() + 1
    i = src.index("{", start)
    depth, j = 1, i + 1
    while depth:
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        j += 1
    return src[start:j]


def _extract_global(src: str, name: str) -> str | None:
    match = re.search(r"\nvar " + re.escape(name) + r"=[^\n]*;", src)
    return match.group(0).strip() if match else None


def _horizon_select_options(src: str) -> list[dict]:
    """Alt-Stand: Optionen des (entfernten) Selects, sonst leer."""
    match = re.search(
        r'<select[^>]*id="aa-sim-horizon"[^>]*>(.*?)</select>', src, re.S
    )
    if not match:
        return []
    return [
        {"value": value, "selected": bool(selected)}
        for value, selected in re.findall(
            r'<option value="([^"]*)"( selected)?[^>]*>', match.group(1)
        )
    ]


_HARNESS = r"""
var __ls={};
var localStorage={
  getItem:function(k){return Object.prototype.hasOwnProperty.call(__ls,k)?__ls[k]:null;},
  setItem:function(k,v){__ls[k]=String(v);},
  removeItem:function(k){delete __ls[k];}
};
function __mkEl(id){
  return {id:id,style:{display:'none'},textContent:'',title:'',value:'',checked:false,
    classList:{contains:function(){return false;}},
    addEventListener:function(){}};
}
function __mkSelect(id,opts){
  var el=__mkEl(id);
  el.options=[];
  el.appendChild=function(o){this.options.push(o);};
  Object.defineProperty(el,'value',{
    get:function(){return this._v;},
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
      if(id==='aa-sim-horizon'&&__HORIZON_OPTIONS.length)__els[id]=__mkSelect(id,__HORIZON_OPTIONS);
      else if(id==='aa-sim-horizon')return null;
      else __els[id]=__mkEl(id);
    }
    return __els[id];
  },
  createElement:function(){return {value:'',textContent:''};},
  querySelectorAll:function(){return [];}
};
var currentPersona=null;
var allocationPreferencesCache={};
var allocationPreferenceStoragePrefix='ares.allocprefs.';
var strategyState={dirty:false,allocation:null};
function getAllocationPreferenceKey(){return 'mandate:M1';}
function getActiveMandateId(){return 'M1';}
function arrMax(a){return Math.max.apply(null,a);}
function getRadioValue(name,fallback){return fallback;}
function hasCanonicalBandBaseline(){return false;}
function collectBandOverridesFromModal(){return null;}
function updateAllocationPreferencesEntryButton(){}
function updateBandOverrideStatus(){}
function renderAllocationPreferenceSummary(){}
function markStrategyDirty(){strategyState.dirty=true;}
function showAppError(){}
var __posts=[];
var API={post:async function(url,body){__posts.push({url:url,body:body});return {};}};
function __stored(){var raw=__ls['ares.allocprefs.mandate:M1'];return raw?JSON.parse(raw):null;}
"""


def _run(scenario_js: str, persona: dict | None = None) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    src = _html()
    parts = []
    for name in _OPTIONAL_GLOBALS:
        decl = _extract_global(src, name)
        if decl:
            parts.append(decl)
    for name in _REQUIRED_FUNCTIONS:
        body = _extract_function(src, name)
        assert body, f"Monolith-Funktion {name} nicht gefunden"
        parts.append(body)
    for name in _OPTIONAL_FUNCTIONS:
        body = _extract_function(src, name)
        if body:
            parts.append(body)
    script = (
        "var __HORIZON_OPTIONS=" + json.dumps(_horizon_select_options(src)) + ";\n"
        + _HARNESS
        + "currentPersona=" + json.dumps(persona) + ";\n"
        + "\n".join(parts)
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


def _seed_local(prefs: dict) -> str:
    return "__ls['ares.allocprefs.mandate:M1']=" + json.dumps(json.dumps(prefs)) + ";"


MAN_1951 = {"date_of_birth": "1951-03-01", "salutation": "Herr"}
WOMAN_1986 = {"date_of_birth": "1986-05-01", "salutation": "Frau"}

_LEGACY_VARIANTS = (
    {"horizonYears": "10"},
    {"horizonYears": "37"},
    {"horizonYears": "25", "horizonExplicit": True},
)


def _mandate(life_expectancy_year=None):
    return SimpleNamespace(
        life_expectancy_year=life_expectancy_year, client_birth_year=1951,
        client_sex="M", jurisdiction="CH", opened_at=None, client=None,
    )


def _engine_horizon(ui_prefs: dict, mandate) -> int:
    """Echte Backend-Kette: Schema-Validierung -> Horizont-Herleitung."""
    normalized = _normalize_preferences(ui_prefs)
    return _simulation_horizon_years(normalized["simulation"], [], mandate)


# ---------------------------------------------------------------------------
# Monolith sendet nie einen Horizont
# ---------------------------------------------------------------------------


def test_untouched_ui_does_not_send_horizon_years():
    out = _run("return collectAllocationPreferencesFromUI();", MAN_1951)
    assert "horizonYears" not in out["simulation"]
    assert "horizonExplicit" not in out["simulation"]
    # Die uebrigen Simulations-Defaults bleiben unveraendert.
    assert out["simulation"]["stressMultiplier"] == "1.0"
    assert out["simulation"]["monteCarloRuns"] == "750"


def test_default_preferences_carry_no_horizon():
    out = _run("return buildDefaultAllocationPreferences();", MAN_1951)
    assert "horizonYears" not in out["simulation"]


@pytest.mark.parametrize("legacy", _LEGACY_VARIANTS)
def test_locally_stored_legacy_horizon_is_neither_loaded_nor_sent(legacy):
    """Alt-Wert im localStorage (vor dem Entscheid gespeichert): er darf weder
    im editierbaren Store landen noch zurueckgesendet werden."""
    out = _run(
        _seed_local({"simulation": {**legacy, "stressMultiplier": "1.5"}})
        + "var loaded=loadAllocationPreferences();"
        + "applyAllocationPreferencesToUI(loaded);"
        + "return {loaded:loaded.simulation,prefs:collectAllocationPreferencesFromUI()};",
        MAN_1951,
    )
    assert "horizonYears" not in out["loaded"]
    assert "horizonExplicit" not in out["loaded"]
    assert "horizonYears" not in out["prefs"]["simulation"]
    assert "horizonExplicit" not in out["prefs"]["simulation"]


@pytest.mark.parametrize("legacy", _LEGACY_VARIANTS)
def test_server_snapshot_legacy_horizon_is_dropped_on_hydration(legacy):
    """Hydration aus dem Server-Snapshot (anderes Geraet): Alt-Horizont wird
    verworfen, die uebrigen Praeferenzen bleiben erhalten."""
    ta = {
        "id": "TA1",
        "preferences_json": json.dumps(
            {"simulation": {**legacy, "stressMultiplier": "1.5"},
             "policy": {"esg": "best_in_class"}}
        ),
    }
    out = _run(
        "var ok=hydrateAllocationPreferencesFromServer({target_allocation:"
        + json.dumps(ta) + "});"
        + "return {ok:ok,stored:__stored(),cache:allocationPreferencesCache['mandate:M1'],"
        + "prefs:collectAllocationPreferencesFromUI()};",
        MAN_1951,
    )
    assert out["ok"] is True
    for sim in (out["stored"]["simulation"], out["cache"]["simulation"], out["prefs"]["simulation"]):
        assert "horizonYears" not in sim
        assert "horizonExplicit" not in sim
    assert out["stored"]["simulation"]["stressMultiplier"] == "1.5"
    assert out["stored"]["policy"]["esg"] == "best_in_class"


def test_no_confirmation_request_is_ever_sent():
    out = _run(
        _seed_local({"simulation": {"horizonYears": "10"}})
        + "applyAllocationPreferencesToUI(loadAllocationPreferences());"
        + "if(typeof confirmSimHorizonFromBanner==='function')await confirmSimHorizonFromBanner();"
        + "collectAllocationPreferencesFromUI();"
        + "return {posts:__posts};",
        MAN_1951,
    )
    assert out["posts"] == []


def test_mandate_investment_horizon_does_not_turn_into_override():
    """Frueher schrieb applyMandateHorizonToSimulationFields() den Anlage-
    horizont (Pensionierung) als expliziten Wert -- bleibt ausgeschlossen."""
    out = _run(
        "globalThis.currentMandateHorizonRange=function(){return {years:15};};"
        "if(typeof applyMandateHorizonToSimulationFields==='function')"
        "applyMandateHorizonToSimulationFields();"
        "return collectAllocationPreferencesFromUI();",
        MAN_1951,
    )
    assert "horizonYears" not in out["simulation"]


# ---------------------------------------------------------------------------
# Ruhige Anzeige des hergeleiteten Horizonts
# ---------------------------------------------------------------------------


def test_horizon_info_shows_derived_years_read_only():
    sentence = "Prognosehorizont 9 Jahre, hergeleitet aus dem Anlagehorizont des Risikoprofils."
    out = _run(
        "if(typeof renderSimulationHorizonInfo!=='function')return {missing:true};"
        "renderSimulationHorizonInfo({projection_horizon:{years:9,sentence:"
        + json.dumps(sentence) + "}});"
        "var el=document.getElementById('aa-sim-horizon-info');"
        "var withResult={text:el.textContent,title:el.title};"
        "renderSimulationHorizonInfo(null);"
        "return {withResult:withResult,empty:el.textContent};",
    )
    assert not out.get("missing"), "renderSimulationHorizonInfo fehlt"
    assert out["withResult"]["text"] == (
        "Prognosehorizont: 9 Jahre (aus Risikoprofil, Zielen und Lebenserwartung)"
    )
    assert out["withResult"]["title"] == sentence
    assert out["empty"] == "Wird aus Risikoprofil, Zielen und Lebenserwartung hergeleitet"


def test_horizon_info_falls_back_to_simulation_horizon():
    out = _run(
        "if(typeof renderSimulationHorizonInfo!=='function')return {missing:true};"
        "renderSimulationHorizonInfo({simulation:{target_mix_series_rappen:[],horizon_years:21}});"
        "return {text:document.getElementById('aa-sim-horizon-info').textContent};",
    )
    assert not out.get("missing"), "renderSimulationHorizonInfo fehlt"
    assert out["text"].startswith("Prognosehorizont: 21 Jahre")


# ---------------------------------------------------------------------------
# Kette Monolith -> Schema -> Engine
# ---------------------------------------------------------------------------


def test_chain_untouched_ui_reaches_mandate_life_expectancy_override():
    ui_prefs = _run("return collectAllocationPreferencesFromUI();", MAN_1951)
    mandate = _mandate(life_expectancy_year=2045)
    expected = 2045 - date.today().year + 1  # inkl. Endjahr, unabhaengig gerechnet
    assert _engine_horizon(ui_prefs, mandate) == expected


def test_chain_untouched_ui_reaches_bfs_mortality_horizon():
    ui_prefs = _run("return collectAllocationPreferencesFromUI();", MAN_1951)
    mandate = _mandate()
    bfs_auto = _simulation_horizon_years({}, [], mandate)
    # Sanity: der BFS-Horizont muss den alten Select-Default ueberschreiten,
    # sonst waere der Test unabhaengig vom Verhalten gruen.
    assert bfs_auto > 10
    assert _engine_horizon(ui_prefs, mandate) == bfs_auto


def test_chain_legacy_stored_horizon_no_longer_overrides():
    """Frueher: ein gespeicherter Wert 25 ueberstimmte die Lebenserwartung."""
    ui_prefs = _run(
        _seed_local({"simulation": {"horizonYears": "25", "horizonExplicit": True}})
        + "applyAllocationPreferencesToUI(loadAllocationPreferences());"
        + "return collectAllocationPreferencesFromUI();",
        MAN_1951,
    )
    mandate = _mandate(life_expectancy_year=2045)
    assert _engine_horizon(ui_prefs, mandate) == 2045 - date.today().year + 1
    # Auch ein direkt gesendeter Alt-Key wirkt nicht mehr.
    assert _engine_horizon({"simulation": {"horizonYears": "25"}}, mandate) == (
        2045 - date.today().year + 1
    )


# ---------------------------------------------------------------------------
# HTML-Vertrag
# ---------------------------------------------------------------------------


def test_html_has_no_horizon_choice_and_no_confirmation():
    html = _html()
    assert 'id="aa-sim-horizon"' not in html
    assert "<select" not in html[html.index('id="aa-sim-horizon-info"') - 200:html.index('id="aa-sim-horizon-info"') + 200]
    for gone in (
        "al-sim-horizon-confirm-banner",
        "al-sim-horizon-confirm-select",
        "btn-sim-horizon-confirm",
        "Horizont bestätigen",
        "confirmSimHorizonFromBanner",
        "renderSimHorizonConfirmBanner",
        "sim-horizon-confirmation",
        "sim_horizon_confirmed_at",
        "horizonExplicit=true",
        "readSimulationHorizonOverride",
        "Auto (Lebenserwartung",
    ):
        assert gone not in html, gone


def test_strategy_summary_renders_horizon_info():
    html = _html()
    body = _extract_function(html, "renderStrategySummary")
    assert body and "renderSimulationHorizonInfo(allocation);" in body
