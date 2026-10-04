"""Round 40 red test: POLICY-VERSION-IDENTITY-001.

Audit finding (2026-10-04-optimizer-policy-version-and-activation-integrity-audit.md,
not committed in this repo) against routers/allocation.py::update_optimizer_policy
(PUT /admin/optimizer-policies/{policy_id}):

``update_optimizer_policy`` calls ``_archive_policy_snapshot(db, policy, now=now)``
*before* mutating. That helper writes a brand-new row with a freshly generated
``id`` holding a COPY of the policy's pre-update field values (``is_current=0``).
Immediately after, ``update_optimizer_policy`` bumps ``policy.version`` and then
does ``setattr(policy, field, value)`` for every payload field -- mutating the
ORIGINAL ORM object (and therefore the ORIGINAL row, under its ORIGINAL id)
in place.

Net effect: any ``TargetAllocation.policy_id`` (or ``RecommendationRun.policy_id``)
that was recorded against the original policy id -- because that id was
"current" at the time the TargetAllocation was generated -- now resolves to a
row that has been silently overwritten with the NEW (version+1) values. The
row that actually still holds the correct historical (version-1) values sits
under a brand-new, never-before-referenced id that nothing points to.

Desired behaviour: a policy, once referenced (e.g. by a TargetAllocation),
must be content-immutable under that id. An update must leave the ORIGINAL
id's row holding the values that were in effect when it was referenced, and
the NEW version must live under a NEW id (with existing references staying on
the original/historical id, or being deliberately re-pointed -- either way,
the id a pre-existing reference already points to must never change meaning
out from under it).

This test seeds a policy (version 1, max_real_estate_bps=500), records its id
as if a pre-existing TargetAllocation.policy_id pointed at it, then PUTs an
update changing max_real_estate_bps to 800. It asserts the row still reachable
by the ORIGINAL id keeps the version-1 value (500) that was in effect when the
reference was created. Today this fails: the original id's row is mutated to
800, while the untouched 500 value sits under a newly-generated id that the
pre-existing reference never points to.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database import get_db, new_uuid
from main import app
from models.allocation import OptimizerPolicy
from services.auth import require_admin
from test_optimizer_shadow_mode import session_factory  # noqa: F401


_ADMIN_ID = "admin-polversid-001"


def _ensure_admin(session_factory) -> None:
    from models.users import User as UserModel
    now = "2026-10-04T10:00:00.000Z"
    with session_factory() as s:
        if not s.query(UserModel).filter(UserModel.id == _ADMIN_ID).first():
            s.add(UserModel(
                id=_ADMIN_ID, username="admin-polversid-001",
                password_hash="x", full_name="Admin PolVersId",
                role="admin", is_active=1,
                created_at=now, updated_at=now,
            ))
            s.commit()


def _seed_policy(session_factory, *, max_real_estate_bps: int = 500) -> str:
    """Erzeugt eine aktive OptimizerPolicy (version=1) in der Test-DB."""
    _ensure_admin(session_factory)
    pid = new_uuid()
    now = "2026-10-04T10:00:00.000Z"
    with session_factory() as s:
        s.add(OptimizerPolicy(
            id=pid,
            policy_name="POLICY-VERSION-IDENTITY-001-Test",
            version=1,
            is_current=1,
            valid_from=now,
            valid_to=None,
            optimizer_engine="goal_based_v1",
            max_real_estate_bps=max_real_estate_bps,
            max_alternatives_bps=1000,
            min_liquidity_bps=0,
            fee_model_json='{"fee_bps":50}',
            notes="v1-seed",
            created_by=_ADMIN_ID,
            created_at=now,
            updated_at=now,
        ))
        s.commit()
    return pid


def _client(session_factory) -> TestClient:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    admin_user = SimpleNamespace(
        id=_ADMIN_ID, full_name="Admin PolVersId", email="admin-polversid-001@test.local"
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    return TestClient(app)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "POLICY-VERSION-IDENTITY-001 -- round 40 red test, see audit "
        "2026-10-04-optimizer-policy-version-and-activation-integrity-audit.md "
        "(not committed in this repo)"
    ),
)
def test_policy_update_must_not_mutate_originally_referenced_id_in_place(session_factory):
    """A pre-existing reference to policy_id must keep seeing version-1 values.

    Desired behaviour: once a TargetAllocation.policy_id points at a policy
    row, that row's content is immutable under that id -- an update must
    produce a NEW id for the NEW version, not silently overwrite the
    referenced row in place.
    """
    # 1. Create an OptimizerPolicy (version 1) with a distinguishing value.
    original_policy_id = _seed_policy(session_factory, max_real_estate_bps=500)

    # 2. Simulate a pre-existing TargetAllocation recorded against this
    #    policy id, back when it held the version-1 value (500). We don't
    #    need a full TargetAllocation row for this assertion -- the FK
    #    integrity point under test is purely about what `original_policy_id`
    #    resolves to before vs. after the update.
    referenced_policy_id = original_policy_id

    # 3. PUT an update to the same policy_id, changing the field.
    try:
        with _client(session_factory) as client:
            response = client.put(
                f"/admin/optimizer-policies/{original_policy_id}",
                json={"max_real_estate_bps": 800},
            )
            assert response.status_code == 200, response.text
    finally:
        app.dependency_overrides.clear()

    # 4. Desired behaviour: the row still reachable by the id the pre-existing
    #    reference points to must still reflect the version-1 value (500)
    #    that was actually in effect when that reference was created --
    #    policy content must be immutable once referenced.
    with session_factory() as s:
        row_at_referenced_id = s.query(OptimizerPolicy).filter(
            OptimizerPolicy.id == referenced_policy_id,
        ).first()

    assert row_at_referenced_id is not None
    assert row_at_referenced_id.max_real_estate_bps == 500, (
        "A pre-existing reference's policy id must keep resolving to the "
        "version-1 value that was in effect when it was referenced; instead "
        f"it now resolves to max_real_estate_bps="
        f"{row_at_referenced_id.max_real_estate_bps} (the NEW version's "
        "value), proving the original id's row was mutated in place instead "
        "of the new version getting its own new id."
    )
