"""CCX-P2 Invalidation und Staleness (Vertrag 2026-11-13 §5).

Kein Backfill -- Bestand ohne Abhaengigkeitskanten bleibt ``UNKNOWN`` (nie
``FRESH``):

* ``advisory_decision_envelopes`` erhaelt ``freshness_status``
  (``FRESH|STALE|UNKNOWN``, Default ``UNKNOWN``), ``stale_at`` und
  ``stale_reason_code``; ``optimistic_version`` (P1) steigt bei jeder
  Frische-Aenderung um genau 1. Der P1-Update-Guard wird ersetzt: Einfuegen
  nur als UNKNOWN; DRAFT -> SEALED als UNKNOWN oder FRESH (FRESH nur mit
  Abhaengigkeitskanten, sonst ``CCX_FRESHNESS_UNKNOWN``); danach nur noch ->
  STALE (nie zurueck auf FRESH; erster stale_at/Reason bleibt); SEALED ->
  SUPERSEDED mit unveraenderter Frische; Inhalt bleibt append-only.
* ``advisory_dependency_edges``: unique ``(envelope_id, dependency_kind,
  dependency_object_id)``; nur solange der Envelope DRAFT ist einfuegbar,
  danach unveraenderlich; Mandant per zusammengesetztem FK.
* ``advisory_invalidation_events``: append-only, unique ``(envelope_id,
  invalidation_sequence)``; Einfuegen nur mit lueckenloser Folge
  (``CCX_INVALIDATION_RACE``), nur fuer einen STALE-Envelope und nur mit dem
  Mandat des Envelopes (Mandant per zusammengesetztem FK).

RLS ENABLE + FORCE und die strikte Policy folgen beim Boot ueber
``ensure_postgres_rls_policies`` (Tabellen mit tenant_id). Gleiche DDL wie
database.py (SQLite-Laufzeitpatch) und ares_schema.sql.

Revision ID: d868f4eaa028
Revises: 2c62f9012c73
Create Date: 2026-11-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "d868f4eaa028"
down_revision: Union[str, Sequence[str], None] = "2c62f9012c73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENVELOPES = "advisory_decision_envelopes"
BINDINGS = "advisory_envelope_bindings"
EDGES = "advisory_dependency_edges"
EVENTS = "advisory_invalidation_events"
TENANT_ERROR = "MANDATE_EVIDENCE_TENANT_MISMATCH"
FRESHNESS_CHECK = "freshness_status IN ('FRESH','STALE','UNKNOWN')"

# ── SQLite (textgleich database.py, eingefroren) ─────────────────────────────

# P1-Text des Update-Guards (2c62f9012c73) -- Downgrade stellt ihn wieder her.
P1_SQLITE_UPDATE_GUARD = (
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_decision_envelopes_update_guard "
    "BEFORE UPDATE ON advisory_decision_envelopes FOR EACH ROW "
    "WHEN NEW.id IS NOT OLD.id OR NEW.tenant_id IS NOT OLD.tenant_id "
    "OR NEW.mandate_id IS NOT OLD.mandate_id OR NEW.schema_version IS NOT OLD.schema_version "
    "OR NEW.locale IS NOT OLD.locale OR NEW.base_currency IS NOT OLD.base_currency "
    "OR NEW.predecessor_id IS NOT OLD.predecessor_id OR NEW.created_at IS NOT OLD.created_at "
    "OR NEW.created_by IS NOT OLD.created_by "
    "OR NEW.optimistic_version IS NOT OLD.optimistic_version + 1 "
    "OR NOT ((OLD.status = 'DRAFT' AND NEW.status IN ('DRAFT', 'SEALED')) "
    "OR (OLD.status = 'SEALED' AND NEW.status = 'SUPERSEDED' "
    "AND NEW.canonical_payload_json IS OLD.canonical_payload_json "
    "AND NEW.envelope_hash IS OLD.envelope_hash AND NEW.sealed_at IS OLD.sealed_at "
    "AND NEW.sealed_by IS OLD.sealed_by)) "
    "BEGIN SELECT RAISE(ABORT, 'advisory_decision_envelopes is append-only once sealed'); END"
)

SQLITE_UPDATE_GUARD = (
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_decision_envelopes_update_guard "
    "BEFORE UPDATE ON advisory_decision_envelopes FOR EACH ROW "
    "WHEN NEW.id IS NOT OLD.id OR NEW.tenant_id IS NOT OLD.tenant_id "
    "OR NEW.mandate_id IS NOT OLD.mandate_id OR NEW.schema_version IS NOT OLD.schema_version "
    "OR NEW.locale IS NOT OLD.locale OR NEW.base_currency IS NOT OLD.base_currency "
    "OR NEW.predecessor_id IS NOT OLD.predecessor_id OR NEW.created_at IS NOT OLD.created_at "
    "OR NEW.created_by IS NOT OLD.created_by "
    "OR NEW.optimistic_version IS NOT OLD.optimistic_version + 1 "
    "OR NOT ((OLD.status = 'DRAFT' AND NEW.status = 'DRAFT' "
    "AND OLD.freshness_status IN ('UNKNOWN', 'STALE') "
    "AND NEW.freshness_status IN (OLD.freshness_status, 'STALE')) "
    "OR (OLD.status = 'DRAFT' AND NEW.status = 'SEALED' AND OLD.freshness_status = 'UNKNOWN' "
    "AND NEW.freshness_status IN ('UNKNOWN', 'FRESH')) "
    "OR (OLD.status = 'SEALED' AND NEW.status IN ('SEALED', 'SUPERSEDED') "
    "AND NEW.canonical_payload_json IS OLD.canonical_payload_json "
    "AND NEW.envelope_hash IS OLD.envelope_hash AND NEW.sealed_at IS OLD.sealed_at "
    "AND NEW.sealed_by IS OLD.sealed_by "
    "AND ((NEW.status = 'SUPERSEDED' AND NEW.freshness_status IS OLD.freshness_status "
    "AND NEW.stale_at IS OLD.stale_at AND NEW.stale_reason_code IS OLD.stale_reason_code) "
    "OR (NEW.status = 'SEALED' AND NEW.freshness_status = 'STALE' "
    "AND (OLD.freshness_status IS NOT 'STALE' OR (NEW.stale_at IS OLD.stale_at "
    "AND NEW.stale_reason_code IS OLD.stale_reason_code)))))) "
    "OR (NEW.freshness_status = 'STALE' AND (NEW.stale_at IS NULL OR NEW.stale_reason_code IS NULL)) "
    "OR (NEW.freshness_status IS NOT 'STALE' AND (NEW.stale_at IS NOT NULL OR NEW.stale_reason_code IS NOT NULL)) "
    "BEGIN SELECT RAISE(ABORT, 'advisory_decision_envelopes is append-only once sealed'); END"
)

SQLITE_COLUMNS = (
    ("freshness_status", f"NOT NULL DEFAULT 'UNKNOWN' CHECK({FRESHNESS_CHECK})"),
    ("stale_at", ""),
    ("stale_reason_code", ""),
)

SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_decision_envelopes_freshness_insert "
    "BEFORE INSERT ON advisory_decision_envelopes FOR EACH ROW "
    "WHEN NEW.freshness_status IS NOT 'UNKNOWN' OR NEW.stale_at IS NOT NULL OR NEW.stale_reason_code IS NOT NULL "
    "BEGIN SELECT RAISE(ABORT, 'advisory_decision_envelopes: insert only as UNKNOWN'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_decision_envelopes_fresh_edges "
    "BEFORE UPDATE ON advisory_decision_envelopes FOR EACH ROW "
    "WHEN NEW.freshness_status = 'FRESH' AND OLD.freshness_status IS NOT 'FRESH' AND NOT EXISTS ("
    "SELECT 1 FROM advisory_dependency_edges d WHERE d.envelope_id = NEW.id) "
    "BEGIN SELECT RAISE(ABORT, 'CCX_FRESHNESS_UNKNOWN'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_dependency_edges_insert_guard "
    "BEFORE INSERT ON advisory_dependency_edges FOR EACH ROW "
    "WHEN (SELECT e.status FROM advisory_decision_envelopes e WHERE e.id = NEW.envelope_id) IS NOT 'DRAFT' "
    "BEGIN SELECT RAISE(ABORT, 'advisory_dependency_edges: envelope is not DRAFT'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_dependency_edges_no_update "
    "BEFORE UPDATE ON advisory_dependency_edges FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'advisory_dependency_edges is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_dependency_edges_no_delete "
    "BEFORE DELETE ON advisory_dependency_edges FOR EACH ROW "
    "WHEN (SELECT e.status FROM advisory_decision_envelopes e WHERE e.id = OLD.envelope_id) IS NOT 'DRAFT' "
    "BEGIN SELECT RAISE(ABORT, 'advisory_dependency_edges is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_invalidation_events_insert_mandate "
    "BEFORE INSERT ON advisory_invalidation_events FOR EACH ROW "
    "WHEN NEW.mandate_id IS NOT (SELECT e.mandate_id FROM advisory_decision_envelopes e "
    "WHERE e.id = NEW.envelope_id AND e.tenant_id = NEW.tenant_id) "
    "BEGIN SELECT RAISE(ABORT, 'MANDATE_EVIDENCE_TENANT_MISMATCH'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_invalidation_events_insert_stale "
    "BEFORE INSERT ON advisory_invalidation_events FOR EACH ROW "
    "WHEN (SELECT e.freshness_status FROM advisory_decision_envelopes e WHERE e.id = NEW.envelope_id) IS NOT 'STALE' "
    "BEGIN SELECT RAISE(ABORT, 'CCX_INPUT_STALE: envelope must be stale'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_invalidation_events_insert_sequence "
    "BEFORE INSERT ON advisory_invalidation_events FOR EACH ROW "
    "WHEN NEW.invalidation_sequence IS NOT (SELECT COALESCE(MAX(i.invalidation_sequence), 0) + 1 "
    "FROM advisory_invalidation_events i WHERE i.envelope_id = NEW.envelope_id) "
    "BEGIN SELECT RAISE(ABORT, 'CCX_INVALIDATION_RACE'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_dependency_edges_no_replace "
    "BEFORE INSERT ON advisory_dependency_edges FOR EACH ROW "
    "WHEN EXISTS (SELECT 1 FROM advisory_dependency_edges d WHERE d.id = NEW.id "
    "OR (d.envelope_id = NEW.envelope_id AND d.dependency_kind = NEW.dependency_kind "
    "AND d.dependency_object_id = NEW.dependency_object_id)) "
    "BEGIN SELECT RAISE(ABORT, 'advisory_dependency_edges row already exists (no replace)'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_invalidation_events_no_replace "
    "BEFORE INSERT ON advisory_invalidation_events FOR EACH ROW "
    "WHEN EXISTS (SELECT 1 FROM advisory_invalidation_events i WHERE i.id = NEW.id "
    "OR (i.envelope_id = NEW.envelope_id AND i.invalidation_sequence = NEW.invalidation_sequence)) "
    "BEGIN SELECT RAISE(ABORT, 'advisory_invalidation_events row already exists (no replace)'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_invalidation_events_no_update "
    "BEFORE UPDATE ON advisory_invalidation_events FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'advisory_invalidation_events is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_invalidation_events_no_delete "
    "BEFORE DELETE ON advisory_invalidation_events FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'advisory_invalidation_events is append-only'); END",
)
SQLITE_TRIGGER_NAMES = tuple(ddl.split()[5] for ddl in SQLITE_TRIGGERS)

# ── PostgreSQL ───────────────────────────────────────────────────────────────

_PG_ENVELOPE_COMMON_INSERT_DELETE = f"""  IF TG_OP = 'INSERT' THEN
    IF NEW.status IS DISTINCT FROM 'DRAFT' OR NEW.optimistic_version IS DISTINCT FROM 1
       OR NEW.canonical_payload_json IS NOT NULL OR NEW.envelope_hash IS NOT NULL
       OR NEW.sealed_at IS NOT NULL OR NEW.sealed_by IS NOT NULL THEN
      RAISE EXCEPTION '{ENVELOPES}: insert only as DRAFT' USING ERRCODE = '23514';
    END IF;
