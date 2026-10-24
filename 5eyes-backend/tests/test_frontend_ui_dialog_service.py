"""Dialog-Service des Monolithen (Ersatz fuer die in Electron nicht
unterstuetzten nativen Dialoge) und seine zwei Eingabe-Aufrufer:

* Storno einer Weiterleitung an das Asset Management
  (``cancelPortfolioHandoffPrompt``): Begruendung ist Pflicht.
* Notiz zur Risikoprofil-Signatur (``signRiskProfile``): optional.

Die echten Monolith-Funktionen laufen in Node gegen ein minimales DOM:
Der Dialog oeffnet sich (``om('m-ui-dialog')``), mit Eingabe wird der
API-Aufruf mit der Notiz gesendet, bei Abbruch (Knopf, ESC) wird nichts
gesendet. Dazu die Grundvertraege von uiConfirm/uiPrompt/uiAlert.
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
HTML_PATH = REPO_ROOT / "5eyes-electron" / "frontend" / "5eyes_v2.html"

FUNCTIONS = (
    "function uiDialogNormalizeOpts(",
    "function uiDialogValidate(",
    "function uiDialogEnsure(",
    "function uiDialogSetVisible(",
    "function uiDialogShow(",
    "function uiDialogClose(",
    "function uiDialogOpen(",
    "function uiDialogSubmit(",
    "function uiDialogCancel(",
    "function uiDialogKeydown(",
    "function uiConfirm(",
    "function uiPrompt(",
    "function uiAlert(",
    "async function cancelPortfolioHandoffPrompt(",
    "function riskSignoffState(",
    "async function signRiskProfile(",
)


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
var calls={native:0,posts:[],om:[],cm:[],errors:[],success:[],notices:[],reloads:0,focus:[]};
var window={prompt:function(){calls.native++;return 'NATIV';},confirm:function(){calls.native++;return true;},alert:function(){calls.native++;}};
function prompt(){calls.native++;return 'NATIV';}
function confirm(){calls.native++;return true;}
function alert(){calls.native++;}
var DOM={};
function el(id){
  if(!DOM[id])DOM[id]={id:id,value:'',textContent:'',disabled:false,style:{display:''},attrs:{},
    setAttribute:function(k,v){this.attrs[k]=String(v);},
    removeAttribute:function(k){delete this.attrs[k];},
    focus:function(){calls.focus.push(this.id);},
    select:function(){}};
  return DOM[id];
}
var document={getElementById:function(id){return el(id);},activeElement:null,body:{appendChild:function(){}},createElement:function(){throw new Error('nicht erwartet');}};
function om(id){calls.om.push(id);}
function cm(id){calls.cm.push(id);}
function showAppNotice(o){calls.notices.push(o);return NOTICE_OK?{dismiss:function(){}}:null;}
function showAppError(m){calls.errors.push(m);}
function showAppSuccess(m){calls.success.push(m);}
function parseApiError(e,f){return String((e&&e.detail)||(e&&e.message)||f||'?');}
function getActiveMandateId(){return 'm-1';}
function isDemoMandateId(){return false;}
function reviewRiskProfileForCard(){return {version:3,override_decision_id:null,signoff_id:null};}
function renderReviewRiskProfileCard(){}
var strategyState={currentRisk:{},risk:{}};
var _tlHandoffCtx={mandateId:'m-1',runId:'r-1'};
async function loadPortfolioHandoffHistory(){calls.reloads++;}
var API={post:async function(url,body){calls.posts.push({url:url,body:body});return {signoff_id:'s-1',signoff_status:'signed'};}};
function tick(){return new Promise(function(r){setTimeout(r,0);});}
"""


