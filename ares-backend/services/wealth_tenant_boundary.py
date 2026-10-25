"""Database tenant boundary for ``wealth_positions`` / ``wealth_inflows`` (PG-002).

Closure review of PR #666: the router checks a Vorsorge link against the
client, but the database itself accepted any ``linked_position_id`` -- a raw,
import, worker or ORM write below the router could link an inflow of tenant A
to a position of tenant B. Both tables also lacked a local ``tenant_id`` and
were therefore invisible to the PostgreSQL RLS plan
(``services/postgres_rls.tenant_scoped_table_names``).

This module holds the dialect-specific DDL for the database-side invariants
(pure SQL, no model imports, so ``models/wealth.py`` and the migration can use
it):

* ``tenant_id`` is derived server-side from ``clients.tenant_id`` of the row's
  client -- never trusted from the request. PostgreSQL: a BEFORE trigger sets
  it and rejects a conflicting explicit value; under RLS the client lookup
  only sees the session's tenant, so a foreign client yields NULL and the
  write fails (NOT NULL / RLS WITH CHECK). SQLite (single-tenant desktop): a
  BEFORE trigger rejects a conflicting value, an AFTER INSERT trigger fills a
  missing one; the ORM derives it as well (``derive_tenant_id``).
* ``wealth_inflows.linked_position_id`` must point to a NOT soft-deleted
  position OF THE SAME CLIENT (hence the same tenant). Checked whenever the
  link or the inflow's client is written (an unchanged legacy link is left
  alone). PostgreSQL additionally gets the composite foreign key
  ``(linked_position_id, client_id) -> wealth_positions(id, client_id)``
  (declared on the ORM model and created by the migration).
* A linked position cannot be moved to another client.

Violations raise an integrity error on both dialects
(``sqlalchemy.exc.IntegrityError``).
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

WEALTH_TENANT_TABLES: tuple[str, ...] = ("wealth_positions", "wealth_inflows")
LINK_ERROR = "WEALTH_INFLOW_LINK_OUTSIDE_CLIENT"
TENANT_ERROR = "WEALTH_TENANT_MISMATCH"
POSITION_MOVE_ERROR = "WEALTH_POSITION_LINKED_CLIENT_CHANGE"
COMPOSITE_FK_NAME = "fk_wealth_inflows_linked_position_client"
POSITION_ID_CLIENT_UNIQUE = "uq_wealth_positions_id_client"

_LINK_TARGET_MISSING = (
    "NOT EXISTS (SELECT 1 FROM wealth_positions p WHERE p.id = NEW.linked_position_id "
    "AND p.client_id = NEW.client_id AND p.deleted_at IS NULL)"
)


def _sqlite_tenant_triggers(table: str) -> tuple[str, ...]:
    mismatch = (
        "NEW.tenant_id IS NOT NULL AND NEW.tenant_id IS NOT "
        "(SELECT c.tenant_id FROM clients c WHERE c.id = NEW.client_id)"
    )
    return (
        f"""CREATE TRIGGER IF NOT EXISTS trg_{table}_tenant_guard_insert
