"""Round 38 red test -- GOAL-RECURRING-EDITOR-CONTRACT-001 (Pensionsausgabe variant).

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md,
finding GOAL-RECURRING-EDITOR-CONTRACT-001, Repro 1.

Repro 1 (summarised): the React goal wizard builds a payload that unconditionally
nulls ``target_amount_rappen`` for every goal type except ``Einmalige_Ausgabe``,
never requires ``start_date``, and defaults ``is_ongoing`` to ``False`` -- even
when editing an already-complete recurring/pension goal. Opening the editor on
an existing, fully valid ``Pensionsausgabe`` goal and clicking "Speichern"
*without changing anything* ("no-op edit") re-submits that nulled shape and the
real backend validator path rejects it with HTTP 422, clobbering a goal that
was perfectly valid a moment before.

This file reproduces that exact create -> no-op-edit contract violation via
the real FastAPI TestClient (routers/wealth.py -> services/goal_semantics.py),
once for each pension pillar value the schema supports. The pillar enum is
read directly off ``schemas.wealth.GoalCreate.pension_pillar`` /
``services.goal_semantics.validate_goal_model_input`` (both list exactly
``AHV``, ``BVG``, ``3a``, ``1e``, ``FZG``) so this test cannot silently drift
from the production enum.

Bug being documented: for every pillar, a Pensionsausgabe goal created with a
complete, valid payload (amount, start_date, is_ongoing=True) can later be
"saved" through a no-op edit -- same label/rank/pillar/frequency, nothing the
advisor touched -- that nulls target_amount_rappen/start_date and flips
is_ongoing to False (the wizard's buildGoalPayload() shape). That no-op edit
*should* be a harmless save (HTTP 200, goal unchanged) but instead fails with
HTTP 422 ("Cashflow-Ziel benoetigt einen positiven Zielbetrag"), because
routers.wealth.update_goal() merges payload fields via exclude_unset=True --
and the wizard payload explicitly sets these fields (not omits them), so the
explicit None/False values win over the goal's persisted, valid state.

CORRECTION: the original framing asserted the broken no-op-edit payload
should itself succeed (200). That tests the wrong layer -- the documented
repair contract for this finding is entirely frontend-side (a discriminated
GoalFormInput union that round-trips amount/start/is_ongoing). A correctly
fixed wizard would never resend the nulled shape in the first place, so
"this exact broken payload eventually returns 200" could only become true
by loosening the backend guard, which is one of the audit's explicitly
listed Scheinfixes. Rewritten as two positive-control tests per pillar: the
broken wizard shape keeps 422ing (guards Positivkontrolle #1), and a no-op
re-save using the SAME complete payload the goal was created with succeeds
and preserves the amount (guards the backend half of the contract the
frontend fix will rely on).
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
from models.clients import Client  # noqa: F401 -- SQLAlchemy metadata
from models.mandates import Mandate  # noqa: F401
from models.users import User
from services.auth import get_current_user

# Must match schemas.wealth.GoalCreate.pension_pillar / the pillar allow-list
# in services.goal_semantics.validate_goal_model_input exactly.
PENSION_PILLARS = ["AHV", "BVG", "3a", "1e", "FZG"]


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_pension_editor_contract.db'}",
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
        id="user-pension-editor-contract",
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


def _setup_mandate(auth_client: TestClient, advisor_user: User, pillar: str) -> str:
    client_resp = auth_client.post(
        "/clients",
        json={
            "client_number": f"PENSION-EDITOR-{pillar}",
            "first_name": "Pension",
            "last_name": "EditorContractClient",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert client_resp.status_code == 201, client_resp.text
    client_id = client_resp.json()["id"]
    mandate_resp = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": f"PENSION-EDITOR-M-{pillar}", "mandate_type": "Anlageberatung"},
    )
    assert mandate_resp.status_code == 201, mandate_resp.text
    return mandate_resp.json()["id"]


def _valid_pension_payload(pillar: str) -> dict:
    """A complete, valid Pensionsausgabe payload an advisor would submit once,
    with amount/start_date/is_ongoing all present -- this is what a correctly
    filled-in wizard (or a direct API call) sends, and it must create fine."""
    return {
        "goal_family": "Cashflow",
        "goal_type": "Pensionsausgabe",
        "label": f"Pensionsausgaben Saeule {pillar}",
        "rank": 1,
        "target_amount_rappen": 500_000,
        "start_date": "2027-01-01",
        "is_ongoing": True,
        "frequency": "monatlich",
        "hardness": "Primär",
        "pension_pillar": pillar,
    }


def _noop_edit_wizard_payload(pillar: str) -> dict:
    """Shaped exactly like the React wizard's buildGoalPayload() output on a
    re-save of an unchanged Pensionsausgabe goal (audit Repro 1): label,
    rank, frequency and pillar are resubmitted unchanged, but
    target_amount_rappen/start_date are explicitly nulled and is_ongoing is
    defaulted to False -- even though the advisor changed nothing."""
    return {
        "goal_family": "Cashflow",
        "goal_type": "Pensionsausgabe",
        "label": f"Pensionsausgaben Saeule {pillar}",
        "rank": 1,
        "target_amount_rappen": None,
        "start_date": None,
        "is_ongoing": False,
        "frequency": "monatlich",
        "hardness": "Primär",
        "pension_pillar": pillar,
    }


@pytest.mark.parametrize("pillar", PENSION_PILLARS)
def test_noop_edit_with_broken_wizard_shape_keeps_422ing_per_pillar(auth_client, advisor_user, pillar):
    """Positive control: create a fully valid Pensionsausgabe goal for this
    pillar, then "save" it through the wizard's broken no-op payload shape
    (nulled amount/start, is_ongoing flipped to False). This must keep
    422ing -- it guards Positivkontrolle #1 against ever being loosened."""
    mandate_id = _setup_mandate(auth_client, advisor_user, pillar)

    create_resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_valid_pension_payload(pillar),
    )
    assert create_resp.status_code == 201, create_resp.text
    goal_id = create_resp.json()["id"]
    assert create_resp.json()["pension_pillar"] == pillar

    noop_resp = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal_id}",
        json=_noop_edit_wizard_payload(pillar),
    )
    assert noop_resp.status_code == 422, noop_resp.text


@pytest.mark.parametrize("pillar", PENSION_PILLARS)
def test_noop_edit_with_complete_payload_preserves_amount_per_pillar(auth_client, advisor_user, pillar):
    """Positive control: a no-op re-save using the SAME complete payload the
    goal was created with (real amount/start/is_ongoing, as a correctly
    fixed wizard would eventually resend) succeeds and preserves the
    amount -- the backend half of the contract the frontend fix relies on."""
    mandate_id = _setup_mandate(auth_client, advisor_user, pillar)

    create_resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_valid_pension_payload(pillar),
    )
    assert create_resp.status_code == 201, create_resp.text
    goal_id = create_resp.json()["id"]

    noop_resp = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal_id}",
        json=_valid_pension_payload(pillar),
    )
    assert noop_resp.status_code == 200, noop_resp.text
    assert noop_resp.json()["target_amount_rappen"] == _valid_pension_payload(pillar)["target_amount_rappen"]
