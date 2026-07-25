"""E1 (2026-06-14): Mitarbeiter-Onboarding per Einladungslink.

Admin legt Account OHNE Passwort an -> Mitarbeiter setzt es selbst per Token.
Token ist einmalig, ablaufend, tenant-vererbt. Nach Annahme erzwingt das
2FA-Hard-Gate (Frontend) das Enrollment beim ersten Login.
"""
from __future__ import annotations
import datetime
import sys
from pathlib import Path
from types import SimpleNamespace

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
from services.auth import require_admin


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'invite.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(autouse=True)
def _reset_invite_guard():
    """Der IP-Rate-Limit-Guard ist ein prozessweiter Singleton; ohne Reset würden
    404/410-Fehlversuche über die Tests unter dem gemeinsamen TestClient-IP
    akkumulieren und mitten in der Suite einen 429 statt 404 auslösen."""
    from services.login_guard import login_attempt_guard
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()
    yield
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()


@pytest.fixture()
def client(session_factory):
    def override_db():
        with session_factory() as s:
            yield s
    admin = SimpleNamespace(id="admin-a", full_name="Admin A", role="admin", tenant_id="firm-A")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _invite(client, username="neuer.mitarbeiter", full_name="Neuer Mitarbeiter", role="advisor"):
    r = client.post("/users/invite", json={"username": username, "full_name": full_name, "role": role})
    return r


def test_invite_creates_account_with_token_and_tenant(client, session_factory):
    r = _invite(client)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["invite_token"] and len(data["invite_token"]) > 20
    assert data["username"] == "neuer.mitarbeiter"
    assert data["email_sent"] is False  # SMTP standardmaessig aus -> Link-Copy
    # Account existiert, hat Tenant des Admins, Token-HASH (nicht Klartext) gespeichert.
    with session_factory() as s:
        u = s.query(User).filter(User.username == "neuer.mitarbeiter").first()
        assert u is not None
        assert u.tenant_id == "firm-A"
        assert u.invite_token_hash and u.invite_token_hash != data["invite_token"]
        assert u.invite_expires_at


# ── 2026-07-25 (Generalaudit): Host-Header-Injection -> Invite-Link auf eine
# Phishing-Domain umleitbar (siehe test_account_recovery.py fuer den
# Reset-Link-Fall). public_base_url wird, wenn konfiguriert, IMMER bevorzugt.

def test_invite_link_ignores_attacker_host_header_when_public_base_url_configured(
    client, monkeypatch,
):
    from config import settings
    monkeypatch.setattr(settings, "public_base_url", "https://trusted.5eyes.example")

    captured = {}

    def _fake_send(to_email, full_name, link):
        captured["link"] = link
        return True

    import routers.auth as auth_router
    monkeypatch.setattr(auth_router, "send_invite_email", _fake_send)

    r = client.post(
        "/users/invite",
        json={"username": "phish.target", "full_name": "Phish Target", "role": "advisor"},
        headers={"Host": "evil-attacker.test", "X-Forwarded-Host": "evil-attacker.test"},
    )
    assert r.status_code == 201, r.text
    assert captured["link"].startswith("https://trusted.5eyes.example/")
    assert "evil-attacker.test" not in captured["link"]


def test_invite_link_falls_back_to_forwarded_host_when_public_base_url_unset(
    client, monkeypatch,
):
    from config import settings
    monkeypatch.setattr(settings, "public_base_url", None)

    captured = {}

    def _fake_send(to_email, full_name, link):
        captured["link"] = link
        return True

    import routers.auth as auth_router
    monkeypatch.setattr(auth_router, "send_invite_email", _fake_send)

    r = client.post(
        "/users/invite",
        json={"username": "legacy.behavior", "full_name": "Legacy Behavior", "role": "advisor"},
        headers={"X-Forwarded-Host": "app.legit-deployment.test", "X-Forwarded-Proto": "https"},
    )
    assert r.status_code == 201, r.text
    # Backwards-Compat: unveraendertes Fallback-Verhalten (kein public_base_url
    # konfiguriert).
    assert captured["link"].startswith("https://app.legit-deployment.test/")


def test_invite_preview_returns_display_info(client):
    token = _invite(client).json()["invite_token"]
    r = client.get(f"/auth/invite/{token}")
    assert r.status_code == 200
    assert r.json()["username"] == "neuer.mitarbeiter"
    assert r.json()["full_name"] == "Neuer Mitarbeiter"


def test_invite_accept_sets_password_and_logs_in(client, session_factory):
    token = _invite(client).json()["invite_token"]
    r = client.post("/auth/invite/accept", json={"token": token, "password": "meinpasswort123"})
    assert r.status_code == 200, r.text
    assert "access_token" in r.json()
    # Token verbraucht; danach normaler Login moeglich.
    with session_factory() as s:
        u = s.query(User).filter(User.username == "neuer.mitarbeiter").first()
        assert u.invite_token_hash is None
        assert u.invite_expires_at is None
    login = client.post("/auth/login", json={"username": "neuer.mitarbeiter", "password": "meinpasswort123"})
    assert login.status_code == 200


