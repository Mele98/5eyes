"""C-COMP-02: Classic-Maske ``product-evidence.js`` (eigenes Modul)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.monolith_source import read_monolith_bundle

ROOT = Path(__file__).resolve().parents[2] / "ares-desktop"
MODULE = ROOT / "frontend" / "product-evidence.js"


def test_module_is_loaded_packaged_and_free_of_native_dialogs():
    html = read_monolith_bundle()
    assert '<script src="./product-evidence.js"></script>' in html
    assert "frontend/product-evidence.js" in json.loads((ROOT / "package.json").read_text("utf-8"))["build"]["files"]
    source = MODULE.read_text("utf-8")
    for forbidden in ("alert(", "window.confirm(", "prompt(", "localStorage", "sessionStorage"):
        assert forbidden not in source


_HARNESS = r"""
var calls=[], items=%(items)s, errors=[];
var nodes={};
function node(id){ if(!nodes[id]) nodes[id]={id:id,value:'',innerHTML:'',style:{},parentNode:{insertBefore:function(){}},
  addEventListener:function(e,f){this.click=f;}, setAttribute:function(){}, querySelectorAll:function(sel){
    if(sel==='[data-pe-seen]') return items.map(function(it,i){return {checked:it.checked,getAttribute:function(){return String(i);}};});
    if(sel==='[data-pe-open]') return [{getAttribute:function(){return '0';},addEventListener:function(e,f){nodes.open=f;}}];
    return []; }}; return nodes[id]; }
var document={readyState:'complete',addEventListener:function(){},getElementById:function(id){
  return (id==='pe-reviewer-body')?null:node(id);},createElement:function(){return node('new');}};
var window={}; var currentUser={role:'admin'};
function escapeHtml(s){return String(s);} function showAppError(m){errors.push(m);} function parseApiError(e,f){return f;}
async function uiConfirm(){return true;}
var API={get:async function(p){calls.push(['GET',p]); if(p.indexOf('overview')>=0) return [{product_id:'p1',product_name:'P',
  stable_instrument_id:'ISIN1',share_class_id:null,status:'missing',issues:[]}]; return items;},
  post:async function(p,b){calls.push(['POST',p,b]); if(%(reject)s) throw new Error('409');}};
%(source)s
(async function(){
  await window.loadProductEvidence(); await nodes.open();
  %(act)s
  await new Promise(function(r){setTimeout(r,20);});
  process.stdout.write(JSON.stringify({calls:calls,errors:errors,text:window.productEvidenceReasonText('PRODUCT_EVIDENCE_STALE'),html:nodes['sec-product-evidence'].innerHTML}));
})();
"""


def _run(tmp_path, *, act, reject="false", items=None):
    if shutil.which("node") is None:
        pytest.fail("node fehlt: der Modulvertrag ist nicht pruefbar")
    items = items if items is not None else [
        {"id": "d1", "status": "draft", "evidence_kind": "kid", "canonical_payload_hash": "a" * 64, "checked": True},
        {"id": "d2", "status": "draft", "evidence_kind": "costs", "canonical_payload_hash": "b" * 64, "checked": False},
    ]
    script = tmp_path / "h.js"
    script.write_text(_HARNESS % {
        "items": json.dumps(items), "source": MODULE.read_text("utf-8"), "act": act, "reject": reject}, "utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


def test_approval_sends_exactly_the_seen_set_and_reloads_after_rejection(tmp_path):
    for reject in ("false", "true"):
        out = _run(tmp_path, act="await nodes['pe-approve'].click();", reject=reject)
        posts = [c for c in out["calls"] if c[0] == "POST"]
        assert posts == [["POST", "/products/p1/evidence/approve", {
            "items": [{"item_id": "d1", "canonical_payload_hash": "a" * 64}], "attestation": None}]]
        assert out["calls"][-1] == ["GET", "/products/p1/evidence"]
        assert bool(out["errors"]) is (reject == "true")
    assert "abgelaufen" in out["text"]


def test_empty_value_is_never_sent_as_zero_and_statement_is_mandatory(tmp_path):
    out = _run(tmp_path, act="node('pe-kind').value='costs'; await nodes['pe-create'].click();")
    assert not [c for c in out["calls"] if c[0] == "POST"] and out["errors"]
    out = _run(tmp_path, act=(
        "node('pe-kind').value='costs'; node('pe-status').value='documented'; await nodes['pe-create'].click();"))
    body = [c for c in out["calls"] if c[0] == "POST"][0][2]
    assert "value" not in body["payload"]  # Server lehnt ab: PRODUCT_EVIDENCE_COST_MISSING
    assert body["stable_instrument_id"] == "ISIN1" and body["share_class_id"] is None
