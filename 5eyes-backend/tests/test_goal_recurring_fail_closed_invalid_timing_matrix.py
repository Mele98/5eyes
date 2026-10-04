"""Fail-closed matrix for invalid recurring-goal timing payloads.

Finding GOAL-RECURRING-EDITOR-CONTRACT-001 (see
docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md,
not present in this worktree -- see commit message / task context): the
recurring-goal editor contract must fail closed on contradictory or
incomplete timing input. A goal must never be silently normalized (e.g. an
absent start/end anchor quietly filled in with a default) or silently
accepted when its timing is self-contradictory.

This module drives the real API surface (routers/wealth.py ->
schemas/wealth.py field isolation -> services/goal_semantics.py complete
domain validation) exactly as the goal editor would, and asserts every
malformed row in the matrix is rejected with HTTP 422. Cases that the
current implementation still lets through silently are marked
xfail(strict=True) rather than weakened, so a real fix flips them to green
and a regression that reintroduces the hole fails CI immediately.
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
        f"sqlite:///{tmp_path / 'goal_recurring_timing_matrix.db'}",
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
        id="goal-recurring-timing-advisor",
        username="goal-recurring-timing-advisor",
        password_hash="h",
        full_name="Goal Recurring Timing Advisor",
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
            "client_number": f"GOALRT-{suffix}",
            "first_name": "Goal",
            "last_name": "RecurringTiming",
            "advisor_id": advisor.id,
            "household_type": "Einzelperson",
        },
    )
    assert client_response.status_code == 201, client_response.text
    mandate_response = auth_client.post(
        f"/clients/{client_response.json()['id']}/mandates",
        json={
            "mandate_number": f"GOALRT-M-{suffix}",
            "mandate_type": "Anlageberatung",
        },
    )
    assert mandate_response.status_code == 201, mandate_response.text
    return mandate_response.json()["id"]


def _base_recurring_payload() -> dict:
    """A deliberately *valid* open-ended recurring expense goal.

    Every matrix case below starts from this baseline and mutates exactly
    the field(s) under test, so a failure can only be attributed to that
    mutation.
    """
    return {
        "goal_family": "Cashflow",
        "goal_type": "Wiederkehrende_Ausgabe",
        "label": "Wiederkehrende Ausgabe Timing-Matrix",
        "rank": 1,
        "weight_bps": 5000,
        "goal_scope": "Beratungsvermögen",
        "value_mode": "nominal",
        "target_amount_rappen": 120_000,
        "start_date": "2030-01-01",
        "is_ongoing": True,
        "frequency": "jährlich",
        "hardness": "Primär",
    }


def _post_goal(auth_client: TestClient, mandate_id: str, payload: dict):
    return auth_client.post(f"/mandates/{mandate_id}/goals", json=payload)


def test_sanity_base_payload_is_accepted(auth_client, advisor_user):
    """Positive control: the unmutated baseline must itself be valid.

    If this fails, every xfail below is meaningless noise rather than a
    signal, because the matrix cases would be comparing against a baseline
    that was never admissible in the first place.
    """
    mandate_id = _create_api_mandate(auth_client, advisor_user, "sanity-base")
    response = _post_goal(auth_client, mandate_id, _base_recurring_payload())
    assert response.status_code == 201, response.text


def test_start_after_end_is_rejected(auth_client, advisor_user):
    """start_date > target_date must be rejected (contradictory interval)."""
    mandate_id = _create_api_mandate(auth_client, advisor_user, "start-after-end")
    payload = _base_recurring_payload()
    payload["is_ongoing"] = False
    payload["start_date"] = "2035-01-01"
    payload["target_date"] = "2030-01-01"

    response = _post_goal(auth_client, mandate_id, payload)

    assert response.status_code == 422, response.text


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RECURRING-EDITOR-CONTRACT-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md. "
        "A recurring goal created with no start_date, no target_date and no "
        "horizon_years is not rejected: _normalize_goal_payload "
        "(routers/wealth.py) silently backfills horizon_years=10 for new "
        "goals whose timing is entirely unanchored, so "
        "validate_goal_model_input's require_stream_timing() never sees the "
        "missing anchor and the row is persisted at HTTP 201 instead of "
        "being rejected."
    ),
)
def test_missing_start_date_is_rejected(auth_client, advisor_user):
    """A recurring goal with no start_date and no other timing anchor
    (target_date, horizon_years) must be rejected rather than silently
    given a default horizon."""
    mandate_id = _create_api_mandate(auth_client, advisor_user, "missing-start")
    payload = _base_recurring_payload()
    payload["start_date"] = None
    payload["target_date"] = None
    payload.pop("horizon_years", None)

    response = _post_goal(auth_client, mandate_id, payload)

    assert response.status_code == 422, response.text


def test_finite_stream_without_end_date_is_rejected(auth_client, advisor_user):
    """is_ongoing=False without a target_date must be rejected -- a finite
    stream needs an explicit end."""
    mandate_id = _create_api_mandate(auth_client, advisor_user, "finite-no-end")
    payload = _base_recurring_payload()
    payload["is_ongoing"] = False
    payload["target_date"] = None

    response = _post_goal(auth_client, mandate_id, payload)

    assert response.status_code == 422, response.text


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RECURRING-EDITOR-CONTRACT-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md. "
        "is_ongoing=True together with a target_date is self-contradictory "
        "(an 'ongoing forever' stream cannot also have a fixed end date), "
        "but neither _validate_complete_goal_state (routers/wealth.py) nor "
        "validate_goal_model_input (services/goal_semantics.py) checks the "
        "combination -- the not-ongoing branch only looks at target_date "
        "when is_ongoing is False -- so the row is persisted at HTTP 201 "
        "instead of being rejected."
    ),
)
def test_ongoing_stream_with_end_date_is_rejected(auth_client, advisor_user):
    """is_ongoing=True with a target_date set is a contradictory state and
    must be rejected."""
    mandate_id = _create_api_mandate(auth_client, advisor_user, "ongoing-with-end")
    payload = _base_recurring_payload()
    payload["is_ongoing"] = True
    payload["target_date"] = "2035-01-01"

    response = _post_goal(auth_client, mandate_id, payload)

    assert response.status_code == 422, response.text


def test_negative_amount_is_rejected(auth_client, advisor_user):
    """A negative target_amount_rappen must be rejected, not clamped or
    silently flipped to its absolute value."""
    mandate_id = _create_api_mandate(auth_client, advisor_user, "negative-amount")
    payload = _base_recurring_payload()
    payload["target_amount_rappen"] = -120_000

    response = _post_goal(auth_client, mandate_id, payload)

    assert response.status_code == 422, response.text


def test_null_amount_is_rejected(auth_client, advisor_user):
    """A cashflow goal with no target_amount_rappen at all must be
    rejected."""
    mandate_id = _create_api_mandate(auth_client, advisor_user, "null-amount")
    payload = _base_recurring_payload()
    payload["target_amount_rappen"] = None

    response = _post_goal(auth_client, mandate_id, payload)

    assert response.status_code == 422, response.text
