"""H5 Risikoprofil (Dok. 105): Maskenteil ``risk-questionnaire-v2.js``.

Das Modul ist ein ausgelagerter Monolith-Teil (EXTRACTED_MONOLITH_PARTS,
eigenes Budget) und laeuft hier in Node gegen einen minimalen DOM-Ersatz.
Geprueft wird die Paritaet zum Server (Texte, Kappungen, Flags) und das
Verhalten der Maskenergaenzungen. Fragen 1-11 im Monolithen bleiben
unveraendert (test_risk_questionnaire_frontend_parity).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

import services.risk_questionnaire_integrity as rqi
from services.pdf.components.eignungspruefung import Q10_BAND_FOOTNOTE
from services.risk_scoring import compute_willingness_v2
from tests.monolith_risk_js import DOM, monolith_js
from tests.monolith_source import EXTRACTED_PARTS, include_tag, read_monolith_bundle
from tests.risk_fixture_helpers import monolith_risk_questionnaire
from tests.test_risk_questionnaire_integrity import (  # noqa: F401 - pytest fixtures
    advisor_user,
    client,
    mandate_id,
    session_factory,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "ares-desktop" / "frontend" / "risk-questionnaire-v2.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node nicht verfuegbar")

# Minimaler DOM: Abschnitte von Tab 3 (Fragen 9-11) und Tab 1 (Kenntnis-Tabellen).
HARNESS = r"""
function mkEl(tag){
  var e={tagName:String(tag||'div').toUpperCase(),children:[],style:{},dataset:{},className:'',
    textContent:'',innerHTML:'',attrs:{},parentNode:null,hidden:false,checked:false,
    appendChild:function(c){c.parentNode=e;e.children.push(c);return c;},
    insertBefore:function(c,ref){c.parentNode=e;var i=e.children.indexOf(ref);
      if(i<0)e.children.push(c);else e.children.splice(i,0,c);return c;},
    setAttribute:function(k,v){e.attrs[k]=String(v);},
    getAttribute:function(k){return k in e.attrs?e.attrs[k]:null;},
    querySelector:function(sel){return find(e,sel)[0]||null;},
    querySelectorAll:function(sel){return find(e,sel);},
    classList:{add:function(c){var s=e.className.split(' ').filter(Boolean);if(s.indexOf(c)<0)s.push(c);e.className=s.join(' ');},
               remove:function(c){e.className=e.className.split(' ').filter(function(x){return x&&x!==c;}).join(' ');},
               contains:function(c){return e.className.split(' ').indexOf(c)>=0;}}};
  return e;
}
function matches(e,sel){
  if(sel.charAt(0)==='.')return e.className.split(' ').indexOf(sel.slice(1))>=0;
  if(sel.charAt(0)==='#')return e.attrs.id===sel.slice(1);
  return e.tagName===sel.toUpperCase();
}
function find(root,sel){
  var out=[];
  (function walk(n){n.children.forEach(function(c){if(matches(c,sel))out.push(c);walk(c);});})(root);
  return out;
}
var RB=mkEl('div');RB.attrs.id='r-rb';
var SECTIONS=[0,1,2].map(function(){var s=mkEl('div');s.className='qsec';RB.appendChild(s);return s;});
var document={
  createElement:mkEl,
  getElementById:function(id){return id==='r-rb'?RB:null;},
  querySelectorAll:function(sel){return sel==='#r-rb .qsec'?find(RB,'.qsec'):[];}
};
"""


def _run(script: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.js"
        path.write_text(script, encoding="utf-8")
        proc = subprocess.run([NODE, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _module() -> str:
    return MODULE_PATH.read_text(encoding="utf-8")


def test_module_is_an_extracted_part_included_after_the_last_runtime_block():
    assert ("risk-questionnaire-v2.js", "js") in EXTRACTED_PARTS
    bundle = read_monolith_bundle()
    assert include_tag("risk-questionnaire-v2.js", "js") not in bundle
    assert "var RISK_Q10_BAND_FOOTNOTE=" in bundle
    # nach dem letzten Laufzeitblock: die gewrappten Funktionen existieren dann bereits
    assert bundle.index("function buildRiskAssessmentPayloadFromUI(") < bundle.index("var RISK_Q10_BAND_FOOTNOTE=")


def test_q10_footnote_text_is_identical_to_the_pdf():
    out = _run(HARNESS + _module() + "\nconsole.log(JSON.stringify(RISK_Q10_BAND_FOOTNOTE));")
    assert json.loads(out) == Q10_BAND_FOOTNOTE


def test_q10_footnote_is_appended_once_to_question_10_only():
    out = _run(HARNESS + _module() + r"""
