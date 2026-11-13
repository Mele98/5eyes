"""RC-CH-1-F1 / N-903-04 gegen ECHTES PostgreSQL: CHECK-Verstoss -> 422.

Ein Endpoint schreibt per SQLAlchemy/psycopg in eine Tabelle mit
``CHECK (kind IN ('a','b'))``. Der echte psycopg-Fehler (SQLSTATE 23514)
muss ueber den zentralen Handler (``core.middleware.integrity_error_handler``)
als 422 ``DB_CHECK_CONSTRAINT_VIOLATION`` enden -- ohne Zeileninhalt aus dem
PG-``DETAIL``. Gegenprobe: ein UNIQUE-Verstoss (23505) bleibt 500.

Eigenes Schema je Test. Ohne ``POSTGRES_TEST_DATABASE_URL`` uebersprungen
(CI-Job ``postgres-rls``, eigener Schritt mit ``-v``).
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.db_integrity import is_check_constraint_violation  # noqa: E402
from core.middleware import install_exception_handlers  # noqa: E402

SECRET = "geheimer-zeileninhalt"


@pytest.fixture()
def pg_engine():
    pytest.importorskip("psycopg")
    assert POSTGRES_URL is not None
    schema = f"ckviol_{uuid.uuid4().hex[:12]}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    sep = "&" if "?" in POSTGRES_URL else "?"
    engine = create_engine(f"{POSTGRES_URL}{sep}options=-csearch_path%3D{schema}", future=True)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE probe (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, note TEXT, "
            "CONSTRAINT ck_probe_kind CHECK (kind IN ('a','b')))"
        ))
        conn.execute(text("INSERT INTO probe (id, kind) VALUES (1, 'a')"))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _app(engine) -> TestClient:
    app = FastAPI()
    install_exception_handlers(app)

    @app.post("/probe/{row_id}/{kind}")
    def write(row_id: int, kind: str):
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO probe (id, kind, note) VALUES (:id, :kind, :note)"),
                {"id": row_id, "kind": kind, "note": SECRET},
            )
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


def test_real_psycopg_check_violation_is_sqlstate_23514(pg_engine):
    with pytest.raises(IntegrityError) as caught:
        with pg_engine.begin() as conn:
            conn.execute(text("INSERT INTO probe (id, kind) VALUES (2, 'zzz')"))
    assert getattr(caught.value.orig, "sqlstate", None) == "23514"
    assert is_check_constraint_violation(caught.value)


def test_real_postgres_check_violation_is_422_without_row_detail(pg_engine):
    r = _app(pg_engine).post("/probe/3/zzz")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["reason_code"] == "DB_CHECK_CONSTRAINT_VIOLATION"
    assert SECRET not in r.text and "Failing row" not in r.text and "zzz" not in r.text


def test_real_postgres_unique_violation_stays_500(pg_engine):
    r = _app(pg_engine).post("/probe/1/b")
    assert r.status_code == 500


def test_valid_write_still_succeeds(pg_engine):
    assert _app(pg_engine).post("/probe/4/b").status_code == 200
