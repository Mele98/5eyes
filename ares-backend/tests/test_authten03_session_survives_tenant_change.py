"""AUTH-TEN-03 (Codex-Audit 2026-08-25, docs/audits/2026-08-25-auth-execution-
operations-followup-audit.md): eine VOR der Tenant-Zuweisung ausgestellte
Session (Access- UND Refresh-Token) blieb bisher gueltig und wechselte
stillschweigend in den neuen Mandanten-Scope, ohne dass sich der User erneut
authentisieren musste. Dasselbe Problem existierte bei Deaktivierung und
Rollenaenderung ueber PUT /users/{id} -- beide sind laut Fixvertrag genauso
sicherheitsrelevant wie ein Passwortwechsel (bereits AUTH-TEN-01/Wave-12
abgesichert).

Diese Tests fahren den echten HTTP-Login-/Refresh-Flow (nicht get_current_user
ueberschrieben) durch, um die tatsaechliche Session-Invalidierung End-to-End
zu beweisen.
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

from config import settings  # noqa: E402
from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import hash_password  # noqa: E402


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'authten03.db'}",
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


@pytest.fixture(autouse=True)
def _enable_tenant_admin_ui(monkeypatch):
    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", True, raising=False)


def _seed_tenant(SF, tenant_id):
    with SF() as s:
        s.add(Tenant(
            id=tenant_id, display_name=tenant_id, slug=tenant_id.lower(),
            hosting_tier="tier2", license_status="active", max_users=10,
            is_active=1, created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def _seed_user(SF, uid, password, role="advisor", tenant_id=None):
    with SF() as s:
        s.add(User(
            id=uid, username=uid, password_hash=hash_password(password),
            full_name=uid, role=role, is_active=1, tenant_id=tenant_id,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def _login(client, username, password):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Tenant-Zuweisung
# ---------------------------------------------------------------------------

def test_tenant_assignment_revokes_targets_access_token(client, session_factory):
    _seed_tenant(session_factory, "firm-target")
    _seed_user(session_factory, "authten03-u1", "pw12345678", role="admin")
    _seed_user(session_factory, "authten03-admin1", "adminpw12345", role="super_admin")

    target = _login(client, "authten03-u1", "pw12345678")
    target_headers = {"Authorization": f"Bearer {target['access_token']}"}
    assert client.get("/auth/me", headers=target_headers).status_code == 200

    admin = _login(client, "authten03-admin1", "adminpw12345")
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}

    resp = client.put(
        "/tenants/firm-target/users/authten03-u1/assign", headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    assert client.get("/auth/me", headers=target_headers).status_code == 401


def test_tenant_assignment_revokes_targets_refresh_token(client, session_factory):
    _seed_tenant(session_factory, "firm-target2")
    _seed_user(session_factory, "authten03-u2", "pw12345678", role="advisor")
    _seed_user(session_factory, "authten03-admin2", "adminpw12345", role="super_admin")

    target = _login(client, "authten03-u2", "pw12345678")
    target_refresh = target["refresh_token"]
    assert target_refresh

    admin = _login(client, "authten03-admin2", "adminpw12345")
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}

    resp = client.put(
        "/tenants/firm-target2/users/authten03-u2/assign", headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    refresh_resp = client.post("/auth/refresh", json={"refresh_token": target_refresh})
    assert refresh_resp.status_code == 401


def test_reassignment_to_same_tenant_does_not_revoke_session(client, session_factory):
    """Regressionsschutz: eine No-Op-Zuweisung (bereits im Zieltenant) darf
    den Admin nicht ungefragt aus seiner eigenen Session werfen."""
    _seed_tenant(session_factory, "firm-same")
    _seed_user(session_factory, "authten03-u3", "pw12345678", role="advisor", tenant_id="firm-same")
    _seed_user(session_factory, "authten03-admin3", "adminpw12345", role="super_admin")

    target = _login(client, "authten03-u3", "pw12345678")
    target_headers = {"Authorization": f"Bearer {target['access_token']}"}

    admin = _login(client, "authten03-admin3", "adminpw12345")
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}

    resp = client.put(
        "/tenants/firm-same/users/authten03-u3/assign", headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    assert client.get("/auth/me", headers=target_headers).status_code == 200


# ---------------------------------------------------------------------------
# PUT /users/{id} -- Deaktivierung und Rollenaenderung
# ---------------------------------------------------------------------------

def test_deactivation_revokes_targets_session(client, session_factory):
    _seed_user(session_factory, "authten03-u4", "pw12345678", role="advisor")
    _seed_user(session_factory, "authten03-admin4", "adminpw12345", role="admin")

    target = _login(client, "authten03-u4", "pw12345678")
    target_headers = {"Authorization": f"Bearer {target['access_token']}"}
    assert client.get("/auth/me", headers=target_headers).status_code == 200

    admin = _login(client, "authten03-admin4", "adminpw12345")
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}

    resp = client.put(
        "/users/authten03-u4", json={"is_active": False}, headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    assert client.get("/auth/me", headers=target_headers).status_code == 401


def test_role_change_revokes_targets_session(client, session_factory):
    _seed_user(session_factory, "authten03-u5", "pw12345678", role="advisor")
    _seed_user(session_factory, "authten03-admin5", "adminpw12345", role="admin")

    target = _login(client, "authten03-u5", "pw12345678")
    target_headers = {"Authorization": f"Bearer {target['access_token']}"}

    admin = _login(client, "authten03-admin5", "adminpw12345")
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}

    resp = client.put(
        "/users/authten03-u5", json={"role": "admin"}, headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    assert client.get("/auth/me", headers=target_headers).status_code == 401


def test_unrelated_field_update_does_not_revoke_session(client, session_factory):
    """Regressionsschutz: full_name/email-Aenderungen sind NICHT
    sicherheitsrelevant -- der Admin darf dabei nicht die Session des Ziels
    (oder gar seine eigene, falls Self-Update erlaubt waere) unbeabsichtigt
    beenden."""
    _seed_user(session_factory, "authten03-u6", "pw12345678", role="advisor")
    _seed_user(session_factory, "authten03-admin6", "adminpw12345", role="admin")

    target = _login(client, "authten03-u6", "pw12345678")
    target_headers = {"Authorization": f"Bearer {target['access_token']}"}

    admin = _login(client, "authten03-admin6", "adminpw12345")
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}

    resp = client.put(
        "/users/authten03-u6", json={"full_name": "Neuer Name"}, headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    assert client.get("/auth/me", headers=target_headers).status_code == 200


def test_reactivation_after_deactivation_does_not_need_revocation(client, session_factory):
    """Aktivierung (is_active True) ist kein Session-Widerruf-Trigger -- es
    gibt zu diesem Zeitpunkt (User war deaktiviert) keine gueltige Session
    des Ziels mehr, die geschuetzt werden muesste."""
    _seed_user(session_factory, "authten03-u7", "pw12345678", role="advisor")
    _seed_user(session_factory, "authten03-admin7", "adminpw12345", role="admin")

    admin = _login(client, "authten03-admin7", "adminpw12345")
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}

    deactivate = client.put(
        "/users/authten03-u7", json={"is_active": False}, headers=admin_headers,
    )
    assert deactivate.status_code == 200

    reactivate = client.put(
        "/users/authten03-u7", json={"is_active": True}, headers=admin_headers,
    )
    assert reactivate.status_code == 200

    # Fresh login funktioniert nach der Reaktivierung wieder normal.
    fresh = client.post(
        "/auth/login", json={"username": "authten03-u7", "password": "pw12345678"},
    )
    assert fresh.status_code == 200
