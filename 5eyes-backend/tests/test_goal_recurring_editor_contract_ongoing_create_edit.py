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

CORRECTION (see sibling test_goal_recurring_editor_contract_finite_create_edit.py
for the same fix applied to the finite variant): the backend correctly
fail-closing on this literally-incomplete payload (no amount at all) is
audit Positivkontrolle #1 and must NEVER change -- the documented repair
contract for this finding is entirely frontend-side (GoalFormInput becomes a
discriminated union that requires amount/start/end semantics before it ever
reaches the backend). Asserting that THIS exact broken payload shape should
one day return 201/200 tests the wrong layer: a correctly-fixed wizard would
never send this payload in the first place, so that assertion could never
become true without wrongly loosening the backend guard (one of the
audit's explicitly listed "Scheinfixes"). These are therefore rewritten as
positive-control tests: the broken shape keeps 422ing (regression guard on
Positivkontrolle #1), and a COMPLETE payload for the same ongoing goal is
accepted and preserved across a no-op edit (regression guard on the backend
half of the contract the frontend fix will eventually rely on).
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


def test_create_ongoing_recurring_goal_with_wizard_payload_shape_is_rejected(
    auth_client, advisor_user,
):
    """Repro 1 (ongoing variant), positive control: CREATE with the wizard's
    broken payload shape (no amount, no start_date) must keep 422ing. This
    guards Positivkontrolle #1 -- the backend must never be loosened to
    accept this shape; the real fix is the frontend never sending it.
    """
    client_id = _create_client(auth_client, advisor_user)
    mandate_id = _create_mandate(auth_client, client_id, "GOAL-REC-ONGOING-CREATE")

    response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_BROKEN_ONGOING_RECURRING_PAYLOAD,
    )

    assert response.status_code == 422, response.text


def test_create_and_noop_edit_of_complete_ongoing_recurring_goal_preserves_amount(
    auth_client, advisor_user,
):
    """Positive control: a COMPLETE ongoing recurring payload (real amount +
    start_date) is accepted, and a no-op re-save of that same complete
    payload preserves the amount. This is the backend half of the contract
    a correctly-fixed wizard will rely on once it stops sending the broken
    shape above.
    """
    client_id = _create_client(auth_client, advisor_user)
    mandate_id = _create_mandate(auth_client, client_id, "GOAL-REC-ONGOING-NOOP-EDIT")

    create_response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_VALID_ONGOING_RECURRING_PAYLOAD,
    )
    assert create_response.status_code == 201, create_response.text
    goal_id = create_response.json()["id"]

    update_response = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal_id}",
        json=_VALID_ONGOING_RECURRING_PAYLOAD,
    )

    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["target_amount_rappen"] == (
        _VALID_ONGOING_RECURRING_PAYLOAD["target_amount_rappen"]
    )
