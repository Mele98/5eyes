"""Positive control for GOAL-VALUE-MODE-ROUNDTRIP-001 (round 40).

The audit finding is that the React goal-builder UI restricts the
``value_mode="real"`` choice to ``Vermoegensziel``-style goals, never
offering it for expense goals (``Einmalige_Ausgabe`` /
``Wiederkehrende_Ausgabe``). That is purely a frontend gap:

- ``services/goal_semantics.py`` validates ``value_mode`` against
  ``{"nominal", "real"}`` with no restriction by ``goal_type`` (see the
  check around line 160) -- ``real`` is accepted for every goal type,
  expense goals included.
- ``services/optimizer/goal_liabilities.py`` actually *applies* that mode:
  ``_build_einmalige_ausgabe()`` calls ``_is_real_value_mode(goal)`` and,
  when true, inflates the target amount via ``_inflate_at_year()`` exactly
  like it does for a real-mode ``Vermoegensziel`` in
  ``_build_wealth_target()``. There is no goal-type gate anywhere in that
  path either.

This test drives the REAL backend (FastAPI route in routers/wealth.py ->
domain validator in services/goal_semantics.py -> persistence) with a
one-off expense goal (``Einmalige_Ausgabe``) carrying
``value_mode="real"`` and asserts:

1. Creation succeeds (HTTP 201) -- the backend does not reject "real" for
   an expense goal.
2. The persisted/returned goal keeps ``value_mode == "real"`` -- it is not
   silently coerced to "nominal" anywhere in the create/read path.

This is expected to PASS today as a plain (non-xfail) regression /
positive control: it documents that the backend half of the contract
already works correctly, so the sibling release-blocking bug (covered by
a separate round-40 frontend test) must be fixed on the React side only,
without touching this backend behavior.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, get_db
from main import app
from models.users import User
from services.auth import get_current_user
from tests.risk_fixture_helpers import noop_lifespan


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_value_mode_real_expense.db'}",
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
def advisor_user() -> User:
    return User(
        id="goal-value-mode-real-advisor",
        username="goal-value-mode-real-advisor",
        password_hash="h",
        full_name="Goal Value Mode Real Advisor",
        role="advisor",
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user, monkeypatch):
    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def _create_api_mandate(auth_client: TestClient, advisor: User, suffix: str) -> str:
    client_response = auth_client.post(
        "/clients",
        json={
            "client_number": f"GOAL-VM-{suffix}",
            "first_name": "Goal",
            "last_name": "ValueModeReal",
            "advisor_id": advisor.id,
            "household_type": "Einzelperson",
        },
    )
    assert client_response.status_code == 201, client_response.text
    mandate_response = auth_client.post(
        f"/clients/{client_response.json()['id']}/mandates",
        json={
            "mandate_number": f"GOAL-VM-M-{suffix}",
            "mandate_type": "Anlageberatung",
        },
    )
    assert mandate_response.status_code == 201, mandate_response.text
    return mandate_response.json()["id"]


def _einmalige_ausgabe_real_payload() -> dict:
    """A backend-valid one-off expense goal requesting real (inflation-
    adjusted) valuation -- exactly the shape the React wizard currently
    never produces for this goal type, per the audit finding."""
    return {
        "goal_family": "Cashflow",
        "goal_type": "Einmalige_Ausgabe",
        "label": "Hauskauf-Anzahlung (real bewertet)",
        "rank": 1,
        "weight_bps": 5000,
        "goal_scope": "Beratungsvermögen",
        "value_mode": "real",
        "target_amount_rappen": 5_000_000,
        "target_date": "2036-01-01",
        "is_ongoing": False,
        "hardness": "Primär",
    }


def test_einmalige_ausgabe_with_real_value_mode_is_accepted_on_create(
    auth_client,
    advisor_user,
):
    mandate_id = _create_api_mandate(auth_client, advisor_user, "create")

    response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_einmalige_ausgabe_real_payload(),
    )

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["value_mode"] == "real"
    assert created["goal_type"] == "Einmalige_Ausgabe"


def test_einmalige_ausgabe_real_value_mode_persists_not_coerced_to_nominal(
    auth_client,
    advisor_user,
):
    mandate_id = _create_api_mandate(auth_client, advisor_user, "persist")

    create_response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_einmalige_ausgabe_real_payload(),
    )
    assert create_response.status_code == 201, create_response.text
    goal_id = create_response.json()["id"]

    get_response = auth_client.get(f"/mandates/{mandate_id}/goals")
    assert get_response.status_code == 200, get_response.text
    persisted = next(g for g in get_response.json() if g["id"] == goal_id)

    assert persisted["value_mode"] == "real"
