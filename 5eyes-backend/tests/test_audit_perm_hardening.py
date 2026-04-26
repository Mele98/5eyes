"""G1 + G2 + G3 - Permission/IDOR/Search-Hardening.

G1 - StrategySnapshot Endpoints:
  * IDOR: ein Advisor darf NICHT auf Mandate fremder Advisor zugreifen.
  * Write-Permission: POST braucht require_advisor (readonly-User -> 403).

G2 - review.py:refresh_system_triggers:
  * Write-Permission: braucht require_advisor (readonly-User -> 403).

G3 - system.py:list_audit_log:
  * LIKE-Suche escaped Wildcards %/_ korrekt - sonst matchen Eingaben mit %
    alles statt nur den Literal-Stern.
"""
from __future__ import annotations
import sys
import uuid
import datetime
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
from models.clients import Client
from models.mandates import Mandate
from models.review import AuditLog
from models.snapshots import StrategySnapshot
from models.users import User
from services.auth import get_current_user, require_admin, require_advisor


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_perm.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _make_user(role: str, suffix: str) -> User:
    return User(
        id=f"user-{role}-{suffix}",
        username=f"{role}-{suffix}",
        password_hash="h",
        full_name=f"{role.title()} {suffix}",
        role=role, is_active=1,
        created_at=_now(), updated_at=_now(),
    )


def _make_client_and_mandate(session_factory, advisor: User):
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        if not s.query(User).filter(User.id == advisor.id).first():
            s.add(advisor)
        s.add(Client(
            id=cid, client_number=f"C-{cid[:6]}",
            first_name="Mandant", last_name=advisor.id[-4:],
            advisor_id=advisor.id, created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
            mandate_type="Anlageberatung", opened_at=now,
            created_at=now, updated_at=now,
        ))
        s.commit()
    return cid, mid


def _client_with_user(session_factory, user: User) -> TestClient:
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.fixture()
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


SNAPSHOT_PAYLOAD = {
    "snapshot_date": "2026-04-25",
    "advisory_assets_rappen": 1_000_000_00,
    "risk_profile_score": 6,
    "risk_profile_label": "Ausgewogen",
    "soll_equities_bps": 4500,
    "soll_bonds_bps": 3500,
    "soll_real_estate_bps": 1000,
    "soll_liquidity_bps": 500,
    "soll_alternatives_bps": 500,
    "band_equities_lo_bps": 2500, "band_equities_hi_bps": 5500,
    "band_bonds_lo_bps": 2500, "band_bonds_hi_bps": 4500,
    "band_real_estate_lo_bps": 500, "band_real_estate_hi_bps": 1500,
    "band_liquidity_lo_bps": 200, "band_liquidity_hi_bps": 800,
    "band_alternatives_lo_bps": 300, "band_alternatives_hi_bps": 800,
    "advisor_note": "Test",
    "goals_summary_json": "{}",
}


# ============================================================================
# G1 - Snapshots: IDOR + write permission
# ============================================================================

def test_g1_create_snapshot_requires_advisor_role(session_factory, cleanup_overrides):
    """readonly-User darf KEINEN Snapshot anlegen."""
    advisor = _make_user("advisor", "1")
    readonly = _make_user("readonly", "1")
    cid, mid = _make_client_and_mandate(session_factory, advisor)
    with session_factory() as s:
        s.add(readonly)
        s.commit()
    client = _client_with_user(session_factory, readonly)
    resp = client.post(f"/mandates/{mid}/strategy-snapshots", json=SNAPSHOT_PAYLOAD)
    assert resp.status_code == 403, resp.text


def test_g1_advisor_cannot_snapshot_foreign_mandate(session_factory, cleanup_overrides):
    """Advisor1 darf nicht zu Mandat von Advisor2 schreiben (IDOR)."""
    advisor1 = _make_user("advisor", "1")
    advisor2 = _make_user("advisor", "2")
    cid2, mid2 = _make_client_and_mandate(session_factory, advisor2)
    with session_factory() as s:
        s.add(advisor1)
        s.commit()
    client = _client_with_user(session_factory, advisor1)
    resp = client.post(f"/mandates/{mid2}/strategy-snapshots", json=SNAPSHOT_PAYLOAD)
    assert resp.status_code == 404, (
        f"Erwarte 404 (Mandat fuer Advisor1 nicht sichtbar), bekam {resp.status_code}: {resp.text}"
    )


