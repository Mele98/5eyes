"""Roadmap #28 (Standpunkt 2026-08-07): Refresh-Token-Rotation.

Testet services/refresh_tokens.py (reine Logik) UND die HTTP-Endpoints
(/auth/login liefert refresh_token, /auth/refresh rotiert, /auth/logout
revoziert). Rotation + Reuse-Detection sind die sicherheitskritischen
Kerneigenschaften (RFC 6749 Sec. 10.4) -- beide werden explizit geprueft.
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

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.refresh_token import RefreshToken  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import hash_password  # noqa: E402
from services.refresh_tokens import (  # noqa: E402
    RefreshTokenReuseDetected,
    issue_refresh_token,
    revoke_all_for_user,
    revoke_family,
    rotate_refresh_token,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Service-Layer (reine Logik, eigene In-Memory-DB)
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_refresh.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_user(SF, uid="u1", is_active=1):
    with SF() as s:
        u = User(
            id=uid, username=uid, password_hash=hash_password("irrelevant123"),
            full_name=uid, role="advisor", is_active=is_active,
            created_at=_now(), updated_at=_now(),
        )
        s.add(u)
        s.commit()
        s.refresh(u)
        return u


def test_issue_refresh_token_creates_row_with_hash_not_raw(session_factory):
    with session_factory() as db:
        user = _seed_user(session_factory)
        issued = issue_refresh_token(db, user)
        db.commit()
        assert issued.raw_token
        row = db.query(RefreshToken).filter(RefreshToken.id == issued.row.id).first()
        assert row is not None
        assert row.token_hash != issued.raw_token
        assert row.revoked_at is None
        assert row.family_id  # neue Familie generiert


def test_issue_refresh_token_reuses_given_family_id(session_factory):
    with session_factory() as db:
        user = _seed_user(session_factory)
        first = issue_refresh_token(db, user)
        second = issue_refresh_token(db, user, family_id=first.row.family_id)
        assert second.row.family_id == first.row.family_id


def test_rotate_success_marks_old_revoked_and_issues_new(session_factory):
    with session_factory() as db:
        user = _seed_user(session_factory)
        first = issue_refresh_token(db, user)
        db.commit()

        result = rotate_refresh_token(db, first.raw_token)
        db.commit()

        assert result is not None
        rotated_user, new_token = result
        assert rotated_user.id == user.id
        assert new_token.raw_token != first.raw_token
        assert new_token.row.family_id == first.row.family_id

        old_row = db.query(RefreshToken).filter(RefreshToken.id == first.row.id).first()
        assert old_row.revoked_at is not None
        assert old_row.replaced_by_id == new_token.row.id


def test_rotate_unknown_token_returns_none(session_factory):
    with session_factory() as db:
        assert rotate_refresh_token(db, "not-a-real-token") == None  # noqa: E711


def test_rotate_expired_token_returns_none(session_factory):
    with session_factory() as db:
        user = _seed_user(session_factory)
        issued = issue_refresh_token(db, user)
        issued.row.expires_at = "2000-01-01T00:00:00Z"
        db.commit()
        assert rotate_refresh_token(db, issued.raw_token) is None


def test_rotate_inactive_user_returns_none(session_factory):
    with session_factory() as db:
        user = _seed_user(session_factory, is_active=0)
        issued = issue_refresh_token(db, user)
        db.commit()
        assert rotate_refresh_token(db, issued.raw_token) is None


def test_rotate_reused_token_raises_and_revokes_entire_family(session_factory):
    """Kern-Sicherheitseigenschaft: Reuse eines VERBRAUCHTEN Tokens revoziert
    die gesamte Kette, inkl. des zuletzt gueltigen Nachfolgers."""
    with session_factory() as db:
        user = _seed_user(session_factory)
        first = issue_refresh_token(db, user)
        db.commit()

        # Legitime erste Rotation.
        _, second = rotate_refresh_token(db, first.raw_token)
        db.commit()

        # Angreifer praesentiert die ALTE (bereits verbrauchte) Kopie erneut.
        with pytest.raises(RefreshTokenReuseDetected):
            rotate_refresh_token(db, first.raw_token)
        db.commit()

        # Der Nachfolger (den der legitime Client jetzt haelt) ist AUCH tot --
        # ein erneuter Versuch mit ihm ist selbst wieder ein Reuse eines
        # bereits revozierten Tokens, also erneut RefreshTokenReuseDetected
        # (nicht None -- None ist nur fuer UNBEKANNTE/abgelaufene Tokens).
        second_row = db.query(RefreshToken).filter(RefreshToken.id == second.row.id).first()
        assert second_row.revoked_at is not None
        with pytest.raises(RefreshTokenReuseDetected):
            rotate_refresh_token(db, second.raw_token)


def test_revoke_family_only_touches_that_family(session_factory):
    with session_factory() as db:
        user = _seed_user(session_factory)
        family_a = issue_refresh_token(db, user)
        family_b = issue_refresh_token(db, user)
        db.commit()

        revoked_count = revoke_family(db, family_a.row.family_id)
        db.commit()

        assert revoked_count == 1
        assert db.query(RefreshToken).filter(RefreshToken.id == family_a.row.id).first().revoked_at is not None
        assert db.query(RefreshToken).filter(RefreshToken.id == family_b.row.id).first().revoked_at is None


def test_revoke_all_for_user_touches_all_families(session_factory):
    with session_factory() as db:
        user = _seed_user(session_factory)
        other_user = _seed_user(session_factory, uid="u2")
        mine_a = issue_refresh_token(db, user)
        mine_b = issue_refresh_token(db, user)
        others = issue_refresh_token(db, other_user)
        db.commit()

        revoked_count = revoke_all_for_user(db, user.id)
        db.commit()

        assert revoked_count == 2
        assert db.query(RefreshToken).filter(RefreshToken.id == mine_a.row.id).first().revoked_at is not None
        assert db.query(RefreshToken).filter(RefreshToken.id == mine_b.row.id).first().revoked_at is not None
        assert db.query(RefreshToken).filter(RefreshToken.id == others.row.id).first().revoked_at is None


# ---------------------------------------------------------------------------
# HTTP-Endpoints (TestClient, echte App)
# ---------------------------------------------------------------------------


@pytest.fixture()
def http_session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_refresh_http.db'}",
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
def _reset_login_guard():
    """Der Login/Refresh-Rate-Limit-Guard ist ein prozessweiter Singleton --
    ohne Reset akkumulieren Fehlversuche ueber Tests hinweg und loesen einen
    429 statt der erwarteten 401/200 aus (identisches Muster zu
    test_invite_onboarding.py::_reset_invite_guard)."""
    from services.login_guard import login_attempt_guard
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()
    yield
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()


@pytest.fixture()
def http_client(http_session_factory):
    def override_db():
        with http_session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_http_user(SF, username="advisor1", password="correctpassword123"):
    with SF() as s:
        s.add(User(
            id=username, username=username, password_hash=hash_password(password),
            full_name="Test Advisor", role="advisor", is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def test_login_response_includes_refresh_token(http_client, http_session_factory):
    _seed_http_user(http_session_factory)
    r = http_client.post("/auth/login", json={"username": "advisor1", "password": "correctpassword123"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refresh_token"]
    assert body["access_token"]


def test_refresh_endpoint_rotates_and_returns_new_tokens(http_client, http_session_factory):
    _seed_http_user(http_session_factory)
    login = http_client.post("/auth/login", json={"username": "advisor1", "password": "correctpassword123"})
    old_refresh = login.json()["refresh_token"]

    r = http_client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refresh_token"] != old_refresh
    assert body["access_token"]


def test_refresh_endpoint_rejects_reused_token(http_client, http_session_factory):
    _seed_http_user(http_session_factory)
    login = http_client.post("/auth/login", json={"username": "advisor1", "password": "correctpassword123"})
    old_refresh = login.json()["refresh_token"]

    first = http_client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert first.status_code == 200
    new_refresh = first.json()["refresh_token"]

    # Reuse der ALTEN Kopie -- muss 401 liefern UND die gesamte Kette toeten.
    second = http_client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert second.status_code == 401

    # Der eigentlich noch gueltige Nachfolger ist jetzt AUCH tot (Kette komplett beendet).
    third = http_client.post("/auth/refresh", json={"refresh_token": new_refresh})
    assert third.status_code == 401


def test_refresh_endpoint_rejects_garbage_token(http_client, http_session_factory):
    _seed_http_user(http_session_factory)
    r = http_client.post("/auth/refresh", json={"refresh_token": "totally-made-up-token"})
    assert r.status_code == 401


def test_logout_revokes_refresh_tokens(http_client, http_session_factory):
    _seed_http_user(http_session_factory)
    login = http_client.post("/auth/login", json={"username": "advisor1", "password": "correctpassword123"})
    access_token = login.json()["access_token"]
    refresh_token = login.json()["refresh_token"]

    logout = http_client.post("/auth/logout", headers={"Authorization": f"Bearer {access_token}"})
    assert logout.status_code == 200

    r = http_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 401


def test_refresh_endpoint_rate_limited_after_repeated_failures(http_client, http_session_factory):
    _seed_http_user(http_session_factory)
    saw_429 = False
    for _ in range(8):
        r = http_client.post("/auth/refresh", json={"refresh_token": "always-invalid"})
        if r.status_code == 429:
            saw_429 = True
            assert r.headers.get("Retry-After")
            break
        assert r.status_code == 401
    assert saw_429, "Rate-Limit auf /auth/refresh greift nicht"
