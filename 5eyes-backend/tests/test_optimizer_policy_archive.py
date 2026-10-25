"""OptimizerPolicy-Versionierung ueber PUT /admin/optimizer-policies/{id}.

POLICY-VERSION-IDENTITY-001: Eine aktive oder referenzierte Policy-Version
ist unter ihrer ID unveraenderlich. Ein PUT erzeugt dann eine neue
Entwurfsversion (neue ID, is_current=0); nur ein nie referenzierter Entwurf
darf in-place editiert werden. Die frueheren Tests dieser Datei pinnten die
In-place-Mutation der aktiven Zeile (die vom Audit beanstandete Ursache) und
wurden auf den neuen Vertrag umgestellt.
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

from database import get_db, new_uuid
from main import app
from models.allocation import OptimizerPolicy
from services.auth import require_admin
from test_optimizer_shadow_mode import session_factory  # noqa: F401


_ADMIN_ID = "admin-u103"


def _ensure_admin(session_factory) -> None:
    from models.users import User as UserModel
    now = "2026-06-05T10:00:00.000Z"
    with session_factory() as s:
        if not s.query(UserModel).filter(UserModel.id == _ADMIN_ID).first():
            s.add(UserModel(
                id=_ADMIN_ID, username="admin-u103",
                password_hash="x", full_name="Admin U103",
                role="admin", is_active=1,
                created_at=now, updated_at=now,
            ))
            s.commit()


def _seed_policy(session_factory, *, fee_model_json: str = '{"fee_bps":50}') -> str:
    """Erzeugt eine aktive OptimizerPolicy in der Test-DB."""
    _ensure_admin(session_factory)
    pid = new_uuid()
    now = "2026-06-05T10:00:00.000Z"
    with session_factory() as s:
        s.add(OptimizerPolicy(
            id=pid,
            policy_name="U103-Test",
            version=1,
            is_current=1,
            valid_from=now,
            valid_to=None,
            optimizer_engine="goal_based_v1",
            max_real_estate_bps=2000,
            max_alternatives_bps=1000,
            min_liquidity_bps=0,
            fee_model_json=fee_model_json,
            notes="seed",
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

    admin_user = SimpleNamespace(id=_ADMIN_ID, full_name="Admin U103", email="admin-u103@test.local")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    return TestClient(app)


# ---------------------------------------------------------------------------
# Archive-Snapshot Tests
# ---------------------------------------------------------------------------

def test_put_on_active_policy_creates_new_draft_version(session_factory):
    pid = _seed_policy(session_factory)
    try:
        with _client(session_factory) as client:
            response = client.put(
                f"/admin/optimizer-policies/{pid}",
                json={"max_real_estate_bps": 2500, "notes": "after-u103"},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["max_real_estate_bps"] == 2500
            assert body["id"] != pid
            assert body["is_current"] == 0
            assert body["version"] == 2
    finally:
        app.dependency_overrides.clear()

    with session_factory() as s:
        rows = s.query(OptimizerPolicy).filter(OptimizerPolicy.policy_name == "U103-Test").all()
    assert len(rows) == 2
    original = next(r for r in rows if r.id == pid)
    draft = next(r for r in rows if r.id != pid)

    # Original: unveraendert und weiterhin aktiv.
    assert original.is_current == 1
    assert original.version == 1
    assert original.max_real_estate_bps == 2000
    assert original.notes == "seed"
    assert original.valid_to is None

    # Neue Version: eigener Entwurf mit den neuen Werten.
    assert draft.is_current == 0
    assert draft.version == 2
    assert draft.max_real_estate_bps == 2500
    assert draft.notes == "after-u103"
    assert draft.fee_model_json == original.fee_model_json


def test_put_policy_no_payload_no_archive(session_factory):
    """Wenn body leer ist (kein effektives Update), keine neue Version schreiben."""
    pid = _seed_policy(session_factory)
    try:
        with _client(session_factory) as client:
            response = client.put(
                f"/admin/optimizer-policies/{pid}",
                json={},
            )
            assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()

    with session_factory() as s:
        rows = s.query(OptimizerPolicy).filter(OptimizerPolicy.policy_name == "U103-Test").all()
    assert len(rows) == 1  # nur die Original-Zeile
    assert rows[0].version == 1


def test_put_on_unreferenced_draft_edits_in_place(session_factory):
    """Nach dem ersten PUT wird der Entwurf weiter editiert -- ohne neue Zeilen."""
    pid = _seed_policy(session_factory)
    try:
        with _client(session_factory) as client:
            draft_id = client.put(
                f"/admin/optimizer-policies/{pid}", json={"max_real_estate_bps": 2100},
            ).json()["id"]
            r2 = client.put(f"/admin/optimizer-policies/{draft_id}", json={"max_real_estate_bps": 2200})
            r3 = client.put(f"/admin/optimizer-policies/{draft_id}", json={"max_real_estate_bps": 2300})
            assert r2.json()["id"] == r3.json()["id"] == draft_id
    finally:
        app.dependency_overrides.clear()

    with session_factory() as s:
        rows = s.query(OptimizerPolicy).filter(OptimizerPolicy.policy_name == "U103-Test").all()
    assert len(rows) == 2
    original = next(r for r in rows if r.id == pid)
    draft = next(r for r in rows if r.id == draft_id)
    assert (original.is_current, original.version, original.max_real_estate_bps) == (1, 1, 2000)
    assert (draft.is_current, draft.version, draft.max_real_estate_bps) == (0, 2, 2300)


def _reference_policy(session_factory, pid: str) -> None:
    """Haengt einen RecommendationRun an die Policy (minimaler Referenz-Seed)."""
    from models.review import RecommendationRun

    now = "2026-06-05T10:00:00.000Z"
    with session_factory() as s:
        s.add(RecommendationRun(
            id=new_uuid(), mandate_id="mandate-u103-ref", client_id="client-u103-ref",
            policy_id=pid, run_type="Optimizer", result_status="Draft",
            created_by=_ADMIN_ID, created_at=now, updated_at=now,
        ))
        s.commit()


def test_put_on_referenced_historic_policy_creates_new_version(session_factory):
    pid = _seed_policy(session_factory)
    _reference_policy(session_factory, pid)
    with session_factory() as s:
        row = s.get(OptimizerPolicy, pid)
        row.is_current = 0
        s.commit()
    try:
        with _client(session_factory) as client:
            resp = client.put(f"/admin/optimizer-policies/{pid}", json={"min_liquidity_bps": 500})
            assert resp.status_code == 200, resp.text
            assert resp.json()["id"] != pid
    finally:
        app.dependency_overrides.clear()

    with session_factory() as s:
        assert s.get(OptimizerPolicy, pid).min_liquidity_bps == 0


# ---------------------------------------------------------------------------
# Redesign 2026-06-10: House-Matrix-Rows-Versionstreue (Backend-Guard)
# ---------------------------------------------------------------------------

_VALID_HM_ROW = {
    "score_from": 1, "score_to": 10, "profile_name": "Test",
    "liq_min_bps": 0, "liq_target_bps": 500, "liq_max_bps": 1000,
    "bonds_min_bps": 0, "bonds_target_bps": 4000, "bonds_max_bps": 6000,
    "equity_min_bps": 0, "equity_target_bps": 4000, "equity_max_bps": 6000,
    "real_estate_min_bps": 0, "real_estate_target_bps": 1000, "real_estate_max_bps": 2000,
    "alt_min_bps": 0, "alt_target_bps": 500, "alt_max_bps": 1000,
    "max_risky_fraction_bps": 9500,
}


def _seed_draft_policy(session_factory) -> str:
    """Erzeugt eine NICHT-aktive (Draft/Klon) OptimizerPolicy."""
    _ensure_admin(session_factory)
    pid = new_uuid()
    now = "2026-06-05T10:00:00.000Z"
    with session_factory() as s:
        s.add(OptimizerPolicy(
            id=pid, policy_name="U-Redesign-Draft", version=1, is_current=0,
            valid_from=now, valid_to=None, optimizer_engine="goal_based_v1",
            max_real_estate_bps=2000, max_alternatives_bps=1000, min_liquidity_bps=0,
            fee_model_json='{"fee_bps":50}', notes="draft", created_by=_ADMIN_ID,
            created_at=now, updated_at=now,
        ))
        s.commit()
    return pid


def test_house_matrix_put_blocked_on_active_policy(session_factory):
    """Aktive Policy darf nicht direkt ueberschrieben werden -> 409 (Versionstreue)."""
    pid = _seed_policy(session_factory)  # is_current=1
    try:
        with _client(session_factory) as client:
            resp = client.put(
                f"/admin/optimizer-policies/{pid}/house-matrix",
                json={"rows": [_VALID_HM_ROW]},
            )
            assert resp.status_code == 409, resp.text
    finally:
        app.dependency_overrides.clear()


def test_house_matrix_put_allowed_on_draft_policy(session_factory):
    """Draft/Klon-Policy bleibt editierbar -> Guard ueberblockt nicht."""
    pid = _seed_draft_policy(session_factory)  # is_current=0
    try:
        with _client(session_factory) as client:
            resp = client.put(
                f"/admin/optimizer-policies/{pid}/house-matrix",
                json={"rows": [_VALID_HM_ROW]},
            )
            assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()


def test_put_policy_keeps_referenced_id_content_for_fk_integrity(session_factory):
    """Bestehende TargetAllocation.policy_id loest weiter auf den alten Inhalt auf."""
    pid = _seed_policy(session_factory)
    try:
        with _client(session_factory) as client:
            client.put(f"/admin/optimizer-policies/{pid}", json={"min_liquidity_bps": 500})
    finally:
        app.dependency_overrides.clear()

    with session_factory() as s:
        current = s.query(OptimizerPolicy).filter(OptimizerPolicy.id == pid).first()
    assert current is not None  # original ID lebt
    assert current.is_current == 1
    assert current.min_liquidity_bps == 0


def test_house_matrix_put_blocked_on_referenced_historic_policy(session_factory):
    pid = _seed_draft_policy(session_factory)
    _reference_policy(session_factory, pid)
    try:
        with _client(session_factory) as client:
            resp = client.put(
                f"/admin/optimizer-policies/{pid}/house-matrix",
                json={"rows": [_VALID_HM_ROW]},
            )
            assert resp.status_code == 409, resp.text
    finally:
        app.dependency_overrides.clear()
