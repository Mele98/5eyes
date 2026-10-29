"""RISK-CAPACITY-RECHECK-UI-001: Monolith zeigt "neu zu pruefen".

``GET /mandates/{id}/risk-capacity-plausibility`` liefert ``bound_evaluation``
(zuletzt gebundene Bewertung) mit ``needs_recheck``/``recheck_label``. Der
Monolith zeigt das als ruhigen Hinweis direkt beim Plausibilitaets-Banner des
Risikoprofils. Laden + Hinweis liegen im Skriptmodul
``risk-capacity-recheck.js`` (Monolith-Budget, Toleranz 0); das Modul wird
hier in Node mit einem minimalen DOM-Harness ausgefuehrt.
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
MODULE_PATH = FRONTEND / "risk-capacity-recheck.js"
PACKAGE_JSON = REPO_ROOT / "5eyes-electron" / "package.json"

HARNESS = r"""
var calls={gets:[],rendered:[]};
var DOM={};
function el(id){if(!DOM[id])DOM[id]={id:id,innerHTML:'',textContent:'',style:{display:'none'},dataset:{}};return DOM[id];}
var document={getElementById:function(id){return id==='missing'?null:el(id);}};
function escapeHtml(v){return String(v==null?'':v).replace(/</g,'&lt;');}
var ACTIVE='m-1';
function getActiveMandateId(){return ACTIVE;}
function isDemoMandateId(id){return String(id).indexOf('demo')===0;}
function renderRiskCapacityPlausibility(res){calls.rendered.push(res);renderRiskCapacityRecheck(res&&res.bound_evaluation);}
var RESPONSE={status:'consistent',bound_evaluation:{evaluation_id:'ev-1',needs_recheck:true,
  recheck_code:'RISK_CAPACITY_EVALUATION_RECHECK_REQUIRED',recheck_label:'neu zu prüfen',
  recheck_text:'Plausibilitätsprüfung Risikofähigkeit neu zu prüfen: <b>Datenlage</b> geändert.',
  stale_reasons:['EVALUATION_INPUTS_CHANGED']}};
var API={get:async function(url){calls.gets.push(url);if(RESPONSE instanceof Error)throw RESPONSE;return RESPONSE;}};
"""


def _run(script: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    code = HARNESS + MODULE_PATH.read_text(encoding="utf-8") + "\n" + (
        "(async function(){\n" + script
        + "\nconsole.log(JSON.stringify({calls:calls,DOM:DOM}));})()"
        + ".catch(function(e){console.error(e&&e.stack||e);process.exit(1);});"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(code)
        path = handle.name
    out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_stale_bound_evaluation_shows_recheck_hint_escaped():
    result = _run("await refreshRiskCapacityPlausibility('m-1');")
    assert result["calls"]["gets"] == ["/mandates/m-1/risk-capacity-plausibility"]
    box = result["DOM"]["rp-capacity-recheck"]
    assert box["style"]["display"] == "block"
    assert "neu zu prüfen" in box["innerHTML"]
    assert "&lt;b>Datenlage" in box["innerHTML"] and "<b>" not in box["innerHTML"]
    assert box["dataset"]["recheckCode"] == "RISK_CAPACITY_EVALUATION_RECHECK_REQUIRED"


def test_current_or_missing_bound_evaluation_hides_hint():
    result = _run(
        "await refreshRiskCapacityPlausibility('m-1');"
        "RESPONSE={status:'consistent',bound_evaluation:{evaluation_id:'ev-1',needs_recheck:false,"
        "recheck_code:null,recheck_label:null,recheck_text:null,stale_reasons:[]}};"
        "await refreshRiskCapacityPlausibility('m-1');calls.afterCurrent=DOM['rp-capacity-recheck'].style.display;"
        "await refreshRiskCapacityPlausibility('m-1');"
        "RESPONSE={status:'partial',bound_evaluation:null};"
        "await refreshRiskCapacityPlausibility('m-1');"
    )
    assert result["calls"]["afterCurrent"] == "none"
    box = result["DOM"]["rp-capacity-recheck"]
    assert box["style"]["display"] == "none" and box["innerHTML"] == ""


def test_label_falls_back_when_backend_sends_none():
    result = _run(
        "RESPONSE.bound_evaluation.recheck_label=null;RESPONSE.bound_evaluation.recheck_text=null;"
        "await refreshRiskCapacityPlausibility('m-1');"
    )
    assert "neu zu prüfen" in result["DOM"]["rp-capacity-recheck"]["innerHTML"]


def test_reset_paths_clear_a_previous_hint():
    # Demo-Mandat, Ladefehler und Mandatswechsel duerfen keinen alten Hinweis stehen lassen.
    result = _run(
        "await refreshRiskCapacityPlausibility('m-1');"
        "await refreshRiskCapacityPlausibility('demo-1');calls.afterDemo=DOM['rp-capacity-recheck'].style.display;"
        "await refreshRiskCapacityPlausibility('m-1');"
        "RESPONSE=new Error('API 500');await refreshRiskCapacityPlausibility('m-1');"
    )
    assert result["calls"]["afterDemo"] == "none"
    assert result["DOM"]["rp-capacity-recheck"]["style"]["display"] == "none"
    assert result["calls"]["rendered"][-1] is None


def test_stale_response_for_other_mandate_is_ignored():
    result = _run("ACTIVE='m-2';await refreshRiskCapacityPlausibility('m-1');")
    assert result["calls"]["rendered"] == []
    assert "rp-capacity-recheck" not in result["DOM"]


def test_monolith_loads_module_and_hosts_hint_next_to_banner():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert '<script src="./risk-capacity-recheck.js"></script>' in html
    assert "function refreshRiskCapacityPlausibility(" not in html
    assert 'id="rp-capacity-recheck"' in html
    banner = html.index('id="rp-capacity-plausibility"')
    assert banner < html.index('id="rp-capacity-recheck"') < html.index('<div class="resbox">')
    start = html.index("function renderRiskCapacityPlausibility(")
    render = html[start:html.index("\n}\n", start)]
    # Jeder Render-Pfad (auch null bei Mandatswechsel) setzt den Hinweis mit.
    assert "renderRiskCapacityRecheck(result&&result.bound_evaluation)" in render
    assert render.index("renderRiskCapacityRecheck(") < render.index("if(!box)return;")
    assert "frontend/risk-capacity-recheck.js" in json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["build"]["files"]


def test_fallback_label_matches_backend_contract():
    import sys

    backend = REPO_ROOT / "5eyes-backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from services.risk_capacity_evaluation_snapshot import RECHECK_LABEL

    source = MODULE_PATH.read_text(encoding="utf-8")
    assert f"var RISK_CAPACITY_RECHECK_FALLBACK_LABEL='{RECHECK_LABEL}';" in source
