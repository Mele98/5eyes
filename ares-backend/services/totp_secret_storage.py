"""SEC-005 (Codex-Audit 2026-08-26, docs/audits/2026-08-26-data-lifecycle-
crypto-browser-followup-audit.md): TOTP-Secret-at-rest-Verschluesselung.

`models/users.py::User.totp_secret` speicherte den Base32-Seed bisher IMMER
im Klartext. `services/tenant_crypto.py` bietet fertige Envelope-Encryption-
Helfer, wurde aber laut Audit nirgends fuer echte Geschaeftsfelder verwendet
(siehe `tests/test_landmine_functions_unused_guard.py`).

Scope dieser Fassung (bewusst NICHT der volle Fixvertrag)
-----------------------------------------------------------
- NUR neu angelegte TOTP-Secrets (`/auth/2fa/setup`) werden verschluesselt
  gespeichert -- und auch das NUR, wenn der User einen `tenant_id` hat
  (zeigt dieser auf keinen existierenden Tenant, scheitert das Setup
  fail-closed, siehe unten). Reiner Tier-1-Desktop-
  Betrieb ohne Tenant-Zuordnung ist von diesem Fix NICHT betroffen:
  unveraendertes Klartext-Verhalten, kein neues Schluesselmaterial noetig,
  KEIN 2FA-Lockout-Risiko fuer bestehende Tier-1-Deployments.
- Bestehende, bereits im Klartext gespeicherte Secrets werden NICHT
  rueckwirkend verschluesselt (kein destruktives Rewrite bestehender Zeilen).
  `load_totp_secret()` erkennt beide Formate (Dual-Read) am `enc1:`-Prefix.
- Fail-closed (AUDIT-FIX 2026-10-23): Jeder Verschluesselungsfehler beim
  Schreiben (z.B. `cryptography` fehlt, Tenant nicht vorhanden, KEK fehlt)
  wirft `TotpSecretStorageError` -- es wird NIE still Klartext gespeichert
  (frueher: stiller Klartext-Fallback -> gemischter Bestand). Ein `enc1:`-
  Wert, der sich nicht entschluesseln laesst (falscher KEK, korrupter
  Ciphertext, fehlender tenant_id), wirft ebenfalls `TotpSecretStorageError`
  statt still "" zu liefern (frueher: lautloser 2FA-Lockout ohne Diagnose).
  Die Router uebersetzen den Fehler in eine verstaendliche 503-Antwort.
  Fehlermeldungen und Logs enthalten nie das Secret.

NICHT Teil dieser Fassung (groesseres, separates Vorhaben laut Fixvertrag):
Key-Versionierung im Ciphertext, gestufte DEK-Rotation
(die DEK-Rotationsfunktion bleibt bewusst ungenutzt -- siehe dessen
WARNUNG-Docstring, kein Re-Encrypt-Flow existiert), HSM/Vault-Anbindung,
Verschluesselung weiterer sensitiver Felder.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from models.users import User
from services.tenant_crypto import (
    decrypt_for_tenant,
    encrypt_for_tenant,
)

logger = logging.getLogger(__name__)

# Marker-Prefix fuer verschluesselte Secrets. Base32-TOTP-Secrets bestehen
# nur aus [A-Z2-7] -- "enc1:" ist damit eindeutig von jedem legitimen
# Klartext-Secret unterscheidbar.
_ENC_PREFIX = "enc1:"

# Stabile, maschinenlesbare Gruende fuer TotpSecretStorageError.
REASON_ENCRYPT_FAILED = "totp_secret_encrypt_failed"
REASON_DECRYPT_FAILED = "totp_secret_decrypt_failed"
REASON_TENANT_MISSING = "totp_secret_tenant_missing"


class TotpSecretStorageError(RuntimeError):
    """TOTP-Secret konnte nicht verschluesselt bzw. entschluesselt werden.

    `reason_code` ist einer der REASON_*-Werte. Die Nachricht enthaelt nie
    das Secret oder den Ciphertext.
    """

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def store_totp_secret(db: Session, user: User, plaintext_secret: str) -> str:
    """Liefert den Wert, der in `User.totp_secret` persistiert werden soll.

    Verschluesselt, sobald der User einen `tenant_id` hat. Tier-1-Default
    (kein tenant_id) bleibt unveraendert Klartext. Schlaegt die
    Verschluesselung fehl, wird `TotpSecretStorageError` geworfen -- kein
    Klartext-Fallback.
    """
    tenant_id = getattr(user, "tenant_id", None)
    if not tenant_id:
        return plaintext_secret
    try:
        ciphertext = encrypt_for_tenant(db, tenant_id, plaintext_secret.encode("utf-8"))
    except Exception as exc:  # fail-closed: jeder Crypto-Fehler
        logger.error(
            "TOTP-Secret-Verschluesselung fehlgeschlagen | reason=%s user_id=%s "
            "tenant_id=%s error_type=%s -- nichts gespeichert",
            REASON_ENCRYPT_FAILED, getattr(user, "id", "?"), tenant_id,
            type(exc).__name__,
        )
        raise TotpSecretStorageError(
            REASON_ENCRYPT_FAILED,
            "TOTP-Secret konnte nicht verschluesselt werden "
            "(Schluesselkonfiguration pruefen)",
        ) from exc
    return _ENC_PREFIX + ciphertext


def load_totp_secret(db: Session, user: User) -> str:
    """Liefert das Klartext-Base32-Secret -- unabhaengig davon, ob es
    verschluesselt oder (legacy) im Klartext gespeichert ist (Dual-Read).

    Legacy-Klartext (ohne `enc1:`) und ein fehlendes Secret ("") verhalten
    sich unveraendert. Ein `enc1:`-Wert, der sich nicht entschluesseln
    laesst, wirft `TotpSecretStorageError` -- nie still "".
    """
    raw = getattr(user, "totp_secret", None) or ""
    if not raw.startswith(_ENC_PREFIX):
        return raw
    user_id = getattr(user, "id", "?")
    tenant_id = getattr(user, "tenant_id", None)
    if not tenant_id:
        # Kann nur vorkommen, wenn tenant_id nachtraeglich vom User entfernt
        # wurde, nachdem store_totp_secret() bereits verschluesselt hat.
        logger.error(
            "TOTP-Secret nicht lesbar | reason=%s user_id=%s -- enc1-Wert, "
            "aber kein tenant_id", REASON_TENANT_MISSING, user_id,
        )
        raise TotpSecretStorageError(
            REASON_TENANT_MISSING,
            "Verschluesseltes TOTP-Secret ohne Tenant-Zuordnung",
        )
    try:
        plaintext = decrypt_for_tenant(db, tenant_id, raw[len(_ENC_PREFIX):]).decode("utf-8")
    except Exception as exc:  # fail-closed: falscher KEK, korrupter Ciphertext ...
        logger.error(
            "TOTP-Secret nicht lesbar | reason=%s user_id=%s tenant_id=%s "
            "error_type=%s", REASON_DECRYPT_FAILED, user_id, tenant_id,
            type(exc).__name__,
        )
        raise TotpSecretStorageError(
            REASON_DECRYPT_FAILED,
            "TOTP-Secret konnte nicht entschluesselt werden "
            "(Schluesselkonfiguration pruefen)",
        ) from exc
    if not plaintext:
        logger.error(
            "TOTP-Secret nicht lesbar | reason=%s user_id=%s tenant_id=%s "
            "-- leerer Klartext", REASON_DECRYPT_FAILED, user_id, tenant_id,
        )
        raise TotpSecretStorageError(
            REASON_DECRYPT_FAILED, "Entschluesseltes TOTP-Secret ist leer",
        )
    return plaintext
