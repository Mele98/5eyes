"""Zentraler Exception-Handler fuer fachliche Fehler (K-2, A2 M17).

``DomainError`` (``core/reason_codes.py``) wird hier auf HTTP abgebildet --
und zwar ueber GENAU den Handler, den die App fuer ``HTTPException``
verwendet (heute FastAPIs Standard ``http_exception_handler``). Damit ist die
Antwort per Konstruktion identisch zu dem, was ein Router bisher mit
``raise HTTPException(status_code=exc.http_status, detail=exc.as_detail())``
erzeugt hat: gleicher Status, gleicher JSON-Body (gleiche Serialisierung und
Schluesselreihenfolge), gleiche Header. Bekommt die App spaeter einen eigenen
HTTPException-Handler (z. B. RFC-9457-Envelope, U-2), folgen fachliche
Fehler automatisch.
"""
from __future__ import annotations

import inspect

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from core.reason_codes import DomainError


def domain_error_as_http_exception(exc: DomainError) -> HTTPException:
    """Die ``HTTPException``, die ein Router bisher selbst gebaut haette."""
    return HTTPException(status_code=exc.http_status, detail=exc.as_detail(), headers=exc.headers)


async def domain_error_handler(request: Request, exc: DomainError) -> Response:
    handler = request.app.exception_handlers.get(StarletteHTTPException, http_exception_handler)
    response = handler(request, domain_error_as_http_exception(exc))
    if inspect.isawaitable(response):
        response = await response
    return response


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, domain_error_handler)
