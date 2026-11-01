"""ADVISORY-LOG-FINMA-FIELDS (AUDIT-FIX 2026-11-01): Monolith-Beratungsprotokoll
sendet die FINMA-Pflichtfelder statt 422 -- ohne erfundenen Inhalt.

Befund (develop 4282c807): seit U-FINMA-2.1 (#99) verlangt
``schemas/review.py::AdvisoryLogCreate`` u. a. ``entry_datetime``,
``duration_minutes``, ``communication_channel``, ``topics`` (>=1, je >=3
Zeichen), ``cost_disclosure_given`` und ``description`` >= 30 Zeichen. Drei
Monolith-Aufrufer von ``POST /mandates/{id}/advisory-log`` sendeten diese
Felder nie:

- ``saveAdvisoryLogEntry`` (Formular "Protokolleintrag"),
- ``runtimeProtokolliereEreignis`` (Ereignis-Erfassung; zusaetzlich
  ``entry_type='Zielaenderung'`` statt ``'Zieländerung'``),
- ``documentDecisionTemplate`` (Entscheidungsvorlage Drift).

Jeder Aufruf endete in 422 ("Field required | Field required | ...").

Teil 1 haelt die heutigen (alten) Payloads als Beleg fest: 422, Schema wird
NICHT gelockert. Teil 2 fuehrt den ECHTEN Payload-Builder des Monolithen in
Node aus und schickt dessen Ergebnis durch die Produktions-API (201). Teil 3
prueft, dass der Builder nichts auffuellt und fehlende Pflichtangaben als
Fehler meldet. Teil 4 ist die Spiegel-Fixture (laeuft auch ohne Node) und
Teil 5 die Verdrahtung der drei Aufrufer.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from main import app  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import ReviewTrigger  # noqa: E402
from models.users import User  # noqa: E402
from schemas.review import AdvisoryLogCreate  # noqa: E402
from services.auth import get_current_user, require_advisor  # noqa: E402

REPO_ROOT = BACKEND_ROOT.parent
MONOLITH = REPO_ROOT / "ares-desktop" / "frontend" / "ares.html"
# Builder/Formular-Logik ausgelagert (Monolith-Budget), klassisches Skript.
MODULE = REPO_ROOT / "ares-desktop" / "frontend" / "advisory-log-finma.js"
PACKAGE_JSON = REPO_ROOT / "ares-desktop" / "package.json"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "monolith_advisory_log_payload.json"
NODE = shutil.which("node")
_NOW = "2026-11-01T09:00:00.000Z"

needs_node = pytest.mark.skipif(NODE is None, reason="node nicht verfuegbar")


# ---------------------------------------------------------------------------
# Isolierte DB + App (kein Lifespan, keine Live-DB)
# ---------------------------------------------------------------------------


@pytest.fixture()
def api(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'monolith_advisory_log.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SF()
    advisor = User(
        id=str(uuid.uuid4()), username=f"adv-{uuid.uuid4().hex[:6]}", password_hash="h",
        full_name="Anna Beispiel", role="advisor", is_active=1,
        created_at=_NOW, updated_at=_NOW,
    )
    client = Client(
        id=str(uuid.uuid4()), client_number=f"C-{uuid.uuid4().hex[:6]}",
        first_name="Daniel", last_name="Beispiel", advisor_id=advisor.id,
        country_of_residence="CH", created_at=_NOW, updated_at=_NOW,
    )
    mandate = Mandate(
        id=str(uuid.uuid4()), client_id=client.id, mandate_number=f"M-{uuid.uuid4().hex[:6]}",
        mandate_type="Anlageberatung", opened_at=_NOW, created_at=_NOW, updated_at=_NOW,
    )
    session.add_all([advisor, client, mandate])
    session.commit()

    def _db_dep():
        yield session

    app.dependency_overrides[get_db] = _db_dep
    app.dependency_overrides[get_current_user] = lambda: advisor
    app.dependency_overrides[require_advisor] = lambda: advisor
    try:
        yield TestClient(app), mandate, session
    finally:
        app.dependency_overrides.clear()
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _trigger(session, mandate, trigger_type="Markt", name="Aktien", status="Ausgelöst") -> ReviewTrigger:
    # Resolve ist nur fuer tatsaechlich ausgeloeste Trigger zulaessig (409 sonst).
    trigger = ReviewTrigger(
        id=str(uuid.uuid4()), mandate_id=mandate.id, trigger_type=trigger_type,
        trigger_name=name, status=status, created_at=_NOW, updated_at=_NOW,
    )
    session.add(trigger)
    session.commit()
    return trigger


# ---------------------------------------------------------------------------
# Echte Monolith-Funktionen in Node
# ---------------------------------------------------------------------------

_FUNCTIONS = (
    "function parseAdvisoryLogTopics(",
    "function advisoryLogEntryDatetimeIso(",
    "function buildAdvisoryLogCreatePayload(",
    "function buildEventAdvisoryLogPrefill(",
    "function buildDecisionTemplateAdvisoryLogPrefill(",
    "function advisoryDecisionToTriggerDecision(",
    "function normalizeAdvisoryDecision(",
    "function inferAdvisoryEntryType(",
)
_VARS = ("var ADVISORY_LOG_ENTRY_TYPES=", "var ADVISORY_LOG_CHANNELS=")


def _src() -> str:
    # Monolith + ausgelagertes Modul: jede Funktion existiert genau einmal.
    return MONOLITH.read_text(encoding="utf-8") + "\n" + MODULE.read_text(encoding="utf-8")


def _function(src: str, signature: str) -> str:
    assert src.count(signature) == 1, signature
    start = src.index(signature)
    i = src.index("{", start + len(signature) - 1)
    depth, j = 1, i + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
    return src[start:j]


def _var(src: str, prefix: str) -> str:
    start = src.index(prefix)
    return src[start:src.index(";\n", start) + 1]


def _node(body: str):
    src = _src()
    script = "\n".join(_var(src, v) for v in _VARS) + "\n"
    script += "\n".join(_function(src, f) for f in _FUNCTIONS) + "\n" + body
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.js"
        path.write_text(script, encoding="utf-8")
        env = dict(os.environ, TZ="Europe/Zurich")
        proc = subprocess.run(
            [NODE, str(path)], capture_output=True, text=True, encoding="utf-8",
            timeout=60, env=env,
        )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _build(inp: dict) -> dict:
    return _node("console.log(JSON.stringify(buildAdvisoryLogCreatePayload(" + json.dumps(inp) + ")));")


# Formular "Protokolleintrag", wie saveAdvisoryLogEntry die Eingaben liest.
FORM_INPUT = {
    "entryType": "Jahresreview",
    "title": "Jahresreview 2026",
    "description": "Kunde bestaetigt Ziele und Risikobereitschaft, SAA unveraendert beibehalten.",
    "contextNotes": [],
    "decision": "Keine Transaktion",
    "triggerId": None,
    "recommendationRunId": None,
    "entryDate": "2026-11-01",
    "entryTime": "10:15",
    "durationMinutes": "45",
    "channel": "persoenlich",
    "topics": "Strategic Asset Allocation\nRisikoprofil",
    "costDisclosureGiven": False,
}


# ---------------------------------------------------------------------------
# Teil 1: Beleg -- die heutigen Monolith-Payloads werden abgelehnt
# ---------------------------------------------------------------------------

LEGACY_PAYLOADS = {
    # saveAdvisoryLogEntry (develop 4282c807)
    "formular": {
        "entry_type": "Jahresreview", "title": "Jahresreview 2026",
        "description": "Kunde bestaetigt Ziele und Risikobereitschaft, SAA unveraendert.",
        "decision": "Keine Transaktion", "trigger_id": None,
        "entry_date": "2026-11-01", "recommendation_run_id": None,
    },
    # runtimeProtokolliereEreignis
    "ereignis": {
        "entry_type": "Ereignis-Reaktion", "title": "Ereignis: Pensionierung / Ruhestand",
        "description": "Pensionierung per Ende Jahr | Massnahme: Review-Termin auslösen",
        "decision": None, "entry_date": "2026-11-01",
    },
    "ereignis_ziel": {
        "entry_type": "Zielaenderung", "title": "Ereignis: Zielaenderung",
        "description": "Massnahme: Review-Termin auslösen", "decision": None,
        "entry_date": "2026-11-01",
    },
    # documentDecisionTemplate
    "vorlage": {
        "entry_type": "Drift-Entscheid",
        "title": "Entscheidungsvorlage – Option A – Zuflüsse umlenken",
        "description": "Nächste Zuflüsse in defensivere Klassen umlenken. Organische Normalisierung 12–18 Monate.",
        "decision": "Strategie angepasst", "trigger_id": None,
        "recommendation_run_id": None, "entry_date": "2026-11-01",
    },
}


@pytest.mark.parametrize("name", sorted(LEGACY_PAYLOADS))
def test_legacy_monolith_payloads_are_rejected_with_422(api, name):
    client, mandate, _ = api
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=LEGACY_PAYLOADS[name])
    assert resp.status_code == 422, resp.text
    missing = {tuple(e["loc"])[-1] for e in resp.json()["detail"] if e["type"] == "missing"}
    assert {"entry_datetime", "duration_minutes", "communication_channel",
            "topics", "cost_disclosure_given"} <= missing


def test_schema_still_demands_finma_fields():
    """Der Fix lockert das Backend-Schema nicht."""
    required = {n for n, f in AdvisoryLogCreate.model_fields.items() if f.is_required()}
    assert {"entry_type", "title", "description", "entry_datetime", "duration_minutes",
            "communication_channel", "topics", "cost_disclosure_given"} <= required


def test_legacy_trigger_resolve_decisions_were_rejected(api):
    """Nach dem Protokoll wurde der Trigger mit einem Protokoll-Entscheid bzw.
    Vorlagentitel aufgeloest -- ReviewTriggerResolve kennt die nicht (422)."""
    client, mandate, session = api
    trigger = _trigger(session, mandate)
    for decision in ("Keine Transaktion", "Option A – Zuflüsse umlenken"):
        resp = client.put(
            f"/mandates/{mandate.id}/triggers/{trigger.id}/resolve",
            json={"decision": decision, "triggered_notes": "x"},
        )
        assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Teil 2: echter Builder -> Produktions-API (201)
# ---------------------------------------------------------------------------


def _assert_only_schema_fields(payload: dict) -> None:
    # Kompatibel mit extra="forbid" (offener PR #838): keine unbekannten Felder.
    assert set(payload) <= set(AdvisoryLogCreate.model_fields), set(payload) - set(AdvisoryLogCreate.model_fields)


@needs_node
def test_form_payload_from_monolith_builder_is_accepted(api):
    client, mandate, _ = api
    out = _build(FORM_INPUT)
    assert out["ok"] is True, out
    payload = out["payload"]
    _assert_only_schema_fields(payload)
    # Datum 2026-11-01 10:15 Europe/Zurich (CET, UTC+1) -> 09:15Z, Format wie React-Editor
    assert payload["entry_datetime"] == "2026-11-01T09:15:00.000Z"
    assert payload["duration_minutes"] == 45
    assert payload["topics"] == ["Strategic Asset Allocation", "Risikoprofil"]
    assert payload["description"] == FORM_INPUT["description"]
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["communication_channel"] == "persoenlich"
    assert body["cost_disclosure_given"] == 0
    assert body["topics"] == ["Strategic Asset Allocation", "Risikoprofil"]


@needs_node
def test_event_prefill_plus_advisor_input_is_accepted(api):
    """Ereignis-Erfassung: ableitbare Werte aus dem Prefill, den Rest ergaenzt
    der Berater im Formular (hier simuliert) -> 201 mit Thema = Ereignistyp."""
    client, mandate, session = api
    trigger = _trigger(session, mandate, trigger_type="Ereignis", name="Zielaenderung", status="Aktiv")
    prefill = _node(
        "console.log(JSON.stringify(buildEventAdvisoryLogPrefill("
        + json.dumps({
            "type": "Zielaenderung", "eventDate": "2026-10-28",
            "details": "Kunde plant Hauskauf 2028, Liquiditaetsbedarf CHF 300k neu.",
            "action": "goals", "actionLabel": "Ziele anpassen", "triggerId": trigger.id,
        })
        + ")));"
    )
    assert prefill["entryType"] == "Zieländerung"  # vorher 'Zielaenderung' -> 422
    assert prefill["topics"] == ["Zielaenderung"]
    assert prefill["resolveTrigger"] is False  # Review-Trigger bleibt offen
    assert prefill["decision"] is None
    out = _build({
        **FORM_INPUT,
        "entryType": prefill["entryType"], "title": prefill["title"],
        "description": prefill["description"], "contextNotes": prefill["contextNotes"],
        "decision": prefill["decision"], "triggerId": prefill["triggerId"],
        "topics": prefill["topics"], "channel": "telefon", "durationMinutes": "20",
    })
    assert out["ok"] is True, out
    payload = out["payload"]
    _assert_only_schema_fields(payload)
    assert payload["description"] == (
        "Ereignisdatum: 2026-10-28 | Massnahme: Ziele anpassen | "
        "Kunde plant Hauskauf 2028, Liquiditaetsbedarf CHF 300k neu."
    )
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["trigger_id"] == trigger.id


@needs_node
def test_decision_template_prefill_plus_advisor_input_is_accepted_and_resolves(api):
    client, mandate, session = api
    trigger = _trigger(session, mandate)
    prefill = _node(
        "console.log(JSON.stringify(buildDecisionTemplateAdvisoryLogPrefill("
        + json.dumps({
            "title": "Option C – Drift tolerieren",
            "detail": "Drift für ein weiteres Quartal dokumentiert tolerieren.",
            "decision": "Override bestätigt",
        })
        + "," + json.dumps(trigger.id) + ")));"
    )
    assert prefill["description"] == ""  # Vorlagentext ist kein Gespraechsinhalt
    assert prefill["contextNotes"] == ["Vorlage: Drift für ein weiteres Quartal dokumentiert tolerieren."]
    # Ohne eigenen Gespraechsinhalt -> kein Payload (nichts wird aufgefuellt)
    bare = _build({**FORM_INPUT, "entryType": prefill["entryType"], "title": prefill["title"],
                   "description": prefill["description"], "contextNotes": prefill["contextNotes"],
                   "topics": prefill["topics"], "decision": prefill["decision"]})
    assert bare["ok"] is False
    out = _build({
        **FORM_INPUT,
        "entryType": prefill["entryType"], "title": prefill["title"],
        "description": "Kunde akzeptiert Uebergewicht Aktien bewusst, schriftliche Bestaetigung folgt.",
        "contextNotes": prefill["contextNotes"], "decision": prefill["decision"],
        "triggerId": prefill["triggerId"], "topics": prefill["topics"],
    })
    assert out["ok"] is True, out
    payload = out["payload"]
    _assert_only_schema_fields(payload)
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=payload)
    assert resp.status_code == 201, resp.text
    trigger_decision = _node(
        "console.log(JSON.stringify(advisoryDecisionToTriggerDecision(" + json.dumps(payload["decision"]) + ")));"
    )
    resolve = client.put(
        f"/mandates/{mandate.id}/triggers/{trigger.id}/resolve",
        json={"decision": trigger_decision, "triggered_notes": payload["title"]},
    )
    assert resolve.status_code == 200, resolve.text


@needs_node
def test_every_advisory_decision_maps_to_a_valid_trigger_decision(api):
    client, mandate, session = api
    decisions = [None, "Keine Transaktion", "Transaktion empfohlen", "Strategie angepasst",
                 "Profil angepasst", "Override bestätigt", "Kein Handlungsbedarf"]
    mapped = _node(
        "console.log(JSON.stringify(" + json.dumps(decisions)
        + ".map(advisoryDecisionToTriggerDecision)));"
    )
    for decision in mapped:
        trigger = _trigger(session, mandate)
        resp = client.put(
            f"/mandates/{mandate.id}/triggers/{trigger.id}/resolve",
            json={"decision": decision, "triggered_notes": "Review dokumentiert"},
        )
        assert resp.status_code == 200, (decision, resp.text)


# ---------------------------------------------------------------------------
# Teil 3: nichts auffuellen, Pflichtangaben verstaendlich einfordern
# ---------------------------------------------------------------------------


@needs_node
@pytest.mark.parametrize(
    "override, fragment",
    [
        ({"description": "zu kurz"}, "mindestens 30 Zeichen"),
        ({"title": "Ja"}, "mindestens 3 Zeichen"),
        ({"topics": ""}, "Mindestens ein Thema"),
        ({"topics": "AB"}, "Jedes Thema"),
        ({"durationMinutes": ""}, "Dauer"),
        ({"durationMinutes": "0"}, "Dauer"),
        ({"durationMinutes": "601"}, "Dauer"),
        ({"durationMinutes": "12.5"}, "Dauer"),
        ({"channel": ""}, "Kommunikationskanal"),
        ({"channel": "email"}, "Kommunikationskanal"),
        ({"entryTime": ""}, "Uhrzeit"),
        ({"entryDate": "2026-02-30"}, "Uhrzeit"),
        ({"costDisclosureGiven": None}, "Kostenkommunikation"),
        ({"entryType": "Zielaenderung"}, "Eintragstyp"),
    ],
)
def test_builder_reports_missing_mandatory_input_instead_of_padding(override, fragment):
    out = _build({**FORM_INPUT, **override})
    assert out["ok"] is False
    assert out["payload"] is None
    assert any(fragment in e for e in out["errors"]), out["errors"]


@needs_node
def test_context_notes_do_not_count_towards_minimum_length():
    """Kontext ('Massnahme: ...', 'Vorlage: ...', 'Operative Ausprägung: ...')
    darf den eigenen Gespraechsinhalt nicht auf 30 Zeichen auffuellen."""
    out = _build({**FORM_INPUT, "description": "kurz",
                  "contextNotes": ["Massnahme: Review-Termin auslösen", "Vorlage: " + "x" * 80]})
    assert out["ok"] is False


@needs_node
def test_topics_are_trimmed_and_deduplicated_not_invented():
    out = _build({**FORM_INPUT, "topics": " Risikoprofil \n\nrisikoprofil; Steuern \n"})
    assert out["payload"]["topics"] == ["Risikoprofil", "Steuern"]


# ---------------------------------------------------------------------------
# Teil 4: Spiegel-Fixture (laeuft auch ohne Node gegen die API)
# ---------------------------------------------------------------------------


def test_mirror_fixture_payload_is_accepted_by_api(api):
    client, mandate, _ = api
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    _assert_only_schema_fields(payload)
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=payload)
    assert resp.status_code == 201, resp.text


@needs_node
def test_mirror_fixture_equals_monolith_builder_output():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert _build(FORM_INPUT)["payload"] == payload


# ---------------------------------------------------------------------------
# Teil 5: Verdrahtung der drei Aufrufer
# ---------------------------------------------------------------------------


def test_all_monolith_advisory_log_posts_go_through_the_builder():
    src = _src()
    save = _function(src, "async function saveAdvisoryLogEntry(")
    assert "buildAdvisoryLogCreatePayload(" in save
    assert "if(!built.ok)" in save
    assert "advisoryDecisionToTriggerDecision(payload.decision)" in save
    for name in ("async function runtimeProtokolliereEreignis(", "async function documentDecisionTemplate("):
        body = _function(src, name)
        assert "/advisory-log" not in body, name  # kein direkter (unvollstaendiger) POST mehr
        assert "openAdvisoryLogModalPrefilled(" in body, name
    assert "buildEventAdvisoryLogPrefill(" in _function(src, "async function runtimeProtokolliereEreignis(")
    assert "buildDecisionTemplateAdvisoryLogPrefill(" in _function(src, "async function documentDecisionTemplate(")


def test_unsaved_prefilled_entry_is_never_silently_dropped():
    src = _src()
    cleanup = _function(src, "function cleanupModalAfterClose(")
    assert "advisoryLogCloseCheck();" in cleanup
    check = _function(src, "function advisoryLogCloseCheck(")
    assert "pending&&!pending.saved" in check
    assert "showAppWarn(" in check and "durationMs:0" in check
    opener = _function(src, "function openAdvisoryLogModalPrefilled(")
    assert "dataset.locked='1'" in opener  # Backdrop-Klick schliesst nicht still


def test_module_is_loaded_by_monolith_and_packaged():
    html = MONOLITH.read_text(encoding="utf-8")
    assert '<script src="./advisory-log-finma.js"></script>' in html
    assert "frontend/advisory-log-finma.js" in json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["build"]["files"]
    module = MODULE.read_text(encoding="utf-8")
    for name in ("function buildAdvisoryLogCreatePayload(", "async function saveAdvisoryLogEntry(",
                 "function openAdvisoryLogModalPrefilled(", "function advisoryLogCloseCheck("):
        assert name in module and name not in html, name  # verschoben, nicht dupliziert


def test_form_has_the_new_mandatory_inputs():
    src = _src()
    for element_id in ("ne-time", "ne-duration", "ne-channel", "ne-topics", "ne-cost", "ne-entry-type", "ne-context"):
        assert f'id="{element_id}"' in src, element_id
    for channel in ("persoenlich", "video", "telefon", "schriftlich", "hybrid"):
        assert f'<option value="{channel}">' in src


# ---------------------------------------------------------------------------
# Teil 6: echte Formular-Funktionen mit minimalem DOM-Ersatz
# ---------------------------------------------------------------------------

_FLOW_FUNCTIONS = (
    "function getInputValue(", "function setInputValue(", "function setSelectValue(",
    "function setCheckboxValue(", "function getCheckboxValue(", "function showModalFeedback(",
    "function parseApiError(", "function resetAdvisoryLogModal(",
    "function openAdvisoryLogModalPrefilled(", "async function saveAdvisoryLogEntry(",
    "function cleanupModalAfterClose(", "function resetAdvisoryLogFinmaFields(",
    "function advisoryLogCloseCheck(",
)

_FLOW_DOM = r"""
var ELS={};
function el(id,extra){
  var e={id:id,value:'',checked:false,textContent:'',disabled:false,style:{},dataset:{},options:[],
    _cls:{},classList:{add:function(c){e._cls[c]=1;},remove:function(c){delete e._cls[c];}},
    appendChild:function(o){e.options.push(o);}};
  return Object.assign(e,extra||{});
}
['ne-date','ne-time','ne-title','ne-description','ne-duration','ne-channel','ne-topics','ne-cost',
 'ne-entry-type','ne-context','ne-trigger-id','ne-error','btn-ne-save','m-ne','m-ed'].forEach(function(id){ELS[id]=el(id);});
