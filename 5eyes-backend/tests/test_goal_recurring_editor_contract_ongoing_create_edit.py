"""Round 38 red test - GOAL-RECURRING-EDITOR-CONTRACT-001 (ongoing variant).

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md,
finding GOAL-RECURRING-EDITOR-CONTRACT-001, "Repro 1".

Repro 1 documents that the React goal wizard's `buildGoalPayload()` never
threads a collected amount/start timing through for recurring/pension goal
types (it unconditionally nulls `target_amount_rappen` outside
Einmalige_Ausgabe, and never requires `start_date`). Feeding that payload
shape into the REAL backend validator path
(`routers/wealth.py::_normalize_goal_payload` ->
`_validate_goal_payload_semantics`, which runs ahead of
`services/goal_semantics.py::validate_goal_model_input`) gets rejected with
HTTP 422 "Cashflow-Ziel benoetigt einen positiven Zielbetrag".

This file exercises the *ongoing* variant of Repro 1: `is_ongoing=True` with
no end date (`target_date=None`). The wizard still fails to collect/send
`target_amount_rappen` and `start_date`, so:

  1. CREATE with that payload shape 422s (same as Repro 1, just with the
     ongoing/no-end-date timing combination instead of a finite end date).
  2. A subsequent *no-op* EDIT of an already-valid ongoing recurring goal --
     opening the editor and saving without the advisor changing anything --
     also 422s. The wizard rebuilds and resends the FULL form state on save;
     because `buildGoalPayload()` nulls `target_amount_rappen`/never carries
     `start_date`, the resend explicitly includes
     `target_amount_rappen: null` / `start_date: null` in the update
     payload. `routers/wealth.py::_goal_effective()` honors an explicitly
     present (even if null) payload key over the persisted value, so the
     previously-valid goal's amount is wiped and the no-op save 422s.

Both assertions run the REAL FastAPI app (TestClient) against the REAL
`create_goal`/`update_goal` endpoints -- no validator is mocked.
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
from models.clients import Client  # noqa: F401 - SQLAlchemy metadata/relationships
from models.mandates import Mandate  # noqa: F401 - SQLAlchemy metadata/relationships
from models.users import User
from services.auth import get_current_user


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_recurring_editor_contract_ongoing.db'}",
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
        id="user-goal-recurring-ongoing",
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
            "client_number": "GOAL-REC-ONGOING-001",
            "first_name": "Ongoing",
            "last_name": "Client",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_mandate(auth_client: TestClient, client_id: str, number: str) -> str:
    response = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": number, "mandate_type": "Anlageberatung"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# Broken-wizard-shaped payload for an ONGOING recurring goal: real backend
# requires target_amount_rappen > 0 and (for a finite stream) start/end
# timing, but validateGoalForm()/buildGoalPayload() never collect/thread an
# amount or start_date through for Wiederkehrende_Ausgabe/Pensionsausgabe.
_BROKEN_ONGOING_RECURRING_PAYLOAD = {
    "goal_family": "Cashflow",
    "goal_type": "Wiederkehrende_Ausgabe",
    "label": "Lebenshaltungskosten",
    "rank": 1,
    "frequency": "jährlich",
    "is_ongoing": True,
    "target_date": None,
    "target_amount_rappen": None,
    "start_date": None,
    "hardness": "Primär",
}

# A complete, valid payload for the SAME ongoing recurring goal -- what the
# backend actually requires (amount + start present, is_ongoing=True,
# target_date=None for an open-ended stream).
_VALID_ONGOING_RECURRING_PAYLOAD = {
    "goal_family": "Cashflow",
    "goal_type": "Wiederkehrende_Ausgabe",
    "label": "Lebenshaltungskosten",
    "rank": 1,
    "frequency": "jährlich",
    "is_ongoing": True,
    "target_date": None,
    "target_amount_rappen": 60_000_00,
    "start_date": "2026-01-01",
    "hardness": "Primär",
}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RECURRING-EDITOR-CONTRACT-001 - round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_create_ongoing_recurring_goal_with_wizard_payload_shape_should_succeed(
    auth_client, advisor_user,
):
    """Repro 1 (ongoing variant): CREATE with the wizard's broken payload shape.

    is_ongoing=True, target_date=None (open-ended), but amount/start were
    never collected by the wizard. A correctly-fixed wizard contract would
    have required them client-side and never reach the backend in this
    shape; documenting the current (buggy) behaviour means asserting the
    call that SHOULD succeed instead 422s.
    """
    client_id = _create_client(auth_client, advisor_user)
    mandate_id = _create_mandate(auth_client, client_id, "GOAL-REC-ONGOING-CREATE")

    response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_BROKEN_ONGOING_RECURRING_PAYLOAD,
    )

    assert response.status_code == 201, response.text


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RECURRING-EDITOR-CONTRACT-001 - round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_noop_edit_of_valid_ongoing_recurring_goal_should_not_wipe_amount(
    auth_client, advisor_user,
):
    """Repro 1 (ongoing variant): a no-op EDIT must not break a valid goal.

    First create a goal the normal (valid) way -- establishing a correctly
    persisted ongoing recurring goal. Then simulate the wizard's "open
    editor, change nothing, save" path: it rebuilds the full form state and
    resends it, but buildGoalPayload() nulls target_amount_rappen/never
    carries start_date, so the PUT explicitly includes
    target_amount_rappen=None/start_date=None. A correctly-fixed editor
    contract would resend the existing amount/start unchanged and the save
    would succeed with the amount intact; documenting the current (buggy)
    behaviour means asserting that expected outcome, which currently 422s
    instead.
    """
    client_id = _create_client(auth_client, advisor_user)
    mandate_id = _create_mandate(auth_client, client_id, "GOAL-REC-ONGOING-NOOP-EDIT")

    create_response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_VALID_ONGOING_RECURRING_PAYLOAD,
    )
    assert create_response.status_code == 201, create_response.text
    goal_id = create_response.json()["id"]

    noop_edit_payload = dict(_BROKEN_ONGOING_RECURRING_PAYLOAD)
    update_response = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal_id}",
        json=noop_edit_payload,
    )

    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["target_amount_rappen"] == (
        _VALID_ONGOING_RECURRING_PAYLOAD["target_amount_rappen"]
    )
