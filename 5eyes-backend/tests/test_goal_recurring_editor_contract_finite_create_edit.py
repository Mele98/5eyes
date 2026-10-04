"""Red test for GOAL-RECURRING-EDITOR-CONTRACT-001, Repro 1 (round 38).

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md.

The React goal wizard builds its create/update payload by unconditionally
nulling ``target_amount_rappen`` for every goal type except
``Einmalige_Ausgabe``, and by never sending ``start_date`` for a finite
recurring expense -- it only sends the wizard's end-date field as
``target_date``. This file drives the REAL backend call path (the FastAPI
route in routers/wealth.py, which normalizes the payload and then calls the
domain validator in services/goal_semantics.py) with exactly that
React-wizard-shaped payload for a finite ``Wiederkehrende_Ausgabe`` goal, on
both create and a no-op re-save (edit) of an already-valid goal.

These tests intentionally do not patch production validation code.

NOTE: against current `develop`, the real backend already correctly
fail-closes on this payload (HTTP 422) -- this is audit Positivkontrolle #1
("Der Backend-Complete-State-Guard blockiert unvollstaendige recurring Goals
heute mit 422") and must not regress. These are therefore plain green
regression/positive-control tests, not red/xfail tests: the actual
release-blocking gap is on the frontend side (it never lets the user supply
a valid payload at all), covered separately by the React-side round-38 red
tests for this same finding.
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
        f"sqlite:///{tmp_path / 'goal_recurring_editor_contract.db'}",
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
        id="goal-recurring-editor-advisor",
        username="goal-recurring-editor-advisor",
        password_hash="h",
        full_name="Goal Recurring Editor Advisor",
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
            "client_number": f"GOAL-RE-{suffix}",
            "first_name": "Goal",
            "last_name": "RecurringEditor",
            "advisor_id": advisor.id,
            "household_type": "Einzelperson",
        },
    )
    assert client_response.status_code == 201, client_response.text
    mandate_response = auth_client.post(
        f"/clients/{client_response.json()['id']}/mandates",
        json={
            "mandate_number": f"GOAL-RE-M-{suffix}",
            "mandate_type": "Anlageberatung",
        },
    )
    assert mandate_response.status_code == 201, mandate_response.text
    return mandate_response.json()["id"]


def _react_wizard_finite_recurring_payload() -> dict:
    """Exactly what reporting/'s buildGoalPayload() sends for a finite
    Wiederkehrende_Ausgabe goal: amount nulled, no start_date, the wizard's
    end-date field mapped onto target_date, is_ongoing explicitly False.
    """
    return {
        "goal_family": "Cashflow",
        "goal_type": "Wiederkehrende_Ausgabe",
        "label": "Befristete wiederkehrende Ausgabe (Editor-Repro)",
        "rank": 1,
        "weight_bps": 5000,
        "goal_scope": "Beratungsvermögen",
        "value_mode": "nominal",
        "target_amount_rappen": None,
        "frequency": "jaehrlich",
        "start_date": None,
        "target_date": "2040-01-01",
        "is_ongoing": False,
        "hardness": "Primär",
    }


def test_react_wizard_payload_for_finite_recurring_goal_is_rejected_on_create(
    auth_client,
    advisor_user,
):
    mandate_id = _create_api_mandate(auth_client, advisor_user, "create-finite-recurring")

    response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_react_wizard_finite_recurring_payload(),
    )

    assert response.status_code == 422, response.text
    assert "Zielbetrag" in response.text


def test_react_wizard_noop_edit_of_valid_finite_recurring_goal_is_rejected_not_silently_corrupted(
    auth_client,
    advisor_user,
):
    mandate_id = _create_api_mandate(auth_client, advisor_user, "noop-edit-finite-recurring")

    # A backend-correct payload: everything the domain validator actually
    # requires for a finite recurring expense is present.
    create_response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Cashflow",
            "goal_type": "Wiederkehrende_Ausgabe",
            "label": "Befristete wiederkehrende Ausgabe (gueltig)",
            "rank": 1,
            "weight_bps": 5000,
            "goal_scope": "Beratungsvermögen",
            "value_mode": "nominal",
            "target_amount_rappen": 120_000,
            "frequency": "jährlich",
            "start_date": "2026-01-01",
            "target_date": "2040-01-01",
            "is_ongoing": False,
            "hardness": "Primär",
        },
    )
    assert create_response.status_code == 201, create_response.text
    goal_id = create_response.json()["id"]
    original_amount = create_response.json()["target_amount_rappen"]
    assert original_amount == 120_000

    # The user re-opens the editor and saves again without touching
    # anything. The React wizard still rebuilds the payload the same
    # (buggy) way: it nulls target_amount_rappen and drops start_date.
    update_response = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal_id}",
        json=_react_wizard_finite_recurring_payload(),
    )

    assert update_response.status_code == 422, update_response.text

    # Whether or not the update is rejected, the persisted amount must
    # never have been silently nulled out by a passthrough update.
    get_response = auth_client.get(f"/mandates/{mandate_id}/goals")
    assert get_response.status_code == 200, get_response.text
    persisted = next(g for g in get_response.json() if g["id"] == goal_id)
    assert persisted["target_amount_rappen"] == original_amount
