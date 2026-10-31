from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

pytest.importorskip("cryptography.fernet")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
import models.tenant  # noqa: F401,E402
from models.tenant import Tenant  # noqa: E402
from services.tenant_crypto import (  # noqa: E402
    TenantCryptoError,
    decrypt_for_tenant,
    encrypt_for_tenant,
    get_tenant_dek,
    rotate_tenant_dek,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tenant-crypto.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield Session, engine
    finally:
        engine.dispose()


def _seed_tenant(db, tenant_id="firm-A"):
    tenant = Tenant(
        id=tenant_id,
        display_name="Firm A",
        slug=tenant_id.lower(),
        hosting_tier="tier2",
        license_status="active",
        max_users=10,
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(tenant)
    db.commit()
    return tenant


def test_tenant_model_has_dek_columns(session_factory):
    _, engine = session_factory
    cols = {c["name"] for c in inspect(engine).get_columns("tenants")}
    assert {"encrypted_dek", "dek_version", "dek_rotated_at"}.issubset(cols)


def test_get_tenant_dek_creates_encrypted_dek_and_roundtrip(session_factory):
    Session, _ = session_factory
    with Session() as db:
        tenant = _seed_tenant(db)
        dek = get_tenant_dek(db, tenant.id, master_kek="master-one")
        assert isinstance(dek, bytes)
        assert tenant.encrypted_dek
        assert tenant.encrypted_dek.encode("utf-8") != dek
        token = encrypt_for_tenant(db, tenant.id, b"PII payload", master_kek="master-one")
        assert decrypt_for_tenant(db, tenant.id, token, master_kek="master-one") == b"PII payload"


def test_wrong_master_kek_fails_to_decrypt_dek(session_factory):
    Session, _ = session_factory
    with Session() as db:
        tenant = _seed_tenant(db)
        get_tenant_dek(db, tenant.id, master_kek="right-master")
        db.commit()
        with pytest.raises(TenantCryptoError):
            get_tenant_dek(db, tenant.id, master_kek="wrong-master")


def test_rotate_tenant_dek_increments_version_and_replaces_key(session_factory):
    Session, _ = session_factory
    with Session() as db:
        tenant = _seed_tenant(db)
        old_dek = get_tenant_dek(db, tenant.id, master_kek="master-one")
        old_encrypted = tenant.encrypted_dek
        new_dek = rotate_tenant_dek(db, tenant.id, master_kek="master-one")
        assert new_dek != old_dek
        assert tenant.encrypted_dek != old_encrypted
        assert tenant.dek_version == 2


def test_passphrase_kek_uses_pbkdf2_not_saltless_sha256(session_factory):
    # #299-Follow-up #1: ein Passphrase-KEK (kein gueltiger Fernet-Key) wird per PBKDF2
    # abgeleitet (Work-Factor), nicht mehr per saltlosem Single-Shot-SHA-256.
    import base64
    import hashlib

    from services.tenant_crypto import (
        _KEK_KDF_ITERATIONS,
        _KEK_KDF_SALT,
        _resolve_master_kek,
    )

    passphrase = "operator-passphrase-not-a-fernet-key"
    resolved = _resolve_master_kek(passphrase)
    expected_pbkdf2 = base64.urlsafe_b64encode(
        hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), _KEK_KDF_SALT, _KEK_KDF_ITERATIONS)
    )
    assert resolved == expected_pbkdf2  # deterministisch + PBKDF2
    old_saltless = base64.urlsafe_b64encode(hashlib.sha256(passphrase.encode("utf-8")).digest())
    assert resolved != old_saltless  # nicht mehr das schwache SHA-256

    Session, _ = session_factory
    with Session() as db:
        _seed_tenant(db, tenant_id="firm-P")
        token = encrypt_for_tenant(db, "firm-P", b"secret", master_kek=passphrase)
        assert decrypt_for_tenant(db, "firm-P", token, master_kek=passphrase) == b"secret"


def test_dek_provisioning_survives_caller_rollback(session_factory):
    # #299-Follow-up #2: ein lazily angelegter DEK muss einen Rollback des Aufrufers
    # ueberleben (eigene committete Transaktion) — sonst waeren damit verschluesselte
    # Daten dauerhaft unlesbar.
    Session, _ = session_factory
    with Session() as db:
        _seed_tenant(db, tenant_id="firm-R")

    with Session() as caller:
        get_tenant_dek(caller, "firm-R", master_kek="m")
        caller.rollback()  # Aufrufer bricht seine Transaktion ab

    with Session() as check:
        tenant = check.query(Tenant).filter(Tenant.id == "firm-R").first()
        assert tenant.encrypted_dek, "DEK muss den Aufrufer-Rollback ueberleben"
        token = encrypt_for_tenant(check, "firm-R", b"payload", master_kek="m")
        assert decrypt_for_tenant(check, "firm-R", token, master_kek="m") == b"payload"


# ---------------------------------------------------------------------------
# W4-c / AF-4: Die Master-KEK ist Pflicht und hat genau eine Quelle
# (settings.tenant_master_kek). Frueher fiel ein Tier-1-/Dev-Deployment ohne
# KEK auf secret_key zurueck (und damit ohne gesetztes secret_key auf den
# oeffentlichen Platzhalter); Multi-Tenant/staging/production schlugen schon
# fehl. Jetzt scheitert JEDES Deployment ohne eigene KEK, unabhaengig von
# app_env, hosting_tier oder tenancy_mode.
# ---------------------------------------------------------------------------

