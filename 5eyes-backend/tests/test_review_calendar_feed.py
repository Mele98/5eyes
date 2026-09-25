"""REVIEW-CALENDAR-001 (Kontrollrunde 2026-09-24): persoenlicher .ics-
Kalender-Abo-Feed fuer faellige/bald faellige Review-Trigger.

Deckt ab:
- Token-Ausstellung/-Rotation/-Widerruf (POST/DELETE /me/calendar-feed-token)
- GET /calendar/reviews.ics: gueltiger Token liefert VCALENDAR mit den
  faelligen/ausgeloesten Triggern NUR der eigenen Mandate
- ungueltiger/fehlender/widerrufener Token -> 404
- "Erledigt"-Trigger und Trigger ohne next_due_at werden NICHT aufgenommen
- Mandate eines ANDEREN Beraters tauchen NICHT im Feed auf (Scoping-Test)
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
from main import app
from models.clients import Client
from models.mandates import Mandate
from models.review import ReviewTrigger
from models.users import User
from services.auth import get_current_user
from services.review_engine import SYSTEM_TRIGGER_REVIEW


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_review_calendar_feed.db'}",
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
        id="advisor-cal-1", username="advisor_cal", password_hash="h",
        full_name="Berater Kalender", role="advisor", is_active=1,
        created_at=_now(), updated_at=_now(),
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


def _seed_scenario(session_factory, advisor_user):
    """Seed: eigener Kunde/Mandat mit einem faelligen (Aktiv) und einem
    erledigten (Erledigt, kein next_due_at) Trigger -- plus ein FREMDER
    Berater mit eigenem Kunden/Mandat/faelligem Trigger, der NICHT im Feed
    des ersten Beraters auftauchen darf."""
    with session_factory() as s:
        s.add(User(
            id=advisor_user.id, username=advisor_user.username,
            password_hash="h", full_name=advisor_user.full_name,
            role="advisor", is_active=1, created_at=_now(), updated_at=_now(),
        ))
        s.add(Client(
            id="client-cal-own", client_number="C-CAL-OWN",
            first_name="Anna", last_name="Muster", advisor_id=advisor_user.id,
            household_type="Einzelperson", country_of_residence="CH",
            language="DE", client_classification="Privatkunde",
            is_professional_opt_out=0, is_qualified_investor=0,
            created_at=_now(), updated_at=_now(),
        ))
        s.add(Mandate(
            id="mandate-cal-own", client_id="client-cal-own",
            mandate_number="M-CAL-OWN", mandate_type="Anlageberatung",
            status="Aktiv", base_currency="CHF", advisory_language="DE",
            opened_at="2024-01-01", created_at=_now(), updated_at=_now(),
        ))
        s.add(ReviewTrigger(
            id="trig-cal-due", mandate_id="mandate-cal-own",
            trigger_type="Zeit", trigger_name=SYSTEM_TRIGGER_REVIEW,
            frequency="jährlich", status="Aktiv", is_system=1,
            next_due_at="2026-01-01",
            created_at=_now(), updated_at=_now(),
        ))
        s.add(ReviewTrigger(
            id="trig-cal-done", mandate_id="mandate-cal-own",
            trigger_type="Zeit", trigger_name="Erledigter Trigger",
            frequency="einmalig", status="Erledigt", is_system=0,
            next_due_at=None,
            created_at=_now(), updated_at=_now(),
        ))

        s.add(User(
            id="advisor-cal-other", username="advisor_cal_other",
            password_hash="h", full_name="Anderer Berater", role="advisor",
            is_active=1, created_at=_now(), updated_at=_now(),
        ))
        s.add(Client(
            id="client-cal-other", client_number="C-CAL-OTHER",
            first_name="Beat", last_name="Fremd", advisor_id="advisor-cal-other",
            household_type="Einzelperson", country_of_residence="CH",
            language="DE", client_classification="Privatkunde",
            is_professional_opt_out=0, is_qualified_investor=0,
            created_at=_now(), updated_at=_now(),
        ))
        s.add(Mandate(
            id="mandate-cal-other", client_id="client-cal-other",
            mandate_number="M-CAL-OTHER", mandate_type="Anlageberatung",
            status="Aktiv", base_currency="CHF", advisory_language="DE",
            opened_at="2024-01-01", created_at=_now(), updated_at=_now(),
        ))
        s.add(ReviewTrigger(
            id="trig-cal-foreign", mandate_id="mandate-cal-other",
            trigger_type="Zeit", trigger_name=SYSTEM_TRIGGER_REVIEW,
            frequency="jährlich", status="Aktiv", is_system=1,
            next_due_at="2026-02-01",
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def test_calendar_feed_requires_valid_token(auth_client):
    response = auth_client.get("/calendar/reviews.ics?token=not-a-real-token")
    assert response.status_code == 404


def test_calendar_feed_requires_token_at_all(auth_client):
    response = auth_client.get("/calendar/reviews.ics")
    assert response.status_code == 422


def test_issue_and_use_calendar_feed_token(session_factory, auth_client, advisor_user):
    _seed_scenario(session_factory, advisor_user)

    issue_response = auth_client.post("/me/calendar-feed-token")
    assert issue_response.status_code == 200
    token = issue_response.json()["token"]
    assert token

    # Kein Auth-Header noetig -- der Feed-Endpoint validiert ausschliesslich
    # per Token-Query (Outlook kann sich beim automatischen Refresh nicht
    # interaktiv anmelden).
    unauth_client = TestClient(app)
    feed_response = unauth_client.get(f"/calendar/reviews.ics?token={token}")
    auth_client.app  # keep reference alive
    assert feed_response.status_code == 200
    assert feed_response.headers["content-type"].startswith("text/calendar")
    body = feed_response.text
    assert body.startswith("BEGIN:VCALENDAR")
    assert body.strip().endswith("END:VCALENDAR")


def test_calendar_feed_includes_only_due_trigger_of_own_mandate(
    session_factory, auth_client, advisor_user,
):
    _seed_scenario(session_factory, advisor_user)
    token = auth_client.post("/me/calendar-feed-token").json()["token"]

    response = auth_client.get(f"/calendar/reviews.ics?token={token}")
    assert response.status_code == 200
    body = response.text

    assert "trig-cal-due" in body
    assert "20260101" in body
    # Erledigter Trigger (kein next_due_at) darf nicht auftauchen.
    assert "trig-cal-done" not in body
    # Trigger eines FREMDEN Beraters darf nicht auftauchen (Scoping).
    assert "trig-cal-foreign" not in body
    assert "M-CAL-OTHER" not in body
    # Erinnerungsalarm ist eingebettet.
    assert "BEGIN:VALARM" in body
    assert "TRIGGER:-P14D" in body


def test_revoked_calendar_feed_token_returns_404(session_factory, auth_client, advisor_user):
    _seed_scenario(session_factory, advisor_user)
    token = auth_client.post("/me/calendar-feed-token").json()["token"]

    revoke_response = auth_client.delete("/me/calendar-feed-token")
    assert revoke_response.status_code == 204

    response = auth_client.get(f"/calendar/reviews.ics?token={token}")
    assert response.status_code == 404


def test_rotating_calendar_feed_token_invalidates_previous_token(
    session_factory, auth_client, advisor_user,
):
    _seed_scenario(session_factory, advisor_user)
    old_token = auth_client.post("/me/calendar-feed-token").json()["token"]
    new_token = auth_client.post("/me/calendar-feed-token").json()["token"]
    assert old_token != new_token

    old_response = auth_client.get(f"/calendar/reviews.ics?token={old_token}")
    assert old_response.status_code == 404

    new_response = auth_client.get(f"/calendar/reviews.ics?token={new_token}")
    assert new_response.status_code == 200
