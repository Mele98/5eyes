"""Sprint T4 (2026-06-08): Tenant-Admin-API Tests.

Verifiziert:
1. Super-Admin-Role kann Tenants erstellen/listen/updaten
2. Regular-Admin und Advisor werden geblockt (403)
3. Settings tenant_admin_ui_enabled = False blockt alle Endpoints (503)
4. User-Tenant-Zuweisung funktioniert
5. Slug-Konflikt → 409
6. Pydantic-Validation: invalide tier / status → 422
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

from config import settings
from database import Base, get_db
from main import app
from models.tenant import (
    LICENSE_STATUS_TRIAL,
    TIER_2_SHARED_CLOUD,
    Tenant,
)
from models.users import User
from services.auth import get_current_user


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tenant_api.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def super_admin():
    return User(
        id="super-admin", username="superadmin", password_hash="h",
        full_name="Super Admin", role="super_admin", is_active=1,
        created_at=_utc_now(), updated_at=_utc_now(),
    )


@pytest.fixture
def regular_admin():
    return User(
        id="regular-admin", username="admin", password_hash="h",
        full_name="Regular Admin", role="admin", is_active=1,
        created_at=_utc_now(), updated_at=_utc_now(),
    )


@pytest.fixture
def advisor_user():
    return User(
        id="advisor", username="advisor", password_hash="h",
        full_name="Advisor", role="advisor", is_active=1,
        created_at=_utc_now(), updated_at=_utc_now(),
    )


def _make_client_as(user, session_factory, monkeypatch):
    """Helper: TestClient mit Auth-Override fuer einen User + Tier-2-Setting."""
    monkeypatch.setattr(
        settings, "tenant_admin_ui_enabled", True, raising=False,
    )

    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    return client


# ===========================================================================
# 1. Role-Schutz
# ===========================================================================


def test_super_admin_kann_tenant_erstellen(session_factory, super_admin, monkeypatch):
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        resp = client.post(
            "/tenants",
            json={
                "display_name": "Test Firm AG",
                "slug": "test-firm",
                "hosting_tier": TIER_2_SHARED_CLOUD,
                "license_status": LICENSE_STATUS_TRIAL,
                "max_users": 10,
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["display_name"] == "Test Firm AG"
        assert data["slug"] == "test-firm"
        assert data["hosting_tier"] == "tier2"
    finally:
        app.dependency_overrides.clear()


def test_regular_admin_geblockt_403(session_factory, regular_admin, monkeypatch):
    client = _make_client_as(regular_admin, session_factory, monkeypatch)
    try:
        resp = client.post(
            "/tenants",
            json={
                "display_name": "Test", "slug": "test-firm",
                "hosting_tier": TIER_2_SHARED_CLOUD,
            },
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_advisor_geblockt_403(session_factory, advisor_user, monkeypatch):
    client = _make_client_as(advisor_user, session_factory, monkeypatch)
    try:
        resp = client.get("/tenants")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# 2. Settings-Schutz
# ===========================================================================


def test_tenant_endpoint_blockt_wenn_admin_ui_disabled(
    session_factory, super_admin, monkeypatch,
):
    """Tier 1 + 3 haben tenant_admin_ui_enabled=False → 503."""
    monkeypatch.setattr(
        settings, "tenant_admin_ui_enabled", False, raising=False,
    )

    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: super_admin
    try:
        with TestClient(app) as client:
            resp = client.get("/tenants")
            assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# 3. CRUD-Flow
# ===========================================================================


def test_list_tenants_zeigt_erstellt_tenant(
    session_factory, super_admin, monkeypatch,
):
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        # Create
        client.post(
            "/tenants",
            json={"display_name": "A AG", "slug": "a-ag",
                  "hosting_tier": TIER_2_SHARED_CLOUD},
        )
        client.post(
            "/tenants",
            json={"display_name": "B AG", "slug": "b-ag",
                  "hosting_tier": TIER_2_SHARED_CLOUD},
        )
        # List
        resp = client.get("/tenants")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 2
        slugs = {t["slug"] for t in items}
        assert slugs == {"a-ag", "b-ag"}
    finally:
        app.dependency_overrides.clear()


def test_get_single_tenant(session_factory, super_admin, monkeypatch):
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        create_resp = client.post(
            "/tenants",
            json={"display_name": "Single AG", "slug": "single",
                  "hosting_tier": TIER_2_SHARED_CLOUD},
        )
        tenant_id = create_resp.json()["id"]
        get_resp = client.get(f"/tenants/{tenant_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["slug"] == "single"
    finally:
        app.dependency_overrides.clear()


def test_get_tenant_404_bei_unbekannter_id(
    session_factory, super_admin, monkeypatch,
):
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        resp = client.get("/tenants/does-not-exist")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_update_tenant_partial(session_factory, super_admin, monkeypatch):
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        create_resp = client.post(
            "/tenants",
            json={"display_name": "Original Name", "slug": "orig",
                  "hosting_tier": TIER_2_SHARED_CLOUD},
        )
        tenant_id = create_resp.json()["id"]
        update_resp = client.put(
            f"/tenants/{tenant_id}",
            json={"display_name": "Updated Name", "max_users": 25},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["display_name"] == "Updated Name"
        assert update_resp.json()["max_users"] == 25
        # Andere Felder unveraendert
        assert update_resp.json()["slug"] == "orig"
    finally:
        app.dependency_overrides.clear()


def test_default_retrocession_reimbursement_roundtrips(session_factory, super_admin, monkeypatch):
    """2026-07-27 (Retrozessions-Feature): das 'Kontrollpanel'-Setting fuer die
    firmenweite Vorbelegung von ConflictOfInterestDisclosure.reimbursed_to_client."""
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        create_resp = client.post(
            "/tenants",
            json={"display_name": "Retro-Firma", "slug": "retro-firma",
                  "hosting_tier": TIER_2_SHARED_CLOUD,
                  "default_retrocession_reimbursement": True},
        )
        assert create_resp.status_code == 201, create_resp.text
        assert create_resp.json()["default_retrocession_reimbursement"] == 1
        tenant_id = create_resp.json()["id"]

        update_resp = client.put(
            f"/tenants/{tenant_id}",
            json={"default_retrocession_reimbursement": False},
        )
        assert update_resp.status_code == 200, update_resp.text
        assert update_resp.json()["default_retrocession_reimbursement"] == 0
    finally:
        app.dependency_overrides.clear()


def test_finig_gate_defaults_to_false_for_new_tenants(session_factory, super_admin, monkeypatch):
    """2026-08-09 (FINIG-Gate): neue Firmen starten OHNE Freischaltung fuer
    diskretionaere Vermoegensverwaltung (Opt-in, kein Opt-out) -- Gegenstueck
    zu test_tenant_orm_default_is_licensed_for_backwards_compat in
    test_finig_discretionary_gate.py (dort: ORM-Default=1 fuer Bestandscode-
    pfade ohne explizite Angabe; hier: API-Schema-Default=False fuer echte
    Neu-Provisionierung ueber POST /tenants)."""
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        create_resp = client.post(
            "/tenants",
            json={"display_name": "Neue Firma AG", "slug": "neue-firma",
                  "hosting_tier": TIER_2_SHARED_CLOUD},
        )
        assert create_resp.status_code == 201, create_resp.text
        assert create_resp.json()["discretionary_management_licensed"] == 0
        tenant_id = create_resp.json()["id"]

        update_resp = client.put(
            f"/tenants/{tenant_id}",
            json={"discretionary_management_licensed": True},
        )
        assert update_resp.status_code == 200, update_resp.text
        assert update_resp.json()["discretionary_management_licensed"] == 1
    finally:
        app.dependency_overrides.clear()


def test_finig_gate_can_be_set_explicitly_at_creation(session_factory, super_admin, monkeypatch):
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        create_resp = client.post(
            "/tenants",
            json={"display_name": "Lizenzierte Firma AG", "slug": "lizenzierte-firma",
                  "hosting_tier": TIER_2_SHARED_CLOUD,
                  "discretionary_management_licensed": True},
        )
        assert create_resp.status_code == 201, create_resp.text
        assert create_resp.json()["discretionary_management_licensed"] == 1
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# 4. Slug-Konflikt
# ===========================================================================


def test_slug_duplicate_409(session_factory, super_admin, monkeypatch):
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        client.post(
            "/tenants",
            json={"display_name": "First", "slug": "duplicate",
                  "hosting_tier": TIER_2_SHARED_CLOUD},
        )
        resp = client.post(
            "/tenants",
            json={"display_name": "Second", "slug": "duplicate",
                  "hosting_tier": TIER_2_SHARED_CLOUD},
        )
        assert resp.status_code == 409
        assert "Slug" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_slug_race_condition_returns_409_not_500(session_factory, super_admin, monkeypatch):
    """2026-07-25 (Generalaudit, Wave 13): der Pre-Check ist TOCTOU-racy --
    analog zum bereits gefixten client_number-Fund (routers/clients.py).
    Simuliert den Race-Verlust direkt ueber Session.commit(), analog
    test_client_creation_race_condition.py."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session as OrmSession

    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        original_commit = OrmSession.commit
        call_count = {"n": 0}

        def _commit_raises_once(self, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise IntegrityError("UNIQUE constraint failed", {}, Exception("simuliert"))
            return original_commit(self, *args, **kwargs)

        monkeypatch.setattr(OrmSession, "commit", _commit_raises_once)

        resp = client.post(
            "/tenants",
            json={"display_name": "Race", "slug": "race-slug",
                  "hosting_tier": TIER_2_SHARED_CLOUD},
        )
        assert resp.status_code == 409, resp.text
        assert "Slug" in resp.json()["detail"]

        with session_factory() as s:
            assert s.query(Tenant).filter(Tenant.slug == "race-slug").count() == 0
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# 5. Pydantic-Validation
# ===========================================================================


def test_invalide_tier_422(session_factory, super_admin, monkeypatch):
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        resp = client.post(
            "/tenants",
            json={"display_name": "Test", "slug": "test-firm",
                  "hosting_tier": "tier99-fantasy"},
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_invalide_license_status_422(
    session_factory, super_admin, monkeypatch,
):
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        resp = client.post(
            "/tenants",
            json={
                "display_name": "Test", "slug": "test-firm",
                "hosting_tier": TIER_2_SHARED_CLOUD,
                "license_status": "not-a-real-status",
            },
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_invalide_slug_format_422(
    session_factory, super_admin, monkeypatch,
):
    """Slug muss Pattern matchen: lowercase, alnum, hyphens, kein leading/trailing hyphen."""
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        for bad_slug in ("UPPER-CASE", "-leading-hyphen", "trailing-", "with spaces"):
            resp = client.post(
                "/tenants",
                json={"display_name": "X", "slug": bad_slug,
                      "hosting_tier": TIER_2_SHARED_CLOUD},
            )
            assert resp.status_code == 422, f"Slug {bad_slug!r} sollte invalid sein"
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# 6. User-Tenant-Zuweisung
# ===========================================================================


def _persist_advisor(session_factory) -> str:
    """Helper: erstellt einen Advisor-User in der DB, returnt seine id-Stringkopie."""
    advisor_id = "advisor-fresh"
    with session_factory() as db:
        u = User(
            id=advisor_id, username="advisor-fresh", password_hash="h",
            full_name="Advisor", role="advisor", is_active=1,
            created_at=_utc_now(), updated_at=_utc_now(),
        )
        db.add(u)
        db.commit()
    return advisor_id


def test_assign_user_to_tenant(session_factory, super_admin, monkeypatch):
    """Super-Admin weist einen Advisor einem Tenant zu."""
    advisor_id = _persist_advisor(session_factory)
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        tenant_resp = client.post(
            "/tenants",
            json={"display_name": "Assign-Test", "slug": "assign-test",
                  "hosting_tier": TIER_2_SHARED_CLOUD},
        )
        tenant_id = tenant_resp.json()["id"]
        assign_resp = client.put(
            f"/tenants/{tenant_id}/users/{advisor_id}/assign",
        )
        assert assign_resp.status_code == 200, assign_resp.text
        data = assign_resp.json()
        assert data["ok"] is True
        assert data["user_id"] == advisor_id
        assert data["tenant_id"] == tenant_id

        with session_factory() as db:
            u = db.query(User).filter(User.id == advisor_id).first()
            assert u.tenant_id == tenant_id
    finally:
        app.dependency_overrides.clear()


# ── 2026-07-26 (Generalaudit-Nachtrag): Guard gegen stille Verwaisung ──────
# Client.tenant_id bleibt beim ALTEN Tenant stehen (kein Cross-Tenant-Leak),
# wuerde fuer den User nach der Neuzuweisung aber unsichtbar werden.

def test_assign_user_to_tenant_blocked_when_active_clients_exist(
    session_factory, super_admin, monkeypatch,
):
    from models.clients import Client

    advisor_id = _persist_advisor(session_factory)
    with session_factory() as db:
        db.add(Client(
            id="client-owned-by-advisor", client_number="C-OWNED",
            first_name="T", last_name="X", advisor_id=advisor_id,
            created_at=_utc_now(), updated_at=_utc_now(),
        ))
        db.query(User).filter(User.id == advisor_id).update({"tenant_id": "firma-alt"})
        db.commit()

    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        tenant_resp = client.post(
            "/tenants",
            json={"display_name": "Neu", "slug": "assign-blocked",
                  "hosting_tier": TIER_2_SHARED_CLOUD},
        )
        tenant_id = tenant_resp.json()["id"]
        assign_resp = client.put(f"/tenants/{tenant_id}/users/{advisor_id}/assign")
        assert assign_resp.status_code == 409, assign_resp.text
        assert "aktive Kunden" in assign_resp.json()["detail"]

        with session_factory() as db:
            u = db.query(User).filter(User.id == advisor_id).first()
            assert u.tenant_id == "firma-alt"  # unveraendert
    finally:
        app.dependency_overrides.clear()


def test_assign_user_to_tenant_allowed_when_no_active_clients(
    session_factory, super_admin, monkeypatch,
):
    advisor_id = _persist_advisor(session_factory)
    with session_factory() as db:
        db.query(User).filter(User.id == advisor_id).update({"tenant_id": "firma-alt"})
        db.commit()

    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        tenant_resp = client.post(
            "/tenants",
            json={"display_name": "Neu", "slug": "assign-allowed",
                  "hosting_tier": TIER_2_SHARED_CLOUD},
        )
        tenant_id = tenant_resp.json()["id"]
        assign_resp = client.put(f"/tenants/{tenant_id}/users/{advisor_id}/assign")
        assert assign_resp.status_code == 200, assign_resp.text
    finally:
        app.dependency_overrides.clear()


def test_assign_user_404_unbekannter_tenant(
    session_factory, super_admin, monkeypatch,
):
    advisor_id = _persist_advisor(session_factory)
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        resp = client.put(f"/tenants/unknown/users/{advisor_id}/assign")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_assign_user_404_unbekannter_user(
    session_factory, super_admin, monkeypatch,
):
    client = _make_client_as(super_admin, session_factory, monkeypatch)
    try:
        tenant_resp = client.post(
            "/tenants",
            json={"display_name": "Test Firm", "slug": "test-firm",
                  "hosting_tier": TIER_2_SHARED_CLOUD},
        )
        tenant_id = tenant_resp.json()["id"]
        resp = client.put(
            f"/tenants/{tenant_id}/users/unknown-user/assign",
        )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
