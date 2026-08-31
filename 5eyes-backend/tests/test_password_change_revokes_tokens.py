"""2026-07-25 (Generalaudit): Passwort-Aenderungen (Self-Service via
/auth/change-password UND /users/{id}/password fuer Self+Admin-Reset)
setzten bisher NIE token_revoked_before -- ein bereits gestohlenes/
kompromittiertes Token blieb bis zu 8h (Access-Token-TTL) gueltig, selbst
NACH einem Passwortwechsel. Genau der Fall, den ein Passwortwechsel
eigentlich sofort beenden soll (analog zum bereits gefixten AUTH-04 Logout).
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


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_pw_revoke.db'}",
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


def _seed_user(SF, uid, password, role="advisor", must_change_password=0):
    with SF() as s:
        s.add(User(
            id=uid, username=uid, password_hash=hash_password(password),
            full_name=uid, role=role, is_active=1,
            must_change_password=must_change_password,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def test_self_service_change_password_revokes_old_token(client, session_factory):
    _seed_user(session_factory, "pwrevoke-u1", "old-pw-12345")
    login = client.post("/auth/login", json={"username": "pwrevoke-u1", "password": "old-pw-12345"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/auth/me", headers=headers).status_code == 200

    resp = client.post(
        "/auth/change-password",
        json={"current_password": "old-pw-12345", "new_password": "new-pw-67890"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # Das VOR der Aenderung ausgestellte Token muss jetzt abgelehnt werden.
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_fresh_login_after_password_change_still_works(client, session_factory):
    _seed_user(session_factory, "pwrevoke-u2", "old-pw-12345")
    login1 = client.post("/auth/login", json={"username": "pwrevoke-u2", "password": "old-pw-12345"})
    token1 = login1.json()["access_token"]
    client.post(
        "/auth/change-password",
        json={"current_password": "old-pw-12345", "new_password": "new-pw-67890"},
        headers={"Authorization": f"Bearer {token1}"},
    )
    time.sleep(1.1)  # JWT 'iat' hat Sekunden-Aufloesung, siehe test_auth04.

    login2 = client.post("/auth/login", json={"username": "pwrevoke-u2", "password": "new-pw-67890"})
    assert login2.status_code == 200
    token2 = login2.json()["access_token"]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token2}"}).status_code == 200


def test_self_service_password_reset_revokes_old_token(client, session_factory):
    """PUT /users/{id}/password, Self-Service-Zweig (is_self=True)."""
    _seed_user(session_factory, "pwrevoke-u3", "old-pw-12345")
    login = client.post("/auth/login", json={"username": "pwrevoke-u3", "password": "old-pw-12345"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/auth/me", headers=headers).status_code == 200

    resp = client.put(
        "/users/pwrevoke-u3/password",
        json={"new_password": "brandnew-pw-999"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_admin_reset_revokes_target_users_token(client, session_factory):
    """PUT /users/{id}/password, Admin-Reset-Zweig -- das Token des ZIELS
    (nicht des Admins) muss widerrufen werden (Account-Takeover-Szenario:
    Admin setzt ein neues Passwort, weil der alte Zugang kompromittiert war)."""
    _seed_user(session_factory, "pwrevoke-admin", "admin-pw-12345", role="admin")
    _seed_user(session_factory, "pwrevoke-target", "target-pw-12345")

    target_login = client.post("/auth/login", json={"username": "pwrevoke-target", "password": "target-pw-12345"})
    target_token = target_login.json()["access_token"]
    target_headers = {"Authorization": f"Bearer {target_token}"}
    assert client.get("/auth/me", headers=target_headers).status_code == 200

    admin_login = client.post("/auth/login", json={"username": "pwrevoke-admin", "password": "admin-pw-12345"})
    admin_token = admin_login.json()["access_token"]

    resp = client.put(
        "/users/pwrevoke-target/password",
        json={"new_password": "forced-new-pw-000"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text

    # Das alte Token des ZIELS ist jetzt tot -- der Angreifer (falls er es
    # gestohlen hatte) ist sofort ausgesperrt, nicht erst nach 8h.
    assert client.get("/auth/me", headers=target_headers).status_code == 401


def test_forced_first_time_change_does_not_revoke_own_token(client, session_factory):
    """Ausnahme (bewusst, Regressionsschutz fuer test_auth02_must_change_
    password.py::test_after_change_flag_cleared_and_access_restored): ein
    ERZWUNGENER Erst-Passwortwechsel (must_change_password=1, frisch
    eingeladener User) darf NICHT die eigene Session widerrufen -- das
    bestehende Onboarding-Frontend erwartet nahtlosen Weiterzugriff mit
    demselben Token direkt nach dem Wechsel."""
    _seed_user(session_factory, "pwrevoke-forced", "old-pw-12345", must_change_password=1)
    login = client.post("/auth/login", json={"username": "pwrevoke-forced", "password": "old-pw-12345"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/auth/change-password",
        json={"current_password": "old-pw-12345", "new_password": "new-pw-67890"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # Anders als bei einem REGULAEREN Wechsel: dasselbe Token bleibt gueltig.
    assert client.get("/auth/me", headers=headers).status_code == 200


def test_admin_reset_revokes_even_when_setting_must_change_flag(client, session_factory):
    """Die Ausnahme greift NUR fuer Self-Service -- der Admin-Reset-Zweig
    setzt must_change_password=1 fuer das Ziel (Zeile 'Admin-Reset -> Flag
    setzen'), MUSS aber trotzdem sofort widerrufen (Account-Takeover-Fall,
    siehe test_admin_reset_revokes_target_users_token)."""
    _seed_user(session_factory, "pwrevoke-admin2", "admin-pw-12345", role="admin")
    _seed_user(session_factory, "pwrevoke-target2", "target-pw-12345")

    target_login = client.post("/auth/login", json={"username": "pwrevoke-target2", "password": "target-pw-12345"})
    target_headers = {"Authorization": f"Bearer {target_login.json()['access_token']}"}
    admin_login = client.post("/auth/login", json={"username": "pwrevoke-admin2", "password": "admin-pw-12345"})
    admin_token = admin_login.json()["access_token"]

    resp = client.put(
        "/users/pwrevoke-target2/password",
        json={"new_password": "forced-new-pw-111"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert client.get("/auth/me", headers=target_headers).status_code == 401


# ── 2026-07-25 (Generalaudit, Wave 12): /auth/password-reset/confirm ────────
# Wave-12-Session-Concurrency-Fork-Fund: der oeffentliche Token-basierte
# Reset-Pfad revoked bisher KEINE Sessions -- anders als change_password und
# PUT /users/{id}/password oben. Reset ist der dedizierte Account-Recovery-
# Pfad; ohne Revocation bliebe ein bereits gestohlenes Token trotz Reset
# gueltig, genau der Angreifer bliebe drin, den der Reset aussperren soll.

def test_password_reset_confirm_revokes_old_token(client, session_factory):
    from services.account_recovery import issue_reset_token

    _seed_user(session_factory, "pwrevoke-reset1", "old-pw-12345")
    login = client.post("/auth/login", json={"username": "pwrevoke-reset1", "password": "old-pw-12345"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/auth/me", headers=headers).status_code == 200

    with session_factory() as s:
        u = s.query(User).filter_by(id="pwrevoke-reset1").first()
        reset_token = issue_reset_token(u)
        s.commit()

    resp = client.post(
        "/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "reset-new-pw-999"},
    )
    assert resp.status_code == 200, resp.text
    # Das VOR dem Reset ausgestellte Token muss jetzt abgelehnt werden.
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_fresh_login_after_password_reset_confirm_still_works(client, session_factory):
    from services.account_recovery import issue_reset_token

    _seed_user(session_factory, "pwrevoke-reset2", "old-pw-12345")
    with session_factory() as s:
        u = s.query(User).filter_by(id="pwrevoke-reset2").first()
        reset_token = issue_reset_token(u)
        s.commit()

    client.post(
        "/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "reset-new-pw-999"},
    )
    time.sleep(1.1)  # JWT 'iat' hat Sekunden-Aufloesung, siehe test_auth04.

    login2 = client.post("/auth/login", json={"username": "pwrevoke-reset2", "password": "reset-new-pw-999"})
    assert login2.status_code == 200
    token2 = login2.json()["access_token"]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token2}"}).status_code == 200


# ── AUTH-TEN-01 (Codex-Audit 2026-08-25): Refresh-Token-Familie ueberlebte
# bisher Reset/Legacy-Passwort-Aenderungen -- Wave 12 (Tests oben) widerrief
# nur Access-Tokens via token_revoked_before, NICHT die Refresh-Tokens via
# revoke_all_for_user(). Ein zuvor ausgestelltes Refresh-Token konnte damit
# nach jedem hier getesteten Reset weiterhin frische Access-Tokens holen --
# genau der Angreifer, den der Reset aussperren soll, waere ueber /auth/refresh
# weiter drin. Diese Tests decken den Refresh-Token-Widerruf zusaetzlich ab.

def test_password_reset_confirm_revokes_refresh_token(client, session_factory):
    from services.account_recovery import issue_reset_token

    _seed_user(session_factory, "pwrevoke-rt1", "old-pw-12345")
    login = client.post("/auth/login", json={"username": "pwrevoke-rt1", "password": "old-pw-12345"})
    refresh_token = login.json()["refresh_token"]
    assert refresh_token

    with session_factory() as s:
        u = s.query(User).filter_by(id="pwrevoke-rt1").first()
        reset_token = issue_reset_token(u)
        s.commit()

    resp = client.post(
        "/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "reset-new-pw-999"},
    )
    assert resp.status_code == 200, resp.text

    refresh_resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_resp.status_code == 401


def test_self_service_password_reset_revokes_refresh_token(client, session_factory):
    """PUT /users/{id}/password, Self-Service-Zweig (is_self=True)."""
    _seed_user(session_factory, "pwrevoke-rt2", "old-pw-12345")
    login = client.post("/auth/login", json={"username": "pwrevoke-rt2", "password": "old-pw-12345"})
    access_token = login.json()["access_token"]
    refresh_token = login.json()["refresh_token"]
    assert refresh_token

    resp = client.put(
        "/users/pwrevoke-rt2/password",
        json={"new_password": "brandnew-pw-999"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 200, resp.text

    refresh_resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_resp.status_code == 401


def test_admin_reset_revokes_target_users_refresh_token(client, session_factory):
    """Account-Takeover-Remediation-Fall: Admin setzt neues Passwort fuer
    einen (vermutlich kompromittierten) fremden User -- dessen Refresh-Token
    muss sofort sterben, nicht erst nach Ablauf der Refresh-Token-TTL."""
    _seed_user(session_factory, "pwrevoke-rt-admin", "admin-pw-12345", role="admin")
    _seed_user(session_factory, "pwrevoke-rt-target", "target-pw-12345")

    target_login = client.post(
        "/auth/login", json={"username": "pwrevoke-rt-target", "password": "target-pw-12345"},
    )
    target_refresh = target_login.json()["refresh_token"]
    assert target_refresh

    admin_login = client.post(
        "/auth/login", json={"username": "pwrevoke-rt-admin", "password": "admin-pw-12345"},
    )
    admin_token = admin_login.json()["access_token"]

    resp = client.put(
        "/users/pwrevoke-rt-target/password",
        json={"new_password": "forced-new-pw-000"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text

    refresh_resp = client.post("/auth/refresh", json={"refresh_token": target_refresh})
    assert refresh_resp.status_code == 401


def test_forced_first_time_change_does_not_revoke_own_refresh_token(client, session_factory):
    """Dieselbe Ausnahme wie bei Access-Tokens (siehe
    test_forced_first_time_change_does_not_revoke_own_token oben) muss auch
    fuer das Refresh-Token gelten -- sonst waere ein frisch eingeladener User
    nach dem erzwungenen Erstwechsel zwar mit dem Access-Token noch drin,
    verliert aber beim naechsten /auth/refresh unerwartet die Session."""
    _seed_user(session_factory, "pwrevoke-rt-forced", "old-pw-12345", must_change_password=1)
    login = client.post("/auth/login", json={"username": "pwrevoke-rt-forced", "password": "old-pw-12345"})
    access_token = login.json()["access_token"]
    refresh_token = login.json()["refresh_token"]

    resp = client.post(
        "/auth/change-password",
        json={"current_password": "old-pw-12345", "new_password": "new-pw-67890"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 200, resp.text

    refresh_resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_resp.status_code == 200
