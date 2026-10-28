"""DEP-SEC-001 (AUDIT-FIX, 2026-10-26): Sicherheits-Untergrenzen fuer
PyJWT und python-multipart.

Vorher
------
- ``PyJWT==2.10.1``: ein Token mit ``crit``-Header (RFC 7515 4.1.11), der
  eine unbekannte Erweiterung verlangt, wurde akzeptiert statt abgelehnt
  (CVE-2026-32597). Betroffen ist der einzige Decode-Pfad
  ``services.auth.decode_access_token``, der jeden Bearer-Token sieht.
- ``python-multipart==0.0.12``: mehrere CPU-/Speicher-DoS beim Parsen von
  ``multipart/form-data`` und ``application/x-www-form-urlencoded``
  (u.a. CVE-2024-53981, CVE-2026-40347, CVE-2026-42561, CVE-2026-53539,
  CVE-2026-53540) sowie ``;`` als zusaetzlicher Feldtrenner im
  urlencoded-Parser (CVE-2026-53538, Parser-Differential). Starlette parst
  den Body vor der Auth-Pruefung (Upload-Route ``/products/import/csv``).

Nachher
-------
- ``PyJWT==2.15.1`` und ``python-multipart==0.0.32`` (gleiche Major-Linie,
  keine API-Aenderung im genutzten Umfang). Die Tests pruefen das
  Verhalten der installierten Bibliotheken, nicht nur den Pin.
"""
from __future__ import annotations

import asyncio
import datetime
import re
from pathlib import Path

import jwt
import pytest

_REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"


def _pinned_version(package: str) -> tuple[int, ...]:
    pattern = re.compile(
        rf"^{re.escape(package)}(?:\[[^\]]+\])?==([0-9.]+)\s*$", re.IGNORECASE
    )
    for line in _REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            return tuple(int(part) for part in match.group(1).split("."))
    raise AssertionError(f"{package} ist in requirements.txt nicht exakt gepinnt")


@pytest.mark.parametrize(
    ("package", "floor"),
    [
        # Letzte Fix-Version der bei der Pruefung 2026-10-26 gemeldeten
        # Advisories innerhalb der Major-Linie 2.x.
        ("PyJWT", (2, 15, 0)),
        # CVE-2026-53540 (negativer Content-Length) erst in 0.0.31 behoben.
        ("python-multipart", (0, 0, 31)),
    ],
)
def test_requirements_pin_is_not_below_security_floor(package, floor):
    assert _pinned_version(package) >= floor


def test_access_token_with_unknown_critical_header_is_rejected():
    from config import settings
    from services.auth import decode_access_token

    now = datetime.datetime.now(datetime.timezone.utc)
    token = jwt.encode(
        {
            "sub": "1",
            "iat": now,
            "exp": now + datetime.timedelta(minutes=5),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        settings.secret_key,
        algorithm=settings.algorithm,
        headers={"kid": settings.jwt_key_id, "crit": ["x-unknown-extension"]},
    )
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token)


def _parse_urlencoded(body: bytes) -> dict[str, str]:
    from starlette.datastructures import Headers
    from starlette.formparsers import FormParser

    async def stream():
        yield body
        yield b""

    async def run():
        parser = FormParser(
            Headers({"content-type": "application/x-www-form-urlencoded"}),
            stream(),
        )
        form = await parser.parse()
        return {key: str(value) for key, value in form.multi_items()}

    return asyncio.run(run())


def test_urlencoded_form_semicolon_is_not_a_field_separator():
    # WHATWG/urllib.parse trennen nur an "&". Ein zusaetzlicher ";"-Trenner
    # erzeugt ein Parser-Differential zu vorgelagerten Proxies/WAFs.
    # Alt-Parser fiel auf ";" zurueck, sobald kein "&" mehr folgte.
    assert _parse_urlencoded(b"a=1;b=2") == {"a": "1;b=2"}
    assert _parse_urlencoded(b"a=1;b=2&c=3") == {"a": "1;b=2", "c": "3"}
