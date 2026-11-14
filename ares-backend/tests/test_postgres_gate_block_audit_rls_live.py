"""RC-CH-1 Teil 2b (Integration E2 x H7 N-884-09): E2-Gate-Sperren schreiben
ihre Audit-Zeile unter ECHTER PostgreSQL-RLS mit dem richtigen Tenant.

``services.audit.gate_block_audit`` (E2: Erfassung/Untergrenze/Nachweis der
Nachhaltigkeitspraeferenz in Kunden-PDF, Finalisierung, Signatur, Vor-Ort,
Handoff) verwirft offene Aenderungen per ``db.rollback()`` und schreibt dann
den Audit-Eintrag. Unter PostgreSQL macht der Rollback den per
``set_config(..., false)`` gesetzten Tenant-Kontext rueckgaengig; ohne
Wiederherstellung scheitert der Insert an der RLS-Policy (WITH CHECK) von
``audit_log`` -- das Muster, das H7 fuer release_block_audit behoben hat.

Ausgeloest wird der echte E2-Sperrpfad ``_preference_block`` (gemeinsamer
Pfad aller Praeferenz-Gates). Aufbau wie
test_postgres_release_block_audit_rls_live.py: eigenes Schema,
unprivilegierte App-Rolle (nicht Owner, kein BYPASSRLS), FORCE RLS. Ohne
``POSTGRES_TEST_DATABASE_URL`` uebersprungen; der CI-Job ``postgres-rls``
setzt sie.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

TENANT = "tenant-gb"
USER_ID = "adv-gb"
FIELD = "sustainability_preference_blocked"


def _qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _with_search_path(url: str, schema: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}options=-csearch_path%3D{schema}"


@pytest.fixture()
def rls_app():
    pytest.importorskip("psycopg")
    from models.review import AuditLog, AuditLogSequenceCounter
    from models.tenant import Tenant
    from models.users import User
    from services.postgres_rls import ensure_postgres_rls_policies
    from services.tenant_context import attach_tenant_context_reset

    assert POSTGRES_URL is not None
    token = uuid.uuid4().hex[:12]
    schema = f"gbaudit_{token}"
    role = f"gbaudit_app_{token}"
    password = f"pw_{token}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE ROLE {_qi(role)} LOGIN PASSWORD '{password}'"))
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    owner = create_engine(_with_search_path(POSTGRES_URL, schema), future=True)
    AuditLog.__table__.create(bind=owner)
    AuditLogSequenceCounter.__table__.create(bind=owner)
    Tenant.__table__.create(bind=owner)
    User.__table__.create(bind=owner)
    now = "2026-11-14T10:00:00.000Z"
    with sessionmaker(bind=owner)() as seed:
        seed.add(Tenant(id=TENANT, display_name="Tenant GB", slug=f"gb-{token}", created_at=now, updated_at=now))
        seed.flush()
        seed.add(User(id=USER_ID, tenant_id=TENANT, username=f"gb-{token}", password_hash="x",
                      full_name="Berater GB", role="advisor", created_at=now, updated_at=now))
        seed.commit()
    with owner.begin() as conn:
        conn.execute(text("INSERT INTO audit_log_sequence_counter (id, value) VALUES ('singleton', 0)"))
        ensure_postgres_rls_policies(conn, table_names=("audit_log",))
        conn.execute(text(f"GRANT USAGE ON SCHEMA {_qi(schema)} TO {_qi(role)}"))
        conn.execute(text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {_qi(schema)} TO {_qi(role)}"
        ))
    app_url = make_url(POSTGRES_URL).set(username=role, password=password).render_as_string(hide_password=False)
    app_engine = create_engine(_with_search_path(app_url, schema), future=True)
    attach_tenant_context_reset(app_engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=app_engine)
    try:
        yield factory
    finally:
        app_engine.dispose()
        owner.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
            conn.execute(text(f"DROP ROLE IF EXISTS {_qi(role)}"))
        admin.dispose()


def _request_session(factory):
    """Wie im Request: Kontext innerhalb der laufenden Transaktion gesetzt."""
    from services.tenant_context import set_tenant_context

    session = factory()
    set_tenant_context(session, TENANT)
    session.execute(text("SELECT COUNT(*) FROM audit_log")).scalar_one()
    return session


def _callback(session, *, restore):
    from services.audit import gate_block_audit
    from services.tenant_context import set_tenant_context

    return gate_block_audit(
        session, user=SimpleNamespace(id=USER_ID, full_name="Berater GB"),
        mandate=SimpleNamespace(id="mandate-gb", client_id="client-gb"), ip_address="127.0.0.1",
        table_name="investment_preference_decisions", field_name=FIELD,
        set_tenant_context=set_tenant_context if restore else None,
    )


def _trigger_e2_block(session, audit):
    """Echter E2-Sperrpfad (alle Praeferenz-Gates): Audit, dann DomainError."""
    from core.reason_codes import DomainError
    from services.recommendation_release_gate import CHANNEL_SIGNATURE, _preference_block

    with pytest.raises(DomainError) as exc:
        _preference_block(
            {"state": "stale", "stale_reasons": ["policy_version"], "decision": {"id": "dec-gb"}},
            CHANNEL_SIGNATURE, audit, "SUSTAINABILITY_PREFERENCE_STALE",
            "Nachhaltigkeitspraeferenz veraltet", "stale",
        )
    return exc.value


def _rows(factory):
    from services.tenant_context import operator_bypass

    with factory() as s:
        with operator_bypass(s):
            return s.execute(text(
                "SELECT tenant_id, table_name, field_name, record_id, new_value FROM audit_log ORDER BY sequence"
            )).all()


def test_e2_gate_block_under_rls_writes_audit_row_with_tenant(rls_app):
    session = _request_session(rls_app)
    try:
        exc = _trigger_e2_block(session, _callback(session, restore=True))
    finally:
        session.close()
    assert exc.as_detail()["reason_code"] == "SUSTAINABILITY_PREFERENCE_STALE"
    rows = _rows(rls_app)
    assert len(rows) == 1
    tenant_id, table_name, field_name, record_id, new_value = rows[0]
    assert (tenant_id, table_name, field_name, record_id) == (
        TENANT, "investment_preference_decisions", FIELD, "dec-gb")
    payload = json.loads(new_value)
    assert payload["event"] == "sustainability_preference_release_blocked"
    assert (payload["channel"], payload["state"], payload["decision_id"]) == ("signature", "stale", "dec-gb")
    # sichtbar unter dem eigenen Tenant, unsichtbar ohne Kontext
    from services.tenant_context import set_tenant_context

    with rls_app() as s:
        set_tenant_context(s, TENANT)
        assert s.execute(text("SELECT COUNT(*) FROM audit_log")).scalar_one() == 1
    with rls_app() as s:
        assert s.execute(text("SELECT COUNT(*) FROM audit_log")).scalar_one() == 0


def test_negative_control_without_restore_rls_rejects_the_audit_row(rls_app):
    """Gegenprobe zum Befund: ohne Wiederherstellung nach dem Rollback fehlt
    app.tenant_id -- der Audit-Insert scheitert an RLS, es entsteht keine
    Zeile. Belegt, dass der positive Test den Fix prueft."""
    from services.tenant_context import TENANT_GUC

    probe = _request_session(rls_app)
    try:
        probe.rollback()
        after = probe.execute(text("SELECT current_setting(:n, true)"), {"n": TENANT_GUC}).scalar()
    finally:
        probe.close()
    if after:
        pytest.skip(f"PG hat den Tenant-Kontext beim Rollback nicht verworfen ({after!r}); Befundpraemisse entfaellt")
    session = _request_session(rls_app)
    try:
        with pytest.raises(Exception) as exc:  # noqa: B017 -- RLS-/DB-Fehler statt DomainError
            _trigger_e2_block(session, _callback(session, restore=False))
        assert "DomainError" not in type(exc.value).__name__
    finally:
        session.rollback()
        session.close()
    assert _rows(rls_app) == []
