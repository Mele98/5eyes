"""E1: 2FA/TOTP-Login-Gate + Setup/Enable-Flow."""
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


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_2fa.db'}",
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


def _seed_user(SF, uid, password, totp_secret=None, totp_enabled=0):
    with SF() as s:
        s.add(User(
            id=uid, username=uid, password_hash=hash_password(password),
            full_name=uid, role="advisor", is_active=1,
            totp_secret=totp_secret, totp_enabled=totp_enabled,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def test_login_without_2fa_ok(client, session_factory):
    _seed_user(session_factory, "u1", "pw")
    r = client.post("/auth/login", json={"username": "u1", "password": "pw"})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_legacy_user_response_normalizes_null_security_flags():
    """Additive columns are nullable in existing DBs and must serialize safely."""
    from types import SimpleNamespace

    from schemas.users import UserResponse

    legacy_user = SimpleNamespace(
        id="legacy-u1",
        username="legacy-u1",
        full_name="Legacy User",
        email=None,
        role="advisor",
        is_active=1,
        last_login_at=None,
        created_at=_now(),
        must_change_password=None,
        totp_enabled=None,
    )

    response = UserResponse.model_validate(legacy_user)

    assert response.must_change_password == 0
    assert response.totp_enabled == 0


def test_login_2fa_requires_code(client, session_factory):
    secret = totp.generate_secret()
    _seed_user(session_factory, "u2", "pw", totp_secret=secret, totp_enabled=1)
    r = client.post("/auth/login", json={"username": "u2", "password": "pw"})
    assert r.status_code == 401
    assert "2FA" in r.json()["detail"]
    assert r.headers.get("X-2FA-Required") == "1"


def test_login_2fa_valid_code_ok(client, session_factory):
    secret = totp.generate_secret()
    _seed_user(session_factory, "u3", "pw", totp_secret=secret, totp_enabled=1)
    code = totp.totp_at(secret, time.time())
    r = client.post("/auth/login", json={"username": "u3", "password": "pw", "totp_code": code})
    assert r.status_code == 200


def test_login_2fa_wrong_code_401(client, session_factory):
    secret = totp.generate_secret()
    _seed_user(session_factory, "u4", "pw", totp_secret=secret, totp_enabled=1)
    r = client.post("/auth/login", json={"username": "u4", "password": "pw", "totp_code": "000000"})
    assert r.status_code == 401


def test_status_exposes_required_flag(session_factory):
    """Pflicht-2FA-Hard-Gate: /auth/2fa/status spiegelt settings.require_2fa,
    damit das Frontend erzwungenes Enrollment auslösen kann."""
    from routers.auth import twofa_status
    from config import settings
    with session_factory() as db:
        u = User(id="rq1", username="rq1", password_hash="h", full_name="rq1",
                 role="advisor", is_active=1, totp_enabled=0,
                 created_at=_now(), updated_at=_now())
        db.add(u)
        db.commit()
        prev = getattr(settings, "require_2fa", False)
        try:
            settings.require_2fa = True
            st = twofa_status(current_user=u)
            assert st["required"] is True
            assert st["enabled"] is False
            settings.require_2fa = False
            assert twofa_status(current_user=u)["required"] is False
        finally:
            settings.require_2fa = prev


def test_setup_returns_qr_data_uri(session_factory):
    """2FA-Setup liefert ein SVG-QR-Bild als data:-URI (Usability fuer mobile
    Authenticator). Dependency-soft: fehlt segno, ist qr_svg None (kein 500)."""
    import base64 as _b64
    from routers.auth import twofa_setup
    with session_factory() as db:
        u = User(id="qr1", username="qr1", password_hash="h", full_name="qr1",
                 role="advisor", is_active=1, created_at=_now(), updated_at=_now())
        db.add(u)
        db.commit()
        res = twofa_setup(db=db, current_user=u)
        assert "qr_svg" in res
        qr = res["qr_svg"]
        if qr is not None:  # segno installiert -> echtes SVG
            assert qr.startswith("data:image/svg+xml;base64,")
            raw = _b64.b64decode(qr.split(",", 1)[1]).decode("utf-8", "replace")
            assert "<svg" in raw


def test_setup_and_enable_flow(session_factory):
    from routers.auth import twofa_setup, twofa_enable, _TwoFACodeRequest
    with session_factory() as db:
        u = User(id="s1", username="s1", password_hash="h", full_name="s1",
                 role="advisor", is_active=1, created_at=_now(), updated_at=_now())
        db.add(u)
        db.commit()
        res = twofa_setup(db=db, current_user=u)
        assert res["otpauth_uri"].startswith("otpauth://totp/")
        assert u.totp_enabled in (0, None)  # noch nicht aktiv
        code = totp.totp_at(res["secret"], time.time())
        out = twofa_enable(_TwoFACodeRequest(code=code), db=db, current_user=u)
        assert out["enabled"] is True
        assert u.totp_enabled == 1
