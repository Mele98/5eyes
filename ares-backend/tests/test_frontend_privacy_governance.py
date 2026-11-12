"""H10 (DSG-Technikaudit 2026-11-11): Frontend-Teil privacy-governance.js.

Administration > Compliance > "Datenschutz": Status, Angaben des
Verantwortlichen (ohne Vorbelegung), Betroffenenanfragen (Frist sichtbar),
Sicherheitsvorfaelle (Gate rot bei offener Meldepflicht), ausgehende
Verbindungen. Einhaengen ohne Markup im Monolithen ausser der Einbindung;
renderAuditLogPagination ist aus dem Monolithen umgezogen (Budget).

Das Modul laeuft in Node mit einem minimalen DOM-Harness.
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
MODULE_PATH = REPO_ROOT / "ares-desktop" / "frontend" / "privacy-governance.js"

HARNESS = r"""
var window=globalThis;
var calls={gets:[],puts:[],posts:[],notices:[]};
function mkEl(tag,id){return {tagName:tag,id:id||'',innerHTML:'',textContent:'',style:{},className:'',
  attrs:{},children:[],parentNode:null,listeners:{},
  setAttribute:function(k,v){this.attrs[k]=v;},getAttribute:function(k){return this.attrs[k];},
  addEventListener:function(t,f){this.listeners[t]=f;},
  insertBefore:function(n,ref){n.parentNode=this;this.children.push(n);if(n.id)DOM[n.id]=n;return n;},
  nextSibling:null};}
var DOM={};
var container=mkEl('div','root');
DOM['asec-audit']=mkEl('button','asec-audit');DOM['asec-audit'].parentNode=container;
DOM['sec-audit']=mkEl('div','sec-audit');DOM['sec-audit'].parentNode=container;
var document={readyState:'complete',getElementById:function(id){return DOM[id]||null;},
  createElement:function(tag){return mkEl(tag);},addEventListener:function(){}};
