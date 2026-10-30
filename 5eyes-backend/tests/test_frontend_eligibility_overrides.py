"""ELIG-OVERRIDE-UI-001 -- request/approve a product eligibility override
where the eligibility block appears (Finalize of the recipe, #m-ums).

The UI lives as a script module next to the monolith (monolith budget,
tolerance 0; the monolith only loads it and calls two hooks). The module runs
here in Node against a minimal DOM. Dialogs only via the dialog service
(uiPrompt/uiConfirm), never native ones.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "5eyes-electron" / "frontend"
HTML_PATH = FRONTEND / "5eyes_v2.html"
MODULE_PATH = FRONTEND / "eligibility-overrides.js"
PACKAGE_JSON = REPO_ROOT / "5eyes-electron" / "package.json"

REASON = "Kunde verlangt das Produkt ausdruecklich; Risiken besprochen."

HARNESS = r"""
var calls={native:0,gets:[],posts:[],prompts:[],confirms:[]};
var window={confirm:function(){calls.native++;return true;},prompt:function(){calls.native++;return 'x';}};
function confirm(){calls.native++;return true;}
function prompt(){calls.native++;return 'x';}
function alert(){calls.native++;}
var DOM={};
function mk(id){var n={id:id,innerHTML:'',textContent:'',style:{},parentNode:null,nextSibling:null};DOM[id]=n;return n;}
var parent={insertBefore:function(node,ref){DOM[node.id]=node;}};
var status=mk('recipe-status');status.parentNode=parent;
var document={
  getElementById:function(id){return DOM[id]||null;},
  createElement:function(){return {id:'',innerHTML:'',style:{}};}
};
function escapeHtml(v){return String(v==null?'':v);}
var PROMPT_RESULTS=[];var CONFIRM_RESULT=true;
async function uiPrompt(opts){calls.prompts.push(opts);return PROMPT_RESULTS.length?PROMPT_RESULTS.shift():null;}
async function uiConfirm(opts){calls.confirms.push(opts);return CONFIRM_RESULT;}
var OVERVIEW={run_id:'r-1',current_user_id:'u-1',approver_count:2,current_user_is_sole_approver:false,items:[
  {product_id:'p-1',product_name:'Fonds Alpha',decision_hash:'dh-1',overrides:[]}]};
var API={
  get:async function(url){calls.gets.push(url);return OVERVIEW;},
  post:async function(url,body){calls.posts.push({url:url,body:body});return {};}
};
var BLOCKED={status:422,detail:'Produkteignung Fonds Alpha: Override fehlt [OVERRIDE_EVIDENCE_MISSING].',
  body:JSON.stringify({detail:'Produkteignung Fonds Alpha: Override fehlt [OVERRIDE_EVIDENCE_MISSING].'})};
