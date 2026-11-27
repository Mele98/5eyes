"""OWN-LIC-01 / ROL-07 (CTO-Entscheid H-180, technischer Standard).

* Die externe Pruefperson (``compliance_reviewer``) zaehlt nicht gegen
  ``max_users`` und wird durch die Grenze nicht gesperrt.
* Der Bootstrap-Admin bekommt sofort seinen Mandanten (Einzelmandanten-Betrieb:
  Default-Mandant) -- er zaehlt ab dem ersten Request gegen ``max_users``, und
  die von ihm angelegten Konten werden sofort quota-geprueft (vorher erst nach
  einem Neustart, ueber den Start-Backfill).

Echte HTTP-Aufrufe gegen eine Wegwerf-SQLite. Alle Werte sind Testwerte.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, get_db
from main import app
from models.tenant import DEFAULT_TENANT_ID, Tenant
from models.users import User
from services.login_guard import login_attempt_guard
from services.quota import assert_within_quota, compute_tenant_usage

NOW = "2026-11-21T09:00:00.000Z"
PW = "Testpasswort-OwnLic-01"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'own_lic.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with factory() as db:
        db.add(Tenant(id=DEFAULT_TENANT_ID, display_name="Testfirma Fiktiv", slug=DEFAULT_TENANT_ID,
                      max_users=1, created_at=NOW, updated_at=NOW))
        db.commit()
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture()
def client(session_factory):
    def override_db():
        with session_factory() as s:
            yield s

    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        login_attempt_guard._failures.clear()
        login_attempt_guard._locked_until.clear()


def _bootstrap(client) -> dict:
    resp = client.post("/auth/bootstrap-admin", json={
        "username": "owner-admin", "password": PW, "full_name": "Testinhaber Fiktiv",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_bootstrap_admin_has_tenant_immediately_and_counts_against_max_users(client, session_factory):
    admin = _bootstrap(client)
    with session_factory() as db:
        row = db.query(User).filter(User.id == admin["user"]["id"]).one()
        assert row.tenant_id == DEFAULT_TENANT_ID
        assert compute_tenant_usage(db, DEFAULT_TENANT_ID)["current_users"] == 1
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    # max_users=1 ist mit dem Admin ausgeschoepft -- sofort, ohne Neustart.
    resp = client.post("/users", headers=headers, json={
        "username": "berater-1", "password": PW, "full_name": "Testberater Fiktiv", "role": "advisor",
    })
    assert resp.status_code == 409, resp.text
    assert "max_users" in resp.text


def test_compliance_reviewer_does_not_count_and_is_not_blocked(client, session_factory):
    admin = _bootstrap(client)
    headers = {"Authorization": f"Bearer {admin['access_token']}"}
    resp = client.post("/users/invite", headers=headers, json={
        "username": "pruefperson-1", "full_name": "Testpruefperson Fiktiv", "role": "compliance_reviewer",
        "email": "pruefperson@testfirma.ch", "reviewer_organisation": "TEST Org",
        "reviewer_reference": "TEST Mandat",
    })
    assert resp.status_code in (200, 201), resp.text
    with session_factory() as db:
        assert db.query(User).filter(User.role == "compliance_reviewer").count() == 1
        # Belegung zaehlt nur die lizenzierten Konten.
        assert compute_tenant_usage(db, DEFAULT_TENANT_ID)["current_users"] == 1
        # Direkt: eine Pruefperson ist nie durch max_users gesperrt, ein Berater schon.
        assert_within_quota(db, DEFAULT_TENANT_ID, "users", role="compliance_reviewer")
        with pytest.raises(Exception) as exc:
            assert_within_quota(db, DEFAULT_TENANT_ID, "users", role="advisor")
        assert getattr(exc.value, "status_code", None) == 409


def test_strict_multi_tenant_bootstrap_admin_is_not_guessed(client, session_factory, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "strict_tenant_isolation", True, raising=False)
    admin = _bootstrap(client)
    with session_factory() as db:
        assert db.query(User).filter(User.id == admin["user"]["id"]).one().tenant_id is None
