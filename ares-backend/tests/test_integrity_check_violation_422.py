"""RC-CH-1-F1: CHECK-Verletzungen der DB enden nie als 500, sondern als 422.

Zentral in ``core/middleware.py::integrity_error_handler`` (Reason-Code
``DB_CHECK_CONSTRAINT_VIOLATION``). Andere Integritaetsfehler (UNIQUE/FK/
NOT NULL) bleiben unveraendert (kein stilles Umdeuten).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.middleware import install_exception_handlers, is_check_constraint_violation  # noqa: E402
from core.reason_codes import ReasonCode  # noqa: E402


def _real_integrity_error(statement: str) -> IntegrityError:
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE t (id INTEGER PRIMARY KEY, kind TEXT NOT NULL "
            "CHECK(kind IN ('a','b')))"
        ))
        conn.execute(text("INSERT INTO t (id, kind) VALUES (1, 'a')"))
    try:
        with engine.begin() as conn:
            conn.execute(text(statement))
    except IntegrityError as exc:
        return exc
    finally:
        engine.dispose()
    raise AssertionError("kein IntegrityError")


class _PgOrig(Exception):
    def __init__(self, sqlstate: str):
        super().__init__("new row violates check constraint \"ck\"\nDETAIL: Failing row contains (geheim)")
        self.sqlstate = sqlstate


def _app(exc: Exception) -> TestClient:
    app = FastAPI()
    install_exception_handlers(app)

    @app.post("/boom")
    def boom():
        raise exc

    return TestClient(app, raise_server_exceptions=False)


def test_sqlite_check_violation_is_422_with_reason_code():
    exc = _real_integrity_error("INSERT INTO t (id, kind) VALUES (2, 'zzz')")
    assert is_check_constraint_violation(exc)
    r = _app(exc).post("/boom")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["reason_code"] == ReasonCode.DB_CHECK_CONSTRAINT_VIOLATION.value
    assert "zzz" not in r.text


def test_postgres_check_violation_sqlstate_is_422_without_row_detail():
    exc = IntegrityError("INSERT ...", {}, _PgOrig("23514"))
    r = _app(exc).post("/boom")
    assert r.status_code == 422
    assert "geheim" not in r.text and "Failing row" not in r.text


@pytest.mark.parametrize("statement", [
    "INSERT INTO t (id, kind) VALUES (1, 'b')",      # UNIQUE / PK
    "INSERT INTO t (id, kind) VALUES (3, NULL)",     # NOT NULL
])
def test_other_sqlite_integrity_errors_stay_500(statement):
    exc = _real_integrity_error(statement)
    assert not is_check_constraint_violation(exc)
    assert _app(exc).post("/boom").status_code == 500


def test_postgres_unique_violation_stays_500():
    exc = IntegrityError("INSERT ...", {}, _PgOrig("23505"))
    assert not is_check_constraint_violation(exc)
    assert _app(exc).post("/boom").status_code == 500


def test_main_app_registers_the_handler():
    from main import app

    assert IntegrityError in app.exception_handlers


def test_raise_if_check_violation_only_reraises_check():
    """Nachtrag 2: gemeinsame Hilfe der Konflikt-Zweige."""
    from core.db_integrity import raise_if_check_violation

    check = _real_integrity_error("INSERT INTO t (id, kind) VALUES (2, 'zzz')")
    with pytest.raises(IntegrityError) as caught:
        raise_if_check_violation(check)
    assert caught.value is check
    for statement in ("INSERT INTO t (id, kind) VALUES (1, 'b')", "INSERT INTO t (id, kind) VALUES (3, NULL)"):
        assert raise_if_check_violation(_real_integrity_error(statement)) is None
    assert raise_if_check_violation(IntegrityError("x", {}, _PgOrig("23505"))) is None
    with pytest.raises(IntegrityError):
        raise_if_check_violation(IntegrityError("x", {}, _PgOrig("23514")))
