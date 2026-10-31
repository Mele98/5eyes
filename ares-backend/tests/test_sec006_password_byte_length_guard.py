"""SEC-006 (Codex-Audit 2026-08-25, docs/audits/2026-08-25-auth-execution-
operations-followup-audit.md): services.auth.hash_password() ruft bcrypt
direkt auf. bcrypt akzeptiert Passwoerter nur bis 72 Bytes (UTF-8) und wirft
sonst ein rohes ValueError -- unbehandelt fuehrt das auf jedem betroffenen
Endpoint (Registrierung, Passwortwechsel, Reset, Einladung, Client-Login) zu
einem unbehandelten 500 statt einer klaren 4xx-Antwort.

Fix: jeder Endpoint, der Nutzer-Eingabe an hash_password() weiterreicht,
lehnt Passwoerter > 72 Bytes jetzt explizit mit einer 4xx-Antwort ab, bevor
bcrypt ueberhaupt aufgerufen wird.
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
from models.users import User
from services.auth import hash_password

# 73 Bytes (ASCII) -- ein Byte ueber dem bcrypt-Limit.
_TOO_LONG_PASSWORD = "x" * 73


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sec006.db'}",
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


def _seed_user(SF, uid, password, role="advisor"):
    with SF() as s:
        s.add(User(
            id=uid, username=uid, password_hash=hash_password(password),
            full_name=uid, role=role, is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def test_bootstrap_admin_rejects_overlong_password(client):
    resp = client.post("/auth/bootstrap-admin", json={
        "username": "boot-admin", "password": _TOO_LONG_PASSWORD, "full_name": "Boot",
    })
    assert resp.status_code == 422, resp.text


def test_change_password_rejects_overlong_new_password(client, session_factory):
    _seed_user(session_factory, "sec006-u1", "old-pw-12345")
    login = client.post("/auth/login", json={"username": "sec006-u1", "password": "old-pw-12345"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.post(
        "/auth/change-password",
        json={"current_password": "old-pw-12345", "new_password": _TOO_LONG_PASSWORD},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


def test_password_reset_confirm_rejects_overlong_password(client, session_factory):
    from services.account_recovery import issue_reset_token

    _seed_user(session_factory, "sec006-u2", "old-pw-12345")
    with session_factory() as s:
        u = s.query(User).filter_by(id="sec006-u2").first()
        reset_token = issue_reset_token(u)
        s.commit()

    resp = client.post(
        "/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": _TOO_LONG_PASSWORD},
    )
    assert resp.status_code == 400, resp.text


def test_reset_user_password_rejects_overlong_password(client, session_factory):
    _seed_user(session_factory, "sec006-u3", "old-pw-12345")
    login = client.post("/auth/login", json={"username": "sec006-u3", "password": "old-pw-12345"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.put(
        "/users/sec006-u3/password",
        json={"new_password": _TOO_LONG_PASSWORD},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


def test_client_login_creation_rejects_overlong_password(client, session_factory):
    from models.clients import Client

    now = _now()
    with session_factory() as s:
        s.add(User(id="sec006-advisor", username="sec006-advisor", password_hash=hash_password("advisor-pw-12345"),
                    full_name="Advisor", role="advisor", is_active=1, created_at=now, updated_at=now))
        s.add(Client(id="sec006-client", client_number="C-SEC006", first_name="T", last_name="X",
                      advisor_id="sec006-advisor", created_at=now, updated_at=now))
        s.commit()

    login = client.post("/auth/login", json={"username": "sec006-advisor", "password": "advisor-pw-12345"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.post(
        "/clients/sec006-client/client-login",
        json={"username": "sec006-client-login", "password": _TOO_LONG_PASSWORD},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


def test_hash_password_still_works_at_exactly_72_bytes():
    """Regressionsschutz: die Grenze selbst (genau 72 Bytes) darf weiterhin
    funktionieren -- nur > 72 Bytes wird abgelehnt."""
    boundary_password = "x" * 72
    hashed = hash_password(boundary_password)
    assert hashed
