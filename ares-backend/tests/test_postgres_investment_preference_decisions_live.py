"""N-888-08 (Pruefrunde ESG @ 99784e5a): investment_preference_decisions live
auf PostgreSQL unter FORCE RLS.

Echte Migrationskette bis Head in ein Wegwerf-Schema, Boot-RLS-Plan
(``ensure_postgres_rls_policies`` ohne Tabellenliste, wie ``init_db``), Probe
als NON-owner/NON-superuser/NOBYPASSRLS-Rolle mit zwei Mandanten:

* RLS ENABLE + FORCE und Policy fuer die Tabelle;
* SELECT mandantengebunden, ohne Kontext nichts sichtbar;
* INSERT leitet ``tenant_id`` aus dem Mandat ab (Funktion
  ``mandate_evidence_tenant_from_mandate``) und lehnt gespooften Mandanten,
  fremdes Mandat und fremden Kunden ab;
* append-only: UPDATE/DELETE scheitern (``trg_..._immutable``), auch fuer den
  Tabellen-Owner.

Ohne ``POSTGRES_TEST_DATABASE_URL`` uebersprungen (CI-Job ``postgres-rls``).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from tests.test_postgres_mandate_evidence_tenant_boundary_live import (  # noqa: F401
    POSTGRES_URL,
    _alembic_cfg,
    _mandate,
    _qi,
    _scoped_url,
    pytestmark,
)
from tests.test_tenant_database_boundary import _raw_insert

TABLE = "investment_preference_decisions"


def _decision(conn, row_id: str, mandate_id: str, client_id: str, seq: int, **extra) -> None:
    values = {
        "id": row_id, "schema_version": "InvestmentPreferenceDecisionV1",
        "mandate_id": mandate_id, "client_id": client_id, "sequence_no": seq,
        "questionnaire_version": "praeferenzen-v1", "definition_hash": "d" * 64,
        "derivation_version": "praeferenzen-ableitung-v1", "response_status": "answered",
        "esg_relevance": "not_relevant", "exclusions_json": "[]", "preference_waived": 0,
        "profile_code": "no_preference", "information_acknowledged": 1, "client_confirmed": 1,
        "capture_channel": "in_person", "review_policy_version": "praeferenz-review-v1",
        "review_policy_months": 36, "review_due_on": "2029-11-07", "captured_by": "adv",
        "captured_at": "2026-11-07T00:00:00Z", "decision_hash": "h" * 64,
        "created_at": "2026-11-07T00:00:00Z",
    }
    values.update(extra)
    columns = ", ".join(values)
    params = ", ".join(f":{key}" for key in values)
    conn.execute(text(f"INSERT INTO {TABLE} ({columns}) VALUES ({params})"), values)


@pytest.fixture(scope="module")
def pg_ipd():
    pytest.importorskip("psycopg")
    from alembic import command

    from services.postgres_rls import ensure_postgres_rls_policies
    from services.tenant_context import attach_tenant_context_reset

    token = uuid.uuid4().hex[:12]
    schema, role, password = f"ipd_{token}", f"ipd_app_{token}", f"pw_{token}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    scoped = _scoped_url(POSTGRES_URL, schema)
    owner = create_engine(scoped, future=True)
    app = None
    try:
        command.upgrade(_alembic_cfg(scoped), "head")
        with owner.begin() as conn:
            for tid in ("t-a", "t-b"):
                _raw_insert(conn, "tenants", id=tid, display_name=tid, slug=tid)
            _raw_insert(conn, "users", id="adv", tenant_id="t-a")
            for cid, tid in (("c-a", "t-a"), ("c-b", "t-b")):
                _raw_insert(conn, "clients", id=cid, client_number=cid, tenant_id=tid)
            _mandate(conn, "m-a", "c-a", "t-a")
            _mandate(conn, "m-b", "c-b", "t-b")
            _decision(conn, "ipd-a", "m-a", "c-a", 1)
            _decision(conn, "ipd-b", "m-b", "c-b", 1)
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


def _session(ctx, tenant):
    from services.tenant_context import set_tenant_context

    session = sessionmaker(bind=ctx["app"])()
    set_tenant_context(session, tenant)
    return session


def test_force_rls_and_policy(pg_ipd):
    from services.postgres_rls import tenant_scoped_table_names, tenant_tables_missing_rls_policies

    assert TABLE in set(tenant_scoped_table_names())
    with pg_ipd["owner"].connect() as conn:
        assert tenant_tables_missing_rls_policies(conn, table_names=(TABLE,), schema=pg_ipd["schema"]) == []
        forced = conn.execute(text(
            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
            "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = :t"
        ), {"s": pg_ipd["schema"], "t": TABLE}).scalar()
    assert forced is True


def test_select_is_tenant_bound(pg_ipd):
    with _session(pg_ipd, "t-a") as db:
        assert dict(db.execute(text(f"SELECT id, tenant_id FROM {TABLE}")).all()) == {"ipd-a": "t-a"}
    with _session(pg_ipd, "t-b") as db:
        assert dict(db.execute(text(f"SELECT id, tenant_id FROM {TABLE}")).all()) == {"ipd-b": "t-b"}
    with _session(pg_ipd, None) as db:
        assert db.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar() == 0


def test_insert_derives_tenant_from_mandate(pg_ipd):
    with _session(pg_ipd, "t-a") as db:
        _decision(db.connection(), "ipd-a2", "m-a", "c-a", 2)
        assert db.execute(text(f"SELECT tenant_id FROM {TABLE} WHERE id = 'ipd-a2'")).scalar() == "t-a"
        db.rollback()


@pytest.mark.parametrize("variant", [
    {"mandate_id": "m-a", "client_id": "c-a", "tenant_id": "t-b"},  # gespoofter Mandant
    {"mandate_id": "m-b", "client_id": "c-b"},                      # fremdes Mandat (unsichtbar)
    {"mandate_id": "m-a", "client_id": "c-b"},                      # fremder Kunde
])
def test_foreign_tenant_cannot_write(pg_ipd, variant):
    with _session(pg_ipd, "t-a") as db:
        with pytest.raises(DBAPIError):
            _decision(db.connection(), "ipd-x", seq=5, **variant)
        db.rollback()


@pytest.mark.parametrize("statement", [
    f"UPDATE {TABLE} SET profile_code = 'declined' WHERE id = 'ipd-a'",
    f"DELETE FROM {TABLE} WHERE id = 'ipd-a'",
])
def test_append_only_for_app_and_owner(pg_ipd, statement):
    with _session(pg_ipd, "t-a") as db:
        with pytest.raises(DBAPIError):
            db.execute(text(statement))
        db.rollback()
    with pg_ipd["owner"].connect() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text(statement))
        conn.rollback()


def test_upgrade_downgrade_upgrade_on_postgres():
    """Codex-Vertrag E2: PostgreSQL besteht upgrade -> downgrade (vor E2) ->
    upgrade; danach sind Tabelle, Trigger und beide Dokumentbindungen da."""
    pytest.importorskip("psycopg")
    from alembic import command
    from sqlalchemy import inspect

    token = uuid.uuid4().hex[:12]
    schema = f"ipdmig_{token}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    scoped = _scoped_url(POSTGRES_URL, schema)
    engine = create_engine(scoped, future=True)
    try:
        cfg = _alembic_cfg(scoped)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "d3b7f1a5c9e2")
        with engine.connect() as conn:
            insp = inspect(conn)
            assert TABLE not in insp.get_table_names(schema=schema)
            doc_cols = {c["name"] for c in insp.get_columns("contract_documents", schema=schema)}
            assert not doc_cols & {"bound_preference_decision_hash", "bound_target_allocation_id"}
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            insp = inspect(conn)
            assert TABLE in insp.get_table_names(schema=schema)
            doc_cols = {c["name"] for c in insp.get_columns("contract_documents", schema=schema)}
            assert {"bound_preference_decision_hash", "bound_target_allocation_id",
                    "bound_preferences_sha256"} <= doc_cols
            triggers = {r[0] for r in conn.execute(text(
                "SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = :t"
            ), {"s": schema, "t": TABLE})}
            assert {f"trg_{TABLE}_immutable", f"trg_{TABLE}_tenant_guard"} <= triggers
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
        admin.dispose()
