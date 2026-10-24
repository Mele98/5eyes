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
# Kontrollrunde 2026-09-24: der Fallback-auf-secret_key-Gate pruefte bisher
# NUR settings.app_env in {staging, production} -- ein Tier-2/3-Multi-
# Tenant-Deployment, das schlicht nie APP_ENV setzt (app_env defaultet auf
# 'development', ein von TENANT_MASTER_KEK komplett getrennter Schalter),
# lief bisher unbemerkt mit einem aus dem oeffentlich sichtbaren
# DEFAULT_SECRET_KEY abgeleiteten KEK. Der Gate greift jetzt zusaetzlich,
# wenn das Deployment tatsaechlich multi-tenant ist.
# ---------------------------------------------------------------------------

def test_missing_kek_raises_for_multi_tenant_deployment_even_in_dev_app_env(monkeypatch):
    """Ein Tier-2-Deployment (hosting_tier via tenancy_mode='multi') OHNE
    gesetzten TENANT_MASTER_KEK und OHNE explizit gesetztes APP_ENV muss
    jetzt fehlschlagen, nicht mehr auf secret_key zurueckfallen."""
    from config import settings
    from services.tenant_crypto import TenantCryptoError, _resolve_master_kek

    monkeypatch.setattr(settings, "app_env", "development", raising=False)
    monkeypatch.setattr(settings, "tenancy_mode", "multi", raising=False)
    monkeypatch.setattr(settings, "strict_tenant_isolation", False, raising=False)
    monkeypatch.setattr(settings, "deployment_tier", "tier1", raising=False)
    monkeypatch.setattr(settings, "tenant_master_kek", "", raising=False)
    monkeypatch.delenv("TENANT_MASTER_KEK", raising=False)

    with pytest.raises(TenantCryptoError, match="TENANT_MASTER_KEK fehlt"):
        _resolve_master_kek(None)


def test_missing_kek_raises_for_tier2_deployment_even_in_dev_app_env(monkeypatch):
    """Gleiches Szenario, aber ueber deployment_tier='tier2' statt
    tenancy_mode='multi' -- beide Wege muessen den Gate ausloesen (siehe
    services.auth._effective_strict_tenant_isolation)."""
    from config import settings
    from services.tenant_crypto import TenantCryptoError, _resolve_master_kek

    monkeypatch.setattr(settings, "app_env", "development", raising=False)
    monkeypatch.setattr(settings, "tenancy_mode", "single", raising=False)
    monkeypatch.setattr(settings, "strict_tenant_isolation", False, raising=False)
    monkeypatch.setattr(settings, "deployment_tier", "tier2", raising=False)
    monkeypatch.setattr(settings, "tenant_master_kek", "", raising=False)
    monkeypatch.delenv("TENANT_MASTER_KEK", raising=False)

    with pytest.raises(TenantCryptoError, match="TENANT_MASTER_KEK fehlt"):
        _resolve_master_kek(None)


def test_missing_kek_still_falls_back_for_genuine_tier1_dev_deployment(monkeypatch):
    """Backwards-Compat: ein echtes Tier-1/Single-Tenant-Dev-Deployment
    (kein Multi-Tenant-Kontext) faellt weiterhin auf secret_key zurueck --
    das ist die etablierte, bewusst unveraenderte Tier-1-Semantik."""
    from config import settings
    from services.tenant_crypto import _resolve_master_kek

    monkeypatch.setattr(settings, "app_env", "development", raising=False)
    monkeypatch.setattr(settings, "tenancy_mode", "single", raising=False)
    monkeypatch.setattr(settings, "strict_tenant_isolation", False, raising=False)
    monkeypatch.setattr(settings, "deployment_tier", "tier1", raising=False)
    monkeypatch.setattr(settings, "tenant_master_kek", "", raising=False)
    monkeypatch.delenv("TENANT_MASTER_KEK", raising=False)

    resolved = _resolve_master_kek(None)
    assert resolved  # faellt auf secret_key zurueck, kein Raise
