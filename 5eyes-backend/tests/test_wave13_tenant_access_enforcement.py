"""2026-07-25 (Generalaudit, Wave 13 -- Tenant-Admin-API-Fork): Tenant.is_active
und Tenant.license_status waren reine Metadaten OHNE Wirkung im Auth-Layer.
Die einzige in der API exponierte "Tenant abschalten"-Aktion (PUT /tenants/{id}
mit is_active=0 oder license_status='suspended') hatte keine tatsaechliche
Zugriffssperre zur Folge -- Nutzer eines deaktivierten/gesperrten Tenants
konnten sich unveraendert weiter einloggen und mit bestehenden Tokens arbeiten.
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
from models.tenant import Tenant
from models.users import User
from services.auth import hash_password


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_tenant_enforcement.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(session_factory):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_login_guard():
    from services.login_guard import login_attempt_guard
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()
    yield
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()


def _tenant(tenant_id: str, *, is_active: int = 1, license_status: str = "active") -> Tenant:
    return Tenant(
        id=tenant_id, display_name=f"Firma {tenant_id}", slug=tenant_id.lower(),
        hosting_tier="tier2", license_status=license_status, max_users=10,
        is_active=is_active, created_at=_now(), updated_at=_now(),
    )


def _seed_user(SF, uid, password, tenant_id):
    with SF() as s:
        s.add(User(
            id=uid, username=uid, password_hash=hash_password(password),
            full_name=uid, role="advisor", is_active=1, tenant_id=tenant_id,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def test_login_blocked_when_tenant_deactivated(client, session_factory):
    with session_factory() as s:
        s.add(_tenant("firm-inactive", is_active=0))
        s.commit()
    _seed_user(session_factory, "u-inactive-tenant", "pw12345678", "firm-inactive")

    r = client.post("/auth/login", json={"username": "u-inactive-tenant", "password": "pw12345678"})
    assert r.status_code == 403
    assert "deaktiviert" in r.json()["detail"].lower()


def test_login_blocked_when_license_suspended(client, session_factory):
    with session_factory() as s:
        s.add(_tenant("firm-suspended", license_status="suspended"))
        s.commit()
    _seed_user(session_factory, "u-suspended-tenant", "pw12345678", "firm-suspended")

    r = client.post("/auth/login", json={"username": "u-suspended-tenant", "password": "pw12345678"})
    assert r.status_code == 403
    assert "lizenz" in r.json()["detail"].lower()


def test_login_blocked_when_license_expired(client, session_factory):
    with session_factory() as s:
        s.add(_tenant("firm-expired", license_status="expired"))
        s.commit()
    _seed_user(session_factory, "u-expired-tenant", "pw12345678", "firm-expired")

    r = client.post("/auth/login", json={"username": "u-expired-tenant", "password": "pw12345678"})
    assert r.status_code == 403


def test_login_succeeds_for_active_tenant(client, session_factory):
    with session_factory() as s:
        s.add(_tenant("firm-active"))
        s.commit()
    _seed_user(session_factory, "u-active-tenant", "pw12345678", "firm-active")

    r = client.post("/auth/login", json={"username": "u-active-tenant", "password": "pw12345678"})
    assert r.status_code == 200, r.text


def test_login_succeeds_for_trial_tenant(client, session_factory):
    with session_factory() as s:
        s.add(_tenant("firm-trial", license_status="trial"))
        s.commit()
    _seed_user(session_factory, "u-trial-tenant", "pw12345678", "firm-trial")

    r = client.post("/auth/login", json={"username": "u-trial-tenant", "password": "pw12345678"})
    assert r.status_code == 200, r.text


def test_login_unaffected_when_no_tenant_id_set(client, session_factory):
    """Legacy/Pre-T1-User ohne tenant_id -- keine Regression fuer Tier-1-Solo-Betrieb."""
    _seed_user(session_factory, "u-no-tenant", "pw12345678", None)

    r = client.post("/auth/login", json={"username": "u-no-tenant", "password": "pw12345678"})
    assert r.status_code == 200, r.text


def test_existing_token_rejected_after_tenant_deactivated_mid_session(client, session_factory):
    """get_current_user muss den Tenant-Status bei JEDEM Request neu pruefen --
    nicht nur beim Login. Ein bereits ausgestelltes Token darf nach nachtraeglicher
    Tenant-Deaktivierung nicht weiter funktionieren."""
    with session_factory() as s:
        s.add(_tenant("firm-live", is_active=1))
        s.commit()
    _seed_user(session_factory, "u-live-tenant", "pw12345678", "firm-live")

    login = client.post("/auth/login", json={"username": "u-live-tenant", "password": "pw12345678"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/auth/me", headers=headers).status_code == 200

    with session_factory() as s:
        tenant = s.query(Tenant).filter_by(id="firm-live").first()
        tenant.is_active = 0
        s.commit()

    resp = client.get("/auth/me", headers=headers)
    assert resp.status_code == 403
