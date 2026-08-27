"""Sprint U-FINMA-2.1 — Endpoint-Tests fuer Beratungsprotokoll-API.

Deckt:
- POST: Pflichtfeld-Validation (description >= 30, topics >= 1, channel-enum, …)
- POST: Hash + retain_until werden korrekt gesetzt
- PUT: Update erzeugt neue Version, altes superseded
- PUT: Doppel-Update auf superseded → 409
- GET single: setzt last_read_at + last_read_by
- GET list: nur aktive (non-superseded) Köpfe
- GET list ?include_history=true: alle Versionen
- Audit-Log-Eintrag bei Create + Update
- 404 wenn unbekanntes Mandat
"""
from __future__ import annotations

import json
import sys
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
from models.profiling import SuitabilityCheck  # noqa: E402
from models.review import (  # noqa: E402
    AdvisoryLog, AuditLog, ConflictOfInterestDisclosure, ContractDocument,
    ReviewTrigger,
)
from models.users import User  # noqa: E402
from services.advisory_log_integrity import (  # noqa: E402
    compute_integrity_hash,
    verify_integrity_hash,
)
from services.auth import get_current_user, require_advisor  # noqa: E402

_NOW = "2026-05-28T14:00:00.000Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'advisory_log_endpoints.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed(session) -> tuple[User, Mandate]:
    advisor = User(
        id=str(uuid.uuid4()),
        username=f"adv-{uuid.uuid4().hex[:6]}",
        password_hash="h",
        full_name="Anna Beispiel",
        role="advisor",
        is_active=1,
        created_at=_NOW,
        updated_at=_NOW,
    )
    client = Client(
        id=str(uuid.uuid4()),
        client_number=f"C-{uuid.uuid4().hex[:6]}",
        first_name="Daniel",
        last_name="Beispiel",
        advisor_id=advisor.id,
        country_of_residence="CH",
        created_at=_NOW,
        updated_at=_NOW,
    )
    mandate = Mandate(
        id=str(uuid.uuid4()),
        client_id=client.id,
        mandate_number=f"M-{uuid.uuid4().hex[:6]}",
        mandate_type="Anlageberatung",
        opened_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add_all([advisor, client, mandate])
    session.commit()
    return advisor, mandate


def _seed_other_mandate(session, advisor: User) -> Mandate:
    """Zweites, unabhaengiges Mandat -- fuer TEN-COMP-002 Cross-Mandate-Tests."""
    other_client = Client(
        id=str(uuid.uuid4()),
        client_number=f"C-{uuid.uuid4().hex[:6]}",
        first_name="Fremd",
        last_name="Mandant",
        advisor_id=advisor.id,
        country_of_residence="CH",
        created_at=_NOW,
        updated_at=_NOW,
    )
    other_mandate = Mandate(
        id=str(uuid.uuid4()),
        client_id=other_client.id,
        mandate_number=f"M-{uuid.uuid4().hex[:6]}",
        mandate_type="Anlageberatung",
        opened_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add_all([other_client, other_mandate])
    session.commit()
    return other_mandate


def _make_trigger(session, mandate: Mandate) -> ReviewTrigger:
    trigger = ReviewTrigger(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        trigger_type="Drift",
        trigger_name="SAA-Abweichung",
        status="Aktiv",
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(trigger)
    session.commit()
    return trigger


def _make_document(session, mandate: Mandate, advisor: User) -> ContractDocument:
    document = ContractDocument(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        document_type="Vertrag",
        title="Beratungsvertrag",
        created_by=advisor.id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(document)
    session.commit()
    return document


def _make_disclosure(session, mandate: Mandate, advisor: User) -> ConflictOfInterestDisclosure:
    disclosure = ConflictOfInterestDisclosure(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        conflict_type="Retrozession",
        description="Vertriebsentschaedigung des Produktanbieters.",
        disclosed_by=advisor.id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(disclosure)
    session.commit()
    return disclosure


def _make_suitability_check(session, mandate: Mandate, advisor: User) -> SuitabilityCheck:
    check = SuitabilityCheck(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        client_id=mandate.client_id,
        duty_type="Angemessenheit",
        result="Geeignet",
        checked_by=advisor.id,
        checked_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(check)
    session.commit()
    return check


@pytest.fixture()
def http_client(session_factory):
    SF = session_factory
    session = SF()
    advisor, mandate = _seed(session)

    def _db_dep():
        try:
            yield session
        finally:
            pass

    def _user_dep():
        return advisor

    app.dependency_overrides[get_db] = _db_dep
    app.dependency_overrides[get_current_user] = _user_dep
    app.dependency_overrides[require_advisor] = _user_dep
    try:
        yield TestClient(app), advisor, mandate, session
    finally:
        app.dependency_overrides.clear()
        session.close()


def _valid_payload() -> dict:
    return {
        "entry_type": "Jahresreview",
        "title": "Jahresreview Mai 2026",
        "description": "SAA besprochen, Risiko diskutiert, Allokation angepasst.",
        "decision": "Strategie angepasst",
        "entry_datetime": "2026-05-28T14:00:00.000Z",
        "duration_minutes": 60,
        "communication_channel": "persoenlich",
        "language": "de",
        "location": "Buero Zuerich",
        "participants": [
            {"role": "client", "name": "Daniel Beispiel"},
        ],
        "topics": ["Strategic Asset Allocation", "Risikoprofil"],
        "risk_warnings_given": ["Marktrisiko", "Fremdwährungsrisiko"],
        "cost_disclosure_given": True,
        "status": "Empfohlen",
    }


# ---------------------------------------------------------------------------
# POST — Pflichtfeld-Validation
# ---------------------------------------------------------------------------

def test_post_with_valid_payload_creates_entry(http_client):
    client, advisor, mandate, session = http_client
    resp = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=_valid_payload(),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["entry_type"] == "Jahresreview"
    assert body["description"].startswith("SAA besprochen")
    assert body["integrity_hash"] is not None
    assert len(body["integrity_hash"]) == 64
    assert body["retain_until"] == "2036-05-28"
    assert body["version"] == 1
    assert body["topics"] == ["Strategic Asset Allocation", "Risikoprofil"]
    assert body["risk_warnings_given"] == ["Marktrisiko", "Fremdwährungsrisiko"]
    assert body["cost_disclosure_given"] == 1
    assert body["communication_channel"] == "persoenlich"


def test_post_rejects_description_too_short(http_client):
    client, _, mandate, _ = http_client
    payload = _valid_payload()
    payload["description"] = "Kurz."  # 6 Zeichen
    resp = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=payload,
    )
    assert resp.status_code == 422


def test_post_rejects_missing_topics(http_client):
    client, _, mandate, _ = http_client
    payload = _valid_payload()
    payload["topics"] = []
    resp = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=payload,
    )
    assert resp.status_code == 422


def test_post_rejects_unknown_channel(http_client):
    client, _, mandate, _ = http_client
    payload = _valid_payload()
    payload["communication_channel"] = "telegramm"
    resp = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=payload,
    )
    assert resp.status_code == 422


def test_post_rejects_duration_out_of_range(http_client):
    client, _, mandate, _ = http_client
    payload = _valid_payload()
    payload["duration_minutes"] = 700  # > 600
    resp = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=payload,
    )
    assert resp.status_code == 422


def test_post_requires_decision_when_status_advanced(http_client):
    """Status != Empfohlen → decision Pflicht."""
    client, _, mandate, _ = http_client
    payload = _valid_payload()
    payload["status"] = "Beschlossen"
    payload["decision"] = None
    resp = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=payload,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST — Integrity-Hash + retain_until persistiert + Audit-Log
# ---------------------------------------------------------------------------

def test_post_persists_integrity_hash_correctly(http_client):
    client, _, mandate, session = http_client
    resp = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=_valid_payload(),
    )
    body = resp.json()
    entry_id = body["id"]
    saved = session.query(AdvisoryLog).filter_by(id=entry_id).one()
    assert saved.integrity_hash == body["integrity_hash"]
    # Hash deterministisch verifizierbar
    from services.advisory_log_service import build_hash_payload

    recomputed = compute_integrity_hash(payload=build_hash_payload(saved))
    assert recomputed == saved.integrity_hash


def test_post_writes_audit_log_entry(http_client):
    client, advisor, mandate, session = http_client
    client.post(
        f"/mandates/{mandate.id}/advisory-log", json=_valid_payload(),
    )
    audits = (
        session.query(AuditLog)
        .filter_by(table_name="advisory_log", action="CREATE")
        .all()
    )
    assert len(audits) == 1
    assert audits[0].user_id == advisor.id
    assert audits[0].mandate_id == mandate.id


# ---------------------------------------------------------------------------
# PUT — Versions-Geschichte
# ---------------------------------------------------------------------------

def test_put_creates_new_version_marks_old_as_superseded(http_client):
    client, _, mandate, session = http_client
    create_resp = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=_valid_payload(),
    )
    log_id = create_resp.json()["id"]

    put_resp = client.put(
        f"/mandates/{mandate.id}/advisory-log/{log_id}",
        json={"description": "Korrigiert: SAA neu beraten und finalisiert."},
    )
    assert put_resp.status_code == 200
    new_body = put_resp.json()
    assert new_body["id"] != log_id
    assert new_body["version"] == 2
    assert new_body["supersedes_id"] == log_id
    assert new_body["description"].startswith("Korrigiert:")
    assert new_body["integrity_hash"] != create_resp.json()["integrity_hash"]

    # Vorgänger ist superseded
    old = session.query(AdvisoryLog).filter_by(id=log_id).one()
    assert old.superseded_by_id == new_body["id"]


