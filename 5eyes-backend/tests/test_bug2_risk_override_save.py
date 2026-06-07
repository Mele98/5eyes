"""Sprint Bug-#2 (2026-06-08): End-to-End-Test fuer Risikoprofil-Override.

User-Report: 'Wenn das Risikoprofil manuell überschrieben wird, kann ich diese
Änderung aktuell nicht speichern.'

Root-Cause-Befund: Frontend hatte Silent-Demo-Path wenn raId=null —
Modal schloss sich, Override-Badge erschien, aber Server hat nichts
persistiert.

Backend-Logik selbst war OK. Frontend-Fix mit Pre-Check + klarer
Fehlermeldung. Backend-Tests verifizieren weiterhin den korrekten Save-Pfad
ueber alle Edge-Cases.
"""
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
import models.allocation  # noqa: F401
import models.clients  # noqa: F401
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.mandates  # noqa: F401
import models.profiling  # noqa: F401
import models.review  # noqa: F401
import models.snapshots  # noqa: F401
import models.tenant  # noqa: F401
import models.users  # noqa: F401
import models.wealth  # noqa: F401

from main import app
from models.profiling import RiskAssessment
from models.users import User
from services.auth import get_current_user
from tests.risk_fixture_helpers import CURRENT_RISK_ANSWERS


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'bug2_override.db'}",
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
        id="advisor-bug2",
        username="advisor-bug2",
        password_hash="h",
        full_name="Test Advisor",
        role="advisor",
        is_active=1,
        created_at=_utc_now_iso(),
        updated_at=_utc_now_iso(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _setup_full(auth_client, advisor_user) -> tuple[str, str, str]:
    """Erstellt Client + Mandate + RiskAssessment. Returnt (client_id, mandate_id, ra_id)."""
    client_resp = auth_client.post(
        "/clients",
        json={
            "client_number": "BUG2-001",
            "first_name": "Bug",
            "last_name": "Two",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert client_resp.status_code == 201, client_resp.text
    client_id = client_resp.json()["id"]
    mandate_resp = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "BUG2-M-001", "mandate_type": "Anlageberatung"},
    )
    assert mandate_resp.status_code == 201, mandate_resp.text
    mandate_id = mandate_resp.json()["id"]
    # Risikoprofilierung erstellen — Voraussetzung fuer Override.
    # Payload analog zu CURRENT_RISK_ANSWERS auf RiskAssessmentCreate-Schema mappen.
    answers_dicts = [
        {"question_number": qn, "answer_label": lbl, "answer_points": pts}
        for (qn, lbl, pts) in CURRENT_RISK_ANSWERS
    ]
    ra_resp = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments",
        json={
            "q_income_points": 3,
            "q_obligations_points": 3,
            "q_savings_points": 9,
            "q_wealth_points": 9,
            "investment_horizon_label": "Mehr als 12 Jahre",
            "investment_horizon_years": 15,
            "q_investment_goal_points": 3,
            "q_risk_preference_points": 3,
            "q_risk_behavior_points": 3,
            "answers": answers_dicts,
            "knowledge_services_json": "{}",
            "knowledge_instruments_json": "{}",
            "income_sources_json": '["Berufliche Taetigkeit"]',
        },
    )
    assert ra_resp.status_code == 201, ra_resp.text
    return client_id, mandate_id, ra_resp.json()["id"]


# ===========================================================================
# Sicherheits-Garantie: Override wird tatsaechlich in der DB persistiert
# ===========================================================================


VALID_REASON = (
    "Kunde wuenscht ausdruecklich erhoehte Risikobereitschaft "
    "wegen langem Anlagehorizont und solider Liquiditaetsreserve."
)


def test_override_wird_in_db_persistiert(auth_client, advisor_user, session_factory):
    """Kern-Test: Override-Endpoint persistiert wirklich.

    Pre-Bug-#2-Fix war das Backend OK, der Bug war im Frontend. Dieser
    Test garantiert dass das Backend weiter sauber speichert (Drift-Schutz).
    """
    _, mandate_id, ra_id = _setup_full(auth_client, advisor_user)
    resp = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments/{ra_id}/override",
        json={
            "override_score_x10": 70,
            "override_profile": "Wachstumsorientiert",
            "override_reason": VALID_REASON,
            "override_client_confirmed": True,
            "override_warning_delivered": True,
        },
    )
    assert resp.status_code == 200, resp.text
    # In DB persistiert
    with session_factory() as db:
        ra = db.query(RiskAssessment).filter(RiskAssessment.id == ra_id).first()
        assert ra is not None
        assert int(ra.is_overridden or 0) == 1
        assert ra.override_score_x10 == 70
        assert ra.override_profile == "Wachstumsorientiert"
        assert ra.override_reason == VALID_REASON
        assert int(ra.override_client_confirmed or 0) == 1
        assert int(ra.override_warning_delivered or 0) == 1
        assert ra.override_by == advisor_user.id
        assert ra.override_at is not None  # timestamp gesetzt


