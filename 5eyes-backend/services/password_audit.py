"""Sprint U-57 (2026-06-03): Passwort-Hash Salt/Rounds-Rotation Audit.

Hintergrund
-----------
services/auth.py hash_password() nutzt bcrypt.gensalt() ohne explizite
rounds-Angabe -> default 12 (bcrypt-Industry-Standard). bcrypt
verwendet Salt-per-Hash (im Hash gespeichert), also gibt es kein
'Salt-Rotation' im klassischen Sinn.

Was ROTIERT wird, ist die Cost-Factor (rounds): wenn Hardware
schneller wird, sollten neue Hashes mit hoeheren rounds erstellt
werden. Bestehende User-Hashes koennen "lazy" beim naechsten
erfolgreichen Login transparent aktualisiert werden ("password
rehash on auth" Pattern, siehe Django/Flask-Security).

Dieses Modul liefert:
- get_bcrypt_rounds(hashed): parse rounds aus dem Hash-String
- needs_rehash(hashed, target_rounds): True wenn Cost-Factor < target
- audit_user_password_strength(db): Cluster-Audit ueber alle User

Non-breaking: kein Auto-Rehash in verify_password (waere Breaking-
Change im Auth-Pfad). Nur Sichtbarkeit + Helper. Wer Auto-Rehash
will, ruft needs_rehash() im Login-Flow auf.

bcrypt-Hash-Format (PHC)
-------------------------
$2b$12$<22-char-salt><31-char-hash>
 │  │  └─ rounds (log2): 12 = 2^12 = 4096 iterations
 │  └─ variant: 2a, 2b, 2x, 2y
 └─ algorithm marker

Industrie-Empfehlung 2026
-------------------------
- OWASP: bcrypt rounds >= 10 (4 sec/hash auf Server-CPU)
- BSI TR-02102: regelmaessige Kostenfaktor-Anhebung
- 5eyes-Default: 12 (bewusst hoeher als OWASP-Min)
"""
from __future__ import annotations

import re
from typing import Any, Optional

from sqlalchemy.orm import Session


# 5eyes Default Cost-Factor — beim Login wird gegen diese Zahl geprueft.
# Hashes mit kleineren rounds gelten als "rehash needed".
BCRYPT_TARGET_ROUNDS = 12

# Format des bcrypt-Hash-Headers (PHC).
# Beispiele: $2a$10$..., $2b$12$..., $2y$13$...
_BCRYPT_HEADER_RE = re.compile(
    r"^\$(?P<variant>2[abxy])\$(?P<rounds>\d{2})\$"
)


def get_bcrypt_rounds(hashed: Any) -> Optional[int]:
    """Liefert Cost-Factor aus bcrypt-Hash-String, None bei invalidem Format."""
    if hashed is None:
        return None
    s = str(hashed).strip()
    if not s:
        return None
    m = _BCRYPT_HEADER_RE.match(s)
    if not m:
        return None
    try:
        return int(m.group("rounds"))
    except (TypeError, ValueError):
        return None


def get_bcrypt_variant(hashed: Any) -> Optional[str]:
    """Liefert die bcrypt-Variante (2a/2b/2x/2y) aus dem Hash."""
    if hashed is None:
        return None
    m = _BCRYPT_HEADER_RE.match(str(hashed).strip())
    return m.group("variant") if m else None


def needs_rehash(hashed: Any, target_rounds: int = BCRYPT_TARGET_ROUNDS) -> bool:
    """True wenn der Hash mit weniger als target_rounds erstellt wurde
    ODER kein gueltiges bcrypt-Format ist (= unbekannter Algo)."""
    rounds = get_bcrypt_rounds(hashed)
    if rounds is None:
        return True
    return rounds < target_rounds


def audit_user_password_strength(
    db: Session, *, target_rounds: int = BCRYPT_TARGET_ROUNDS,
) -> dict[str, Any]:
    """Cluster-Audit: wie viele User-Hashes brauchen Rotation?

    Output-Schema
    -------------
    {
      'target_rounds': 12,
      'total_users': N,
      'users_with_valid_bcrypt': N,
      'users_with_invalid_hash': N,
      'users_needing_rehash': N,
      'rounds_distribution': {10: 5, 11: 2, 12: 100, 13: 3},
      'variant_distribution': {'2b': 108, '2a': 2},
      'is_compliant': bool,    # alle aktiven User >= target_rounds
      'reference': 'OWASP Password Storage Cheat Sheet 2026',
    }

    Robust: bei Schema-Mismatch -> degraded leeres Schema.
    """
    empty = {
        "target_rounds": target_rounds,
        "total_users": 0,
        "users_with_valid_bcrypt": 0,
        "users_with_invalid_hash": 0,
        "users_needing_rehash": 0,
        "rounds_distribution": {},
        "variant_distribution": {},
        "is_compliant": True,
        "reference": "OWASP Password Storage Cheat Sheet 2026",
    }
    try:
        from models.users import User
        users = (
            db.query(User)
            .filter(User.deleted_at.is_(None))
            .filter(User.is_active == True)  # noqa: E712
            .all()
        )
    except Exception:  # noqa: BLE001
        return empty

    if not users:
        return empty

    rounds_dist: dict[int, int] = {}
    variant_dist: dict[str, int] = {}
    valid_count = 0
    invalid_count = 0
    rehash_count = 0
    for u in users:
        hashed = getattr(u, "password_hash", None) or getattr(u, "hashed_password", None)
        rounds = get_bcrypt_rounds(hashed)
        variant = get_bcrypt_variant(hashed)
        if rounds is None:
            invalid_count += 1
            rehash_count += 1
            continue
        valid_count += 1
        rounds_dist[rounds] = rounds_dist.get(rounds, 0) + 1
        if variant:
            variant_dist[variant] = variant_dist.get(variant, 0) + 1
        if rounds < target_rounds:
            rehash_count += 1

    return {
        "target_rounds": target_rounds,
        "total_users": len(users),
        "users_with_valid_bcrypt": valid_count,
        "users_with_invalid_hash": invalid_count,
        "users_needing_rehash": rehash_count,
        "rounds_distribution": rounds_dist,
        "variant_distribution": variant_dist,
        "is_compliant": rehash_count == 0,
        "reference": "OWASP Password Storage Cheat Sheet 2026",
    }
