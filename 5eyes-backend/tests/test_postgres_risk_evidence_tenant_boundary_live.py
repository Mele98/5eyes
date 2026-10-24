"""PG-002 live on PostgreSQL: risk evidence tables under FORCE RLS (PR #662 review).

Runs the real migration chain into a throwaway schema, applies the boot-time
RLS plan (``ensure_postgres_rls_policies``) and probes as a dedicated
NON-owner, NON-superuser, NOBYPASSRLS role with two tenants:

* SELECT on ``risk_override_decisions`` / ``risk_profile_signoffs`` is
  tenant-bound; without tenant context nothing is visible;
* raw-SQL INSERT derives ``tenant_id`` from the mandate, rejects a spoofed
  tenant and a foreign (invisible) mandate;
* the append-only guard still blocks UPDATE/DELETE;
* removing one policy is reported for exactly that table by the coverage
  guard ``tenant_tables_missing_rls_policies``.

Skipped without ``POSTGRES_TEST_DATABASE_URL`` (CI job ``postgres-rls``).
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)


def _backend_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "main.py").is_file() and (candidate / "database.py").is_file():
            return candidate
    raise AssertionError("backend directory (main.py + database.py) not found")


BACKEND_ROOT = _backend_root()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.postgres_rls import (  # noqa: E402
    ensure_postgres_rls_policies,
    tenant_tables_missing_rls_policies,
)
from services.risk_evidence_tenant_boundary import RISK_EVIDENCE_TENANT_TABLES  # noqa: E402
from services.tenant_context import (  # noqa: E402
    attach_tenant_context_reset,
    set_tenant_context,
)
from tests.test_tenant_database_boundary import _raw_insert  # noqa: E402

MIGRATION_REVISION = "b5d2e8f41a73"
NOW = "2026-10-24T00:00:00.000Z"
_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")


def _qi(identifier: str) -> str:
    assert _IDENT.match(identifier), identifier
    return f'"{identifier}"'


def _scoped_url(url: str, schema: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}options=-csearch_path%3D{schema}"


def _alembic_cfg(scoped_url: str):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", scoped_url.replace("%", "%%"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _mandate(conn, mid: str, cid: str, tid: str) -> None:
    conn.execute(text(
        "INSERT INTO mandates (id, client_id, mandate_number, mandate_type, status, base_currency, "
        "advisory_language, opened_at, investment_universe, tenant_id, created_at, updated_at) "
        "VALUES (:id, :cid, :id, 'Anlageberatung', 'Aktiv', 'CHF', 'DE', '2026-01-01', 'Standard', "
        ":tid, :n, :n)"
    ), {"id": mid, "cid": cid, "tid": tid, "n": NOW})


def _signoff(conn, sid: str, mandate_id: str, client_id: str, **extra) -> None:
    values = dict(
        id=sid, schema_version="RiskProfileSignoffV2", assessment_id=f"ra-{sid}",
        mandate_id=mandate_id, client_id=client_id, assessment_version=1, sequence_no=1,
        effective_score_x10=50, effective_profile="Ausgewogen", final_score_x10=50,
        final_profile="Ausgewogen", is_overridden=0, override_binding="no_override",
        assessment_input_hash="h", method="advisor_recorded", evidence_level="advisor_attested",
        actor_id="adv", signed_at=NOW, rules_version="r", signoff_hash="x", created_at=NOW,
    )
    values.update(extra)
    columns = ", ".join(values)
    params = ", ".join(f":{key}" for key in values)
    conn.execute(text(f"INSERT INTO risk_profile_signoffs ({columns}) VALUES ({params})"), values)


def _decision(conn, did: str, mandate_id: str, client_id: str, **extra) -> None:
    values = dict(
        id=did, schema_version="RiskOverrideDecisionV2", assessment_id=f"ra-{did}",
        mandate_id=mandate_id, client_id=client_id, assessment_version=1, sequence_no=1,
        basis_final_score_x10=50, requested_score_x10=40, requested_profile="Defensiv",
        reason="r", client_confirmed=0, warning_delivered=0, required_client_confirmation=0,
        required_warning=0, actor_id="adv", decided_at=NOW, rules_version="r",
        decision_hash="x", created_at=NOW,
    )
    values.update(extra)
    columns = ", ".join(values)
    params = ", ".join(f":{key}" for key in values)
    conn.execute(text(f"INSERT INTO risk_override_decisions ({columns}) VALUES ({params})"), values)


def _seed(conn) -> None:
    for tid in ("t-a", "t-b"):
        _raw_insert(conn, "tenants", id=tid, display_name=tid, slug=tid)
    _raw_insert(conn, "users", id="adv", tenant_id="t-a")
    for cid, tid in (("c-a", "t-a"), ("c-b", "t-b")):
        _raw_insert(conn, "clients", id=cid, client_number=cid, tenant_id=tid)
    _mandate(conn, "m-a", "c-a", "t-a")
    _mandate(conn, "m-b", "c-b", "t-b")
    _signoff(conn, "s-a", "m-a", "c-a")
    _signoff(conn, "s-b", "m-b", "c-b")
    _decision(conn, "d-a", "m-a", "c-a")
    _decision(conn, "d-b", "m-b", "c-b")


@pytest.fixture(scope="module")
def pg_evidence():
    pytest.importorskip("psycopg")
    assert POSTGRES_URL is not None
    from alembic import command

    token = uuid.uuid4().hex[:12]
    schema, role, password = f"retb_{token}", f"retb_app_{token}", f"pw_{token}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    scoped = _scoped_url(POSTGRES_URL, schema)
    command.upgrade(_alembic_cfg(scoped), MIGRATION_REVISION)
    owner = create_engine(scoped, future=True)
    with owner.begin() as conn:
        _seed(conn)
        ensure_postgres_rls_policies(conn, table_names=("mandates", *RISK_EVIDENCE_TENANT_TABLES))
        conn.execute(text(
            f"CREATE ROLE {_qi(role)} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{password}'"
        ))
        conn.execute(text(f"GRANT USAGE ON SCHEMA {_qi(schema)} TO {_qi(role)}"))
        conn.execute(text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {_qi(schema)} TO {_qi(role)}"
        ))
    app_url = make_url(scoped).set(username=role, password=password).render_as_string(hide_password=False)
    app = create_engine(app_url, future=True, pool_size=1, max_overflow=0)
    attach_tenant_context_reset(app)
    try:
        yield {"app": app, "owner": owner, "schema": schema}
    finally:
        app.dispose()
        owner.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
            conn.execute(text(f"DROP ROLE IF EXISTS {_qi(role)}"))
        admin.dispose()


def _session(ctx, tenant: str | None):
    session = sessionmaker(bind=ctx["app"])()
    set_tenant_context(session, tenant)
    return session


def test_migration_backfills_tenant_and_force_rls_is_active(pg_evidence):
    with pg_evidence["owner"].connect() as conn:
        for table in RISK_EVIDENCE_TENANT_TABLES:
            forced = conn.execute(text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = :t"
            ), {"s": pg_evidence["schema"], "t": table}).scalar()
            assert forced is True, table


@pytest.mark.parametrize(
    ("table", "own", "foreign"),
    [("risk_profile_signoffs", "s-a", "s-b"), ("risk_override_decisions", "d-a", "d-b")],
)
def test_select_is_tenant_bound(pg_evidence, table, own, foreign):
    with _session(pg_evidence, "t-a") as db:
        rows = dict(db.execute(text(f"SELECT id, tenant_id FROM {table}")).all())
        assert rows.get(own) == "t-a"
        assert foreign not in rows
    with _session(pg_evidence, None) as db:
        assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0


def test_insert_derives_tenant_and_rejects_spoofing_and_foreign_mandate(pg_evidence):
    with _session(pg_evidence, "t-a") as db:
        _signoff(db.connection(), "s-new", "m-a", "c-a")
        assert db.execute(text(
            "SELECT tenant_id FROM risk_profile_signoffs WHERE id = 's-new'"
        )).scalar() == "t-a"
        db.rollback()
    for builder, values in (
        (_signoff, {"sid": "x1", "mandate_id": "m-a", "client_id": "c-a", "tenant_id": "t-b"}),
        (_signoff, {"sid": "x2", "mandate_id": "m-b", "client_id": "c-b"}),
        (_signoff, {"sid": "x3", "mandate_id": "m-b", "client_id": "c-b", "tenant_id": "t-a"}),
        (_signoff, {"sid": "x4", "mandate_id": "m-a", "client_id": "c-b"}),
        (_decision, {"did": "y1", "mandate_id": "m-a", "client_id": "c-a", "tenant_id": "t-b"}),
        (_decision, {"did": "y2", "mandate_id": "m-b", "client_id": "c-b"}),
    ):
        with _session(pg_evidence, "t-a") as db:
            with pytest.raises(DBAPIError):
                builder(db.connection(), **values)
            db.rollback()


@pytest.mark.parametrize(
    "statement",
    ["UPDATE risk_profile_signoffs SET note = 'x' WHERE id = 's-a'",
     "DELETE FROM risk_override_decisions WHERE id = 'd-a'"],
)
def test_append_only_still_holds(pg_evidence, statement):
    with _session(pg_evidence, "t-a") as db:
        with pytest.raises(DBAPIError):
            db.execute(text(statement))
        db.rollback()


def test_coverage_guard_reports_exactly_the_table_without_policy(pg_evidence):
    schema = pg_evidence["schema"]
    with pg_evidence["owner"].begin() as conn:
        assert tenant_tables_missing_rls_policies(
            conn, table_names=RISK_EVIDENCE_TENANT_TABLES, schema=schema,
        ) == []
        conn.execute(text("DROP POLICY IF EXISTS tenant_isolation ON risk_profile_signoffs"))
        assert tenant_tables_missing_rls_policies(
            conn, table_names=RISK_EVIDENCE_TENANT_TABLES, schema=schema,
        ) == ["risk_profile_signoffs"]
        ensure_postgres_rls_policies(conn, table_names=("risk_profile_signoffs",))
        assert tenant_tables_missing_rls_policies(
            conn, table_names=RISK_EVIDENCE_TENANT_TABLES, schema=schema,
        ) == []
