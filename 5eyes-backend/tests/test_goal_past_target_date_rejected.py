"""GOAL-PAST-DATE-UI-001.

Live reproduction (2026-10-09) in the real production database: a Renditeziel
goal (target_return_bps=300, horizon_years=10) was saved with
target_date='2025-01-01' -- already more than a year in the past at creation
time. Root cause, two independent layers:

1. Frontend (5eyes-electron/frontend/5eyes_v2.html, goalEditorHorizonYears()):
   when a target_date is set but resolves to a non-positive (past) duration,
   the function fell through to reading the #nz-horizon input's raw value
   instead of returning "no valid date-derived horizon". That raw value is
   whatever was last typed or defaulted (resetGoalModal() sets it to '10'),
   so the UI silently displayed and saved a plausible-looking positive
   horizon for a goal whose date had already passed, hiding the problem
   entirely from the advisor.

2. Neither the frontend's saveGoal() nor the backend's
   routers.wealth._normalize_goal_payload() ever compared target_date against
   today -- only the relative ordering of start_date vs target_date was
   checked. A goal's target_date is always a future due/evaluation anchor
   (unlike a Cashflow's valid_until, which legitimately can be in the past
   for an expired entry), so this was a genuine validation gap.

Fix is deliberately scoped to the create/update entry point only
(routers.wealth._normalize_goal_payload), not to
services.goal_semantics.validate_goal_model_input -- that shared validator is
also re-run by services.portfolio_engine._validate_active_goal_inputs() for
EVERY already-active goal on every allocation Generate/Reload. Rejecting past
target_date there would turn any other mandate's already-overdue goal into a
hard block on that mandate's entire allocation calculation, which is exactly
the blast-radius risk flagged in
docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
(GOAL-PAST-DATE-LIFECYCLE-001) as needing a full lifecycle contract, not a
naive blocking fix. This test only closes the narrower data-entry gap: a NEW
or EDITED goal can no longer be saved with a past target_date.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = BACKEND_ROOT.parents[0] / "5eyes-electron" / "frontend" / "5eyes_v2.html"

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.clients import Client  # noqa: F401,E402 — SQLAlchemy metadata
from models.mandates import Mandate  # noqa: F401,E402
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_past_target_date.db'}",
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
        id="user-past-date",
        username="advisor-past-date",
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


def _setup_mandate(auth_client: TestClient, advisor_user: User) -> str:
    client_resp = auth_client.post(
        "/clients",
        json={
            "client_number": "PAST-DATE-001",
            "first_name": "Past",
            "last_name": "DateClient",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert client_resp.status_code == 201, client_resp.text
    client_id = client_resp.json()["id"]
    mandate_resp = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "PAST-DATE-M-001", "mandate_type": "Anlageberatung"},
    )
    assert mandate_resp.status_code == 201, mandate_resp.text
    return mandate_resp.json()["id"]


def _renditeziel_payload(target_date: str) -> dict:
    return {
        "goal_family": "Rendite",
        "goal_type": "Renditeziel",
        "label": "Renditeziel",
        "rank": 2,
        "target_return_bps": 300,
        "horizon_years": 10,
        "target_date": target_date,
        "hardness": "Primär",
        "goal_scope": "Beratungsvermögen",
        "value_mode": "nominal",
    }


# ---------------------------------------------------------------------------
# Backend: create/update must reject a past target_date.
# ---------------------------------------------------------------------------


def test_create_goal_with_past_target_date_rejected(auth_client, advisor_user):
    mandate_id = _setup_mandate(auth_client, advisor_user)
    past_date = (datetime.date.today() - datetime.timedelta(days=400)).isoformat()
    resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_renditeziel_payload(past_date),
    )
    assert resp.status_code == 422, resp.text
    assert "Vergangenheit" in resp.json()["detail"]


def test_create_goal_with_future_target_date_accepted(auth_client, advisor_user):
    mandate_id = _setup_mandate(auth_client, advisor_user)
    future_date = (datetime.date.today() + datetime.timedelta(days=400)).isoformat()
    resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_renditeziel_payload(future_date),
    )
    assert resp.status_code == 201, resp.text


def test_create_goal_with_todays_target_date_accepted(auth_client, advisor_user):
    mandate_id = _setup_mandate(auth_client, advisor_user)
    resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_renditeziel_payload(datetime.date.today().isoformat()),
    )
    assert resp.status_code == 201, resp.text


def test_update_goal_to_past_target_date_rejected(auth_client, advisor_user):
    mandate_id = _setup_mandate(auth_client, advisor_user)
    future_date = (datetime.date.today() + datetime.timedelta(days=400)).isoformat()
    created = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_renditeziel_payload(future_date),
    )
    assert created.status_code == 201, created.text
    goal_id = created.json()["id"]
    past_date = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    resp = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal_id}",
        json={"target_date": past_date},
    )
    assert resp.status_code == 422, resp.text
    assert "Vergangenheit" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Frontend: the UI must not silently fabricate a positive horizon for a past
# target_date, and must block save client-side too.
# ---------------------------------------------------------------------------


def test_goal_editor_horizon_years_commits_to_date_branch():
    html = _html()
    fn_start = html.index("function goalEditorHorizonYears(){")
    fn_end = html.index("\n}", fn_start)
    body = html[fn_start:fn_end]
    assert "return years>0?years:0;" in body, (
        "goalEditorHorizonYears() must unconditionally return based on the "
        "parsed target_date once one is present -- falling through to the "
        "(possibly stale) #nz-horizon raw value for a past date is exactly "
        "the GOAL-PAST-DATE-UI-001 bug."
    )
    assert not re.search(r"if\(years>0\)return years;\s*\}\s*\}\s*var raw=", body), (
        "the old fall-through pattern (only return on years>0, otherwise "
        "drop out of the date branch entirely) must be gone."
    )


def test_save_goal_blocks_past_target_date_client_side():
    html = _html()
    fn_start = html.index("async function saveGoal(options){")
    fn_end = html.index("\nasync function", fn_start + 10)
    body = html[fn_start:fn_end]
    idx_guard = body.index("Zieldatum darf nicht in der Vergangenheit liegen")
    idx_mandate = body.index("var mid=getActiveMandateId();")
    assert idx_guard < idx_mandate, (
        "the past-target-date guard must run before the save request is "
        "built/sent, not after."
    )
