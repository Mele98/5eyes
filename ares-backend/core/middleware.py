from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from config import settings


logger = logging.getLogger(__name__)


# Sprint U-7 (2026-06-04): CSP-Defaults fuer Electron+Browser-Setup.
# Roadmap-Befund: Bearer-Token in sessionStorage XSS-empfindlich.
# CSP haertet die Renderer-Surface — verhindert dass injektierte
# Scripts an den Token kommen.
#
# - script-src 'self' 'unsafe-inline' — Tailwind inline + Electron-
#   Renderer brauchen unsafe-inline; Long-Term: nonce-based CSP.
# - style-src 'self' 'unsafe-inline' — Tailwind JIT generiert inline-styles
# - connect-src 'self' http://localhost:* — Vite-Dev-Backend
# - img-src 'self' data: — base64-Charts (SVG-Foundation)
# - frame-ancestors 'none' — Clickjacking-Schutz
# - form-action 'self' — POST-Submit auf eigene Origin
# - object-src 'none' — keine Flash/Java-Plugins
DEFAULT_CSP_POLICY = (
    "default-src 'self' app://. null; "
    "script-src 'self' 'unsafe-inline' app://. null; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self' http://localhost:* http://127.0.0.1:* "
    "ws://localhost:* ws://127.0.0.1:*; "
    "font-src 'self' data:; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "object-src 'none'; "
    "base-uri 'self'"
)

# Permissions-Policy: alle Browser-Features default deny.
# Berater-App braucht keines davon -> Defense-in-Depth gegen
# kompromittierte 3rd-Party-Scripts.
DEFAULT_PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), midi=(), payment=(), "
    "usb=(), interest-cohort=()"
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                'Unhandled exception | request_id=%s method=%s path=%s duration_ms=%s',
                request_id,
                request.method,
                request.url.path,
                duration_ms,
            )
            response = JSONResponse(
                status_code=500,
                content={
                    'detail': 'Interner Serverfehler',
                    'request_id': request_id,
                },
            )

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers['X-Request-ID'] = request_id
        response.headers['X-Process-Time-Ms'] = str(duration_ms)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'

        # Sprint U-7 (2026-06-04): CSP + Permissions-Policy.
        if getattr(settings, 'csp_enabled', True):
            csp = str(getattr(settings, 'csp_policy', '') or '').strip() or DEFAULT_CSP_POLICY
            response.headers['Content-Security-Policy'] = csp

        if getattr(settings, 'permissions_policy_enabled', True):
            response.headers['Permissions-Policy'] = DEFAULT_PERMISSIONS_POLICY

        # HSTS nur wenn https erzwungen ist (z.B. via Reverse-Proxy).
        # Default backend laeuft lokal http://, HSTS waere kontraproduktiv.
        if getattr(settings, 'hsts_enabled', False):
            response.headers['Strict-Transport-Security'] = (
                'max-age=63072000; includeSubDomains; preload'
            )

        logger.info(
            'Request completed | request_id=%s method=%s path=%s status=%s duration_ms=%s',
            request_id,
            request.method,
            request.url.path,
            getattr(response, 'status_code', 'n/a'),
            duration_ms,
        )
        return response


