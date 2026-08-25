"""#25 2FA-Recovery-Codes + #27 Passwort-Reset (Self-Service)."""
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
from services import totp
from services.account_recovery import issue_reset_token, ensure_account_recovery_columns


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_recovery.db'}",
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


def _seed_user(SF, uid, password, email=None):
    with SF() as s:
        s.add(User(
            id=uid, username=uid, password_hash=hash_password(password),
            full_name=uid, email=email, role="advisor", is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def _headers(client, uid, pw, totp_secret=None):
    body = {"username": uid, "password": pw}
    if totp_secret:
        body["totp_code"] = totp.totp_at(totp_secret, time.time())
    tok = client.post("/auth/login", json=body).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _enable_2fa(client, uid, pw):
    """Vollflow setup->enable; gibt (secret, recovery_codes) zurueck."""
    h = _headers(client, uid, pw)
    secret = client.post("/auth/2fa/setup", headers=h).json()["secret"]
    code = totp.totp_at(secret, time.time())
    body = client.post("/auth/2fa/enable", headers=h, json={"code": code}).json()
    return secret, body["recovery_codes"]


# ── #27 Passwort-Reset ───────────────────────────────────────────────────────

def test_reset_request_is_generic_and_issues_token(client, session_factory):
    _seed_user(session_factory, "r1", "pw")
    r = client.post("/auth/password-reset/request", json={"username": "r1"})
    assert r.status_code == 200
    with session_factory() as s:
        assert s.query(User).filter_by(id="r1").first().reset_token_hash
    # Unbekanntes Konto -> ebenfalls generisch 200 (keine Enumeration).
    r2 = client.post("/auth/password-reset/request", json={"username": "does-not-exist"})
    assert r2.status_code == 200


# ── 2026-07-25 (Generalaudit): Host-Header-Injection -> Password-Reset-
# Poisoning. Der Reset-Link wurde bisher aus dem (Client-kontrollierten!)
# Host-Header konstruiert -- ein Angreifer konnte auf dem OEFFENTLICHEN
# /auth/password-reset/request-Endpoint einen gueltigen Reset-Token fuer ein
# fremdes Konto ausloesen UND den Link auf eine Phishing-Domain umleiten,
# indem er den Host-Header manipuliert. Fix: config.public_base_url wird,
# wenn konfiguriert, IMMER bevorzugt (Header komplett ignoriert).

def test_reset_link_ignores_attacker_host_header_when_public_base_url_configured(
    client, session_factory, monkeypatch,
):
    from config import settings
    import services.mailer as mailer_mod

    monkeypatch.setattr(settings, "public_base_url", "https://trusted.5eyes.example")
    _seed_user(session_factory, "r2", "pw", email="victim@example.test")

    captured = {}

    def _fake_send(to_email, full_name, link):
        captured["link"] = link
        return True

    monkeypatch.setattr(mailer_mod, "send_password_reset_email", _fake_send)
    import routers.auth as auth_router
    monkeypatch.setattr(auth_router, "send_password_reset_email", _fake_send)

    r = client.post(
        "/auth/password-reset/request",
        json={"username": "r2"},
        headers={"Host": "evil-attacker.test", "X-Forwarded-Host": "evil-attacker.test"},
    )
    assert r.status_code == 200
    assert captured["link"].startswith("https://trusted.5eyes.example/")
    assert "evil-attacker.test" not in captured["link"]


def test_reset_link_falls_back_to_host_header_when_public_base_url_unset(
    client, session_factory, monkeypatch,
):
    from config import settings
    monkeypatch.setattr(settings, "public_base_url", None)
    _seed_user(session_factory, "r3", "pw", email="user3@example.test")

    captured = {}

    def _fake_send(to_email, full_name, link):
        captured["link"] = link
        return True

    import routers.auth as auth_router
    monkeypatch.setattr(auth_router, "send_password_reset_email", _fake_send)

    r = client.post("/auth/password-reset/request", json={"username": "r3"})
    assert r.status_code == 200
    # Backwards-Compat: unveraendertes Fallback-Verhalten (kein public_base_url
    # konfiguriert -- z.B. lokaler Tier-1-Desktop-Betrieb, kein Angriffsvektor).
    assert "/app/5eyes_v2.html?reset=" in captured["link"]


def test_reset_confirm_sets_new_password_and_is_single_use(client, session_factory):
    _seed_user(session_factory, "r2", "oldpw")
    with session_factory() as s:
        ensure_account_recovery_columns(s)
        u = s.query(User).filter_by(id="r2").first()
        token = issue_reset_token(u)
        u.updated_at = _now()
        s.commit()
    r = client.post("/auth/password-reset/confirm", json={"token": token, "new_password": "newpw1234"})
    assert r.status_code == 200
    assert client.post("/auth/login", json={"username": "r2", "password": "oldpw"}).status_code == 401
    assert client.post("/auth/login", json={"username": "r2", "password": "newpw1234"}).status_code == 200
    # Token ist verbraucht -> zweiter Versuch scheitert.
    r2 = client.post("/auth/password-reset/confirm", json={"token": token, "new_password": "another123"})
    assert r2.status_code == 400


def test_reset_confirm_rejects_invalid_token(client, session_factory):
    _seed_user(session_factory, "r3", "pw")
    r = client.post("/auth/password-reset/confirm", json={"token": "garbage", "new_password": "newpw1234"})
    assert r.status_code == 400


def test_reset_confirm_rejects_short_password(client, session_factory):
    _seed_user(session_factory, "r4", "pw")
    with session_factory() as s:
        u = s.query(User).filter_by(id="r4").first()
        token = issue_reset_token(u)
        s.commit()
    r = client.post("/auth/password-reset/confirm", json={"token": token, "new_password": "short"})
    assert r.status_code == 400


# ── #25 2FA-Recovery-Codes ───────────────────────────────────────────────────

def test_enable_returns_recovery_codes(client, session_factory):
    _seed_user(session_factory, "u1", "pw")
    _secret, codes = _enable_2fa(client, "u1", "pw")
    assert isinstance(codes, list) and len(codes) == 10
    assert all("-" in c for c in codes)


def test_login_with_recovery_code_works_and_is_single_use(client, session_factory):
    _seed_user(session_factory, "u2", "pw")
    _secret, codes = _enable_2fa(client, "u2", "pw")
    rc = codes[0]
    # Falscher/abwesender TOTP, aber gueltiger Recovery-Code -> Login ok.
    r = client.post("/auth/login", json={"username": "u2", "password": "pw", "totp_code": rc})
    assert r.status_code == 200
    # Derselbe Code ein zweites Mal -> abgelehnt (single-use).
    r2 = client.post("/auth/login", json={"username": "u2", "password": "pw", "totp_code": rc})
    assert r2.status_code == 401


def test_regenerate_invalidates_old_codes(client, session_factory):
    _seed_user(session_factory, "u3", "pw")
    secret, codes = _enable_2fa(client, "u3", "pw")
    h = _headers(client, "u3", "pw", secret)
    new = client.post("/auth/2fa/recovery/regenerate", headers=h).json()["recovery_codes"]
    assert set(new).isdisjoint(set(codes))
    # Alter Code greift nicht mehr.
    assert client.post("/auth/login", json={"username": "u3", "password": "pw", "totp_code": codes[0]}).status_code == 401
    # Neuer Code greift.
    assert client.post("/auth/login", json={"username": "u3", "password": "pw", "totp_code": new[0]}).status_code == 200


def test_recovery_status_counts_remaining(client, session_factory):
    _seed_user(session_factory, "u4", "pw")
    secret, codes = _enable_2fa(client, "u4", "pw")
    h = _headers(client, "u4", "pw", secret)
    st = client.get("/auth/2fa/recovery/status", headers=h).json()
    assert st["enabled"] is True and st["remaining"] == 10
    # Einen verbrauchen -> remaining sinkt.
    client.post("/auth/login", json={"username": "u4", "password": "pw", "totp_code": codes[0]})
    st2 = client.get("/auth/2fa/recovery/status", headers=h).json()
    assert st2["remaining"] == 9


def test_disable_clears_recovery_codes(client, session_factory):
    _seed_user(session_factory, "u5", "pw")
    secret, codes = _enable_2fa(client, "u5", "pw")
    h = _headers(client, "u5", "pw", secret)
    code = totp.totp_at(secret, time.time())
    assert client.post("/auth/2fa/disable", headers=h, json={"code": code}).status_code == 200
    with session_factory() as s:
        assert not s.query(User).filter_by(id="u5").first().totp_recovery_codes


def test_regenerate_requires_2fa_active(client, session_factory):
    _seed_user(session_factory, "u6", "pw")
    h = _headers(client, "u6", "pw")
    r = client.post("/auth/2fa/recovery/regenerate", headers=h)
    assert r.status_code == 400


def test_recovery_columns_in_startup_migration():
    """Regression: das User-Modell selektiert reset_token_hash/totp_recovery_codes bei
    JEDEM Query (inkl. Login). Auf bestehenden DBs MUSS ensure_runtime_columns sie beim
    Start ergaenzen, sonst crasht der Login (OperationalError: no such column)."""
    db_src = (Path(__file__).resolve().parents[1] / "database.py").read_text(encoding="utf-8")
    for col in ("reset_token_hash", "reset_token_expires_at", "totp_recovery_codes"):
        assert f"('{col}', 'TEXT')" in db_src, f"{col} fehlt in ensure_runtime_columns (Startup-Migration)"
