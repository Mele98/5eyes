"""SEC-005 (Codex-Audit 2026-08-26, docs/audits/2026-08-26-data-lifecycle-
crypto-browser-followup-audit.md): TOTP-Secret-at-rest-Verschluesselung.

`models/users.py::User.totp_secret` speicherte den Base32-Seed bisher IMMER
im Klartext. `services/tenant_crypto.py` bietet fertige Envelope-Encryption-
Helfer, wurde aber laut Audit nirgends fuer echte Geschaeftsfelder verwendet
(siehe `tests/test_landmine_functions_unused_guard.py`).

Scope dieser Fassung (bewusst NICHT der volle Fixvertrag)
-----------------------------------------------------------
- NUR neu angelegte TOTP-Secrets (`/auth/2fa/setup`) werden verschluesselt
  gespeichert -- und auch das NUR, wenn der User einen `tenant_id` hat, der
  auf einen tatsaechlich existierenden Tenant zeigt. Reiner Tier-1-Desktop-
  Betrieb ohne Tenant-Zuordnung ist von diesem Fix NICHT betroffen:
  unveraendertes Klartext-Verhalten, kein neues Schluesselmaterial noetig,
  KEIN 2FA-Lockout-Risiko fuer bestehende Tier-1-Deployments.
- Bestehende, bereits im Klartext gespeicherte Secrets werden NICHT
  rueckwirkend verschluesselt (kein destruktives Rewrite bestehender Zeilen).
  `load_totp_secret()` erkennt beide Formate (Dual-Read) am `enc1:`-Prefix.
- Jeder Verschluesselungsfehler beim Schreiben (z.B. `cryptography` fehlt,
  Tenant zwischen Check und Encrypt geloescht) faellt defensiv auf
  Klartext-Speicherung zurueck -- 2FA-Setup darf dadurch NIE hart scheitern.
  Ein Entschluesselungsfehler beim Lesen liefert "" (totp_verify() lehnt
  dann korrekt jeden Code ab) statt eine Exception zu werfen, die den
  Login-Pfad crashen wuerde.

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
    TenantCryptoError,
    decrypt_for_tenant,
    encrypt_for_tenant,
)

logger = logging.getLogger(__name__)

# Marker-Prefix fuer verschluesselte Secrets. Base32-TOTP-Secrets bestehen
# nur aus [A-Z2-7] -- "enc1:" ist damit eindeutig von jedem legitimen
# Klartext-Secret unterscheidbar.
_ENC_PREFIX = "enc1:"


def store_totp_secret(db: Session, user: User, plaintext_secret: str) -> str:
    """Liefert den Wert, der in `User.totp_secret` persistiert werden soll.

    Verschluesselt NUR wenn der User einen `tenant_id` hat, der zu einem
    tatsaechlich vorhandenen Tenant gehoert. Tier-1-Default (kein tenant_id)
    bleibt unveraendert Klartext.
    """
    tenant_id = getattr(user, "tenant_id", None)
    if not tenant_id:
        return plaintext_secret
    try:
        ciphertext = encrypt_for_tenant(db, tenant_id, plaintext_secret.encode("utf-8"))
    except TenantCryptoError as exc:
        logger.warning(
            "TOTP-Secret-Verschluesselung fehlgeschlagen fuer tenant_id=%s -- "
            "speichere Klartext (2FA-Setup darf nicht hart scheitern): %s",
            tenant_id, exc,
        )
        return plaintext_secret
    return _ENC_PREFIX + ciphertext


def load_totp_secret(db: Session, user: User) -> str:
    """Liefert das Klartext-Base32-Secret -- unabhaengig davon, ob es
    verschluesselt oder (legacy) im Klartext gespeichert ist (Dual-Read).

    Liefert "" bei jedem Entschluesselungsfehler statt zu werfen, damit
    `totp_verify("", code)` konsistent False liefert (fail-closed auf
    Verify-Ebene, kein 500 im Login-/2FA-Pfad).
    """
    raw = getattr(user, "totp_secret", None) or ""
    if not raw.startswith(_ENC_PREFIX):
        return raw
    tenant_id = getattr(user, "tenant_id", None)
    if not tenant_id:
        # Kann nur vorkommen, wenn tenant_id nachtraeglich vom User entfernt
        # wurde, nachdem store_totp_secret() bereits verschluesselt hat.
        logger.error(
            "TOTP-Secret hat enc1-Prefix, aber User %s hat keinen tenant_id "
            "-- kann nicht entschluesseln.", getattr(user, "id", "?"),
        )
        return ""
    try:
        return decrypt_for_tenant(db, tenant_id, raw[len(_ENC_PREFIX):]).decode("utf-8")
    except TenantCryptoError as exc:
        logger.error(
            "TOTP-Secret-Entschluesselung fehlgeschlagen fuer tenant_id=%s: %s",
            tenant_id, exc,
        )
        return ""
