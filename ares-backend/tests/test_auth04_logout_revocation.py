"""AUTH-04 (2026-07-22): /auth/logout war ein No-op — ein gestohlenes Token
blieb bis zum Ablauf gueltig. Fix: token_revoked_before-Timestamp am User;
get_current_user verweigert jedes Token mit payload['iat'] < token_revoked_before
(401), unabhaengig von dessen exp."""
from __future__ import annotations

import sys
import time
import datetime
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
from models.users import User
from services.auth import hash_password


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_auth04.db'}",
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


def _seed_user(SF, uid, password):
    with SF() as s:
        s.add(User(
            id=uid, username=uid, password_hash=hash_password(password),
            full_name=uid, role="advisor", is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def test_logout_revokes_previously_valid_token(client, session_factory):
    _seed_user(session_factory, "auth04-u1", "pw")
    login = client.post("/auth/login", json={"username": "auth04-u1", "password": "pw"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Token ist gueltig, bevor abgemeldet wird.
    assert client.get("/auth/me", headers=headers).status_code == 200

    logout = client.post("/auth/logout", headers=headers)
    assert logout.status_code == 200

    # Dasselbe (alte) Token muss jetzt ueberall abgelehnt werden.
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_login_after_logout_issues_fresh_valid_token(client, session_factory):
    """Ein NEUES Token (nach erneutem Login) darf NICHT durch die Revocation
    des alten Tokens betroffen sein. JWT-'iat' hat Sekunden-Aufloesung — 1.1s
    Abstand stellt sicher, dass der Relogin sicher in einer NEUEN Sekunde nach
    dem Logout-Timestamp liegt (keine Grenzfall-Flakiness im Test)."""
    _seed_user(session_factory, "auth04-u2", "pw")
    login1 = client.post("/auth/login", json={"username": "auth04-u2", "password": "pw"})
    token1 = login1.json()["access_token"]
    client.post("/auth/logout", headers={"Authorization": f"Bearer {token1}"})
    time.sleep(1.1)

    login2 = client.post("/auth/login", json={"username": "auth04-u2", "password": "pw"})
    assert login2.status_code == 200
    token2 = login2.json()["access_token"]
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token2}"})
    assert r.status_code == 200


def test_logout_requires_valid_token(client):
    """/auth/logout ist wie jeder andere geschuetzte Endpoint auth-pflichtig."""
    r = client.post("/auth/logout")
    assert r.status_code in (401, 403)