def test_put_on_superseded_returns_409(http_client):
    client, _, mandate, _ = http_client
    log_id = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=_valid_payload(),
    ).json()["id"]
    client.put(
        f"/mandates/{mandate.id}/advisory-log/{log_id}",
        json={"description": "Erstes Update, neue Version entsteht."},
    )
    # Zweites Update auf der ALTEN ID -> 409
    second = client.put(
        f"/mandates/{mandate.id}/advisory-log/{log_id}",
        json={"description": "Zweites Update sollte abgelehnt werden."},
    )
    assert second.status_code == 409


def test_put_rejects_invalid_status_transition(http_client):
    client, _, mandate, _ = http_client
    log_id = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=_valid_payload(),
    ).json()["id"]
    # Empfohlen → Umgesetzt ist NICHT erlaubt (nur Empfohlen→Beschlossen oder Abgelehnt)
    resp = client.put(
        f"/mandates/{mandate.id}/advisory-log/{log_id}",
        json={"status": "Umgesetzt"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET single — Read-Audit
# ---------------------------------------------------------------------------

def test_get_single_sets_last_read_at(http_client):
    client, advisor, mandate, session = http_client
    log_id = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=_valid_payload(),
    ).json()["id"]
    # Pre-fetch: last_read sind None
    before = session.query(AdvisoryLog).filter_by(id=log_id).one()
    assert before.last_read_at is None
    assert before.last_read_by is None

    get_resp = client.get(f"/mandates/{mandate.id}/advisory-log/{log_id}")
    assert get_resp.status_code == 200

    session.expire_all()
    after = session.query(AdvisoryLog).filter_by(id=log_id).one()
    assert after.last_read_at is not None
    assert after.last_read_by == advisor.id


def test_get_unknown_log_returns_404(http_client):
    client, _, mandate, _ = http_client
    resp = client.get(f"/mandates/{mandate.id}/advisory-log/non-existent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET list — Default vs. ?include_history=true
# ---------------------------------------------------------------------------

def test_get_list_returns_only_current_versions_by_default(http_client):
    client, _, mandate, _ = http_client
    log_id = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=_valid_payload(),
    ).json()["id"]
    client.put(
        f"/mandates/{mandate.id}/advisory-log/{log_id}",
        json={"description": "Update — alte Version wird superseded."},
    )
    listing = client.get(f"/mandates/{mandate.id}/advisory-log").json()
    assert len(listing) == 1
    assert listing[0]["version"] == 2


def test_get_list_with_include_history_returns_all_versions(http_client):
    client, _, mandate, _ = http_client
    log_id = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=_valid_payload(),
    ).json()["id"]
    client.put(
        f"/mandates/{mandate.id}/advisory-log/{log_id}",
        json={"description": "Update — alte Version wird superseded."},
    )
    listing = client.get(
        f"/mandates/{mandate.id}/advisory-log?include_history=true",
    ).json()
    assert len(listing) == 2
    versions = sorted(e["version"] for e in listing)
    assert versions == [1, 2]


