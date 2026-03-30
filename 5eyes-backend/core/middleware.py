from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


logger = logging.getLogger(__name__)


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

        logger.info(
            'Request completed | request_id=%s method=%s path=%s status=%s duration_ms=%s',
            request_id,
            request.method,
            request.url.path,
            getattr(response, 'status_code', 'n/a'),
            duration_ms,
        )
        return response
