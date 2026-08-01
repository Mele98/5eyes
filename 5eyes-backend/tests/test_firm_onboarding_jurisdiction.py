"""2026-08-01 (Onboarding, Entscheid Auftraggeber): Tests fuer den Standort
der lizenznehmenden Firma (Tenant.home_jurisdiction) und dessen Verwendung
als Default fuer neue Mandate.

Verifiziert:
1. Tenant.home_jurisdiction: additive Migration, Roundtrip via POST/PUT /tenants.
2. GET/PUT /tenants/me: funktioniert TIER-UNABHAENGIG (Tier 1 + Tier 2),
   im Gegensatz zur super_admin-only /tenants/{id}-API. Muss vor /{tenant_id}
   registriert sein (Pfad-Kollisions-Check).
3. /auth/bootstrap-admin: setzt company_name/home_jurisdiction auf der
   Default-Tenant-Zeile ('main'), best-effort (Ersteinrichtung darf nicht
   daran scheitern).
4. POST /clients/{id}/mandates: neue Mandate erben Tenant.home_jurisdiction
   als Default, koennen es aber explizit ueberschreiben (Firmen mit Kunden
   in mehreren Laendern).
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
from models.clients import Client
from models.tenant import DEFAULT_TENANT_ID, Tenant
from models.users import User
from services.auth import get_current_user


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'firm_onboarding.db'}",
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
# 1. Schema-Migration
# ---------------------------------------------------------------------------


def test_tenant_home_jurisdiction_column_exists(session_factory):
    with session_factory() as s:
        inspector = inspect(s.get_bind())
        cols = {c["name"] for c in inspector.get_columns("tenants")}
        assert "home_jurisdiction" in cols


def test_ensure_runtime_columns_tenants_idempotent_when_table_already_current(session_factory):
    """Die 'tenants'-Tabelle existiert NICHT im Raw-Bootstrap-SQL (rein ORM-
    erzeugt via Base.metadata.create_all(), siehe models/tenant.py) -- ein
    Legacy-Raw-SQL-Migrationstest wie fuer capital_market_assumptions ist
    hier also nicht anwendbar. Stattdessen: ensure_runtime_columns() zweimal
    gegen eine bereits aktuelle, ORM-erzeugte DB ausfuehren darf keinen
    Fehler werfen und die Spalte nicht duplizieren/zerstoeren."""
    import database as db_module
    engine = session_factory().get_bind()
    original_engine = db_module.engine
    db_module.engine = engine
    try:
        db_module.ensure_runtime_columns()
        db_module.ensure_runtime_columns()
        inspector = inspect(engine)
        assert "home_jurisdiction" in {c["name"] for c in inspector.get_columns("tenants")}
    finally:
        db_module.engine = original_engine


# ---------------------------------------------------------------------------
# 2. Super-Admin CRUD (Tier 2) -- home_jurisdiction roundtrip
# ---------------------------------------------------------------------------


def test_create_tenant_with_home_jurisdiction(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", True, raising=False)
    _login_as("super-1", "super_admin", tenant_id=None)
    try:
        resp = client.post("/tenants", json={
            "display_name": "DE-Firma", "slug": "de-firma", "home_jurisdiction": "DE",
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["home_jurisdiction"] == "DE"
    finally:
        _logout()


def test_create_tenant_without_home_jurisdiction_is_null(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", True, raising=False)
    _login_as("super-2", "super_admin", tenant_id=None)
    try:
        resp = client.post("/tenants", json={"display_name": "CH-Firma", "slug": "ch-firma"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["home_jurisdiction"] is None
    finally:
        _logout()


def test_update_tenant_home_jurisdiction(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", True, raising=False)
    _login_as("super-3", "super_admin", tenant_id=None)
    try:
        created = client.post("/tenants", json={"display_name": "Firma X", "slug": "firma-x"})
        tid = created.json()["id"]
        updated = client.put(f"/tenants/{tid}", json={"home_jurisdiction": "DE"})
        assert updated.status_code == 200, updated.text
        assert updated.json()["home_jurisdiction"] == "DE"
    finally:
        _logout()


# ---------------------------------------------------------------------------
# 3. GET/PUT /tenants/me -- tier-unabhaengig, muss vor /{tenant_id} matchen
# ---------------------------------------------------------------------------


def test_get_my_tenant_works_even_when_tenant_admin_ui_disabled(client, session_factory, monkeypatch):
    """Tier 1/3: settings.tenant_admin_ui_enabled=False -- /tenants/{id} waere
    503, aber /tenants/me MUSS trotzdem funktionieren."""
    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", False, raising=False)
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id=DEFAULT_TENANT_ID, display_name="Default Tenant", slug="main",
            hosting_tier="tier1", license_status="active", home_jurisdiction="DE",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    _login_as("admin-1", "admin", tenant_id=DEFAULT_TENANT_ID)
    try:
        resp = client.get("/tenants/me")
        assert resp.status_code == 200, resp.text
        assert resp.json()["home_jurisdiction"] == "DE"

        # Sanity: die super_admin-only Route ist tatsaechlich 503 (beweist,
        # dass /tenants/me NICHT einfach zufaellig auch funktionieren wuerde).
        blocked = client.get(f"/tenants/{DEFAULT_TENANT_ID}")
        assert blocked.status_code in (403, 503)
    finally:
        _logout()


def test_update_my_tenant_sets_home_jurisdiction(client, session_factory, monkeypatch):
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
        resp = client.put("/tenants/me", json={
            "display_name": "Meine Firma AG", "home_jurisdiction": "DE",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["display_name"] == "Meine Firma AG"
        assert resp.json()["home_jurisdiction"] == "DE"
    finally:
        _logout()


def test_update_my_tenant_cannot_set_license_fields(client, session_factory, monkeypatch):
    """TenantSelfServiceUpdate ist bewusst schmaler als TenantUpdate -- ein
    normaler Admin darf hosting_tier/max_users/etc. nicht ueber diese Route
    aendern (kein Feld dafuer im Schema, extra Felder werden von Pydantic
    schlicht ignoriert, nicht validiert -> kein Fehler, aber auch kein Effekt)."""
    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", False, raising=False)
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id=DEFAULT_TENANT_ID, display_name="Default Tenant", slug="main",
            hosting_tier="tier1", license_status="trial", max_users=1,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    _login_as("admin-3", "admin", tenant_id=DEFAULT_TENANT_ID)
    try:
        resp = client.put("/tenants/me", json={"license_status": "active", "max_users": 999})
        assert resp.status_code == 200
        assert resp.json()["license_status"] == "trial"
        assert resp.json()["max_users"] == 1
    finally:
        _logout()


def test_my_tenant_requires_admin_role(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", False, raising=False)
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id=DEFAULT_TENANT_ID, display_name="Default Tenant", slug="main",
            hosting_tier="tier1", license_status="active",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    _login_as("advisor-1", "advisor", tenant_id=DEFAULT_TENANT_ID)
    try:
        resp = client.get("/tenants/me")
        assert resp.status_code == 403
    finally:
        _logout()


# ---------------------------------------------------------------------------
# 4. /auth/bootstrap-admin -- setzt company_name/home_jurisdiction
# ---------------------------------------------------------------------------


def test_bootstrap_admin_sets_company_name_and_jurisdiction(client, session_factory):
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id=DEFAULT_TENANT_ID, display_name="Default Tenant", slug="main",
            hosting_tier="tier1", license_status="active",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    resp = client.post("/auth/bootstrap-admin", json={
        "username": "firstadmin", "password": "StrongPass1234",
        "full_name": "Erster Admin", "company_name": "Mueller VV AG",
        "home_jurisdiction": "DE",
    })
    assert resp.status_code == 201, resp.text
    with session_factory() as s:
        tenant = s.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
        assert tenant.display_name == "Mueller VV AG"
        assert tenant.home_jurisdiction == "DE"


def test_bootstrap_admin_without_company_fields_leaves_tenant_unchanged(client, session_factory):
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id=DEFAULT_TENANT_ID, display_name="Default Tenant", slug="main",
            hosting_tier="tier1", license_status="active",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    resp = client.post("/auth/bootstrap-admin", json={
        "username": "firstadmin2", "password": "StrongPass1234", "full_name": "Admin Zwei",
    })
    assert resp.status_code == 201, resp.text
    with session_factory() as s:
        tenant = s.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
        assert tenant.display_name == "Default Tenant"
        assert tenant.home_jurisdiction is None


def test_bootstrap_admin_succeeds_even_if_default_tenant_row_missing(client, session_factory):
    """Best-effort: fehlt die 'main'-Tenant-Zeile ausnahmsweise (z.B. Boot-
    Reihenfolge-Edge-Case), darf die Ersteinrichtung trotzdem NICHT scheitern."""
    resp = client.post("/auth/bootstrap-admin", json={
        "username": "firstadmin3", "password": "StrongPass1234", "full_name": "Admin Drei",
        "company_name": "Firma ohne Tenant-Row",
    })
    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# 5. Mandat-Erstellung erbt Tenant.home_jurisdiction als Default
# ---------------------------------------------------------------------------


def _seed_client_for_mandate(session_factory, *, tenant_id, home_jurisdiction):
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id=tenant_id, display_name=tenant_id, slug=tenant_id,
            hosting_tier="tier2", license_status="active",
            home_jurisdiction=home_jurisdiction, is_active=1,
            created_at=now, updated_at=now,
        ))
        s.add(User(
            id=f"adv-{tenant_id}", username=f"adv-{tenant_id}", password_hash="h",
            full_name="Advisor", role="advisor", is_active=1, tenant_id=tenant_id,
            created_at=now, updated_at=now,
        ))
        s.add(Client(
            id=f"cli-{tenant_id}", client_number=f"C-{tenant_id}", first_name="T", last_name="X",
            advisor_id=f"adv-{tenant_id}", tenant_id=tenant_id,
            created_at=now, updated_at=now,
        ))
        s.commit()
    return f"adv-{tenant_id}", f"cli-{tenant_id}"


def test_new_mandate_inherits_tenant_home_jurisdiction(client, session_factory):
    advisor_id, client_id = _seed_client_for_mandate(
        session_factory, tenant_id="firm-de-onboard", home_jurisdiction="DE",
    )
    _login_as(advisor_id, "advisor", tenant_id="firm-de-onboard")
    try:
        resp = client.post(f"/clients/{client_id}/mandates", json={
            "mandate_number": "M-ONBOARD-1", "mandate_type": "Anlageberatung",
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["jurisdiction"] == "DE"
    finally:
        _logout()


def test_new_mandate_defaults_to_null_when_tenant_has_no_home_jurisdiction(client, session_factory):
    advisor_id, client_id = _seed_client_for_mandate(
        session_factory, tenant_id="firm-ch-onboard", home_jurisdiction=None,
    )
    _login_as(advisor_id, "advisor", tenant_id="firm-ch-onboard")
    try:
        resp = client.post(f"/clients/{client_id}/mandates", json={
            "mandate_number": "M-ONBOARD-2", "mandate_type": "Anlageberatung",
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["jurisdiction"] is None
    finally:
        _logout()


def test_new_mandate_explicit_jurisdiction_overrides_tenant_default(client, session_factory):
    """Firmen mit Kunden in mehreren Laendern: explizite Wahl geht vor dem
    Tenant-Default (z.B. eine DE-Firma hat auch einen Schweizer Kunden)."""
    advisor_id, client_id = _seed_client_for_mandate(
        session_factory, tenant_id="firm-multi-onboard", home_jurisdiction="DE",
    )
    _login_as(advisor_id, "advisor", tenant_id="firm-multi-onboard")
    try:
        resp = client.post(f"/clients/{client_id}/mandates", json={
            "mandate_number": "M-ONBOARD-3", "mandate_type": "Anlageberatung",
            "jurisdiction": "CH",
        })
        assert resp.status_code == 201, resp.text
        assert resp.json()["jurisdiction"] == "CH"
    finally:
        _logout()
