from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, bootstrap_sqlite_schema, build_connect_args, ensure_audit_log_actions, get_db
from main import app
from models.review import AuditLog  # noqa: F401
from models.users import User
from services.auth import hash_password
from services.login_guard import login_attempt_guard


@pytest.fixture()
def session_factory(tmp_path):
    db_path = tmp_path / "test_user_management.db"
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
def client(session_factory):
    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def seed_user(session_factory, *, password: str = "Password123!", **overrides) -> str:
    payload = {
        "id": "user-1",
        "username": "user1",
        "password_hash": hash_password(password),
        "full_name": "User One",
        "email": "user1@example.com",
        "role": "advisor",
        "is_active": 1,
        "created_at": "2026-04-01T00:00:00.000Z",
        "updated_at": "2026-04-01T00:00:00.000Z",
        "deleted_at": None,
    }
    payload.update(overrides)
    with session_factory() as session:
        session.add(User(**payload))
        session.commit()
    return payload["id"]


def login_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def reset_login_guard_state() -> None:
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()


def test_admin_can_reset_password(session_factory, client):
    admin_id = seed_user(
        session_factory,
        id="admin-1",
        username="admin",
        full_name="Admin User",
        role="admin",
        password="AdminPass123!",
    )
    user_id = seed_user(
        session_factory,
        id="user-reset-1",
        username="reset-user",
        full_name="Reset User",
        role="advisor",
        password="OldPass123!",
    )
    headers = login_headers(client, "admin", "AdminPass123!")

    response = client.put(
        f"/users/{user_id}/password",
        json={"new_password": "NewSecure123!"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == user_id
    assert payload["username"] == "reset-user"

    login_response = client.post(
        "/auth/login",
        json={"username": "reset-user", "password": "NewSecure123!"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["user"]["id"] == user_id
    assert login_response.json()["user"]["username"] == "reset-user"


def test_password_reset_requires_min_length(session_factory, client):
    seed_user(
        session_factory,
        id="admin-2",
        username="admin2",
        full_name="Admin User Two",
        role="admin",
        password="AdminPass123!",
    )
    user_id = seed_user(
        session_factory,
        id="user-reset-2",
        username="short-reset",
        full_name="Short Reset",
        password="OldPass123!",
    )
    headers = login_headers(client, "admin2", "AdminPass123!")

    response = client.put(
        f"/users/{user_id}/password",
        json={"new_password": "123456789"},
        headers=headers,
    )

    assert response.status_code == 422


def test_password_reset_returns_404_for_unknown_user(session_factory, client):
    seed_user(
        session_factory,
        id="admin-3",
        username="admin3",
        full_name="Admin User Three",
        role="admin",
        password="AdminPass123!",
    )
    headers = login_headers(client, "admin3", "AdminPass123!")

    response = client.put(
        "/users/unknown/password",
        json={"new_password": "NewSecure123!"},
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Benutzer nicht gefunden"


def test_cannot_deactivate_own_account(session_factory, client):
    admin_id = seed_user(
        session_factory,
        id="admin-self-1",
        username="self-admin",
        full_name="Self Admin",
        role="admin",
        password="AdminPass123!",
    )
    headers = login_headers(client, "self-admin", "AdminPass123!")

    response = client.put(
        f"/users/{admin_id}",
        json={"is_active": False},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Eigenes Konto kann nicht deaktiviert werden"


def test_cannot_change_own_role(session_factory, client):
    admin_id = seed_user(
        session_factory,
        id="admin-self-2",
        username="self-role-admin",
        full_name="Self Role Admin",
        role="admin",
        password="AdminPass123!",
    )
    headers = login_headers(client, "self-role-admin", "AdminPass123!")

    response = client.put(
        f"/users/{admin_id}",
        json={"role": "readonly"},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Eigene Rolle kann nicht geändert werden"


def test_can_deactivate_other_user(session_factory, client):
    seed_user(
        session_factory,
        id="admin-4",
        username="admin4",
        full_name="Admin User Four",
        role="admin",
        password="AdminPass123!",
    )
    user_id = seed_user(
        session_factory,
        id="user-disable-1",
        username="deactivate-me",
        full_name="Deactivate Me",
        role="advisor",
        password="UserPass123!",
    )
    headers = login_headers(client, "admin4", "AdminPass123!")

    response = client.put(
        f"/users/{user_id}",
        json={"is_active": False},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["id"] == user_id
    assert response.json()["is_active"] == 0


def test_deactivated_user_cannot_login(session_factory, client):
    seed_user(
        session_factory,
        id="admin-5",
        username="admin5",
        full_name="Admin User Five",
        role="admin",
        password="AdminPass123!",
    )
    user_id = seed_user(
        session_factory,
        id="user-disable-2",
        username="disabled-user",
        full_name="Disabled User",
        role="advisor",
        password="UserPass123!",
    )
    headers = login_headers(client, "admin5", "AdminPass123!")

    deactivate_response = client.put(
        f"/users/{user_id}",
        json={"is_active": False},
        headers=headers,
    )
    assert deactivate_response.status_code == 200

    login_response = client.post(
        "/auth/login",
        json={"username": "disabled-user", "password": "UserPass123!"},
    )

    assert login_response.status_code == 401
    assert login_response.json()["detail"] == "Konto deaktiviert"


def test_login_rate_limit_blocks_after_repeated_failures_from_same_ip(monkeypatch, client):
    from config import settings

    reset_login_guard_state()
    monkeypatch.setattr(settings, "login_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "login_max_attempts", 5)
    monkeypatch.setattr(settings, "login_window_seconds", 60)
    monkeypatch.setattr(settings, "login_lockout_seconds", 60)

    try:
        for idx in range(5):
            response = client.post(
                "/auth/login",
                json={"username": f"ghost-{idx}", "password": "wrong"},
            )
            assert response.status_code == 401

        blocked = client.post(
            "/auth/login",
            json={"username": "ghost-locked", "password": "wrong"},
        )

        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers
    finally:
        reset_login_guard_state()


def test_runtime_migration_allows_password_reset_action_on_bootstrap_schema(tmp_path):
    db_path = tmp_path / "bootstrap_user_management.db"
    bootstrap_sqlite_schema(db_path=db_path)
    temp_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    try:
        ensure_audit_log_actions(temp_engine)
        with temp_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO audit_log (
                        id, user_id, user_name, table_name, record_id, action, created_at
                    ) VALUES (
                        'audit-1', 'admin-1', 'Admin User', 'users', 'user-1', 'PASSWORD_RESET', '2026-04-01T00:00:00.000Z'
                    )
                    """
                )
            )
            action = conn.execute(text("SELECT action FROM audit_log WHERE id='audit-1'")).scalar()
            integrity_hash_column = conn.execute(
                text("SELECT COUNT(*) FROM pragma_table_info('audit_log') WHERE name='integrity_hash'")
            ).scalar()
        assert action == "PASSWORD_RESET"
        assert integrity_hash_column == 1
    finally:
        temp_engine.dispose()


def test_build_connect_args_include_sqlite_timeout():
    assert build_connect_args()["timeout"] == 30
