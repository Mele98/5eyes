"""AUTH-02 (2026-07-19): must_change_password wird serverseitig erzwungen.

Ein User mit gesetztem Flag darf NUR /auth/change-password, /auth/me, /auth/logout
aufrufen (403 sonst), bis er das Passwort geaendert hat. Der neue authentifizierte
Change-Password-Endpoint verhindert das Aussperren.
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
from services.auth import hash_password, issue_token_for_user


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_auth02.db'}",
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


def _seed(SF, uid="u-mcp", password="OldPassw0rd", must_change=1):
    with SF() as s:
        s.add(User(
            id=uid, username=uid, password_hash=hash_password(password),
            full_name=uid, role="advisor", is_active=1,
            must_change_password=must_change,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()
    return uid


def _token(SF, uid):
    with SF() as s:
        return issue_token_for_user(s.query(User).filter(User.id == uid).first())


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_protected_endpoint_blocked_when_must_change(session_factory, client):
    uid = _seed(session_factory, must_change=1)
    tok = _token(session_factory, uid)
    r = client.get("/auth/2fa/status", headers=_auth(tok))
    assert r.status_code == 403
    assert "must_change_password" in r.json().get("detail", "")


def test_me_and_change_password_reachable_when_must_change(session_factory, client):
    uid = _seed(session_factory, must_change=1)
    tok = _token(session_factory, uid)
    assert client.get("/auth/me", headers=_auth(tok)).status_code == 200
    # change-password erreichbar (nicht 403 durchs Gate):
    r = client.post("/auth/change-password", headers=_auth(tok),
                    json={"current_password": "OldPassw0rd", "new_password": "NewPassw0rd1"})
    assert r.status_code == 200


def test_after_change_flag_cleared_and_access_restored(session_factory, client):
    uid = _seed(session_factory, must_change=1)
    tok = _token(session_factory, uid)
    client.post("/auth/change-password", headers=_auth(tok),
                json={"current_password": "OldPassw0rd", "new_password": "NewPassw0rd1"})
    with session_factory() as s:
        assert s.query(User).filter(User.id == uid).first().must_change_password == 0
    # jetzt ist der geschuetzte Endpoint wieder erreichbar:
    assert client.get("/auth/2fa/status", headers=_auth(tok)).status_code == 200


def test_no_flag_user_not_blocked(session_factory, client):
    uid = _seed(session_factory, must_change=0)
    tok = _token(session_factory, uid)
    assert client.get("/auth/2fa/status", headers=_auth(tok)).status_code == 200


def test_change_password_wrong_current_rejected(session_factory, client):
    uid = _seed(session_factory, must_change=1)
    tok = _token(session_factory, uid)
    r = client.post("/auth/change-password", headers=_auth(tok),
                    json={"current_password": "WRONG", "new_password": "NewPassw0rd1"})
    assert r.status_code == 400


def test_change_password_too_short_rejected(session_factory, client):
    uid = _seed(session_factory, must_change=1)
    tok = _token(session_factory, uid)
    r = client.post("/auth/change-password", headers=_auth(tok),
                    json={"current_password": "OldPassw0rd", "new_password": "short"})
    assert r.status_code == 422


def test_self_service_password_endpoint_reachable_when_must_change(session_factory, client):
    """A2-Smoke-Test-Fund (2026-07-22): das BESTEHENDE Frontend-Modal fuer den
    erzwungenen Erst-Passwortwechsel ruft PUT /users/{eigene_id}/password
    (nicht /auth/change-password) — dieser Pfad muss trotz must_change_password
    erreichbar sein, sonst waere jeder frisch angelegte User ausgesperrt."""
    uid = _seed(session_factory, must_change=1)
    tok = _token(session_factory, uid)
    r = client.put(f"/users/{uid}/password", headers=_auth(tok),
                   json={"new_password": "NewPassw0rd1"})
    assert r.status_code == 200
    with session_factory() as s:
        assert s.query(User).filter(User.id == uid).first().must_change_password == 0


def test_self_service_password_endpoint_blocked_for_other_users_while_locked(session_factory, client):
    """Die Ausnahme gilt NUR fuer die EIGENE user_id — ein gesperrter Admin darf
    waehrend must_change_password weiterhin NICHT das Passwort eines ANDEREN
    Users zuruecksetzen (kein genereller /password-Freifahrtschein)."""
    admin_uid = _seed(session_factory, uid="u-admin-mcp", must_change=1)
    with session_factory() as s:
        s.add(User(
            id="u-other", username="u-other", password_hash=hash_password("Whatever1"),
            full_name="Other", role="advisor", is_active=1,
            must_change_password=0, created_at=_now(), updated_at=_now(),
        ))
        s.commit()
    tok = _token(session_factory, admin_uid)
    r = client.put("/users/u-other/password", headers=_auth(tok),
                   json={"new_password": "NewPassw0rd1"})
    assert r.status_code == 403
