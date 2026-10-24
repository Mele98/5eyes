"""AUTH-06 (2026-07-22): TOTP-Login-Verify hatte keinen Anti-Replay-Schutz —
services/totp.verify() prueft nur, ob ein Code zum aktuellen Zeitfenster passt,
nicht ob er bereits verwendet wurde. Ein mitgelesener (z.B. per Shoulder-Surfing
oder Netzwerk-Sniffing) Code war beliebig oft im selben 30s-Zeitfenster
wiederverwendbar. Fix: User.totp_last_counter haelt den zuletzt akzeptierten
HOTP-Zeitschritt fest; ein zweiter Login-Versuch mit Code aus demselben oder
einem frueheren Zeitschritt wird abgelehnt. services/totp.py bleibt
unveraendert — die Speicherung/Pruefung lebt im Login-Flow (routers/auth.py)."""
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
        f"sqlite:///{tmp_path / 'test_auth06.db'}",
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
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()
    yield
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()


def _seed_user(SF, uid, password, totp_secret, totp_enabled=1):
    with SF() as s:
        s.add(User(
            id=uid, username=uid, password_hash=hash_password(password),
            full_name=uid, role="advisor", is_active=1,
            totp_secret=totp_secret, totp_enabled=totp_enabled,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def test_totp_code_reuse_is_rejected_on_second_login(client, session_factory):
    secret = totp.generate_secret()
    _seed_user(session_factory, "auth06-u1", "pw", secret)
    code = totp.totp_at(secret, time.time())

    first = client.post("/auth/login", json={
        "username": "auth06-u1", "password": "pw", "totp_code": code,
    })
    assert first.status_code == 200
    assert "access_token" in first.json()

    second = client.post("/auth/login", json={
        "username": "auth06-u1", "password": "pw", "totp_code": code,
    })
    assert second.status_code == 401
    assert "verwendet" in second.json()["detail"]


def test_totp_reuse_rejected_even_with_multiple_replay_attempts(client, session_factory):
    """Nicht nur der ZWEITE Versuch — jeder weitere Replay desselben Codes
    bleibt abgelehnt (kein Off-by-one, der Zaehler bleibt monoton)."""
    secret = totp.generate_secret()
    _seed_user(session_factory, "auth06-u3", "pw", secret)
    code = totp.totp_at(secret, time.time())

    assert client.post("/auth/login", json={
        "username": "auth06-u3", "password": "pw", "totp_code": code,
    }).status_code == 200
    for _ in range(3):
        r = client.post("/auth/login", json={
            "username": "auth06-u3", "password": "pw", "totp_code": code,
        })
        assert r.status_code == 401


def test_totp_next_time_step_code_still_accepted(client, session_factory, monkeypatch):
    """Regression-Guard: ein GUELTIGER, NEUER Code (naechster Zeitschritt)
    darf durch die Anti-Replay-Logik nicht blockiert werden. Server-'now' wird
    via monkeypatch vorgespult, damit der Test nicht real 30s warten muss —
    sowohl totp_verify (Standard: time.time()) als auch der Replay-Guard sehen
    dieselbe vorgespulte Zeit."""
    secret = totp.generate_secret()
    _seed_user(session_factory, "auth06-u2", "pw", secret)
    base_t = time.time()
    code_now = totp.totp_at(secret, base_t)
    first = client.post("/auth/login", json={
        "username": "auth06-u2", "password": "pw", "totp_code": code_now,
    })
    assert first.status_code == 200

    future_t = base_t + 31  # sicher im naechsten Zeitschritt (Periode = 30s)
    monkeypatch.setattr(time, "time", lambda: future_t)
    code_next = totp.totp_at(secret, future_t)
    second = client.post("/auth/login", json={
        "username": "auth06-u2", "password": "pw", "totp_code": code_next,
    })
    assert second.status_code == 200


# FLAKE-TOTP-BOUNDARY (2026-10-18): der Test nahm base_t = time.time() (echte
# Uhr) und spulte fuer den Replay auf base_t + 31 vor. Lag base_t in den
# letzten Sekunde eines 30s-Zeitschritts N (Offset >= 29s, ~1/30 der Laeufe),
# landete base_t + 31 in Schritt N+2 -- ausserhalb der +/-1-Toleranz. Der Code
# war dann schlicht abgelaufen, verify() lehnte ihn ab und die Antwort war
# korrekt "2FA-Code falsch" statt der erwarteten Replay-Meldung (CI-Run
# 39077084567). Jetzt wird die Zeit fuer BEIDE Requests eingefroren und der
# Replay-Zeitpunkt deterministisch in Schritt N+1 gelegt, fuer jeden Offset im
# Fenster -- inklusive der frueher fehlschlagenden Offsets >= 29s.
_WINDOW_OFFSETS = [0.0, 0.001, 1.0, 14.5, 28.999, 29.0, 29.5, 29.999]


def _window_anchor() -> int:
    """Start eines realen 30s-Zeitschritts (nahe 'jetzt', damit Token-
    Zeitstempel plausibel bleiben) -- deterministischer Bezugspunkt."""
    return (int(time.time()) // totp._PERIOD) * totp._PERIOD


@pytest.mark.parametrize("offset", _WINDOW_OFFSETS)
def test_totp_same_code_rejected_across_window_boundary_within_tolerance(
    client, session_factory, monkeypatch, offset,
):
    """SEC-TOTP-REPLAY-WINDOW (2026-09-15): reproduziert die Luecke direkt.
    Ein Code, der fuer Zeitschritt N generiert wurde, ist dank der +/-1-Drift-
    Toleranz in services/totp.py::verify() bei Server-Zeitschritt N+1 immer
    noch kryptografisch gueltig. Vorher liess die reine Zaehler-Monotonie
    (last(N) < N+1) den woertlich IDENTISCHEN Code in diesem Fall faelschlich
    ein zweites Mal durch. Derselbe Code muss abgelehnt bleiben, unabhaengig
    vom fortgeschrittenen Zeitfenster."""
    secret = totp.generate_secret()
    _seed_user(session_factory, "auth06-u5", "pw", secret)
    base_t = _window_anchor() + offset
    step_n = int(base_t // totp._PERIOD)
    monkeypatch.setattr(time, "time", lambda: base_t)
    code = totp.totp_at(secret, base_t)

    first = client.post("/auth/login", json={
        "username": "auth06-u5", "password": "pw", "totp_code": code,
    })
    assert first.status_code == 200

    # Replay-Zeitpunkt: gleicher Offset, aber genau ein Zeitschritt spaeter
    # (N+1) -- nie N+2, egal wo im Fenster base_t lag.
    future_t = base_t + totp._PERIOD
    assert int(future_t // totp._PERIOD) == step_n + 1
    # Positivkontrolle: der Code ist bei N+1 kryptografisch NOCH gueltig --
    # sonst waere ein 401 "falsch" kein Beleg fuer den Replay-Guard.
    assert totp.verify(secret, code, future_t) is True
    monkeypatch.setattr(time, "time", lambda: future_t)

    replay = client.post("/auth/login", json={
        "username": "auth06-u5", "password": "pw", "totp_code": code,
    })
    assert replay.status_code == 401
    assert "verwendet" in replay.json()["detail"]


def test_totp_replay_rejected_after_intervening_login_with_clock_skew(
    client, session_factory, monkeypatch,
):
    """SEC-TOTP-REPLAY-STEP (2026-10-18): der Guard speicherte den Server-
    Zeitschritt statt des Code-Zeitschritts. Szenario (Client-Uhr ~30s vor):
    Code X (Schritt s) wird bei Server-Schritt s-1 akzeptiert, ein anderer
    Code Y bei Server-Schritt s, dann wird X bei Server-Schritt s+1 erneut
    vorgelegt -- X ist dort dank w=-1 noch gueltig, last(s) < s+1 und
    Hash(X) != Hash(Y). Vor dem Fix: 200 (Replay ging durch)."""
    secret = totp.generate_secret()
    _seed_user(session_factory, "auth06-u6", "pw", secret)
    s = _window_anchor() // totp._PERIOD
    code_x = totp._hotp(secret, s)
    code_y = totp._hotp(secret, s + 1)
    assert code_x != code_y

    def _login_at(step, code):
        t = step * totp._PERIOD + 10
        monkeypatch.setattr(time, "time", lambda: t)
        return client.post("/auth/login", json={
            "username": "auth06-u6", "password": "pw", "totp_code": code,
        })

    assert _login_at(s - 1, code_x).status_code == 200
    assert _login_at(s, code_y).status_code == 200
    # Positivkontrolle: X ist bei Server-Schritt s+1 kryptografisch gueltig.
    assert totp.verify(secret, code_x, (s + 1) * totp._PERIOD + 10) is True
    replay = _login_at(s + 1, code_x)
    assert replay.status_code == 401
    assert "verwendet" in replay.json()["detail"]


def test_totp_fresh_next_step_code_accepted_within_same_server_step(
    client, session_factory, monkeypatch,
):
    """SEC-TOTP-REPLAY-STEP Nebeneffekt: ein neuer, nie benutzter Code des
    naechsten Schritts (Authenticator schon umgesprungen, Server-Uhr noch
    nicht) wurde vorher als 'bereits verwendet' verworfen, weil der Server-
    Zeitschritt sich nicht geaendert hatte. Massgeblich ist der Code-Schritt."""
    secret = totp.generate_secret()
    _seed_user(session_factory, "auth06-u7", "pw", secret)
    t = _window_anchor() + 20
    s = int(t // totp._PERIOD)
    monkeypatch.setattr(time, "time", lambda: t)
    assert client.post("/auth/login", json={
        "username": "auth06-u7", "password": "pw", "totp_code": totp._hotp(secret, s),
    }).status_code == 200
    r = client.post("/auth/login", json={
        "username": "auth06-u7", "password": "pw", "totp_code": totp._hotp(secret, s + 1),
    })
    assert r.status_code == 200


def test_recovery_code_login_unaffected_by_totp_replay_guard(client, session_factory):
    """Recovery-Codes laufen ueber einen eigenen Single-Use-Mechanismus
    (consume_recovery_code) — die TOTP-Counter-Pruefung darf diesen Pfad
    nicht betreffen/blockieren."""
    from services.account_recovery import generate_recovery_codes, ensure_account_recovery_columns
    import json as _json

    secret = totp.generate_secret()
    _seed_user(session_factory, "auth06-u4", "pw", secret)
    codes, blob = generate_recovery_codes(n=2)
    with session_factory() as s:
        ensure_account_recovery_columns(s)
        u = s.query(User).filter_by(id="auth06-u4").first()
        u.totp_recovery_codes = blob
        s.commit()

    r = client.post("/auth/login", json={
        "username": "auth06-u4", "password": "pw", "totp_code": codes[0],
    })
    assert r.status_code == 200
