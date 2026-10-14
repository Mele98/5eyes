"""BAND-OVERRIDE-ROUNDTRIP-001 (Assetallocation-Audit 2026-10-14).

The "Soll-Quoten & Bandbreiten" editor (``buildQT('qt-modal')`` +
``collectBandOverridesFromModal()``) took its "unchanged" baseline from the
CURRENT engine result. The engine echoes an applied override back in the
buckets, so on the next opening the override WAS the baseline: the collector
returned ``{}``, "Neu berechnen" persisted ``bands = {}`` and the next
calculation silently ran without the advisor's restriction (audit: Aktien
max 7000 applied in run 1, gone after one round-trip).

Same code path, two more defects fixed here:

* PARTIAL EDIT: editing only "Max" sent the full min/target/max triplet
  filled from the result, so Aktien Max 50 % produced
  ``{min 6000, target 6000, max 5000}`` -> 422 instead of the backend's
  partial-override contract (``{max_bps: 5000}``).
* UNIT MIX-UP: stored overrides are bps, but were re-read through the
  percent parser, which treats numbers <= 100 as percent -- a stored
  liquidity max of 100 bps (1 %) came back as 10'000 bps (100 %).

The functions are executed from the real monolith in node (same convention as
tests/test_goal_driver_evidence_delivery_chain.py).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"
BUCKETS = ["equities", "bonds", "real_estate", "alternatives", "liquidity"]


def _function(src: str, signature: str) -> str:
    start = src.index(signature)
    i = src.index("{", start + len(signature) - 1)
    depth, j = 1, i + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
    return src[start:j]


def _run(scenario_js: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")
    src = HTML_PATH.read_text(encoding="utf-8")
    names = [
        "function normalizeBandKey(", "function parseBandPercentInput(",
        "function formatBandPercent(", "function normalizeBandOverrideEntry(",
        "function collectBandOverridesFromModal(", "function buildQT(",
    ]
    optional = ["function normalizeStoredBandOverride(", "function parseBandPercentUserInput("]
    fns = [_function(src, n) for n in names]
    fns += [_function(src, n) for n in optional if n in src]
    harness = r"""
var allocationBandBaseline={}, allocationBandStoredOverrides={}, quoten=[];
var STORED={bands:{}}; var RESULT=null; var INPUTS=[];
function ensureAllocationRuntimePanels(){}
function buildAllocationPendingSummaryHtml(){return '';}
function updateBandOverrideStatus(){}
function markStrategyDirty(){}
function persistAllocationPreferences(){}
function loadAllocationPreferences(){return JSON.parse(JSON.stringify(STORED));}
function deriveQuotenFromAllocation(a){
  return a.buckets.map(function(b){return {key:b.key,n:b.key,c:'#000',ist:0,
    min:b.band_min_bps/100,ziel:b.target_weight_bps/100,max:b.band_max_bps/100};});
}
var strategyState={allocation:null};
// Minimal DOM: buildQT writes innerHTML; we parse the generated <input>s.
var container={_html:'',set innerHTML(v){this._html=v;INPUTS=parseInputs(v);},get innerHTML(){return this._html;},
  querySelectorAll:function(){return INPUTS;}};
function parseInputs(html){
  var out=[];var re=/<input class="qtinp"([^>]*)>/g;var m;
  while((m=re.exec(html))){
    var attrs={};var ar=/([\w-]+)="([^"]*)"/g;var a;
    while((a=ar.exec(m[1])))attrs[a[1]]=a[2];
    (function(attrs){out.push({value:attrs.value,getAttribute:function(k){return attrs[k]==null?null:attrs[k];},
      addEventListener:function(){},style:{}});})(attrs);
  }
  return out;
}
var document={getElementById:function(){return container;},
  querySelectorAll:function(sel){return INPUTS;}};
function setInput(bucket,field,value){
  INPUTS.forEach(function(i){if(i.getAttribute('data-bucket')===bucket&&i.getAttribute('data-field')===field)i.value=value;});
}
function engineResult(overrides){
  var base={equities:[6000,7080,7500],bonds:[1000,1210,2500],real_estate:[500,1033,2000],alternatives:[300,300,1000],liquidity:[100,377,500]};
  return {buckets:Object.keys(base).map(function(k){
    var b=base[k].slice(), o=overrides[k]||{};
    if(o.min_bps!=null)b[0]=o.min_bps; if(o.max_bps!=null)b[2]=o.max_bps;
    if(b[1]>b[2])b[1]=b[2]; if(b[1]<b[0])b[1]=b[0];
    return {key:k,band_min_bps:b[0],target_weight_bps:b[1],band_max_bps:b[2]};})};
}
"""
    script = "\n".join(fns) + harness + scenario_js
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    res = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=30)
    Path(path).unlink(missing_ok=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_applied_override_survives_reopen_and_recalculate():
    out = _run(r"""
// Run 1: advisor sets Aktien max 70 % and the engine applies + echoes it.
STORED.bands={equities:{max_bps:7000}};
strategyState.allocation=engineResult(STORED.bands);
buildQT('qt-modal');
// Advisor reopens the editor and presses "Neu berechnen" WITHOUT editing.
var collected=collectBandOverridesFromModal();
console.log(JSON.stringify({collected:collected}));
""")
    assert out["collected"] == {"equities": {"max_bps": 7000}}


def test_untouched_override_survives_editing_another_bucket():
    out = _run(r"""
STORED.bands={equities:{max_bps:7000}};
strategyState.allocation=engineResult(STORED.bands);
buildQT('qt-modal');
setInput('bonds','min_bps','15%');
console.log(JSON.stringify({collected:collectBandOverridesFromModal()}));
""")
    assert out["collected"] == {"equities": {"max_bps": 7000}, "bonds": {"min_bps": 1500}}


def test_max_only_edit_sends_only_max():
    out = _run(r"""
STORED.bands={};
strategyState.allocation=engineResult({});
buildQT('qt-modal');
setInput('equities','max_bps','50%');
console.log(JSON.stringify({collected:collectBandOverridesFromModal()}));
""")
    assert out["collected"] == {"equities": {"max_bps": 5000}}


def test_stored_small_bps_override_is_not_misread_as_percent():
    out = _run(r"""
// A stored liquidity max of 100 bps (= 1 %) must render as 1 % and stay 100.
STORED.bands={liquidity:{max_bps:100}};
strategyState.allocation=engineResult(STORED.bands);
buildQT('qt-modal');
var shown=INPUTS.filter(function(i){return i.getAttribute('data-bucket')==='liquidity'&&i.getAttribute('data-field')==='max_bps';})[0].value;
console.log(JSON.stringify({shown:shown,collected:collectBandOverridesFromModal()}));
""")
    assert out["shown"] == "1%"
    assert out["collected"] == {"liquidity": {"max_bps": 100}}


def test_no_edits_and_no_stored_overrides_sends_nothing():
    out = _run(r"""
STORED.bands={};
strategyState.allocation=engineResult({});
buildQT('qt-modal');
console.log(JSON.stringify({collected:collectBandOverridesFromModal()}));
""")
    assert out["collected"] == {}


def test_out_of_range_percent_input_is_not_sent_as_bps():
    out = _run(r"""
STORED.bands={};
strategyState.allocation=engineResult({});
buildQT('qt-modal');
setInput('equities','max_bps','150');
console.log(JSON.stringify({collected:collectBandOverridesFromModal()}));
""")
    # "150" in a percent field is invalid; it must never become 150 bps (1.5 %).
    assert out["collected"] == {}
