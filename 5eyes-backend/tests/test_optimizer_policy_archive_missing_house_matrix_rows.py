"""Round 40 red test — POLICY-VERSION-IDENTITY-001 (sibling gap).

``_archive_policy_snapshot()`` in routers/allocation.py (~line 78) only
copies OptimizerPolicy's own scalar columns into the new archived row. It
does NOT copy the HouseMatrix rows (nor BuildingBlock rows — same FK shape)
that belonged to the policy being archived. Those child rows stay attached,
via their ``policy_id`` foreign key, only to the ORIGINAL policy_id — which,
per the sibling finding, keeps living on as the NEW/current version after
the update. The archived snapshot therefore has correct top-level scalar
fields but zero HouseMatrix rows of its own: it is an incomplete "policy
aggregate" and cannot reconstruct the bands that were actually in effect at
archive time by querying HouseMatrix.policy_id == <archived snapshot id>.

See audit 2026-10-04-optimizer-policy-version-and-activation-integrity-audit.md
(not committed in this repo).
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
from models.allocation import HouseMatrix, OptimizerPolicy
from services.auth import require_admin
from test_optimizer_shadow_mode import session_factory  # noqa: F401


_ADMIN_ID = "admin-r40-11"

_VALID_HM_ROW_KWARGS = dict(
    score_from=1, score_to=10, profile_name="Konservativ",
    liq_min_bps=0, liq_target_bps=500, liq_max_bps=1000,
    bonds_min_bps=0, bonds_target_bps=4000, bonds_max_bps=6000,
    equity_min_bps=0, equity_target_bps=4000, equity_max_bps=6000,
    real_estate_min_bps=0, real_estate_target_bps=1000, real_estate_max_bps=2000,
    alt_min_bps=0, alt_target_bps=500, alt_max_bps=1000,
    equity_minimum_bps=0, max_risky_fraction_bps=9500,
)


def _ensure_admin(session_factory) -> None:
    from models.users import User as UserModel
    now = "2026-10-04T10:00:00.000Z"
    with session_factory() as s:
        if not s.query(UserModel).filter(UserModel.id == _ADMIN_ID).first():
            s.add(UserModel(
                id=_ADMIN_ID, username="admin-r40-11",
                password_hash="x", full_name="Admin R40-11",
                role="admin", is_active=1,
                created_at=now, updated_at=now,
            ))
            s.commit()


def _seed_policy_with_house_matrix(session_factory) -> str:
    """Erzeugt eine aktive OptimizerPolicy MIT einer zugehoerigen HouseMatrix-Row."""
    _ensure_admin(session_factory)
    pid = new_uuid()
    now = "2026-10-04T10:00:00.000Z"
    with session_factory() as s:
        s.add(OptimizerPolicy(
            id=pid,
            policy_name="R40-11-Test",
            version=1,
            is_current=1,
            valid_from=now,
            valid_to=None,
            optimizer_engine="goal_based_v1",
            max_real_estate_bps=2000,
            max_alternatives_bps=1000,
            min_liquidity_bps=0,
            fee_model_json='{"fee_bps":50}',
            notes="seed",
            created_by=_ADMIN_ID,
            created_at=now,
            updated_at=now,
        ))
        s.add(HouseMatrix(
            id=new_uuid(),
            policy_id=pid,
            **_VALID_HM_ROW_KWARGS,
            is_active=1,
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

    admin_user = SimpleNamespace(id=_ADMIN_ID, full_name="Admin R40-11", email="admin-r40-11@test.local")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    return TestClient(app)


@pytest.mark.xfail(
    strict=True,
    reason="POLICY-VERSION-IDENTITY-001 — round 40 red test, see audit "
           "2026-10-04-optimizer-policy-version-and-activation-integrity-audit.md "
           "(not committed in this repo)",
)
def test_archived_policy_snapshot_gets_own_house_matrix_rows(session_factory):
    """Desired behaviour: archiving a policy must also snapshot its HouseMatrix
    rows under the NEW archived row's id, so the archived aggregate is complete
    and self-contained (queryable by HouseMatrix.policy_id == archived.id)."""
    pid = _seed_policy_with_house_matrix(session_factory)
    try:
        with _client(session_factory) as client:
            response = client.put(
                f"/admin/optimizer-policies/{pid}",
                json={"max_real_estate_bps": 2500, "notes": "after-r40-11"},
            )
            assert response.status_code == 200, response.text
    finally:
        app.dependency_overrides.clear()

    with session_factory() as s:
        rows = s.query(OptimizerPolicy).filter(OptimizerPolicy.policy_name == "R40-11-Test").all()
        archive_rows = [r for r in rows if r.is_current == 0]
        assert len(archive_rows) == 1
        archived_id = archive_rows[0].id
        assert archived_id != pid  # neue ID fuer den Snapshot

        # Gewuenschtes Verhalten: die archivierte Policy-Zeile hat EIGENE
        # HouseMatrix-Rows, die die zum Archivierungszeitpunkt gueltigen
        # Bandbreiten widerspiegeln.
        archived_house_matrix_rows = (
            s.query(HouseMatrix).filter(HouseMatrix.policy_id == archived_id).all()
        )
        assert len(archived_house_matrix_rows) == 1
        assert archived_house_matrix_rows[0].profile_name == "Konservativ"
        assert archived_house_matrix_rows[0].bonds_target_bps == 4000
