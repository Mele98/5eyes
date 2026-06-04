from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

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
