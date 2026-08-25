"""HUD-Polish (2026-08-02): Tests fuer die Wealthmanagement/Consulting-
"Maske" (Tenant.default_presentation_mode).

Verifiziert:
1. Additive Migration (Model + ensure_runtime_columns), Validierung erlaubter
   Werte.
2. Roundtrip via POST/PUT /tenants (super_admin, Tier 2).
3. GET/PUT /tenants/me (tier-unabhaengig).
4. /auth/bootstrap-admin setzt den Firmen-Default best-effort.
5. TokenResponse.tenant_default_presentation_mode wird bei JEDEM Login
   mitgeliefert (nicht nur admin/super_admin via GET /tenants/me), damit
   auch ein normaler Advisor die Firmenpraeferenz ohne 403 erfaehrt.

Rein UI-seitiges Feature -- KEINE Engine-/Compliance-Wirkung. Die eigentliche
Sichtbarkeits-Logik (data-wm-only) lebt im Frontend (5eyes_v2.html) und ist
hier nicht Gegenstand (kein Python-Test moeglich ohne Browser).
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import settings
from database import Base, get_db
from main import app
from models.tenant import DEFAULT_TENANT_ID, Tenant
from models.users import User
from services.auth import get_current_user


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'presentation_mode.db'}",
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
def client(session_factory):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login_as(user_id, role, tenant_id):
    user = User(id=user_id, username=user_id, password_hash="h", full_name=user_id,
                role=role, is_active=1, tenant_id=tenant_id)
    app.dependency_overrides[get_current_user] = lambda: user


def _logout():
    app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# 1. Schema-Migration + Validierung
# ---------------------------------------------------------------------------


def test_tenant_default_presentation_mode_column_exists(session_factory):
    with session_factory() as s:
        inspector = inspect(s.get_bind())
        cols = {c["name"] for c in inspector.get_columns("tenants")}
        assert "default_presentation_mode" in cols


def test_ensure_runtime_columns_presentation_mode_idempotent(session_factory):
    import database as db_module
    engine = session_factory().get_bind()
    original_engine = db_module.engine
    db_module.engine = engine
    try:
        db_module.ensure_runtime_columns()
        db_module.ensure_runtime_columns()
        inspector = inspect(engine)
        assert "default_presentation_mode" in {c["name"] for c in inspector.get_columns("tenants")}
    finally:
        db_module.engine = original_engine


def test_create_tenant_rejects_invalid_presentation_mode(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", True, raising=False)
    _login_as("super-invalid", "super_admin", tenant_id=None)
    try:
        resp = client.post("/tenants", json={
            "display_name": "Bad Firma", "slug": "bad-firma",
            "default_presentation_mode": "nonsense",
        })
        assert resp.status_code == 422, resp.text
    finally:
        _logout()


# ---------------------------------------------------------------------------
# 2. Super-Admin CRUD (Tier 2) -- default_presentation_mode roundtrip
# ---------------------------------------------------------------------------


def test_create_tenant_with_consulting_default(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", True, raising=False)
    _login_as("super-1", "super_admin", tenant_id=None)
    try:
        resp = client.post("/tenants", json={
            "display_name": "Consulting-Firma", "slug": "consulting-firma",
            "default_presentation_mode": "consulting",
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["default_presentation_mode"] == "consulting"
    finally:
        _logout()


def test_create_tenant_without_presentation_mode_is_null(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", True, raising=False)
    _login_as("super-2", "super_admin", tenant_id=None)
    try:
        resp = client.post("/tenants", json={"display_name": "CH-Firma", "slug": "ch-firma-pm"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["default_presentation_mode"] is None
    finally:
        _logout()


def test_update_tenant_presentation_mode(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", True, raising=False)
    _login_as("super-3", "super_admin", tenant_id=None)
    try:
        created = client.post("/tenants", json={"display_name": "Firma Y", "slug": "firma-y"})
        tid = created.json()["id"]
        updated = client.put(f"/tenants/{tid}", json={"default_presentation_mode": "consulting"})
        assert updated.status_code == 200, updated.text
        assert updated.json()["default_presentation_mode"] == "consulting"
    finally:
        _logout()


def test_update_tenant_rejects_invalid_presentation_mode(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", True, raising=False)
    _login_as("super-4", "super_admin", tenant_id=None)
    try:
        created = client.post("/tenants", json={"display_name": "Firma Z", "slug": "firma-z"})
        tid = created.json()["id"]
        updated = client.put(f"/tenants/{tid}", json={"default_presentation_mode": "garbage"})
        assert updated.status_code == 422
    finally:
        _logout()


# ---------------------------------------------------------------------------
# 3. GET/PUT /tenants/me
# ---------------------------------------------------------------------------


def test_get_my_tenant_returns_presentation_mode(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", False, raising=False)
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id=DEFAULT_TENANT_ID, display_name="Default Tenant", slug="main",
            hosting_tier="tier1", license_status="active",
            default_presentation_mode="consulting",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    _login_as("admin-1", "admin", tenant_id=DEFAULT_TENANT_ID)
    try:
        resp = client.get("/tenants/me")
        assert resp.status_code == 200, resp.text
        assert resp.json()["default_presentation_mode"] == "consulting"
    finally:
        _logout()


def test_update_my_tenant_sets_presentation_mode(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", False, raising=False)
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id=DEFAULT_TENANT_ID, display_name="Default Tenant", slug="main",
            hosting_tier="tier1", license_status="active",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    _login_as("admin-2", "admin", tenant_id=DEFAULT_TENANT_ID)
    try:
        resp = client.put("/tenants/me", json={"default_presentation_mode": "consulting"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["default_presentation_mode"] == "consulting"
    finally:
        _logout()


# ---------------------------------------------------------------------------
# 4. /auth/bootstrap-admin -- setzt default_presentation_mode best-effort
# ---------------------------------------------------------------------------


def test_bootstrap_admin_sets_presentation_mode(client, session_factory):
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id=DEFAULT_TENANT_ID, display_name="Default Tenant", slug="main",
            hosting_tier="tier1", license_status="active",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    resp = client.post("/auth/bootstrap-admin", json={
        "username": "pmadmin", "password": "StrongPass1234",
        "full_name": "PM Admin", "default_presentation_mode": "consulting",
    })
    assert resp.status_code == 201, resp.text
    with session_factory() as s:
        tenant = s.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
        assert tenant.default_presentation_mode == "consulting"


def test_bootstrap_admin_rejects_invalid_presentation_mode(client, session_factory):
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id=DEFAULT_TENANT_ID, display_name="Default Tenant", slug="main",
            hosting_tier="tier1", license_status="active",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    resp = client.post("/auth/bootstrap-admin", json={
        "username": "pmadmin2", "password": "StrongPass1234",
        "full_name": "PM Admin Zwei", "default_presentation_mode": "garbage",
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 5. TokenResponse.tenant_default_presentation_mode bei JEDEM Login
# ---------------------------------------------------------------------------


def test_login_response_includes_tenant_presentation_mode_for_advisor(client, session_factory):
    """Ein normaler Advisor (kein admin/super_admin, siehe require_admin auf
    GET /tenants/me) MUSS die Firmenpraeferenz trotzdem kennen -- deshalb
    wird sie bei JEDEM Login mitgeliefert, nicht nur ueber /tenants/me."""
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id=DEFAULT_TENANT_ID, display_name="Default Tenant", slug="main",
            hosting_tier="tier1", license_status="active",
            default_presentation_mode="consulting",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    resp = client.post("/auth/bootstrap-admin", json={
        "username": "loginadvisor", "password": "StrongPass1234",
        "full_name": "Login Advisor",
    })
    assert resp.status_code == 201, resp.text
    login_resp = client.post("/auth/login", json={
        "username": "loginadvisor", "password": "StrongPass1234",
    })
    assert login_resp.status_code == 200, login_resp.text
    assert login_resp.json()["tenant_default_presentation_mode"] == "consulting"


def test_login_response_presentation_mode_null_when_tenant_default_unset(client, session_factory):
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id=DEFAULT_TENANT_ID, display_name="Default Tenant", slug="main",
            hosting_tier="tier1", license_status="active",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    resp = client.post("/auth/bootstrap-admin", json={
        "username": "loginadvisor2", "password": "StrongPass1234",
        "full_name": "Login Advisor Zwei",
    })
    assert resp.status_code == 201, resp.text
    login_resp = client.post("/auth/login", json={
        "username": "loginadvisor2", "password": "StrongPass1234",
    })
    assert login_resp.status_code == 200, login_resp.text
    assert login_resp.json()["tenant_default_presentation_mode"] is None


def test_bootstrap_admin_response_includes_presentation_mode(client, session_factory):
    """Die Bootstrap-Admin-Response ist selbst auch eine TokenResponse
    (der User loggt sich implizit mit ein) -- muss also ebenfalls das Feld
    liefern, konsistent mit dem eben gesetzten Firmen-Default."""
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id=DEFAULT_TENANT_ID, display_name="Default Tenant", slug="main",
            hosting_tier="tier1", license_status="active",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    resp = client.post("/auth/bootstrap-admin", json={
        "username": "bootstrapadmin3", "password": "StrongPass1234",
        "full_name": "Bootstrap Admin Drei", "default_presentation_mode": "consulting",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["tenant_default_presentation_mode"] == "consulting"
