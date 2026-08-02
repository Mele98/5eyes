"""sec-f4 (2026-08-02, Independent Security Audit F4): Phase-0-Datenklassi-
fizierungs-Gate (enforce_data_classification) fehlte komplett fuer
Planning-Assumptions (upsert_planning_assumptions / create_planning_assumptions
in routers/wealth.py) -- analog zur bereits gefixten Luecke bei WealthInflow
(rls-3, siehe tests/test_data_classification_gate.py::
test_wealth_inflow_create_and_update_enforce_gate). Waehrend Phase 0
(settings.allow_real_client_data=False) durfte ein Advisor ueber
PUT/POST /mandates/{id}/planning-assumptions mit
data_classification="real" reale Planungsannahmen (Pensionsalter,
Lebenserwartung, Inflationsannahme etc.) persistieren, obwohl das Gate fuer
alle anderen Wealth-Endpunkte bereits griff.

PlanningAssumption (models/wealth.py) hat keine data_classification-Spalte --
das Feld auf dem Create-Schema dient ausschliesslich der Enforcement und wird
vor dem Persistieren aus dem dict gepoppt (siehe routers/wealth.py).
"""
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
from models.wealth import PlanningAssumption
from models.users import User
from services.auth import get_current_user
from services.data_classification import PHASE_ZERO_BLOCK_DETAIL


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'planning_assumption_data_classification_gate.db'}",
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
        id="advisor-pa-gate",
        username="advisor-pa-gate",
        password_hash="h",
        full_name="Planning Assumption Gate Advisor",
        role="advisor",
        is_active=1,
        created_at="2026-08-02T00:00:00.000Z",
        updated_at="2026-08-02T00:00:00.000Z",
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


def _assert_phase_zero_block(response) -> None:
    assert response.status_code == 403
    assert response.json() == {"detail": PHASE_ZERO_BLOCK_DETAIL}


