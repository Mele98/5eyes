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
from models.review import AdvisoryLog, RecommendationRun
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
    payload = {
        "entry_type": "Jahresreview",
        "title": "Review 2026",
        "description": "Strategie mit Kunde besprochen",
        "decision": "Transaktion empfohlen",
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

    with session_factory() as s:
        entry = s.query(AdvisoryLog).filter(AdvisoryLog.id == entry_id).first()
        assert entry is not None
        assert entry.status == "Beschlossen"


def test_advisory_log_status_transition_beschlossen_to_umgesetzt(session_factory, auth_client, advisor_user):
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

    with session_factory() as s:
        entry = s.query(AdvisoryLog).filter(AdvisoryLog.id == entry_id).first()
        assert entry is not None
        assert entry.status == "Umgesetzt"
