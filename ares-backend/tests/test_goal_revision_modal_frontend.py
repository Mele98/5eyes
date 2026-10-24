"""GOAL-REVISION-DECISION-001 (CIO-Abnahme #665): die Aktion "Als
nachrangiges Wunschziel einstufen..." oeffnet ein echtes Modal (``m-goalrev``,
``om``/``cm`` wie ``m-overr``) -- ``window.prompt`` ist in Electron nicht
implementiert und darf nicht verwendet werden.

Die echten Monolith-Funktionen laufen in Node gegen ein minimales DOM:
Modal oeffnet ohne prompt, die Begruendungspruefung sperrt den Button und
zeigt die Meldung am Feld, der POST-Body ist ``{reason}``, Fehler erscheinen
als ``message [reason_code]``, Erfolg markiert die Strategie als veraltet.
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
HTML_PATH = REPO_ROOT / "ares-desktop" / "frontend" / "ares.html"

FUNCTIONS = (
    "function goalRevisionCellHtml(",
    "function goalRevisionReasonIssue(",
    "function goalRevisionErrorText(",
    "function openGoalRevisionDialog(",
    "function updGoalRevisionBtn(",
    "async function submitGoalRevision(",
)
VARS = (
    "goalRevisionEvidenceByGoal",
    "goalRevisionDialogState",
    "GOAL_REVISION_REASON_MIN_LENGTH",
    "GOAL_REVISION_GENERIC_PHRASES",
)
GOOD_REASON = "Mit dem Kunden besprochen: Familienvermoegen 2035 ist ein Wunsch, kein Muss."


def _function(src: str, signature: str) -> str:
    start = src.index(signature)
    i = src.index("{", start + len(signature) - 1)
    depth, j = 1, i + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
    return src[start:j]


def _var(src: str, name: str) -> str:
    match = re.search(r"^var " + re.escape(name) + r"=.*?;$", src, re.M)
    assert match, name
    return match.group(0)


HARNESS = r"""
var calls={prompt:0,posts:[],om:[],cm:[],dirty:[],errors:[],success:[]};
var window={prompt:function(){calls.prompt++;return null;}};
function prompt(){calls.prompt++;return null;}
function el(id){
  if(!DOM[id])DOM[id]={id:id,value:'',textContent:'',disabled:false,style:{display:''}};
  return DOM[id];
}
var DOM={};
var document={getElementById:function(id){return el(id);}};
function om(id){calls.om.push(id);}
function cm(id){calls.cm.push(id);}
function escapeHtml(s){return String(s);}
function fmtProbPct(v){return (Math.round(v*10)/10)+'%';}
function getActiveMandateId(){return 'm-1';}
function isDemoMandateId(){return false;}
function goalById(id){return {id:id,label:'Familienvermoegen 2035'};}
function parseApiError(e,f){return String((e&&e.detail)||(e&&e.message)||f||'?');}
function showAppError(m){calls.errors.push(m);}
function showAppSuccess(m){calls.success.push(m);}
function markStrategyDirty(m){calls.dirty.push(m);}
var API={post:async function(url,body){calls.posts.push({url:url,body:body});if(MODE==='fail'){var e=new Error('x');e.detail='Das Ziel ist bereits als nachrangiges Wunschziel eingestuft. [already_active]';throw e;}if(MODE==='obj'){var e2=new Error('y');e2.detail={message:'Begruendung zu kurz',reason_code:'reason_too_short'};throw e2;}return {decision_id:'d1'};}};
"""


def _run(script: str, mode: str = "ok") -> dict:
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")
    src = HTML_PATH.read_text(encoding="utf-8")
    code = "var MODE=" + json.dumps(mode) + ";" + HARNESS
    code += "\n".join(_var(src, name) for name in VARS) + "\n"
    code += "\n".join(_function(src, sig) for sig in FUNCTIONS) + "\n"
    code += "(async function(){\n" + script + "\nconsole.log(JSON.stringify({calls:calls,DOM:DOM}));})();"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(code)
        path = handle.name
    out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


EVIDENCE = json.dumps({
    "goal_id": "g-far",
    "goal_revision": {
        "revision_suggested": True, "best_probability": 0.151, "tau": 0.8,
        "engine_version": "saa_resampled_v11",
    },
})


def test_modal_opens_without_prompt_and_shows_goal_and_evidence():
    result = _run(
        "goalRevisionCellHtml(" + EVIDENCE + ");"
        "openGoalRevisionDialog('g-far');"
    )
    calls, dom = result["calls"], result["DOM"]
    assert calls["prompt"] == 0
    assert calls["om"] == ["m-goalrev"]
    assert dom["grv-goal"]["textContent"] == "Familienvermoegen 2035"
    assert "15.1%" in dom["grv-evidence"]["textContent"]
    assert "saa_resampled_v11" in dom["grv-evidence"]["textContent"]
    assert dom["grv-submit"]["disabled"] is True  # leere Begruendung sperrt


@pytest.mark.parametrize("reason,fragment", [
    ("zu kurz", "Mindestens 20 Zeichen"),
    ("kundenwunsch kundenwunsch kundenwunsch", "Floskel"),
    ("1111111111 2222222222 33333", "aussagekr"),
])
def test_validation_blocks_button_and_shows_message_at_field(reason, fragment):
    result = _run(
        "goalRevisionCellHtml(" + EVIDENCE + ");openGoalRevisionDialog('g-far');"
        "el('grv-reason').value=" + json.dumps(reason) + ";updGoalRevisionBtn(true);"
        "await submitGoalRevision();"
    )
    dom, calls = result["DOM"], result["calls"]
    assert dom["grv-submit"]["disabled"] is True
    assert fragment in dom["grv-error"]["textContent"]
    assert dom["grv-error"]["style"]["display"] == "block"
    assert calls["posts"] == []


def test_valid_reason_posts_exact_body_and_marks_strategy_dirty():
    result = _run(
        "goalRevisionCellHtml(" + EVIDENCE + ");openGoalRevisionDialog('g-far');"
        "el('grv-reason').value=" + json.dumps("  " + GOOD_REASON + "  ") + ";"
        "updGoalRevisionBtn(true);var enabled=!el('grv-submit').disabled;"
        "await submitGoalRevision();calls.enabled=enabled;"
    )
    calls = result["calls"]
    assert calls["enabled"] is True
    assert calls["posts"] == [{
        "url": "/mandates/m-1/goals/g-far/revision-decisions",
        "body": {"reason": GOOD_REASON},
    }]
    assert calls["cm"] == ["m-goalrev"]
    assert calls["dirty"] and "Strategie neu berechnen" in calls["dirty"][0]
    assert calls["prompt"] == 0


@pytest.mark.parametrize("mode,expected", [
    ("fail", "Das Ziel ist bereits als nachrangiges Wunschziel eingestuft. [already_active]"),
    ("obj", "Begruendung zu kurz [reason_too_short]"),
])
def test_api_errors_appear_as_message_with_reason_code(mode, expected):
    result = _run(
        "goalRevisionCellHtml(" + EVIDENCE + ");openGoalRevisionDialog('g-far');"
        "el('grv-reason').value=" + json.dumps(GOOD_REASON) + ";updGoalRevisionBtn(true);"
        "await submitGoalRevision();",
        mode=mode,
    )
    calls, dom = result["calls"], result["DOM"]
    assert dom["grv-error"]["textContent"] == expected
    assert calls["errors"] == [expected]
    assert calls["cm"] == [] and calls["dirty"] == []
    assert dom["grv-submit"]["disabled"] is False  # erneut versuchbar


def test_modal_markup_and_no_native_dialogs_in_goal_revision_code():
    src = HTML_PATH.read_text(encoding="utf-8")
    assert 'id="m-goalrev"' in src and 'id="grv-reason"' in src and 'id="grv-submit"' in src
    code = "\n".join(_function(src, sig) for sig in FUNCTIONS)
    for native in ("prompt(", "confirm(", "alert("):
        assert native not in code
