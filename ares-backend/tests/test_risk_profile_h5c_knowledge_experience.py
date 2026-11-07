"""H5c Kenntnisse und Erfahrung getrennt (Dok. 105 G8, Entscheid E6; Art. 11 FIDLEG).

Rein dokumentarisch (Angemessenheit), kein Bereitschafts-Score:

* Beide Kenntnis-Tabellen erhalten die Spalte "Erfahrung vorhanden"
  (``experienced``); die Instrumentliste kennt zusaetzlich ETF, strukturierte
  Produkte, Derivate, Alternative Anlagen, Private Equity, Rohstoffe und
  Fremdwaehrungsanlagen.
* Bestehende Daten ohne Informationsverlust: Altprofile tragen den Schluessel
  nicht, bleiben gueltig und werden nicht umgeschrieben (gebundene Evidenz);
  ihr PDF-Text bleibt gleich, die Maske weist auf die gemeinsame Erfassung hin.
* Scores bleiben unberuehrt; der Kenntnis-Abgleich der SAA nutzt die neuen
  Zeilen.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from services.knowledge_asset_class_gap import (
    QUESTIONNAIRE_INSTRUMENT_ROWS,
    documented_instrument_rows,
    evaluate_knowledge_gaps,
    required_rows_for,
)
from services.pdf.components.eignungspruefung import _knowledge_summary
from services.risk_questionnaire_integrity import _knowledge_table_ok
from tests.monolith_source import read_monolith_bundle
from tests.risk_fixture_helpers import standard_risk_payload
from tests.test_risk_questionnaire_integrity import (  # noqa: F401 - pytest fixtures
    advisor_user,
    client,
    mandate_id,
    session_factory,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = REPO_ROOT / "ares-desktop" / "frontend" / "risk-questionnaire-v2.js"
NODE = shutil.which("node")
NEW_ROWS = ("ETF", "Strukturierte Produkte", "Derivate", "Alternative Anlagen",
            "Private Equity", "Rohstoffe", "Fremdwährungsanlagen")


def _module_rows() -> list[str]:
    src = MODULE.read_text(encoding="utf-8")
    block = src.split("var RISK_KE_EXTRA_INSTRUMENTS=[", 1)[1].split("];", 1)[0]
    return re.findall(r"\['([^']+)','[^']+'\]", block)


# ── Daten ───────────────────────────────────────────────────────────────────────

def test_knowledge_table_accepts_separate_experience_and_legacy_rows():
    assert _knowledge_table_ok(json.dumps({"Aktien": {"known": 1, "experienced": 0, "informed": 1}}))
    assert _knowledge_table_ok(json.dumps({"Aktien": {"known": 1, "informed": 1}}))  # Altprofil
    assert not _knowledge_table_ok(json.dumps({"Aktien": {"known": 1, "erfahren": 1}}))
    assert not _knowledge_table_ok(json.dumps({"Aktien": {"experienced": True}}))


def test_new_payload_with_experience_and_new_rows_is_saved_unchanged_scores(client, mandate_id):
    payload = standard_risk_payload()
    instruments = {"Aktien": {"known": 1, "experienced": 0, "informed": 1},
                   "Private Equity": {"known": 0, "experienced": 1, "informed": 0}}
    payload["knowledge_instruments_json"] = json.dumps(instruments)
    payload["answers"][1]["answer_label"] = "Finanzinstrumente: " + json.dumps(instruments, separators=(",", ":"))
    resp = client.post(f"/mandates/{mandate_id}/risk-assessments", json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["final_score_x10"] == 70  # dokumentarisch, kein Score
    assert json.loads(resp.json()["knowledge_instruments_json"]) == instruments


# ── PDF ─────────────────────────────────────────────────────────────────────────

def test_pdf_lists_experience_separately():
    text = _knowledge_summary({"Aktien": {"known": 1, "experienced": 1, "informed": 0},
                               "Derivate": {"known": 0, "experienced": 0, "informed": 1}})
    assert text == "Aktien: Kenntnisse vorhanden, Erfahrung vorhanden; Derivate: Aufklärung erhalten"


def test_pdf_text_of_legacy_rows_is_unchanged():
    assert _knowledge_summary({"Aktien": {"known": 1, "informed": 1}}) == \
        "Aktien: Kenntnisse vorhanden, Aufklärung erhalten"


# ── Angemessenheit: Kenntnis-Abgleich der SAA ───────────────────────────────────

def test_questionnaire_rows_are_monolith_rows_plus_module_rows():
    html_rows = list(dict.fromkeys(re.findall(r'class="ke-ins" data-row="([^"]+)"', read_monolith_bundle())))
    assert tuple(_module_rows()) == NEW_ROWS
    assert tuple(html_rows) + NEW_ROWS == QUESTIONNAIRE_INSTRUMENT_ROWS


def test_new_rows_cover_alternatives_and_private_equity():
    assert required_rows_for("Alternative", "Private Equity") == ("Private Equity",)
    assert required_rows_for("Alternative", "Hedge Funds") == ("Alternative Anlagen",)
    assert required_rows_for("Alternative", "Liquid Alternatives") == ("Alternative Anlagen",)
    assert required_rows_for("Alternative", "Krypto") == ()          # weiterhin keine Zeile
    assert required_rows_for("Alternative", "Unbekannt XY") == ()    # konservativ
    saa = [{"asset_class": "Alternative", "sub_asset_class": "Private Equity", "target_weight_bps": 300}]
    gap = evaluate_knowledge_gaps(saa, "{}", client_classification="Privatkunde")
    assert gap["findings"][0]["questionnaire_row_available"] is True
    ok = evaluate_knowledge_gaps(saa, json.dumps({"Private Equity": {"known": 1, "experienced": 0, "informed": 0}}),
                                 client_classification="Privatkunde")
    assert ok["findings"] == []
    # N-886-06: Erfahrung allein ist kein Kenntnisnachweis -> Hinweis bleibt.
    exp = evaluate_knowledge_gaps(saa, json.dumps({"Private Equity": {"known": 0, "experienced": 1, "informed": 0}}),
                                  client_classification="Privatkunde")
    assert exp["findings"][0]["experience_only"] is True
    assert "Aufklärung dokumentieren" in exp["findings"][0]["message"]


def test_experience_alone_does_not_document_a_row():
    # N-886-06 (Art. 11 FIDLEG, wie ELIG-KNOWLEDGE-001): Kenntnis ODER Aufklaerung noetig.
    assert documented_instrument_rows({"Derivate": {"known": 0, "experienced": 1, "informed": 0}}) == set()
    assert _knowledge_summary({"Derivate": {"known": 0, "experienced": 1, "informed": 0}}) ==         "Derivate: Erfahrung vorhanden, Kenntnisse/Aufklärung nicht dokumentiert"


# ── Maske (Node, minimaler DOM) ─────────────────────────────────────────────────

_HARNESS = r"""
function mkEl(tag){
  var e={tagName:String(tag||'div').toUpperCase(),children:[],style:{},className:'',textContent:'',
    attrs:{},parentNode:null,type:'',checked:false,
    appendChild:function(c){c.parentNode=e;e.children.push(c);return c;},
    insertBefore:function(c,ref){c.parentNode=e;var i=e.children.indexOf(ref);
      if(i<0)e.children.push(c);else e.children.splice(i,0,c);return c;},
    setAttribute:function(k,v){e.attrs[k]=String(v);},
    getAttribute:function(k){return k in e.attrs?e.attrs[k]:null;}};
  Object.defineProperty(e,'nextSibling',{get:function(){
    if(!e.parentNode)return null;var s=e.parentNode.children;return s[s.indexOf(e)+1]||null;}});
  Object.defineProperty(e,'id',{get:function(){return e.attrs.id||'';},set:function(v){e.attrs.id=v;}});
  return e;
}
var ALL=[];
function walk(n,f){n.children.forEach(function(c){f(c);walk(c,f);});}
function grid(cls,rows){
  var wrap=mkEl('div'), g=mkEl('div');wrap.appendChild(g);
  ['Finanzinstrument','Kenntnisse vorhanden','Aufklärung erhalten'].forEach(function(t){
    var h=mkEl('div');h.textContent=t;h.style.cssText='hdr';g.appendChild(h);});
  rows.forEach(function(r){
    var l=mkEl('div');l.textContent=r;g.appendChild(l);
    ['known','informed'].forEach(function(col){var c=mkEl('div');c.style.cssText='cell-'+col;
      var i=mkEl('input');i.className=cls;i.setAttribute('data-row',r);i.setAttribute('data-col',col);
      c.appendChild(i);g.appendChild(c);});
  });
  ALL.push(wrap);return g;
}
var SVC=grid('ke-svc',['Anlageberatung']);
var INS=grid('ke-ins',['Aktien','Edelmetalle']);
var document={
  createElement:mkEl,
  getElementById:function(id){var f=null;ALL.forEach(function(w){walk(w,function(n){if(n.id===id)f=n;});});return f;},
  querySelectorAll:function(sel){
    var m=/^input\.(.+)$/.exec(sel), out=[];
    if(!m)return [];
    ALL.forEach(function(w){walk(w,function(n){if(n.tagName==='INPUT'&&n.className===m[1])out.push(n);});});
    return out;
  }
};
"""

pytestmark_node = pytest.mark.skipif(NODE is None, reason="node nicht verfuegbar")


def _run(script: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.js"
        path.write_text(script, encoding="utf-8")
        proc = subprocess.run([NODE, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytestmark_node
def test_mask_adds_experience_column_and_new_instrument_rows_once():
    out = _run(_HARNESS + MODULE.read_text(encoding="utf-8") + r"""