ELS['ne-decision']=el('ne-decision',{options:['Keine Transaktion','Kauf','Verkauf','Umschichtung',''].map(function(v){return {value:v};})});
var document={getElementById:function(id){return ELS[id]||null;},createElement:function(){return {value:'',textContent:''};}};
var CALLS=[],NOTICES=[];
var API={post:async function(p,b){CALLS.push(['POST',p,b]);return {id:'log-1'};},put:async function(p,b){CALLS.push(['PUT',p,b]);return {};}};
function getActiveMandateId(){return 'm-1';}
function isDemoMandateId(){return false;}
var strategyState={recommendation:null};
var currentReviewState={logs:[],triggers:[]};
async function refreshReviewUI(){}
function renderSrImplementationDecision(){}
function showAppWarn(m,o){NOTICES.push(['warn',m,o]);}
function showAppError(m,o){NOTICES.push(['error',m,o]);}
function showAppSuccess(m,o){NOTICES.push(['success',m,o]);}
function cm(id){cleanupModalAfterClose(id);}
var WENT=[];function go(p){WENT.push(p);}
function fill(v){Object.keys(v).forEach(function(k){if(k==='ne-cost')ELS[k].checked=v[k];else ELS[k].value=v[k];});}
function done(extra){setTimeout(function(){console.log(JSON.stringify(Object.assign({calls:CALLS,notices:NOTICES,went:WENT,error:ELS['ne-error'].textContent},extra||{})));},800);}
"""


def _flow(body: str):
    src = _src()
    script = _var(src, "var advisoryLogPrefill=") + "\n"
    script += "\n".join(_function(src, f) for f in _FLOW_FUNCTIONS)
    return _node(_FLOW_DOM + "\n" + script + "\n(async function(){\n" + body + "\n})();")


@needs_node
def test_event_flow_form_posts_valid_payload_and_keeps_review_trigger_open(api):
    client, mandate, session = api
    trigger = _trigger(session, mandate, trigger_type="Ereignis", name="Erbschaft erhalten", status="Aktiv")
    out = _flow(
        "openAdvisoryLogModalPrefilled(buildEventAdvisoryLogPrefill("
        + json.dumps({"type": "Erbschaft erhalten", "eventDate": "2026-10-20", "details": "",
                      "action": "risk", "actionLabel": "Risikoprofil neu prüfen", "triggerId": trigger.id})
        + "));\n"
        "var locked=ELS['m-ne'].dataset.locked;\n"
        "await saveAdvisoryLogEntry();\n"  # ohne Ergaenzung -> kein POST
        "var firstError=ELS['ne-error'].textContent;\n"
        "fill({'ne-description':'Erbschaft CHF 400k erwartet, Kunde will Teil fuer Hypothek-Amortisation verwenden.',"
        "'ne-duration':'30','ne-channel':'video','ne-cost':false});\n"
        "await saveAdvisoryLogEntry();\n"
        "done({locked:locked,firstError:firstError});"
    )
    assert out["locked"] == "1"
    assert "Gesprächsinhalt" in out["firstError"] and "Kommunikationskanal" in out["firstError"]
    posts = [c for c in out["calls"] if c[0] == "POST"]
    assert len(posts) == 1
    assert not [c for c in out["calls"] if c[0] == "PUT"]  # Review-Trigger bleibt offen
    payload = posts[0][2]
    _assert_only_schema_fields(payload)
    assert payload["topics"] == ["Erbschaft erhalten"]
    assert payload["decision"] is None  # kein unterstellter Entscheid
    assert payload["trigger_id"] == trigger.id
    assert out["went"] == ["rp"]
    assert not [n for n in out["notices"] if n[0] == "warn"]
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=payload)
    assert resp.status_code == 201, resp.text


@needs_node
def test_decision_template_flow_resolves_trigger_with_valid_decision(api):
    client, mandate, session = api
    trigger = _trigger(session, mandate)
    out = _flow(
        "openAdvisoryLogModalPrefilled(buildDecisionTemplateAdvisoryLogPrefill("
        + json.dumps({"title": "Option B – Teilverkauf Aktien",
                      "detail": "Teilverkauf Aktien. Sofortige Normalisierung, Steuerfolgen separat prüfen.",
                      "decision": "Transaktion empfohlen"})
        + "," + json.dumps(trigger.id) + "));\n"
        "fill({'ne-description':'Kunde stimmt Teilverkauf zu, Steuerfolgen werden mit Treuhaender geklaert.',"
        "'ne-duration':'40','ne-channel':'persoenlich','ne-cost':true});\n"
        "await saveAdvisoryLogEntry();\n"
        "done();"
    )
    post = next(c for c in out["calls"] if c[0] == "POST")
    put = next(c for c in out["calls"] if c[0] == "PUT")
    assert post[2]["decision"] == "Transaktion empfohlen"
    assert post[2]["entry_type"] == "Drift-Entscheid"
    assert post[2]["description"].startswith("Vorlage: Teilverkauf Aktien.")
    assert put[2]["decision"] == "Massnahme eingeleitet"
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=post[2])
    assert resp.status_code == 201, resp.text
    resolve = client.put(f"/mandates/{mandate.id}/triggers/{trigger.id}/resolve", json=put[2])
    assert resolve.status_code == 200, resolve.text


@needs_node
def test_closing_prefilled_form_without_saving_warns_visibly():
    out = _flow(
        "openAdvisoryLogModalPrefilled(buildEventAdvisoryLogPrefill("
        + json.dumps({"type": "Jobwechsel / Kuendigung", "eventDate": "2026-10-20", "details": "",
                      "action": "review", "actionLabel": "Review-Termin auslösen", "triggerId": "t-1"})
        + "));\n"
        "cm('m-ne');\n"
        "done({locked:ELS['m-ne'].dataset.locked||null,pending:advisoryLogPrefill});"
    )
    assert out["calls"] == []
    warns = [n for n in out["notices"] if n[0] == "warn"]
    assert len(warns) == 1
    assert "NICHT im Beratungsprotokoll erfasst" in warns[0][1]
    assert "Review-Trigger ist angelegt" in warns[0][1]
    assert warns[0][2]["durationMs"] == 0
    assert out["locked"] is None and out["pending"] is None


@needs_node
def test_plain_form_open_decision_is_sent_as_null(api):
    client, mandate, _ = api
    out = _flow(
        "resetAdvisoryLogModal();\n"
        "fill({'ne-title':'Quartalscheck Q4','ne-decision':'',"
        "'ne-description':'Allokation besprochen, Entscheid zur Umschichtung folgt naechste Woche.',"
        "'ne-duration':'25','ne-channel':'telefon','ne-topics':'Allokation','ne-cost':false});\n"
        "await saveAdvisoryLogEntry();\n"
        "done();"
    )
    post = next(c for c in out["calls"] if c[0] == "POST")
    assert post[2]["decision"] is None
    assert post[2]["entry_type"] == "Quartalscheck"
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=post[2])
    assert resp.status_code == 201, resp.text


_PARSE_CHECK_JS = r"""
const fs=require('fs');const vm=require('vm');
const s=fs.readFileSync(process.argv[2],'utf8');
const re=/<script(\s[^>]*)?>([\s\S]*?)<\/script>/g;let m,bad=[];
while((m=re.exec(s))){if(m[1]&&/src=/.test(m[1]))continue;try{new vm.Script(m[2]);}catch(e){bad.push(e.message);}}
console.log(JSON.stringify(bad));
"""


@needs_node
def test_monolith_inline_scripts_still_parse():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "chk.js"
        path.write_text(_PARSE_CHECK_JS, encoding="utf-8")
        proc = subprocess.run([NODE, str(path), str(MONOLITH)], capture_output=True, text=True,
                              encoding="utf-8", timeout=120)
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout) == []
        check = subprocess.run([NODE, "--check", str(MODULE)], capture_output=True, text=True,
                               encoding="utf-8", timeout=60)
    assert check.returncode == 0, check.stderr
