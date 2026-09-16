"""PENSION-POSITION-001 Option A (2026-09-15).

Finding: WealthPosition pension fields (`pension_payout_form`,
`pension_technical_rate_bps`, `pension_retirement_age`) and
`Goal.linked_position_id` had ZERO validation. Concretely reproduced earlier
the same day: changing a pension position from age 63/Kapital/175bp to age
-999/Rente/999999bp produced an IDENTICAL SHA-256 input-snapshot hash (that
hash-binding gap is fixed separately, not here). What remained open, and is
closed by this Option-A patch:

  (a) `pension_payout_form` accepted any string -- no validation at all,
      even though the DB already has a real CHECK constraint
      (5eyes_schema_v4.0_FINAL.sql: pension_payout_form TEXT CHECK(... IN
      ('Rente','Kapital','Gemischt','Offen'))). Mirrors the A3-Pilot fix
      already applied to pension_type (see
      tests/test_wealth_position_enum_validation.py).
  (b) `pension_technical_rate_bps` / `pension_retirement_age` had no sanity
      bounds at all (age -999, rate 999999bp both passed Pydantic).
  (c) `Goal.linked_position_id` was a bare Optional[str] -- could reference a
      deleted, inactive, or even a DIFFERENT client's position, and nothing
      ever caught it. Fixed by mirroring the existing
      `_validate_mortgage_link()` precedent (routers/wealth.py) with a new
      `_validate_goal_link()`: exists, active, same client -> else 422.

Test pattern mirrors tests/test_goal_rank_auto_resolution.py (TestClient +
Base.metadata.create_all(), since none of this needs real DB CHECK
constraints -- Pydantic/router-level validation catches it before any SQL is
issued).
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
from models.clients import Client  # noqa: F401 — SQLAlchemy metadata
from models.mandates import Mandate  # noqa: F401
from models.wealth import WealthPosition  # noqa: F401
from models.users import User
from services.auth import get_current_user


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pension_position_001_option_a.db'}",
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
        id="user-pension-position-001",
        username="advisor-ppos001",
        password_hash="h",
        full_name="Advisor PPOS001",
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


def _setup_client_and_mandate(auth_client: TestClient, advisor_user: User, number: str) -> tuple[str, str]:
    client_resp = auth_client.post(
        "/clients",
        json={
            "client_number": number,
            "first_name": "PPOS",
            "last_name": "Test",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert client_resp.status_code == 201, client_resp.text
    client_id = client_resp.json()["id"]
    mandate_resp = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": f"{number}-M", "mandate_type": "Anlageberatung"},
    )
    assert mandate_resp.status_code == 201, mandate_resp.text
    return client_id, mandate_resp.json()["id"]


def _create_wealth_position(auth_client: TestClient, client_id: str, label: str = "Freizuegigkeit") -> str:
    resp = auth_client.post(
        f"/clients/{client_id}/wealth-positions",
        json={
            "label": label,
            "position_type": "Vorsorge",
            "current_value_rappen": 1_000_000_00,
            "pension_type": "Freizügigkeit",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _vermoegensziel_payload(rank: int = 1, linked_position_id: str | None = None) -> dict:
    payload = {
        "goal_family": "Vermögen",
        "goal_type": "Vermoegensziel",
        "label": "Testziel",
        "rank": rank,
        "target_wealth_rappen": 1_000_000_00,
        "horizon_years": 10,
        "hardness": "Primär",
        "value_mode": "nominal",
    }
    if linked_position_id is not None:
        payload["linked_position_id"] = linked_position_id
    return payload


# ---------------------------------------------------------------------------
# (c) Goal.linked_position_id validation
# ---------------------------------------------------------------------------


def test_goal_link_to_nonexistent_position_rejected_on_create(auth_client, advisor_user):
    _client_id, mandate_id = _setup_client_and_mandate(auth_client, advisor_user, "PPOS-001")
    resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(linked_position_id="does-not-exist"),
    )
    assert resp.status_code == 422, resp.text
    assert "Vermögensposition" in str(resp.json()["detail"])


def test_goal_link_to_nonexistent_position_rejected_on_update(auth_client, advisor_user):
    _client_id, mandate_id = _setup_client_and_mandate(auth_client, advisor_user, "PPOS-002")
    create_resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(),
    )
    assert create_resp.status_code == 201, create_resp.text
    goal_id = create_resp.json()["id"]

    update_resp = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal_id}",
        json={"linked_position_id": "still-does-not-exist"},
    )
    assert update_resp.status_code == 422, update_resp.text
    assert "Vermögensposition" in str(update_resp.json()["detail"])


def test_goal_link_to_valid_active_same_client_position_accepted(auth_client, advisor_user):
    client_id, mandate_id = _setup_client_and_mandate(auth_client, advisor_user, "PPOS-003")
    position_id = _create_wealth_position(auth_client, client_id)

    resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(linked_position_id=position_id),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["linked_position_id"] == position_id


def test_goal_link_to_valid_position_accepted_on_update(auth_client, advisor_user):
    client_id, mandate_id = _setup_client_and_mandate(auth_client, advisor_user, "PPOS-004")
    position_id = _create_wealth_position(auth_client, client_id)
    create_resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(),
    )
    goal_id = create_resp.json()["id"]

    update_resp = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal_id}",
        json={"linked_position_id": position_id},
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["linked_position_id"] == position_id


def test_goal_link_to_different_clients_position_rejected(auth_client, advisor_user):
    """Cross-tenant safety: a goal under mandate A must not be allowed to link
    a wealth position that belongs to a DIFFERENT client B."""
    _client_a, mandate_a = _setup_client_and_mandate(auth_client, advisor_user, "PPOS-005A")
    client_b, _mandate_b = _setup_client_and_mandate(auth_client, advisor_user, "PPOS-005B")
    position_b = _create_wealth_position(auth_client, client_b)

    resp = auth_client.post(
        f"/mandates/{mandate_a}/goals",
        json=_vermoegensziel_payload(linked_position_id=position_b),
    )
    assert resp.status_code == 422, resp.text
    assert "Vermögensposition" in str(resp.json()["detail"])


def test_goal_link_none_omitted_still_accepted(auth_client, advisor_user):
    """Regression guard: linked_position_id is optional -- omitting it must
    keep working exactly as before this fix."""
    _client_id, mandate_id = _setup_client_and_mandate(auth_client, advisor_user, "PPOS-006")
    resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["linked_position_id"] is None


def test_goal_link_inactive_position_rejected(auth_client, advisor_user):
    """A soft-deactivated position must not remain a valid link target."""
    client_id, mandate_id = _setup_client_and_mandate(auth_client, advisor_user, "PPOS-007")
    position_id = _create_wealth_position(auth_client, client_id)
    deactivate_resp = auth_client.put(
        f"/clients/{client_id}/wealth-positions/{position_id}",
        json={"is_active": False},
    )
    assert deactivate_resp.status_code == 200, deactivate_resp.text

    resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(linked_position_id=position_id),
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# (a) pension_payout_form validation
# ---------------------------------------------------------------------------


def test_invalid_pension_payout_form_rejected(auth_client, advisor_user):
    client_id, _mandate_id = _setup_client_and_mandate(auth_client, advisor_user, "PPOS-008")
    resp = auth_client.post(
        f"/clients/{client_id}/wealth-positions",
        json={
            "label": "Vorsorgekonto",
            "position_type": "Vorsorge",
            "current_value_rappen": 5_000_000,
            "pension_payout_form": "Bar",
        },
    )
    assert resp.status_code == 422, resp.text
    assert "pension_payout_form" in str(resp.json()["detail"])


@pytest.mark.parametrize("payout_form", ["Rente", "Kapital", "Gemischt", "Offen"])
def test_valid_pension_payout_form_values_accepted(auth_client, advisor_user, payout_form):
    client_id, _mandate_id = _setup_client_and_mandate(
        auth_client, advisor_user, f"PPOS-009-{payout_form}"
    )
    resp = auth_client.post(
        f"/clients/{client_id}/wealth-positions",
        json={
            "label": "Vorsorgekonto",
            "position_type": "Vorsorge",
            "current_value_rappen": 5_000_000,
            "pension_payout_form": payout_form,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["pension_payout_form"] == payout_form


# ---------------------------------------------------------------------------
# (b) pension_technical_rate_bps / pension_retirement_age bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bps", [-1, 1001, 999999])
def test_pension_technical_rate_bps_out_of_bounds_rejected(auth_client, advisor_user, bps):
    client_id, _mandate_id = _setup_client_and_mandate(
        auth_client, advisor_user, f"PPOS-010-{bps}"
    )
    resp = auth_client.post(
        f"/clients/{client_id}/wealth-positions",
        json={
            "label": "Vorsorgekonto",
            "position_type": "Vorsorge",
            "current_value_rappen": 5_000_000,
            "pension_technical_rate_bps": bps,
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("bps", [0, 175, 1000])
def test_pension_technical_rate_bps_in_bounds_accepted(auth_client, advisor_user, bps):
    client_id, _mandate_id = _setup_client_and_mandate(
        auth_client, advisor_user, f"PPOS-011-{bps}"
    )
    resp = auth_client.post(
        f"/clients/{client_id}/wealth-positions",
        json={
            "label": "Vorsorgekonto",
            "position_type": "Vorsorge",
            "current_value_rappen": 5_000_000,
            "pension_technical_rate_bps": bps,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json().get("pension_technical_rate_bps") == bps


@pytest.mark.parametrize("age", [-999, 0, 39, 101, 999999])
def test_pension_retirement_age_out_of_bounds_rejected(auth_client, advisor_user, age):
    client_id, _mandate_id = _setup_client_and_mandate(
        auth_client, advisor_user, f"PPOS-012-{age}"
    )
    resp = auth_client.post(
        f"/clients/{client_id}/wealth-positions",
        json={
            "label": "Vorsorgekonto",
            "position_type": "Vorsorge",
            "current_value_rappen": 5_000_000,
            "pension_retirement_age": age,
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("age", [40, 63, 65, 100])
def test_pension_retirement_age_in_bounds_accepted(auth_client, advisor_user, age):
    client_id, _mandate_id = _setup_client_and_mandate(
        auth_client, advisor_user, f"PPOS-013-{age}"
    )
    resp = auth_client.post(
        f"/clients/{client_id}/wealth-positions",
        json={
            "label": "Vorsorgekonto",
            "position_type": "Vorsorge",
            "current_value_rappen": 5_000_000,
            "pension_retirement_age": age,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["pension_retirement_age"] == age


def test_update_schema_also_bounds_pension_fields(auth_client, advisor_user):
    """WealthPositionUpdate must carry the same bounds -- an update is just as
    capable of writing an absurd value as a create."""
    client_id, _mandate_id = _setup_client_and_mandate(auth_client, advisor_user, "PPOS-014")
    position_id = _create_wealth_position(auth_client, client_id)

    resp = auth_client.put(
        f"/clients/{client_id}/wealth-positions/{position_id}",
        json={"pension_retirement_age": -999, "pension_technical_rate_bps": 999999},
    )
    assert resp.status_code == 422, resp.text

    ok_resp = auth_client.put(
        f"/clients/{client_id}/wealth-positions/{position_id}",
        json={"pension_retirement_age": 65, "pension_technical_rate_bps": 200},
    )
    assert ok_resp.status_code == 200, ok_resp.text
    assert ok_resp.json()["pension_retirement_age"] == 65
