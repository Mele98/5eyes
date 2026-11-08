"""H8 (Compliance-Audit 2026-11-07): Frontend-Teil client-compliance.js.

- N-873-09: Die Audit-Tabelle der Administration zeigt ``rank_requested`` als
  "Gewünschter Rang (nicht übernommen)" (Basis: roher Feldname).
- Rechtliche Angaben, Kundeninformation/KYC/Vertretung: Masken ohne
  Vorbelegung, Sperrgruende 1:1 vom Backend, Einhaengen ohne Aenderung an
  ares.html ausser der Einbindung (Monolith-Budget, Toleranz 0).

Das Modul wird in Node mit einem minimalen DOM-Harness ausgefuehrt.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.monolith_source import MONOLITH_PATH, read_monolith_bundle

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "ares-desktop" / "frontend"
MODULE_PATH = FRONTEND / "client-compliance.js"

HARNESS = r"""
var window=globalThis;
var calls={gets:[],puts:[],posts:[],notices:[]};
function mkEl(tag,id){return {tagName:tag,id:id||'',innerHTML:'',textContent:'',style:{},className:'',
  attrs:{},children:[],parentNode:null,listeners:{},
  setAttribute:function(k,v){this.attrs[k]=v;},getAttribute:function(k){return this.attrs[k];},
  addEventListener:function(t,f){this.listeners[t]=f;},
  insertBefore:function(n,ref){n.parentNode=this;this.children.push(n);if(n.id)DOM[n.id]=n;
    (String(n.innerHTML).match(/id="([^"]+)"/g)||[]).forEach(function(m){var i=m.slice(4,-1);DOM[i]=mkEl('div',i);});
    return n;},
  closest:function(){return this._card||null;},nextSibling:null};}
var DOM={};
var container=mkEl('div','root');
DOM['asec-audit']=mkEl('button','asec-audit');DOM['asec-audit'].parentNode=container;
DOM['sec-audit']=mkEl('div','sec-audit');DOM['sec-audit'].parentNode=container;
var docsCard=mkEl('div','docs-card');docsCard.parentNode=container;
DOM['sd-output-hub']=mkEl('div','sd-output-hub');DOM['sd-output-hub']._card=docsCard;
var document={readyState:'complete',getElementById:function(id){return DOM[id]||null;},
  createElement:function(tag){return mkEl(tag);},addEventListener:function(){}};
