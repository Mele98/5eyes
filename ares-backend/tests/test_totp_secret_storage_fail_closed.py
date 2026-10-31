"""AUDIT-FIX 2026-10-23: TOTP-Secret-Speicher fail-closed.

Vorher (services/totp_secret_storage.py):
- Schreibpfad: jeder Crypto-Fehler -> stiller Klartext-Fallback (gemischter
  Bestand aus Klartext- und `enc1:`-Zeilen).
- Lesepfad: `enc1:`-Wert nicht entschluesselbar (z.B. falscher KEK) -> still
  "" -> 2FA-Lockout ohne jede Diagnose.

Nachher:
- Schreibfehler -> `TotpSecretStorageError`, nichts wird gespeichert,
  /auth/2fa/setup antwortet 503 mit verstaendlicher Meldung.
- Lesefehler -> `TotpSecretStorageError`, Login/Enable/Disable antworten 503
  (kein Code wird akzeptiert); Recovery-Codes bleiben beim Login nutzbar.
- Legacy-Klartext (ohne `enc1:`) bleibt unveraendert lesbar.
"""
from __future__ import annotations

import datetime
import logging
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pytest.importorskip("cryptography.fernet")
from cryptography.fernet import Fernet  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from services import totp  # noqa: E402
from services.auth import hash_password  # noqa: E402
from services.tenant_crypto import TenantCryptoError  # noqa: E402
import services.totp_secret_storage as storage_mod  # noqa: E402
from services.totp_secret_storage import (  # noqa: E402
    REASON_DECRYPT_FAILED,
    REASON_ENCRYPT_FAILED,
    REASON_TENANT_MISSING,
    TotpSecretStorageError,
    _ENC_PREFIX,
    load_totp_secret,
    store_totp_secret,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'totp_fail_closed.db'}",
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
    from services.login_guard import login_attempt_guard
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()
    yield
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()


