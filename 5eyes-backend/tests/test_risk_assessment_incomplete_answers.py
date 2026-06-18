"""Regressions-Lock: unvollstaendige Antwortzeilen duerfen das Speichern eines
Risikoprofils NICHT mit 500 abbrechen.

Befund (Extern-Test 2026-06-18): Schickt das Frontend eine zusaetzliche, nicht
angeklickte Frage mit NULL-Werten mit (z.B. Frage 12), rutschte sie am
Vollstaendigkeits-Gate vorbei (das prueft nur Fragen 1-11). Beim Speichern
versuchte create_risk_assessment dann, eine risk_assessment_answers-Zeile mit
answer_label=NULL einzufuegen -> die Spalte ist NOT NULL -> IntegrityError ->
HTTP 500 ("Interner Serverfehler").

Fix: in create_risk_assessment werden unvollstaendige Antwortzeilen (kein
question_number / answer_points oder leeres answer_label) uebersprungen. Das ist
konsistent mit dem Gate, das solche Antworten ohnehin ignoriert.
"""
from __future__ import annotations

import datetime
import sys
from contextlib import asynccontextmanager
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
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from services.auth import get_current_user


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'risk_incomplete_answers.db'}",
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
        id="user-incomplete-answers",
        username="advisor",
        password_hash="h",
        full_name="Advisor Incomplete",
        role="advisor",
        is_active=1,
        created_at=_utc_now_iso(),
        updated_at=_utc_now_iso(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user, monkeypatch):
    def override_db():
        with session_factory() as session:
            yield session

    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _setup_mandate(auth_client: TestClient, advisor_user: User) -> str:
    cr = auth_client.post(
        "/clients",
        json={
            "client_number": "INC-001",
            "first_name": "Incomplete",
            "last_name": "Tester",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert cr.status_code == 201, cr.text
    client_id = cr.json()["id"]
    mr = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "INC-M-001", "mandate_type": "Anlageberatung"},
    )
    assert mr.status_code == 201, mr.text
    return mr.json()["id"]


def _full_answers() -> list[dict]:
    return [
        {"question_number": 1, "answer_label": "Finanzdienstleistungen: Beratung und Verwaltung", "answer_points": 0},
        {"question_number": 2, "answer_label": "Finanzinstrumente: Anlagefonds und ETFs", "answer_points": 0},
        {"question_number": 3, "answer_label": "CHF 12'000 bis 20'000", "answer_points": 3},
        {"question_number": 4, "answer_label": "Herkunft: Berufliche Taetigkeit", "answer_points": 0},
        {"question_number": 5, "answer_label": "CHF 3'000 bis 5'000", "answer_points": 3},
        {"question_number": 6, "answer_label": "CHF 1'000'000 bis 2'000'000", "answer_points": 9},
        {"question_number": 7, "answer_label": "25 bis 50 %", "answer_points": 9},
        {"question_number": 8, "answer_label": "5 bis 7 Jahre - Matrix-Faktor", "answer_points": 0},
        {"question_number": 9, "answer_label": "Das investierte Kapital soll sich stetig vermehren.", "answer_points": 3},
        {"question_number": 10, "answer_label": "Ich strebe eine hoehere Rendite an und gehe erhoehtes Risiko ein.", "answer_points": 3},
        {"question_number": 11, "answer_label": "Ich kann den Verlust voruebergehend akzeptieren und halte fest.", "answer_points": 3},
    ]


def _base_payload(answers: list[dict]) -> dict:
    return {
        "q_income_points": 3,
        "q_obligations_points": 2,
        "q_savings_points": 8,
        "q_wealth_points": 8,
        "investment_horizon_years": 12,
        "investment_horizon_label": "5 bis 10 Jahre",
        "q_investment_goal_points": 3,
        "q_risk_preference_points": 3,
        "q_risk_behavior_points": 3,
        "answers": answers,
    }


@pytest.mark.parametrize(
    "incomplete",
    [
        {"question_number": 12, "answer_label": None, "answer_points": None},
        {"question_number": 12, "answer_label": "Teilweise", "answer_points": None},
        {"question_number": 12, "answer_label": "   ", "answer_points": 2},
        {"question_number": None, "answer_label": "Frei", "answer_points": 2},
    ],
)
def test_incomplete_extra_answer_does_not_500(auth_client, advisor_user, session_factory, incomplete):
    mid = _setup_mandate(auth_client, advisor_user)
    response = auth_client.post(
        f"/mandates/{mid}/risk-assessments",
        json=_base_payload(_full_answers() + [incomplete]),
    )
    # War vorher 500 (NOT NULL constraint failed: risk_assessment_answers.answer_label)
    assert response.status_code == 201, response.text
    ra_id = response.json()["id"]
    # Nur die 11 vollstaendigen Antworten landen in der DB, die leere wird verworfen.
    with session_factory() as s:
        stored = s.query(RiskAssessmentAnswer).filter(
            RiskAssessmentAnswer.assessment_id == ra_id
        ).all()
        assert len(stored) == 11
        assert all(a.answer_label and a.answer_label.strip() for a in stored)
        assert all(a.answer_points is not None for a in stored)


def test_full_questionnaire_still_persists_all_answers(auth_client, advisor_user, session_factory):
    mid = _setup_mandate(auth_client, advisor_user)
    response = auth_client.post(
        f"/mandates/{mid}/risk-assessments",
        json=_base_payload(_full_answers()),
    )
    assert response.status_code == 201, response.text
    ra_id = response.json()["id"]
    with session_factory() as s:
        n = s.query(RiskAssessmentAnswer).filter(
            RiskAssessmentAnswer.assessment_id == ra_id
        ).count()
        assert n == 11
        ra = s.query(RiskAssessment).filter(RiskAssessment.id == ra_id).one()
        assert ra.is_current == 1