BEFORE INSERT ON {table} FOR EACH ROW WHEN {mismatch}
BEGIN SELECT RAISE(ABORT, '{TENANT_ERROR}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS trg_{table}_tenant_guard_update
BEFORE UPDATE OF tenant_id, client_id ON {table} FOR EACH ROW WHEN {mismatch}
BEGIN SELECT RAISE(ABORT, '{TENANT_ERROR}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS trg_{table}_tenant_fill
AFTER INSERT ON {table} FOR EACH ROW WHEN NEW.tenant_id IS NULL
BEGIN UPDATE {table} SET tenant_id = (SELECT c.tenant_id FROM clients c WHERE c.id = NEW.client_id)
WHERE id = NEW.id; END""",
    )


WEALTH_INFLOW_SQLITE_TRIGGERS: tuple[str, ...] = (
    f"""CREATE TRIGGER IF NOT EXISTS trg_wealth_inflows_link_guard_insert
BEFORE INSERT ON wealth_inflows FOR EACH ROW
WHEN NEW.linked_position_id IS NOT NULL AND {_LINK_TARGET_MISSING}
BEGIN SELECT RAISE(ABORT, '{LINK_ERROR}'); END""",
    f"""CREATE TRIGGER IF NOT EXISTS trg_wealth_inflows_link_guard_update
BEFORE UPDATE OF linked_position_id, client_id ON wealth_inflows FOR EACH ROW
WHEN NEW.linked_position_id IS NOT NULL
 AND (NEW.linked_position_id IS NOT OLD.linked_position_id OR NEW.client_id IS NOT OLD.client_id)
 AND {_LINK_TARGET_MISSING}
BEGIN SELECT RAISE(ABORT, '{LINK_ERROR}'); END""",
) + _sqlite_tenant_triggers("wealth_inflows")

WEALTH_POSITION_SQLITE_TRIGGERS: tuple[str, ...] = (
    f"""CREATE TRIGGER IF NOT EXISTS trg_wealth_positions_linked_client_guard
BEFORE UPDATE OF client_id ON wealth_positions FOR EACH ROW
WHEN NEW.client_id IS NOT OLD.client_id AND EXISTS (
  SELECT 1 FROM wealth_inflows i WHERE i.linked_position_id = OLD.id AND i.client_id IS NOT NEW.client_id)
BEGIN SELECT RAISE(ABORT, '{POSITION_MOVE_ERROR}'); END""",
) + _sqlite_tenant_triggers("wealth_positions")


POSTGRES_FUNCTIONS: tuple[str, ...] = (
    f"""CREATE OR REPLACE FUNCTION wealth_row_tenant_from_client() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text;
BEGIN
  SELECT c.tenant_id INTO derived FROM clients c WHERE c.id = NEW.client_id;
  IF NEW.tenant_id IS NOT NULL AND NEW.tenant_id IS DISTINCT FROM derived THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  NEW.tenant_id := derived;
  RETURN NEW;
END $$""",
    f"""CREATE OR REPLACE FUNCTION wealth_inflow_link_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.linked_position_id IS NULL THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' AND NEW.linked_position_id IS NOT DISTINCT FROM OLD.linked_position_id
     AND NEW.client_id IS NOT DISTINCT FROM OLD.client_id THEN
    RETURN NEW;
  END IF;
  PERFORM 1 FROM wealth_positions p WHERE p.id = NEW.linked_position_id
    AND p.client_id = NEW.client_id AND p.deleted_at IS NULL;
  IF NOT FOUND THEN
    RAISE EXCEPTION '{LINK_ERROR}' USING ERRCODE = '23503';
  END IF;
  RETURN NEW;
END $$""",
    f"""CREATE OR REPLACE FUNCTION wealth_position_linked_client_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.client_id IS DISTINCT FROM OLD.client_id AND EXISTS (
     SELECT 1 FROM wealth_inflows i WHERE i.linked_position_id = OLD.id
       AND i.client_id IS DISTINCT FROM NEW.client_id) THEN
    RAISE EXCEPTION '{POSITION_MOVE_ERROR}' USING ERRCODE = '23503';
  END IF;
  RETURN NEW;
END $$""",
)


def postgres_triggers(table: str) -> tuple[str, ...]:
    statements = [
        f"DROP TRIGGER IF EXISTS trg_{table}_tenant_from_client ON {table}",
        f"""CREATE TRIGGER trg_{table}_tenant_from_client
BEFORE INSERT OR UPDATE OF tenant_id, client_id ON {table}
FOR EACH ROW EXECUTE FUNCTION wealth_row_tenant_from_client()""",
    ]
    if table == "wealth_inflows":
        statements += [
            "DROP TRIGGER IF EXISTS trg_wealth_inflows_link_guard ON wealth_inflows",
            """CREATE TRIGGER trg_wealth_inflows_link_guard
BEFORE INSERT OR UPDATE OF linked_position_id, client_id ON wealth_inflows
FOR EACH ROW EXECUTE FUNCTION wealth_inflow_link_guard()""",
        ]
    else:
        statements += [
            "DROP TRIGGER IF EXISTS trg_wealth_positions_linked_client_guard ON wealth_positions",
            """CREATE TRIGGER trg_wealth_positions_linked_client_guard
BEFORE UPDATE OF client_id ON wealth_positions
FOR EACH ROW EXECUTE FUNCTION wealth_position_linked_client_guard()""",
        ]
    return tuple(statements)


def sqlite_triggers(table: str) -> tuple[str, ...]:
    return WEALTH_INFLOW_SQLITE_TRIGGERS if table == "wealth_inflows" else WEALTH_POSITION_SQLITE_TRIGGERS


def _sqlite_columns(connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})")).all()}


def create_sqlite_triggers_after_create(target, connection, **_kw) -> None:
    """``after_create`` hook (SQLite): install the triggers whose columns exist.

    A database bootstrapped from the reference SQL schema can lack
    ``clients.tenant_id`` until the runtime patch adds it; a trigger naming a
    missing column would break every later ``ALTER TABLE``. Tenant triggers
    are then installed by ``ensure_sqlite_wealth_tenant_boundary``.
    """
    if connection.dialect.name != "sqlite":
        return
    tenant_ready = "tenant_id" in _sqlite_columns(connection, "clients")
    for ddl in sqlite_triggers(target.name):
        if "tenant" in ddl.split("ON", 1)[0] and not tenant_ready:
            continue
        connection.execute(text(ddl))


# --- data checks (migration / runtime patch) ---------------------------------

INVALID_LINKS_SQL = """
SELECT i.id FROM wealth_inflows i
LEFT JOIN wealth_positions p ON p.id = i.linked_position_id
WHERE i.linked_position_id IS NOT NULL
  AND (p.id IS NULL OR p.client_id IS DISTINCT FROM i.client_id)
ORDER BY i.id
"""
INVALID_LINKS_SQL_SQLITE = INVALID_LINKS_SQL.replace("IS DISTINCT FROM", "IS NOT")


def backfill_tenant_sql(table: str) -> str:
    return (
        f"UPDATE {table} SET tenant_id = (SELECT c.tenant_id FROM clients c "
        f"WHERE c.id = {table}.client_id) WHERE tenant_id IS NULL"
    )


def find_invalid_inflow_links(conn, *, dialect: str) -> list[str]:
    """Inflows whose link is dangling or points to another client's position."""
    sql = INVALID_LINKS_SQL_SQLITE if dialect == "sqlite" else INVALID_LINKS_SQL
    return [str(row[0]) for row in conn.execute(text(sql)).all()]


def ensure_sqlite_wealth_tenant_boundary(engine) -> list[str]:
    """SQLite runtime patch (existing desktop DBs): backfill + triggers.

    Returns the inflow ids with an invalid legacy link. They are NOT changed
    (no silent re-assignment); they are logged so an operator can repair them.
    The triggers stop every new invalid write.
    """
    with engine.begin() as conn:
        tables = {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).all()
        }
        if not set(WEALTH_TENANT_TABLES) <= tables or "clients" not in tables:
            return []
        for table in (*WEALTH_TENANT_TABLES, "clients"):
            columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).all()}
            if "tenant_id" not in columns:
                return []
        for table in WEALTH_TENANT_TABLES:
            conn.execute(text(backfill_tenant_sql(table)))
            for ddl in sqlite_triggers(table):
                conn.execute(text(ddl))
        invalid = find_invalid_inflow_links(conn, dialect="sqlite")
    if invalid:
        logger.error(
            "PG-002: %d Vorsorge-Zufluss-Verknuepfung(en) zeigen auf keine Position "
            "desselben Kunden (Inflow-IDs: %s). Neue Writes sind gesperrt; Altbestand "
            "manuell bereinigen.",
            len(invalid),
            ", ".join(invalid[:20]),
        )
    return invalid


def derive_tenant_id(connection, client_id) -> str | None:
    """ORM-side derivation: the tenant of the row's client (server truth)."""
    if not client_id:
        return None
    return connection.execute(
        text("SELECT tenant_id FROM clients WHERE id = :client_id"), {"client_id": client_id}
    ).scalar()