riskV2AddQ10Footnote();  // zweiter Aufruf: idempotent
console.log(JSON.stringify(SECTIONS.map(function(s){
  return s.children.filter(function(c){return c.className==='rp-q10-note';}).map(function(c){return c.textContent;});
})));
""")
    notes = json.loads(out)
    assert notes[0] == [] and notes[2] == []
    assert notes[1] == [Q10_BAND_FOOTNOTE]


# ── H5b: Fragebogen v2 in der Maske ─────────────────────────────────────────────

# Echte Monolith-Funktionen (Builder, Profile) + Stubs fuer die gewrappten
# Laufzeitfunktionen; danach das Modul. STATE = Auswahl im Fragebogen.
_STUBS = r"""
var document={querySelectorAll:function(){return [];},getElementById:function(){return null;},
  createElement:function(){return {style:{}};}};
var SAVED=[];
function saveRiskProfile(){SAVED.push('base');return Promise.resolve(true);}
function hydrateRiskQuestionnaire(){}
var FEEDBACK=[];
function showRiskSaveFeedback(m){FEEDBACK.push(m);}
function formatRiskAssessmentIssues(i){return i.join(' | ');}
var STATE=null;
function collectRiskAssessmentUiState(){return STATE;}
"""


def _v2_script(body: str, *, enabled: bool = True) -> str:
    q = monolith_risk_questionnaire()
    o = q["options"]
    policy = rqi.questionnaire_v2_policy(enabled=enabled)
    return (
        monolith_js() + DOM + _STUBS + _module()
        + f"""
var O={json.dumps(o)};
var rf=[fakeSection(O['rf-income']),fakeSection([]),fakeSection(O['rf-oblig']),
        fakeSection(O['rf-wealth']),fakeSection(O['rf-savings']),fakeSection(O['rf-horizon'])];
var rb=[fakeSection(O['q9']),fakeSection(O['q10']),fakeSection(O['q11'])];
function state(goal,pref,behav,instr){{
  return {{rfSections:rf,rbSections:rb,incomeIdx:3,obligIdx:1,wealthIdx:3,savingsIdx:3,horizonIdx:5,
    goalIdx:goal,prefIdx:pref,behavIdx:behav,knowledgeServices:{{Anlageberatung:{{known:1,informed:1}}}},
    knowledgeInstruments:instr||{{Aktien:{{known:1,informed:1}}}},incomeSources:[{json.dumps(q["sources"][0])}]}};
}}
RISK_V2.policy={json.dumps(policy)};
var SEL={{}};
riskV2SelectedIndex=function(q){{return SEL[q]==null?-1:SEL[q];}};
"""
        + body
    )


def test_wrapper_is_a_no_op_while_v2_is_not_enabled():
    out = _run(_v2_script(r"""
STATE=state(3,3,0);
var r=buildRiskAssessmentPayloadFromUI();
console.log(JSON.stringify({keys:Object.keys(r.payload).sort(),will:r.willScore,fin:r.finalScore,
  issues:collectRiskAssessmentUiIssues()}));
""", enabled=False))
    data = json.loads(out)
    assert "questionnaire_version" not in data["keys"] and "questionnaire_v2_answers" not in data["keys"]
    assert (data["will"], data["fin"]) == (70, 70)  # v1 unveraendert, auch mit Panik-Antwort
    assert data["issues"] == []


def test_caps_and_flags_in_the_mask_equal_the_server_for_every_combination():
    out = _run(_v2_script(r"""
