"""Kontrollrunde 2026-09-21 (Password-Audit-Nachtrag): lazy Rehash-on-
Auth. services/password_audit.py existierte bereits seit Sprint U-57
(needs_rehash/get_bcrypt_rounds/audit_user_password_strength), war aber
nie in den Login-Pfad (routers/auth.py::login) verdrahtet -- ein mit
niedrigeren bcrypt-rounds erstellter Hash (Alt-Import, oder ein
kuenftig gesenkter BCRYPT_TARGET_ROUNDS-Verstoss) wurde nie erneuert.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import bcrypt
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
from services.password_audit import BCRYPT_TARGET_ROUNDS, get_bcrypt_rounds


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_login_rehash.db'}",
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
    from services.login_guard import login_attempt_guard
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()
    yield
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()


def _low_cost_hash(password: str, rounds: int = 4) -> str:
    """Bcrypt-Minimum ist rounds=4 (schnell fuer Tests) -- unterhalb von
    BCRYPT_TARGET_ROUNDS=12, damit needs_rehash() greift."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("utf-8")


def _seed_user(SF, uid, password_hash):
    with SF() as s:
        s.add(User(
            id=uid, username=uid, password_hash=password_hash,
            full_name=uid, role="advisor", is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()


def test_login_with_low_cost_hash_upgrades_it_transparently(client, session_factory):
    """BUG (vor Fix): needs_rehash() existierte, wurde aber nie aufgerufen --
    ein Alt-Hash mit rounds=4 blieb fuer immer bei rounds=4."""
    low_hash = _low_cost_hash("correcthorsebatterystaple")
    assert get_bcrypt_rounds(low_hash) == 4
    _seed_user(session_factory, "rehash-u1", low_hash)

    r = client.post("/auth/login", json={"username": "rehash-u1", "password": "correcthorsebatterystaple"})
    assert r.status_code == 200
    assert "access_token" in r.json()

    with session_factory() as s:
        user = s.query(User).filter_by(id="rehash-u1").first()
        assert get_bcrypt_rounds(user.password_hash) == BCRYPT_TARGET_ROUNDS
        assert user.password_hash != low_hash


def test_login_with_low_cost_hash_still_works_after_upgrade(client, session_factory):
    """Regression-Guard: der rehashte Wert authentifiziert weiterhin
    korrekt mit demselben Klartext-Passwort (kein Passwort-Bruch)."""
    low_hash = _low_cost_hash("correcthorsebatterystaple")
    _seed_user(session_factory, "rehash-u2", low_hash)

    first = client.post("/auth/login", json={"username": "rehash-u2", "password": "correcthorsebatterystaple"})
    assert first.status_code == 200

    second = client.post("/auth/login", json={"username": "rehash-u2", "password": "correcthorsebatterystaple"})
    assert second.status_code == 200
    assert "access_token" in second.json()


def test_login_with_wrong_password_does_not_touch_hash(client, session_factory):
    """Kein False-Positive: eine fehlgeschlagene Passwort-Pruefung darf den
    gespeicherten Hash nicht veraendern (Rehash braucht das bestaetigte
    Klartext-Passwort, nicht nur den Versuch)."""
    low_hash = _low_cost_hash("correcthorsebatterystaple")
    _seed_user(session_factory, "rehash-u3", low_hash)

    r = client.post("/auth/login", json={"username": "rehash-u3", "password": "wrong-password"})
    assert r.status_code == 401

    with session_factory() as s:
        user = s.query(User).filter_by(id="rehash-u3").first()
        assert user.password_hash == low_hash
        assert get_bcrypt_rounds(user.password_hash) == 4


def test_login_with_already_current_hash_is_not_rewritten(client, session_factory):
    """Kein unnoetiger Rehash: ein bereits auf Ziel-rounds erstellter Hash
    (der Normalfall, jeder neu erstellte User via hash_password()) bleibt
    beim Login unveraendert."""
    good_hash = hash_password("correcthorsebatterystaple")
    assert get_bcrypt_rounds(good_hash) == BCRYPT_TARGET_ROUNDS
    _seed_user(session_factory, "rehash-u4", good_hash)

    r = client.post("/auth/login", json={"username": "rehash-u4", "password": "correcthorsebatterystaple"})
    assert r.status_code == 200

    with session_factory() as s:
        user = s.query(User).filter_by(id="rehash-u4").first()
        assert user.password_hash == good_hash
