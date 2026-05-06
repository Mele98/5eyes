from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.review import AuditLog
from models.users import User
from services.auth import require_admin
from services.audit import _audit_integrity_payload, log


@pytest.fixture()
def session_factory(tmp_path):
    db_path = tmp_path / "test_audit_log_viewer.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield testing_session_local
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def admin_user():
    return User(
        id="admin-audit-1",
        username="admin",
        password_hash="hash",
        full_name="Admin User",
        role="admin",
        is_active=1,
        created_at="2026-04-01T00:00:00.000Z",
        updated_at="2026-04-01T00:00:00.000Z",
    )


@pytest.fixture()
def admin_client(session_factory, admin_user):
    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def forbidden_client(session_factory):
    def override_get_db():
        with session_factory() as session:
            yield session

    def deny_admin():
        raise HTTPException(status_code=403, detail="Nur für Administratoren")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = deny_admin
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def seed_audit_entry(session_factory, **overrides) -> str:
    payload = {
        "id": "audit-entry-1",
        "user_id": "admin-audit-1",
        "user_name": "Admin User",
        "table_name": "users",
        "record_id": "record-1",
        "action": "CREATE",
        "field_name": None,
        "old_value": None,
        "new_value": None,
        "mandate_id": None,
        "client_id": None,
        "created_at": "2026-04-01T10:00:00.000Z",
    }
    payload.update(overrides)
    with session_factory() as session:
        session.add(AuditLog(**payload))
        session.commit()
    return payload["id"]


def test_audit_log_returns_entries_sorted_desc(session_factory, admin_client):
    seed_audit_entry(session_factory, id="audit-old", created_at="2026-04-01T08:00:00.000Z")
    seed_audit_entry(session_factory, id="audit-newest", created_at="2026-04-01T12:00:00.000Z")
    seed_audit_entry(session_factory, id="audit-mid", created_at="2026-04-01T10:00:00.000Z")

    response = admin_client.get("/admin/system/audit-log")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert [entry["id"] for entry in payload["entries"]] == ["audit-newest", "audit-mid", "audit-old"]


def test_audit_log_filter_by_action(session_factory, admin_client):
    seed_audit_entry(session_factory, id="audit-login-1", action="LOGIN", created_at="2026-04-01T09:00:00.000Z")
    seed_audit_entry(session_factory, id="audit-login-2", action="LOGIN", created_at="2026-04-01T11:00:00.000Z")
    seed_audit_entry(session_factory, id="audit-create-1", action="CREATE", created_at="2026-04-01T12:00:00.000Z")

    response = admin_client.get("/admin/system/audit-log?action=LOGIN")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert all(entry["action"] == "LOGIN" for entry in payload["entries"])


def test_audit_log_filter_by_q(session_factory, admin_client):
    seed_audit_entry(session_factory, id="audit-admin", user_name="Admin", table_name="users")
    seed_audit_entry(session_factory, id="audit-berater", user_name="Berater", table_name="clients")

    response = admin_client.get("/admin/system/audit-log?q=admin")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["entries"][0]["id"] == "audit-admin"


def test_audit_log_limit_capped_at_200(session_factory, admin_client):
    seed_audit_entry(session_factory)

    response = admin_client.get("/admin/system/audit-log?limit=999")

    assert response.status_code == 422


def test_audit_log_requires_admin(session_factory, forbidden_client):
    seed_audit_entry(session_factory)

    response = forbidden_client.get("/admin/system/audit-log")

    assert response.status_code == 403
    assert response.json()["detail"] == "Nur für Administratoren"


def test_audit_log_entries_receive_integrity_hash_chain(session_factory):
    with session_factory() as session:
        log(
            session,
            user_id="admin-audit-1",
            user_name="Admin User",
            table_name="users",
            record_id="record-1",
            action="CREATE",
        )
        log(
            session,
            user_id="admin-audit-1",
            user_name="Admin User",
            table_name="users",
            record_id="record-2",
            action="UPDATE",
        )
        session.commit()
        entries = session.query(AuditLog).order_by(AuditLog.created_at.asc(), AuditLog.id.asc()).all()

    assert len(entries) == 2
    assert entries[0].integrity_hash
    assert entries[1].integrity_hash
    assert entries[0].integrity_hash != entries[1].integrity_hash


def test_audit_log_integrity_hash_covers_content_fields(session_factory):
    with session_factory() as session:
        log(
            session,
            user_id="admin-audit-1",
            user_name="Admin User",
            table_name="clients",
            record_id="client-1",
            action="UPDATE",
            field_name="name",
            old_value="Alt",
            new_value="Neu",
            mandate_id="mandate-1",
            client_id="client-1",
        )
        session.commit()
        entry = session.query(AuditLog).one()

    expected_payload = _audit_integrity_payload(
        entry_id=entry.id,
        user_id=entry.user_id,
        user_name=entry.user_name,
        table_name=entry.table_name,
        record_id=entry.record_id,
        action=entry.action,
        field_name=entry.field_name,
        old_value=entry.old_value,
        new_value=entry.new_value,
        mandate_id=entry.mandate_id,
        client_id=entry.client_id,
        created_at=entry.created_at,
        previous_hash="",
    )
    tampered_payload = _audit_integrity_payload(
        entry_id=entry.id,
        user_id=entry.user_id,
        user_name=entry.user_name,
        table_name=entry.table_name,
        record_id=entry.record_id,
        action=entry.action,
        field_name=entry.field_name,
        old_value=entry.old_value,
        new_value="Manipuliert",
        mandate_id=entry.mandate_id,
        client_id=entry.client_id,
        created_at=entry.created_at,
        previous_hash="",
    )

    assert entry.integrity_hash == hashlib.sha256(expected_payload.encode("utf-8")).hexdigest()
    assert entry.integrity_hash != hashlib.sha256(tampered_payload.encode("utf-8")).hexdigest()