riskKeExtendTable('ke-ins',RISK_KE_EXTRA_INSTRUMENTS);  // idempotent
function shape(g){return g.children.map(function(c){
  var i=c.children[0];return i?i.getAttribute('data-row')+'/'+i.getAttribute('data-col'):c.textContent;});}
console.log(JSON.stringify({svc:shape(SVC),ins:shape(INS),cols:INS.style.gridTemplateColumns}));
""")
    data = json.loads(out)
    assert data["svc"] == ["Finanzinstrument", "Kenntnisse vorhanden", "Erfahrung vorhanden", "Aufklärung erhalten",
                           "Anlageberatung", "Anlageberatung/known", "Anlageberatung/experienced",
                           "Anlageberatung/informed"]
    assert data["cols"] == "1fr 110px 110px 110px"
    ins = data["ins"]
    assert ins[:12] == ["Finanzinstrument", "Kenntnisse vorhanden", "Erfahrung vorhanden", "Aufklärung erhalten",
                        "Aktien", "Aktien/known", "Aktien/experienced", "Aktien/informed",
                        "Edelmetalle", "Edelmetalle/known", "Edelmetalle/experienced", "Edelmetalle/informed"]
    added = [ins[i] for i in range(12, len(ins), 4)]
    assert len(ins) == 12 + 4 * len(NEW_ROWS)
    assert [r.split(" (")[0].split(" /")[0] for r in added][:2] == ["Börsengehandelte Indexfonds", "Strukturierte Produkte"]
    for i, row in enumerate(NEW_ROWS):
        assert ins[13 + 4 * i: 16 + 4 * i] == [f"{row}/known", f"{row}/experienced", f"{row}/informed"]


@pytestmark_node
def test_mask_shows_legacy_hint_only_for_rows_without_separate_experience():
    out = _run(_HARNESS + MODULE.read_text(encoding="utf-8") + r"""
var res=[];
riskKeLegacyHint({knowledge_instruments_json:JSON.stringify({Aktien:{known:1,informed:0}})});
res.push(document.getElementById('rp-ke-legacy-hint').style.display);
riskKeLegacyHint({knowledge_instruments_json:JSON.stringify({Aktien:{known:1,experienced:0,informed:0}})});
res.push(document.getElementById('rp-ke-legacy-hint').style.display);
riskKeLegacyHint(null);
res.push(document.getElementById('rp-ke-legacy-hint').style.display);
console.log(JSON.stringify(res));
""")
    assert json.loads(out) == ["", "none", "none"]