def test_g1_advisor_cannot_list_foreign_snapshots(session_factory, cleanup_overrides):
    """GET ../strategy-snapshots fuer fremdes Mandat -> 404."""
    advisor1 = _make_user("advisor", "1")
    advisor2 = _make_user("advisor", "2")
    cid2, mid2 = _make_client_and_mandate(session_factory, advisor2)
    with session_factory() as s:
        s.add(advisor1)
        s.commit()
    client = _client_with_user(session_factory, advisor1)
    resp = client.get(f"/mandates/{mid2}/strategy-snapshots")
    assert resp.status_code == 404, resp.text


def test_g1_advisor_cannot_get_foreign_drift(session_factory, cleanup_overrides):
    """GET ../latest/drift fuer fremdes Mandat -> 404."""
    advisor1 = _make_user("advisor", "1")
    advisor2 = _make_user("advisor", "2")
    cid2, mid2 = _make_client_and_mandate(session_factory, advisor2)
    with session_factory() as s:
        s.add(advisor1)
        s.commit()
    client = _client_with_user(session_factory, advisor1)
    resp = client.get(f"/mandates/{mid2}/strategy-snapshots/latest/drift")
    assert resp.status_code == 404, resp.text


def test_g1_admin_can_access_any_snapshot(session_factory, cleanup_overrides):
    """Admin (global access) muss weiterhin auf jedes Mandat schreiben koennen."""
    admin = _make_user("admin", "0")
    advisor = _make_user("advisor", "9")
    cid, mid = _make_client_and_mandate(session_factory, advisor)
    with session_factory() as s:
        s.add(admin)
        s.commit()
    client = _client_with_user(session_factory, admin)
    resp = client.post(f"/mandates/{mid}/strategy-snapshots", json=SNAPSHOT_PAYLOAD)
    assert resp.status_code == 201, resp.text


def test_g1_advisor_can_snapshot_own_mandate(session_factory, cleanup_overrides):
    """Sanity: Advisor darf weiterhin eigene Mandate snapshotten."""
    advisor = _make_user("advisor", "own")
    cid, mid = _make_client_and_mandate(session_factory, advisor)
    client = _client_with_user(session_factory, advisor)
    resp = client.post(f"/mandates/{mid}/strategy-snapshots", json=SNAPSHOT_PAYLOAD)
    assert resp.status_code == 201, resp.text


# ============================================================================
# G2 - review.py:refresh_system_triggers braucht require_advisor
# ============================================================================

def test_g2_refresh_system_triggers_requires_advisor(session_factory, cleanup_overrides):
    advisor = _make_user("advisor", "rsta")
    readonly = _make_user("readonly", "rsta")
    cid, mid = _make_client_and_mandate(session_factory, advisor)
    with session_factory() as s:
        s.add(readonly)
        s.commit()
    client = _client_with_user(session_factory, readonly)
    resp = client.post(f"/mandates/{mid}/triggers/system-refresh")
    assert resp.status_code == 403, resp.text


# ============================================================================
# G3 - system.py:list_audit_log: LIKE-Wildcards muessen escaped werden
# ============================================================================

def test_g3_audit_log_search_escapes_like_wildcards(session_factory, cleanup_overrides):
    """Suche '%' darf nicht auf alle Eintraege matchen, sondern nur auf Literale."""
    admin = _make_user("admin", "g3")
    with session_factory() as s:
        s.add(admin)
        # Drei AuditLog-Eintraege: einer mit Literalem '%', zwei ohne.
        for tn, un in (("clients", "alice"), ("mandates", "bob"), ("clients", "carol100%cool")):
            s.add(AuditLog(
                id=str(uuid.uuid4()),
                user_id=admin.id, user_name=un,
                table_name=tn, record_id=str(uuid.uuid4()),
                action="CREATE",
                created_at=_now(),
            ))
        s.commit()
    client = _client_with_user(session_factory, admin)
    # ohne escape matched '%' alle drei Eintraege; mit escape nur den einen mit '%'
    resp = client.get("/admin/system/audit-log?q=%25")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1, (
        f"Erwarte genau 1 Treffer fuer literal '%'-Suche, bekam {body['total']}: {body}"
    )
