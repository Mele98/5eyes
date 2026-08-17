"""RLS-CI-guard (2026-08-17): dynamic tenant-table-coverage verification.

A prior security audit of the Postgres RLS implementation found that table
coverage relied on a hand-maintained Python list (the old body of
``import_tenant_models()``): safe *today* (all real tenant_id-bearing tables
were verified covered), but fragile -- a future model with a ``tenant_id``
column could ship without anyone adding it to that list, in which case it
would be invisible to ``Base.metadata`` entirely and no check would ever
catch it.

Two-part fix, two-part test file:

1. ``import_tenant_models()`` (services/postgres_rls.py) no longer lists
   modules by hand -- it walks the ``models`` package directory via
   ``pkgutil`` and imports every submodule it finds. New model files are
   picked up automatically. The tests in the first half of this file run
   on SQLite (no live Postgres needed) and prove this discovery mechanism
   actually works: every ``models/*.py`` file ends up imported, and a
   *synthetic* tenant_id-bearing model (simulating "a future developer adds
   one and forgets to wire anything up") is picked up by
   ``tenant_scoped_table_names()`` purely because it is declared against the
   shared ``Base`` -- no list to edit.

2. ``tenant_tables_missing_rls_policies()`` (services/postgres_rls.py) is the
   actual CI guard: it asks Postgres's own ``pg_policies`` catalog, for every
   dynamically-discovered tenant table, whether a policy actually exists.
   ``test_every_dynamically_discovered_tenant_table_has_an_rls_policy`` below
   is the live-Postgres assertion that fails loudly if a tenant table is
   missing its policy. It is skipped on SQLite (matching every sibling RLS
   test's convention) and needs a real Postgres instance to actually run --
   see the module docstring bottom for how to do that.

How to run the live-Postgres part when a real instance is available
---------------------------------------------------------------------
    export POSTGRES_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres
    python -m pytest tests/test_rls_dynamic_table_coverage_guard.py -q

(same env var and same ``postgresql+psycopg://`` driver convention as
``tests/test_postgres_rls_adversarial.py`` -- requires the ``psycopg``
package, and a role on the target server allowed to CREATE ROLE / CREATE
SCHEMA, exactly like that sibling test.)
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Column, String, create_engine, text
from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from services.postgres_rls import (  # noqa: E402
    ensure_postgres_rls_policies,
    import_tenant_models,
    tenant_scoped_table_names,
    tenant_tables_missing_rls_policies,
)


# ---------------------------------------------------------------------------
# Part 1: dynamic-discovery mechanics -- always runnable, no DB needed.
# ---------------------------------------------------------------------------


def test_import_tenant_models_imports_every_models_package_module():
    """Every .py file under models/ must end up imported -- not just the
    ones a human remembered to list. Regression guard for the old
    hand-maintained-list design (a file present on disk but never imported
    would previously vanish from Base.metadata without a trace)."""

    import models as models_pkg

    on_disk = {
        path.stem
        for path in Path(models_pkg.__file__).parent.glob("*.py")
        if path.stem != "__init__"
    }
    assert on_disk, "sanity: models/ should contain model files"

    import_tenant_models()

    for stem in on_disk:
        module_name = f"models.{stem}"
        assert module_name in sys.modules, (
            f"{module_name} exists on disk under models/ but was not imported by "
            "import_tenant_models() -- dynamic pkgutil discovery regressed back "
            "toward a hand-maintained list."
        )


def test_tenant_scoped_table_inventory_matches_current_models():
    """Unchanged behavioural contract from the pre-existing hardcoded-list
    test (test_postgres_rls_policy_setup.py) -- still true under dynamic
    discovery."""

    names = set(tenant_scoped_table_names())
    assert {"clients", "mandates", "protocol_bausteine", "users"}.issubset(names)
    assert "tenants" not in names


def test_dynamic_discovery_catches_a_synthetic_forgotten_tenant_table():
    """Simulates the exact audit-finding scenario: a future developer adds a
    new SQLAlchemy model with a tenant_id column and never touches any
    "list of tenant tables" anywhere. Because discovery introspects
    Base.metadata directly (not a maintained list), the new table shows up
    in tenant_scoped_table_names() automatically, with zero code changes
    beyond declaring the model against the shared Base.

    This is the mocked/simulated proof (per the task's fallback instruction)
    that the discovery logic itself is correct, independent of whether a
    live Postgres instance is available to also prove the pg_policies half.
    """

    import_tenant_models()
    before = set(tenant_scoped_table_names())
    marker_table = f"_test_forgotten_tenant_table_{uuid.uuid4().hex[:8]}"
    assert marker_table not in before

    class _ForgottenTenantModel(Base):
        __tablename__ = marker_table
        id = Column(String, primary_key=True)
        tenant_id = Column(String, nullable=True)

    try:
        after = set(tenant_scoped_table_names())
        assert marker_table in after, (
            "a model with a tenant_id column that is declared against Base but "
            "never added to any hand-maintained list must still be discovered "
            "-- that is the entire point of scanning Base.metadata dynamically."
        )
    finally:
        # Clean up so this synthetic table doesn't leak into other tests in
        # the same process (Base.metadata is process-global).
        Base.metadata.remove(_ForgottenTenantModel.__table__)


def test_tenant_tables_missing_rls_policies_is_noop_on_sqlite(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'rls-coverage-noop.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    assert tenant_tables_missing_rls_policies(engine) == []


def test_tenant_tables_missing_rls_policies_empty_table_list_is_noop():
    # Non-Postgres dialect short-circuits before even resolving table names,
    # but an explicit empty table_names iterable must also short-circuit
    # cleanly regardless of dialect.
    class _FakeSqliteDialect:
        name = "sqlite"

    class _FakeEngine:
        dialect = _FakeSqliteDialect()

    assert tenant_tables_missing_rls_policies(_FakeEngine(), table_names=()) == []


# ---------------------------------------------------------------------------
# Part 2: live-Postgres integration guard. Skips cleanly without a real DB,
# exactly like tests/test_postgres_rls_adversarial.py.
# ---------------------------------------------------------------------------

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark_pg = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; SQLite-Suite ueberspringt Postgres-RLS",
)

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _qi(identifier: str) -> str:
    if not _IDENTIFIER_RE.match(identifier):
        raise ValueError(identifier)
    return f'"{identifier}"'


@pytest.fixture(scope="module")
def rls_coverage_schema():
    pytest.importorskip("psycopg")
    assert POSTGRES_URL is not None
    token = uuid.uuid4().hex[:12]
    schema = f"rls_cov_{token}"

    admin_engine = create_engine(POSTGRES_URL, future=True)
    with admin_engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
        conn.execute(text(f"SET search_path TO {_qi(schema)}"))
        import_tenant_models()
        Base.metadata.create_all(bind=conn)
        ensure_postgres_rls_policies(conn)

    try:
        yield {"engine": admin_engine, "schema": schema}
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
        admin_engine.dispose()


@pytestmark_pg
def test_every_dynamically_discovered_tenant_table_has_an_rls_policy(rls_coverage_schema):
    """THE guard: after standing up every ORM table this codebase currently
    defines (in a fresh schema, exactly the way database.py's startup path
    does via ensure_postgres_rls_policies(engine)), assert that pg_policies
    has at least one row for every table tenant_scoped_table_names()
    discovered -- not a fixed subset of it.

    If a future developer adds models/some_new_thing.py with a tenant_id
    column and never wires up an RLS policy for it, this test fails loudly
    (missing == [<the new table>]) instead of silently passing, which is
    exactly the audit finding this guard closes.
    """

    engine = rls_coverage_schema["engine"]
    schema = rls_coverage_schema["schema"]

    discovered = tenant_scoped_table_names()
    assert discovered, "sanity: there should be at least one tenant-scoped table"

    with engine.connect() as conn:
        missing = tenant_tables_missing_rls_policies(conn, table_names=discovered, schema=schema)

    assert missing == [], (
        f"Tenant-scoped tables with NO pg_policies row: {missing}. "
        "Every table with a tenant_id column must have an RLS policy applied "
        "via ensure_postgres_rls_policies() -- see services/postgres_rls.py."
    )


@pytestmark_pg
def test_guard_fails_loudly_when_a_policy_is_genuinely_missing(rls_coverage_schema):
    """Negative control: prove the guard actually detects a gap, not just
    that it passes when everything happens to already be covered. Creates a
    real table with tenant_id in the test schema, deliberately WITHOUT ever
    calling ensure_postgres_rls_policies() for it, and asserts the guard
    reports exactly that table as missing.
    """

    engine = rls_coverage_schema["engine"]
    schema = rls_coverage_schema["schema"]
    marker_table = f"_forgotten_{uuid.uuid4().hex[:8]}"

    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {_qi(schema)}"))
        conn.execute(
            text(f'CREATE TABLE {_qi(marker_table)} (id text primary key, tenant_id text)')
        )

    try:
        with engine.connect() as conn:
            missing = tenant_tables_missing_rls_policies(
                conn, table_names=(marker_table,), schema=schema
            )
        assert missing == [marker_table]
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"SET search_path TO {_qi(schema)}"))
            conn.execute(text(f"DROP TABLE IF EXISTS {_qi(marker_table)}"))