# ---------------------------------------------------------------------------
# Tamper-Detection via integrity_hash
# ---------------------------------------------------------------------------

def test_tampering_description_invalidates_hash(http_client):
    client, _, mandate, session = http_client
    log_id = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=_valid_payload(),
    ).json()["id"]
    entry = session.query(AdvisoryLog).filter_by(id=log_id).one()
    original_hash = entry.integrity_hash

    # Tamper direkt in DB
    entry.description = "Manipulierter Inhalt nach Speicherung."
    session.commit()
    session.expire_all()
    tampered = session.query(AdvisoryLog).filter_by(id=log_id).one()
    from services.advisory_log_service import build_hash_payload

    assert verify_integrity_hash(
        payload=build_hash_payload(tampered), expected_hash=original_hash
    ) is False


# ---------------------------------------------------------------------------
# Mega-Audit (2026-08-04): verify_integrity_hash() wurde seit U-FINMA-2.1 nur
# beim Schreiben berechnet, aber NIE beim Lesen tatsaechlich aufgerufen (nur
# in Tests wie oben) -- der Manipulationsschutz existierte nur auf dem
# Papier. serialize_response() liefert jetzt ein `integrity_verified`-Feld,
# das bei jedem GET tatsaechlich geprueft wird.
# ---------------------------------------------------------------------------

