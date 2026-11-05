"""Per-tenant DEK envelope encryption helpers.

The master KEK has exactly one configuration source,
``settings.tenant_master_kek`` (environment/config ``TENANT_MASTER_KEK``), and
is mandatory: without it the app does not start (startup check
``config.require_tenant_master_kek`` in ``main.lifespan``, before ``init_db``;
the same check ``config.tenant_master_kek_problem`` guards every unwrap here).
There is no fallback to ``SECRET_KEY`` or to a placeholder. The tenant table
stores only the encrypted DEK plus the KEK generation (``kek_version``);
callers use the plaintext DEK through these helpers.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from config import (
    MISSING_TENANT_MASTER_KEK_MESSAGE,
    TENANT_KEK_KDF_ITERATIONS,
    TENANT_KEK_KDF_SALT,
    effective_tenant_master_kek,
    settings,
    tenant_master_kek_problem,
)
from models.tenant import Tenant
from services.tenant_context import is_postgres_bind, operator_bypass


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
# Quelle: config.TENANT_KEK_KDF_* (dieselbe Ableitung prueft die Startpruefung).
_KEK_KDF_SALT = TENANT_KEK_KDF_SALT
_KEK_KDF_ITERATIONS = TENANT_KEK_KDF_ITERATIONS

# Generation der Master-KEK (Spalte tenants.kek_version), unter der neue DEKs
# verpackt werden. Ein DEK mit anderer Generation wird nie entpackt: er ist
# mit dem Migrator zu uebernehmen (kein Rueckfall auf einen frueheren Vertrag).
CURRENT_KEK_VERSION = 2

MISSING_KEK_MESSAGE = MISSING_TENANT_MASTER_KEK_MESSAGE


def _configured_master_kek() -> str:
    """Einzige Konfigurationsquelle der Master-KEK: ``settings.tenant_master_kek``."""
    return str(getattr(settings, "tenant_master_kek", "") or "").strip()


def _validate_master_kek(raw: str | bytes) -> None:
    """Fail-closed: kein Rueckfall auf SECRET_KEY oder einen Platzhalter
    (gemeinsame Pruefung ``config.tenant_master_kek_problem``)."""
    problem = tenant_master_kek_problem(raw, secret_key=str(getattr(settings, "secret_key", "") or ""))
    if problem:
        raise TenantCryptoError(problem)


def _resolve_master_kek(master_kek: str | bytes | None = None) -> bytes:
    raw = master_kek if master_kek else _configured_master_kek()
    _validate_master_kek(raw)
    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8")
    else:
        raw_bytes = raw
    _fernet_class()  # klare TenantCryptoError, falls cryptography fehlt
    # Gueltiger Fernet-Key unveraendert; Passphrase-KEK per PBKDF2-HMAC-SHA256
    # mit hohem Work-Factor und dem stabilen v2-Salt -- deterministische
    # Re-Ableitung ist noetig, damit verpackte DEKs entpackbar bleiben. Die
    # Funktion liegt in config, damit die Startpruefung dieselbe Ableitung nutzt.
    return effective_tenant_master_kek(
        raw_bytes, salt=_KEK_KDF_SALT, iterations=_KEK_KDF_ITERATIONS,
    )


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


@dataclass(frozen=True)
class KekRewrapResult:
    """Ergebnis des Rewraps, ohne Schluesselmaterial."""

    count: int
    tenant_ids: tuple[str, ...]


def rewrap_tenant_deks_to_master_kek(
    db: Session,
    *,
    source_kek: str | bytes,
    target_kek: str | bytes,
) -> KekRewrapResult:
    """N-870-6 (2026-11-05): Offline-Rewrap aller Tenant-DEKs von der bisherigen
    Master-KEK (``source_kek``) auf einen neuen Fernet-Key (``target_kek``).

    Fuer Bestandsinstallationen, deren Passphrase-KEK allein an der
    Staerkeregel scheitert (zu kurz, zu wenig Vielfalt): Ares startet damit
    nicht mehr, die DEKs sind aber unveraendert. Die Quelle darf hier deshalb
    die Staerkeregel verletzen; Platzhalter, Vorlagenwerte und oeffentliche
    Ableitungen bleiben auch als Quelle abgelehnt (fail-closed). Das Ziel muss
    ein gueltiger Fernet-Key sein und die volle Pruefung bestehen.

    Die DEKs selbst bleiben gleich (kein Re-Encrypt der Nutzdaten noetig); nur
    ``tenants.encrypted_dek`` wird neu verpackt und vor dem Schreiben gegen das
    Ziel rueckgeprueft. Alles in der Transaktion des Aufrufers: der Aufrufer
    committet; jeder Fehler laesst den Bestand unveraendert. ``updated_at``
    der umverpackten Tenants wird gesetzt; ``dek_rotated_at`` bleibt, denn
    der DEK selbst ist unveraendert. Den Audit-Eintrag schreibt der Aufrufer
    in derselben Transaktion (scripts/rewrap_tenant_master_kek.py, N-870-10).
    Rueckgabe: Anzahl und IDs der umverpackten Tenants. Keine Meldung nennt
    einen Schluessel."""
    Fernet, InvalidToken = _fernet_class()
    secret = str(getattr(settings, "secret_key", "") or "")
    problem = tenant_master_kek_problem(
        source_kek, secret_key=secret, enforce_passphrase_strength=False,
    )
    if problem:
        raise TenantCryptoError(f"Quell-KEK abgelehnt: {problem}")
    problem = tenant_master_kek_problem(target_kek, secret_key=secret)
    if problem:
        raise TenantCryptoError(f"Ziel-KEK abgelehnt: {problem}")
    source_bytes = source_kek.encode("utf-8") if isinstance(source_kek, str) else bytes(source_kek)
    target_bytes = target_kek.encode("utf-8") if isinstance(target_kek, str) else bytes(target_kek)
    if effective_tenant_master_kek(target_bytes.strip()) != target_bytes.strip():
        raise TenantCryptoError(
            "Ziel-KEK abgelehnt: fuer den Rewrap ist ein Fernet-Key verlangt "
            "(Fernet.generate_key()), keine Passphrase."
        )
    source_key = effective_tenant_master_kek(
        source_bytes.strip(), salt=_KEK_KDF_SALT, iterations=_KEK_KDF_ITERATIONS,
    )
    target_key = target_bytes.strip()
    if base64.urlsafe_b64decode(source_key) == base64.urlsafe_b64decode(target_key):
        raise TenantCryptoError("Ziel-KEK abgelehnt: identisch mit der Quell-KEK.")
    source_fernet = Fernet(source_key)
    target_fernet = Fernet(target_key)

    with operator_bypass(db):
        tenants = db.query(Tenant).filter(Tenant.encrypted_dek.isnot(None)).all()
        # Erst alles entpacken und neu verpacken, dann schreiben: ein Fehler bei
        # irgendeinem Tenant aendert keinen einzigen.
        planned: list[tuple[Tenant, str]] = []
        for tenant in tenants:
            _require_current_kek_version(tenant)
            try:
                dek = source_fernet.decrypt(str(tenant.encrypted_dek).encode("utf-8"))
            except InvalidToken as exc:
                raise TenantCryptoError(
                    "Tenant-DEK kann mit der Quell-KEK nicht entschluesselt werden; "
                    "kein DEK wurde geaendert."
                ) from exc
            rewrapped = target_fernet.encrypt(dek)
            if target_fernet.decrypt(rewrapped) != dek:  # pragma: no cover - Fernet-Vertrag
                raise TenantCryptoError("Rewrap-Rueckpruefung fehlgeschlagen; kein DEK wurde geaendert.")
            planned.append((tenant, rewrapped.decode("utf-8")))
        now = _now_iso()
        for tenant, encrypted in planned:
            tenant.encrypted_dek = encrypted
            tenant.updated_at = now
        db.flush()
    return KekRewrapResult(
        count=len(planned),
        tenant_ids=tuple(str(tenant.id) for tenant, _ in planned),
    )
