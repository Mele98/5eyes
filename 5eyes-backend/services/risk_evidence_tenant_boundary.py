"""Database tenant boundary for the append-only risk evidence tables (PG-002).

Closure review of PR #662: ``risk_override_decisions`` and
``risk_profile_signoffs`` carry mandate, client, assessment, effective risk
profile, reasons/notes and actors, but had no ``tenant_id``. The PostgreSQL
RLS plan (``services/postgres_rls.tenant_scoped_table_names``) only discovers
tables with that column, so both were outside RLS; append-only stops UPDATE
and DELETE, not a cross-tenant SELECT or INSERT.

This module holds the dialect-specific DDL (pure SQL, no model imports, so
``models/profiling.py``, ``database.py`` and the migration can share it):

* ``tenant_id`` is derived from ``mandates.tenant_id`` of the row's mandate
  -- the application writes it explicitly (it is part of the V2 row hash),
  the database re-derives and rejects any conflicting value. PostgreSQL:
  under RLS the mandate lookup only sees the session's tenant, so a foreign
  mandate yields no tenant and the insert fails; a mandate without tenant
  is rejected as well (non-empty tenant).
* The combination is checked on insert: client must be the mandate's client,
  the assessment (when present) must belong to the same mandate.
* Legacy rows are backfilled deterministically from their mandate. Rows whose
  mandate no longer exists (demo/foundation purge keeps evidence rows) stay
  ``tenant_id IS NULL`` -- quarantined: under strict RLS no tenant sees them,
  they are never assigned to a guessed tenant.

Both tables are append-only (UPDATE/DELETE triggers); the backfill disables
the UPDATE guard only for its own statement and restores it afterwards.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

RISK_EVIDENCE_TENANT_TABLES: tuple[str, ...] = ("risk_override_decisions", "risk_profile_signoffs")
TENANT_ERROR = "RISK_EVIDENCE_TENANT_MISMATCH"
POSTGRES_FUNCTION_NAME = "risk_evidence_tenant_from_mandate"


def guard_trigger_name(table: str) -> str:
    return f"trg_{table}_tenant_guard"


def _sqlite_guard(table: str) -> str:
    return f"""CREATE TRIGGER IF NOT EXISTS {guard_trigger_name(table)}
BEFORE INSERT ON {table} FOR EACH ROW
WHEN NEW.tenant_id IS NOT (SELECT m.tenant_id FROM mandates m WHERE m.id = NEW.mandate_id)
  OR (NEW.client_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM mandates m WHERE m.id = NEW.mandate_id AND m.client_id IS NOT NEW.client_id))
  OR EXISTS (
        SELECT 1 FROM risk_assessments a WHERE a.id = NEW.assessment_id AND a.mandate_id IS NOT NEW.mandate_id)
BEGIN SELECT RAISE(ABORT, '{TENANT_ERROR}'); END"""


def sqlite_guard_triggers(table: str) -> tuple[str, ...]:
    return (_sqlite_guard(table),)


POSTGRES_FUNCTION = f"""CREATE OR REPLACE FUNCTION {POSTGRES_FUNCTION_NAME}() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text; mandate_client text; assessment_mandate text;
BEGIN
  SELECT m.tenant_id, m.client_id INTO derived, mandate_client FROM mandates m WHERE m.id = NEW.mandate_id;
  IF derived IS NULL THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  IF NEW.tenant_id IS NOT NULL AND NEW.tenant_id IS DISTINCT FROM derived THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  IF NEW.client_id IS NOT NULL AND NEW.client_id IS DISTINCT FROM mandate_client THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  SELECT a.mandate_id INTO assessment_mandate FROM risk_assessments a WHERE a.id = NEW.assessment_id;
  IF assessment_mandate IS NOT NULL AND assessment_mandate IS DISTINCT FROM NEW.mandate_id THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  NEW.tenant_id := derived;
  RETURN NEW;
END $$"""


def postgres_triggers(table: str) -> tuple[str, ...]:
    name = guard_trigger_name(table)
    return (
        f"DROP TRIGGER IF EXISTS {name} ON {table}",
        f"""CREATE TRIGGER {name}
