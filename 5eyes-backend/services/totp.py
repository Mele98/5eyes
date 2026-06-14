"""TOTP (RFC 6238) ohne externe Dependency — fuer 2FA bei externen Logins (E1).

Standardlib-only (hmac/hashlib/base64/struct/secrets). Kompatibel mit Google/
Microsoft Authenticator (SHA1, 6 Stellen, 30s Periode).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

_PERIOD = 30
_DIGITS = 6


def generate_secret(num_bytes: int = 20) -> str:
    """Zufaelliges Base32-Secret (ohne Padding) — wird dem Authenticator uebergeben."""
    return base64.b32encode(secrets.token_bytes(num_bytes)).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int, digits: int = _DIGITS) -> str:
    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(secret_b32.upper() + pad)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_at(secret_b32: str, timestamp: float | None = None,
            period: int = _PERIOD, digits: int = _DIGITS) -> str:
    if timestamp is None:
        timestamp = time.time()
    return _hotp(secret_b32, int(timestamp // period), digits)


def verify(secret_b32: str, code: str, timestamp: float | None = None,
           period: int = _PERIOD, window: int = 1) -> bool:
    """Prueft `code` gegen das Secret im Zeitfenster +/-window Schritte (Drift-Toleranz)."""
    if not secret_b32 or not code:
        return False
    code = str(code).strip()
    if len(code) != _DIGITS or not code.isdigit():
        return False
    if timestamp is None:
        timestamp = time.time()
    counter = int(timestamp // period)
    for w in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret_b32, counter + w), code):
            return True
    return False


def provisioning_uri(secret_b32: str, account_name: str, issuer: str = "5eyes") -> str:
    """otpauth://-URI fuer den QR-Code im Authenticator."""
    label = quote(f"{issuer}:{account_name}")
    return (
        f"otpauth://totp/{label}?secret={secret_b32}"
        f"&issuer={quote(issuer)}&algorithm=SHA1&digits={_DIGITS}&period={_PERIOD}"
    )


def qr_svg_data_uri(uri: str) -> str | None:
    """SVG-QR-Code als data:-URI fuer die otpauth-URI — oder None, falls die
    optionale `segno`-Lib fehlt (dann zeigt das Frontend nur das Text-Secret).
    Dependency-soft: kein 500, wenn die Lib im Deploy fehlt."""
    try:
        import segno  # optional
    except Exception:
        return None
    try:
        import io
        buf = io.BytesIO()
        segno.make(uri, error="m").save(buf, kind="svg", scale=4, border=2, dark="#0a1423")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return "data:image/svg+xml;base64," + b64
    except Exception:
        return None
