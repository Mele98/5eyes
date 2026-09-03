"""RESOURCE-001 (Codex-Audit 2026-08-27, docs/audits/2026-08-27-request-
ingestion-and-resource-governance-audit.md): main.py registrierte bisher nur
RequestContextMiddleware + CORS -- kein Layer zaehlte je die tatsaechlich
eingehenden Request-Body-Bytes, BEVOR FastAPI/Starlette JSON oder Multipart
vollstaendig puffert/parst. Der Audit reproduzierte das live gegen den
oeffentlichen, unauthentifizierten /auth/password-reset/request-Endpoint:
ein 8-MiB-Body wurde komplett geparst und mit HTTP 200 beantwortet, obwohl
das Requestmodell nur zwei kurze optionale Strings erwartet.

Fix: core.middleware.MaxBodySizeMiddleware (reine ASGI-Middleware, siehe
Docstring dort), registriert als aeusserste Schicht in main.py, konfigurierbar
via settings.max_request_body_bytes (config.py, Default 10 MiB).

Getestet:
- White-Box: frueher Abbruch anhand eines ueberlangen Content-Length-Headers,
  OHNE die innere App/receive() je aufzurufen (kein Byte wird gelesen).
- White-Box: fehlt Content-Length (chunked-Simulation) ODER luegt der Header
  (deklariert klein, tatsaechlicher Stream gross), bricht der receive()-
  Wrapper beim ersten Byte ueber dem Limit ab -- beweisbar VOR
  Vollmaterialisierung eines absichtlich sehr grossen synthetischen Streams.
- Regression: normal kleine Bodies (mit und ohne Content-Length-Header)
  passieren unveraendert.
- Integration: eine aus receive() geworfene HTTPException(413) wird von der
  echten FastAPI/Starlette-Pipeline (ExceptionMiddleware) automatisch in eine
  saubere JSON-413-Antwort uebersetzt -- kein eigener try/except in der
  Middleware noetig.
- End-to-End gegen die echte main.app am urspruenglichen Audit-Repro-Pfad
  (/auth/password-reset/request): ueberlanger Body -> 413 (Guard/DB/Mail
  werden nie erreicht); normal-grosser Body bleibt unveraendert wie vor dem
  Fix (Regression auf dem echten Produktionspfad).
- config.py: Default 10 MiB, Validator lehnt <=0 ab.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from pydantic import BaseModel

from config import Settings
from core.middleware import MaxBodySizeMiddleware


class _EchoBody(BaseModel):
    """Modulweit (nicht innerhalb der Testfunktion) definiert: dieses Modul
    hat `from __future__ import annotations` (PEP 563) -- ein lokal in der
    Testfunktion definiertes Pydantic-Modell waere fuer FastAPIs
    `get_type_hints()` beim Aufloesen des String-Annotation nicht erreichbar
    (kein Zugriff auf Funktions-Locals) und wuerde STILLSCHWEIGEND als
    Query-Parameter statt als Body behandelt (422 'query.body missing')."""
    padding: str


# ---------------------------------------------------------------------------
# White-Box: fruehe Ablehnung ueber Content-Length
# ---------------------------------------------------------------------------

def test_early_content_length_rejection_never_touches_app_or_receive():
    """Ein deklarierter Content-Length ueber dem Limit muss SOFORT mit 413
    beantwortet werden -- ohne die innere App aufzurufen und ohne ein
    einziges Byte per receive() zu lesen."""
    sent: list[dict] = []

    async def _send(message):
        sent.append(message)

    async def _receive_must_not_be_called():
        raise AssertionError(
            "receive() darf bei frueher Content-Length-Ablehnung nie "
            "aufgerufen werden"
        )

    async def _app_must_not_be_called(scope, receive, send):
        raise AssertionError(
            "die innere App darf bei frueher Content-Length-Ablehnung nie "
            "aufgerufen werden"
        )

    mw = MaxBodySizeMiddleware(_app_must_not_be_called, max_bytes=1024)
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/x",
        "headers": [(b"content-length", b"2048")],
    }

    asyncio.run(mw(scope, _receive_must_not_be_called, _send))

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413
    assert sent[1]["type"] == "http.response.body"
    detail = json.loads(sent[1]["body"])["detail"]
    assert "1024" in detail


def test_early_rejection_sets_connection_close_to_avoid_keepalive_desync():
    """Der Body wird nicht gelesen/verworfen -- ohne Connection: close
    koennte die restliche Client-Uebertragung als naechster Request auf
    derselben Keep-Alive-Verbindung fehlinterpretiert werden."""
    sent: list[dict] = []

    async def _send(message):
        sent.append(message)

    async def _receive():  # pragma: no cover - darf nicht aufgerufen werden
        raise AssertionError("unerwarteter receive()-Aufruf")

    async def _app(scope, receive, send):  # pragma: no cover
        raise AssertionError("unerwarteter App-Aufruf")

    mw = MaxBodySizeMiddleware(_app, max_bytes=10)
    scope = {
        "type": "http", "method": "POST", "path": "/x",
        "headers": [(b"content-length", b"999")],
    }
    asyncio.run(mw(scope, _receive, _send))

    header_names = {name.lower(): value for name, value in sent[0]["headers"]}
    assert header_names[b"connection"] == b"close"


# ---------------------------------------------------------------------------
# White-Box: Streaming-Schranke (kein/falscher Content-Length)
# ---------------------------------------------------------------------------

def test_streaming_rejection_without_content_length_aborts_before_full_stream():
    """Chunked Transfer-Encoding hat keinen Content-Length-Header. Der
    receive()-Wrapper muss trotzdem beim ersten Byte ueber dem Limit
    abbrechen -- NICHT erst nachdem der komplette (absichtlich riesige)
    virtuelle Stream konsumiert wurde."""
    chunk = b"x" * (256 * 1024)  # 256 KiB je Chunk
    total_chunks = 1000  # virtueller Stream: ~250 MiB, weit ueber dem Limit
    call_count = {"n": 0}

    async def _receive():
        call_count["n"] += 1
        if call_count["n"] > total_chunks:
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def _consuming_app(scope, receive, send):
        # Mimikt Starlette Request.stream(): liest bis more_body=False.
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        # Darf nie erreicht werden -- die Limit-Ueberschreitung muss vorher
        # abbrechen.
        raise AssertionError(
            "innere App hat den kompletten Stream konsumiert -- Limit griff "
            "nicht rechtzeitig"
        )

    sent: list[dict] = []

    async def _send(message):
        sent.append(message)

    max_bytes = 2 * 1024 * 1024  # 2 MiB Limit
    mw = MaxBodySizeMiddleware(_consuming_app, max_bytes=max_bytes)
    scope = {"type": "http", "method": "POST", "path": "/x", "headers": []}

    with pytest.raises(HTTPException) as exc:
        asyncio.run(mw(scope, _receive, _send))
    assert exc.value.status_code == 413

    bytes_consumed = call_count["n"] * len(chunk)
    # Hoechstens ein paar Chunks ueber dem Limit duerfen gelesen worden sein,
    # NICHT die vollen ~250 MiB (1000 Chunks) des virtuellen Streams.
    assert call_count["n"] <= (max_bytes // len(chunk)) + 2
    assert bytes_consumed < 4 * 1024 * 1024


def test_streaming_rejection_catches_a_lying_content_length_header():
    """Ein Content-Length-Header, der einen kleinen Wert behauptet, darf die
    tatsaechliche Bytezaehlung nicht umgehen -- der Header ist
    Client-kontrolliert und kein verlaesslicher alleiniger Schutz."""
    chunk = b"y" * (256 * 1024)
    total_chunks = 200  # ~50 MiB tatsaechlich, obwohl Header 10 Bytes behauptet
    call_count = {"n": 0}

    async def _receive():
        call_count["n"] += 1
        if call_count["n"] > total_chunks:
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def _consuming_app(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        raise AssertionError("Limit griff trotz luegendem Header nicht")

    async def _send(message):
        pass

    max_bytes = 1 * 1024 * 1024  # 1 MiB Limit
    mw = MaxBodySizeMiddleware(_consuming_app, max_bytes=max_bytes)
    scope = {
        "type": "http", "method": "POST", "path": "/x",
        "headers": [(b"content-length", b"10")],  # luegt: behauptet 10 Bytes
    }

    with pytest.raises(HTTPException) as exc:
        asyncio.run(mw(scope, _receive, _send))
    assert exc.value.status_code == 413
    # Muss frueh abgebrochen sein, nicht die vollen ~50 MiB gelesen haben.
    assert call_count["n"] <= (max_bytes // len(chunk)) + 2


# ---------------------------------------------------------------------------
# Regression: normale, kleine Bodies bleiben unveraendert
# ---------------------------------------------------------------------------

def test_normal_small_body_with_content_length_passes_through_unchanged():
    payload = b'{"username": "leart"}'
    captured = {}

    async def _receive_once():
        return {"type": "http.request", "body": payload, "more_body": False}

    async def _app(scope, receive, send):
        message = await receive()
        captured["body"] = message["body"]
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    sent: list[dict] = []

    async def _send(message):
        sent.append(message)

    mw = MaxBodySizeMiddleware(_app, max_bytes=1024)
    scope = {
        "type": "http", "method": "POST", "path": "/x",
        "headers": [(b"content-length", str(len(payload)).encode())],
    }
    asyncio.run(mw(scope, _receive_once, _send))

    assert captured["body"] == payload
    assert sent[0]["status"] == 200


def test_normal_small_body_without_content_length_passes_through_unchanged():
    """Chunked Transfer-Encoding (kein Content-Length) mit einer normalen,
    kleinen Bodygroesse darf nicht faelschlich blockiert werden."""
    chunks = [b'{"user', b'name": "leart"}']
    captured = {"body": b""}

    call_count = {"n": 0}

    async def _receive():
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(chunks):
            return {"type": "http.request", "body": chunks[idx], "more_body": idx < len(chunks) - 1}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _app(scope, receive, send):
        while True:
            message = await receive()
            captured["body"] += message.get("body", b"")
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    sent: list[dict] = []

    async def _send(message):
        sent.append(message)

    mw = MaxBodySizeMiddleware(_app, max_bytes=1024)
    scope = {"type": "http", "method": "POST", "path": "/x", "headers": []}
    asyncio.run(mw(scope, _receive, _send))

    assert captured["body"] == b'{"username": "leart"}'
    assert sent[0]["status"] == 200


def test_non_http_scope_passes_through_untouched():
    """Lifespan-/Websocket-Scopes haben keinen 'headers'-Eintrag im selben
    Format -- die Middleware darf Headers(...) dafuer nie aufrufen."""
    called = {"app": False}

    async def _app(scope, receive, send):
        called["app"] = True

    mw = MaxBodySizeMiddleware(_app, max_bytes=1024)
    scope = {"type": "lifespan"}

    async def _receive():
        return {"type": "lifespan.startup"}

    async def _send(message):
        pass

    asyncio.run(mw(scope, _receive, _send))
    assert called["app"] is True


# ---------------------------------------------------------------------------
# Integration: echte FastAPI/Starlette-Pipeline (ExceptionMiddleware)
# ---------------------------------------------------------------------------

def test_http_exception_from_receive_is_translated_to_413_by_real_pipeline():
    """Beweist die zentrale Design-Annahme: eine aus dem receive()-Wrapper
    geworfene HTTPException(413) wird von Starlettes eingebauter
    ExceptionMiddleware -- innerhalb der Router-Verarbeitung, also BEVOR sie
    je RequestContextMiddleware's aeusseren except-Block erreichen wuerde --
    automatisch in eine saubere JSON-413-Antwort uebersetzt."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    mini_app = FastAPI()

    @mini_app.post("/echo")
    def _echo(body: _EchoBody):
        return {"received": body.padding}

    mini_app.add_middleware(MaxBodySizeMiddleware, max_bytes=256)

    with TestClient(mini_app) as client:
        oversized_resp = client.post("/echo", json={"padding": "A" * 1000})
        assert oversized_resp.status_code == 413
        assert "gross" in oversized_resp.json()["detail"]

        normal_resp = client.post("/echo", json={"padding": "ok"})
        assert normal_resp.status_code == 200
        assert normal_resp.json() == {"received": "ok"}