@@FRESH_INSERT@@    SELECT m.tenant_id INTO derived FROM mandates m WHERE m.id = NEW.mandate_id;
    IF derived IS NULL OR NEW.tenant_id IS DISTINCT FROM derived THEN
      RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
  ELSIF TG_OP = 'DELETE' THEN
    IF OLD.status IS DISTINCT FROM 'DRAFT' THEN
      RAISE EXCEPTION '{ENVELOPES} is append-only once sealed';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
     OR NEW.mandate_id IS DISTINCT FROM OLD.mandate_id
     OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
     OR NEW.locale IS DISTINCT FROM OLD.locale
     OR NEW.base_currency IS DISTINCT FROM OLD.base_currency
     OR NEW.predecessor_id IS DISTINCT FROM OLD.predecessor_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR NEW.created_by IS DISTINCT FROM OLD.created_by
     OR NEW.optimistic_version IS DISTINCT FROM OLD.optimistic_version + 1
"""

# P1-Fassung (2c62f9012c73 inkl. Nachtrag 1 / N-906-01), eingefroren fuer den Downgrade.
P1_PG_ENVELOPE_FUNCTION = (
    f"""CREATE OR REPLACE FUNCTION {ENVELOPES}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text;
BEGIN
"""
    + _PG_ENVELOPE_COMMON_INSERT_DELETE.replace("@@FRESH_INSERT@@", "")
    + f"""     OR NOT ((OLD.status = 'DRAFT' AND NEW.status IN ('DRAFT', 'SEALED'))
             OR (OLD.status = 'SEALED' AND NEW.status = 'SUPERSEDED'
                 AND NEW.canonical_payload_json IS NOT DISTINCT FROM OLD.canonical_payload_json
                 AND NEW.envelope_hash IS NOT DISTINCT FROM OLD.envelope_hash
                 AND NEW.sealed_at IS NOT DISTINCT FROM OLD.sealed_at
                 AND NEW.sealed_by IS NOT DISTINCT FROM OLD.sealed_by)) THEN
    RAISE EXCEPTION '{ENVELOPES} is append-only once sealed';
  END IF;
  IF OLD.status = 'DRAFT' AND NEW.status = 'SEALED' AND NOT EXISTS (
      SELECT 1 FROM {BINDINGS} b WHERE b.envelope_id = NEW.id
      AND b.binding_kind = 'effective_input_manifest') THEN
    RAISE EXCEPTION 'CCX_BINDING_MISSING';
  END IF;
  RETURN NEW;
