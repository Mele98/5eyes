"""N-869-4 (Pruefrunde #869): Audit-Kette unter ECHTER PostgreSQL-RLS.

``audit_log`` traegt ``tenant_id`` und steht unter der strikten Policy aus
``services/postgres_rls.py`` (``tenant_id = app.tenant_id OR app.rls_bypass``,
FORCE ROW LEVEL SECURITY). Superuser umgehen RLS immer -- dieser Test legt
deshalb eine eigene, unprivilegierte Rolle an (Muster
``test_postgres_rls_adversarial.py``).

Geprueft wird:
* log() verkettet bei abwechselnden Tenants lueckenlos (vorher: previous_hash
  '' bei jedem Wechsel, weil der Vorgaenger unsichtbar war);
* ohne Operator-Bypass sieht eine Session ohne Tenant-Kontext 0 Zeilen --
  der Verifier meldet dann (wegen des Zaehlers) "Kettenende fehlt";
* der Admin-Endpoint und die Startpruefung laufen im Bypass: ok, kein
  CRITICAL;
* Alembic c8a2f4e6b0d9 traegt last_hash nach (up/down/up).

Ohne ``POSTGRES_TEST_DATABASE_URL`` wird uebersprungen; in CI setzt der
``postgres-rls``-Job sie.
"""
from __future__ import annotations

import logging
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

LAST_HASH_REVISION = "c8a2f4e6b0d9"


def _qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _with_search_path(url: str, schema: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}options=-csearch_path%3D{schema}"


@pytest.fixture()
def rls_app():
    """Schema mit audit_log (+ RLS-Policy) und Zaehler, App-Rolle ohne
    Superuser/BYPASSRLS, nicht Owner."""
    pytest.importorskip("psycopg")
    from models.review import AuditLog, AuditLogSequenceCounter
    from services.postgres_rls import ensure_postgres_rls_policies
    from services.tenant_context import attach_tenant_context_reset

    assert POSTGRES_URL is not None
    token = uuid.uuid4().hex[:12]
    schema = f"auditrls_{token}"
    role = f"auditrls_app_{token}"
    password = f"pw_{token}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE ROLE {_qi(role)} LOGIN PASSWORD '{password}'"))
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    owner = create_engine(_with_search_path(POSTGRES_URL, schema), future=True)
    AuditLog.__table__.create(bind=owner)
    AuditLogSequenceCounter.__table__.create(bind=owner)
    # log() schlaegt ohne explizite tenant_id den Akteur in users nach
    # (System-Eintraege wie das Bestandssiegel).
    from models.tenant import Tenant
    from models.users import User

    Tenant.__table__.create(bind=owner)
    User.__table__.create(bind=owner)
    with owner.begin() as conn:
        conn.execute(text("INSERT INTO audit_log_sequence_counter (id, value) VALUES ('singleton', 0)"))
        ensure_postgres_rls_policies(conn, table_names=("audit_log",))
        conn.execute(text(f"GRANT USAGE ON SCHEMA {_qi(schema)} TO {_qi(role)}"))
        conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {_qi(schema)} TO {_qi(role)}"))
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


def _log_as(factory, tenant: str, record_id: str) -> None:
    from services.audit import log
    from services.tenant_context import set_tenant_context

    with factory() as s:
        set_tenant_context(s, tenant)
        log(s, user_id=f"u-{tenant}", user_name="A", table_name="clients",
            record_id=record_id, action="UPDATE", tenant_id=tenant)
        s.commit()


def _alternate(factory) -> None:
    for i, tenant in enumerate(["tenant-a", "tenant-b", "tenant-a", "tenant-b", "tenant-b", "tenant-a"]):
        _log_as(factory, tenant, f"r{i}")


def test_rls_is_really_active_for_the_app_role(rls_app):
    _alternate(rls_app)
    from services.tenant_context import set_tenant_context

    with rls_app() as s:
        set_tenant_context(s, "tenant-a")
        assert s.execute(text("SELECT COUNT(*) FROM audit_log")).scalar_one() == 3
    with rls_app() as s:
        assert s.execute(text("SELECT COUNT(*) FROM audit_log")).scalar_one() == 0


def test_alternating_tenants_form_one_linear_chain(rls_app):
    from services.audit import audit_log_integrity_report
    from services.tenant_context import operator_bypass

    _alternate(rls_app)
    with rls_app() as s:
        with operator_bypass(s):
            rows = s.execute(text(
                "SELECT sequence, previous_hash, integrity_hash FROM audit_log ORDER BY sequence"
            )).all()
            report = audit_log_integrity_report(s)
    assert [r[0] for r in rows] == [1, 2, 3, 4, 5, 6]
    for prev, cur in zip(rows, rows[1:]):
        assert cur[1] == prev[2], f"Kette bricht bei sequence={cur[0]}"
    assert report["ok"], report
    assert report["chain"]["checked"] == 6


