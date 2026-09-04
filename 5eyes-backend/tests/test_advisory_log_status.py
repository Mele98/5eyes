from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.allocation import OptimizerPolicy
from models.clients import Client
from models.mandates import Mandate
from models.review import AdvisoryLog, AuditLog, ContractDocument, RecommendationRun, ReviewTrigger
from models.users import User
from services.auth import get_current_user


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_advisory_log_status.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="user-advisory-log-1",
        username="advisor_review",
        password_hash="h",
        full_name="Advisor Review",
        role="advisor",
        is_active=1,
        created_at="2026-04-04T00:00:00.000Z",
        updated_at="2026-04-04T00:00:00.000Z",
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _seed_review_context(session_factory, advisor_user) -> tuple[str, str]:
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(
            User(
                id=advisor_user.id,
                username=advisor_user.username,
                password_hash=advisor_user.password_hash,
                full_name=advisor_user.full_name,
                role=advisor_user.role,
                is_active=advisor_user.is_active,
                created_at=advisor_user.created_at,
                updated_at=advisor_user.updated_at,
            )
        )
        s.add(
            Client(
                id="client-advisory-log-1",
                client_number="CL-ADVISORY-001",
                salutation="Herr",
                first_name="Andreas",
                last_name="Mueller",
                advisor_id=advisor_user.id,
                household_type="Einzelperson",
                country_of_residence="CH",
                language="DE",
                created_at=now,
                updated_at=now,
            )
        )
        s.add(
            Mandate(
                id="mandate-advisory-log-1",
                client_id="client-advisory-log-1",
                mandate_number="MD-ADVISORY-001",
                mandate_type="Anlageberatung",
                status="Aktiv",
                base_currency="CHF",
                advisory_language="DE",
                opened_at="2026-04-04",
                created_at=now,
                updated_at=now,
            )
        )
        s.add(
            OptimizerPolicy(
                id="policy-advisory-log-1",
                policy_name="Hausmeinung",
                valid_from="2026-01-01",
                created_by=advisor_user.id,
                created_at=now,
                updated_at=now,
            )
        )
        s.add(
            RecommendationRun(
                id="run-advisory-log-1",
                mandate_id="mandate-advisory-log-1",
                client_id="client-advisory-log-1",
                policy_id="policy-advisory-log-1",
                run_type="Strategie",
                created_by=advisor_user.id,
                created_at=now,
                updated_at=now,
            )
        )
        s.commit()
    return "mandate-advisory-log-1", "run-advisory-log-1"


def _create_advisory_entry(auth_client: TestClient, mandate_id: str, **extra):
    # Sprint U-FINMA-2.1: AdvisoryLogCreate verlangt jetzt FIDLEG-Pflichtfelder
    payload = {
        "entry_type": "Jahresreview",
        "title": "Review 2026",
        "description": (
            "Strategie mit Kunde besprochen, Allokation ueberprueft, "
            "naechste Schritte definiert."
        ),
        "decision": "Transaktion empfohlen",
        "entry_datetime": "2026-05-28T14:00:00.000Z",
        "duration_minutes": 60,
        "communication_channel": "persoenlich",
        "language": "de",
        "topics": ["Strategie", "Allokation"],
        "risk_warnings_given": ["Marktrisiko"],
        "cost_disclosure_given": True,
    }
    payload.update(extra)
    return auth_client.post(f"/mandates/{mandate_id}/advisory-log", json=payload)


