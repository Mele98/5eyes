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

from services.pdf.components.eignungspruefung import Q10_BAND_FOOTNOTE
from tests.monolith_source import EXTRACTED_PARTS, include_tag, read_monolith_bundle

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