BEFORE INSERT ON {table}
FOR EACH ROW EXECUTE FUNCTION {POSTGRES_FUNCTION_NAME}()""",
    )


def backfill_tenant_sql(table: str) -> str:
    return (
        f"UPDATE {table} SET tenant_id = (SELECT m.tenant_id FROM mandates m "
        f"WHERE m.id = {table}.mandate_id) WHERE tenant_id IS NULL"
    )


def quarantined_count_sql(table: str) -> str:
    return f"SELECT count(*) FROM {table} WHERE tenant_id IS NULL"


# Append-only UPDATE guards installed by the original migrations / database.py.
SQLITE_NO_UPDATE_TRIGGERS: dict[str, str] = {
    table: (
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update "
        f"BEFORE UPDATE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END"
    )
    for table in RISK_EVIDENCE_TENANT_TABLES
}
POSTGRES_IMMUTABLE_TRIGGERS: dict[str, str] = {
    table: f"trg_{table}_immutable" for table in RISK_EVIDENCE_TENANT_TABLES
}


def _sqlite_columns(connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})")).all()}


def _sqlite_tables(connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).all()
    }


def create_sqlite_guards_after_metadata_create(_metadata, connection, **_kw) -> None:
    """Metadata-level ``after_create`` hook (SQLite): runs after ALL tables of
    ``create_all`` exist (the evidence tables have no FK to ``mandates``, so a
    table-level hook could fire before ``mandates`` is created).

    A database bootstrapped from the reference SQL schema can lack
    ``mandates.tenant_id`` until the runtime patch adds it; a trigger naming a
    missing column would break later ``ALTER TABLE`` statements. The guard is
    then installed by ``ensure_sqlite_risk_evidence_tenant_boundary``.
    """
    if connection.dialect.name != "sqlite":
        return
    tables = _sqlite_tables(connection)
    if not {"mandates", "risk_assessments", *RISK_EVIDENCE_TENANT_TABLES} <= tables:
        return
    if "tenant_id" not in _sqlite_columns(connection, "mandates"):
        return
    for table in RISK_EVIDENCE_TENANT_TABLES:
        if "tenant_id" not in _sqlite_columns(connection, table):
            continue
        for ddl in sqlite_guard_triggers(table):
            connection.execute(text(ddl))


def sqlite_backfill(conn, table: str) -> None:
    """Backfill legacy rows; the UPDATE guard is lifted only around it."""
    conn.execute(text(f"DROP TRIGGER IF EXISTS trg_{table}_no_update"))
    try:
        conn.execute(text(backfill_tenant_sql(table)))
    finally:
        conn.execute(text(SQLITE_NO_UPDATE_TRIGGERS[table]))


def ensure_sqlite_risk_evidence_tenant_boundary(engine) -> dict[str, int]:
    """SQLite runtime patch (existing desktop DBs): backfill + guard triggers.

    Returns the number of quarantined rows per table (no derivable tenant,
    e.g. purged mandate). They are not changed; they are logged.
    """
    quarantined: dict[str, int] = {}
    with engine.begin() as conn:
        tables = _sqlite_tables(conn)
        if not set(RISK_EVIDENCE_TENANT_TABLES) <= tables or not {"mandates", "risk_assessments"} <= tables:
            return {}
        if "tenant_id" not in _sqlite_columns(conn, "mandates"):
            return {}
        for table in RISK_EVIDENCE_TENANT_TABLES:
            if "tenant_id" not in _sqlite_columns(conn, table):
                return {}
        for table in RISK_EVIDENCE_TENANT_TABLES:
            pending = conn.execute(text(
                f"SELECT count(*) FROM {table} t WHERE t.tenant_id IS NULL AND EXISTS ("
                f"SELECT 1 FROM mandates m WHERE m.id = t.mandate_id AND m.tenant_id IS NOT NULL)"
            )).scalar()
            if pending:
                sqlite_backfill(conn, table)
            for ddl in sqlite_guard_triggers(table):
                conn.execute(text(ddl))
            quarantined[table] = int(conn.execute(text(quarantined_count_sql(table))).scalar() or 0)
    if any(quarantined.values()):
        logger.warning(
            "PG-002: Risiko-Evidence ohne ableitbaren Mandanten bleibt quarantaeniert "
            "(tenant_id NULL, unter RLS fuer keinen Mandanten sichtbar): %s",
            quarantined,
        )
    return quarantined
