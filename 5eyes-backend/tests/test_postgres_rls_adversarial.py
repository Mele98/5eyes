from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; SQLite-Suite ueberspringt Postgres-RLS",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.postgres_rls import (  # noqa: E402
    ensure_postgres_rls_policies,
    ensure_postgres_tenant_not_null,
)
from services.tenant_context import (  # noqa: E402
    attach_tenant_context_reset,
    operator_bypass,
    set_tenant_context,
)


_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _qi(identifier: str) -> str:
    if not _IDENTIFIER_RE.match(identifier):
        raise ValueError(identifier)
    return f'"{identifier}"'


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _set_search_path(db, schema: str) -> None:
    db.execute(text(f"SET search_path TO {_qi(schema)}"))


@pytest.fixture(scope="module")
def postgres_rls_context():
    pytest.importorskip("psycopg")
    assert POSTGRES_URL is not None
    token = uuid.uuid4().hex[:12]
    schema = f"rls_{token}"
    role = f"rls_app_{token}"
    password = f"pw_{token}"

    admin_engine = create_engine(POSTGRES_URL, future=True)
    url = make_url(POSTGRES_URL).set(username=role, password=password)
    app_engine = create_engine(str(url), future=True, pool_size=1, max_overflow=0)
    attach_tenant_context_reset(app_engine)

    with admin_engine.begin() as conn:
        conn.execute(text(f"CREATE ROLE {_qi(role)} LOGIN PASSWORD {_sql_literal(password)}"))
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
        conn.execute(text(f"SET search_path TO {_qi(schema)}"))
        conn.execute(text("""
            CREATE TABLE clients (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                label TEXT NOT NULL
            )
        """))
        conn.execute(
            text("INSERT INTO clients (id, tenant_id, label) VALUES (:id, :tenant_id, :label)"),
            [
                {"id": "a1", "tenant_id": "tenant-a", "label": "A"},
                {"id": "b1", "tenant_id": "tenant-b", "label": "B"},
            ],
        )
        ensure_postgres_tenant_not_null(conn, table_names=("clients",), default_tenant_id="tenant-a")
        ensure_postgres_rls_policies(conn, table_names=("clients",))
        conn.execute(text(f"GRANT USAGE ON SCHEMA {_qi(schema)} TO {_qi(role)}"))
        conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {_qi(schema)} TO {_qi(role)}"))

    try:
        yield {"engine": app_engine, "schema": schema}
    finally:
        app_engine.dispose()
        with admin_engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
            conn.execute(text(f"DROP ROLE IF EXISTS {_qi(role)}"))
        admin_engine.dispose()


def _ids(db) -> list[str]:
    return [row[0] for row in db.execute(text("SELECT id FROM clients ORDER BY id")).all()]


def test_raw_query_without_app_filter_is_limited_by_rls(postgres_rls_context):
    Session = sessionmaker(bind=postgres_rls_context["engine"])
    with Session() as db:
        _set_search_path(db, postgres_rls_context["schema"])
        set_tenant_context(db, "tenant-a")
        assert _ids(db) == ["a1"]


def test_pool_reuse_resets_tenant_context(postgres_rls_context):
    Session = sessionmaker(bind=postgres_rls_context["engine"])
    with Session() as db:
        _set_search_path(db, postgres_rls_context["schema"])
        set_tenant_context(db, "tenant-a")
        assert _ids(db) == ["a1"]

    with Session() as db:
        _set_search_path(db, postgres_rls_context["schema"])
        assert _ids(db) == []


def test_rls_with_check_rejects_cross_tenant_insert(postgres_rls_context):
    Session = sessionmaker(bind=postgres_rls_context["engine"])
    with Session() as db:
        _set_search_path(db, postgres_rls_context["schema"])
        set_tenant_context(db, "tenant-a")
        with pytest.raises(SQLAlchemyError):
            db.execute(
                text("INSERT INTO clients (id, tenant_id, label) VALUES ('bad', 'tenant-b', 'bad')")
            )
            db.commit()


def test_operator_sees_all_rows_only_with_explicit_bypass(postgres_rls_context):
    Session = sessionmaker(bind=postgres_rls_context["engine"])
    with Session() as db:
        _set_search_path(db, postgres_rls_context["schema"])
        assert _ids(db) == []

        with operator_bypass(db):
            assert _ids(db) == ["a1", "b1"]

        assert _ids(db) == []