def test_get_single_reports_integrity_verified_true_for_untampered_entry(http_client):
    client, _, mandate, _session = http_client
    log_id = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=_valid_payload(),
    ).json()["id"]
    body = client.get(f"/mandates/{mandate.id}/advisory-log/{log_id}").json()
    assert body["integrity_verified"] is True


def test_get_single_reports_integrity_verified_false_for_tampered_entry(http_client):
    client, _, mandate, session = http_client
    log_id = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=_valid_payload(),
    ).json()["id"]

    entry = session.query(AdvisoryLog).filter_by(id=log_id).one()
    entry.description = "Manipulierter Inhalt nach Speicherung, Hash passt nicht mehr."
    session.commit()

    body = client.get(f"/mandates/{mandate.id}/advisory-log/{log_id}").json()
    assert body["integrity_verified"] is False


def test_get_single_reports_integrity_verified_none_for_legacy_entry_without_hash(http_client):
    """Eintraege von vor U-FINMA-2.1 haben integrity_hash=None -- das ist
    KEIN Manipulationsverdacht, sondern "nichts zu verifizieren"."""
    client, _, mandate, session = http_client
    log_id = client.post(
        f"/mandates/{mandate.id}/advisory-log", json=_valid_payload(),
    ).json()["id"]

    entry = session.query(AdvisoryLog).filter_by(id=log_id).one()
    entry.integrity_hash = None
    session.commit()

    body = client.get(f"/mandates/{mandate.id}/advisory-log/{log_id}").json()
    assert body["integrity_verified"] is None


def test_get_list_also_reports_integrity_verified(http_client):
    client, _, mandate, _session = http_client
    client.post(f"/mandates/{mandate.id}/advisory-log", json=_valid_payload())
    listing = client.get(f"/mandates/{mandate.id}/advisory-log").json()
    assert len(listing) == 1
    assert listing[0]["integrity_verified"] is True


