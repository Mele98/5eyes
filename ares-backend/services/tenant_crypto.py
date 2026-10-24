"""Per-tenant DEK envelope encryption helpers.

The master KEK has exactly one configuration source,
``settings.tenant_master_kek`` (environment/config ``TENANT_MASTER_KEK``), and
is mandatory: without it the app does not start (``require_master_kek``).
There is no fallback to ``SECRET_KEY`` or to a placeholder. The tenant table
stores only the encrypted DEK plus the KEK generation (``kek_version``);
callers use the plaintext DEK through these helpers.
"""
from __future__ import annotations

import base64
import hashlib
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


# KEK-Vertrag v2 (W4-c): Salt der PBKDF2-Ableitung eines Passphrase-KEK.
# Markenfrei und versioniert; muss konstant bleiben, damit ein einmal
# abgeleiteter KEK reproduzierbar ist. Den Salt des vorherigen Vertrags kennt
# nur der externe Einmal-Migrator, der Bestands-DEKs unter einen v2-KEK
# umverpackt (Rewrap) und dabei tenants.kek_version auf 2 setzt.
_KEK_KDF_SALT = b"ares.tenant.kek.pbkdf2.v2"
_KEK_KDF_ITERATIONS = 200_000

# Generation der Master-KEK (Spalte tenants.kek_version), unter der neue DEKs
# verpackt werden. Ein DEK mit anderer Generation wird nie entpackt: er ist
# mit dem Migrator zu uebernehmen (kein Rueckfall auf einen frueheren Vertrag).
CURRENT_KEK_VERSION = 2

MISSING_KEK_MESSAGE = (
    "TENANT_MASTER_KEK fehlt: Ares startet nicht ohne eigene Master-KEK. "
    "Einen Fernet-Key erzeugen (python -c \"from cryptography.fernet import "
    "Fernet; print(Fernet.generate_key().decode())\") und als "
    "TENANT_MASTER_KEK in der Konfiguration setzen; eine Bestandsinstallation "
    "bringt ihn aus der Zielkonfiguration des Migrators mit."
)


def _configured_master_kek() -> str:
    """Einzige Konfigurationsquelle der Master-KEK: ``settings.tenant_master_kek``."""
    return str(getattr(settings, "tenant_master_kek", "") or "").strip()


def _validate_master_kek(raw: str | bytes) -> None:
    """Fail-closed: kein Rueckfall auf SECRET_KEY oder einen Platzhalter."""
    from config import DEFAULT_SECRET_KEY

    value = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    if not value.strip():
        raise TenantCryptoError(MISSING_KEK_MESSAGE)
    if value == DEFAULT_SECRET_KEY:
        raise TenantCryptoError(
            "TENANT_MASTER_KEK ist der oeffentliche Platzhalter aus dem Quellcode "
            "und damit kein Geheimnis. Einen eigenen Fernet-Key setzen."
        )
    secret_key = str(getattr(settings, "secret_key", "") or "")
    if secret_key and value == secret_key:
        raise TenantCryptoError(
            "TENANT_MASTER_KEK ist identisch mit SECRET_KEY. Der JWT-Schluessel "
            "darf nicht zugleich die Master-KEK sein; einen eigenen Fernet-Key setzen."
        )


def require_master_kek() -> None:
    """Startpruefung (Lifespan): ohne gueltige Master-KEK startet Ares nicht."""
    _validate_master_kek(_configured_master_kek())


def _resolve_master_kek(master_kek: str | bytes | None = None) -> bytes:
    raw = master_kek if master_kek else _configured_master_kek()
    _validate_master_kek(raw)
    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
    else:
        raw_bytes = raw
    Fernet, _ = _fernet_class()
    try:
        Fernet(raw_bytes)
        return raw_bytes
    except Exception:
        # Passphrase-KEK (kein gueltiger Fernet-Key): PBKDF2-HMAC-SHA256 mit
        # hohem Work-Factor (Brute-Force-Haertung) und dem stabilen v2-Salt --
        # deterministische Re-Ableitung ist noetig, damit verpackte DEKs
        # entpackbar bleiben.
        derived = hashlib.pbkdf2_hmac(
            "sha256", raw_bytes, _KEK_KDF_SALT, _KEK_KDF_ITERATIONS
        )
        return base64.urlsafe_b64encode(derived)


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


def _require_current_kek_version(tenant: Tenant) -> None:
    """Ein DEK unter einer anderen KEK-Generation wird nicht entpackt."""
    version = getattr(tenant, "kek_version", None)
    if version != CURRENT_KEK_VERSION:
        raise TenantCryptoError(
            f"Tenant-DEK ist unter KEK-Generation {version!r} verpackt, erwartet "
            f"{CURRENT_KEK_VERSION}. Diese Daten stammen aus einer frueheren "
            "Installation: Daten mit dem Migrator uebernehmen (Rewrap auf die "
            "aktuelle KEK), nicht mit dieser App-Version oeffnen."
        )


