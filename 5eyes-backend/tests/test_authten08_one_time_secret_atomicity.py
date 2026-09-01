"""AUTH-TEN-08 (Codex-Audit 2026-08-25, docs/audits/2026-08-25-auth-execution-
operations-followup-audit.md): Invite- und Passwort-Reset-Tokens waren
read-then-write-Einmalvertraege -- zwei parallele Requests mit demselben
Token konnten beide die Gueltigkeitspruefung bestehen, bevor irgendeiner
committet, und je einen eigenen Effekt (Passwort setzen + Login) ausloesen.

Diese Tests reproduzieren die Race-Situation direkt gegen die Router-
Funktionen mit zwei echten Threads/DB-Sessions (dieselbe Pragma-Konfiguration
wie test_refresh_token_rotation.py::test_concurrent_rotation_of_same_token_
exactly_one_wins) -- exakt EIN Aufruf darf erfolgreich sein, der andere
muss den Standard-Fehler fuer einen ungueltigen/verbrauchten Token bekommen.

Scope dieser Fassung (bewusst NICHT der volle Fixvertrag): nur die beiden
oeffentlichen HTTP-Einmalvertraege (Reset-Token, Invite-Token). TOTP-Replay-
Counter-CAS, atomarer Recovery-Code-Verbrauch und ein DB-seitiger Bootstrap-
Singleton bleiben ein separates, groesseres Vorhaben.
"""
from __future__ import annotations

import datetime
import sys
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request as _StarletteRequest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, attach_sqlite_pragmas, build_connect_args  # noqa: E402
from main import app  # noqa: F401,E402  (registriert alle Models)
from models.users import User  # noqa: E402
from routers.auth import (  # noqa: E402
    _PasswordResetConfirm,
    _hash_invite_token,
    invite_accept,
    password_reset_confirm,
)
from schemas.users import InviteAccept  # noqa: E402
from services.account_recovery import issue_reset_token  # noqa: E402
from services.auth import hash_password  # noqa: E402


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _fake_request() -> _StarletteRequest:
    """Minimaler ASGI-Scope -- reicht fuer _extract_client_ip() (liest nur
    request.headers/request.client.host, siehe routers/auth.py)."""
    scope = {
        "type": "http", "method": "POST", "path": "/",
        "headers": [], "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80), "scheme": "http",
    }
    return _StarletteRequest(scope)


@pytest.fixture(autouse=True)
def _reset_login_guard():
    """Der IP-Rate-Limit-Guard ist ein prozessweiter Singleton -- ohne Reset
    wuerden Fehlversuche ueber Tests hinweg unter derselben Fake-Request-IP
    akkumulieren (siehe test_invite_onboarding.py fuer denselben Vertrag)."""
    from services.login_guard import login_attempt_guard
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()
    yield
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()


@pytest.fixture()
def session_factory(tmp_path):
    """Datei-basierte SQLite-DB mit denselben Pragmas wie database.py (WAL,
    busy_timeout=5000) -- siehe test_refresh_token_rotation.py fuer denselben
    etablierten Pragma-Fixture-Vertrag, sonst wirft der zweite Writer sofort
    ein 'database is locked' statt (realistisch) zu warten."""
    db_url = f"sqlite:///{tmp_path / 'authten08.db'}"
    engine = create_engine(db_url, connect_args=build_connect_args(database_url=db_url), pool_timeout=30)
    attach_sqlite_pragmas(engine)
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# ---------------------------------------------------------------------------
# Passwort-Reset-Token
# ---------------------------------------------------------------------------

def test_concurrent_reset_confirm_with_same_token_exactly_one_wins(session_factory):
    SF = session_factory
    with SF() as seed_db:
        user = User(
            id="authten08-r1", username="authten08-r1", password_hash=hash_password("oldpw12345678"),
            full_name="r1", role="advisor", is_active=1, created_at=_now(), updated_at=_now(),
        )
        seed_db.add(user)
        seed_db.commit()
        raw_token = issue_reset_token(user)
        seed_db.commit()

    barrier = threading.Barrier(2)
    results: list = []
    lock = threading.Lock()

    def _attempt(new_password):
        barrier.wait()
        with SF() as db:
            try:
                password_reset_confirm(
                    _PasswordResetConfirm(token=raw_token, new_password=new_password),
                    _fake_request(), db=db,
                )
                with lock:
                    results.append("ok")
            except HTTPException as exc:
                with lock:
                    results.append(("http_error", exc.status_code))

    threads = [
        threading.Thread(target=_attempt, args=(f"newpw-{i}-12345678",)) for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 2
    ok_count = results.count("ok")
    error_results = [r for r in results if r != "ok"]
    assert ok_count == 1, f"Erwartete genau 1 Gewinner, bekam: {results}"
    assert len(error_results) == 1
    assert error_results[0] == ("http_error", 400)

    with SF() as db:
        row = db.query(User).filter_by(id="authten08-r1").first()
        assert row.reset_token_hash is None  # Token final verbraucht, nicht doppelt


# ---------------------------------------------------------------------------
# Invite-Token
# ---------------------------------------------------------------------------

def test_concurrent_invite_accept_with_same_token_exactly_one_wins(session_factory):
    SF = session_factory
    raw_token = "authten08-invite-token-raw-value-1234567890"
    with SF() as seed_db:
        user = User(
            id="authten08-i1", username="authten08-i1", password_hash="unset",
            full_name="i1", role="advisor", is_active=1,
            invite_token_hash=_hash_invite_token(raw_token),
            invite_expires_at=(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1))
                .isoformat().replace("+00:00", "Z"),
            created_at=_now(), updated_at=_now(),
        )
        seed_db.add(user)
        seed_db.commit()

    barrier = threading.Barrier(2)
    results: list = []
    lock = threading.Lock()

    def _attempt(password):
        barrier.wait()
        with SF() as db:
            try:
                invite_accept(
                    InviteAccept(token=raw_token, password=password),
                    _fake_request(), db=db,
                )
                with lock:
                    results.append("ok")
            except HTTPException as exc:
                with lock:
                    results.append(("http_error", exc.status_code))

    threads = [
        threading.Thread(target=_attempt, args=(f"newpw-{i}-12345678",)) for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 2
    ok_count = results.count("ok")
    error_results = [r for r in results if r != "ok"]
    assert ok_count == 1, f"Erwartete genau 1 Gewinner, bekam: {results}"
    assert len(error_results) == 1
    assert error_results[0] == ("http_error", 404)

    with SF() as db:
        row = db.query(User).filter_by(id="authten08-i1").first()
        assert row.invite_token_hash is None  # Token final verbraucht, nicht doppelt
