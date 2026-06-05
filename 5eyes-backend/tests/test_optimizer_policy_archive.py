"""Sprint U-103 (2026-06-05): Tests fuer OptimizerPolicy-Archiv-Snapshot.

PUT /admin/optimizer-policies/{id} muss vor In-Place-Update einen
historischen Snapshot schreiben — sonst kann nach einem Update nicht
mehr rekonstruiert werden mit welchen Bandbreiten eine bestehende
TargetAllocation generiert wurde.
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

def test_put_policy_creates_archive_snapshot(session_factory):
    pid = _seed_policy(session_factory)
    try:
        with _client(session_factory) as client:
            response = client.put(
                f"/admin/optimizer-policies/{pid}",
                json={"max_real_estate_bps": 2500, "notes": "after-u103"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["max_real_estate_bps"] == 2500
    finally:
        app.dependency_overrides.clear()

    # Es muessen jetzt 2 Rows existieren: 1 aktive (version=2) + 1 archiviert (version=1)
    with session_factory() as s:
        rows = s.query(OptimizerPolicy).filter(OptimizerPolicy.policy_name == "U103-Test").all()
    assert len(rows) == 2

    current_rows = [r for r in rows if r.is_current == 1]
    archive_rows = [r for r in rows if r.is_current == 0]
    assert len(current_rows) == 1
    assert len(archive_rows) == 1

    current = current_rows[0]
    archive = archive_rows[0]

    # Current: version bumped, neue Werte
    assert current.id == pid  # gleiche ID, FK-Integritaet
    assert current.version == 2
    assert current.max_real_estate_bps == 2500
    assert current.notes == "after-u103"
    assert current.valid_to is None

    # Archive: alte Werte konserviert
    assert archive.id != pid  # neue ID
    assert archive.version == 1
    assert archive.max_real_estate_bps == 2000  # alter Wert
    assert archive.notes == "seed"  # alter Wert
    assert archive.valid_to is not None  # Ende-Datum gesetzt
    assert archive.valid_from is not None  # Anfangs-Datum erhalten


def test_put_policy_no_payload_no_archive(session_factory):
    """Wenn body leer ist (kein effektives Update), keinen Archive-Snapshot schreiben."""
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
    assert len(rows) == 1  # nur die Original-Zeile, kein Archive
    assert rows[0].version == 1


def test_put_policy_multiple_updates_create_chain(session_factory):
    """Mehrere PUTs hintereinander erzeugen eine Archive-Kette."""
    pid = _seed_policy(session_factory)
    try:
        with _client(session_factory) as client:
            client.put(f"/admin/optimizer-policies/{pid}", json={"max_real_estate_bps": 2100})
            client.put(f"/admin/optimizer-policies/{pid}", json={"max_real_estate_bps": 2200})
            client.put(f"/admin/optimizer-policies/{pid}", json={"max_real_estate_bps": 2300})
    finally:
        app.dependency_overrides.clear()

    with session_factory() as s:
        rows = s.query(OptimizerPolicy).filter(OptimizerPolicy.policy_name == "U103-Test").all()
    # 1 aktive + 3 archiviert = 4
    assert len(rows) == 4

    current_rows = [r for r in rows if r.is_current == 1]
    archives = sorted(
        [r for r in rows if r.is_current == 0],
        key=lambda r: r.version,
    )
    assert len(current_rows) == 1
    assert current_rows[0].version == 4
    assert current_rows[0].max_real_estate_bps == 2300

    assert [a.version for a in archives] == [1, 2, 3]
    assert [a.max_real_estate_bps for a in archives] == [2000, 2100, 2200]


def test_put_policy_preserves_id_for_fk_integrity(session_factory):
    """Bestehende TargetAllocations.policy_id muss weiter gueltig sein."""
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
    assert current.min_liquidity_bps == 500