def _no_kek(monkeypatch, *, app_env="development", tenancy_mode="single", tier="tier1"):
    from config import settings

    monkeypatch.setattr(settings, "app_env", app_env, raising=False)
    monkeypatch.setattr(settings, "tenancy_mode", tenancy_mode, raising=False)
    monkeypatch.setattr(settings, "strict_tenant_isolation", False, raising=False)
    monkeypatch.setattr(settings, "deployment_tier", tier, raising=False)
    monkeypatch.setattr(settings, "tenant_master_kek", "", raising=False)
    return settings


@pytest.mark.parametrize(
    "app_env,tenancy_mode,tier",
    [
        ("development", "multi", "tier1"),
        ("development", "single", "tier2"),
        ("development", "single", "tier1"),
        ("production", "single", "tier1"),
    ],
)
def test_missing_kek_raises_for_every_deployment(monkeypatch, app_env, tenancy_mode, tier):
    from services.tenant_crypto import TenantCryptoError, _resolve_master_kek

    _no_kek(monkeypatch, app_env=app_env, tenancy_mode=tenancy_mode, tier=tier)
    with pytest.raises(TenantCryptoError, match="TENANT_MASTER_KEK fehlt"):
        _resolve_master_kek(None)


def test_missing_kek_never_falls_back_to_secret_key(monkeypatch):
    """Frueher: Tier-1-Dev ohne KEK -> KEK aus secret_key. Jetzt: Fehler."""
    from services.tenant_crypto import TenantCryptoError, _resolve_master_kek

    settings = _no_kek(monkeypatch)
    monkeypatch.setattr(settings, "secret_key", "s" * 48, raising=False)
    with pytest.raises(TenantCryptoError, match="TENANT_MASTER_KEK fehlt"):
        _resolve_master_kek(None)


def test_kek_equal_to_secret_key_or_placeholder_is_refused(monkeypatch):
    from config import DEFAULT_SECRET_KEY
    from services.tenant_crypto import TenantCryptoError, _resolve_master_kek

    settings = _no_kek(monkeypatch)
    monkeypatch.setattr(settings, "secret_key", "jwt-signing-key-" + "x" * 32, raising=False)
    monkeypatch.setattr(settings, "tenant_master_kek", settings.secret_key, raising=False)
    with pytest.raises(TenantCryptoError, match="identisch mit SECRET_KEY"):
        _resolve_master_kek(None)
    monkeypatch.setattr(settings, "tenant_master_kek", DEFAULT_SECRET_KEY, raising=False)
    with pytest.raises(TenantCryptoError, match="Platzhalter"):
        _resolve_master_kek(None)


def test_environment_variable_is_not_a_second_source(monkeypatch):
    """Eine einzige Quelle: ein nur in os.environ gesetzter Wert, der nicht in
    den Settings angekommen ist, wird nicht gelesen."""
    from cryptography.fernet import Fernet
    from services.tenant_crypto import TenantCryptoError, _resolve_master_kek

    _no_kek(monkeypatch)
    monkeypatch.setenv("TENANT_MASTER_KEK", Fernet.generate_key().decode("ascii"))
    with pytest.raises(TenantCryptoError, match="TENANT_MASTER_KEK fehlt"):
        _resolve_master_kek(None)
    source = (BACKEND_ROOT / "services" / "tenant_crypto.py").read_text(encoding="utf-8")
    assert "os.getenv" not in source and "os.environ" not in source


def test_configured_fernet_kek_is_used(monkeypatch):
    from cryptography.fernet import Fernet
    from services.tenant_crypto import _resolve_master_kek, require_master_kek

    settings = _no_kek(monkeypatch)
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "tenant_master_kek", key, raising=False)
    require_master_kek()
    assert _resolve_master_kek(None) == key.encode("ascii")


def test_app_start_without_kek_fails_closed_with_clear_message(monkeypatch, caplog):
    from fastapi.testclient import TestClient

    import main

    _no_kek(monkeypatch)
    init_calls = []
    monkeypatch.setattr(main, "init_db", lambda: init_calls.append(1))
    with pytest.raises(TenantCryptoError, match="TENANT_MASTER_KEK fehlt"):
        with TestClient(main.app):
            pass
    assert init_calls == [], "ohne KEK darf die DB nicht initialisiert werden"
    assert any("Start abgebrochen" in r.getMessage() for r in caplog.records)


def test_tunnel_scripts_provide_their_own_master_kek():
    """Die Staging-/Tunnel-Skripte setzen eine eigene, persistente Fernet-KEK
    (nicht das Login-Secret), sonst startet das Backend dort nicht mehr."""
    deploy = BACKEND_ROOT.parent / "docs" / "deploy"
    for name in ("start-external.ps1", "start-external-staging.ps1"):
        text_ = (deploy / name).read_text(encoding="utf-8")
        assert "$kekFile = Join-Path $aresHome '.external-kek.txt'" in text_, name
        assert "Fernet.generate_key()" in text_, name
        assert "$env:TENANT_MASTER_KEK     = $kek" in text_, name
        assert "$env:TENANT_MASTER_KEK     = $secret" not in text_, name
