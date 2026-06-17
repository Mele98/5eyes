from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import settings
from database import Base, get_db
from main import app
from models.clients import Client
from models.users import User
from services.auth import get_current_user
from services.data_classification import PHASE_ZERO_BLOCK_DETAIL


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'data_classification_gate.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="advisor-data-gate",
        username="advisor-data-gate",
        password_hash="h",
        full_name="Data Gate Advisor",
        role="advisor",
        is_active=1,
        created_at="2026-06-12T00:00:00.000Z",
        updated_at="2026-06-12T00:00:00.000Z",
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


def _client_payload(number: str, classification: str | None = None) -> dict:
    payload = {
        "client_number": number,
        "first_name": "Phase",
        "last_name": "Zero",
        "advisor_id": "advisor-data-gate",
    }
    if classification is not None:
        payload["data_classification"] = classification
    return payload


def _create_synthetic_client(auth_client: TestClient, number: str = "E0-CLIENT") -> str:
    response = auth_client.post(
        "/clients",
        json=_client_payload(number, "synthetic"),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_mandate(auth_client: TestClient, client_id: str) -> str:
    response = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": f"E0-M-{client_id[-8:]}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _assert_phase_zero_block(response) -> None:
    assert response.status_code == 403
    assert response.json() == {"detail": PHASE_ZERO_BLOCK_DETAIL}


def test_real_client_is_blocked_when_gate_is_closed(
    auth_client,
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        "/clients",
        json=_client_payload("E0-REAL", "real"),
    )

    _assert_phase_zero_block(response)
    with session_factory() as session:
        assert session.query(Client).filter(Client.client_number == "E0-REAL").count() == 0


def test_synthetic_client_is_allowed_when_gate_is_closed(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        "/clients",
        json=_client_payload("E0-SYNTHETIC", "synthetic"),
    )

    assert response.status_code == 201, response.text
    assert "data_classification" not in response.json()


def test_omitted_classification_defaults_to_synthetic(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        "/clients",
        json=_client_payload("E0-DEFAULT"),
    )

    assert response.status_code == 201, response.text


def test_real_client_is_allowed_when_gate_is_open(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", True)

    response = auth_client.post(
        "/clients",
        json=_client_payload("E0-OPEN", "real"),
    )

    assert response.status_code == 201, response.text
    assert "data_classification" not in response.json()


def test_real_client_update_is_blocked_without_mutation(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    client_id = _create_synthetic_client(auth_client)

    response = auth_client.put(
        f"/clients/{client_id}",
        json={"last_name": "MustNotPersist", "data_classification": "real"},
    )

    _assert_phase_zero_block(response)
    current = auth_client.get(f"/clients/{client_id}")
    assert current.status_code == 200
    assert current.json()["last_name"] == "Zero"


def test_cashflow_create_and_update_enforce_gate(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    client_id = _create_synthetic_client(auth_client, "E0-CASHFLOW")
    base_payload = {
        "cashflow_type": "Income",
        "label": "Synthetic salary",
        "amount_rappen": 10_000_00,
        "frequency": "jährlich",
        "nature": "wiederkehrend",
    }

    blocked_create = auth_client.post(
        f"/clients/{client_id}/cashflows",
        json={**base_payload, "data_classification": "real"},
    )
    _assert_phase_zero_block(blocked_create)

    created = auth_client.post(
        f"/clients/{client_id}/cashflows",
        json={**base_payload, "data_classification": "synthetic"},
    )
    assert created.status_code == 201, created.text
    cashflow_id = created.json()["id"]

    blocked_update = auth_client.put(
        f"/clients/{client_id}/cashflows/{cashflow_id}",
        json={"label": "MustNotPersist", "data_classification": "real"},
    )
    _assert_phase_zero_block(blocked_update)

    listed = auth_client.get(f"/clients/{client_id}/cashflows")
    assert listed.status_code == 200
    assert listed.json()[0]["label"] == "Synthetic salary"


def test_goal_create_and_update_enforce_gate(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    client_id = _create_synthetic_client(auth_client, "E0-GOAL")
    mandate_id = _create_mandate(auth_client, client_id)
    base_payload = {
        "goal_family": "Rendite",
        "goal_type": "Renditeziel",
        "label": "Synthetic return goal",
        "rank": 1,
        "target_return_bps": 400,
        "hardness": "Primär",
    }

    blocked_create = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={**base_payload, "data_classification": "real"},
    )
    _assert_phase_zero_block(blocked_create)

    created = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={**base_payload, "data_classification": "synthetic"},
    )
    assert created.status_code == 201, created.text
    goal_id = created.json()["id"]

    blocked_update = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal_id}",
        json={"label": "MustNotPersist", "data_classification": "real"},
    )
    _assert_phase_zero_block(blocked_update)

    listed = auth_client.get(f"/mandates/{mandate_id}/goals")
    assert listed.status_code == 200
    assert listed.json()[0]["label"] == "Synthetic return goal"


def test_invalid_data_classification_is_rejected_by_schema(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        "/clients",
        json=_client_payload("E0-INVALID", "confidential"),
    )

    assert response.status_code == 422


def test_root_info_exposes_data_gate(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.get("/")

    assert response.status_code == 200
    assert response.json()["allow_real_client_data"] is False