def test_invite_token_single_use(client):
    token = _invite(client).json()["invite_token"]
    ok = client.post("/auth/invite/accept", json={"token": token, "password": "meinpasswort123"})
    assert ok.status_code == 200
    again = client.post("/auth/invite/accept", json={"token": token, "password": "anderespwd999"})
    assert again.status_code == 404


def test_invite_invalid_token_404(client):
    r = client.get("/auth/invite/voellig-ungueltig")
    assert r.status_code == 404
    r2 = client.post("/auth/invite/accept", json={"token": "voellig-ungueltig", "password": "meinpasswort123"})
    assert r2.status_code == 404


def test_invite_expired_410(client, session_factory):
    token = _invite(client).json()["invite_token"]
    # Ablauf in die Vergangenheit setzen.
    with session_factory() as s:
        u = s.query(User).filter(User.username == "neuer.mitarbeiter").first()
        u.invite_expires_at = "2000-01-01T00:00:00.000Z"
        s.commit()
    r = client.get(f"/auth/invite/{token}")
    assert r.status_code == 410
    r2 = client.post("/auth/invite/accept", json={"token": token, "password": "meinpasswort123"})
    assert r2.status_code == 410


def test_invite_endpoint_rate_limited(client):
    """Öffentlicher Endpoint: nach zu vielen ungültigen Token-Versuchen von
    derselben Quelle -> 429 (Anti-Enumeration / DoS)."""
    saw_429 = False
    for _ in range(8):  # login_max_attempts=5 -> spätestens danach gesperrt
        r = client.get("/auth/invite/immer-falsch")
        if r.status_code == 429:
            saw_429 = True
            assert r.headers.get("Retry-After")
            break
        assert r.status_code == 404
    assert saw_429, "Rate-Limit auf öffentlichem Invite-Endpoint greift nicht"


def test_invite_short_password_rejected(client):
    token = _invite(client).json()["invite_token"]
    r = client.post("/auth/invite/accept", json={"token": token, "password": "kurz"})
    assert r.status_code == 422


def test_invite_duplicate_username_409(client):
    assert _invite(client).status_code == 201
    assert _invite(client).status_code == 409


def test_resend_invite_rotates_token(client):
    """Resend: neuer Token gültig, alter Token tot."""
    first = _invite(client).json()
    uid, old_token = first["user_id"], first["invite_token"]
    r = client.post(f"/users/{uid}/invite/resend")
    assert r.status_code == 200, r.text
    new_token = r.json()["invite_token"]
    assert new_token != old_token
    assert client.get(f"/auth/invite/{old_token}").status_code == 404   # alter tot
    assert client.get(f"/auth/invite/{new_token}").status_code == 200   # neuer gültig


def test_resend_is_rate_limited(client):
    """#107: wiederholtes Resend wird pro Ziel-User gedrosselt (429)."""
    uid = _invite(client).json()["user_id"]
    saw_429 = False
    for _ in range(8):  # login_max_attempts=5 -> spätestens danach 429
        r = client.post(f"/users/{uid}/invite/resend")
        if r.status_code == 429:
            saw_429 = True
            assert r.headers.get("Retry-After")
            break
        assert r.status_code == 200, r.text
    assert saw_429, "Resend-Rate-Limit greift nicht"


def test_resend_on_active_account_409(client):
    first = _invite(client).json()
    client.post("/auth/invite/accept", json={"token": first["invite_token"], "password": "meinpasswort123"})
    r = client.post(f"/users/{first['user_id']}/invite/resend")
    assert r.status_code == 409


def test_revoke_invite_kills_link_and_account(client):
    first = _invite(client).json()
    uid, token = first["user_id"], first["invite_token"]
    r = client.delete(f"/users/{uid}/invite")
    assert r.status_code == 200 and r.json()["revoked"] is True
    # Link tot, Account weg (soft-deleted -> nicht in Liste, accept scheitert).
    assert client.get(f"/auth/invite/{token}").status_code == 404
    assert client.post("/auth/invite/accept", json={"token": token, "password": "meinpasswort123"}).status_code == 404
    users = [u for u in client.get("/users").json() if u["username"] == "neuer.mitarbeiter"]
    assert not users


def test_revoke_on_active_account_409(client):
    first = _invite(client).json()
    client.post("/auth/invite/accept", json={"token": first["invite_token"], "password": "meinpasswort123"})
    r = client.delete(f"/users/{first['user_id']}/invite")
    assert r.status_code == 409


def test_invited_user_listed_as_pending_then_active(client):
    """Team-UI: eingeladener User erscheint mit invite_pending=True, nach
    Annahme mit invite_pending=False."""
    token = _invite(client).json()["invite_token"]
    users = client.get("/users").json()
    match = [u for u in users if u["username"] == "neuer.mitarbeiter"]
    assert match and match[0]["invite_pending"] is True
    client.post("/auth/invite/accept", json={"token": token, "password": "meinpasswort123"})
    users2 = client.get("/users").json()
    match2 = [u for u in users2 if u["username"] == "neuer.mitarbeiter"]
    assert match2 and match2[0]["invite_pending"] is False
