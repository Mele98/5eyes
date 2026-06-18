"""Per-tenant DEK envelope encryption helpers.

The master KEK is supplied via ``settings.tenant_master_kek`` or the
``TENANT_MASTER_KEK`` environment variable. The tenant table stores only the
encrypted DEK; callers use the plaintext DEK through these helpers.
"""
from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from config import settings
from models.tenant import Tenant


class TenantCryptoError(RuntimeError):
    pass


def _fernet_class():
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError as exc:  # pragma: no cover - exercised in envs without dependency
        raise TenantCryptoError(
            "cryptography ist fuer Tenant-DEK-Verschluesselung erforderlich"
        ) from exc
    return Fernet, InvalidToken


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _resolve_master_kek(master_kek: str | bytes | None = None) -> bytes:
    raw = (
        master_kek
        or os.getenv("TENANT_MASTER_KEK")
        or getattr(settings, "tenant_master_kek", "")
    )
    if not raw:
        if getattr(settings, "app_env", "development") in {"staging", "production"}:
            raise TenantCryptoError("TENANT_MASTER_KEK fehlt fuer staging/production")
        raw = getattr(settings, "secret_key", "")
    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
    else:
        raw_bytes = raw
    Fernet, _ = _fernet_class()
    try:
        Fernet(raw_bytes)
        return raw_bytes
    except Exception:
        return base64.urlsafe_b64encode(hashlib.sha256(raw_bytes).digest())


def _master_fernet(master_kek: str | bytes | None = None):
    Fernet, _ = _fernet_class()
    return Fernet(_resolve_master_kek(master_kek))


def _new_dek() -> bytes:
    Fernet, _ = _fernet_class()
    return Fernet.generate_key()


def _tenant_or_error(db: Session, tenant_id: str) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)).first()
    if tenant is None:
        raise TenantCryptoError(f"Tenant nicht gefunden: {tenant_id}")
    return tenant


def _decrypt_dek(encrypted_dek: str, master_kek: str | bytes | None = None) -> bytes:
    _, InvalidToken = _fernet_class()
    try:
        return _master_fernet(master_kek).decrypt(encrypted_dek.encode("utf-8"))
    except InvalidToken as exc:
        raise TenantCryptoError("Tenant-DEK kann mit dieser Master-KEK nicht entschluesselt werden") from exc


def get_tenant_dek(db: Session, tenant_id: str, *, master_kek: str | bytes | None = None) -> bytes:
    """Return the tenant DEK, creating and storing one if absent."""

    tenant = _tenant_or_error(db, tenant_id)
    if getattr(tenant, "encrypted_dek", None):
        return _decrypt_dek(str(tenant.encrypted_dek), master_kek)

    dek = _new_dek()
    tenant.encrypted_dek = _master_fernet(master_kek).encrypt(dek).decode("utf-8")
    tenant.dek_version = int(getattr(tenant, "dek_version", None) or 1)
    tenant.dek_rotated_at = _now_iso()
    db.flush()
    return dek


def rotate_tenant_dek(db: Session, tenant_id: str, *, master_kek: str | bytes | None = None) -> bytes:
    """Generate and store a new tenant DEK.

    Existing encrypted payloads must be re-encrypted by the caller before old
    ciphertext is discarded. Current codebase uses this as the documented PII
    encryption interface; no existing business fields are mutated here.
    """

    tenant = _tenant_or_error(db, tenant_id)
    dek = _new_dek()
    tenant.encrypted_dek = _master_fernet(master_kek).encrypt(dek).decode("utf-8")
    tenant.dek_version = int(getattr(tenant, "dek_version", None) or 0) + 1
    tenant.dek_rotated_at = _now_iso()
    db.flush()
    return dek


def encrypt_for_tenant(
    db: Session,
    tenant_id: str,
    plaintext: bytes,
    *,
    master_kek: str | bytes | None = None,
) -> str:
    Fernet, _ = _fernet_class()
    return Fernet(get_tenant_dek(db, tenant_id, master_kek=master_kek)).encrypt(plaintext).decode("utf-8")


def decrypt_for_tenant(
    db: Session,
    tenant_id: str,
    ciphertext: str,
    *,
    master_kek: str | bytes | None = None,
) -> bytes:
    Fernet, InvalidToken = _fernet_class()
    try:
        return Fernet(get_tenant_dek(db, tenant_id, master_kek=master_kek)).decrypt(
            ciphertext.encode("utf-8")
        )
    except InvalidToken as exc:
        raise TenantCryptoError("Tenant-Ciphertext konnte nicht entschluesselt werden") from exc
