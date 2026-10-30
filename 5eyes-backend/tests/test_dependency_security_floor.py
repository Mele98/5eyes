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

DEP-SEC-002 (AUDIT-FIX, 2026-10-27): Starlette und cryptography
------------------------------------------------------------------
Vorher: ``fastapi==0.115.0`` zog ``starlette==0.38.6``; ``cryptography``
war nur als Bereich ``>=42,<45`` angegeben (frische Installation 44.0.3,
die Desktop-venv hatte abweichend 46.0.5).

- Starlette 0.38.6: ``request.url``/``request.base_url`` wurden aus einem
  ungeprueften ``Host``-Header zusammengesetzt (CVE-2026-48710,
  CVE-2026-54282; ``routers/auth.py`` nutzt ``request.base_url`` als
  Rueckfall fuer Links), ``max_fields`` wurde fuer urlencoded-Formulare
  ignoriert (CVE-2026-54283), ``StaticFiles`` folgte unter Windows
  UNC-Pfaden (CVE-2026-48818), dazu Formular-DoS (CVE-2024-47874,
  CVE-2025-54121). Die 0.4x-Linie braechte zusaetzlich CVE-2025-62727
  (Range-DoS auf ``StaticFiles``); alle Fixes gibt es nur in 1.x.
- cryptography 44.0.3: CVE-2026-26007, CVE-2026-34073, CVE-2026-69247,
  CVE-2026-69248, CVE-2026-69249 und GHSA-537c-gmf6-5ccf (statisch
  gelinktes OpenSSL); letzte Fix-Version 50.0.0.

Nachher: ``fastapi==0.136.3`` + ``starlette==1.10.0`` und
``cryptography==50.0.2``, alle exakt gepinnt.
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
        # DEP-SEC-002: CVE-2026-54283 erst in 1.3.1 behoben.
        ("starlette", (1, 3, 1)),
        # DEP-SEC-002: CVE-2026-69247 erst in 50.0.0 behoben.
        ("cryptography", (50, 0, 0)),
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


# ---------------------------------------------------------------------------
# DEP-SEC-002: installierte Bibliotheken und ihr Verhalten
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("distribution", "floor"),
    [("starlette", (1, 3, 1)), ("cryptography", (50, 0, 0))],
)
def test_installed_library_is_not_below_security_floor(distribution, floor):
    from importlib.metadata import version

    installed = version(distribution)
    parts = tuple(int(part) for part in re.findall(r"\d+", installed)[:3])
    assert parts >= floor, f"{distribution} {installed} liegt unter {floor}"


def _request(*, body=b"", content_type=b"text/plain", host=b"testserver"):
    from starlette.requests import Request

    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/x",
        "raw_path": b"/x",
        "query_string": b"",
        "headers": [(b"content-type", content_type), (b"host", host)],
        "scheme": "http",
        "server": ("testserver", 80),
    }
    return Request(scope, receive)


def test_urlencoded_form_enforces_max_fields():
    # CVE-2026-54283: alt lieferte form(max_fields=1) alle drei Felder.
    from starlette.formparsers import MultiPartException

    request = _request(
        body=b"a=1&b=2&c=3", content_type=b"application/x-www-form-urlencoded"
    )

    async def run():
        return await request.form(max_fields=1)

    with pytest.raises(MultiPartException):
        asyncio.run(run())


@pytest.mark.parametrize(
    "host", [b"evil.example/inject?", b"evil.example#frag", b"user@evil.example"]
)
def test_invalid_host_header_does_not_reach_request_url(host):
    # CVE-2026-48710 / CVE-2026-54282: alt wurde aus "evil.example/inject?"
    # die URL http://evil.example/inject?/x (Host und Pfad verfaelscht).
    request = _request(host=host)
    assert request.url.hostname != "evil.example"
    assert request.url.path == "/x"
    assert str(request.base_url) == "http://testserver/"
