"""H10 (DSG-Technikaudit 2026-11-11) live auf PostgreSQL: die neuen
Datenschutz-Tabellen unter FORCE RLS.

Echte Migrationskette in ein Wegwerf-Schema (inkl. Downgrade/Upgrade der drei
H10-Revisionen), Boot-RLS-Plan (``ensure_postgres_rls_policies``), Proben als
NICHT-Owner, NICHT-Superuser, NOBYPASSRLS mit zwei Mandanten:

* ``privacy_owner_values``, ``privacy_subject_requests``,
  ``privacy_security_incidents`` haben RLS ENABLE + FORCE und eine Policy;
* SELECT ist mandantengebunden, ohne Mandant unsichtbar;
* INSERT mit fremdem Mandanten wird abgewiesen;
* der CHECK "hohes Risiko nur melden" greift auch auf PostgreSQL.

Uebersprungen ohne ``POSTGRES_TEST_DATABASE_URL`` (CI-Job ``postgres-rls``).
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.postgres_rls import (  # noqa: E402
    ensure_postgres_rls_policies,
    tenant_tables_missing_rls_policies,
)
from services.tenant_context import attach_tenant_context_reset, set_tenant_context  # noqa: E402
from tests.test_postgres_mandate_evidence_tenant_boundary_live import (  # noqa: E402
    _alembic_cfg,
    _qi,
    _required_columns,
    _scoped_url,
)
from tests.test_tenant_database_boundary import _raw_insert  # noqa: E402

TABLES = ("privacy_owner_values", "privacy_subject_requests", "privacy_security_incidents",
          "processing_activity_versions", "outbound_processing_manifest_versions", "privacy_egress_events",
          "privacy_subject_request_events", "privacy_security_incident_events")
APPEND_ONLY = TABLES[3:]
FIRST_H10_DOWN = "d8e4b2a6c1f9"
_NUMERIC = ("integer", "bigint", "smallint", "numeric", "double precision", "real")
_VALUES = {
    "status": {"privacy_owner_values": "CONFIRMED", "privacy_subject_requests": "RECEIVED",
               "privacy_security_incidents": "OPEN", "processing_activity_versions": "APPROVED",
               "outbound_processing_manifest_versions": "APPROVED"},
    "result": "BLOCKED",
    "request_type": "ACCESS", "received_channel": "LETTER", "requester_relation": "SELF",
    "incident_type": "AVAILABILITY",
}


def _row(conn, table: str, row_id: str, **values) -> None:
    row: dict[str, object] = {}
    for name, dtype in _required_columns(conn, table).items():
        row[name] = 1 if dtype in _NUMERIC else f"{row_id}-{name}"
    for name, value in _VALUES.items():
        if name in row:
            row[name] = value[table] if isinstance(value, dict) else value
    row.update(id=row_id, **values)
    columns = ", ".join(row)
    params = ", ".join(f":{key}" for key in row)
    conn.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({params})"), row)


@pytest.fixture(scope="module")
def pg_ctx():
    pytest.importorskip("psycopg")
    assert POSTGRES_URL is not None
    from alembic import command

    token = uuid.uuid4().hex[:12]
    schema, role, password = f"h10_{token}", f"h10_app_{token}", f"pw_{token}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    scoped = _scoped_url(POSTGRES_URL, schema)
    owner = create_engine(scoped, future=True)
    app = None
    try:
        command.upgrade(_alembic_cfg(scoped), "head")
        command.downgrade(_alembic_cfg(scoped), FIRST_H10_DOWN)
        with owner.connect() as conn:
            assert not set(TABLES) & set(inspect(conn).get_table_names())
        command.upgrade(_alembic_cfg(scoped), "head")
        with owner.begin() as conn:
            for tid in ("t-a", "t-b"):
                _raw_insert(conn, "tenants", id=tid, display_name=tid, slug=tid)
            for table in TABLES:
                for tid in ("t-a", "t-b"):
                    _row(conn, table, f"{table}-{tid}", tenant_id=tid)
            ensure_postgres_rls_policies(conn)
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
        yield {"app": app, "owner": owner, "schema": schema}
    finally:
        if app is not None:
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


def test_boot_plan_covers_h10_tables_with_force_rls(pg_ctx):
    with pg_ctx["owner"].connect() as conn:
        assert tenant_tables_missing_rls_policies(conn, table_names=TABLES, schema=pg_ctx["schema"]) == []
        for table in TABLES:
            forced = conn.execute(text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = :t"
            ), {"s": pg_ctx["schema"], "t": table}).scalar()
            assert forced is True, table


@pytest.mark.parametrize("table", TABLES)
def test_select_is_tenant_bound(pg_ctx, table):
    for tenant in ("t-a", "t-b"):
        with _session(pg_ctx, tenant) as db:
            rows = dict(db.execute(text(f"SELECT id, tenant_id FROM {table}")).all())
            assert rows == {f"{table}-{tenant}": tenant}
    with _session(pg_ctx, None) as db:
        assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0


@pytest.mark.parametrize("table", TABLES)
def test_insert_with_foreign_tenant_is_rejected(pg_ctx, table):
    with _session(pg_ctx, "t-a") as db:
        _row(db.connection(), table, f"{table}-own", tenant_id="t-a")
        db.rollback()
    with _session(pg_ctx, "t-a") as db:
        with pytest.raises(DBAPIError):
            _row(db.connection(), table, f"{table}-x", tenant_id="t-b")
        db.rollback()


def test_high_risk_without_notification_is_rejected_by_check(pg_ctx):
    with _session(pg_ctx, "t-a") as db:
        with pytest.raises(DBAPIError):
            _row(db.connection(), "privacy_security_incidents", "inc-check", tenant_id="t-a",
                 risk_level="HIGH", notification_decision="NOT_REQUIRED")
        db.rollback()



@pytest.mark.parametrize("table", APPEND_ONLY)
@pytest.mark.parametrize("statement", ["UPDATE {t} SET tenant_id = tenant_id WHERE id = :id",
                                       "DELETE FROM {t} WHERE id = :id"])
def test_nachtrag1_tables_are_append_only(pg_ctx, table, statement):
    with _session(pg_ctx, "t-a") as db:
        with pytest.raises(DBAPIError):
            db.execute(text(statement.format(t=table)), {"id": f"{table}-t-a"})
        db.rollback()


@pytest.mark.parametrize("table", ["privacy_subject_requests", "privacy_security_incidents"])
def test_two_concurrent_status_changes_one_wins_on_postgres(pg_ctx, table):
    """Nachtrag 1: optimistische Sperre (row_version) unter echter RLS."""
    from sqlalchemy.orm.exc import StaleDataError

    from models.privacy import PrivacySecurityIncident, PrivacySubjectRequest

    model = PrivacySubjectRequest if table == "privacy_subject_requests" else PrivacySecurityIncident
    field, values = ("status", ("IDENTITY_VERIFIED", "WITHDRAWN")) if model is PrivacySubjectRequest         else ("risk_level", ("LOW", "HIGH"))
    first, second = _session(pg_ctx, "t-a"), _session(pg_ctx, "t-a")
    try:
        a, b = first.get(model, f"{table}-t-a"), second.get(model, f"{table}-t-a")
        assert a is not None and b is not None
        setattr(a, field, values[0])
        setattr(b, field, values[1])
        first.commit()
        with pytest.raises(StaleDataError):
            second.commit()
    finally:
        first.close()
        second.close()
    with pg_ctx["owner"].connect() as conn:
        assert conn.execute(text(f"SELECT {field}, row_version FROM {table} WHERE id = :id"),
                            {"id": f"{table}-t-a"}).one() == (values[0], 2)


def test_event_sequence_unique_on_postgres(pg_ctx):
    with _session(pg_ctx, "t-a") as db:
        _row(db.connection(), "privacy_subject_request_events", "ev-1", tenant_id="t-a", case_id="c", sequence=7)
        with pytest.raises(DBAPIError):
            _row(db.connection(), "privacy_subject_request_events", "ev-2", tenant_id="t-a", case_id="c",
                 sequence=7)
        db.rollback()