def test_override_audit_log_eintrag(auth_client, advisor_user, session_factory):
    """FIDLEG-Compliance: Override muss im Audit-Log erscheinen."""
    from models.review import AuditLog
    _, mandate_id, ra_id = _setup_full(auth_client, advisor_user)
    resp = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments/{ra_id}/override",
        json={
            "override_score_x10": 70,
            "override_profile": "Wachstumsorientiert",
            "override_reason": VALID_REASON,
        },
    )
    assert resp.status_code == 200, resp.text
    with session_factory() as db:
        log_entries = (
            db.query(AuditLog)
            .filter(
                AuditLog.table_name == "risk_assessments",
                AuditLog.record_id == ra_id,
                AuditLog.action == "UPDATE",
            )
            .all()
        )
        # Mind. ein Eintrag fuer Override (field_name='override')
        override_entries = [e for e in log_entries if e.field_name == "override"]
        assert len(override_entries) >= 1
        assert override_entries[0].new_value == "Wachstumsorientiert"


def test_override_reason_zu_kurz_422(auth_client, advisor_user):
    """User-Bug: Reason 'OK' → Backend lehnt korrekt ab mit detail-msg."""
    _, mandate_id, ra_id = _setup_full(auth_client, advisor_user)
    resp = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments/{ra_id}/override",
        json={
            "override_score_x10": 70,
            "override_profile": "Wachstumsorientiert",
            "override_reason": "OK",  # zu kurz
        },
    )
    assert resp.status_code == 422
    # Detail enthaelt den Grund (Mindestlaenge)
    detail = resp.json().get("detail", [])
    if isinstance(detail, list):
        msgs = " ".join(d.get("msg", "") for d in detail if isinstance(d, dict))
    else:
        msgs = str(detail)
    assert ("mindestens" in msgs.lower() or "min" in msgs.lower())


def test_override_reason_floskel_422(auth_client, advisor_user):
    """Generische Floskel ('siehe oben') wird abgelehnt."""
    _, mandate_id, ra_id = _setup_full(auth_client, advisor_user)
    resp = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments/{ra_id}/override",
        json={
            "override_score_x10": 70,
            "override_profile": "Wachstumsorientiert",
            "override_reason": "siehe oben",
        },
    )
    assert resp.status_code == 422


def test_override_score_profile_mismatch_422(auth_client, advisor_user):
    """Score 30 mit Profil 'Wachstumsorientiert' ist inkonsistent → 422."""
    _, mandate_id, ra_id = _setup_full(auth_client, advisor_user)
    resp = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments/{ra_id}/override",
        json={
            "override_score_x10": 30,
            "override_profile": "Wachstumsorientiert",  # passt nicht zu Score 30
            "override_reason": VALID_REASON,
        },
    )
    assert resp.status_code == 422


def test_override_unbekannte_ra_id_404(auth_client, advisor_user):
    """Falsche RA-ID → 404 (sauberer Fehler statt Silent-Success)."""
    _, mandate_id, _ = _setup_full(auth_client, advisor_user)
    resp = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments/unknown-ra-id/override",
        json={
            "override_score_x10": 70,
            "override_profile": "Wachstumsorientiert",
            "override_reason": VALID_REASON,
        },
    )
    assert resp.status_code == 404


def test_override_geloeschte_ra_404(auth_client, advisor_user, session_factory):
    """Soft-deleted RA → 404, nicht 200."""
    _, mandate_id, ra_id = _setup_full(auth_client, advisor_user)
    with session_factory() as db:
        ra = db.query(RiskAssessment).filter(RiskAssessment.id == ra_id).first()
        ra.deleted_at = _utc_now_iso()
        db.commit()
    resp = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments/{ra_id}/override",
        json={
            "override_score_x10": 70,
            "override_profile": "Wachstumsorientiert",
            "override_reason": VALID_REASON,
        },
    )
    assert resp.status_code == 404


# ===========================================================================
# Re-Override-Pfad (User aendert Override mehrfach)
# ===========================================================================


def test_re_override_aktualisiert_felder(auth_client, advisor_user, session_factory):
    """Zweiter Override auf gleicher RA aktualisiert override_at, _by, etc.

    Score-Mapping (SCORE_TO_PROFILE):
    - Score-x10=60 (=Score 6) → "Ausgewogen"
    - Score-x10=80 (=Score 8) → "Wachstumsorientiert"
    """
    _, mandate_id, ra_id = _setup_full(auth_client, advisor_user)
    # Erster Override
    r1 = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments/{ra_id}/override",
        json={
            "override_score_x10": 60,
            "override_profile": "Ausgewogen",
            "override_reason": VALID_REASON,
        },
    )
    assert r1.status_code == 200, r1.text
    # Zweiter Override mit anderem Score (8/10 → Wachstumsorientiert)
    r2 = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments/{ra_id}/override",
        json={
            "override_score_x10": 80,
            "override_profile": "Wachstumsorientiert",
            "override_reason": VALID_REASON + " Update mit aktualisierter Begruendung.",
        },
    )
    assert r2.status_code == 200, r2.text
    with session_factory() as db:
        ra2 = db.query(RiskAssessment).filter(RiskAssessment.id == ra_id).first()
        assert ra2.override_score_x10 == 80
        assert ra2.override_profile == "Wachstumsorientiert"
        assert int(ra2.is_overridden or 0) == 1
