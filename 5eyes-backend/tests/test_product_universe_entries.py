"""2026-07-27 (Fonds-Kuratierung): Tests fuer die ProductUniverseEntry-CRUD-
Endpoints (/product-universe).

Verifiziert:
  - Admin kann Eintraege anlegen/listen/updaten/loeschen (soft-delete)
  - Harte Tenant-Trennung: Eintrag eines anderen Tenants ist nicht sichtbar (404)
  - Duplikat (gleicher Tenant+Jurisdiktion+Produkt, aktiv) -> 409
  - Nicht-Admin (advisor) -> 403
  - Unbekanntes Produkt -> 404
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
from models.review import Product
from models.tenant import Tenant
from models.users import User
from services.auth import get_current_user


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'product_universe.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed(SF, *, tenant_id="firm-a", other_tenant_id="firm-b"):
    now = _now()
    with SF() as s:
        for tid in (tenant_id, other_tenant_id, "main"):
            s.add(Tenant(
                id=tid, display_name=tid, slug=tid,
                hosting_tier="tier2", license_status="active",
                is_active=1, created_at=now, updated_at=now,
            ))
        s.add(User(
            id="admin-a", username="admin-a", password_hash="h",
            full_name="Admin A", role="admin", is_active=1, tenant_id=tenant_id,
            created_at=now, updated_at=now,
        ))
        s.add(User(
            id="advisor-a", username="advisor-a", password_hash="h",
            full_name="Advisor A", role="advisor", is_active=1, tenant_id=tenant_id,
            created_at=now, updated_at=now,
        ))
        s.add(User(
            id="admin-b", username="admin-b", password_hash="h",
            full_name="Admin B", role="admin", is_active=1, tenant_id=other_tenant_id,
            created_at=now, updated_at=now,
        ))
        # 2026-07-29 (UI-Verifikation): Admin ohne tenant_id (z.B. frisch
        # gebootstrapped, vor dem naechsten Boot-Backfill) -- muss ueber
        # DEFAULT_TENANT_ID ('main') fallback nutzbar bleiben.
        s.add(User(
            id="admin-null-tenant", username="admin-null-tenant", password_hash="h",
            full_name="Admin Null-Tenant", role="admin", is_active=1, tenant_id=None,
            created_at=now, updated_at=now,
        ))
        s.add(User(
            id="admin-main-tenant", username="admin-main-tenant", password_hash="h",
            full_name="Admin Main-Tenant", role="admin", is_active=1, tenant_id="main",
            created_at=now, updated_at=now,
        ))
        s.add(Product(
            id="prod-1", product_name="Fonds A", asset_class="Aktien",
            product_type="ETF", currency="CHF", is_active=1, ter_bps=20,
            created_at=now, updated_at=now,
        ))
        s.commit()


@pytest.fixture()
def client(session_factory):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login_as(user_id):
    with_session_user_map = {
        "admin-a": ("firm-a", "admin"),
        "advisor-a": ("firm-a", "advisor"),
        "admin-b": ("firm-b", "admin"),
        "admin-null-tenant": (None, "admin"),
        "admin-main-tenant": ("main", "admin"),
    }
    tenant_id, role = with_session_user_map[user_id]
    user = User(id=user_id, username=user_id, password_hash="h",
                full_name=user_id, role=role, is_active=1, tenant_id=tenant_id)
    app.dependency_overrides[get_current_user] = lambda: user


def test_admin_can_create_and_list_entry(client, session_factory):
    _seed(session_factory)
    _login_as("admin-a")
    try:
        resp = client.post("/product-universe", json={
            "jurisdiction": "CH", "product_id": "prod-1", "override_ter_bps": 5,
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["tenant_id"] == "firm-a"
        assert body["jurisdiction"] == "CH"
        assert body["override_ter_bps"] == 5

        listed = client.get("/product-universe")
        assert listed.status_code == 200
        assert len(listed.json()) == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_advisor_forbidden(client, session_factory):
    _seed(session_factory)
    _login_as("advisor-a")
    try:
        resp = client.post("/product-universe", json={
            "jurisdiction": "CH", "product_id": "prod-1",
        })
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_unknown_product_404(client, session_factory):
    _seed(session_factory)
    _login_as("admin-a")
    try:
        resp = client.post("/product-universe", json={
            "jurisdiction": "CH", "product_id": "does-not-exist",
        })
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_duplicate_entry_conflicts(client, session_factory):
    _seed(session_factory)
    _login_as("admin-a")
    try:
        first = client.post("/product-universe", json={
            "jurisdiction": "CH", "product_id": "prod-1",
        })
        assert first.status_code == 201, first.text
        second = client.post("/product-universe", json={
            "jurisdiction": "CH", "product_id": "prod-1",
        })
        assert second.status_code == 409
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_other_tenant_cannot_see_or_modify_entry(client, session_factory):
    _seed(session_factory)
    _login_as("admin-a")
    entry_id = None
    try:
        created = client.post("/product-universe", json={
            "jurisdiction": "CH", "product_id": "prod-1",
        })
        entry_id = created.json()["id"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    _login_as("admin-b")
    try:
        listed = client.get("/product-universe")
        assert listed.status_code == 200
        assert listed.json() == []

        updated = client.put(f"/product-universe/{entry_id}", json={"override_ter_bps": 1})
        assert updated.status_code == 404

        deleted = client.delete(f"/product-universe/{entry_id}")
        assert deleted.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_update_and_soft_delete_roundtrip(client, session_factory):
    _seed(session_factory)
    _login_as("admin-a")
    try:
        created = client.post("/product-universe", json={
            "jurisdiction": "CH", "product_id": "prod-1",
        })
        entry_id = created.json()["id"]
        assert created.json()["override_ter_bps"] is None

        updated = client.put(f"/product-universe/{entry_id}", json={"override_ter_bps": 12})
        assert updated.status_code == 200
        assert updated.json()["override_ter_bps"] == 12

        deleted = client.delete(f"/product-universe/{entry_id}")
        assert deleted.status_code == 204

        listed = client.get("/product-universe")
        assert listed.json() == []

        # Nach Soft-Delete kann derselbe (tenant, jurisdiction, product) neu angelegt werden.
        recreated = client.post("/product-universe", json={
            "jurisdiction": "CH", "product_id": "prod-1",
        })
        assert recreated.status_code == 201, recreated.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_jurisdiction_filter_query_param(client, session_factory):
    _seed(session_factory)
    _login_as("admin-a")
    try:
        client.post("/product-universe", json={"jurisdiction": "CH", "product_id": "prod-1"})
        listed_ch = client.get("/product-universe", params={"jurisdiction": "CH"})
        assert len(listed_ch.json()) == 1
        listed_de = client.get("/product-universe", params={"jurisdiction": "DE"})
        assert listed_de.json() == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_admin_without_tenant_id_can_create_and_list(client, session_factory):
    """2026-07-29 (UI-Verifikation, echter Bug via Browser-Test gefunden):
    ein Admin ohne tenant_id (z.B. frisch via /auth/bootstrap-admin
    angelegt, vor dem naechsten Boot-Backfill) durfte das Feature vorher
    gar nicht nutzen (422 'Benutzer ohne Tenant...'). Muss stattdessen wie
    ueberall im Code auf DEFAULT_TENANT_ID ('main') fallen."""
    _seed(session_factory)
    _login_as("admin-null-tenant")
    try:
        created = client.post("/product-universe", json={
            "jurisdiction": "CH", "product_id": "prod-1",
        })
        assert created.status_code == 201, created.text
        assert created.json()["tenant_id"] == "main"

        listed = client.get("/product-universe")
        assert listed.status_code == 200
        assert len(listed.json()) == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_null_tenant_and_main_tenant_share_the_same_effective_scope(client, session_factory):
    """Ein Admin mit tenant_id=NULL und einer mit tenant_id='main' muessen
    dieselben Eintraege sehen/verwalten koennen -- beide loesen auf densel-
    ben effektiven Tenant auf."""
    _seed(session_factory)
    _login_as("admin-null-tenant")
    try:
        created = client.post("/product-universe", json={
            "jurisdiction": "CH", "product_id": "prod-1",
        })
        entry_id = created.json()["id"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    _login_as("admin-main-tenant")
    try:
        listed = client.get("/product-universe")
        assert len(listed.json()) == 1
        assert listed.json()[0]["id"] == entry_id

        updated = client.put(f"/product-universe/{entry_id}", json={"override_ter_bps": 9})
        assert updated.status_code == 200, updated.text
        assert updated.json()["override_ter_bps"] == 9
    finally:
        app.dependency_overrides.pop(get_current_user, None)