function panel(){return (DOM['elig-override-panel']||{}).innerHTML||'';}
"""

BASE = "/mandates/m-1/recommendations/r-1/eligibility-overrides"


def _run(script: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    code = HARNESS + MODULE_PATH.read_text(encoding="utf-8") + "\n" + (
        "(async function(){\n" + script
        + "\nconsole.log(JSON.stringify({calls:calls,panel:panel()}));})()"
        + ".catch(function(e){console.error(e&&e.stack||e);process.exit(1);});"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(code)
        path = handle.name
    out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_blocked_finalize_shows_override_request_where_the_block_appears():
    result = _run("await eligOverrideOnFinalizeBlocked('m-1','r-1',BLOCKED);")
    assert result["calls"]["gets"] == [BASE]
    assert "Produkt-Override erforderlich" in result["panel"]
    assert "Fonds Alpha" in result["panel"] and "eligOverrideRequest(0)" in result["panel"]


def test_other_finalize_errors_do_not_open_the_override_panel():
    result = _run("await eligOverrideOnFinalizeBlocked('m-1','r-1',{detail:'Risikoprofil fehlt.',body:'{}'});")
    assert result["calls"]["gets"] == [] and result["panel"] == ""


def test_request_uses_dialog_service_with_minimum_reason_and_decision_hash():
    result = _run(
        f"PROMPT_RESULTS=[{json.dumps(REASON)}];"
        "await eligOverrideOnFinalizeBlocked('m-1','r-1',BLOCKED);await eligOverrideRequest(0);"
    )
    calls = result["calls"]
    assert calls["native"] == 0
    assert calls["prompts"][0]["minLength"] == 20 and calls["prompts"][0]["required"] is True
    assert calls["posts"] == [{"url": BASE, "body": {
        "product_id": "p-1", "reason_text": REASON, "expected_decision_hash": "dh-1"}}]
    assert calls["gets"] == [BASE, BASE]  # re-rendered after the request


def test_cancelled_request_sends_nothing():
    result = _run("await eligOverrideOnFinalizeBlocked('m-1','r-1',BLOCKED);await eligOverrideRequest(0);")
    assert result["calls"]["posts"] == []


def test_second_person_approves_after_confirmation():
    result = _run(
        "OVERVIEW.items[0].overrides=[{id:'o-1',state:'pending',requested_by:'u-2',reason_text:'Grund'}];"
        "await eligOverrideOnFinalizeBlocked('m-1','r-1',BLOCKED);"
        "calls.before=panel();await eligOverrideApprove(0,0);"
    )
    calls = result["calls"]
    assert "eligOverrideApprove(0,0)" in calls["before"]
    assert "eligOverrideAttest" not in calls["before"]
    assert calls["confirms"][0]["title"] == "Override freigeben"
    assert calls["posts"] == [{"url": BASE + "/o-1/approve", "body": {}}]
    assert calls["native"] == 0


def test_declined_approval_sends_nothing():
    result = _run(
        "OVERVIEW.items[0].overrides=[{id:'o-1',state:'pending',requested_by:'u-2'}];CONFIRM_RESULT=false;"
        "await eligOverrideOnFinalizeBlocked('m-1','r-1',BLOCKED);await eligOverrideApprove(0,0);"
    )
    assert result["calls"]["posts"] == []


def test_own_request_without_sole_approver_offers_no_self_approval():
    result = _run(
        "OVERVIEW.items[0].overrides=[{id:'o-1',state:'pending',requested_by:'u-1'}];"
        "await eligOverrideOnFinalizeBlocked('m-1','r-1',BLOCKED);"
    )
    assert "eligOverrideApprove" not in result["panel"] and "eligOverrideAttest" not in result["panel"]
    assert "Vier-Augen-Prinzip" in result["panel"]


def test_sole_approver_attests_with_confirmation_and_reason():
    result = _run(
        "OVERVIEW.current_user_is_sole_approver=true;OVERVIEW.approver_count=1;"
        "OVERVIEW.items[0].overrides=[{id:'o-1',state:'pending',requested_by:'u-1'}];"
        f"PROMPT_RESULTS=[{json.dumps(REASON)}];"
        "await eligOverrideOnFinalizeBlocked('m-1','r-1',BLOCKED);"
        "calls.before=panel();await eligOverrideAttest(0,0);"
    )
    calls = result["calls"]
    assert "eligOverrideAttest(0,0)" in calls["before"]
    assert len(calls["confirms"]) == 1 and "allein attestiert" in calls["confirms"][0]["message"]
    assert calls["prompts"][0]["minLength"] == 20
    assert calls["posts"] == [{"url": BASE + "/o-1/approve", "body": {
        "single_approver_attestation": True, "attestation_reason": REASON}}]


def test_valid_attested_override_is_shown_as_allein_attestiert():
    result = _run(
        "OVERVIEW.items[0].overrides=[{id:'o-2',state:'valid',requested_by:'u-1',approved_by:'u-1',"
        "approval_mode:'single_approver_attested',expires_at:'2026-11-26T10:00:00+00:00'},"
        "{id:'o-1',state:'approved',requested_by:'u-1'}];"
        "await eligOverrideOnFinalizeBlocked('m-1','r-1',BLOCKED);"
    )
    assert "allein attestiert" in result["panel"] and "2026-11-26" in result["panel"]
    assert "eligOverrideRequest" not in result["panel"]


def test_reset_clears_a_previous_panel():
    result = _run("await eligOverrideOnFinalizeBlocked('m-1','r-1',BLOCKED);eligOverrideReset();")
    assert result["panel"] == ""


def test_monolith_loads_module_and_calls_hooks_without_native_dialogs():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert '<script src="./eligibility-overrides.js"></script>' in html
    start = html.index("async function confirmImplementationRecipe()")
    body = html[start:html.index("function finalizeErrorText(e)", start)]
    assert "eligOverrideOnFinalizeBlocked(mid,runId,e)" in body
    start = html.index("async function openImplementationRecipe()")
    assert "eligOverrideReset()" in html[start:start + 300]
    source = MODULE_PATH.read_text(encoding="utf-8")
    stripped = source.replace("uiConfirm(", "").replace("uiPrompt(", "")
    assert "window.confirm" not in source and "window.prompt" not in source
    assert "confirm(" not in stripped and "prompt(" not in stripped and "alert(" not in stripped
    assert "frontend/eligibility-overrides.js" in json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["build"]["files"]
