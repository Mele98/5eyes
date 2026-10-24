"""Postgres-RLS: Sichtbarkeit globaler Referenzzeilen (``tenant_id IS NULL``).

Befund (Inventur 2026-10, hier live belegt): das RLS-Praedikat
``tenant_id::text = current_setting('app.tenant_id')`` ist fuer NULL-Zeilen
nie wahr. Jede Tenant-Session auf Postgres sah damit das globale
Produktuniversum, die globale CMA (die ``services/jurisdiction/resolve.py``
ausdruecklich mit ``tenant_id IS NULL`` sucht) und die globalen
Eignungsregelwerke nicht.

Soll (gilt ab dieser Datei als Regression-Gate):
- Referenztabellen (``GLOBAL_REFERENCE_TABLES``): globale Zeilen fuer jede
  Session lesbar; schreiben, aendern, loeschen nur per Operator-Bypass.
  Tenant-Zeilen bleiben strikt getrennt.
- Alle anderen Tabellen mit ``tenant_id``: unveraendert strikt, NULL-Zeilen
  bleiben unsichtbar (Kunden-, Benutzer-, Audit-Daten).

Aufbau: vollstaendige Alembic-Kette auf ein frisches Schema, danach
``ensure_postgres_rls_policies()`` wie ``database.init_db()``. Die App
verbindet sich mit einer eigenen, unprivilegierten Rolle (kein Superuser,
kein BYPASSRLS, nicht Owner), sonst waere RLS wirkungslos und der Test
gruen aus dem falschen Grund. Ohne ``POSTGRES_TEST_DATABASE_URL``
uebersprungen; in CI setzt der ``postgres-rls``-Job sie.
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
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
    GLOBAL_REFERENCE_TABLES,
    ensure_postgres_rls_policies,
    tenant_scoped_table_names,
)
from services.tenant_context import (  # noqa: E402
    attach_tenant_context_reset,
    operator_bypass,
    set_tenant_context,
)

# Fachliches Soll, bewusst hier ausgeschrieben statt aus dem Modul gelesen:
# eine stille Erweiterung der Referenzliste um eine Kundendaten-Tabelle
# muss diesen Test rot machen.
EXPECTED_REFERENCE_TABLES = frozenset({
    "capital_market_assumptions",
    "product_eligibility_rule_sets",
    "product_eligibility_rules",
    "products",
})
TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


def _qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


_ENUM_CHECK_RE = re.compile(r"\(?(\w+)\)?::[\w ]+ = ANY \(\(?ARRAY\['([^']*)'")


def _dummy_value(data_type: str, column: str, row_id: str):
    dt = data_type.lower()
    if dt in {"integer", "bigint", "smallint"}:
        return 1
    if dt in {"numeric", "double precision", "real"}:
        return 0
    if dt == "boolean":
        return False
    if dt.startswith("timestamp"):
        return "2026-01-01 00:00:00"
    if dt == "date":
        return "2026-01-01"
    if dt in {"json", "jsonb"}:
        return "{}"
    return f"{column}-{row_id}"


def _seed_row(conn, schema: str, table: str, row_id: str, tenant_id: str | None) -> None:
    """Minimalzeile mit allen Pflichtspalten. FK-Trigger sind per
    ``session_replication_role = replica`` aus -- es geht hier nur um die
    Sichtbarkeit je ``tenant_id``, nicht um referenzielle Vollstaendigkeit."""
    cols = conn.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns"
            " WHERE table_schema = :s AND table_name = :t"
            " AND is_nullable = 'NO' AND column_default IS NULL"
        ),
        {"s": schema, "t": table},
    ).all()
    # Aufzaehlungs-CHECKs (``col = ANY (ARRAY['X', ...])``): ersten erlaubten
    # Wert nehmen, sonst lehnt z.B. audit_log.action den Platzhalter ab.
    allowed: dict[str, str] = {}
    for (definition,) in conn.execute(
        text(
            "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c"
            " JOIN pg_class r ON r.oid = c.conrelid"
            " JOIN pg_namespace n ON n.oid = r.relnamespace"
            " WHERE c.contype = 'c' AND n.nspname = :s AND r.relname = :t"
        ),
        {"s": schema, "t": table},
    ).all():
        match = _ENUM_CHECK_RE.search(definition)
        if match:
            allowed.setdefault(match.group(1), match.group(2))
    values: dict[str, object] = {}
    for name, data_type in cols:
        values[name] = allowed.get(name, _dummy_value(data_type, name, row_id))
    values["id"] = row_id
    values["tenant_id"] = tenant_id
    names = list(values)
    conn.execute(
        text(
            f"INSERT INTO {_qi(table)} ({', '.join(_qi(n) for n in names)})"
            f" VALUES ({', '.join(':' + n for n in names)})"
        ),
        values,
    )


@pytest.fixture(scope="module")
def pg_ctx():
    pytest.importorskip("psycopg")
    assert POSTGRES_URL is not None
    token = uuid.uuid4().hex[:12]
    schema = f"rlsg_{token}"
    role = f"rlsg_app_{token}"
    password = f"pw_{token}"

    admin_engine = create_engine(POSTGRES_URL, future=True)
    with admin_engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
        conn.execute(text(f"CREATE ROLE {_qi(role)} LOGIN PASSWORD {_sql_literal(password)}"))

    separator = "&" if "?" in POSTGRES_URL else "?"
    scoped_url = f"{POSTGRES_URL}{separator}options=-csearch_path%3D{schema}"
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", scoped_url.replace("%", "%%"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))

    scoped_admin = create_engine(scoped_url, future=True)
    app_url = make_url(scoped_url).set(username=role, password=password)
    app_engine = create_engine(
        app_url.render_as_string(hide_password=False), future=True,
        pool_size=1, max_overflow=0,
    )
    attach_tenant_context_reset(app_engine)
    try:
        command.upgrade(cfg, "head")
        with scoped_admin.begin() as conn:
            landed = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables"
                    " WHERE table_schema = :s AND table_name = 'alembic_version'"
                ),
                {"s": schema},
            ).scalar()
            assert landed == 1, "Alembic ist nicht im Test-Schema gelandet"

            live_tenant_tables = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT c.table_name FROM information_schema.columns c"
                        " JOIN information_schema.tables t"
                        "   ON t.table_schema = c.table_schema AND t.table_name = c.table_name"
                        " WHERE c.table_schema = :s AND c.column_name = 'tenant_id'"
                        "   AND t.table_type = 'BASE TABLE'"
                    ),
                    {"s": schema},
                ).all()
            }
            # Wie database.init_db(): Policies fuer alle Tenant-Tabellen.
            ensure_postgres_rls_policies(conn)

            conn.execute(text("SET session_replication_role = replica"))
            nullable = {
                row[0]: row[1] == "YES"
                for row in conn.execute(
                    text(
                        "SELECT table_name, is_nullable FROM information_schema.columns"
                        " WHERE table_schema = :s AND column_name = 'tenant_id'"
                    ),
                    {"s": schema},
                ).all()
            }
            seeded_null: set[str] = set()
            for table in sorted(live_tenant_tables):
                _seed_row(conn, schema, table, f"{table}-a", TENANT_A)
                _seed_row(conn, schema, table, f"{table}-b", TENANT_B)
                if nullable.get(table):
                    _seed_row(conn, schema, table, f"{table}-g", None)
                    seeded_null.add(table)
            conn.execute(text("SET session_replication_role = origin"))

            conn.execute(text(f"GRANT USAGE ON SCHEMA {_qi(schema)} TO {_qi(role)}"))
            conn.execute(text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {_qi(schema)} TO {_qi(role)}"
            ))
            policies = conn.execute(
                text(
                    "SELECT tablename, policyname, cmd FROM pg_policies"
                    " WHERE schemaname = :s ORDER BY tablename, policyname"
                ),
                {"s": schema},
            ).all()

        yield {
            "engine": app_engine,
            "schema": schema,
            "tenant_tables": live_tenant_tables,
            "seeded_null": seeded_null,
            "policies": policies,
        }
    finally:
        app_engine.dispose()
        scoped_admin.dispose()
        with admin_engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
            conn.execute(text(f"DROP OWNED BY {_qi(role)}"))
            conn.execute(text(f"DROP ROLE IF EXISTS {_qi(role)}"))
        admin_engine.dispose()


def _assert_rls_violation(exc: SQLAlchemyError) -> None:
    """RLS-WITH-CHECK-Verletzung per SQLSTATE 42501 (sprachunabhaengig) --
    nicht irgendein FK-/Unique-Fehler, der den Test aus dem falschen Grund
    gruen machen wuerde."""
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
    assert sqlstate == "42501", f"erwartet RLS-Verletzung, erhalten {sqlstate}: {exc}"
    # 42501 umfasst auch "permission denied"; Text EN (CI) bzw. DE (lokal).
    assert "row-level security" in str(exc) or "Zeilenebene" in str(exc), str(exc)


def _session(ctx):
    return sessionmaker(bind=ctx["engine"])()


def _ids(db, table: str) -> set[str]:
    return {row[0] for row in db.execute(text(f"SELECT id FROM {_qi(table)}")).all()}


# --- Inventar --------------------------------------------------------------


def test_inventory_every_live_tenant_table_is_discovered_and_has_a_policy(pg_ctx):
    """Alle Tabellen mit ``tenant_id`` aus der Alembic-Kette == Modell-Inventar,
    und jede hat nach dem Startup-Pfad eine Policy."""
    assert pg_ctx["tenant_tables"] == set(tenant_scoped_table_names())
    covered = {row[0] for row in pg_ctx["policies"]}
    assert pg_ctx["tenant_tables"] <= covered


def test_reference_classification_is_exactly_the_agreed_catalog(pg_ctx):
    assert GLOBAL_REFERENCE_TABLES == EXPECTED_REFERENCE_TABLES
    assert EXPECTED_REFERENCE_TABLES <= pg_ctx["tenant_tables"]
    # Jede Referenztabelle kann ueberhaupt globale Zeilen tragen.
    assert EXPECTED_REFERENCE_TABLES <= pg_ctx["seeded_null"]


def test_policies_are_split_by_command_only_on_reference_tables(pg_ctx):
    by_table: dict[str, set[tuple[str, str]]] = {}
    for table, name, cmd in pg_ctx["policies"]:
        by_table.setdefault(table, set()).add((name, cmd))
    for table in pg_ctx["tenant_tables"]:
        if table in EXPECTED_REFERENCE_TABLES:
            assert by_table[table] == {
                ("tenant_reference_select", "SELECT"),
                ("tenant_reference_insert", "INSERT"),
                ("tenant_reference_update", "UPDATE"),
                ("tenant_reference_delete", "DELETE"),
            }, table
        else:
            assert by_table[table] == {("tenant_isolation", "ALL")}, table


# --- Lesen -----------------------------------------------------------------


@pytest.mark.parametrize("table", sorted(EXPECTED_REFERENCE_TABLES))
def test_tenant_session_sees_global_reference_rows_and_own_but_never_foreign(pg_ctx, table):
    with _session(pg_ctx) as db:
        set_tenant_context(db, TENANT_A)
        assert _ids(db, table) == {f"{table}-a", f"{table}-g"}


@pytest.mark.parametrize("table", sorted(EXPECTED_REFERENCE_TABLES))
def test_unscoped_session_sees_only_global_reference_rows(pg_ctx, table):
    """Super-Admin laeuft ohne Tenant-Kontext (services/auth.py): er sieht die
    globalen Referenzdaten, aber keine Tenant-Zeilen."""
    with _session(pg_ctx) as db:
        assert _ids(db, table) == {f"{table}-g"}


def test_customer_tables_stay_strict_no_null_and_no_foreign_rows(pg_ctx):
    strict = sorted(pg_ctx["tenant_tables"] - EXPECTED_REFERENCE_TABLES)
    assert {"clients", "mandates", "users", "audit_log"} <= set(strict)
    leaks: dict[str, set[str]] = {}
    with _session(pg_ctx) as db:
        set_tenant_context(db, TENANT_A)
        for table in strict:
            seen = _ids(db, table)
            if seen != {f"{table}-a"}:
                leaks[table] = seen
    assert leaks == {}


def test_unscoped_session_sees_no_customer_rows(pg_ctx):
    strict = sorted(pg_ctx["tenant_tables"] - EXPECTED_REFERENCE_TABLES)
    with _session(pg_ctx) as db:
        visible = {table: _ids(db, table) for table in strict}
    assert {t: v for t, v in visible.items() if v} == {}


# --- Schreiben -------------------------------------------------------------


@pytest.mark.parametrize("table", sorted(EXPECTED_REFERENCE_TABLES))
def test_tenant_cannot_update_or_delete_global_rows(pg_ctx, table):
    with _session(pg_ctx) as db:
        set_tenant_context(db, TENANT_A)
        updated = db.execute(
            text(f"UPDATE {_qi(table)} SET tenant_id = :t WHERE id = :id"),
            {"t": TENANT_A, "id": f"{table}-g"},
        ).rowcount
        deleted = db.execute(
            text(f"DELETE FROM {_qi(table)} WHERE id IN (:g, :b)"),
            {"g": f"{table}-g", "b": f"{table}-b"},
        ).rowcount
        db.rollback()
    assert (updated, deleted) == (0, 0)
    with _session(pg_ctx) as db, operator_bypass(db):
        assert {f"{table}-g", f"{table}-b"} <= _ids(db, table)


@pytest.mark.parametrize("table", sorted(EXPECTED_REFERENCE_TABLES))
@pytest.mark.parametrize("target_tenant", [None, TENANT_B])
def test_tenant_cannot_insert_global_or_foreign_rows(pg_ctx, table, target_tenant):
    with _session(pg_ctx) as db:
        set_tenant_context(db, TENANT_A)
        # Kopie der eigenen Zeile, nur mit NULL- bzw. fremdem Tenant.
        with pytest.raises(SQLAlchemyError) as excinfo:
            db.execute(
                text(
                    f"INSERT INTO {_qi(table)} SELECT (x).* FROM ("
                    f"  SELECT jsonb_populate_record(NULL::{_qi(table)},"
                    f"    to_jsonb(r) || jsonb_build_object('id', CAST(:id AS text), 'tenant_id', CAST(:t AS text))) AS x"
                    f"  FROM {_qi(table)} r WHERE r.id = :own"
                    f") s"
                ),
                {"id": f"{table}-evil", "t": target_tenant, "own": f"{table}-a"},
            )
        db.rollback()
    _assert_rls_violation(excinfo.value)


@pytest.mark.parametrize("table", sorted(EXPECTED_REFERENCE_TABLES))
def test_tenant_cannot_turn_own_row_into_global_row(pg_ctx, table):
    with _session(pg_ctx) as db:
        set_tenant_context(db, TENANT_A)
        with pytest.raises(SQLAlchemyError) as excinfo:
            db.execute(
                text(f"UPDATE {_qi(table)} SET tenant_id = NULL WHERE id = :id"),
                {"id": f"{table}-a"},
            )
        db.rollback()
    _assert_rls_violation(excinfo.value)


@pytest.mark.parametrize("table", sorted(EXPECTED_REFERENCE_TABLES))
def test_tenant_can_still_write_own_reference_rows(pg_ctx, table):
    with _session(pg_ctx) as db:
        set_tenant_context(db, TENANT_A)
        updated = db.execute(
            text(f"UPDATE {_qi(table)} SET tenant_id = tenant_id WHERE id = :id"),
            {"id": f"{table}-a"},
        ).rowcount
        db.rollback()
    assert updated == 1


@pytest.mark.parametrize("table", sorted(EXPECTED_REFERENCE_TABLES))
def test_operator_bypass_can_write_global_rows(pg_ctx, table):
    with _session(pg_ctx) as db:
        with operator_bypass(db):
            updated = db.execute(
                text(f"UPDATE {_qi(table)} SET tenant_id = NULL WHERE id = :id"),
                {"id": f"{table}-g"},
            ).rowcount
        db.rollback()
    assert updated == 1


# --- Migration -------------------------------------------------------------

MIGRATION_REVISION = "e2b7c4f9a1d6"
MIGRATION_DOWN_REVISION = "c4d9e2a7f1b6"


@pytest.fixture()
def migration_schema():
    pytest.importorskip("psycopg")
    assert POSTGRES_URL is not None
    schema = f"rlsm_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(POSTGRES_URL, future=True)
    with admin_engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    separator = "&" if "?" in POSTGRES_URL else "?"
    scoped_url = f"{POSTGRES_URL}{separator}options=-csearch_path%3D{schema}"
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", scoped_url.replace("%", "%%"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    scoped = create_engine(scoped_url, future=True)
    try:
        yield {"cfg": cfg, "engine": scoped, "schema": schema}
    finally:
        scoped.dispose()
        with admin_engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
        admin_engine.dispose()


def _reference_policies(engine, schema: str) -> dict[tuple[str, str], tuple[str, str, str]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT tablename, policyname, cmd, coalesce(qual, ''), coalesce(with_check, '')"
                " FROM pg_policies WHERE schemaname = :s AND tablename = ANY(:t)"
            ),
            {"s": schema, "t": sorted(EXPECTED_REFERENCE_TABLES)},
        ).all()
    return {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows}


def test_migration_upgrade_downgrade_is_idempotent_and_matches_runtime(migration_schema):
    cfg, engine, schema = (
        migration_schema["cfg"], migration_schema["engine"], migration_schema["schema"],
    )
    # Kettenbasiert statt "ist Head": spaetere Revisionen duerfen folgen.
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert MIGRATION_REVISION in chain
    assert script.get_revision(MIGRATION_REVISION).down_revision == MIGRATION_DOWN_REVISION

    command.upgrade(cfg, MIGRATION_REVISION)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == MIGRATION_REVISION
    after_migration = _reference_policies(engine, schema)
    assert {name for (_t, name) in after_migration} == {
        "tenant_reference_select", "tenant_reference_insert",
        "tenant_reference_update", "tenant_reference_delete",
    }
    assert len(after_migration) == 4 * len(EXPECTED_REFERENCE_TABLES)

    # Startup-Pfad (init_db) erzeugt exakt dieselben Policies.
    with engine.begin() as conn:
        ensure_postgres_rls_policies(conn, table_names=sorted(EXPECTED_REFERENCE_TABLES))
    assert _reference_policies(engine, schema) == after_migration

    command.downgrade(cfg, MIGRATION_DOWN_REVISION)
    downgraded = _reference_policies(engine, schema)
    assert set(downgraded) == {(t, "tenant_isolation") for t in EXPECTED_REFERENCE_TABLES}
    assert all(cmd == "ALL" and "IS NULL" not in qual for cmd, qual, _ in downgraded.values())

    command.upgrade(cfg, MIGRATION_REVISION)
    assert _reference_policies(engine, schema) == after_migration