function escapeHtml(v){return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function parseApiError(e,f){return (e&&e.message)||f;}
function showAppNotice(o){calls.notices.push(o);}
function showAppError(m){calls.notices.push({level:'error',message:m});}
var RESP={};
var API={
  get:async function(url){calls.gets.push(url);var r=RESP[url];if(r instanceof Error)throw r;return r;},
  put:async function(url,b){calls.puts.push([url,b]);return {};},
  post:async function(url,b){calls.posts.push([url,b]);return {};}
};
var _auditLogTotal=0,_auditLogOffset=0,_auditLogLimit=50;
"""

REGISTER = {
    "complete": True, "customer_output_ready": False,
    "open_blocking_fields": [{"key": "controller.name", "label": "Verantwortliche Firma (Name)"}],
}
FIELDS = [
    {"key": "controller.name", "label": "Verantwortliche Firma (Name)", "blocking": "customer_output",
     "status": "OPEN", "value": None, "revision": 0},
    {"key": "egress.mail.smtp.guarantee", "label": "Garantie E-Mail-Anbieter", "blocking": "channel",
     "status": "CONFIRMED", "value": "TESTWERT nur Schweiz", "revision": 2},
]
REQUESTS = [{
    "id": "sr-1", "client_id": "c-1", "request_type": "ACCESS", "status": "RECEIVED", "received_at": "2026-10-01T00:00:00Z",
    "effective_due_at": "2026-10-31", "overdue": True, "days_remaining": -11, "decision": None,
}]
GATE = {"blocked": True, "open_incidents": 1, "notification_target_hours": None,
        "escalation_contact": {"status": "OPEN", "value": None},
        "findings": [{"reference": "INC-1", "message": "Hohes Risiko ohne Meldeentscheid an den EDOEB",
                      "blocking": True, "hours_since_discovery": 3.0}]}
INCIDENTS = [{"id": "i-1", "reference": "INC-1", "status": "ASSESSED", "incident_type": "CONFIDENTIALITY",
              "discovered_at": "2026-11-11T08:00:00Z", "description": "Testvorfall", "risk_level": "HIGH",
              "notification_decision": None, "close_problems": ["Meldeentscheid fehlt"]}]
EGRESS = {"runtime": {"active": True, "channels": [
    {"id": "market_data.stooq", "class": "market_data", "hosts": ["stooq.com"], "personal_data": False,
     "configured": True, "allowed_now": True, "owner_confirmation_required": False, "owner_confirmed": False},
    {"id": "mail.smtp", "class": "mail", "hosts": ["smtp.example"], "personal_data": True,
     "configured": True, "allowed_now": False, "owner_confirmation_required": True, "owner_confirmed": False,
     "approved": True, "owner_block": "EGRESS_GUARANTEE_MISSING"},
], "recent_blocked": [{"at": "2026-11-11T09:00:00Z", "host": "tracker.invalid",
                       "reason_code": "EGRESS_DESTINATION_DENIED"}]}}


def _run(script: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    code = HARNESS + MODULE_PATH.read_text(encoding="utf-8") + "\n" + (
        "(async function(){\n" + script
        + "\nconsole.log(JSON.stringify({calls:calls,DOM:Object.keys(DOM).reduce(function(a,k){"
        "a[k]={innerHTML:DOM[k].innerHTML,attrs:DOM[k].attrs};return a;},{})}));})()"
        + ".catch(function(e){console.error(e&&e.stack||e);process.exit(1);});"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(code)
        path = handle.name
    out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _load_script() -> str:
    responses = {
        "/privacy/processing-register": REGISTER, "/privacy/owner-fields": FIELDS,
        "/privacy/subject-requests": REQUESTS, "/privacy/incidents": INCIDENTS, "/privacy/incidents/gate": GATE,
        "/privacy/egress-manifest": EGRESS,
        "/clients": [{"id": "c-1", "first_name": "Erika", "last_name": "Beispiel", "client_number": "C-1"}],
    }
    return "".join(f"RESP[{json.dumps(k)}]={json.dumps(v)};" for k, v in responses.items()) + "await loadPrivacyGovernance();"


def test_mounts_admin_section_without_monolith_markup():
    dom = _run("")["DOM"]
    assert "asec-privacy-gov" in dom and "sec-privacy-gov" in dom
    raw = MONOLITH_PATH.read_text(encoding="utf-8")
    assert "sec-privacy-gov" not in raw
    assert raw.count('<script src="./privacy-governance.js"></script>') == 1


def test_panel_shows_blocking_state_owner_fields_without_prefill_and_overdue_request():
    html = _run(_load_script())["DOM"]["sec-privacy-gov"]["innerHTML"]
    assert "gesperrt (1 Angaben offen)" in html
    assert 'id="pg-of-0" value=""' in html  # offenes Feld ohne Vorbelegung
    assert 'id="pg-of-1" value="TESTWERT nur Schweiz"' in html
    assert "Pflicht (Auskunft)" in html and "Pflicht für Kanal" in html
    assert "überfällig" in html and "Erika Beispiel" in html
    assert "Meldepflicht offen" in html and 'data-blocked="1"' in html
    assert "An EDÖB melden" in html and "Keine Meldung" not in html  # hohes Risiko: nur melden
    assert "gesperrt: EGRESS_GUARANTEE_MISSING" in html and "EGRESS_DESTINATION_DENIED" in html
    assert "Verzeichnis freigeben" in html and "Manifest freigeben" in html
    assert "Rechtsberatung" in html


def test_saving_an_owner_field_puts_the_value():
    result = _run(_load_script() + "DOM['pg-of-0']={value:'TESTWERT Firma'};await savePrivacyOwnerField(0);")
    assert result["calls"]["puts"] == [["/privacy/owner-fields/controller.name", {"value": "TESTWERT Firma"}]]


def test_empty_owner_value_is_not_sent():
    result = _run(_load_script() + "DOM['pg-of-0']={value:'  '};await savePrivacyOwnerField(0);")
    assert result["calls"]["puts"] == []
    assert result["calls"]["notices"][-1]["level"] == "error"


def test_opening_a_request_requires_client_type_and_channel():
    result = _run(_load_script() + "await openSubjectRequest();")
    assert result["calls"]["posts"] == []
    result = _run(_load_script()
                  + "DOM['pg-new-client']={value:'c-1'};DOM['pg-new-type']={value:'ACCESS'};"
                  + "DOM['pg-new-received']={value:'2026-11-11'};DOM['pg-new-channel']={value:'LETTER'};"
                  + "await openSubjectRequest();")
    assert result["calls"]["posts"][0] == ["/privacy/subject-requests", {
        "client_id": "c-1", "request_type": "ACCESS", "received_at": "2026-11-11", "received_channel": "LETTER"}]


def test_audit_pagination_moved_out_of_the_monolith():
    bundle = read_monolith_bundle()
    assert bundle.count("function renderAuditLogPagination(") == 1
    assert "function renderAuditLogPagination(" not in MONOLITH_PATH.read_text(encoding="utf-8")
    result = _run("_auditLogTotal=120;_auditLogOffset=50;var c=mkEl('div','pg');DOM['pg']=c;renderAuditLogPagination(c);")
    assert "Einträge 51–100 von 120" in result["DOM"]["pg"]["innerHTML"]



def test_approve_buttons_post_new_versions():
    result = _run(_load_script() + "await approvePrivacyArtifact('processing-register');"
                  + "await approvePrivacyArtifact('egress-manifest');")
    assert result["calls"]["posts"] == [["/privacy/processing-register/approve", {"keys": []}],
                                        ["/privacy/egress-manifest/approve", {"keys": []}]]
