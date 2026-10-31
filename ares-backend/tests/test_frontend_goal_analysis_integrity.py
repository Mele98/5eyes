"""GOAL-ANALYSIS-INTEGRITY-001 / SHADOW-ANALYSIS-INTEGRITY-001 -- ruhiger UI-Hinweis.

Verletzt die gespeicherte Zielanalyse oder der Shadow-Container der aktuellen
Strategie den Integritaetsnachweis, blenden die Kanaele die Analyse aus (#793).
Der Berater sah bisher nur, dass etwas fehlt, nicht warum. Das Skriptmodul
``goal-analysis-integrity.js`` (neben dem Monolithen, Budget Toleranz 0) holt
den Status vom Server und zeigt einen ruhigen Hinweis ueber der
SOLL/IST-Tabelle. Das Modul laeuft hier in Node gegen ein minimales DOM.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "ares-desktop" / "frontend"
HTML_PATH = FRONTEND / "ares.html"
MODULE_PATH = FRONTEND / "goal-analysis-integrity.js"
PACKAGE_JSON = REPO_ROOT / "ares-desktop" / "package.json"

HARNESS = r"""
var calls={gets:[]};
var DOM={};
function mk(id){return {id:id,innerHTML:'',style:{},dataset:{},attrs:{},
  setAttribute:function(k,v){this.attrs[k]=v;},parentNode:null};}
var anchor=mk('aa-goal-sollist');
anchor.parentNode={insertBefore:function(node,ref){DOM[node.id]=node;}};
DOM['aa-goal-sollist']=anchor;
var document={getElementById:function(id){return DOM[id]||null;},createElement:function(){return mk('');}};
function escapeHtml(v){return String(v==null?'':v).replace(/</g,'&lt;');}
var ACTIVE='m-1';
function getActiveMandateId(){return ACTIVE;}
function isDemoMandateId(id){return String(id).indexOf('demo')===0;}
var RESPONSE={target_allocation_id:'ta-1',goal_analysis:'verified',shadow_analysis:'integrity_mismatch',
  needs_attention:true,label:'Zielanalyse nicht verifizierbar',text:'Bitte die Strategie neu berechnen.'};
var FAIL=false;
var API={get:async function(url){calls.gets.push(url);if(FAIL){throw new Error('API 500');}
  if(SWITCH_DURING){ACTIVE='m-2';}return RESPONSE;}};
var SWITCH_DURING=false;
"""


def _run(script: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    code = HARNESS + MODULE_PATH.read_text(encoding="utf-8") + "\n" + (
        "(async function(){\n" + script
        + "\nvar box=DOM['aa-goal-integrity']||null;"
        + "console.log(JSON.stringify({calls:calls,box:box&&{display:box.style.display,html:box.innerHTML,"
        + "integrity:box.dataset.integrity,role:box.attrs.role}}));})()"
        + ".catch(function(e){console.error(e&&e.stack||e);process.exit(1);});"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(code)
        path = handle.name
    out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_mismatch_shows_quiet_hint_above_goal_table():
    result = _run("await refreshGoalAnalysisIntegrity('m-1');")
    assert result["calls"]["gets"] == [
        "/mandates/m-1/target-allocation/current/analysis-integrity"
    ]
    box = result["box"]
    assert box["display"] == "block"
    assert box["role"] == "status"
    assert "Zielanalyse nicht verifizierbar" in box["html"]
    assert "neu berechnen" in box["html"]
    assert box["integrity"] == "verified|integrity_mismatch"


def test_verified_state_keeps_hint_hidden():
    result = _run(
        "RESPONSE={goal_analysis:'verified',shadow_analysis:'legacy_unbound',needs_attention:false};"
        "await refreshGoalAnalysisIntegrity('m-1');"
    )
    assert result["box"]["display"] == "none"
    assert result["box"]["html"] == ""


def test_demo_mandate_makes_no_request_and_api_error_hides_hint():
    demo = _run("await refreshGoalAnalysisIntegrity('demo-1');")
    assert demo["calls"]["gets"] == []
    assert demo["box"]["display"] == "none"
    failed = _run("await refreshGoalAnalysisIntegrity('m-1');FAIL=true;"
                  "await refreshGoalAnalysisIntegrity('m-1');")
    assert failed["box"]["display"] == "none"


def test_stale_answer_for_previous_mandate_is_ignored():
    result = _run("SWITCH_DURING=true;await refreshGoalAnalysisIntegrity('m-1');")
    assert result["box"] is None or result["box"]["display"] in ("", "none")


def test_monolith_loads_module_and_refreshes_on_every_allocation_load():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert '<script src="./goal-analysis-integrity.js"></script>' in html
    load = html[html.index("async function loadCurrentAllocationResult(mid){"):]
    load = load[: load.index("\n}\n")]
    # Vor dem Payload-Abruf: der Hinweis erscheint auch, wenn das Payload
    # wegen derselben Integritaetsverletzung scheitert.
    assert load.index("refreshGoalAnalysisIntegrity(mid)") < load.index("current/payload")
    # Kein natives alert/confirm/prompt im Modul (Electron).
    module = MODULE_PATH.read_text(encoding="utf-8")
    assert not re.search(r"\b(alert|confirm|prompt)\(", module)


def test_goal_table_renderer_moved_not_duplicated_and_packaged():
    html = HTML_PATH.read_text(encoding="utf-8")
    module = MODULE_PATH.read_text(encoding="utf-8")
    assert "function renderGoalAchievementSollIst(" not in html
    assert module.count("function renderGoalAchievementSollIst(") == 1
    assert "renderGoalAchievementSollIst(result)" in html
    files = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["build"]["files"]
    assert "frontend/goal-analysis-integrity.js" in files
