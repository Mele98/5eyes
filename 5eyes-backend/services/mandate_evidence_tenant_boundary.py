"""Direct tenant binding for append-only mandate evidence tables (PG-002).

Red-team review 2026-10-28, finding 6: ``depot_snapshots`` and the three
on-site signature tables (``onsite_signature_events``,
``onsite_signature_challenges``, ``onsite_signature_evidence``) carried only
``mandate_id``; in the tenant inventory they were ``tenant_derived`` and thus
outside the PostgreSQL RLS plan (``services.postgres_rls`` only discovers
tables with a physical ``tenant_id``).

Same pattern as ``services/risk_evidence_tenant_boundary.py``:

* ``tenant_id`` is derived from ``mandates.tenant_id`` of the row's mandate.
  The application writes it explicitly; the database re-derives it and
  rejects a conflicting value. PostgreSQL: under RLS the mandate lookup only
  sees the session's tenant, so a foreign mandate yields no tenant and the
  insert fails; a mandate without tenant is rejected as well.
* ``client_id`` must be the mandate's client.
* Legacy rows are backfilled deterministically from their mandate. Rows whose
  mandate no longer exists (purge keeps evidence rows) stay
  ``tenant_id IS NULL`` -- quarantined: under strict RLS no tenant sees them,
  they are never assigned to a guessed tenant.

All four tables are append-only (UPDATE/DELETE triggers); the backfill lifts
the UPDATE guard only around its own statement and restores it afterwards.
The tenant id is NOT part of any evidence hash (hashes stay unchanged).

The PostgreSQL DDL lives frozen in Alembic ``b8d4f2a6c9e1``; this module holds
the SQLite runtime side (create_all hook + runtime patch for desktop DBs).
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

MANDATE_EVIDENCE_TENANT_TABLES: tuple[str, ...] = (
    "depot_snapshots",
    "onsite_signature_events",
    "onsite_signature_challenges",
    "onsite_signature_evidence",
)
TENANT_ERROR = "MANDATE_EVIDENCE_TENANT_MISMATCH"
POSTGRES_FUNCTION_NAME = "mandate_evidence_tenant_from_mandate"


def guard_trigger_name(table: str) -> str:
    return f"trg_{table}_tenant_guard"


def tenant_index_name(table: str) -> str:
    return f"ix_{table}_tenant_id"


def sqlite_guard_trigger(table: str) -> str:
    return (
        f"CREATE TRIGGER IF NOT EXISTS {guard_trigger_name(table)} "
        f"BEFORE INSERT ON {table} FOR EACH ROW "
        f"WHEN NEW.tenant_id IS NOT (SELECT m.tenant_id FROM mandates m WHERE m.id = NEW.mandate_id) "
        f"OR EXISTS (SELECT 1 FROM mandates m WHERE m.id = NEW.mandate_id "
        f"AND m.client_id IS NOT NEW.client_id) "
        f"BEGIN SELECT RAISE(ABORT, '{TENANT_ERROR}'); END"
    )


def sqlite_no_update_trigger(table: str) -> str:
    """Append-only UPDATE guard, textually identical to the original DDL."""
    return (
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update "
        f"BEFORE UPDATE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END"
    )


def backfill_tenant_sql(table: str) -> str:
    return (
        f"UPDATE {table} SET tenant_id = (SELECT m.tenant_id FROM mandates m "
        f"WHERE m.id = {table}.mandate_id) WHERE tenant_id IS NULL"
    )


def quarantined_count_sql(table: str) -> str:
    return f"SELECT count(*) FROM {table} WHERE tenant_id IS NULL"


def _sqlite_columns(connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})")).all()}


def _sqlite_tables(connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).all()
    }


def _ready_tables(connection) -> list[str]:
    """Evidence tables that exist and carry ``tenant_id``, provided
    ``mandates.tenant_id`` exists (a trigger naming a missing column would
    break later ``ALTER TABLE`` statements)."""
    tables = _sqlite_tables(connection)
    if "mandates" not in tables or "tenant_id" not in _sqlite_columns(connection, "mandates"):
        return []
    return [
        table for table in MANDATE_EVIDENCE_TENANT_TABLES
        if table in tables and "tenant_id" in _sqlite_columns(connection, table)
    ]


def create_sqlite_guards_after_metadata_create(_metadata, connection, **_kw) -> None:
    """Metadata-level ``after_create`` hook (SQLite): runs after ALL tables of
    ``create_all`` exist (the evidence tables have no FK to ``mandates``)."""
    if connection.dialect.name != "sqlite":
        return
    for table in _ready_tables(connection):
        connection.execute(text(sqlite_guard_trigger(table)))


def ensure_sqlite_mandate_evidence_tenant_boundary(engine) -> dict[str, int]:
    """SQLite runtime patch (existing desktop DBs): backfill + guard triggers.

    Idempotent. Returns the number of quarantined rows per table (no
    derivable tenant, e.g. purged mandate); they are logged, never guessed.
    """
    quarantined: dict[str, int] = {}
    with engine.begin() as conn:
        for table in _ready_tables(conn):
            pending = conn.execute(text(
                f"SELECT count(*) FROM {table} t WHERE t.tenant_id IS NULL AND EXISTS ("
                f"SELECT 1 FROM mandates m WHERE m.id = t.mandate_id AND m.tenant_id IS NOT NULL)"
            )).scalar()
            if pending:
                conn.execute(text(f"DROP TRIGGER IF EXISTS trg_{table}_no_update"))
                try:
                    conn.execute(text(backfill_tenant_sql(table)))
                finally:
                    conn.execute(text(sqlite_no_update_trigger(table)))
            conn.execute(text(sqlite_guard_trigger(table)))
            quarantined[table] = int(conn.execute(text(quarantined_count_sql(table))).scalar() or 0)
    if any(quarantined.values()):
        logger.warning(
            "PG-002: Mandats-Evidenz ohne ableitbaren Mandanten bleibt quarantaeniert "
            "(tenant_id NULL, unter RLS fuer keinen Mandanten sichtbar): %s",
            quarantined,
        )
    return quarantined