@pytest.fixture()
def kek_a(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("TENANT_MASTER_KEK", key)
    return key


def _seed_tenant(db, tenant_id):
    db.add(Tenant(
        id=tenant_id, display_name=tenant_id, slug=tenant_id.lower(),
        hosting_tier="tier2", license_status="active", max_users=10,
        is_active=1, created_at=_now(), updated_at=_now(),
    ))
    db.commit()


def _seed_user(db, uid, *, tenant_id=None, password="pw", totp_secret=None,
               totp_enabled=0, recovery_blob=None):
    user = User(
        id=uid, username=uid, password_hash=hash_password(password),
        full_name=uid, role="advisor", is_active=1, tenant_id=tenant_id,
        totp_secret=totp_secret, totp_enabled=totp_enabled,
        created_at=_now(), updated_at=_now(),
    )
    if recovery_blob is not None:
        user.totp_recovery_codes = recovery_blob
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def client(session_factory):
    from fastapi.testclient import TestClient

    def override_db():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _bearer(client, uid, password="pw"):
    r = client.post("/auth/login", json={"username": uid, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Service-Ebene
# ---------------------------------------------------------------------------

def test_store_raises_typed_error_instead_of_plaintext_on_crypto_failure(session_factory, monkeypatch):
    def _boom(*_a, **_kw):
        raise TenantCryptoError("simulierter Verschluesselungsfehler")

    monkeypatch.setattr(storage_mod, "encrypt_for_tenant", _boom)
    with session_factory() as db:
        _seed_tenant(db, "firm-W1")
        user = _seed_user(db, "w1", tenant_id="firm-W1")
        secret = totp.generate_secret()
        with pytest.raises(TotpSecretStorageError) as info:
            store_totp_secret(db, user, secret)
        assert info.value.reason_code == REASON_ENCRYPT_FAILED
        assert secret not in str(info.value)


def test_store_raises_when_tenant_row_missing(session_factory, kek_a):
    with session_factory() as db:
        user = _seed_user(db, "w2", tenant_id="ghost-tenant")
        with pytest.raises(TotpSecretStorageError) as info:
            store_totp_secret(db, user, totp.generate_secret())
        assert info.value.reason_code == REASON_ENCRYPT_FAILED


def test_load_with_wrong_kek_raises_instead_of_empty_string(session_factory, monkeypatch, kek_a, caplog):
    with session_factory() as db:
        _seed_tenant(db, "firm-R1")
        user = _seed_user(db, "r1", tenant_id="firm-R1")
        secret = totp.generate_secret()
        user.totp_secret = store_totp_secret(db, user, secret)
        db.commit()
        assert user.totp_secret.startswith(_ENC_PREFIX)
        ciphertext = user.totp_secret

        monkeypatch.setenv("TENANT_MASTER_KEK", Fernet.generate_key().decode("ascii"))
        with caplog.at_level(logging.ERROR, logger="services.totp_secret_storage"):
            with pytest.raises(TotpSecretStorageError) as info:
                load_totp_secret(db, user)
        assert info.value.reason_code == REASON_DECRYPT_FAILED
        assert secret not in caplog.text
        assert ciphertext[len(_ENC_PREFIX):] not in caplog.text
        assert REASON_DECRYPT_FAILED in caplog.text


def test_load_with_enc_prefix_but_no_tenant_id_raises(session_factory):
    with session_factory() as db:
        user = _seed_user(db, "r2", tenant_id=None)
        user.totp_secret = _ENC_PREFIX + "whatever"
        with pytest.raises(TotpSecretStorageError) as info:
            load_totp_secret(db, user)
        assert info.value.reason_code == REASON_TENANT_MISSING


def test_positive_control_correct_kek_roundtrips_and_verifies(session_factory, kek_a):
    with session_factory() as db:
        _seed_tenant(db, "firm-P1")
        user = _seed_user(db, "p1", tenant_id="firm-P1")
        secret = totp.generate_secret()
        user.totp_secret = store_totp_secret(db, user, secret)
        db.commit()
        assert user.totp_secret.startswith(_ENC_PREFIX)
        decrypted = load_totp_secret(db, user)
        assert decrypted == secret
        assert totp.verify(decrypted, totp.totp_at(secret, time.time())) is True


def test_legacy_plaintext_without_prefix_still_readable(session_factory, kek_a):
    with session_factory() as db:
        _seed_tenant(db, "firm-L1")
        legacy = totp.generate_secret()
        user = _seed_user(db, "l1", tenant_id="firm-L1", totp_secret=legacy)
        assert load_totp_secret(db, user) == legacy
        user.totp_secret = None
        assert load_totp_secret(db, user) == ""


# ---------------------------------------------------------------------------
# HTTP-Ebene
# ---------------------------------------------------------------------------

def test_setup_endpoint_returns_503_and_persists_nothing_on_encrypt_failure(client, session_factory, monkeypatch):
    with session_factory() as db:
        _seed_tenant(db, "firm-H1")
        _seed_user(db, "h1", tenant_id="firm-H1")
    headers = _bearer(client, "h1")

    def _boom(*_a, **_kw):
        raise TenantCryptoError("simulierter Verschluesselungsfehler")

    monkeypatch.setattr(storage_mod, "encrypt_for_tenant", _boom)
    r = client.post("/auth/2fa/setup", headers=headers)
    assert r.status_code == 503, r.text
    assert "Schluesselkonfiguration" in r.json()["detail"]
    assert r.headers.get("X-2FA-Error") == REASON_ENCRYPT_FAILED
    assert "secret" not in r.json()
    with session_factory() as db:
        assert db.get(User, "h1").totp_secret is None


def _seed_corrupt_2fa_user(session_factory, uid, tenant_id, *, recovery_blob=None):
    with session_factory() as db:
        _seed_tenant(db, tenant_id)
        _seed_user(
            db, uid, tenant_id=tenant_id, totp_enabled=1,
            totp_secret=_ENC_PREFIX + "corrupted-ciphertext-not-valid-fernet",
            recovery_blob=recovery_blob,
        )


def test_login_with_corrupt_enc_secret_returns_clear_error_and_no_token(client, session_factory, kek_a):
    _seed_corrupt_2fa_user(session_factory, "h2", "firm-H2")
    r = client.post(
        "/auth/login",
        json={"username": "h2", "password": "pw", "totp_code": "123456"},
    )
    assert r.status_code == 503, r.text
    assert "access_token" not in r.json()
    assert "Schluesselkonfiguration" in r.json()["detail"]
    assert r.headers.get("X-2FA-Error") == REASON_DECRYPT_FAILED


def test_login_with_wrong_kek_rejects_otherwise_valid_code(client, session_factory, monkeypatch, kek_a):
    with session_factory() as db:
        _seed_tenant(db, "firm-H3")
        user = _seed_user(db, "h3", tenant_id="firm-H3")
        secret = totp.generate_secret()
        user.totp_secret = store_totp_secret(db, user, secret)
        user.totp_enabled = 1
        db.commit()

    monkeypatch.setenv("TENANT_MASTER_KEK", Fernet.generate_key().decode("ascii"))
    r = client.post(
        "/auth/login",
        json={"username": "h3", "password": "pw", "totp_code": totp.totp_at(secret, time.time())},
    )
    assert r.status_code == 503, r.text
    assert "access_token" not in r.json()


def test_login_recovery_code_still_works_when_secret_unreadable(client, session_factory, kek_a):
    from services.account_recovery import generate_recovery_codes

    codes, blob = generate_recovery_codes()
    _seed_corrupt_2fa_user(session_factory, "h4", "firm-H4", recovery_blob=blob)
    r = client.post(
        "/auth/login",
        json={"username": "h4", "password": "pw", "totp_code": codes[0]},
    )
    assert r.status_code == 200, r.text
    assert "access_token" in r.json()


def test_disable_with_corrupt_enc_secret_returns_503_and_keeps_2fa(client, session_factory, kek_a):
    from services.account_recovery import generate_recovery_codes

    codes, blob = generate_recovery_codes()
    _seed_corrupt_2fa_user(session_factory, "h5", "firm-H5", recovery_blob=blob)
    login = client.post(
        "/auth/login",
        json={"username": "h5", "password": "pw", "totp_code": codes[0]},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = client.post("/auth/2fa/disable", json={"code": "123456"}, headers=headers)
    assert r.status_code == 503, r.text
    with session_factory() as db:
        row = db.get(User, "h5")
        assert row.totp_enabled == 1
        assert row.totp_secret.startswith(_ENC_PREFIX)


def test_enable_with_corrupt_enc_secret_returns_503_and_stays_disabled(client, session_factory, kek_a):
    with session_factory() as db:
        _seed_tenant(db, "firm-H6")
        _seed_user(
            db, "h6", tenant_id="firm-H6", totp_enabled=0,
            totp_secret=_ENC_PREFIX + "corrupted-ciphertext-not-valid-fernet",
        )
    headers = _bearer(client, "h6")
    r = client.post("/auth/2fa/enable", json={"code": "123456"}, headers=headers)
    assert r.status_code == 503, r.text
    with session_factory() as db:
        assert db.get(User, "h6").totp_enabled == 0
