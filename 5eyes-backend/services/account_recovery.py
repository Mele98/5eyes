"""Self-Service Konto-Wiederherstellung.

- **#25 2FA-Recovery-Codes**: Backup-Codes falls der Authenticator verloren geht.
- **#27 Passwort-Reset**: Token-basiert (sha256, Ablauf, single-use), analog zum
  Invite-Flow.

Schema-Disziplin (kein Eingriff in database.py): die Spalten werden im User-Modell
deklariert (``create_all`` fuer frische DBs) UND zur Laufzeit idempotent ergaenzt
(``ensure_account_recovery_columns``), damit bestehende SQLite-DBs ohne Aenderung an
``database.ensure_runtime_columns`` migriert werden. Sobald Codex' database.py-Refactor
steht, koennen die Spalten dort zentralisiert werden (rein kosmetisch).
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone, timedelta

RECOVERY_CODE_COUNT = 10
RESET_TOKEN_TTL_HOURS = 2

# (Spaltenname, SQLite-Typ) — additiv, nullable.
_COLUMNS = [
    ("reset_token_hash", "TEXT"),
    ("reset_token_expires_at", "TEXT"),
    ("totp_recovery_codes", "TEXT"),
]


def ensure_account_recovery_columns(db) -> None:
    """Idempotent fehlende Spalten auf 'users' ergaenzen (bestehende DBs).

    WICHTIG: DDL laeuft auf einer SEPARATEN Engine-Connection, NICHT auf der
    uebergebenen Session. Sonst wuerde ein rollback() bei bereits existierender
    Spalte die noch nicht committeten Aenderungen des Aufrufers (z.B.
    totp_enabled=1) mit zuruecksetzen.
    """
    from sqlalchemy import text
    try:
        bind = db.get_bind()
    except Exception:
        return
    with bind.connect() as conn:
        try:
            existing = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        except Exception:
            existing = set()
        for name, coltype in _COLUMNS:
            if name not in existing:
                try:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {coltype}"))
                except Exception:
                    pass  # parallel/already added -> ignorieren
        try:
            conn.commit()
        except Exception:
            pass


def _sha256(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ── 2FA Recovery Codes ──────────────────────────────────────────────────────
def generate_recovery_codes(n: int = RECOVERY_CODE_COUNT):
    """(klartext_codes, json_hash_blob). Klartext wird NUR EINMAL angezeigt."""
    codes = []
    for _ in range(max(1, n)):
        raw = secrets.token_hex(5)  # 10 Hex-Zeichen
        codes.append(f"{raw[:5]}-{raw[5:]}")
    blob = json.dumps([_sha256(c) for c in codes])
    return codes, blob


def consume_recovery_code(user, code: str) -> bool:
    """Prueft + verbraucht einen Recovery-Code. True bei Erfolg (Hash entfernt).

    Der Aufrufer ist fuer das ``db.commit()`` zustaendig (Persistenz des Verbrauchs).
    """
    blob = getattr(user, "totp_recovery_codes", None)
    if not blob:
        return False
    try:
        hashes = json.loads(blob)
    except (ValueError, TypeError):
        return False
    target = _sha256((code or "").strip())
    if target in hashes:
        hashes.remove(target)
        user.totp_recovery_codes = json.dumps(hashes)
        return True
    return False


def remaining_recovery_codes(user) -> int:
    blob = getattr(user, "totp_recovery_codes", None)
    if not blob:
        return 0
    try:
        return len(json.loads(blob))
    except (ValueError, TypeError):
        return 0


# ── Passwort-Reset-Token ────────────────────────────────────────────────────
def issue_reset_token(user) -> str:
    """Erzeugt Reset-Token, speichert sha256 + Ablauf am User. Klartext zurueck."""
    token = secrets.token_urlsafe(32)
    user.reset_token_hash = _sha256(token)
    expires = datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_TTL_HOURS)
    user.reset_token_expires_at = expires.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return token


def reset_token_valid(user, token: str) -> bool:
    stored = getattr(user, "reset_token_hash", None)
    if not stored or stored != _sha256((token or "").strip()):
        return False
    exp = getattr(user, "reset_token_expires_at", None)
    if not exp:
        return False
    try:
        exp_dt = datetime.strptime(
            str(exp).replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f"
        ).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    return datetime.now(timezone.utc) <= exp_dt


def clear_reset_token(user) -> None:
    user.reset_token_hash = None
    user.reset_token_expires_at = None
