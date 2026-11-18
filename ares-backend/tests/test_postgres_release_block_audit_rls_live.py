"""H7 N-884-09: Retro-Sperre unter ECHTER PostgreSQL-RLS schreibt ihre
Audit-Zeile mit dem richtigen Tenant.

Unter PostgreSQL setzt ``services.tenant_context.set_tenant_context`` den
Kontext per ``set_config(..., false)``. Geschieht das in der laufenden
Transaktion, macht ``db.rollback()`` es rueckgaengig. Der Audit-Insert der
Freigabe-Sperre (``services.audit.release_block_audit``) liefe dann ohne
``app.tenant_id`` und scheiterte an der RLS-Policy (WITH CHECK) von
``audit_log``. Der Callback setzt den Kontext nach dem Rollback wieder.

Aufbau wie ``test_postgres_audit_chain_rls_live.py``: eigenes Schema,
unprivilegierte App-Rolle (nicht Owner, kein BYPASSRLS), FORCE RLS.
Ohne ``POSTGRES_TEST_DATABASE_URL`` uebersprungen; der CI-Job
``postgres-rls`` setzt sie.
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

TENANT = "tenant-rb"
USER_ID = "adv-rb"


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
    schema = f"rbaudit_{token}"
    role = f"rbaudit_app_{token}"
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
    # log() leitet tenant_id aus users.tenant_id des Akteurs her.
    now = "2026-11-07T10:00:00.000Z"
    with sessionmaker(bind=owner)() as seed:
        seed.add(Tenant(id=TENANT, display_name="Tenant RB", slug=f"rb-{token}", created_at=now, updated_at=now))
        seed.flush()
        seed.add(User(id=USER_ID, tenant_id=TENANT, username=f"rb-{token}", password_hash="x",
                      full_name="Berater RB", role="advisor", created_at=now, updated_at=now))
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


def _legacy_final_run():
    """Finaler Lauf mit eingefrorenem, unvollstaendigem Retro-Ausweis."""
    payload = {"product_retrocessions": {"complete": False, "lines": []}, "cost_items": []}
    return SimpleNamespace(
        id="run-rb", result_status="Final",
        cost_disclosure_snapshot_json=json.dumps({"payload": payload}),
    )


def _trigger_retro_block(session, *, restore):
    from core.reason_codes import DomainError
    from services.audit import release_block_audit
    from services.recommendation_release_gate import CHANNEL_SIGNATURE, assert_retrocession_release_eligible
    from services.tenant_context import set_tenant_context

    user = SimpleNamespace(id=USER_ID, full_name="Berater RB", tenant_id=TENANT)
    on_block = release_block_audit(
        session, user=user, ip_address="127.0.0.1", mandate_id="mandate-rb",
        field_name="signature_blocked",
        set_tenant_context=set_tenant_context if restore else None,
    )
    with pytest.raises(DomainError) as exc:
        assert_retrocession_release_eligible(
            session, SimpleNamespace(id="mandate-rb"), channel=CHANNEL_SIGNATURE,
            run=_legacy_final_run(), on_block=on_block,
        )
    return exc.value


def _request_session(factory):
    """Wie im Request: Kontext innerhalb der laufenden Transaktion gesetzt."""
    from services.tenant_context import set_tenant_context

    session = factory()
    set_tenant_context(session, TENANT)
    # Lesezugriff unter Tenant-Kontext in derselben Transaktion.
    session.execute(text("SELECT COUNT(*) FROM audit_log")).scalar_one()
    return session


def _rows(factory):
    from services.tenant_context import operator_bypass

    with factory() as s:
        with operator_bypass(s):
            return s.execute(text(
                "SELECT tenant_id, field_name, new_value, record_id FROM audit_log ORDER BY sequence"
            )).all()


def test_retro_block_under_rls_writes_audit_row_with_tenant(rls_app):
    session = _request_session(rls_app)
    try:
        exc = _trigger_retro_block(session, restore=True)
    finally:
        session.close()
    assert exc.as_detail()["reason_code"] == "RETROCESSION_DISCLOSURE_INCOMPLETE"
    rows = _rows(rls_app)
    assert [tuple(r) for r in rows] == [
        (TENANT, "signature_blocked", "RETROCESSION_DISCLOSURE_INCOMPLETE", "run-rb"),
    ]
    # sichtbar unter dem eigenen Tenant, unsichtbar ohne Kontext
    from services.tenant_context import set_tenant_context

    with rls_app() as s:
        set_tenant_context(s, TENANT)
        assert s.execute(text("SELECT COUNT(*) FROM audit_log")).scalar_one() == 1
    with rls_app() as s:
        assert s.execute(text("SELECT COUNT(*) FROM audit_log")).scalar_one() == 0


def test_negative_control_without_restore_rls_rejects_the_audit_row(rls_app):
    """Gegenprobe zum Befund: ohne Wiederherstellung nach dem Rollback fehlt
    app.tenant_id -- der Insert scheitert an RLS (oder es entsteht keine
    Zeile). Belegt, dass der positive Test den Fix prueft."""
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
        with pytest.raises(Exception):  # noqa: B017 -- RLS-/DB-Fehler, nicht DomainError
            from services.audit import release_block_audit

            user = SimpleNamespace(id=USER_ID, full_name="Berater RB", tenant_id=TENANT)
            release_block_audit(
                session, user=user, ip_address=None, mandate_id="mandate-rb",
                field_name="signature_blocked", set_tenant_context=None,
            )("RETROCESSION_DISCLOSURE_INCOMPLETE", "run-rb")
    finally:
        session.rollback()
        session.close()
    assert _rows(rls_app) == []
