"""K-2: ``DomainError`` + zentraler Handler sind byte-gleich zu ``HTTPException``.

Auf einer Mini-App (gleicher Handler wie ``main.app``) wirft je ein Endpunkt
``DomainError`` bzw. die ``HTTPException``, die ein Router bisher daraus gebaut
haette. Verglichen werden Status, rohe Body-Bytes und alle Header -- fuer
Status 4xx/5xx, mit/ohne ``details``, mit/ohne ``channel``, mit Headern,
Nicht-ASCII-Text und fuer Statuscodes ohne Body. Zusaetzlich: ``main.app`` hat
den Handler registriert, und die Detail-Struktur der alten
``OnsiteSignatureError.as_detail()`` (hier eingefroren) ist unveraendert.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.error_handlers import (  # noqa: E402
    domain_error_as_http_exception,
    domain_error_handler,
    install_exception_handlers,
)
from core.reason_codes import DomainError, ReasonCode  # noqa: E402


class _Channel(DomainError):
    channel = "onsite_signature"


def _legacy_onsite_detail(reason_code: str, message: str, details: Mapping[str, Any] | None) -> dict:
    """Eingefrorene Kopie von ``OnsiteSignatureError.as_detail()`` vor K-2."""
    detail = {"reason_code": reason_code, "message": message, "channel": "onsite_signature"}
    if dict(details or {}):
        detail["details"] = dict(details or {})
    return detail


CASES = [
    pytest.param(dict(cls=DomainError, code="RISK_BUDGET_VIOLATED", msg="Budget", status=409), id="plain-409"),
    pytest.param(dict(cls=_Channel, code=ReasonCode.ONSITE_SIGNATURE_NOT_FOUND, msg="Signaturvorgang nicht gefunden.",
                      status=404), id="channel-404-enum-member"),
    pytest.param(dict(cls=_Channel, code="ONSITE_SIGNATURE_NOT_RELEASED", msg="Nicht freigegeben – Umlaute äöü ✓",
                      status=409, details={"release_problems": ["policy_status:PROPOSED", "x"], "n": 1.5}),
                 id="channel-details-unicode"),
    pytest.param(dict(cls=_Channel, code="ONSITE_SIGNATURE_INPUT_MISSING", msg="fehlt", status=422, details={}),
                 id="channel-422-empty-details"),
    pytest.param(dict(cls=DomainError, code="dynamic_provider_code", msg="x", status=503,
                      headers={"Retry-After": "30"}), id="503-with-header"),
    pytest.param(dict(cls=DomainError, code="NO_TRADES", msg="nichts", status=304), id="304-no-body"),
]


def _app() -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)
    return app


@pytest.mark.parametrize("case", CASES)
def test_domain_error_response_equals_legacy_http_exception(case):
    app = _app()
    kwargs = {"http_status": case["status"]}
    if "details" in case:
        kwargs["details"] = case["details"]
    if "headers" in case:
        kwargs["headers"] = case["headers"]

    def make():
        return case["cls"](case["code"], case["msg"], **kwargs)

    @app.get("/new")
    def new():
        raise make()

    @app.get("/old")
    def old():
        exc = make()
        raise HTTPException(status_code=exc.http_status, detail=exc.as_detail(), headers=case.get("headers"))

    client = TestClient(app, raise_server_exceptions=False)
    a, b = client.get("/new"), client.get("/old")
    assert a.status_code == b.status_code == case["status"]
    assert a.content == b.content
    assert a.headers.raw == b.headers.raw


def test_onsite_detail_structure_is_unchanged():
    from services.onsite_signature import service as svc

    for details in (None, {}, {"provider": "x", "provider_reason": None}):
        new = svc.OnsiteSignatureError(svc.INVALID_STATE, "m", http_status=409, details=details)
        assert new.as_detail() == _legacy_onsite_detail(svc.INVALID_STATE, "m", details)
        assert list(new.as_detail()) == list(_legacy_onsite_detail(svc.INVALID_STATE, "m", details))
    default = svc.OnsiteSignatureError(svc.TRANSACTION_NOT_FOUND, "x")
    assert default.http_status == 409 and default.headers is None and default.details == {}
    assert str(default) == "x" and default.reason_code == "ONSITE_SIGNATURE_NOT_FOUND"
    assert type(default.reason_code) is str


def test_enum_member_is_stored_as_plain_str():
    err = DomainError(ReasonCode.RISK_BUDGET_VIOLATED, "m")
    assert type(err.reason_code) is str and err.reason_code == "RISK_BUDGET_VIOLATED"
    assert domain_error_as_http_exception(err).detail == {"reason_code": "RISK_BUDGET_VIOLATED", "message": "m"}


def test_main_app_registers_the_central_handler():
    from main import app

    assert app.exception_handlers.get(DomainError) is domain_error_handler


def test_handler_follows_a_custom_http_exception_handler():
    """Bekommt die App einen eigenen HTTPException-Handler, nutzt DomainError ihn mit."""
    from fastapi.responses import PlainTextResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    app = _app()

    @app.exception_handler(StarletteHTTPException)
    async def custom(_request, exc):
        return PlainTextResponse(f"custom:{exc.status_code}", status_code=exc.status_code)

    @app.get("/x")
    def x():
        raise DomainError("NO_TRADES", "m", http_status=409)

    r = TestClient(app).get("/x")
    assert r.status_code == 409 and r.text == "custom:409"