function escapeHtml(v){return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function parseApiError(e,f){return (e&&e.message)||f;}
function showAppNotice(o){calls.notices.push(o);}
function showAppError(m){calls.notices.push({level:'error',message:m});}
var currentMandateId='m-1', currentClientId='c-1';
var RESP={};
var API={
  get:async function(url){calls.gets.push(url);var r=RESP[url];if(r instanceof Error)throw r;return r;},
  put:async function(url,b){calls.puts.push([url,b]);return RESP['PUT '+url];},
  post:async function(url,b){calls.posts.push([url,b]);return {};}
};
"""


def _run(script: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    code = HARNESS + MODULE_PATH.read_text(encoding="utf-8") + "\n" + (
        "(async function(){\n" + script
        + "\nconsole.log(JSON.stringify({calls:calls,DOM:Object.keys(DOM).reduce(function(a,k){"
        "a[k]={innerHTML:DOM[k].innerHTML,textContent:DOM[k].textContent,attrs:DOM[k].attrs};return a;},{})}));})()"
        + ".catch(function(e){console.error(e&&e.stack||e);process.exit(1);});"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(code)
        path = handle.name
    out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_audit_table_labels_rank_requested():
    result = _run(
        "var c=mkEl('div','al');DOM['al']=c;"
        "renderAuditLogTable([{created_at:'2026-11-07T10:00:00Z',user_name:'A',table_name:'goals',"
        "action:'UPDATE',record_id:'abcdef123456',field_name:'rank_requested',new_value:'2'},"
        "{created_at:'2026-11-07T10:00:00Z',user_name:'A',table_name:'x',action:'UPDATE',record_id:'1',"
        "field_name:'unbekanntes_feld',new_value:'v'}],c);"
    )
    html = result["DOM"]["al"]["innerHTML"]
    assert "Gewünschter Rang (nicht übernommen) → 2" in html
    assert "rank_requested" not in html
    assert "unbekanntes_feld → v" in html  # unbekannte Felder bleiben roh


def test_audit_renderer_lives_only_in_the_module():
    bundle = read_monolith_bundle()
    assert bundle.count("function renderAuditLogTable(") == 1
    raw = MONOLITH_PATH.read_text(encoding="utf-8")
    assert "function renderAuditLogTable(" not in raw
    assert raw.count('<script src="./client-compliance.js"></script>') == 1


def test_mounts_admin_section_and_stammdaten_card_without_monolith_markup():
    result = _run("")
    dom = result["DOM"]
    assert "asec-legal-profile" in dom and "sec-legal-profile" in dom
    assert "sd-client-compliance" in dom
    raw = MONOLITH_PATH.read_text(encoding="utf-8")
    assert "sec-legal-profile" not in raw and "sd-client-compliance" not in raw


def test_legal_profile_form_has_no_prefilled_values_and_shows_missing():
    profile = {
        "tenant_id": "t", "present": False, "revision": 0, "missing_fields": ["legal_name", "ombudsman_name"],
        "missing_labels": ["Firma (vollstaendiger Name)", "Ombudsstelle: Name"],
        "field_labels": {"legal_name": "Firma (vollstaendiger Name)", "ombudsman_name": "Ombudsstelle: Name"},
        "supervision_labels": {"vermoegensverwalter_finig": "VV FINIG"}, "complete": False,
    }
    result = _run(
        "RESP['/compliance/legal-profile']=" + json.dumps(profile) + ";"
        "await loadAdminLegalProfile();"
    )
    html = result["DOM"]["sec-legal-profile"]["innerHTML"]
    assert "Es fehlen: Firma (vollstaendiger Name), Ombudsstelle: Name" in html
    assert 'id="lp-legal_name" value=""' in html
    assert '<option value="">nicht erfasst</option>' in html
    assert " selected" not in html  # kein Aufsichtsstatus vorausgewaehlt


def test_compliance_panel_shows_backend_findings_and_unanswered_kyc_selects():
    status = {
        "mandate_id": "m-1", "client_id": "c-1", "release_ready": False,
        "findings": [{"reason_code": "KYC_CONFIRMATION_MISSING", "message": "Bestaetigung fehlt: X",
                      "owner_action": "Berater: KYC-Bestaetigung erfassen", "scope": "client"}],
        "legal_profile": {}, "deliveries": [], "kyc_confirmation": None,
        "kyc_requires_second_approval": None, "template_version": "ARES-KI-FIDLEG-1", "latest_document": None,
    }
    result = _run(
        "RESP['/mandates/m-1/client-onboarding/status']=" + json.dumps(status) + ";"
        "RESP['/clients/c-1/representations']=[];"
        "await new Promise(function(r){setTimeout(r,200);});"
        "await renderClientCompliancePanel();"
    )
    html = result["DOM"]["sd-client-compliance"]["innerHTML"]
    assert 'data-reason-code="KYC_CONFIRMATION_MISSING"' in html
    assert "Zu tun: Berater: KYC-Bestaetigung erfassen" in html
    assert '<option value="" selected>nicht beantwortet</option>' in html
    for select_id in ("kyc-form", "kyc-risk", "kyc-pep", "rep-type"):
        assert f'id="{select_id}" style="font-size:11px"><option value="">bitte wählen</option>' in html, select_id
    assert result["DOM"]["sd-client-compliance"]["attrs"]["data-release-ready"] == "0"


def test_kyc_submission_sends_unanswered_pep_as_null_not_false():
    result = _run(
        "DOM['kyc-pep']={value:''};DOM['kyc-risk']={value:'normal'};DOM['kyc-form']={value:'A'};"
        "DOM['kyc-date']={value:'2026-11-01'};DOM['kyc-ref']={value:'Ref'};DOM['kyc-review']={value:'2027-11-01'};"
        "RESP['/mandates/m-1/client-onboarding/status']={findings:[],deliveries:[]};"
        "RESP['/clients/c-1/representations']=[];"
        "await createKycConfirmation();"
    )
    url, body = result["calls"]["posts"][0]
    assert url == "/clients/c-1/kyc-confirmations"
    assert body["is_pep"] is None