# ---------------------------------------------------------------------------
# End-to-End gegen die echte main.app am urspruenglichen Audit-Repro-Pfad
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_login_attempt_guard():
    """login_attempt_guard ist ein prozessweiter, DB-gestuetzter Singleton
    (IP-basierte Schluessel, siehe routers/auth.py::_login_guard_key) --
    ohne Reset zwischen Tests akkumulieren wiederholte /auth/password-reset/
    request-Aufrufe auf demselben Test-Client-IP-Schluessel und koennten
    irgendwann 429 statt 200/413 liefern (etabliertes Muster, siehe
    tests/test_account_recovery.py::_reset_login_attempt_guard)."""
    from services.login_guard import login_attempt_guard
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()
    yield
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()


@pytest.fixture()
def _password_reset_client(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from fastapi.testclient import TestClient

    from database import Base, get_db
    import main as main_module

    engine = create_engine(
        f"sqlite:///{tmp_path / 'resource001.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = SF()
        try:
            yield db
        finally:
            db.close()

    main_module.app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(main_module.app) as client:
            yield client
    finally:
        main_module.app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_oversized_password_reset_request_rejected_before_guard_or_db(
    _password_reset_client, monkeypatch
):
    """Der urspruengliche Audit-Repro-Pfad: /auth/password-reset/request ist
    oeffentlich (kein Auth-Header noetig). Ein absichtlich weit ueber dem
    globalen Default-Limit (10 MiB) liegender Body muss mit 413 abgelehnt
    werden, BEVOR Login-Guard, DB oder Mail-Versand je erreicht werden."""
    from services.login_guard import login_attempt_guard

    guard_calls: list[str] = []
    original_check = login_attempt_guard.check

    def _tracking_check(key):
        guard_calls.append(key)
        return original_check(key)

    monkeypatch.setattr(login_attempt_guard, "check", _tracking_check)

    oversized_payload = {
        "username": "irrelevant-user-fuer-diesen-test",
        # 11 MiB Padding -- klar ueber dem 10-MiB-Default, Pydantic ignoriert
        # das unbekannte Feld standardmaessig (extra='ignore'), genau wie im
        # Audit-Repro dokumentiert.
        "padding": "A" * (11 * 1024 * 1024),
    }

    resp = _password_reset_client.post(
        "/auth/password-reset/request", json=oversized_payload
    )

    assert resp.status_code == 413
    # Der Login-Guard darf fuer einen am Body-Limit abgelehnten Request nie
    # aufgerufen worden sein (Beweis: die Route-Funktion wurde nie betreten,
    # der Abbruch geschah bereits waehrend des Body-Lesens).
    assert guard_calls == []


def test_normal_password_reset_request_still_returns_generic_200(_password_reset_client):
    """Regression: ein normal kleiner, legitimer Request an denselben
    Endpoint bleibt unveraendert (generische 200-Antwort, kein 413)."""
    resp = _password_reset_client.post(
        "/auth/password-reset/request",
        json={"username": "kein-solches-konto"},
    )
    assert resp.status_code == 200
    assert "message" in resp.json()


# ---------------------------------------------------------------------------
# config.py: Default + Validator
# ---------------------------------------------------------------------------

def test_max_request_body_bytes_default_is_ten_mebibytes():
    settings = Settings()
    assert settings.max_request_body_bytes == 10 * 1024 * 1024


def test_max_request_body_bytes_rejects_non_positive_values():
    with pytest.raises(ValueError):
        Settings(max_request_body_bytes=0)
    with pytest.raises(ValueError):
        Settings(max_request_body_bytes=-1)