def test_without_bypass_the_check_is_blind_with_bypass_it_is_ok(rls_app, caplog):
    from routers.system import verify_audit_log_chain
    from services.audit import _verify_audit_chain_detail, run_startup_audit_chain_check
    from services.tenant_context import operator_bypass

    _alternate(rls_app)
    with rls_app() as s:
        blind = _verify_audit_chain_detail(s)
    assert blind["checked"] == 0 and not blind["ok"]  # Schein-Alarm ohne Bypass

    with rls_app() as s:
        body = verify_audit_log_chain(db=s, current_user=SimpleNamespace(role="super_admin"))
    assert body["ok"] and body["chain"]["checked"] == 6

    with caplog.at_level(logging.INFO, logger="services.audit"):
        report = run_startup_audit_chain_check(rls_app, read_scope=operator_bypass)
    assert report is not None and report["ok"]
    assert not [r for r in caplog.records if r.levelno >= logging.CRITICAL]


# ---------------------------------------------------------------------------
# Alembic c8a2f4e6b0d9: last_hash nachtragen (up/down/up)
# ---------------------------------------------------------------------------

@pytest.fixture()
def pg_alembic():
    pytest.importorskip("psycopg")
    from alembic.config import Config as AlembicConfig

    assert POSTGRES_URL is not None
    schema = f"auditlh_{uuid.uuid4().hex[:12]}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    scoped_url = _with_search_path(POSTGRES_URL, schema)
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", scoped_url.replace("%", "%%"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    engine = create_engine(scoped_url, future=True)
    try:
        yield cfg, engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {_qi(schema)} CASCADE"))
        admin.dispose()


def test_migration_backfills_last_hash_and_downgrades(pg_alembic):
    from alembic import command
    from alembic.script import ScriptDirectory

    cfg, engine = pg_alembic
    previous = ScriptDirectory(str(BACKEND_ROOT / "alembic")).get_revision(LAST_HASH_REVISION).down_revision
    command.upgrade(cfg, previous)
    with engine.begin() as conn:
        for seq, h in ((1, "a" * 64), (2, "b" * 64)):
            conn.execute(text(
                "INSERT INTO audit_log (id, user_name, table_name, record_id, action, created_at,"
                " sequence, integrity_hash, previous_hash)"
                " VALUES (:id, 'x', 't', 'r', 'CREATE', '2026-11-05T00:00:00Z', :s, :h, '')"
            ), {"id": f"row-{seq}", "s": seq, "h": h})
        conn.execute(text("UPDATE audit_log_sequence_counter SET value = 2 WHERE id = 'singleton'"))

    command.upgrade(cfg, LAST_HASH_REVISION)
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT value, last_hash FROM audit_log_sequence_counter WHERE id = 'singleton'"
        )).one() == (2, "b" * 64)

    command.downgrade(cfg, previous)
    with engine.connect() as conn:
        cols = {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'audit_log_sequence_counter' AND table_schema = current_schema()"
        ))}
    assert "last_hash" not in cols
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT last_hash FROM audit_log_sequence_counter WHERE id = 'singleton'"
        )).scalar_one() == "b" * 64


def test_legacy_seal_is_written_under_rls_with_bypass(rls_app):
    """Bestandssiegel (#869) unter echter RLS: die Startpruefung (Operator-
    Bypass) sieht die Altzeilen aller Tenants und schreibt das Siegel ohne
    tenant_id -- ohne Bypass schluege WITH CHECK fehl."""
    from services.audit import LEGACY_SEAL_MARKER, run_startup_audit_chain_check
    from services.tenant_context import operator_bypass

    with rls_app() as s:
        with operator_bypass(s):
            for row_id, tenant in (("L1", "tenant-a"), ("L2", "tenant-b")):
                s.execute(text(
                    "INSERT INTO audit_log (id, user_name, table_name, record_id, action, created_at, tenant_id)"
                    " VALUES (:id, 'Alt', 'clients', 'c', 'UPDATE', '2026-03-01T00:00:00.000Z', :t)"
                ), {"id": row_id, "t": tenant})
            s.commit()
    _alternate(rls_app)
    first = run_startup_audit_chain_check(rls_app, read_scope=operator_bypass)
    second = run_startup_audit_chain_check(rls_app, read_scope=operator_bypass)
    assert first["ok"] and first["legacy"]["seal_ok"] is True and first["legacy"]["seal_count"] == 2
    assert second["ok"]
    with rls_app() as s:
        with operator_bypass(s):
            seals = s.execute(text(
                "SELECT sequence FROM audit_log WHERE field_name = :m"
            ), {"m": LEGACY_SEAL_MARKER}).all()
    assert len(seals) == 1 and seals[0][0] == 7
