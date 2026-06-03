"""Sprint U-57 (Roadmap-Punkt 57, 2026-06-03): Password-Hash-Rotation Audit.

Hintergrund
-----------
bcrypt nutzt Salt-per-Hash (im Hash gespeichert) — kein klassisches
'Salt-Rotation'. Was rotiert wird: Cost-Factor (rounds). U-57 liefert
Audit + Helper (non-breaking).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import bcrypt as _bcrypt
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.password_audit import (  # noqa: E402
    BCRYPT_TARGET_ROUNDS,
    audit_user_password_strength,
    get_bcrypt_rounds,
    get_bcrypt_variant,
    needs_rehash,
)


def _hash_with_rounds(password: str, rounds: int) -> str:
    return _bcrypt.hashpw(
        password.encode("utf-8"), _bcrypt.gensalt(rounds=rounds),
    ).decode("utf-8")


# ---------------------------------------------------------------------------
# get_bcrypt_rounds — Parser
# ---------------------------------------------------------------------------

def test_rounds_parses_real_bcrypt_hash_rounds_10():
    h = _hash_with_rounds("password", 10)
    assert get_bcrypt_rounds(h) == 10


def test_rounds_parses_real_bcrypt_hash_rounds_12():
    h = _hash_with_rounds("password", 12)
    assert get_bcrypt_rounds(h) == 12


def test_rounds_parses_real_bcrypt_hash_rounds_14():
    h = _hash_with_rounds("password", 14)
    assert get_bcrypt_rounds(h) == 14


def test_rounds_handles_variant_2a():
    """$2a$ ist Legacy-Variante, parser muss sie erkennen."""
    h = "$2a$10$abcdefghijklmnopqrstuv.abcdefghijklmnopqrstuvabcdefghij"
    assert get_bcrypt_rounds(h) == 10


def test_rounds_handles_variant_2y():
    h = "$2y$11$abcdefghijklmnopqrstuv.abcdefghijklmnopqrstuvabcdefghij"
    assert get_bcrypt_rounds(h) == 11


def test_rounds_none_for_invalid_hash():
    assert get_bcrypt_rounds("not-a-hash") is None
    assert get_bcrypt_rounds("") is None
    assert get_bcrypt_rounds(None) is None


def test_rounds_none_for_legacy_md5_or_sha1():
    """MD5/SHA1-Hashes haben kein bcrypt-Format -> None."""
    md5 = "5f4dcc3b5aa765d61d8327deb882cf99"
    sha1 = "5baa61e4c9b93f3f0682250b6cf8331b7ee68fd8"
    assert get_bcrypt_rounds(md5) is None
    assert get_bcrypt_rounds(sha1) is None


def test_rounds_handles_whitespace_padded():
    h = _hash_with_rounds("password", 12)
    assert get_bcrypt_rounds(f"  {h}  ") == 12


# ---------------------------------------------------------------------------
# get_bcrypt_variant
# ---------------------------------------------------------------------------

def test_variant_2b_for_default_bcrypt():
    """bcrypt-Lib erzeugt 2b standardmaessig."""
    h = _hash_with_rounds("password", 12)
    assert get_bcrypt_variant(h) == "2b"


def test_variant_2a_recognized():
    h = "$2a$10$abcdefghijklmnopqrstuv.abcdefghijklmnopqrstuvabcdefghij"
    assert get_bcrypt_variant(h) == "2a"


def test_variant_none_for_invalid():
    assert get_bcrypt_variant("invalid") is None
    assert get_bcrypt_variant(None) is None


# ---------------------------------------------------------------------------
# needs_rehash
# ---------------------------------------------------------------------------

def test_needs_rehash_when_below_target():
    h = _hash_with_rounds("password", 10)
    assert needs_rehash(h, target_rounds=12) is True


def test_no_rehash_at_target_rounds():
    h = _hash_with_rounds("password", 12)
    assert needs_rehash(h, target_rounds=12) is False


def test_no_rehash_above_target():
    h = _hash_with_rounds("password", 13)
    assert needs_rehash(h, target_rounds=12) is False


def test_needs_rehash_for_invalid_hash():
    """Kein bcrypt-Hash -> sicherheitshalber Rotation triggern."""
    assert needs_rehash("not-bcrypt") is True
    assert needs_rehash("") is True
    assert needs_rehash(None) is True


def test_default_target_is_5eyes_constant():
    """U-57 default rounds = 12."""
    assert BCRYPT_TARGET_ROUNDS == 12


# ---------------------------------------------------------------------------
# audit_user_password_strength
# ---------------------------------------------------------------------------

def _user(**overrides):
    base = {
        "id": "user-001",
        "is_active": True,
        "deleted_at": None,
        "password_hash": _hash_with_rounds("password", 12),
        "hashed_password": None,
    }
    base.update(overrides)
    return MagicMock(**base)


def _stub_db(users):
    db = MagicMock()
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.all.return_value = users
    db.query.return_value = chain
    return db


def test_audit_empty_db():
    db = _stub_db([])
    result = audit_user_password_strength(db)
    assert result["total_users"] == 0
    assert result["is_compliant"] is True
    assert result["target_rounds"] == 12


def test_audit_all_compliant_users():
    users = [
        _user(id="u1", password_hash=_hash_with_rounds("a", 12)),
        _user(id="u2", password_hash=_hash_with_rounds("b", 13)),
    ]
    db = _stub_db(users)
    result = audit_user_password_strength(db)
    assert result["total_users"] == 2
    assert result["users_with_valid_bcrypt"] == 2
    assert result["users_needing_rehash"] == 0
    assert result["is_compliant"] is True
    assert result["rounds_distribution"][12] == 1
    assert result["rounds_distribution"][13] == 1


def test_audit_flags_stale_rounds_users():
    """User mit rounds=10 -> needs_rehash."""
    users = [
        _user(id="u1", password_hash=_hash_with_rounds("a", 12)),
        _user(id="u2", password_hash=_hash_with_rounds("b", 10)),
    ]
    db = _stub_db(users)
    result = audit_user_password_strength(db)
    assert result["users_needing_rehash"] == 1
    assert result["is_compliant"] is False


def test_audit_flags_invalid_hash():
    """User mit Legacy-MD5-Hash -> in invalid + rehash."""
    users = [
        _user(id="u1", password_hash="5f4dcc3b5aa765d61d8327deb882cf99"),
    ]
    db = _stub_db(users)
    result = audit_user_password_strength(db)
    assert result["users_with_invalid_hash"] == 1
    assert result["users_needing_rehash"] == 1
    assert result["is_compliant"] is False


def test_audit_falls_back_to_hashed_password_field():
    """Falls Schema 'hashed_password' statt 'password_hash' nutzt — Drift-Schutz."""
    users = [
        _user(
            id="u1",
            password_hash=None,
            hashed_password=_hash_with_rounds("a", 12),
        ),
    ]
    db = _stub_db(users)
    result = audit_user_password_strength(db)
    assert result["users_with_valid_bcrypt"] == 1


def test_audit_custom_target_rounds_override():
    """target_rounds-Override fuer Strict-Mode Audit (z.B. rounds>=14)."""
    users = [_user(password_hash=_hash_with_rounds("a", 12))]
    db = _stub_db(users)
    result = audit_user_password_strength(db, target_rounds=14)
    assert result["target_rounds"] == 14
    assert result["users_needing_rehash"] == 1
    assert result["is_compliant"] is False


def test_audit_db_error_returns_degraded():
    db = MagicMock()
    db.query.side_effect = RuntimeError("schema mismatch")
    result = audit_user_password_strength(db)
    assert result["total_users"] == 0
    assert result["is_compliant"] is True
    assert result["reference"] == "OWASP Password Storage Cheat Sheet 2026"


def test_audit_variant_distribution_counted():
    """Variant 2a vs 2b in distribution."""
    users = [
        _user(id="u1", password_hash=_hash_with_rounds("a", 12)),  # 2b
        _user(id="u2", password_hash="$2a$12$" + "a" * 53),  # 2a
    ]
    db = _stub_db(users)
    result = audit_user_password_strength(db)
    assert result["variant_distribution"].get("2b", 0) == 1
    assert result["variant_distribution"].get("2a", 0) == 1


# ---------------------------------------------------------------------------
# Smoke: existierender auth.hash_password produziert konformen Hash
# ---------------------------------------------------------------------------

def test_existing_hash_password_produces_target_compliant_hash():
    """5eyes hash_password() default >= 12 rounds (OWASP-konform)."""
    from services.auth import hash_password
    h = hash_password("test-password")
    rounds = get_bcrypt_rounds(h)
    assert rounds is not None, "hash_password() liefert nicht-bcrypt"
    assert rounds >= BCRYPT_TARGET_ROUNDS, (
        f"hash_password() produziert rounds={rounds}, Target ist "
        f">= {BCRYPT_TARGET_ROUNDS}. OWASP-konform-Drift-Verdacht."
    )