# ---------------------------------------------------------------------------
# RESOURCE-001 (Codex-Audit 2026-08-27, docs/audits/2026-08-27-request-
# ingestion-and-resource-governance-audit.md): globale Body-Groessenschranke.
# ---------------------------------------------------------------------------
# Vorher registrierte main.py ausser RequestContextMiddleware + CORS keinen
# Layer, der eingehende Request-Bodies begrenzt -- FastAPI/Starlette pufferte
# JSON- und Multipart-Bodies vollstaendig, BEVOR Auth-, Rate-Limit- oder
# Domainlogik ueberhaupt greifen konnte. Der Audit reproduzierte das live
# gegen den oeffentlichen, unauthentifizierten /auth/password-reset/request-
# Endpoint: ein 8-MiB-Body wurde komplett geparst und mit HTTP 200
# beantwortet.
#
# MaxBodySizeMiddleware ist bewusst eine REINE ASGI-Middleware (kein
# BaseHTTPMiddleware wie oben) -- BaseHTTPMiddleware.dispatch() liest den
# Body ueber request.stream() erst waehrend/nach dem Aufruf der inneren App;
# fuer eine Vor-Parsing-Schranke ist das zu spaet. Hier wird stattdessen der
# rohe ASGI-`receive`-Callable gewrapped und JEDES tatsaechlich ankommende
# 'http.request'-Chunk gezaehlt.
#
# Zwei Schutzstufen (siehe Fixvertrag RESOURCE-001 Punkt 2/4):
#   1. Fruehe Ablehnung anhand des Content-Length-Headers, falls vorhanden
#      und bereits ueber dem Limit -- die innere App (und damit Auth/DB/Mail)
#      wird gar nicht erst aufgerufen, es wird kein einziges Byte gelesen.
#   2. Stream-Schranke: fehlt Content-Length (chunked Transfer-Encoding)
#      oder luegt der Header (Client-kontrolliert, daher kein verlaesslicher
#      alleiniger Schutz), zaehlt der receive()-Wrapper die tatsaechlich
#      ankommenden Bytes kumulativ und bricht beim ersten Byte ueber dem
#      Limit sofort ab.
#
# Der Stream-Abbruch geschieht durch Werfen einer regulaeren FastAPI/
# Starlette-HTTPException(413) direkt aus dem receive()-Callable heraus.
# Dieser Callable wird von FastAPI/Starlette immer INNERHALB der Router-
# Verarbeitung aufgerufen (z.B. via Request.stream()/.body()/.form() waehrend
# der Dependency-Injection eines Endpoints) -- also innerhalb von Starlettes
# eingebauter ExceptionMiddleware, die HTTPException bereits standardmaessig
# in eine saubere JSON-413-Antwort uebersetzt, BEVOR die Exception je
# RequestContextMiddleware's breiten except-Block (weiter aussen im Stack)
# erreicht. Ein zusaetzlicher try/except in dieser Middleware ist daher nicht
# noetig.
#
# Deckt sowohl JSON- als auch Multipart-Bodies ab, weil beide letztlich ueber
# denselben Request.stream()-Mechanismus gelesen werden (siehe
# routers/review.py::import_products_csv, der CSV-Upload-Pfad) -- ergaenzt,
# ersetzt aber nicht dessen eigene 2-MiB-Grenze.
class MaxBodySizeMiddleware:
    """Globale Obergrenze fuer eingehende HTTP-Request-Bodies (RESOURCE-001).

    Konfigurierbar via ``settings.max_request_body_bytes`` (Default 10 MiB,
    siehe config.py). Greift fuer JEDE Methode/JEDEN Content-Type -- es gibt
    bewusst keine Route-Ausnahme; der Default ist grosszuegig genug bemessen,
    um alle bekannten legitimen Payloads (Fondsuniversum-CSV-Import 2 MiB,
    Bulk-JSON-Produktimport, Signatur-Bilddaten <=500 KB) unveraendert
    durchzulassen.
    """

    def __init__(self, app: ASGIApp, max_bytes: int | None = None) -> None:
        self.app = app
        self.max_bytes = int(
            max_bytes if max_bytes is not None else settings.max_request_body_bytes
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get('content-length')
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except (TypeError, ValueError):
                declared_length = None
            if declared_length is not None and declared_length > self.max_bytes:
                await self._reject(scope, send, declared_length=declared_length)
                return

        limit = self.max_bytes
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message['type'] == 'http.request':
                body = message.get('body') or b''
                received += len(body)
                if received > limit:
                    # Wird von Starlettes ExceptionMiddleware (innerhalb des
                    # Router-Aufrufs) automatisch in eine 413-JSON-Antwort
                    # uebersetzt -- siehe Modul-Docstring oben.
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f'Request-Body zu gross (max. {limit} Bytes).'
                        ),
                        headers={'Connection': 'close'},
                    )
            return message

        await self.app(scope, limited_receive, send)

    async def _reject(self, scope: Scope, send: Send, *, declared_length: int) -> None:
        logger.warning(
            'Request-Body abgelehnt (Content-Length ueber Limit) | '
            'method=%s path=%s content_length=%s limit=%s',
            scope.get('method'),
            scope.get('path'),
            declared_length,
            self.max_bytes,
        )
        payload = json.dumps(
            {'detail': f'Request-Body zu gross (max. {self.max_bytes} Bytes).'}
        ).encode('utf-8')
        await send({
            'type': 'http.response.start',
            'status': 413,
            'headers': [
                (b'content-type', b'application/json'),
                (b'content-length', str(len(payload)).encode('ascii')),
                (b'connection', b'close'),
            ],
        })
        await send({'type': 'http.response.body', 'body': payload})
