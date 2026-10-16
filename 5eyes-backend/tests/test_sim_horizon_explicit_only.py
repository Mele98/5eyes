"""SIM-HORIZON-ALWAYS-EXPLICIT-001 -- Sim-Horizont nur bei expliziter Wahl senden.

Befund
------
`collectAllocationPreferencesFromUI()` (5eyes_v2.html) schickte IMMER
`simulation.horizonYears` -- aus dem Select `#aa-sim-horizon`, dessen Default
'10 Jahre' war. Das Backend (`_simulation_horizon_years`) behandelt jeden
vorhandenen Wert als expliziten Berater-Override. Dadurch wurden
`mandate.life_expectancy_year` und der BFS-Sterbetafel-Horizont aus dem
Monolithen NIE erreicht: Mann Jg. 1951, Select unberuehrt -> Engine 10 Jahre,
obwohl Mandats-Override 2045 (=20 J.) bzw. BFS-Auto (~13 J.) gelten sollten.
Nebenbefund (P2): ein gespeicherter Wert ausserhalb der Optionsliste (z.B.
'37') liess den Select nach dem Reload leer erscheinen.

Diese Datei fuehrt die ECHTEN Monolith-Funktionen in Node aus (nur das DOM
ist gefaked, inkl. Browser-Semantik "Wert nicht in Optionsliste -> ''") und
reicht deren Ausgabe durch die echte Backend-Kette
(`_normalize_preferences` -> `_simulation_horizon_years`).
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

HTML_PATH = BACKEND_DIR.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"

# Pflicht-Funktionen (existieren vor UND nach dem Fix) ...
_REQUIRED_FUNCTIONS = (
    "cloneJSON",
    "buildDefaultAllocationPreferences",
    "mergeAllocationPreferences",
    "getInputValue",
    "getCheckboxValue",
    "setSelectValue",
    "setCheckboxValue",
    "setRadioValue",
    "_lifeExpectancyEndYear",
    "_lifeExpectancyHorizonYears",
    "collectAllocationPreferencesFromUI",
    "applyAllocationPreferencesToUI",
)
# ... und optionale (Fix-Helfer bzw. die entfernte Mandats-Sync-Funktion).
# Fehlen sie, wird der Test NICHT an der Extraktion rot, sondern am Verhalten.
_OPTIONAL_FUNCTIONS = (
    "readSimulationHorizonOverride",
    "setSimulationHorizonSelectValue",
    "applyMandateHorizonToSimulationFields",
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _extract_function(src: str, name: str) -> str | None:
    match = re.search(r"\nfunction " + re.escape(name) + r"\(", src)
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


_FAKE_DOM = r"""
var __els={};
function __mkSelect(opts){
  var el={options:[],_v:'',classList:{contains:function(){return false;}},
    appendChild:function(o){this.options.push(o);}};
  Object.defineProperty(el,'value',{
    get:function(){return this._v;},
    // Browser-Semantik: Wert ausserhalb der Optionsliste -> selectedIndex -1, value ''.
    set:function(v){var s=String(v);this._v=this.options.some(function(o){return String(o.value)===s;})?s:'';}
  });
  opts.forEach(function(o){el.options.push({value:o.value,textContent:o.value});});
  var sel=opts.filter(function(o){return o.selected;})[0]||opts[0];
  el._v=sel?sel.value:'';
  return el;
}
var document={
  getElementById:function(id){
    if(!__els[id])__els[id]=(id==='aa-sim-horizon')?__mkSelect(__HORIZON_OPTIONS):
      {value:'',checked:false,classList:{contains:function(){return false;}}};
    return __els[id];
  },
  createElement:function(){return {value:'',textContent:''};},
  querySelectorAll:function(){return [];}
};
var localStorage={getItem:function(){return null;},setItem:function(){}};
function arrMax(a){return Math.max.apply(null,a);}
function getRadioValue(name,fallback){return fallback;}
function hasCanonicalBandBaseline(){return false;}
function collectBandOverridesFromModal(){return null;}
function renderAllocationPreferenceSummary(){}
var __stored={};
function loadAllocationPreferences(){return mergeAllocationPreferences(buildDefaultAllocationPreferences(),__stored);}
"""


def _run(scenario_js: str, persona: dict) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    src = _html()
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
        + _FAKE_DOM
        + "var currentPersona=" + json.dumps(persona) + ";\n"
        + "\n".join(fns)
        + "\nvar __out=(function(){" + scenario_js + "})();\n"
        + "console.log(JSON.stringify(__out));\n"
    )
    res = subprocess.run(
        ["node", "-"], input=script, capture_output=True, text=True,
        timeout=30, check=False, encoding="utf-8",
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


MAN_1951 = {"date_of_birth": "1951-03-01", "salutation": "Herr"}
WOMAN_1986 = {"date_of_birth": "1986-05-01", "salutation": "Frau"}


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
# Frontend-Verhalten
# ---------------------------------------------------------------------------


def test_untouched_select_does_not_send_horizon_years():
    out = _run("return collectAllocationPreferencesFromUI();", MAN_1951)
    assert "horizonYears" not in out["simulation"], (
        "unberuehrter Select darf keinen expliziten Override senden: "
        f"{out['simulation']}"
    )
    # Die uebrigen Simulations-Defaults bleiben unveraendert.
    assert out["simulation"]["stressMultiplier"] == "1.0"
    assert out["simulation"]["monteCarloRuns"] == "750"


def test_default_preferences_carry_no_horizon_override():
    out = _run("return buildDefaultAllocationPreferences();", MAN_1951)
    assert out["simulation"].get("horizonYears") in (None, "")


def test_explicit_choice_is_sent():
    out = _run(
        "document.getElementById('aa-sim-horizon').value='25';"
        "return collectAllocationPreferencesFromUI();",
        MAN_1951,
    )
    assert out["simulation"]["horizonYears"] == "25"


def test_explicit_choice_keeps_life_expectancy_floor():
    """Kompatibilitaet: ein expliziter Wert wird wie bisher nie kuerzer als
    die (flache) Lebenserwartung gesendet -- Frau Jg. 1986 -> 1986+85."""
    out = _run(
        "document.getElementById('aa-sim-horizon').value='10';"
        "return collectAllocationPreferencesFromUI();",
        WOMAN_1986,
    )
    expected = 1986 + 85 - date.today().year + 1
    assert out["simulation"]["horizonYears"] == str(expected)


def test_stored_value_outside_option_list_is_rendered_and_round_trips():
    out = _run(
        "__stored={simulation:{horizonYears:'37'}};"
        "applyAllocationPreferencesToUI(loadAllocationPreferences());"
        "return {select:document.getElementById('aa-sim-horizon').value,"
        "prefs:collectAllocationPreferencesFromUI()};",
        MAN_1951,
    )
    assert out["select"] == "37", "gespeicherter Wert '37' darf den Select nicht leeren"
    assert out["prefs"]["simulation"]["horizonYears"] == "37"


def test_stored_explicit_choice_in_option_list_is_preserved():
    out = _run(
        "__stored={simulation:{horizonYears:'20'}};"
        "applyAllocationPreferencesToUI(loadAllocationPreferences());"
        "return {select:document.getElementById('aa-sim-horizon').value,"
        "prefs:collectAllocationPreferencesFromUI()};",
        MAN_1951,
    )
    assert out["select"] == "20"
    assert out["prefs"]["simulation"]["horizonYears"] == "20"


def test_client_without_stored_choice_resets_select_to_auto():
    """Mandantenwechsel: ein Kunde ohne gespeicherten Horizont darf nicht den
    expliziten Wert des vorherigen Kunden im Select erben."""
    out = _run(
        "document.getElementById('aa-sim-horizon').value='25';"
        "__stored={};"
        "applyAllocationPreferencesToUI(loadAllocationPreferences());"
        "return {select:document.getElementById('aa-sim-horizon').value,"
        "prefs:collectAllocationPreferencesFromUI()};",
        MAN_1951,
    )
    assert out["select"] == ""
    assert "horizonYears" not in out["prefs"]["simulation"]


def test_mandate_investment_horizon_does_not_turn_auto_into_override():
    """Frueher schrieb applyMandateHorizonToSimulationFields() beim Oeffnen
    des Parameter-Modals den Anlagehorizont (Pensionierung) als expliziten
    Wert in den Select -- derselbe Defekt ueber einen zweiten Pfad."""
    out = _run(
        "globalThis.currentMandateHorizonRange=function(){return {years:15};};"
        "if(typeof applyMandateHorizonToSimulationFields==='function')"
        "applyMandateHorizonToSimulationFields();"
        "return collectAllocationPreferencesFromUI();",
        MAN_1951,
    )
    assert "horizonYears" not in out["simulation"]


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
    # sonst waere der Test unabhaengig vom Fix gruen.
    assert bfs_auto > 10
    assert _engine_horizon(ui_prefs, mandate) == bfs_auto


def test_chain_explicit_choice_still_overrides():
    ui_prefs = _run(
        "document.getElementById('aa-sim-horizon').value='25';"
        "return collectAllocationPreferencesFromUI();",
        MAN_1951,
    )
    assert _engine_horizon(ui_prefs, _mandate(life_expectancy_year=2045)) == 25


def test_schema_accepts_absent_horizon_key():
    normalized = _normalize_preferences({"simulation": {"stressMultiplier": "1.0"}})
    assert "horizonYears" not in normalized["simulation"]


def test_html_has_explicit_auto_option_as_default():
    options = _horizon_select_options(_html())
    assert options[0]["value"] == ""
    assert options[0]["selected"] is True
    assert sum(1 for o in options if o["selected"]) == 1