def test_advisory_log_create_with_run_id(session_factory, auth_client, advisor_user):
    mandate_id, run_id = _seed_review_context(session_factory, advisor_user)

    response = _create_advisory_entry(
        auth_client,
        mandate_id,
        recommendation_run_id=run_id,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["recommendation_run_id"] == run_id
    assert data["status"] == "Empfohlen"

    with session_factory() as s:
        entry = s.query(AdvisoryLog).filter(AdvisoryLog.id == data["id"]).first()
        assert entry is not None
        assert entry.recommendation_run_id == run_id
        assert entry.status == "Empfohlen"


def test_advisory_log_status_transition_empfohlen_to_beschlossen(session_factory, auth_client, advisor_user):
    """U-FINMA-2.1: PUT erzeugt neue Version; Status-Check auf der neuen ID."""
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    create_response = _create_advisory_entry(auth_client, mandate_id)
    entry_id = create_response.json()["id"]

    response = auth_client.put(
        f"/mandates/{mandate_id}/advisory-log/{entry_id}",
        json={"status": "Beschlossen"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "Beschlossen"
    assert data["supersedes_id"] == entry_id

    with session_factory() as s:
        new_entry = s.query(AdvisoryLog).filter(AdvisoryLog.id == data["id"]).first()
        assert new_entry is not None
        assert new_entry.status == "Beschlossen"
        # Alte Version ist superseded
        old = s.query(AdvisoryLog).filter(AdvisoryLog.id == entry_id).first()
        assert old.superseded_by_id == data["id"]


def test_advisory_log_status_transition_beschlossen_to_umgesetzt(session_factory, auth_client, advisor_user):
    """U-FINMA-2.1: zweistufige Versions-Geschichte."""
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    create_response = _create_advisory_entry(
        auth_client,
        mandate_id,
        status="Beschlossen",
    )
    entry_id = create_response.json()["id"]

    response = auth_client.put(
        f"/mandates/{mandate_id}/advisory-log/{entry_id}",
        json={"status": "Umgesetzt"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "Umgesetzt"
    assert data["version"] == 2

    with session_factory() as s:
        new_entry = s.query(AdvisoryLog).filter(AdvisoryLog.id == data["id"]).first()
        assert new_entry is not None
        assert new_entry.status == "Umgesetzt"


def test_advisory_log_status_transition_empfohlen_to_abgelehnt_requires_description(session_factory, auth_client, advisor_user):
    """U-FINMA-2.1: 422 ohne description bei Statuswechsel auf Abgelehnt.
    Da der erste PUT fehlschlägt, ist die Version nicht superseded
    und kann mit zweitem (validen) PUT korrigiert werden."""
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    create_response = _create_advisory_entry(auth_client, mandate_id)
    entry_id = create_response.json()["id"]

    missing_comment = auth_client.put(
        f"/mandates/{mandate_id}/advisory-log/{entry_id}",
        json={"status": "Abgelehnt"},
    )

    assert missing_comment.status_code == 422
    assert "description" in missing_comment.json()["detail"]

    response = auth_client.put(
        f"/mandates/{mandate_id}/advisory-log/{entry_id}",
        json={
            "status": "Abgelehnt",
            "description": "Kunde lehnt Empfehlung nach Rücksprache ab — Risiko zu hoch.",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "Abgelehnt"


def test_advisory_log_status_transition_umgesetzt_to_ueberarbeitung_noetig(session_factory, auth_client, advisor_user):
    """U-FINMA-2.1: dreistufige Versions-Geschichte — PUT folgt jeweils der
    aktuellsten Version-ID."""
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    create_response = _create_advisory_entry(
        auth_client,
        mandate_id,
        status="Beschlossen",
    )
    v1_id = create_response.json()["id"]
    v2 = auth_client.put(
        f"/mandates/{mandate_id}/advisory-log/{v1_id}",
        json={"status": "Umgesetzt"},
    ).json()
    v2_id = v2["id"]

    response = auth_client.put(
        f"/mandates/{mandate_id}/advisory-log/{v2_id}",
        json={
            "status": "Überarbeitung nötig",
            "description": "Umsetzung muss wegen Preisänderung neu geprüft und angepasst werden.",
        },
    )

    assert response.status_code == 200
    v3 = response.json()
    assert v3["status"] == "Überarbeitung nötig"
    assert v3["version"] == 3


def test_resolve_trigger_rolls_recurring_time_trigger_forward(session_factory, auth_client, advisor_user):
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    with session_factory() as s:
        s.add(
            ReviewTrigger(
                id="trigger-recurring-1",
                mandate_id=mandate_id,
                trigger_type="Zeit",
                trigger_name="Jahresreview",
                frequency="jährlich",
                status="Ausgelöst",
                next_due_at="2026-04-01",
                created_at="2026-04-01T00:00:00.000Z",
                updated_at="2026-04-01T00:00:00.000Z",
            )
        )
        s.commit()

    response = auth_client.put(
        f"/mandates/{mandate_id}/triggers/trigger-recurring-1/resolve",
        json={"decision": "Erledigt", "triggered_notes": "Review durchgeführt"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "Aktiv"
    assert data["next_due_at"] is not None


def test_advisory_log_description_update_is_audited(session_factory, auth_client, advisor_user):
    """U-FINMA-2.1: Update erzeugt neuen Audit-Log-Eintrag mit field_name=version.
    Beide Eintrags-Versionen (v1+v2) verbleiben persistent — der Wechsel ist
    durch das Audit-Log + integrity_hash nachvollziehbar."""
    mandate_id, _ = _seed_review_context(
        session_factory,
        advisor_user,
    )
    create_response = _create_advisory_entry(
        auth_client,
        mandate_id,
        description=(
            "Initiale Beratung — Strategie diskutiert, Allokation prinzipiell ok."
        ),
    )
    v1_id = create_response.json()["id"]

    response = auth_client.put(
        f"/mandates/{mandate_id}/advisory-log/{v1_id}",
        json={"description": "Neu dokumentierte Begruendung nach Rueckfragen des Kunden."},
    )

    assert response.status_code == 200
    v2_id = response.json()["id"]
    with session_factory() as s:
        audit_entry = (
            s.query(AuditLog)
            .filter(
                AuditLog.table_name == "advisory_log",
                AuditLog.record_id == v2_id,
                AuditLog.action == "UPDATE",
            )
            .order_by(AuditLog.created_at.desc())
            .first()
        )

    assert audit_entry is not None
    assert audit_entry.field_name == "version"
    assert audit_entry.old_value == "1"
    assert audit_entry.new_value == "2"


# ---------------------------------------------------------------------------
# REVIEW-STATE-002 (Codex-Audit 2026-08-27): manuelle Trigger-Erstellung
# validiert Frequenz/Datum/Schwelle jetzt strikt statt unbekannte Werte
# stillschweigend umzudeuten oder kaputte Daten unveraendert zu speichern.
# ---------------------------------------------------------------------------

def test_create_trigger_rejects_unknown_frequency(session_factory, auth_client, advisor_user):
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)

    response = auth_client.post(
        f"/mandates/{mandate_id}/triggers",
        json={"trigger_type": "Zeit", "trigger_name": "Mein Trigger", "frequency": "weekly"},
    )

    assert response.status_code == 422
    with session_factory() as s:
        assert s.query(ReviewTrigger).filter(ReviewTrigger.mandate_id == mandate_id).count() == 0


def test_create_trigger_rejects_invalid_next_due_at(session_factory, auth_client, advisor_user):
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)

    response = auth_client.post(
        f"/mandates/{mandate_id}/triggers",
        json={
            "trigger_type": "Zeit",
            "trigger_name": "Mein Trigger",
            "frequency": "jährlich",
            "next_due_at": "not-a-date",
        },
    )

    assert response.status_code == 422


def test_create_trigger_rejects_negative_threshold(session_factory, auth_client, advisor_user):
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)

    response = auth_client.post(
        f"/mandates/{mandate_id}/triggers",
        json={"trigger_type": "Markt", "trigger_name": "Drift-Check", "threshold_bps": -999999},
    )

    assert response.status_code == 422
    with session_factory() as s:
        assert s.query(ReviewTrigger).filter(ReviewTrigger.mandate_id == mandate_id).count() == 0


def test_create_trigger_rejects_bool_threshold(session_factory, auth_client, advisor_user):
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)

    response = auth_client.post(
        f"/mandates/{mandate_id}/triggers",
        json={"trigger_type": "Markt", "trigger_name": "Drift-Check", "threshold_bps": True},
    )

    assert response.status_code == 422


def test_create_trigger_rejects_threshold_on_zeit_trigger(session_factory, auth_client, advisor_user):
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)

    response = auth_client.post(
        f"/mandates/{mandate_id}/triggers",
        json={
            "trigger_type": "Zeit",
            "trigger_name": "Mein Trigger",
            "frequency": "jährlich",
            "threshold_bps": 500,
        },
    )

    assert response.status_code == 422


def test_create_trigger_rejects_frequency_on_markt_trigger(session_factory, auth_client, advisor_user):
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)

    response = auth_client.post(
        f"/mandates/{mandate_id}/triggers",
        json={
            "trigger_type": "Markt",
            "trigger_name": "Drift-Check",
            "threshold_bps": 500,
            "frequency": "jährlich",
        },
    )

    assert response.status_code == 422


def test_create_trigger_accepts_valid_zeit_trigger(session_factory, auth_client, advisor_user):
    """Golden path: ein gueltiger Zeit-Trigger wird weiterhin angelegt --
    die Haertung darf den normalen Beraterworkflow nicht blockieren."""
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)

    response = auth_client.post(
        f"/mandates/{mandate_id}/triggers",
        json={"trigger_type": "Zeit", "trigger_name": "Eigener Review", "frequency": "quartalsweise"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["frequency"] == "quartalsweise"
    assert data["status"] == "Aktiv"


# ---------------------------------------------------------------------------
# REVIEW-STATE-003 (Codex-Audit 2026-08-27): Resolve liest/persistiert jetzt
# den Entscheid, prueft Faelligkeit vor der Mutation und ist nicht mehr
# beliebig oft replaybar.
# ---------------------------------------------------------------------------

def _seed_time_trigger(session_factory, mandate_id: str, **overrides) -> str:
    defaults = dict(
        id="trigger-state003-1",
        mandate_id=mandate_id,
        trigger_type="Zeit",
        trigger_name="Jahresreview",
        frequency="jährlich",
        status="Ausgelöst",
        next_due_at="2026-04-01",
        created_at="2026-04-01T00:00:00.000Z",
        updated_at="2026-04-01T00:00:00.000Z",
    )
    defaults.update(overrides)
    with session_factory() as s:
        s.add(ReviewTrigger(**defaults))
        s.commit()
    return defaults["id"]


def test_resolve_trigger_persists_decision_evidence(session_factory, auth_client, advisor_user):
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    trigger_id = _seed_time_trigger(session_factory, mandate_id)

    response = auth_client.put(
        f"/mandates/{mandate_id}/triggers/{trigger_id}/resolve",
        json={"decision": "Erledigt", "triggered_notes": "Review durchgeführt"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["resolution_decision"] == "Erledigt"
    assert data["resolved_by"] == advisor_user.id
    assert data["resolved_at"] is not None
    assert data["previous_next_due_at"] == "2026-04-01"
    with session_factory() as s:
        row = s.query(ReviewTrigger).filter(ReviewTrigger.id == trigger_id).one()
        assert row.resolution_decision == "Erledigt"
        assert row.previous_next_due_at == "2026-04-01"


def test_resolve_trigger_is_not_replayable(session_factory, auth_client, advisor_user):
    """REVIEW-STATE-003 Kern-Repro: ein frueher zweiter Resolve-Aufruf darf
    die Faelligkeit NICHT ein zweites Mal verschieben."""
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    trigger_id = _seed_time_trigger(session_factory, mandate_id)

    first = auth_client.put(
        f"/mandates/{mandate_id}/triggers/{trigger_id}/resolve",
        json={"decision": "Erledigt", "triggered_notes": "Review durchgeführt"},
    )
    assert first.status_code == 200
    first_next_due = first.json()["next_due_at"]
    assert first_next_due == "2027-04-01"

    replay = auth_client.put(
        f"/mandates/{mandate_id}/triggers/{trigger_id}/resolve",
        json={"decision": "Erledigt", "triggered_notes": "Erneuter Versuch"},
    )

    assert replay.status_code == 409
    with session_factory() as s:
        row = s.query(ReviewTrigger).filter(ReviewTrigger.id == trigger_id).one()
        assert row.next_due_at == first_next_due


def test_resolve_trigger_rejects_not_yet_due_time_trigger(session_factory, auth_client, advisor_user):
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    trigger_id = _seed_time_trigger(
        session_factory,
        mandate_id,
        status="Aktiv",
        next_due_at="2099-01-01",
    )

    response = auth_client.put(
        f"/mandates/{mandate_id}/triggers/{trigger_id}/resolve",
        json={"decision": "Erledigt"},
    )

    assert response.status_code == 409
    with session_factory() as s:
        row = s.query(ReviewTrigger).filter(ReviewTrigger.id == trigger_id).one()
        assert row.next_due_at == "2099-01-01"
        assert row.status == "Aktiv"
        assert row.resolution_decision is None


def test_resolve_trigger_rejects_already_resolved(session_factory, auth_client, advisor_user):
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    trigger_id = _seed_time_trigger(
        session_factory,
        mandate_id,
        status="Erledigt",
        next_due_at=None,
    )

    response = auth_client.put(
        f"/mandates/{mandate_id}/triggers/{trigger_id}/resolve",
        json={"decision": "Erledigt"},
    )

    assert response.status_code == 409


def test_resolve_trigger_einmalig_does_not_reschedule(session_factory, auth_client, advisor_user):
    """Vorher wurde ein 'einmalig'-Trigger faelschlich auf 12 Monate
    weiterverlaengert (trigger_frequency_months(...) or 12). Jetzt bleibt er
    nach Resolve endgueltig 'Erledigt' ohne neue Faelligkeit."""
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    trigger_id = _seed_time_trigger(session_factory, mandate_id, frequency="einmalig")

    response = auth_client.put(
        f"/mandates/{mandate_id}/triggers/{trigger_id}/resolve",
        json={"decision": "Erledigt"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "Erledigt"
    assert data["next_due_at"] is None


def test_resolve_trigger_rejects_legacy_broken_frequency(session_factory, auth_client, advisor_user):
    """Raw-/Legacy-Zeile mit einer nie ueber die API erzeugbaren Frequenz
    (Direct-ORM-Insert simuliert Altbestand) muss fail-closed stoppen statt
    stillschweigend auf 12 Monate zu defaulten."""
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    trigger_id = _seed_time_trigger(session_factory, mandate_id, frequency="weekly")

    response = auth_client.put(
        f"/mandates/{mandate_id}/triggers/{trigger_id}/resolve",
        json={"decision": "Erledigt"},
    )

    assert response.status_code == 409
    with session_factory() as s:
        row = s.query(ReviewTrigger).filter(ReviewTrigger.id == trigger_id).one()
        assert row.status == "Ausgelöst"
        assert row.resolution_decision is None


def test_resolve_trigger_rejects_unknown_decision_value(session_factory, auth_client, advisor_user):
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    trigger_id = _seed_time_trigger(session_factory, mandate_id)

    response = auth_client.put(
        f"/mandates/{mandate_id}/triggers/{trigger_id}/resolve",
        json={"decision": "Irgendwas"},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# FIDLEG-STATE-002 (Codex-Audit 2026-08-27): client_signed_at muss ein echter
# ISO-Zeitstempel sein; ist ein signiertes ContractDocument verknuepft, wird
# der Zeitpunkt aus dessen echter Kundensignatur abgeleitet statt aus einem
# frei behaupteten Request-String.
# ---------------------------------------------------------------------------

def test_advisory_log_create_rejects_non_date_client_signed_at(session_factory, auth_client, advisor_user):
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)

    response = _create_advisory_entry(
        auth_client,
        mandate_id,
        client_signed=True,
        client_signed_at="not-a-date",
    )

    assert response.status_code == 422


def test_advisory_log_update_rejects_client_signed_without_timestamp(session_factory, auth_client, advisor_user):
    """Vorher hatte AdvisoryLogUpdate ueberhaupt keinen Signatur-Validator --
    client_signed=true ohne Zeitpunkt wurde klaglos in eine neue Version
    uebernommen (repro: versioned_client_signed_at=None)."""
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    create_response = _create_advisory_entry(auth_client, mandate_id)
    entry_id = create_response.json()["id"]

    response = auth_client.put(
        f"/mandates/{mandate_id}/advisory-log/{entry_id}",
        json={"client_signed": True},
    )

    assert response.status_code == 422


def _create_signed_client_document(auth_client: TestClient, mandate_id: str) -> str:
    create_response = auth_client.post(
        f"/mandates/{mandate_id}/documents",
        json={"document_type": "Sonstiges", "title": "Beratungsvertrag"},
    )
    assert create_response.status_code == 201
    doc_id = create_response.json()["id"]
    sign_response = auth_client.post(
        f"/mandates/{mandate_id}/documents/{doc_id}/sign",
        json={
            "signed_by_client": True,
            "signature_image": "data:image/png;base64,AAAA",
            "signer_name": "Max Muster",
        },
    )
    assert sign_response.status_code == 200
    return doc_id


def test_advisory_log_create_with_signed_document_derives_real_timestamp(session_factory, auth_client, advisor_user):
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    doc_id = _create_signed_client_document(auth_client, mandate_id)
    with session_factory() as s:
        doc = s.query(ContractDocument).filter(ContractDocument.id == doc_id).one()
        real_signed_at = doc.signature_client_signed_at
    assert real_signed_at

    response = _create_advisory_entry(
        auth_client,
        mandate_id,
        document_id=doc_id,
        client_signed=True,
        # Ein frei erfundener Zeitpunkt -- muss vom Server verworfen und
        # durch den echten Signatur-Zeitpunkt des Dokuments ersetzt werden.
        client_signed_at="2020-01-01T00:00:00.000Z",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["client_signed_at"] == real_signed_at
    assert data["client_signed_at"] != "2020-01-01T00:00:00.000Z"


def test_advisory_log_create_rejects_client_signed_with_unsigned_document(session_factory, auth_client, advisor_user):
    mandate_id, _ = _seed_review_context(session_factory, advisor_user)
    create_response = auth_client.post(
        f"/mandates/{mandate_id}/documents",
        json={"document_type": "Sonstiges", "title": "Beratungsvertrag"},
    )
    assert create_response.status_code == 201
    doc_id = create_response.json()["id"]

    response = _create_advisory_entry(
        auth_client,
        mandate_id,
        document_id=doc_id,
        client_signed=True,
        client_signed_at="2026-05-28T14:00:00.000Z",
    )

    assert response.status_code == 422
