"""ELIG-OVERRIDE-APPEND-ONLY-001 -- database-side append-only guarantee for
``product_eligibility_overrides``.

The capture workflow (services/product_eligibility_override.py) only ever
INSERTs: a request row, then a separate approval row. No status transition
updates a row, so UPDATE and DELETE are rejected without exception by
triggers on SQLite and PostgreSQL.

Like the other append-only evidence tables (risk_override_decisions,
goal_revision_decisions, audit_log) the table carries NO hard foreign key to
the recommendation run: the demo purge (services/foundation_purge.py) and
the draft-run cleanup (services/recommendation_run_cleanup.py) hard-delete
runs, and the evidence rows must neither block that nor be deleted with it
(Purge-fest). The run binding stays verifiable through the evidence hash.

Pure SQL, no model imports, so ``models/product_eligibility.py``,
``database.py`` (runtime patch for existing desktop databases) and the
Alembic migration ``f4b8d2a6c1e7`` share the same DDL.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

TABLE = "product_eligibility_overrides"
RUN_PRODUCT_INDEX = "ix_product_eligibility_overrides_run_product"
TENANT_INDEX = "ix_product_eligibility_overrides_tenant_id"
IMMUTABLE_MESSAGE = "product_eligibility_overrides is immutable"

# Column order = ORM order (tests/test_elig_override_followups.py pins it).
OVERRIDE_COLUMNS: dict[str, str] = {
    "id": "VARCHAR NOT NULL PRIMARY KEY",
    "snapshot_id": "VARCHAR REFERENCES product_eligibility_snapshots(id)",
    "rule_id": "VARCHAR REFERENCES product_eligibility_rules(id)",
    "product_id": "VARCHAR NOT NULL REFERENCES products(id)",
    "recommendation_run_id": "VARCHAR NOT NULL",
    "original_decision": "VARCHAR NOT NULL",
    "overridden_dimension": "VARCHAR NOT NULL",
    "reason_code": "VARCHAR NOT NULL",
    "reason_text": "VARCHAR",
    "requested_by": "VARCHAR NOT NULL",
    "approved_by": "VARCHAR NOT NULL",
    "client_acknowledgement_id": "VARCHAR",
    "warning_delivery_id": "VARCHAR",
    "valid_from": "VARCHAR NOT NULL",
    "expires_at": "VARCHAR NOT NULL",
    "policy_basis": "VARCHAR",
    "approval_mode": "VARCHAR",
    "evidence_hash": "VARCHAR NOT NULL",
    "created_at": "VARCHAR NOT NULL",
    "updated_at": "VARCHAR NOT NULL",
    # PG-002: Mandant direkt (Guard/Backfill: services/mandate_evidence_tenant_boundary.py).
    "tenant_id": "VARCHAR",
}

SQLITE_TRIGGERS: tuple[str, ...] = (
    f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_no_update "
    f"BEFORE UPDATE ON {TABLE} FOR EACH ROW "
    f"BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MESSAGE}'); END",
    f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_no_delete "
    f"BEFORE DELETE ON {TABLE} FOR EACH ROW "
    f"BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MESSAGE}'); END",
)
SQLITE_TRIGGER_NAMES: tuple[str, ...] = (f"trg_{TABLE}_no_update", f"trg_{TABLE}_no_delete")

POSTGRES_FUNCTION_NAME = f"{TABLE}_immutable"
POSTGRES_TRIGGER_NAME = f"trg_{TABLE}_immutable"
POSTGRES_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {POSTGRES_FUNCTION_NAME}()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '{IMMUTABLE_MESSAGE}';
END;
$$ LANGUAGE plpgsql
"""
POSTGRES_TRIGGER = f"""
CREATE TRIGGER {POSTGRES_TRIGGER_NAME}
BEFORE UPDATE OR DELETE ON {TABLE}
FOR EACH ROW EXECUTE FUNCTION {POSTGRES_FUNCTION_NAME}()
"""
# Default name PostgreSQL gave the inline FK of migration a3f7c1e9b542.
POSTGRES_RUN_FK_NAME = f"{TABLE}_recommendation_run_id_fkey"


# PG-002 column added by Alembic d6a2c8e4f1b7 -- the historical revision
# f4b8d2a6c1e7 calls this module with ``with_tenant=False`` and keeps its shape.
TENANT_COLUMN = "tenant_id"


def _columns(with_tenant: bool) -> dict[str, str]:
    return {c: ddl for c, ddl in OVERRIDE_COLUMNS.items() if with_tenant or c != TENANT_COLUMN}


def _create_table_sql(name: str, with_tenant: bool = True) -> str:
    columns = ",\n    ".join(f"{column} {ddl}" for column, ddl in _columns(with_tenant).items())
    return f"CREATE TABLE {name} (\n    {columns}\n)"


def _ensure(conn: Connection, with_tenant: bool = True) -> bool:
    exists = conn.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :t"
    ), {"t": TABLE}).first()
    if exists is None:
        return False
    columns = [row[1] for row in conn.execute(text(f"PRAGMA table_info({TABLE})")).all()]
    run_fk = [row for row in conn.execute(text(f"PRAGMA foreign_key_list({TABLE})")).all()
              if row[3] == "recommendation_run_id"]
    changed = False
    if run_fk:
        # SQLite cannot drop a foreign key: rebuild the table (documented
        # 12-step procedure, no table references this one). DROP TABLE runs
        # no DELETE triggers.
        for name in SQLITE_TRIGGER_NAMES:
            conn.execute(text(f"DROP TRIGGER IF EXISTS {name}"))
        rebuild = f"{TABLE}__append_only"
        conn.execute(text(f"DROP TABLE IF EXISTS {rebuild}"))
        conn.execute(text(_create_table_sql(rebuild, with_tenant)))
        common = ", ".join(column for column in _columns(with_tenant) if column in columns)
        conn.execute(text(f"INSERT INTO {rebuild} ({common}) SELECT {common} FROM {TABLE}"))
        conn.execute(text(f"DROP TABLE {TABLE}"))
        conn.execute(text(f"ALTER TABLE {rebuild} RENAME TO {TABLE}"))
        changed = True
    else:
        # ADD COLUMN feuert den UPDATE-Trigger nicht.
        for column in ("approval_mode", TENANT_COLUMN) if with_tenant else ("approval_mode",):
            if column not in columns:
                conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {column} VARCHAR"))
                changed = True
    conn.execute(text(
        f"CREATE INDEX IF NOT EXISTS {RUN_PRODUCT_INDEX} ON {TABLE} (recommendation_run_id, product_id)"
    ))
    if with_tenant:
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {TENANT_INDEX} ON {TABLE} (tenant_id)"))
    present = {row[0] for row in conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = :t"
    ), {"t": TABLE}).all()}
    if not set(SQLITE_TRIGGER_NAMES) <= present:
        for ddl in SQLITE_TRIGGERS:
            conn.execute(text(ddl))
        changed = True
    return changed


def ensure_sqlite_override_append_only(bind: Engine | Connection, *, with_tenant: bool = True) -> bool:
    """Bring an existing SQLite table to the append-only shape (no run FK,
    ``approval_mode``/``tenant_id`` columns, immutability triggers). Idempotent; returns
    True if anything changed. No-op if the table does not exist."""
    if isinstance(bind, Engine):
        with bind.begin() as conn:
            return _ensure(conn, with_tenant)
    return _ensure(bind, with_tenant)
