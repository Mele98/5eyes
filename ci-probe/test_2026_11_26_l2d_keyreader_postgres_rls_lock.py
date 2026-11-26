"""Independent PostgreSQL acceptance for the L2d key-reader lock contract.

The test uses the product's existing random-schema PostgreSQL fixture, but its
assertions are independent.  The exact product tree and SHA are mandatory.
No fallback database or owner profile is permitted.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError


POSTGRES_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL not set; real PostgreSQL is mandatory",
)


PRODUCT = os.environ.get("ARES_PRODUCT_ROOT")
EXPECTED = os.environ.get("ARES_EXPECTED_SHA")
if not PRODUCT or not EXPECTED:
    raise RuntimeError("Set ARES_PRODUCT_ROOT and ARES_EXPECTED_SHA; refusing fallback")
ROOT = Path(PRODUCT).resolve()
BACKEND = ROOT / "ares-backend"
TESTS = BACKEND / "tests"
if not BACKEND.is_dir():
    raise RuntimeError(f"Not an Ares product root: {ROOT}")
for path in (str(BACKEND), str(TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)
HEAD = subprocess.run(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
    check=True,
    capture_output=True,
    text=True,
    encoding="utf-8",
).stdout.strip()
if HEAD != EXPECTED:
    raise RuntimeError(f"Expected {EXPECTED}, got {HEAD}; refusing cross-SHA verdict")

from services import pii_vault  # noqa: E402
from services.tenant_context import set_tenant_context  # noqa: E402
from tests.test_postgres_l2d_query_budget_rls_live import (  # noqa: E402,F401
    FOREIGN,
    TENANT,
    pg_app,
)


def _role_is_unprivileged(db) -> None:
    row = db.execute(text(
        "SELECT r.rolsuper, r.rolbypassrls, "
        "(SELECT tableowner = current_user FROM pg_tables "
        " WHERE schemaname = current_schema() AND tablename = 'clients') AS owns_clients "
        "FROM pg_roles r WHERE r.rolname = current_user"
    )).one()
    assert row.rolsuper is False
    assert row.rolbypassrls is False
    assert row.owns_clients is False


def _reveal_after_shred(db, envelope: str, reader) -> None:
    try:
        value = pii_vault.reveal(db, envelope, reader=reader)
    except RuntimeError as exc:
        assert "closed" in str(exc).lower() or "geschlossen" in str(exc).lower()
    else:
        assert value is None


def test_unprivileged_rls_role_can_complete_shred_without_an_active_reader(pg_app):
    """Positive control: privileges/RLS do not make every shred time out."""
    with pg_app() as db:
        set_tenant_context(db, TENANT)
        _role_is_unprivileged(db)
        envelope = pii_vault.seal_for_client(db, "c-1", "SYNTHETISCHE POSITIVKONTROLLE")
        db.commit()
        set_tenant_context(db, TENANT)
        assert pii_vault.shred_client_keys(db, "c-1") == 1
        db.commit()
        set_tenant_context(db, TENANT)
        assert pii_vault.reveal(db, envelope, reader=pii_vault.KeyReader(db)) is None


def test_for_share_blocks_shred_until_normal_rls_reader_transaction_ends(pg_app):
    """A normal app reader must hold a real PostgreSQL row lock until commit."""
    session_factory = pg_app
    with session_factory() as reader_db:
        set_tenant_context(reader_db, TENANT)
        _role_is_unprivileged(reader_db)
        envelope = pii_vault.seal_for_client(reader_db, "c-1", "SYNTHETISCHER LOCKTEST")
        reader_db.commit()
        set_tenant_context(reader_db, TENANT)

        statements: list[str] = []

        def capture(_conn, _cursor, statement, *_rest):
            statements.append(statement)

        event.listen(reader_db.get_bind(), "before_cursor_execute", capture)
        reader = pii_vault.KeyReader(reader_db)
        assert pii_vault.reveal(reader_db, envelope, reader=reader) == "SYNTHETISCHER LOCKTEST"
        event.remove(reader_db.get_bind(), "before_cursor_execute", capture)
        assert any("FOR SHARE" in statement.upper() for statement in statements), statements

        # The same application role, in a second session, must not be able to
        # finish the UPDATE while the first request owns the read lock.
        with session_factory() as shred_db:
            set_tenant_context(shred_db, TENANT)
            _role_is_unprivileged(shred_db)
            shred_db.execute(text("SET LOCAL lock_timeout = '400ms'"))
            try:
                pii_vault.shred_client_keys(shred_db, "c-1")
                shred_db.flush()
            except DBAPIError as exc:
                sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
                assert sqlstate == "55P03", sqlstate
                shred_db.rollback()
            else:
                shred_db.rollback()
                pytest.fail("DSG key deletion completed while the reader transaction was active")

        # Releasing the reader transaction must release the lock and invalidate
        # its cached key.  A subsequent deletion then succeeds normally.
        reader_db.commit()
        with session_factory() as shred_db:
            set_tenant_context(shred_db, TENANT)
            assert pii_vault.shred_client_keys(shred_db, "c-1") == 1
            shred_db.commit()
        set_tenant_context(reader_db, TENANT)
        _reveal_after_shred(reader_db, envelope, reader)

        # RLS is genuinely active for the same unprivileged role: changing the
        # tenant context hides the seeded client row.
        reader_db.rollback()
        set_tenant_context(reader_db, FOREIGN)
        assert reader_db.execute(text("SELECT COUNT(*) FROM clients WHERE id = 'c-1'")).scalar_one() == 0