END $$"""
)

PG_ENVELOPE_FUNCTION = (
    f"""CREATE OR REPLACE FUNCTION {ENVELOPES}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text;
BEGIN
"""
    + _PG_ENVELOPE_COMMON_INSERT_DELETE.replace(
        "@@FRESH_INSERT@@",
        "    IF NEW.freshness_status IS DISTINCT FROM 'UNKNOWN' OR NEW.stale_at IS NOT NULL\n"
        "       OR NEW.stale_reason_code IS NOT NULL THEN\n"
        f"      RAISE EXCEPTION '{ENVELOPES}: insert only as UNKNOWN' USING ERRCODE = '23514';\n"
        "    END IF;\n",
    )
    + f"""     OR NOT ((OLD.status = 'DRAFT' AND NEW.status = 'DRAFT'
              AND OLD.freshness_status IN ('UNKNOWN', 'STALE')
              AND NEW.freshness_status IN (OLD.freshness_status, 'STALE'))
             OR (OLD.status = 'DRAFT' AND NEW.status = 'SEALED' AND OLD.freshness_status = 'UNKNOWN'
                 AND NEW.freshness_status IN ('UNKNOWN', 'FRESH'))
             OR (OLD.status = 'SEALED' AND NEW.status IN ('SEALED', 'SUPERSEDED')
                 AND NEW.canonical_payload_json IS NOT DISTINCT FROM OLD.canonical_payload_json
                 AND NEW.envelope_hash IS NOT DISTINCT FROM OLD.envelope_hash
                 AND NEW.sealed_at IS NOT DISTINCT FROM OLD.sealed_at
                 AND NEW.sealed_by IS NOT DISTINCT FROM OLD.sealed_by
                 AND ((NEW.status = 'SUPERSEDED'
                       AND NEW.freshness_status IS NOT DISTINCT FROM OLD.freshness_status
                       AND NEW.stale_at IS NOT DISTINCT FROM OLD.stale_at
                       AND NEW.stale_reason_code IS NOT DISTINCT FROM OLD.stale_reason_code)
                      OR (NEW.status = 'SEALED' AND NEW.freshness_status = 'STALE'
                          AND (OLD.freshness_status IS DISTINCT FROM 'STALE'
                               OR (NEW.stale_at IS NOT DISTINCT FROM OLD.stale_at
                                   AND NEW.stale_reason_code IS NOT DISTINCT FROM OLD.stale_reason_code))))))
     OR (NEW.freshness_status = 'STALE' AND (NEW.stale_at IS NULL OR NEW.stale_reason_code IS NULL))
     OR (NEW.freshness_status IS DISTINCT FROM 'STALE'
         AND (NEW.stale_at IS NOT NULL OR NEW.stale_reason_code IS NOT NULL)) THEN
    RAISE EXCEPTION '{ENVELOPES} is append-only once sealed';
  END IF;
  IF OLD.status = 'DRAFT' AND NEW.status = 'SEALED' AND NOT EXISTS (
      SELECT 1 FROM {BINDINGS} b WHERE b.envelope_id = NEW.id
      AND b.binding_kind = 'effective_input_manifest') THEN
    RAISE EXCEPTION 'CCX_BINDING_MISSING';
  END IF;
  IF NEW.freshness_status = 'FRESH' AND OLD.freshness_status IS DISTINCT FROM 'FRESH' AND NOT EXISTS (
      SELECT 1 FROM {EDGES} d WHERE d.envelope_id = NEW.id) THEN
    RAISE EXCEPTION 'CCX_FRESHNESS_UNKNOWN';
  END IF;
  RETURN NEW;
