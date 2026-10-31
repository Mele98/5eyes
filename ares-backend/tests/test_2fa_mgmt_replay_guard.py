"""Kontrollrunde 2026-09-21: /auth/2fa/enable + /auth/2fa/disable riefen
_totp_replay_check_and_record() (AUTH-06) NICHT auf, anders als /auth/login.
Ein mitgelesener/geleakter TOTP-Code blieb innerhalb des +/-1-Drift-Fensters
gegen diese beiden Endpunkte beliebig oft wiederverwendbar -- konkret konnte
derselbe Code, der /2fa/enable erfolgreich ausgeloest hat, unmittelbar danach
auch gegen /2fa/disable vorgelegt werden (und /2fa/enable erneut, was
Recovery-Codes ein zweites Mal ausgibt), ohne dass der Angreifer das Secret
kennen muss.
"""
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
from services.login_guard import login_attempt_guard
from services import totp


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_2fa_mgmt_replay.db'}",
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


@pytest.fixture(autouse=True)
def _reset_login_guard():
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()
    yield
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()


def _seed_user(SF, uid, password):
    with SF() as s:
        s.add(User(
            id=uid, username=uid, password_hash=hash_password(password),
            full_name=uid, role="advisor", is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def _login_headers(client, uid, password):
    r = client.post("/auth/login", json={"username": uid, "password": password})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_enable_rejects_replayed_code_on_second_call(client, session_factory):
    _seed_user(session_factory, "mgmt-replay-1", "pw")
    headers = _login_headers(client, "mgmt-replay-1", "pw")

    setup = client.post("/auth/2fa/setup", headers=headers).json()
    code = totp.totp_at(setup["secret"], time.time())

    first = client.post("/auth/2fa/enable", json={"code": code}, headers=headers)
    assert first.status_code == 200
    first_codes = first.json()["recovery_codes"]

    # BUG (vor Fix): kein "already enabled"-Guard oben in twofa_enable, und
    # keine Replay-Pruefung -- derselbe Code loeste ein ZWEITES Mal frische
    # Recovery-Codes aus.
    replay = client.post("/auth/2fa/enable", json={"code": code}, headers=headers)
    assert replay.status_code == 401
    assert "verwendet" in replay.json()["detail"]


def test_disable_rejects_code_already_used_for_enable(client, session_factory):
    """Kernfall: derselbe Code, der /2fa/enable ausgeloest hat, darf nicht
    sofort danach auch /2fa/disable ausloesen koennen (2FA wieder aus, ohne
    dass der Angreifer das Secret je gesehen hat)."""
    _seed_user(session_factory, "mgmt-replay-2", "pw")
    headers = _login_headers(client, "mgmt-replay-2", "pw")

    setup = client.post("/auth/2fa/setup", headers=headers).json()
    code = totp.totp_at(setup["secret"], time.time())

    enable = client.post("/auth/2fa/enable", json={"code": code}, headers=headers)
    assert enable.status_code == 200

    disable = client.post("/auth/2fa/disable", json={"code": code}, headers=headers)
    assert disable.status_code == 401
    assert "verwendet" in disable.json()["detail"]

    # 2FA muss weiterhin aktiv sein -- der Replay durfte nichts bewirken.
    with session_factory() as s:
        user = s.query(User).filter(User.id == "mgmt-replay-2").first()
        assert user.totp_enabled == 1


def test_disable_accepts_fresh_code_after_replay_rejection(client, session_factory, monkeypatch):
    """Regression-Guard: ein GUELTIGER, NEUER Code darf durch die Anti-Replay-
    Logik nicht dauerhaft blockiert werden."""
    _seed_user(session_factory, "mgmt-replay-3", "pw")
    headers = _login_headers(client, "mgmt-replay-3", "pw")

    setup = client.post("/auth/2fa/setup", headers=headers).json()
    base_t = time.time()
    code = totp.totp_at(setup["secret"], base_t)
    assert client.post("/auth/2fa/enable", json={"code": code}, headers=headers).status_code == 200

    future_t = base_t + 31  # naechster Zeitschritt
    monkeypatch.setattr(time, "time", lambda: future_t)
    fresh_code = totp.totp_at(setup["secret"], future_t)

    disable = client.post("/auth/2fa/disable", json={"code": fresh_code}, headers=headers)
    assert disable.status_code == 200
    assert disable.json()["enabled"] is False