def _create_client(auth_client: TestClient, number: str = "PA-CLIENT") -> str:
    response = auth_client.post(
        "/clients",
        json={
            "client_number": number,
            "first_name": "Planning",
            "last_name": "Assumption",
            "advisor_id": "advisor-pa-gate",
            "data_classification": "synthetic",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_mandate(auth_client: TestClient, client_id: str) -> str:
    response = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": f"PA-M-{client_id[-8:]}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---------------------------------------------------------------------------
# PUT /mandates/{id}/planning-assumptions (upsert_planning_assumptions)
# ---------------------------------------------------------------------------

def test_upsert_planning_assumptions_blocks_real_when_gate_closed(
    auth_client, session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    client_id = _create_client(auth_client, "PA-UPSERT-REAL")
    mandate_id = _create_mandate(auth_client, client_id)

    response = auth_client.put(
        f"/mandates/{mandate_id}/planning-assumptions",
        json={"retirement_age_primary": 65, "data_classification": "real"},
    )

    _assert_phase_zero_block(response)
    with session_factory() as session:
        assert session.query(PlanningAssumption).filter(
            PlanningAssumption.mandate_id == mandate_id
        ).count() == 0


def test_upsert_planning_assumptions_default_synthetic_still_succeeds(
    auth_client, session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    client_id = _create_client(auth_client, "PA-UPSERT-DEFAULT")
    mandate_id = _create_mandate(auth_client, client_id)

    response = auth_client.put(
        f"/mandates/{mandate_id}/planning-assumptions",
        json={"retirement_age_primary": 65, "inflation_assumption_bps": 150},
    )

    assert response.status_code == 200, response.text
    assert response.json()["inflation_assumption_bps"] == 150
    with session_factory() as session:
        pa = session.query(PlanningAssumption).filter(
            PlanningAssumption.mandate_id == mandate_id
        ).one()
        assert pa.retirement_age_primary == 65


def test_upsert_planning_assumptions_explicit_synthetic_still_succeeds(
    auth_client, session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    client_id = _create_client(auth_client, "PA-UPSERT-EXPLICIT-SYN")
    mandate_id = _create_mandate(auth_client, client_id)

    response = auth_client.put(
        f"/mandates/{mandate_id}/planning-assumptions",
        json={"retirement_age_primary": 63, "data_classification": "synthetic"},
    )

    assert response.status_code == 200, response.text
    with session_factory() as session:
        pa = session.query(PlanningAssumption).filter(
            PlanningAssumption.mandate_id == mandate_id
        ).one()
        assert pa.retirement_age_primary == 63


def test_upsert_planning_assumptions_allows_real_when_gate_open(
    auth_client, session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "allow_real_client_data", True)
    client_id = _create_client(auth_client, "PA-UPSERT-OPEN")
    mandate_id = _create_mandate(auth_client, client_id)

    response = auth_client.put(
        f"/mandates/{mandate_id}/planning-assumptions",
        json={"retirement_age_primary": 67, "data_classification": "real"},
    )

    assert response.status_code == 200, response.text
    with session_factory() as session:
        pa = session.query(PlanningAssumption).filter(
            PlanningAssumption.mandate_id == mandate_id
        ).one()
        assert pa.retirement_age_primary == 67


def test_upsert_planning_assumptions_new_version_blocks_real_when_gate_closed(
    auth_client, session_factory, monkeypatch
):
    """Der zweite Upsert-Zweig (Versionierung ueber bestehende `existing`
    Zeile) muss dieselbe Enforcement anwenden wie der Erst-Anlage-Zweig."""
    monkeypatch.setattr(settings, "allow_real_client_data", True)
    client_id = _create_client(auth_client, "PA-UPSERT-V2")
    mandate_id = _create_mandate(auth_client, client_id)
    first = auth_client.put(
        f"/mandates/{mandate_id}/planning-assumptions",
        json={"retirement_age_primary": 65},
    )
    assert first.status_code == 200, first.text

    monkeypatch.setattr(settings, "allow_real_client_data", False)
    response = auth_client.put(
        f"/mandates/{mandate_id}/planning-assumptions",
        json={"retirement_age_primary": 66, "data_classification": "real"},
    )

    _assert_phase_zero_block(response)
    with session_factory() as session:
        pa = session.query(PlanningAssumption).filter(
            PlanningAssumption.mandate_id == mandate_id,
            PlanningAssumption.is_current == 1,
        ).one()
        # Muss weiterhin die erste (65), nicht die geblockte zweite (66) Version sein.
        assert pa.retirement_age_primary == 65


# ---------------------------------------------------------------------------
# POST /mandates/{id}/planning-assumptions (create_planning_assumptions)
# ---------------------------------------------------------------------------

def test_create_planning_assumptions_blocks_real_when_gate_closed(
    auth_client, session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    client_id = _create_client(auth_client, "PA-CREATE-REAL")
    mandate_id = _create_mandate(auth_client, client_id)

    response = auth_client.post(
        f"/mandates/{mandate_id}/planning-assumptions",
        json={"life_expectancy_primary": 95, "data_classification": "real"},
    )

    _assert_phase_zero_block(response)
    with session_factory() as session:
        assert session.query(PlanningAssumption).filter(
            PlanningAssumption.mandate_id == mandate_id
        ).count() == 0


def test_create_planning_assumptions_default_synthetic_still_succeeds(
    auth_client, session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    client_id = _create_client(auth_client, "PA-CREATE-DEFAULT")
    mandate_id = _create_mandate(auth_client, client_id)

    response = auth_client.post(
        f"/mandates/{mandate_id}/planning-assumptions",
        json={"life_expectancy_primary": 95},
    )

    assert response.status_code == 201, response.text
    assert response.json()["life_expectancy_primary"] == 95
    with session_factory() as session:
        pa = session.query(PlanningAssumption).filter(
            PlanningAssumption.mandate_id == mandate_id
        ).one()
        assert pa.life_expectancy_primary == 95


def test_create_planning_assumptions_allows_real_when_gate_open(
    auth_client, session_factory, monkeypatch
):
    monkeypatch.setattr(settings, "allow_real_client_data", True)
    client_id = _create_client(auth_client, "PA-CREATE-OPEN")
    mandate_id = _create_mandate(auth_client, client_id)

    response = auth_client.post(
        f"/mandates/{mandate_id}/planning-assumptions",
        json={"life_expectancy_primary": 90, "data_classification": "real"},
    )

    assert response.status_code == 201, response.text
    with session_factory() as session:
        pa = session.query(PlanningAssumption).filter(
            PlanningAssumption.mandate_id == mandate_id
        ).one()
        assert pa.life_expectancy_primary == 90
