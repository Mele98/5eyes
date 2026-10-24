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
from models.allocation import TargetAllocation
from models.clients import Client  # noqa: F401 - imported for SQLAlchemy metadata/relationships
from models.mandates import Mandate  # noqa: F401 - imported for SQLAlchemy metadata/relationships
from models.users import User
from services.auth import get_current_user


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_schema_field_isolation.db'}",
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
        id="user-goal-schema",
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


def _create_client(auth_client: TestClient, advisor_user: User) -> str:
    response = auth_client.post(
        "/clients",
        json={
            "client_number": "GOAL-SCHEMA-001",
            "first_name": "Schema",
            "last_name": "Client",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_mandate(auth_client: TestClient, client_id: str, number: str = "GOAL-SCHEMA-M-001") -> str:
    response = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": number, "mandate_type": "Anlageberatung"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _post_goal(auth_client: TestClient, advisor_user: User, payload: dict, mandate_suffix: str):
    client_id = _create_client(auth_client, advisor_user)
    mandate_id = _create_mandate(auth_client, client_id, f"GOAL-SCHEMA-{mandate_suffix}")
    return auth_client.post(f"/mandates/{mandate_id}/goals", json=payload)


def test_return_goal_rejects_target_amount(auth_client, advisor_user):
    response = _post_goal(
        auth_client,
        advisor_user,
        {
            "goal_family": "Rendite",
            "goal_type": "Renditeziel",
            "label": "Renditeziel",
            "rank": 1,
            "target_return_bps": 450,
            "target_amount_rappen": 1_000_000_00,
            "hardness": "Opportunistisch",
        },
        "RETURN-AMOUNT",
    )

    assert response.status_code == 422, response.text
    assert "Feld 'target_amount_rappen' ist für Zieltyp 'Renditeziel' nicht erlaubt" in response.text


def test_wealth_goal_rejects_target_return(auth_client, advisor_user):
    response = _post_goal(
        auth_client,
        advisor_user,
        {
            "goal_family": "Vermögen",
            "goal_type": "Vermoegensziel",
            "label": "Mindestvermögen",
            "rank": 1,
            "target_wealth_rappen": 1_500_000_00,
            "target_return_bps": 450,
            "horizon_years": 10,
            "hardness": "Primär",
        },
        "WEALTH-RETURN",
    )

    assert response.status_code == 422, response.text
    assert "Feld 'target_return_bps' ist für Zieltyp 'Vermoegensziel' nicht erlaubt" in response.text


def test_pension_goal_rejects_target_return(auth_client, advisor_user):
    response = _post_goal(
        auth_client,
        advisor_user,
        {
            "goal_family": "Cashflow",
            "goal_type": "Pensionsausgabe",
            "label": "Pension",
            "rank": 1,
            "target_amount_rappen": 80_000_00,
            "target_return_bps": 450,
            "frequency": "jährlich",
            "start_date": "2035-01-01",
            "hardness": "Hart",
        },
        "PENSION-RETURN",
    )

    assert response.status_code == 422, response.text
    assert "Feld 'target_return_bps' ist für Zieltyp 'Pensionsausgabe' nicht erlaubt" in response.text


def test_maximization_goal_rejects_target_amount(auth_client, advisor_user):
    response = _post_goal(
        auth_client,
        advisor_user,
        {
            "goal_family": "Maximierung",
            "goal_type": "Maximierung",
            "label": "Opportunistisches Wachstum",
            "rank": 1,
            "target_amount_rappen": 500_000_00,
            "hardness": "Opportunistisch",
        },
        "MAX-AMOUNT",
    )

    assert response.status_code == 422, response.text
    assert "Feld 'target_amount_rappen' ist für Zieltyp 'Maximierung' nicht erlaubt" in response.text


def test_return_goal_rejects_hardness_hart(auth_client, advisor_user):
    response = _post_goal(
        auth_client,
        advisor_user,
        {
            "goal_family": "Rendite",
            "goal_type": "Renditeziel",
            "label": "Renditeziel",
            "rank": 1,
            "target_return_bps": 450,
            "hardness": "hart",
        },
        "RETURN-HARD",
    )

    assert response.status_code == 422, response.text
    assert "Renditeziel darf nicht als 'hart' definiert werden" in response.text


def test_return_goal_happy_path_defaults_success_probability(auth_client, advisor_user):
    response = _post_goal(
        auth_client,
        advisor_user,
        {
            "goal_family": "Rendite",
            "goal_type": "Renditeziel",
            "label": "Renditeziel",
            "rank": 1,
            "target_return_bps": 450,
            "hardness": "Opportunistisch",
        },
        "RETURN-OK",
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["target_return_bps"] == 450
    assert body["target_amount_rappen"] is None
    assert body["success_probability_min_x100"] == 5000


def test_one_off_goal_happy_path_defaults_success_probability(auth_client, advisor_user):
    response = _post_goal(
        auth_client,
        advisor_user,
        {
            "goal_family": "Cashflow",
            "goal_type": "Einmalige_Ausgabe",
            "label": "Eigenmittel",
            "rank": 1,
            "target_amount_rappen": 250_000_00,
            "target_date": "2030-01-01",
            "hardness": "Primär",
        },
        "ONE-OFF-OK",
    )

    assert response.status_code == 201, response.text
    assert response.json()["success_probability_min_x100"] == 8000


def test_target_allocation_stage1_fields_are_nullable_smoke(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'target_allocation_stage1.db'}")
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        with sf() as session:
            allocation = TargetAllocation(
                id="ta-stage1",
                mandate_id="mandate-stage1",
                version=1,
                is_current=1,
                target_equities_bps=4000,
                target_bonds_bps=4000,
                target_real_estate_bps=1000,
                target_alternatives_bps=500,
                target_liquidity_bps=500,
                band_equities_min_bps=3000,
                band_equities_max_bps=5000,
                band_bonds_min_bps=3000,
                band_bonds_max_bps=5000,
                band_real_estate_min_bps=0,
                band_real_estate_max_bps=2000,
                band_alternatives_min_bps=0,
                band_alternatives_max_bps=1000,
                band_liquidity_min_bps=200,
                band_liquidity_max_bps=1000,
                policy_id="policy-stage1",
                set_by="user-stage1",
                set_at=_utc_now_iso(),
                created_at=_utc_now_iso(),
                updated_at=_utc_now_iso(),
            )
            session.add(allocation)
            session.commit()
            session.refresh(allocation)

            assert allocation.risky_fraction_bps_at_generation is None
            assert allocation.risk_budget_bps_at_generation is None
            assert allocation.limiting_factor is None
            assert allocation.goal_achievability_json is None
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
