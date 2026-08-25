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
from models.users import User
from services.auth import get_current_user


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_cashflow_ist_contract.db'}",
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
        id="user-goal-ist-contract",
        username="advisor",
        password_hash="h",
        full_name="Advisor",
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


def _create_client_and_mandate(
    auth_client: TestClient,
    advisor_user: User,
) -> tuple[str, str]:
    client_response = auth_client.post(
        "/clients",
        json={
            "client_number": "GOAL-IST-001",
            "first_name": "Goal",
            "last_name": "Contract",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert client_response.status_code == 201, client_response.text
    client_id = client_response.json()["id"]

    mandate_response = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={
            "mandate_number": "GOAL-IST-M-001",
            "mandate_type": "Anlageberatung",
        },
    )
    assert mandate_response.status_code == 201, mandate_response.text
    return client_id, mandate_response.json()["id"]


def _return_goal_payload() -> dict:
    # Mirrors the explicit null-field contract emitted by saveGoal().
    return {
        "goal_family": "Rendite",
        "goal_type": "Renditeziel",
        "label": "Zielrendite Ruhestand",
        "notes": "Frontend-Vertrag",
        "rank": 2,
        "goal_scope": "Beratungsvermögen",
        "value_mode": "nominal",
        "target_amount_rappen": None,
        "target_wealth_rappen": None,
        "target_return_bps": 475,
        "success_probability_min_x100": 5000,
        "start_date": None,
        "horizon_years": 12,
        "target_date": None,
        "is_ongoing": False,
        "frequency": None,
        "hardness": "Primär",
        "probability_pct": 100,
        "pension_pillar": None,
    }


def test_frontend_return_goal_payload_posts_and_roundtrips(
    auth_client,
    advisor_user,
):
    _, mandate_id = _create_client_and_mandate(auth_client, advisor_user)

    response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_return_goal_payload(),
    )

    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["label"] == "Zielrendite Ruhestand"
    assert saved["target_return_bps"] == 475
    assert saved["target_amount_rappen"] is None
    assert saved["target_wealth_rappen"] is None
    assert saved["hardness"] == "Primär"

    reload_response = auth_client.get(f"/mandates/{mandate_id}/goals")
    assert reload_response.status_code == 200, reload_response.text
    assert reload_response.json() == [saved]


def test_frontend_hard_return_goal_returns_actionable_422(
    auth_client,
    advisor_user,
):
    _, mandate_id = _create_client_and_mandate(auth_client, advisor_user)
    payload = _return_goal_payload()
    payload["rank"] = 1
    payload["hardness"] = "Hart"

    response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=payload,
    )

    assert response.status_code == 422, response.text
    assert "Renditeziel darf nicht als 'hart' definiert werden" in response.text


def test_goal_create_and_update_do_not_change_ist_cashflow_projection(
    auth_client,
    advisor_user,
):
    client_id, mandate_id = _create_client_and_mandate(auth_client, advisor_user)
    income = auth_client.post(
        f"/clients/{client_id}/cashflows",
        json={
            "cashflow_type": "Income",
            "label": "Lohn",
            "amount_rappen": 10_000_000,
            "frequency": "jaehrlich",
            "nature": "wiederkehrend",
        },
    )
    expense = auth_client.post(
        f"/clients/{client_id}/cashflows",
        json={
            "cashflow_type": "Expense",
            "label": "Lebenskosten",
            "amount_rappen": 4_000_000,
            "frequency": "jaehrlich",
            "nature": "wiederkehrend",
        },
    )
    assert income.status_code == 201, income.text
    assert expense.status_code == 201, expense.text

    before = auth_client.get(
        f"/clients/{client_id}/cashflow-projection?horizon_years=20"
    )
    assert before.status_code == 200, before.text

    goal_response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Cashflow",
            "goal_type": "Pensionsausgabe",
            "label": "Lebenshaltung im Ruhestand",
            "rank": 1,
            "goal_scope": "Gesamtvermögen",
            "value_mode": "real",
            "target_amount_rappen": 7_200_000,
            "target_wealth_rappen": None,
            "target_return_bps": None,
            "success_probability_min_x100": 8000,
            "start_date": "2036-01-01",
            "horizon_years": 10,
            "target_date": None,
            "is_ongoing": True,
            "frequency": "jaehrlich",
            "hardness": "Hart",
            "probability_pct": 100,
            "pension_pillar": "BVG",
        },
    )
    assert goal_response.status_code == 201, goal_response.text

    after_create = auth_client.get(
        f"/clients/{client_id}/cashflow-projection?horizon_years=20"
    )
    assert after_create.status_code == 200, after_create.text
    assert after_create.json() == before.json()

    update_response = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal_response.json()['id']}",
        json={
            "label": "Lebenshaltung im Ruhestand aktualisiert",
            "target_amount_rappen": 8_000_000,
        },
    )
    assert update_response.status_code == 200, update_response.text

    after_update = auth_client.get(
        f"/clients/{client_id}/cashflow-projection?horizon_years=20"
    )
    assert after_update.status_code == 200, after_update.text
    assert after_update.json() == before.json()

