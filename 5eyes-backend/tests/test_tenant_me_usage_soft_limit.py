"""Roadmap #24-Rest (2026-08-09): Soft-Limit-Warn-UI fuer Quotas.

services/quota.py::assert_within_quota blockt hart bei 100% (409), zeigte dem
Firmen-Admin vorher aber KEIN Feedback, wenn die Auslastung sich der Grenze
naehert. GET /tenants/me liefert jetzt zusaetzlich current_users/
current_mandates, damit das Frontend (teamRender() in 5eyes_v2.html) eine
Warnschwelle VOR dem harten Block anzeigen kann.
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
from models.clients import Client
from models.mandates import Mandate
from models.tenant import Tenant
from models.users import User
from services.auth import get_current_user
from services.quota import compute_tenant_usage


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tenant_me_usage.db'}",
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


def test_compute_tenant_usage_counts_users_and_mandates(session_factory):
    now = _now()
    with session_factory() as db:
        db.add(Tenant(
            id="firm-usage", display_name="Firm", slug="firm-usage",
            hosting_tier="tier2", license_status="active", max_users=5,
            is_active=1, created_at=now, updated_at=now,
        ))
        db.add(User(id="u1", username="u1", password_hash="h", full_name="U1",
                     role="advisor", is_active=1, tenant_id="firm-usage",
                     created_at=now, updated_at=now))
        db.add(User(id="u2", username="u2", password_hash="h", full_name="U2",
                     role="advisor", is_active=1, tenant_id="firm-usage",
                     created_at=now, updated_at=now))
        db.add(Client(id="c1", client_number="C1", first_name="A", last_name="B",
                       advisor_id="u1", tenant_id="firm-usage", household_type="Einzelperson",
                       client_classification="Privatkunde", country_of_residence="CH",
                       language="DE", created_at=now, updated_at=now))
        db.add(Mandate(id="m1", client_id="c1", mandate_number="M1", tenant_id="firm-usage",
                        mandate_type="Anlageberatung", opened_at="2026-08-09",
                        created_at=now, updated_at=now))
        db.commit()

        usage = compute_tenant_usage(db, "firm-usage")
    assert usage == {"current_users": 2, "current_mandates": 1}


def test_compute_tenant_usage_empty_tenant_id_returns_zero(session_factory):
    with session_factory() as db:
        assert compute_tenant_usage(db, None) == {"current_users": 0, "current_mandates": 0}
        assert compute_tenant_usage(db, "") == {"current_users": 0, "current_mandates": 0}


def test_get_my_tenant_includes_current_usage(client, session_factory):
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id="firm-me", display_name="Firm Me", slug="firm-me",
            hosting_tier="tier2", license_status="active", max_users=3,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(User(id="admin-1", username="admin-1", password_hash="h", full_name="Admin",
                     role="admin", is_active=1, tenant_id="firm-me",
                     created_at=now, updated_at=now))
        s.add(User(id="advisor-1", username="advisor-1", password_hash="h", full_name="Advisor",
                     role="advisor", is_active=1, tenant_id="firm-me",
                     created_at=now, updated_at=now))
        s.commit()
    _login_as("admin-1", "admin", tenant_id="firm-me")
    try:
        resp = client.get("/tenants/me")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["current_users"] == 2
        assert body["current_mandates"] == 0
        assert body["max_users"] == 3
    finally:
        _logout()


def test_get_my_tenant_usage_zero_for_brand_new_tenant(client, session_factory):
    now = _now()
    with session_factory() as s:
        s.add(Tenant(
            id="firm-empty", display_name="Firm Empty", slug="firm-empty",
            hosting_tier="tier2", license_status="active",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(User(id="admin-2", username="admin-2", password_hash="h", full_name="Admin2",
                     role="admin", is_active=1, tenant_id="firm-empty",
                     created_at=now, updated_at=now))
        s.commit()
    _login_as("admin-2", "admin", tenant_id="firm-empty")
    try:
        resp = client.get("/tenants/me")
        assert resp.status_code == 200, resp.text
        assert resp.json()["current_users"] == 1
    finally:
        _logout()
