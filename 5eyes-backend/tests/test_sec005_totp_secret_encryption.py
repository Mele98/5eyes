"""SEC-005 (Codex-Audit 2026-08-26, docs/audits/2026-08-26-data-lifecycle-
crypto-browser-followup-audit.md): `models/users.py::User.totp_secret`
speicherte den Base32-Seed IMMER im Klartext, obwohl `services/tenant_crypto.py`
fertige Envelope-Encryption-Helfer bereitstellt (die laut Audit nirgends fuer
echte Geschaeftsfelder verwendet wurden -- siehe auch
tests/test_landmine_functions_unused_guard.py).

Diese Tests decken die neue, opt-in Verschluesselung ueber
`services/totp_secret_storage.py` ab -- die weitergehenden Forderungen des
Audits (Key-Versionierung im Ciphertext, gestufte DEK-Rotation, HSM/Vault)
bleiben ein groesseres, separates Vorhaben und sind bewusst NICHT Teil
dieses Fixes.

Kernrisiko dieses Fixes: ein bestehender, real eingerichteter 2FA-Nutzer
darf NIEMALS durch diese Aenderung ausgesperrt werden. Mehrere Tests
reproduzieren genau dieses Szenario (Tier-1 ohne tenant_id, Dual-Read
bestehender Klartext-Secrets, defensiver Fallback bei Krypto-Fehlern).
"""
from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pytest.importorskip("cryptography.fernet")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from main import app  # noqa: F401,E402  (registriert alle Models)
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from services import totp  # noqa: E402
from services.tenant_crypto import TenantCryptoError  # noqa: E402
from services.totp_secret_storage import (  # noqa: E402
    _ENC_PREFIX,
    load_totp_secret,
    store_totp_secret,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sec005.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_tenant(db, tenant_id="firm-A"):
    tenant = Tenant(
        id=tenant_id, display_name="Firm A", slug=tenant_id.lower(),
        hosting_tier="tier2", license_status="active", max_users=10,
        is_active=1, created_at=_now(), updated_at=_now(),
    )
    db.add(tenant)
    db.commit()
    return tenant


def _seed_user(db, uid, *, tenant_id=None):
    user = User(
        id=uid, username=uid, password_hash="h", full_name=uid,
        role="advisor", is_active=1, tenant_id=tenant_id,
        created_at=_now(), updated_at=_now(),
    )
    db.add(user)
    db.commit()
    return user


# ---------------------------------------------------------------------------
# Tier-1 (kein tenant_id): unveraendertes Klartext-Verhalten -- KEIN
# Regressionsrisiko, KEIN 2FA-Lockout fuer bestehende Deployments.
# ---------------------------------------------------------------------------

def test_store_returns_plaintext_unchanged_when_user_has_no_tenant_id(session_factory):
    with session_factory() as db:
        user = _seed_user(db, "u1", tenant_id=None)
        secret = totp.generate_secret()
        stored = store_totp_secret(db, user, secret)
        assert stored == secret
        assert not stored.startswith(_ENC_PREFIX)


def test_load_returns_plaintext_unchanged_when_user_has_no_tenant_id(session_factory):
    with session_factory() as db:
        user = _seed_user(db, "u2", tenant_id=None)
        secret = totp.generate_secret()
        user.totp_secret = store_totp_secret(db, user, secret)
        assert load_totp_secret(db, user) == secret


# ---------------------------------------------------------------------------
# Mit tenant_id + echtem Tenant: Secret wird verschluesselt gespeichert.
# ---------------------------------------------------------------------------

def test_store_encrypts_when_tenant_exists(session_factory):
    with session_factory() as db:
        _seed_tenant(db, "firm-A")
        user = _seed_user(db, "u3", tenant_id="firm-A")
        secret = totp.generate_secret()
        stored = store_totp_secret(db, user, secret)
        assert stored.startswith(_ENC_PREFIX)
        assert secret not in stored  # Ciphertext, nicht nur ein Prefix vor Klartext


def test_store_then_load_roundtrips_to_original_secret(session_factory):
    with session_factory() as db:
        _seed_tenant(db, "firm-B")
        user = _seed_user(db, "u4", tenant_id="firm-B")
        secret = totp.generate_secret()
        user.totp_secret = store_totp_secret(db, user, secret)
        assert load_totp_secret(db, user) == secret


def test_totp_verify_works_against_roundtripped_encrypted_secret(session_factory):
    """End-to-End: ein echter TOTP-Code fuer das Original-Secret muss auch
    gegen das entschluesselte Secret verifizieren."""
    with session_factory() as db:
        _seed_tenant(db, "firm-C")
        user = _seed_user(db, "u5", tenant_id="firm-C")
        secret = totp.generate_secret()
        user.totp_secret = store_totp_secret(db, user, secret)
        code = totp.totp_at(secret, time.time())
        decrypted = load_totp_secret(db, user)
        assert totp.verify(decrypted, code) is True


# ---------------------------------------------------------------------------
# Dual-Read: bestehende, VOR diesem Fix im Klartext gespeicherte Secrets
# bleiben lesbar -- auch wenn der User inzwischen einen tenant_id hat.
# ---------------------------------------------------------------------------

def test_load_dual_reads_legacy_plaintext_secret_even_with_tenant_id(session_factory):
    with session_factory() as db:
        _seed_tenant(db, "firm-D")
        user = _seed_user(db, "u6", tenant_id="firm-D")
        legacy_secret = totp.generate_secret()
        user.totp_secret = legacy_secret  # direkt gesetzt, wie vor dem Fix
        assert load_totp_secret(db, user) == legacy_secret


# ---------------------------------------------------------------------------
# Fail-safe: Krypto-Fehler duerfen 2FA-Setup/-Verify NIE hart crashen lassen.
# ---------------------------------------------------------------------------

def test_store_falls_back_to_plaintext_when_tenant_missing(session_factory):
    """tenant_id zeigt auf keinen existierenden Tenant (Race/Datenfehler) --
    store_totp_secret() darf trotzdem nicht werfen."""
    with session_factory() as db:
        user = _seed_user(db, "u7", tenant_id="ghost-tenant")
        secret = totp.generate_secret()
        stored = store_totp_secret(db, user, secret)
        assert stored == secret  # Fallback: Klartext statt Exception


def test_load_returns_empty_string_on_decrypt_failure_instead_of_raising(session_factory, monkeypatch):
    import services.totp_secret_storage as storage_mod

    with session_factory() as db:
        _seed_tenant(db, "firm-E")
        user = _seed_user(db, "u8", tenant_id="firm-E")
        user.totp_secret = _ENC_PREFIX + "corrupted-ciphertext-not-valid-fernet"

        def _boom(*_a, **_kw):
            raise TenantCryptoError("simulierter Entschluesselungsfehler")

        monkeypatch.setattr(storage_mod, "decrypt_for_tenant", _boom)
        result = load_totp_secret(db, user)
        assert result == ""
        # totp_verify() lehnt konsistent ab statt zu crashen.
        assert totp.verify(result, "123456") is False


def test_load_returns_empty_string_when_enc_prefix_but_no_tenant_id(session_factory):
    """Kann eigentlich nicht vorkommen (nur wir schreiben den Prefix, und nur
    mit tenant_id) -- defensiv trotzdem kein Crash bei Inkonsistenz."""
    with session_factory() as db:
        user = _seed_user(db, "u9", tenant_id=None)
        user.totp_secret = _ENC_PREFIX + "whatever"
        assert load_totp_secret(db, user) == ""


# ---------------------------------------------------------------------------
# Voller HTTP-Integrationsflow: Setup -> Enable -> Login mit Tenant-User.
# ---------------------------------------------------------------------------

def test_full_setup_enable_login_flow_with_tenant_scoped_encrypted_secret(session_factory):
    from fastapi.testclient import TestClient
    from database import get_db
    from main import app
    from services.auth import hash_password

    with session_factory() as seed_db:
        _seed_tenant(seed_db, "firm-F")
        seed_db.add(User(
            id="tu1", username="tu1", password_hash=hash_password("pw"),
            full_name="tu1", role="advisor", is_active=1, tenant_id="firm-F",
            created_at=_now(), updated_at=_now(),
        ))
        seed_db.commit()

    def override_db():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            login = client.post("/auth/login", json={"username": "tu1", "password": "pw"})
            assert login.status_code == 200
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            setup = client.post("/auth/2fa/setup", headers=headers)
            assert setup.status_code == 200
            secret = setup.json()["secret"]  # Klartext im API-Response (fuer QR)

            with session_factory() as db:
                stored_row = db.query(User).filter_by(id="tu1").first()
                assert stored_row.totp_secret.startswith(_ENC_PREFIX), (
                    "Persistierter Wert muss verschluesselt sein (tenant_id vorhanden)"
                )

            code = totp.totp_at(secret, time.time())
            enable = client.post("/auth/2fa/enable", json={"code": code}, headers=headers)
            assert enable.status_code == 200

            # Voller Kreis: erneuter Login MIT 2FA-Code funktioniert -- das
            # entschluesselte Secret aus der DB matcht den echten Authenticator-Code.
            login2 = client.post(
                "/auth/login",
                json={"username": "tu1", "password": "pw", "totp_code": totp.totp_at(secret, time.time())},
            )
            assert login2.status_code == 200
    finally:
        app.dependency_overrides.clear()