var rows=[], P=RISK_V2.policy, INSTR=[{Aktien:{known:0,informed:0}},{Aktien:{known:0,experienced:1,informed:0}}];
for(var q9=1;q9<=4;q9++)for(var q10=1;q10<=4;q10++)for(var q11=1;q11<=4;q11++){
  var core=Math.max(10,Math.min(100,Math.round(((q9+q10+q11-3)/9)*90+10)));
  for(var a=0;a<4;a++)for(var b=0;b<5;b++)for(var c=0;c<4;c++)for(var k=0;k<2;k++){
    var cc=riskV2Caps(P,q11,{12:a,13:b,14:c});
    var eff=Math.min(core,cc.cap);
    rows.push([q9,q10,q11,a,b,c,k,core,cc.cap,eff,cc.caps.map(function(x){return x.source;}),
      riskV2Flags(P,q9,q10,q11,b,riskWillingnessProfile(eff),INSTR[k])]);
  }
}
console.log(JSON.stringify(rows));
"""))
    instr = [json.dumps({"Aktien": {"known": 0, "informed": 0}}),
             json.dumps({"Aktien": {"known": 0, "experienced": 1, "informed": 0}})]
    rows = json.loads(out)
    assert len(rows) == 64 * 80 * 2
    for q9, q10, q11, a, b, c, k, core, cap, eff, sources, flags in rows:
        r = compute_willingness_v2(core_willingness_score_x10=core, q_risk_behavior_points=q11,
                                   q12_option=a, q13_option=b, q14_option=c)
        assert (r.cap_score_x10, r.effective_score_x10) == (cap, eff)
        assert [x.source for x in r.caps] == sources
        assert rqi.consistency_flags(
            q9=q9, q10=q10, q11=q11, q13_option=b, effective_willingness_profile=r.effective_profile,
            knowledge_instruments_json=instr[k],
        ) == flags


def _js_v2_payload(goal, pref, behav, sel, note="") -> dict:
    out = _run(_v2_script(f"""
STATE=state({goal},{pref},{behav});
SEL={json.dumps(sel)};
riskV2NoteText=function(){{return {json.dumps(note)};}};
var r=buildRiskAssessmentPayloadFromUI();
console.log(JSON.stringify({{payload:r?r.payload:null,will:r&&r.willScore,fin:r&&r.finalScore,
  prof:r&&r.finalProfile,issues:collectRiskAssessmentUiIssues()}}));
"""))
    return json.loads(out)


def test_mask_payload_with_full_agreement_equals_v1_and_is_accepted_by_the_server(
    client, mandate_id, monkeypatch,  # noqa: F811
):
    monkeypatch.setattr(rqi, "RISK_QUESTIONNAIRE_V2_ENABLED", True)
    data = _js_v2_payload(2, 2, 2, {"12": 3, "13": 3, "14": 3})
    p = data["payload"]
    assert p["questionnaire_version"] == "v2"
    assert [a["answer_label"] for a in p["questionnaire_v2_answers"]] == [
        rqi.V2_OPTIONS[12][3], rqi.V2_OPTIONS[13][3], rqi.V2_OPTIONS[14][3]]
    assert (data["will"], data["fin"]) == (70, 70) and data["issues"] == []
    resp = client.post(f"/mandates/{mandate_id}/risk-assessments", json=p)
    assert resp.status_code == 201, resp.text
    assert resp.json()["final_score_x10"] == data["fin"]


def test_mask_payload_with_panic_answer_is_capped_identically_on_the_server(
    client, mandate_id, monkeypatch,  # noqa: F811
):
    monkeypatch.setattr(rqi, "RISK_QUESTIONNAIRE_V2_ENABLED", True)
    note = "Panik-Antwort besprochen, Kunde bestaetigt defensive Haltung."
    data = _js_v2_payload(3, 3, 0, {"12": 3, "13": 3, "14": 3}, note=note)
    assert (data["will"], data["fin"], data["prof"]) == (40, 40, "Defensiv")
    resp = client.post(f"/mandates/{mandate_id}/risk-assessments", json=data["payload"])
    assert resp.status_code == 201, resp.text
    assert resp.json()["final_score_x10"] == 40


def test_mask_without_v2_answers_has_no_payload_and_names_the_questions():
    data = _js_v2_payload(2, 2, 2, {"12": 3})
    assert data["payload"] is None
    assert data["issues"] == [
        "Frage 13: Tatsächliches Verhalten", "Frage 14: Dauer einer Verlustphase"]


def test_mask_requires_the_note_before_saving_but_keeps_the_preview():
    out = _run(_v2_script(r"""
STATE=state(3,3,0); SEL={12:3,13:3,14:3};
riskV2NoteText=function(){return '';};
var r=buildRiskAssessmentPayloadFromUI();
saveRiskProfile().then(function(ok){
  console.log(JSON.stringify({preview:r&&r.finalScore,saved:ok,base:SAVED.length,fb:FEEDBACK,
    issues:collectRiskAssessmentUiIssues()}));
});
"""))
    data = json.loads(out)
    assert data["preview"] == 40          # Vorschau bleibt sichtbar
    assert data["saved"] is False and data["base"] == 0
    assert data["issues"] == ["Beraternotiz zu den Konsistenzhinweisen"]
    assert "Beraternotiz" in data["fb"][0]