END $$"""
)

PG_FUNCTIONS = (
    f"""CREATE OR REPLACE FUNCTION {EDGES}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE envelope_status text;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION '{EDGES} is immutable';
  END IF;
  IF TG_OP = 'INSERT' THEN
    SELECT e.status INTO envelope_status FROM {ENVELOPES} e WHERE e.id = NEW.envelope_id;
    IF envelope_status IS DISTINCT FROM 'DRAFT' THEN
      RAISE EXCEPTION '{EDGES}: envelope is not DRAFT';
    END IF;
    RETURN NEW;
  END IF;
  SELECT e.status INTO envelope_status FROM {ENVELOPES} e WHERE e.id = OLD.envelope_id;
  IF envelope_status IS DISTINCT FROM 'DRAFT' THEN
    RAISE EXCEPTION '{EDGES} is immutable';
  END IF;
  RETURN OLD;
END $$""",
    f"""CREATE OR REPLACE FUNCTION {EVENTS}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE envelope_mandate text;
DECLARE envelope_freshness text;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION '{EVENTS} is append-only';
  END IF;
  SELECT e.mandate_id, e.freshness_status INTO envelope_mandate, envelope_freshness
    FROM {ENVELOPES} e WHERE e.id = NEW.envelope_id AND e.tenant_id = NEW.tenant_id;
  IF envelope_mandate IS NULL OR NEW.mandate_id IS DISTINCT FROM envelope_mandate THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  IF envelope_freshness IS DISTINCT FROM 'STALE' THEN
    RAISE EXCEPTION 'CCX_INPUT_STALE: envelope must be stale' USING ERRCODE = '23514';
  END IF;
  IF NEW.invalidation_sequence IS DISTINCT FROM (
      SELECT COALESCE(MAX(i.invalidation_sequence), 0) + 1 FROM {EVENTS} i
      WHERE i.envelope_id = NEW.envelope_id) THEN
    RAISE EXCEPTION 'CCX_INVALIDATION_RACE' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$""",
)
PG_TRIGGERS = tuple(
    f"CREATE TRIGGER trg_{table}_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} "
    f"FOR EACH ROW EXECUTE FUNCTION {table}_guard()"
    for table in (EDGES, EVENTS)
)


def _dialect() -> str:
    if context.is_offline_mode():
        return context.get_context().dialect.name
    return op.get_bind().dialect.name


def upgrade() -> None:
    dialect = _dialect()
    column_type = "TEXT" if dialect == "sqlite" else "VARCHAR"
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_advisory_decision_envelopes_update_guard")
    for name, constraint in SQLITE_COLUMNS:
        named = constraint.replace(
            "CHECK(", "CONSTRAINT ck_advisory_decision_envelopes_freshness CHECK(",
        ) if dialect != "sqlite" else constraint
        op.execute(f"ALTER TABLE {ENVELOPES} ADD COLUMN {name} {column_type} {named}".rstrip())

    op.create_table(
        EDGES,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("envelope_id", sa.String(), nullable=False),
        sa.Column("dependency_kind", sa.String(), nullable=False),
        sa.Column("dependency_object_id", sa.String(), nullable=False),
        sa.Column("dependency_version", sa.Integer(), nullable=True),
        sa.Column("dependency_hash", sa.String(), nullable=False),
        sa.Column("observed_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.CheckConstraint("length(dependency_hash) = 64", name="ck_advisory_dependency_edges_hash_length"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "envelope_id"], [f"{ENVELOPES}.tenant_id", f"{ENVELOPES}.id"],
            name="fk_advisory_dependency_edges_envelope",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "envelope_id", "dependency_kind", "dependency_object_id",
            name="uq_advisory_dependency_edges_kind_object",
        ),
    )
    op.create_index("ix_advisory_dependency_edges_tenant_id", EDGES, ["tenant_id"])
    op.create_index("ix_advisory_dependency_edges_object", EDGES, ["dependency_kind", "dependency_object_id"])

    op.create_table(
        EVENTS,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("envelope_id", sa.String(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("source_object_id", sa.String(), nullable=False),
        sa.Column("old_hash", sa.String(), nullable=True),
        sa.Column("new_hash", sa.String(), nullable=True),
        sa.Column("reason_code", sa.String(), nullable=False),
        sa.Column("invalidation_sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.CheckConstraint("old_hash IS NULL OR length(old_hash) = 64", name="ck_advisory_invalidation_events_old_hash"),
        sa.CheckConstraint("new_hash IS NULL OR length(new_hash) = 64", name="ck_advisory_invalidation_events_new_hash"),
        sa.CheckConstraint("reason_code = 'CCX_INPUT_STALE'", name="ck_advisory_invalidation_events_reason"),
        sa.CheckConstraint("invalidation_sequence >= 1", name="ck_advisory_invalidation_events_sequence"),
        sa.CheckConstraint("length(created_by) > 0", name="ck_advisory_invalidation_events_actor"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "envelope_id"], [f"{ENVELOPES}.tenant_id", f"{ENVELOPES}.id"],
            name="fk_advisory_invalidation_events_envelope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("envelope_id", "invalidation_sequence", name="uq_advisory_invalidation_events_sequence"),
    )
    op.create_index("ix_advisory_invalidation_events_tenant_id", EVENTS, ["tenant_id"])
    op.create_index("ix_advisory_invalidation_events_mandate", EVENTS, ["tenant_id", "mandate_id"])

    if dialect == "sqlite":
        for ddl in (SQLITE_UPDATE_GUARD,) + SQLITE_TRIGGERS:
            op.execute(ddl)
    elif dialect == "postgresql":
        for ddl in (PG_ENVELOPE_FUNCTION,) + PG_FUNCTIONS + PG_TRIGGERS:
            op.execute(ddl)


def downgrade() -> None:
    dialect = _dialect()
    if dialect == "postgresql":
        for table in (EVENTS, EDGES):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_guard ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_guard()")
        op.execute(P1_PG_ENVELOPE_FUNCTION)
    elif dialect == "sqlite":
        for name in SQLITE_TRIGGER_NAMES + ("trg_advisory_decision_envelopes_update_guard",):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("ix_advisory_invalidation_events_mandate", table_name=EVENTS)
    op.drop_index("ix_advisory_invalidation_events_tenant_id", table_name=EVENTS)
    op.drop_table(EVENTS)
    op.drop_index("ix_advisory_dependency_edges_object", table_name=EDGES)
    op.drop_index("ix_advisory_dependency_edges_tenant_id", table_name=EDGES)
    op.drop_table(EDGES)
    for name, _constraint in reversed(SQLITE_COLUMNS):
        op.execute(f"ALTER TABLE {ENVELOPES} DROP COLUMN {name}")
    if dialect == "sqlite":
        op.execute(P1_SQLITE_UPDATE_GUARD)
