"""Sprint U-59 (Roadmap-Punkt 59, 2026-06-01): Bearer-Token-TTL Audit.

Hintergrund
-----------
Pre-U-59 war die Token-TTL nur durch validate_positive_numbers
abgesichert (>0). Keine Obergrenze in production -> jemand koennte
versehentlich access_token_expire_minutes=99999 setzen und Tokens mit
JAHRE-Gueltigkeit ausstellen. Bei Token-Diebstahl waere das
Mitigation-Window viel zu gross.

Auch: create_access_token setzte nur 'exp', kein 'iat' (issued-at).
Ohne iat kann ein Audit-Log nicht rekonstruieren WANN ein Token
ausgestellt wurde.

Fix-Coverage
------------
- Production cap 1440 min (24h)
- iat im Token (timezone-aware UTC)
- exp/iat aware-UTC (kein naive-Drift)
- expired token rejected
- missing exp rejected (TypeError-Pfad)
- missing sub rejected
- Algorithm allowlist verhindert alg-confusion (kein 'none')
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
import jwt
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import Settings, settings  # noqa: E402
from services.auth import create_access_token, get_current_user  # noqa: E402


def _set_production_security_env(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', 'strong-random-key-1234567890abcdefghij')
    monkeypatch.setenv('DB_USE_SQLCIPHER', 'true')
    monkeypatch.setenv('DB_KEY', 'strong-db-key-abc1234567890')
    monkeypatch.setenv('CORS_ORIGINS', '["https://app.5eyes.local"]')


# ---------------------------------------------------------------------------
# Settings-Validator (U-59 production cap)
# ---------------------------------------------------------------------------

def test_production_rejects_excessive_ttl(monkeypatch):
    """Production mit TTL > 24h soll ValidationError werfen."""
    _set_production_security_env(monkeypatch)
    monkeypatch.setenv('ACCESS_TOKEN_EXPIRE_MINUTES', '2880')  # 48h
    with pytest.raises(ValidationError, match=r'exceeds 1440'):
        Settings()


def test_production_accepts_exactly_24h_ttl(monkeypatch):
    """1440 (genau 24h) soll OK sein."""
    _set_production_security_env(monkeypatch)
    monkeypatch.setenv('ACCESS_TOKEN_EXPIRE_MINUTES', '1440')
    s = Settings()
    assert s.access_token_expire_minutes == 1440


def test_development_allows_arbitrary_ttl(monkeypatch):
    """Dev darf lange Tokens haben (Long-running Integration-Tests etc.)."""
    monkeypatch.setenv('APP_ENV', 'development')
    monkeypatch.setenv('ACCESS_TOKEN_EXPIRE_MINUTES', '99999')
    s = Settings()
    assert s.access_token_expire_minutes == 99999


def test_default_ttl_is_8h_workday():
    """Default 480 = 8h Berater-Workday."""
    assert settings.access_token_expire_minutes == 480


def test_zero_ttl_rejected_by_existing_validator(monkeypatch):
    """validate_positive_numbers verhindert 0/negative — drift-test."""
    monkeypatch.setenv('ACCESS_TOKEN_EXPIRE_MINUTES', '0')
    with pytest.raises(ValidationError):
        Settings()


# ---------------------------------------------------------------------------
# create_access_token (iat + exp aware-UTC)
# ---------------------------------------------------------------------------

def test_create_access_token_includes_iat():
    """U-59: iat (issued-at) muss im Token sein fuer Audit-Trail."""
    token = create_access_token({'sub': 'user-x'})
    payload = jwt.decode(
        token, settings.secret_key, algorithms=[settings.algorithm],
        options={'verify_exp': False},
    )
    assert 'iat' in payload, "Token muss 'iat' (issued-at) enthalten"


def test_create_access_token_iat_is_close_to_now():
    """iat sollte aktuelle UTC-Zeit sein (Toleranz 5s)."""
    before = datetime.now(timezone.utc).timestamp()
    token = create_access_token({'sub': 'user-x'})
    after = datetime.now(timezone.utc).timestamp()
    payload = jwt.decode(
        token, settings.secret_key, algorithms=[settings.algorithm],
        options={'verify_exp': False},
    )
    iat = float(payload['iat'])
    assert before - 1 <= iat <= after + 1, (
        f"iat={iat} liegt nicht im Bereich [{before}, {after}]"
    )


def test_create_access_token_exp_respects_ttl():
    """exp = iat + TTL (in Sekunden)."""
    token = create_access_token({'sub': 'user-x'})
    payload = jwt.decode(
        token, settings.secret_key, algorithms=[settings.algorithm],
        options={'verify_exp': False},
    )
    iat = float(payload['iat'])
    exp = float(payload['exp'])
    expected_delta = settings.access_token_expire_minutes * 60
    actual_delta = exp - iat
    assert abs(actual_delta - expected_delta) < 2, (
        f"exp-iat={actual_delta}s, erwartet {expected_delta}s (TTL)"
    )


def test_create_access_token_custom_expires_delta_overrides_default():
    """expires_delta-Argument hat Vorrang vor Settings-TTL."""
    token = create_access_token(
        {'sub': 'user-x'}, expires_delta=timedelta(minutes=5),
    )
    payload = jwt.decode(
        token, settings.secret_key, algorithms=[settings.algorithm],
        options={'verify_exp': False},
    )
    iat = float(payload['iat'])
    exp = float(payload['exp'])
    assert 290 < (exp - iat) < 310, "5min override nicht respektiert"


# ---------------------------------------------------------------------------
# get_current_user (Auth-Decode-Pfad)
# ---------------------------------------------------------------------------

def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme='Bearer', credentials=token)


def test_expired_token_rejected():
    """Token mit exp in der Vergangenheit -> 401."""
    expired = create_access_token(
        {'sub': 'user-x'}, expires_delta=timedelta(seconds=-10),
    )
    db_mock = MagicMock()
    with pytest.raises(HTTPException) as exc:
        get_current_user(_credentials(expired), db=db_mock)
    assert exc.value.status_code == 401


def test_token_missing_exp_rejected():
    """Token ohne exp -> 401 (TypeError-Pfad in get_current_user)."""
    raw = jwt.encode(
        {'sub': 'user-x'},  # KEIN exp
        settings.secret_key,
        algorithm=settings.algorithm,
    )
    db_mock = MagicMock()
    with pytest.raises(HTTPException) as exc:
        get_current_user(_credentials(raw), db=db_mock)
    assert exc.value.status_code == 401


def test_token_missing_sub_rejected():
    """Token mit gueltigem exp aber ohne sub -> 401."""
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    raw = jwt.encode(
        {'exp': future},  # KEIN sub
        settings.secret_key,
        algorithm=settings.algorithm,
    )
    db_mock = MagicMock()
    with pytest.raises(HTTPException) as exc:
        get_current_user(_credentials(raw), db=db_mock)
    assert exc.value.status_code == 401


def test_token_wrong_signature_rejected():
    """Token mit falschem Secret signiert -> 401."""
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    raw = jwt.encode(
        {'sub': 'user-x', 'exp': future},
        'WRONG_SECRET_KEY_TOTALLY_DIFFERENT',
        algorithm=settings.algorithm,
    )
    db_mock = MagicMock()
    with pytest.raises(HTTPException) as exc:
        get_current_user(_credentials(raw), db=db_mock)
    assert exc.value.status_code == 401


def test_token_alg_none_attack_rejected():
    """alg=none Angriff: Token ohne Signatur muss abgelehnt werden.

    python-jose erlaubt 'none' nur wenn explizit in algorithms-Liste.
    Settings.algorithm='HS256' -> 'none' wird nicht akzeptiert.
    """
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    # Token mit alg=none manuell konstruieren
    import base64
    import json
    header = base64.urlsafe_b64encode(
        json.dumps({'alg': 'none', 'typ': 'JWT'}).encode()
    ).rstrip(b'=').decode()
    payload_dict = {'sub': 'user-x', 'exp': int(future.timestamp())}
    payload = base64.urlsafe_b64encode(
        json.dumps(payload_dict).encode()
    ).rstrip(b'=').decode()
    forged = f"{header}.{payload}."  # kein signature
    db_mock = MagicMock()
    with pytest.raises(HTTPException) as exc:
        get_current_user(_credentials(forged), db=db_mock)
    assert exc.value.status_code == 401


def test_token_wrong_algorithm_rejected():
    """Algorithm-Allowlist (Anti-Confusion): ein mit HS512 statt HS256
    signiertes Token muss abgelehnt werden, weil der Server hart auf
    algorithms=[settings.algorithm] pinnt. Regression-Guard fuer die
    jose->PyJWT-Migration (2026-07-18) — PyJWT wirft InvalidAlgorithmError,
    die als PyJWTError zu 401 wird.
    """
    assert settings.algorithm == 'HS256'  # Praemisse des Tests
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    raw = jwt.encode(
        {'sub': 'user-x', 'exp': future},
        settings.secret_key,          # gleiches Secret ...
        algorithm='HS512',            # ... aber nicht erlaubter Algorithmus
    )
    db_mock = MagicMock()
    with pytest.raises(HTTPException) as exc:
        get_current_user(_credentials(raw), db=db_mock)
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Settings-Doku / Schema-Drift-Schutz
# ---------------------------------------------------------------------------

def test_algorithm_is_hs256_for_now():
    """HS256 ist aktuell. Falls jemand auf 'none' wechselt -> Alarm."""
    assert settings.algorithm == 'HS256'
    assert settings.algorithm.lower() != 'none'
