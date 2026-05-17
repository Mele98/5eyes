"""Roundtrip-Tests fuer Referenzmodell Eignungspruefung Seite 1: Kenntnisse & Erfahrungen +
Einkommensquellen werden im Risk-Assessment persistiert.

Bugfix-Test: vor 2026-05-15 hat create_risk_assessment die 3 Felder
knowledge_services_json, knowledge_instruments_json, income_sources_json
aus dem Request stillschweigend ignoriert (Datenverlust). Felder waren
in Schema, Model und DB definiert, aber nicht im RiskAssessment(...) Constructor.
"""
from __future__ import annotations

import datetime
import json
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
from models.users import User
from services.auth import get_current_user
from tests.risk_fixture_helpers import current_risk_answer_dicts, noop_lifespan


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'risk_suitability_persistence.db'}",
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
        id="user-suitability",
        username="advisor",
        password_hash="h",
        full_name="Advisor Suitability",
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

    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _setup_mandate(auth_client: TestClient, advisor_user: User) -> str:
    cr = auth_client.post(
        "/clients",
        json={
            "client_number": "SUIT-001",
            "first_name": "Eignungspruefung",
            "last_name": "Tester",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert cr.status_code == 201, cr.text
    client_id = cr.json()["id"]
    mr = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "SUIT-M-001", "mandate_type": "Anlageberatung"},
    )
    assert mr.status_code == 201, mr.text
    return mr.json()["id"]


def _valid_payload(**overrides) -> dict:
    base = {
        "q_income_points": 3,
        "q_obligations_points": 2,
        "q_savings_points": 8,
        "q_wealth_points": 8,
        "investment_horizon_years": 12,
        "investment_horizon_label": "5 bis 10 Jahre",
        "q_investment_goal_points": 3,
        "q_risk_preference_points": 3,
        "q_risk_behavior_points": 3,
        "answers": current_risk_answer_dicts(),
    }
    base.update(overrides)
    return base


def test_suitability_fields_persist_on_create(auth_client, advisor_user):
    mid = _setup_mandate(auth_client, advisor_user)
    services = json.dumps({"Vermögensverwaltung": {"known": 1, "informed": 1}})
    instruments = json.dumps({"Anlagefonds": {"known": 1, "informed": 1}})
    sources = json.dumps(["Berufliche Tätigkeit", "Rente"])

    response = auth_client.post(
        f"/mandates/{mid}/risk-assessments",
        json=_valid_payload(
            knowledge_services_json=services,
            knowledge_instruments_json=instruments,
            income_sources_json=sources,
        ),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["knowledge_services_json"] == services
    assert body["knowledge_instruments_json"] == instruments
    assert body["income_sources_json"] == sources

    # Reload via /current confirms DB persistence (not just response echo)
    current = auth_client.get(f"/mandates/{mid}/risk-assessments/current")
    assert current.status_code == 200, current.text
    cb = current.json()
    assert cb["knowledge_services_json"] == services
    assert cb["knowledge_instruments_json"] == instruments
    assert cb["income_sources_json"] == sources


def test_suitability_fields_default_empty_schema_markers_when_omitted(auth_client, advisor_user):
    mid = _setup_mandate(auth_client, advisor_user)
    response = auth_client.post(
        f"/mandates/{mid}/risk-assessments",
        json=_valid_payload(),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # Neue Risk-Gates brauchen Schema-Marker; alte Aufrufe werden defensiv normalisiert.
    assert body["knowledge_services_json"] == "{}"
    assert body["knowledge_instruments_json"] == "{}"
    assert body["income_sources_json"] == "[]"