def _run(script: str, notice_ok: bool = True) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")
    src = HTML_PATH.read_text(encoding="utf-8")
    code = "var NOTICE_OK=" + json.dumps(notice_ok) + ";" + HARNESS
    code += _var(src, "uiDialogState") + "\n"
    code += "\n".join(_function(src, sig) for sig in FUNCTIONS) + "\n"
    code += (
        "(async function(){\nvar R={};\n" + script
        + "\nconsole.log(JSON.stringify({calls:calls,DOM:DOM,R:R}));})()"
        + ".catch(function(e){console.error(e&&e.stack||e);process.exit(1);});"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(code)
        path = handle.name
    out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# --------------------------------------------------------------- Storno

def test_cancel_handoff_opens_dialog_and_posts_reason():
    result = _run(
        "var p=cancelPortfolioHandoffPrompt('h-9');await tick();"
        "R.openBeforeInput=calls.om.slice();R.postsBefore=calls.posts.length;"
        "R.msg=DOM['m-ui-dialog-msg'].textContent;R.wrap=DOM['m-ui-dialog-input-wrap'].style.display;"
        "R.required=DOM['m-ui-dialog-input'].attrs['aria-required'];"
        "DOM['m-ui-dialog-input'].value='  Kunde hat Auftrag zurueckgezogen ';"
        "uiDialogKeydown({key:'Enter',target:DOM['m-ui-dialog-input']});await p;"
    )
    calls, r = result["calls"], result["R"]
    assert calls["native"] == 0
    assert r["openBeforeInput"] == ["m-ui-dialog"]
    assert r["postsBefore"] == 0
    assert r["msg"] == "Grund für die Stornierung:"
    assert r["wrap"] == ""
    assert r["required"] == "true"
    assert calls["posts"] == [{
        "url": "/mandates/m-1/portfolio-handoffs/h-9/cancel",
        "body": {"cancelled_reason": "Kunde hat Auftrag zurueckgezogen"},
    }]
    assert calls["cm"] == ["m-ui-dialog"]
    assert calls["reloads"] == 1
    assert calls["success"] == ["Weiterleitung storniert"]


@pytest.mark.parametrize("abort", [
    "uiDialogCancel();",
    "uiDialogKeydown({key:'Escape',target:DOM['m-ui-dialog-input']});",
])
def test_cancel_handoff_abort_sends_nothing(abort):
    result = _run(
        "var p=cancelPortfolioHandoffPrompt('h-9');await tick();"
        "DOM['m-ui-dialog-input'].value='angefangen';" + abort + "await p;"
    )
    calls = result["calls"]
    assert calls["om"] == ["m-ui-dialog"]
    assert calls["cm"] == ["m-ui-dialog"]
    assert calls["posts"] == []
    assert calls["reloads"] == 0
    assert calls["native"] == 0


def test_cancel_handoff_empty_reason_blocks_submit_without_sending():
    result = _run(
        "var p=cancelPortfolioHandoffPrompt('h-9');await tick();"
        "DOM['m-ui-dialog-input'].value='   ';uiDialogSubmit();await tick();"
        "R.stillOpen=uiDialogState.active!==null;R.err=DOM['m-ui-dialog-error'].textContent;"
        "R.errShown=DOM['m-ui-dialog-error'].style.display;"
        "R.invalid=DOM['m-ui-dialog-input'].attrs['aria-invalid'];"
        "uiDialogCancel();await p;"
    )
    r, calls = result["R"], result["calls"]
    assert r["stillOpen"] is True
    assert r["err"] == "Bitte ausfuellen."
    assert r["errShown"] == ""
    assert r["invalid"] == "true"
    assert calls["posts"] == []


# ------------------------------------------------------ Signatur-Notiz

def test_sign_risk_profile_opens_dialog_and_posts_note():
    result = _run(
        "var p=signRiskProfile();await tick();"
        "R.open=calls.om.slice();R.postsBefore=calls.posts.length;"
        "R.msg=DOM['m-ui-dialog-msg'].textContent;"
        "DOM['m-ui-dialog-input'].value='Im Gespraech vom 20.10. besprochen';"
        "uiDialogSubmit();await p;"
    )
    calls, r = result["calls"], result["R"]
    assert calls["native"] == 0
    assert r["open"] == ["m-ui-dialog"]
    assert r["postsBefore"] == 0
    assert r["msg"] == "Notiz zur Signatur (optional):"
    assert len(calls["posts"]) == 1
    post = calls["posts"][0]
    assert post["url"] == "/mandates/m-1/risk-profile/sign"
    assert post["body"]["note"] == "Im Gespraech vom 20.10. besprochen"
    assert post["body"]["expected_assessment_version"] == 3
    assert calls["success"] == ["Risikoprofil signiert."]


def test_sign_risk_profile_note_stays_optional():
    result = _run("var p=signRiskProfile();await tick();uiDialogSubmit();await p;")
    calls = result["calls"]
    assert len(calls["posts"]) == 1
    assert calls["posts"][0]["body"]["note"] == ""


@pytest.mark.parametrize("abort", [
    "uiDialogCancel();",
    "uiDialogKeydown({key:'Escape',target:DOM['m-ui-dialog-input']});",
])
def test_sign_risk_profile_abort_sends_nothing(abort):
    result = _run(
        "var p=signRiskProfile();await tick();"
        "DOM['m-ui-dialog-input'].value='Notiz';" + abort + "await p;"
    )
    calls = result["calls"]
    assert calls["om"] == ["m-ui-dialog"]
    assert calls["posts"] == []
    assert calls["success"] == []
    assert calls["native"] == 0


# --------------------------------------------------- Service-Vertraege

def test_confirm_resolves_true_on_ok_and_false_on_cancel():
    result = _run(
        "var a=uiConfirm('Baustein wirklich loeschen?');await tick();"
        "R.msg=DOM['m-ui-dialog-msg'].textContent;R.role=DOM['m-ui-dialog-box'].attrs.role;"
        "R.inputShown=DOM['m-ui-dialog-input-wrap'].style.display;"
        "uiDialogKeydown({key:'Enter',target:DOM['m-ui-dialog-ok']});R.a=await a;"
        "var b=uiConfirm({title:'T',message:'M'});await tick();R.title=DOM['m-ui-dialog-title'].textContent;"
        "uiDialogKeydown({key:'Escape',target:DOM['m-ui-dialog-ok']});R.b=await b;"
        "var c=uiConfirm('x');await tick();uiDialogKeydown({key:'Enter',target:DOM['m-ui-dialog-cancel']});"
        "R.cStillOpen=uiDialogState.active!==null;uiDialogCancel();R.c=await c;"
    )
    r = result["R"]
    assert r["msg"] == "Baustein wirklich loeschen?"
    assert r["role"] == "alertdialog"
    assert r["inputShown"] == "none"
    assert r["a"] is True
    assert r["title"] == "T"
    assert r["b"] is False
    # Enter auf "Abbrechen" bestaetigt nicht (der Knopf-Klick bricht ab).
    assert r["cStillOpen"] is True
    assert r["c"] is False


def test_dialogs_are_queued_one_at_a_time():
    result = _run(
        "var a=uiConfirm('erst');var b=uiPrompt({message:'dann',defaultValue:'v'});await tick();"
        "R.first=DOM['m-ui-dialog-msg'].textContent;uiDialogSubmit();R.a=await a;await tick();"
        "R.second=DOM['m-ui-dialog-msg'].textContent;R.value=DOM['m-ui-dialog-input'].value;"
        "uiDialogSubmit();R.b=await b;"
    )
    r = result["R"]
    assert (r["first"], r["a"], r["second"], r["value"], r["b"]) == ("erst", True, "dann", "v", "v")


def test_prompt_min_length_is_enforced():
    result = _run(
        "var p=uiPrompt({message:'Begruendung',minLength:5});await tick();"
        "DOM['m-ui-dialog-input'].value='abc';uiDialogSubmit();"
        "R.err=DOM['m-ui-dialog-error'].textContent;R.open=uiDialogState.active!==null;"
        "DOM['m-ui-dialog-input'].value='abcdef';uiDialogSubmit();R.v=await p;"
    )
    r = result["R"]
    assert r["open"] is True
    assert r["err"] == "Bitte mindestens 5 Zeichen eingeben."
    assert r["v"] == "abcdef"


def test_tab_focus_stays_inside_dialog():
    result = _run(
        "var p=uiPrompt('x');await tick();calls.focus=[];"
        "uiDialogKeydown({key:'Tab',target:DOM['m-ui-dialog-ok'],preventDefault:function(){}});"
        "uiDialogKeydown({key:'Tab',shiftKey:true,target:DOM['m-ui-dialog-x'],preventDefault:function(){}});"
        "uiDialogCancel();await p;"
    )
    assert result["calls"]["focus"] == ["m-ui-dialog-x", "m-ui-dialog-ok"]


def test_alert_uses_toast_by_severity_and_modal_on_request():
    result = _run(
        "await uiAlert({level:'error',message:'Bitte zuerst ein Mandat oeffnen.'});"
        "R.omAfterToast=calls.om.slice();"
        "var m=uiAlert({level:'warn',modal:true,message:'Hinweis'});await tick();"
        "R.cancelHidden=DOM['m-ui-dialog-cancel'].style.display;uiDialogSubmit();await m;"
    )
    calls, r = result["calls"], result["R"]
    assert calls["notices"] == [{"level": "error", "message": "Bitte zuerst ein Mandat oeffnen."}]
    assert r["omAfterToast"] == []
    assert calls["om"] == ["m-ui-dialog"]
    assert r["cancelHidden"] == "none"


def test_alert_falls_back_to_modal_without_toast_area():
    result = _run(
        "var m=uiAlert('Export fehlgeschlagen');await tick();uiDialogSubmit();await m;",
        notice_ok=False,
    )
    assert result["calls"]["om"] == ["m-ui-dialog"]
    assert result["DOM"]["m-ui-dialog-msg"]["textContent"] == "Export fehlgeschlagen"
