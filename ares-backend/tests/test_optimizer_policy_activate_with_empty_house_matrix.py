"""POLICY-ACTIVATION-COMPLETENESS-001 (round 40 red test).

routers/allocation.py::create_optimizer_policy() (POST /admin/optimizer-policies)
loops over `body.house_matrix_rows` to persist HouseMatrix rows, but does
nothing if that list is empty -- there is no validation that an
activate=True policy actually has at least one usable House Matrix row
before it is allowed to replace the previously-current (working) policy.

If activate=True, the endpoint unconditionally:
  - deactivates whatever policy was previously current (prev.is_current = 0)
  - sets is_current=1 on the brand-new, possibly House-Matrix-less policy
  - commits immediately

This test creates a normal, COMPLETE policy (with House Matrix rows) and
activates it, establishing a working "previous current" policy. It then
POSTs a second OptimizerPolicy with house_matrix_rows=[] and activate=True.

Desired behavior (currently NOT implemented): the second request must be
REJECTED (422/409) and the previously-working complete policy must remain
current -- a policy must never become the active current policy with zero
House Matrix rows, since the next real strategy-calculation run for any
mandate would then fail downstream with
`services/portfolio_engine_house_matrix.py::_house_matrix_or_default()`
raising `ValueError(f"HouseMatrix unvollstaendig fuer Score {score_bucket}")`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pytest

from database import get_db, new_uuid
from main import app
from models.allocation import OptimizerPolicy
from services.auth import require_admin
from test_optimizer_shadow_mode import session_factory  # noqa: F401


_ADMIN_ID = "admin-r40-12"

_VALID_HM_ROW = {
    "score_from": 1, "score_to": 10, "profile_name": "Test",
    "liq_min_bps": 0, "liq_target_bps": 500, "liq_max_bps": 1000,
    "bonds_min_bps": 0, "bonds_target_bps": 4000, "bonds_max_bps": 6000,
    "equity_min_bps": 0, "equity_target_bps": 4000, "equity_max_bps": 6000,
    "real_estate_min_bps": 0, "real_estate_target_bps": 1000, "real_estate_max_bps": 2000,
    "alt_min_bps": 0, "alt_target_bps": 500, "alt_max_bps": 1000,
    "max_risky_fraction_bps": 9500,
}


def _ensure_admin(session_factory) -> None:
    from models.users import User as UserModel
    now = "2026-10-04T10:00:00.000Z"
    with session_factory() as s:
        if not s.query(UserModel).filter(UserModel.id == _ADMIN_ID).first():
            s.add(UserModel(
                id=_ADMIN_ID, username="admin-r40-12",
                password_hash="x", full_name="Admin R40-12",
                role="admin", is_active=1,
                created_at=now, updated_at=now,
            ))
            s.commit()


def _client(session_factory) -> TestClient:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    admin_user = SimpleNamespace(id=_ADMIN_ID, full_name="Admin R40-12", email="admin-r40-12@test.local")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    return TestClient(app)


def _base_policy_payload(name: str, house_matrix_rows: list[dict]) -> dict:
    return {
        "policy_name": name,
        "optimizer_engine": "goal_based_v1",
        "max_real_estate_bps": 2000,
        "max_alternatives_bps": 1000,
        "min_liquidity_bps": 0,
        "fee_model_json": '{"fee_bps":50}',
        "notes": "r40-12",
        "house_matrix_rows": house_matrix_rows,
    }


@pytest.mark.xfail(
    strict=True,
    reason=(
        "POLICY-ACTIVATION-COMPLETENESS-001 -- round 40 red test, see audit "
        "2026-10-04-optimizer-policy-version-and-activation-integrity-audit.md "
        "(not committed in this repo)"
    ),
)
def test_activating_policy_with_empty_house_matrix_is_rejected(session_factory):
    _ensure_admin(session_factory)

    try:
        with _client(session_factory) as client:
            # 1. Create and activate a normal, COMPLETE policy -- this becomes
            #    the working "previous current" policy.
            complete_resp = client.post(
                "/admin/optimizer-policies",
                params={"activate": "true"},
                json=_base_policy_payload("R40-12-Complete", [_VALID_HM_ROW]),
            )
            assert complete_resp.status_code == 201, complete_resp.text
            complete_id = complete_resp.json()["id"]
            assert complete_resp.json()["is_current"] == 1

            # 2. Attempt to create+activate a SECOND policy with an EMPTY
            #    House Matrix. Desired behavior: this must be REJECTED, and
            #    the previously-working complete policy must remain current.
            empty_resp = client.post(
                "/admin/optimizer-policies",
                params={"activate": "true"},
                json=_base_policy_payload("R40-12-Empty", []),
            )
            assert empty_resp.status_code in (409, 422), (
                "activate=True with an empty house_matrix_rows list must be "
                f"rejected, got {empty_resp.status_code}: {empty_resp.text}"
            )
    finally:
        app.dependency_overrides.clear()

    # The previously-working complete policy must still be the current one.
    with session_factory() as s:
        complete = s.query(OptimizerPolicy).filter(OptimizerPolicy.id == complete_id).first()
        assert complete is not None
        assert complete.is_current == 1, (
            "the previously-working, House-Matrix-complete policy must remain "
            "current -- it must not be silently deactivated in favour of an "
            "empty-House-Matrix policy"
        )

        empty_policies = s.query(OptimizerPolicy).filter(
            OptimizerPolicy.policy_name == "R40-12-Empty",
        ).all()
        assert not any(p.is_current == 1 for p in empty_policies), (
            "a policy with zero House Matrix rows must never become is_current=1 "
            "-- the next real strategy-calculation run for any mandate would "
            "fail downstream with 'HouseMatrix unvollstaendig fuer Score ...'"
        )