def _decrypt_dek(encrypted_dek: str, master_kek: str | bytes | None = None) -> bytes:
    _, InvalidToken = _fernet_class()
    try:
        return _master_fernet(master_kek).decrypt(encrypted_dek.encode("utf-8"))
    except InvalidToken as exc:
        raise TenantCryptoError("Tenant-DEK kann mit dieser Master-KEK nicht entschluesselt werden") from exc


def _provision_tenant_dek_committed(
    db: Session, tenant_id: str, master_kek: str | bytes | None
) -> str:
    """#299-Follow-up #2: einen fehlenden DEK in EIGENER, sofort committeter Transaktion
    anlegen und den persistierten encrypted_dek-String zurueckgeben.

    So ueberlebt der DEK einen spaeteren Rollback des Aufrufers — sonst waeren mit ihm
    verschluesselte Daten dauerhaft unlesbar. Race-sicher: auf PostgreSQL per
    SELECT ... FOR UPDATE serialisiert; legt ein paralleler Request zuerst an, wird
    dessen encrypted_dek uebernommen (Re-Check), statt ihn zu ueberschreiben. Die
    frische Session laeuft auf DERSELBEN Engine wie der Aufrufer (db.get_bind()).
    """
    from sqlalchemy.orm import Session as _SASession
    from services.tenant_context import is_postgres_bind

    session = _SASession(bind=db.get_bind())
    try:
        query = session.query(Tenant).filter(
            Tenant.id == tenant_id, Tenant.deleted_at.is_(None)
        )
        if is_postgres_bind(session):
            query = query.with_for_update()
        tenant = query.first()
        if tenant is None:
            raise TenantCryptoError(f"Tenant nicht gefunden: {tenant_id}")
        if getattr(tenant, "encrypted_dek", None):
            _require_current_kek_version(tenant)
            return str(tenant.encrypted_dek)  # paralleler Request war schneller
        tenant.encrypted_dek = _master_fernet(master_kek).encrypt(_new_dek()).decode("utf-8")
        tenant.dek_version = int(getattr(tenant, "dek_version", None) or 1)
        tenant.kek_version = CURRENT_KEK_VERSION
        tenant.dek_rotated_at = _now_iso()
        session.commit()
        return str(tenant.encrypted_dek)
    finally:
        session.close()


def get_tenant_dek(db: Session, tenant_id: str, *, master_kek: str | bytes | None = None) -> bytes:
    """Return the tenant DEK, provisioning one (committed) if absent."""

    tenant = _tenant_or_error(db, tenant_id)
    if getattr(tenant, "encrypted_dek", None):
        _require_current_kek_version(tenant)
        return _decrypt_dek(str(tenant.encrypted_dek), master_kek)

    # DEK fehlt -> unabhaengig committen statt lazily mit blossem flush() in der
    # Aufrufer-Transaktion (Rollback/Race-Risiko, siehe _provision_tenant_dek_committed).
    encrypted = _provision_tenant_dek_committed(db, tenant_id, master_kek)
    try:
        db.refresh(tenant)  # ORM-Objekt des Aufrufers mit persistiertem Zustand synchronisieren
    except Exception:
        db.expire(tenant)
    return _decrypt_dek(encrypted, master_kek)


def rotate_tenant_dek(db: Session, tenant_id: str, *, master_kek: str | bytes | None = None) -> bytes:
    """Generate and store a new tenant DEK.

    Existing encrypted payloads must be re-encrypted by the caller before old
    ciphertext is discarded. Current codebase uses this as the documented PII
    encryption interface; no existing business fields are mutated here.

    ⚠️ WARNUNG (2026-07-25, Generalaudit, Wave 12): diese Funktion
    ueberschreibt `tenant.encrypted_dek` SOFORT und bewahrt die alte DEK
    NIRGENDS auf. Jeder mit der alten DEK bereits verschluesselte Payload
    wird dadurch DAUERHAFT unlesbar, wenn der Aufrufer nicht VORHER selbst
    alle betroffenen Payloads mit der neuen DEK re-verschluesselt hat (die
    alte DEK muss dafuer VOR diesem Aufruf separat abgerufen werden). Stand
    Audit: `rotate_tenant_dek`/`encrypt_for_tenant`/`decrypt_for_tenant`
    werden im gesamten Anwendungscode NIRGENDS aufgerufen (nur in Tests) --
    kein Live-PII-Feld nutzt diese Schnittstelle, daher aktuell kein
    Datenverlust-Risiko. Vor dem ersten produktiven Einsatz MUSS ein
    echter Re-Encrypt-Flow um diese Funktion herum gebaut werden.
    """

    tenant = _tenant_or_error(db, tenant_id)
    dek = _new_dek()
    tenant.encrypted_dek = _master_fernet(master_kek).encrypt(dek).decode("utf-8")
    tenant.dek_version = int(getattr(tenant, "dek_version", None) or 0) + 1
    tenant.kek_version = CURRENT_KEK_VERSION
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
