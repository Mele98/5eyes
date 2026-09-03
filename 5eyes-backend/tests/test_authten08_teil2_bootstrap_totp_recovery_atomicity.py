"""AUTH-TEN-08 (Teil 2, Codex-Audit-Followup 2026-08-25): der erste Teil des
Fixes (siehe test_authten08_one_time_secret_atomicity.py) deckte nur die
beiden oeffentlichen HTTP-Einmalvertraege (Reset-/Invite-Token) ab. Der
Docstring dort nennt drei bewusst zurueckgestellte Luecken -- dieses Modul
schliesst alle drei:

1. Bootstrap-Admin ist jetzt zusaetzlich zum In-Prozess-Lock
   (``routers.auth._bootstrap_admin_lock``) durch einen DB-seitigen
   Singleton (``models.bootstrap_lock.BootstrapLock``) geschuetzt -- deckt
   auch mehrere Backend-Worker-Prozesse (Tier-2/3) ab, nicht nur mehrere
   Threads/Requests innerhalb eines Prozesses.
2. TOTP-Login-Replay-Counter (``User.totp_last_counter``) wird jetzt per
   atomarem CAS-UPDATE verbraucht statt read-then-write auf dem ORM-Objekt.
3. 2FA-Recovery-Codes (``services.account_recovery.consume_recovery_code``)
   werden jetzt per atomarem CAS-UPDATE auf dem gesamten JSON-Blob
   verbraucht statt read-then-write.

Alle drei Tests nutzen echte Multi-Thread-SQLite-Konkurrenz (dieselbe
Pragma-Konfiguration wie test_refresh_token_rotation.py::
test_concurrent_rotation_of_same_token_exactly_one_wins und
test_authten08_one_time_secret_atomicity.py) -- ohne
``attach_sqlite_pragmas``/``build_connect_args`` wirft der zweite
gleichzeitige Writer sofort ein 'database is locked' statt (realistisch)
ueber PRAGMA busy_timeout zu warten.
"""
from __future__ import annotations

