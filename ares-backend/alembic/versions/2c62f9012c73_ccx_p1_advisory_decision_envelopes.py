"""CCX-P1 Snapshot und Hash: Beratungsentscheid-Envelope (Vertrag 2026-11-13 §4).

Drei neue Tabellen (kein Backfill -- Bestand wird nie als versiegelt oder
geprueft markiert):

* ``advisory_decision_envelopes``: DRAFT -> SEALED -> SUPERSEDED; kanonischer
  Payload ``ares/advisory-envelope/1`` + ``envelope_hash``; Unique
  ``(tenant_id, envelope_hash)``; hoechstens ein SEALED je Mandat und ein
  Nachfolger je Vorgaenger (Parallelversiegelung -> ein Sieger); SEALED ist
  append-only, einzige Aenderung SEALED -> SUPERSEDED bei unveraendertem
  Inhalt; ``optimistic_version`` steigt bei jeder Aenderung um genau 1.
* ``advisory_envelope_bindings``: Kind-Bindungen (Merkle-Blaetter), unique
  ``(envelope_id, binding_kind, ordinal)``; nur solange der Envelope DRAFT ist
  einfuegbar, danach unveraenderlich; Mandant per zusammengesetztem FK.
* ``advisory_effective_input_manifests``: Effective-Input-Manifest, append-only.

Mandantentrennung: ``tenant_id`` NOT NULL -> tenants, INSERT-Guard leitet den
Mandanten aus dem Mandat ab (PostgreSQL: unter RLS ist ein fremdes Mandat
unsichtbar -> Ablehnung); RLS ENABLE + FORCE und die strikte Policy folgen
beim Boot ueber ``ensure_postgres_rls_policies`` (Tabellen mit tenant_id).
Gleiche DDL wie database.py (SQLite-Laufzeitpatch) und ares_schema.sql.

Revision ID: 2c62f9012c73
Revises: e7b3d9f1a2c4
Create Date: 2026-11-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "2c62f9012c73"
down_revision: Union[str, Sequence[str], None] = "e7b3d9f1a2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENVELOPES = "advisory_decision_envelopes"
BINDINGS = "advisory_envelope_bindings"
MANIFESTS = "advisory_effective_input_manifests"
TENANT_ERROR = "MANDATE_EVIDENCE_TENANT_MISMATCH"

# SQLite: textgleich database.py ADVISORY_ENVELOPE_SQLITE_TRIGGERS +
# ADVISORY_ENVELOPE_SQLITE_TENANT_GUARDS (eingefroren).
_SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_decision_envelopes_insert_guard "
    "BEFORE INSERT ON advisory_decision_envelopes FOR EACH ROW "
    "WHEN NEW.status IS NOT 'DRAFT' OR NEW.optimistic_version IS NOT 1 "
    "BEGIN SELECT RAISE(ABORT, 'advisory_decision_envelopes: insert only as DRAFT'); END",
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
    "BEGIN SELECT RAISE(ABORT, 'advisory_decision_envelopes is append-only once sealed'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_decision_envelopes_seal_binding "
    "BEFORE UPDATE ON advisory_decision_envelopes FOR EACH ROW "
    "WHEN OLD.status = 'DRAFT' AND NEW.status = 'SEALED' AND NOT EXISTS ("
    "SELECT 1 FROM advisory_envelope_bindings b WHERE b.envelope_id = NEW.id "
    "AND b.binding_kind = 'effective_input_manifest') "
    "BEGIN SELECT RAISE(ABORT, 'CCX_BINDING_MISSING'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_decision_envelopes_no_delete "
    "BEFORE DELETE ON advisory_decision_envelopes FOR EACH ROW "
    "WHEN OLD.status IS NOT 'DRAFT' "
    "BEGIN SELECT RAISE(ABORT, 'advisory_decision_envelopes is append-only once sealed'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_envelope_bindings_insert_guard "
    "BEFORE INSERT ON advisory_envelope_bindings FOR EACH ROW "
    "WHEN (SELECT e.status FROM advisory_decision_envelopes e WHERE e.id = NEW.envelope_id) IS NOT 'DRAFT' "
    "BEGIN SELECT RAISE(ABORT, 'advisory_envelope_bindings: envelope is not DRAFT'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_envelope_bindings_no_update "
    "BEFORE UPDATE ON advisory_envelope_bindings FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'advisory_envelope_bindings is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_envelope_bindings_no_delete "
    "BEFORE DELETE ON advisory_envelope_bindings FOR EACH ROW "
    "WHEN (SELECT e.status FROM advisory_decision_envelopes e WHERE e.id = OLD.envelope_id) IS NOT 'DRAFT' "
    "BEGIN SELECT RAISE(ABORT, 'advisory_envelope_bindings is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_effective_input_manifests_no_update "
    "BEFORE UPDATE ON advisory_effective_input_manifests FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'advisory_effective_input_manifests is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_effective_input_manifests_no_delete "
    "BEFORE DELETE ON advisory_effective_input_manifests FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'advisory_effective_input_manifests is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_decision_envelopes_tenant_guard "
    "BEFORE INSERT ON advisory_decision_envelopes FOR EACH ROW "
    "WHEN NEW.tenant_id IS NOT (SELECT m.tenant_id FROM mandates m WHERE m.id = NEW.mandate_id) "
    "BEGIN SELECT RAISE(ABORT, 'MANDATE_EVIDENCE_TENANT_MISMATCH'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_effective_input_manifests_tenant_guard "
    "BEFORE INSERT ON advisory_effective_input_manifests FOR EACH ROW "
    "WHEN NEW.tenant_id IS NOT (SELECT m.tenant_id FROM mandates m WHERE m.id = NEW.mandate_id) "
    "BEGIN SELECT RAISE(ABORT, 'MANDATE_EVIDENCE_TENANT_MISMATCH'); END",
)
_SQLITE_TRIGGER_NAMES = (
    "trg_advisory_decision_envelopes_insert_guard",
    "trg_advisory_decision_envelopes_update_guard",
    "trg_advisory_decision_envelopes_seal_binding",
    "trg_advisory_decision_envelopes_no_delete",
    "trg_advisory_envelope_bindings_insert_guard",
    "trg_advisory_envelope_bindings_no_update",
    "trg_advisory_envelope_bindings_no_delete",
    "trg_advisory_effective_input_manifests_no_update",
    "trg_advisory_effective_input_manifests_no_delete",
    "trg_advisory_decision_envelopes_tenant_guard",
    "trg_advisory_effective_input_manifests_tenant_guard",
)

# PostgreSQL: dieselben Regeln als plpgsql (ein Guard je Tabelle). Unter RLS
# sieht die Mandats-/Envelope-Abfrage nur den Mandanten der Session.
_PG_FUNCTIONS = (
    f"""CREATE OR REPLACE FUNCTION {ENVELOPES}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status IS DISTINCT FROM 'DRAFT' OR NEW.optimistic_version IS DISTINCT FROM 1 THEN
      RAISE EXCEPTION '{ENVELOPES}: insert only as DRAFT' USING ERRCODE = '23514';
    END IF;
    SELECT m.tenant_id INTO derived FROM mandates m WHERE m.id = NEW.mandate_id;
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
     OR NOT ((OLD.status = 'DRAFT' AND NEW.status IN ('DRAFT', 'SEALED'))
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
END $$""",
    f"""CREATE OR REPLACE FUNCTION {BINDINGS}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE envelope_status text;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION '{BINDINGS} is immutable';
  END IF;
  IF TG_OP = 'INSERT' THEN
    SELECT e.status INTO envelope_status FROM {ENVELOPES} e WHERE e.id = NEW.envelope_id;
    IF envelope_status IS DISTINCT FROM 'DRAFT' THEN
      RAISE EXCEPTION '{BINDINGS}: envelope is not DRAFT';
    END IF;
    RETURN NEW;
  END IF;
  SELECT e.status INTO envelope_status FROM {ENVELOPES} e WHERE e.id = OLD.envelope_id;
  IF envelope_status IS DISTINCT FROM 'DRAFT' THEN
    RAISE EXCEPTION '{BINDINGS} is immutable';
  END IF;
  RETURN OLD;
END $$""",
    f"""CREATE OR REPLACE FUNCTION {MANIFESTS}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION '{MANIFESTS} is immutable';
  END IF;
  SELECT m.tenant_id INTO derived FROM mandates m WHERE m.id = NEW.mandate_id;
  IF derived IS NULL OR NEW.tenant_id IS DISTINCT FROM derived THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$""",
)
_PG_TRIGGERS = tuple(
    f"CREATE TRIGGER trg_{table}_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} "
    f"FOR EACH ROW EXECUTE FUNCTION {table}_guard()"
    for table in (ENVELOPES, BINDINGS, MANIFESTS)
)


def _dialect() -> str:
    if context.is_offline_mode():
        return context.get_context().dialect.name
    return op.get_bind().dialect.name


def upgrade() -> None:
    op.create_table(
        ENVELOPES,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("locale", sa.String(), nullable=False),
        sa.Column("base_currency", sa.String(), nullable=False),
        sa.Column("canonical_payload_json", sa.String(), nullable=True),
        sa.Column("envelope_hash", sa.String(), nullable=True),
        sa.Column("predecessor_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("sealed_at", sa.String(), nullable=True),
        sa.Column("sealed_by", sa.String(), nullable=True),
        sa.Column("optimistic_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "schema_version = 'ares/advisory-envelope/1'",
            name="ck_advisory_decision_envelopes_schema_version",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','SEALED','SUPERSEDED')", name="ck_advisory_decision_envelopes_status",
        ),
        sa.CheckConstraint(
            "envelope_hash IS NULL OR length(envelope_hash) = 64",
            name="ck_advisory_decision_envelopes_hash_length",
        ),
        sa.CheckConstraint("optimistic_version >= 1", name="ck_advisory_decision_envelopes_version"),
        sa.CheckConstraint(
            "status = 'DRAFT' OR (canonical_payload_json IS NOT NULL AND envelope_hash IS NOT NULL "
            "AND sealed_at IS NOT NULL AND sealed_by IS NOT NULL)",
            name="ck_advisory_decision_envelopes_sealed_complete",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["sealed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "envelope_hash", name="uq_advisory_decision_envelopes_tenant_hash"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_advisory_decision_envelopes_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "predecessor_id"], [f"{ENVELOPES}.tenant_id", f"{ENVELOPES}.id"],
            name="fk_advisory_decision_envelopes_predecessor",
        ),
    )
    op.create_index("ix_advisory_decision_envelopes_tenant_id", ENVELOPES, ["tenant_id"])
    op.create_index("ix_advisory_decision_envelopes_mandate", ENVELOPES, ["tenant_id", "mandate_id", "status"])
    op.create_index(
        "ux_advisory_decision_envelopes_one_sealed", ENVELOPES, ["tenant_id", "mandate_id"], unique=True,
        sqlite_where=sa.text("status = 'SEALED'"), postgresql_where=sa.text("status = 'SEALED'"),
    )
    op.create_index(
        "ux_advisory_decision_envelopes_one_successor", ENVELOPES, ["predecessor_id"], unique=True,
        sqlite_where=sa.text("predecessor_id IS NOT NULL"),
        postgresql_where=sa.text("predecessor_id IS NOT NULL"),
    )

    op.create_table(
        BINDINGS,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("envelope_id", sa.String(), nullable=False),
        sa.Column("binding_kind", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("object_id", sa.String(), nullable=False),
        sa.Column("object_version", sa.Integer(), nullable=True),
        sa.Column("child_hash", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.CheckConstraint("length(child_hash) = 64", name="ck_advisory_envelope_bindings_hash_length"),
        sa.CheckConstraint("ordinal >= 0", name="ck_advisory_envelope_bindings_ordinal"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "envelope_id"], [f"{ENVELOPES}.tenant_id", f"{ENVELOPES}.id"],
            name="fk_advisory_envelope_bindings_envelope",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "envelope_id", "binding_kind", "ordinal", name="uq_advisory_envelope_bindings_kind_ordinal",
        ),
    )
    op.create_index("ix_advisory_envelope_bindings_tenant_id", BINDINGS, ["tenant_id"])

    op.create_table(
        MANIFESTS,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        *(sa.Column(name, sa.String(), nullable=False) for name in (
            "client_hash", "mandate_hash", "goals_hash", "cashflows_hash", "risk_hash",
            "preference_hash", "cma_hash", "policy_hash", "constraints_hash", "holdings_hash",
            "engine_version", "random_stream_id", "rounding_policy_version", "manifest_hash",
            "created_at", "created_by",
        )),
        sa.CheckConstraint("length(manifest_hash) = 64", name="ck_advisory_effective_input_manifests_hash"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_advisory_effective_input_manifests_tenant_id"),
    )
    op.create_index("ix_advisory_effective_input_manifests_tenant_id", MANIFESTS, ["tenant_id"])
    op.create_index("ix_advisory_effective_input_manifests_mandate", MANIFESTS, ["tenant_id", "mandate_id"])

    dialect = _dialect()
    if dialect == "sqlite":
        for ddl in _SQLITE_TRIGGERS:
            op.execute(ddl)
    elif dialect == "postgresql":
        for ddl in _PG_FUNCTIONS + _PG_TRIGGERS:
            op.execute(ddl)


def downgrade() -> None:
    dialect = _dialect()
    if dialect == "postgresql":
        for table in (MANIFESTS, BINDINGS, ENVELOPES):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_guard ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_guard()")
    elif dialect == "sqlite":
        for name in _SQLITE_TRIGGER_NAMES:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("ix_advisory_effective_input_manifests_mandate", table_name=MANIFESTS)
    op.drop_index("ix_advisory_effective_input_manifests_tenant_id", table_name=MANIFESTS)
    op.drop_table(MANIFESTS)
    op.drop_index("ix_advisory_envelope_bindings_tenant_id", table_name=BINDINGS)
    op.drop_table(BINDINGS)
    op.drop_index("ux_advisory_decision_envelopes_one_successor", table_name=ENVELOPES)
    op.drop_index("ux_advisory_decision_envelopes_one_sealed", table_name=ENVELOPES)
    op.drop_index("ix_advisory_decision_envelopes_mandate", table_name=ENVELOPES)
    op.drop_index("ix_advisory_decision_envelopes_tenant_id", table_name=ENVELOPES)
    op.drop_table(ENVELOPES)