# ---------------------------------------------------------------------------
# TEN-COMP-002 (Codex-Audit 2026-08-27): Evidence-Anker (trigger_id,
# document_id, conflict_disclosure_ids, suitability_check_id) muessen zum
# SELBEN Mandat gehoeren wie das Beratungsprotokoll -- sonst signiert der
# Integrity-Hash ein Beweis-Buendel, das aus einem fremden Mandat stammt.
# Nur recommendation_run_id war bisher geprueft; die anderen vier liefen
# ungeprueft durch. Diese Tests decken je einen negativen Fall (fremdes
# Mandat -> 404) plus einen positiven Regressionstest (gueltige, gleiche
# Mandats-IDs funktionieren weiterhin) ab.
# ---------------------------------------------------------------------------

def test_post_rejects_trigger_id_from_other_mandate(http_client):
    client, advisor, mandate, session = http_client
    other_mandate = _seed_other_mandate(session, advisor)
    foreign_trigger = _make_trigger(session, other_mandate)

    payload = _valid_payload()
    payload["trigger_id"] = foreign_trigger.id
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=payload)
    assert resp.status_code == 404


def test_post_accepts_trigger_id_from_same_mandate(http_client):
    client, advisor, mandate, session = http_client
    trigger = _make_trigger(session, mandate)

    payload = _valid_payload()
    payload["trigger_id"] = trigger.id
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["trigger_id"] == trigger.id


def test_post_rejects_document_id_from_other_mandate(http_client):
    client, advisor, mandate, session = http_client
    other_mandate = _seed_other_mandate(session, advisor)
    foreign_document = _make_document(session, other_mandate, advisor)

    payload = _valid_payload()
    payload["document_id"] = foreign_document.id
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=payload)
    assert resp.status_code == 404


def test_post_accepts_document_id_from_same_mandate(http_client):
    client, advisor, mandate, session = http_client
    document = _make_document(session, mandate, advisor)

    payload = _valid_payload()
    payload["document_id"] = document.id
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["document_id"] == document.id


def test_post_rejects_conflict_disclosure_id_from_other_mandate(http_client):
    client, advisor, mandate, session = http_client
    other_mandate = _seed_other_mandate(session, advisor)
    foreign_disclosure = _make_disclosure(session, other_mandate, advisor)

    payload = _valid_payload()
    payload["conflict_disclosure_ids"] = [foreign_disclosure.id]
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=payload)
    assert resp.status_code == 404


def test_post_rejects_one_foreign_id_among_valid_conflict_disclosure_ids(http_client):
    """Auch wenn nur EINE von mehreren IDs fremd ist, muss der ganze Request
    scheitern -- keine Teilvalidierung."""
    client, advisor, mandate, session = http_client
    own_disclosure = _make_disclosure(session, mandate, advisor)
    other_mandate = _seed_other_mandate(session, advisor)
    foreign_disclosure = _make_disclosure(session, other_mandate, advisor)

    payload = _valid_payload()
    payload["conflict_disclosure_ids"] = [own_disclosure.id, foreign_disclosure.id]
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=payload)
    assert resp.status_code == 404


def test_post_accepts_conflict_disclosure_ids_from_same_mandate(http_client):
    client, advisor, mandate, session = http_client
    disclosure = _make_disclosure(session, mandate, advisor)

    payload = _valid_payload()
    payload["conflict_disclosure_ids"] = [disclosure.id]
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["conflict_disclosure_ids"] == [disclosure.id]


def test_post_rejects_suitability_check_id_from_other_mandate(http_client):
    client, advisor, mandate, session = http_client
    other_mandate = _seed_other_mandate(session, advisor)
    foreign_check = _make_suitability_check(session, other_mandate, advisor)

    payload = _valid_payload()
    payload["suitability_check_id"] = foreign_check.id
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=payload)
    assert resp.status_code == 404


def test_post_accepts_suitability_check_id_from_same_mandate(http_client):
    client, advisor, mandate, session = http_client
    check = _make_suitability_check(session, mandate, advisor)

    payload = _valid_payload()
    payload["suitability_check_id"] = check.id
    resp = client.post(f"/mandates/{mandate.id}/advisory-log", json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["suitability_check_id"] == check.id