import contextlib
import datetime
import sys
import threading
import time
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
import routers.auth as auth_router  # noqa: E402
from models.bootstrap_lock import BootstrapLock  # noqa: E402
from models.users import User  # noqa: E402
from routers.auth import bootstrap_admin, login  # noqa: E402
from schemas.users import BootstrapAdminRequest, LoginRequest  # noqa: E402
from services import totp  # noqa: E402
from services.account_recovery import generate_recovery_codes  # noqa: E402
from services.auth import hash_password  # noqa: E402


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _fake_request(host: str = "127.0.0.1") -> _StarletteRequest:
    """Minimaler ASGI-Scope -- reicht fuer _extract_client_ip() (liest nur
    request.headers/request.client.host, siehe routers/auth.py)."""
    scope = {
        "type": "http", "method": "POST", "path": "/",
        "headers": [], "client": (host, 12345),
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
    db_url = f"sqlite:///{tmp_path / 'authten08_teil2.db'}"
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
# 1. Bootstrap-Admin -- DB-seitiger Singleton (mehrere Worker-Prozesse)
# ---------------------------------------------------------------------------

def test_concurrent_bootstrap_across_simulated_processes_creates_exactly_one_admin(
    session_factory, monkeypatch,
):
    """Der bestehende In-Prozess-Lock (_bootstrap_admin_lock) wird hier
    bewusst durch ein No-op ersetzt -- das simuliert exakt das Szenario, vor
    dem der urspruengliche Kommentar warnte: mehrere Backend-Worker-Prozesse
    haetten JEWEILS ihren eigenen (leeren) Lock und koennten sich damit
    gegenseitig NICHT serialisieren. Ohne den neuen DB-seitigen Singleton
    (models/bootstrap_lock.py) waere das hier reproduzierbar zwei "erste"
    Admins. Mit ihm muss trotz fehlendem Prozess-Lock exakt ein Gewinner
    entstehen -- der DB-Constraint alleine traegt die Garantie."""
    monkeypatch.setattr(auth_router, "_bootstrap_admin_lock", contextlib.nullcontext())

    SF = session_factory
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def _attempt(username, host):
        barrier.wait(timeout=5)
        with SF() as db:
            body = BootstrapAdminRequest(username=username, password="pw12345678", full_name="Root")
            try:
                bootstrap_admin(body, _fake_request(host), db=db)
                with lock:
                    outcomes.append("201")
            except HTTPException as exc:
                with lock:
                    outcomes.append(str(exc.status_code))

    t1 = threading.Thread(target=_attempt, args=("root_proc_a", "10.2.1.1"))
    t2 = threading.Thread(target=_attempt, args=("root_proc_b", "10.2.1.2"))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert sorted(outcomes) == ["201", "409"], outcomes

    with SF() as db:
        admin_count = db.query(User).filter(User.role == "admin").count()
        assert admin_count == 1
        lock_rows = db.query(BootstrapLock).all()
        assert len(lock_rows) == 1
        assert lock_rows[0].id == "singleton"


def test_bootstrap_still_succeeds_normally_without_any_race(session_factory):
    """Tier-1-Regressions-Guard: der voellig normale Einzel-Request-Pfad
    (keine Konkurrenz) bleibt unveraendert -- ein Admin wird angelegt, die
    Singleton-Zeile existiert danach, ein zweiter Versuch bekommt weiterhin
    409 (nicht 500/IntegrityError-Leak)."""
    SF = session_factory
    with SF() as db:
        body = BootstrapAdminRequest(username="solo-admin", password="pw12345678", full_name="Solo")
        result = bootstrap_admin(body, _fake_request(), db=db)
        assert result.user.username == "solo-admin"

    with SF() as db:
        assert db.query(User).filter(User.role == "admin").count() == 1
        assert db.query(BootstrapLock).count() == 1

    with SF() as db:
        body2 = BootstrapAdminRequest(username="solo-admin-2", password="pw12345678", full_name="Solo2")
        with pytest.raises(HTTPException) as exc_info:
            bootstrap_admin(body2, _fake_request(), db=db)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# 2. TOTP-Login-Replay-Counter -- atomares CAS
# ---------------------------------------------------------------------------

def _seed_totp_user(SF, uid, password, secret):
    with SF() as s:
        s.add(User(
            id=uid, username=uid, password_hash=hash_password(password),
            full_name=uid, role="advisor", is_active=1,
            totp_secret=secret, totp_enabled=1,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def test_concurrent_totp_login_with_same_code_exactly_one_wins(session_factory):
    """Vorher: read-then-write auf dem ORM-Objekt -- zwei nahezu
    gleichzeitige Logins mit demselben (z.B. mitgelesenen) TOTP-Code
    konnten BEIDE die counter<=last-Pruefung bestehen, bevor irgendeiner
    committete, und wuerden den Code damit zweimal akzeptieren. Jetzt: genau
    EIN Login gewinnt, der andere bekommt den bestehenden 'bereits
    verwendet'-401."""
    SF = session_factory
    secret = totp.generate_secret()
    _seed_totp_user(SF, "totp-race-1", "pw12345678", secret)
    code = totp.totp_at(secret, time.time())

    barrier = threading.Barrier(2)
    results: list = []
    lock = threading.Lock()

    def _attempt(host):
        barrier.wait(timeout=5)
        with SF() as db:
            body = LoginRequest(username="totp-race-1", password="pw12345678", totp_code=code)
            try:
                login(body, _fake_request(host), db=db)
                with lock:
                    results.append("ok")
            except HTTPException as exc:
                with lock:
                    results.append(("http_error", exc.status_code))

    threads = [threading.Thread(target=_attempt, args=(f"10.3.1.{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 2
    assert results.count("ok") == 1, f"Erwartete genau 1 Gewinner, bekam: {results}"
    errors = [r for r in results if r != "ok"]
    assert len(errors) == 1
    assert errors[0] == ("http_error", 401)

    with SF() as db:
        row = db.query(User).filter_by(id="totp-race-1").first()
        expected_counter = int(time.time() // totp._PERIOD)
        assert row.totp_last_counter is not None
        # Zaehler ist genau einmal auf den aktuellen Zeitschritt gesetzt --
        # kein zweiter Login hat ihn nochmal (unnoetig) ueberschrieben.
        assert int(row.totp_last_counter) == expected_counter


def test_totp_login_normal_single_request_path_unchanged(session_factory):
    """Tier-1-Regressions-Guard: ein einzelner, unbestrittener Login mit
    gueltigem TOTP-Code funktioniert weiterhin wie zuvor."""
    SF = session_factory
    secret = totp.generate_secret()
    _seed_totp_user(SF, "totp-solo-1", "pw12345678", secret)
    code = totp.totp_at(secret, time.time())
    with SF() as db:
        body = LoginRequest(username="totp-solo-1", password="pw12345678", totp_code=code)
        result = login(body, _fake_request(), db=db)
        assert result.user.username == "totp-solo-1"

    # Replay desselben Codes bleibt abgelehnt (unveraendertes AUTH-06-Verhalten).
    with SF() as db:
        body2 = LoginRequest(username="totp-solo-1", password="pw12345678", totp_code=code)
        with pytest.raises(HTTPException) as exc_info:
            login(body2, _fake_request(), db=db)
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# 3. 2FA-Recovery-Codes -- atomares CAS auf dem JSON-Blob
# ---------------------------------------------------------------------------

def _seed_recovery_user(SF, uid, password, secret, codes_blob):
    with SF() as s:
        s.add(User(
            id=uid, username=uid, password_hash=hash_password(password),
            full_name=uid, role="advisor", is_active=1,
            totp_secret=secret, totp_enabled=1, totp_recovery_codes=codes_blob,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def test_concurrent_recovery_code_login_with_same_code_exactly_one_wins(session_factory):
    """Vorher: read-then-write auf dem ORM-Objekt -- zwei nahezu
    gleichzeitige Logins mit demselben Recovery-Code konnten BEIDE den Hash
    im geladenen Blob finden, bevor irgendeiner committete, und den Code
    damit zweimal akzeptieren (der zuletzt committende Request haette den
    Verbrauch des anderen sogar unbemerkt ueberschrieben)."""
    SF = session_factory
    secret = totp.generate_secret()
    codes, blob = generate_recovery_codes(n=3)
    _seed_recovery_user(SF, "rec-race-1", "pw12345678", secret, blob)
    same_code = codes[0]

    barrier = threading.Barrier(2)
    results: list = []
    lock = threading.Lock()

    def _attempt(host):
        barrier.wait(timeout=5)
        with SF() as db:
            body = LoginRequest(username="rec-race-1", password="pw12345678", totp_code=same_code)
            try:
                login(body, _fake_request(host), db=db)
                with lock:
                    results.append("ok")
            except HTTPException as exc:
                with lock:
                    results.append(("http_error", exc.status_code))

    threads = [threading.Thread(target=_attempt, args=(f"10.4.1.{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 2
    assert results.count("ok") == 1, f"Erwartete genau 1 Gewinner, bekam: {results}"
    errors = [r for r in results if r != "ok"]
    assert len(errors) == 1
    assert errors[0] == ("http_error", 401)

    with SF() as db:
        import json
        row = db.query(User).filter_by(id="rec-race-1").first()
        remaining = json.loads(row.totp_recovery_codes)
        # Genau EIN Code verbraucht (nicht zwei, nicht null).
        assert len(remaining) == 2


def test_concurrent_recovery_code_login_with_different_codes_both_succeed(session_factory):
    """Der Retry-Loop in consume_recovery_code() darf legitime parallele
    Verbraeuche ZWEIER VERSCHIEDENER Backup-Codes nicht faelschlich
    ablehnen -- nur derselbe Code doppelt verwendet ist der eigentliche
    Race, den dieser Fix verhindern soll."""
    SF = session_factory
    secret = totp.generate_secret()
    codes, blob = generate_recovery_codes(n=3)
    _seed_recovery_user(SF, "rec-race-2", "pw12345678", secret, blob)

    barrier = threading.Barrier(2)
    results: list = []
    lock = threading.Lock()

    def _attempt(code, host):
        barrier.wait(timeout=5)
        with SF() as db:
            body = LoginRequest(username="rec-race-2", password="pw12345678", totp_code=code)
            try:
                login(body, _fake_request(host), db=db)
                with lock:
                    results.append("ok")
            except HTTPException as exc:
                with lock:
                    results.append(("http_error", exc.status_code))

    t1 = threading.Thread(target=_attempt, args=(codes[0], "10.4.2.1"))
    t2 = threading.Thread(target=_attempt, args=(codes[1], "10.4.2.2"))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert results.count("ok") == 2, f"Erwartete 2 legitime Erfolge, bekam: {results}"

    with SF() as db:
        import json
        row = db.query(User).filter_by(id="rec-race-2").first()
        remaining = json.loads(row.totp_recovery_codes)
        assert len(remaining) == 1


def test_recovery_code_login_normal_single_request_path_unchanged(session_factory):
    """Tier-1-Regressions-Guard: ein einzelner, unbestrittener Login mit
    einem gueltigen Recovery-Code funktioniert weiterhin wie zuvor und
    verbraucht genau diesen einen Code."""
    SF = session_factory
    secret = totp.generate_secret()
    codes, blob = generate_recovery_codes(n=2)
    _seed_recovery_user(SF, "rec-solo-1", "pw12345678", secret, blob)

    with SF() as db:
        body = LoginRequest(username="rec-solo-1", password="pw12345678", totp_code=codes[0])
        result = login(body, _fake_request(), db=db)
        assert result.user.username == "rec-solo-1"

    with SF() as db:
        import json
        row = db.query(User).filter_by(id="rec-solo-1").first()
        remaining = json.loads(row.totp_recovery_codes)
        assert len(remaining) == 1

    # Derselbe Code kann nicht erneut verwendet werden (weiterhin Single-Use).
    with SF() as db:
        body2 = LoginRequest(username="rec-solo-1", password="pw12345678", totp_code=codes[0])
        with pytest.raises(HTTPException) as exc_info:
            login(body2, _fake_request(), db=db)
        assert exc_info.value.status_code == 401
