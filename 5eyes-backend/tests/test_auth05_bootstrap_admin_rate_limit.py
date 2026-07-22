"""AUTH-05 (2026-07-22): /auth/bootstrap-admin hatte kein Rate-Limit — ein
oeffentlicher, unauthentifizierter Endpoint der einen Admin-Account anlegt
war beliebig oft aufrufbar (Brute-Force/DoS auf die Ersteinrichtung). Fix:
Wiederverwendung des bestehenden login_attempt_guard-Musters, IP-basierter
Guard-Key (analog zu den Invite-Endpoints)."""
from __future__ import annotations

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
from services.login_guard import login_attempt_guard


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_auth05.db'}",
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
def _reset_persistent_login_guard():
    """Der Guard ist DB-persistent + prozessweit geteilt (AUTH-03) —
    zwischen diesen Tests (und anderen Modulen) zuruecksetzen."""
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()
    yield
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()


def test_bootstrap_admin_first_call_succeeds(client):
    r = client.post("/auth/bootstrap-admin", json={
        "username": "root", "password": "pw12345678", "full_name": "Root",
    })
    assert r.status_code == 201
    assert "access_token" in r.json()


def test_bootstrap_admin_rate_limited_after_repeated_attempts(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "login_rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "login_max_attempts", 3, raising=False)
    monkeypatch.setattr(settings, "login_window_seconds", 300, raising=False)
    monkeypatch.setattr(settings, "login_lockout_seconds", 600, raising=False)

    # Erster Aufruf legt den Admin an (Ersteinrichtung noch offen) -> 201.
    r0 = client.post("/auth/bootstrap-admin", json={
        "username": "root", "password": "pw12345678", "full_name": "Root",
    })
    assert r0.status_code == 201

    # Ersteinrichtung ist jetzt abgeschlossen -> jeder weitere Versuch 409,
    # zaehlt aber gegen das Rate-Limit (Brute-Force/DoS-Schutz).
    for _ in range(settings.login_max_attempts - 1):
        r = client.post("/auth/bootstrap-admin", json={
            "username": "root2", "password": "pw12345678", "full_name": "Root2",
        })
        assert r.status_code == 409

    # Nach Erreichen des Limits: 429 statt 409.
    locked = client.post("/auth/bootstrap-admin", json={
        "username": "root3", "password": "pw12345678", "full_name": "Root3",
    })
    assert locked.status_code == 429
    assert "Retry-After" in locked.headers


def test_bootstrap_admin_lockout_is_per_source_not_global(client, monkeypatch):
    """Der Lockout haengt am Guard-Key (IP via X-Forwarded-For) — eine andere
    Quelle darf durch den Lockout einer anderen NICHT blockiert werden."""
    from config import settings
    monkeypatch.setattr(settings, "login_rate_limit_enabled", True, raising=False)
    monkeypatch.setattr(settings, "login_max_attempts", 2, raising=False)
    monkeypatch.setattr(settings, "login_window_seconds", 300, raising=False)
    monkeypatch.setattr(settings, "login_lockout_seconds", 600, raising=False)

    attacker_headers = {"X-Forwarded-For": "10.0.0.9"}
    r0 = client.post(
        "/auth/bootstrap-admin",
        json={"username": "root", "password": "pw12345678", "full_name": "Root"},
        headers=attacker_headers,
    )
    assert r0.status_code == 201
    r1 = client.post(
        "/auth/bootstrap-admin",
        json={"username": "root2", "password": "pw12345678", "full_name": "Root2"},
        headers=attacker_headers,
    )
    assert r1.status_code == 409
    r2 = client.post(
        "/auth/bootstrap-admin",
        json={"username": "root3", "password": "pw12345678", "full_name": "Root3"},
        headers=attacker_headers,
    )
    assert r2.status_code == 429

    other_headers = {"X-Forwarded-For": "10.0.0.10"}
    r3 = client.post(
        "/auth/bootstrap-admin",
        json={"username": "root4", "password": "pw12345678", "full_name": "Root4"},
        headers=other_headers,
    )
    # Bereits abgeschlossene Ersteinrichtung -> 409, NICHT 429 (andere Quelle
    # ist nicht gesperrt).
    assert r3.status_code == 409
