"""CCX-P4 Allocation-Publish (Vertrag 2026-11-13 §7).

Zwei neue Tabellen (kein Backfill -- Bestand ist nicht publiziert, bis
ausdruecklich ueber das Publish-Gate publiziert wird):

* ``allocation_publication_decisions``: append-only Publikationsentscheide je
  Mandat mit lueckenloser ``publication_sequence`` (``CCX_PUBLICATION_RACE``),
  ``validation_hash``, Freigabe (``approval_hash``, Freigeber, Zeit, Modus),
  ``publishable`` und ``blocker_codes_json``; ``published_envelope_hash`` nur
  bei Publikation und nur fuer einen SEALED+FRESH Envelope desselben Mandats.
  Hoechstens eine Publikation je Envelope (partieller Unique-Index).
* ``allocation_active_publications``: Active-Pointer, hoechstens einer je
  Mandat; zeigt nur auf einen publizierbaren Entscheid desselben Mandats,
  wandert nur vorwaerts (hoehere Sequenz, ``optimistic_version`` + 1), nie
  geloescht.

Beide Tabellen sind mandantengebunden (INSERT-Guard aus dem Mandat; RLS
ENABLE + FORCE folgen beim Boot ueber ``ensure_postgres_rls_policies``).
Gleiche DDL wie database.py (SQLite-Laufzeitpatch) und ares_schema.sql.

Platz ``CCX_P4_REV``; lineare Kette P1 ``2c62f9012c73`` -> P2 ``d868f4eaa028``
-> P3 ``6814c14575e9`` -> P4 (diese Revision).

Revision ID: 24e7606245d3
Revises: 6814c14575e9
Create Date: 2026-11-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "24e7606245d3"
down_revision: Union[str, Sequence[str], None] = "6814c14575e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DECISIONS = "allocation_publication_decisions"
POINTER = "allocation_active_publications"
ENVELOPES = "advisory_decision_envelopes"
TENANT_ERROR = "MANDATE_EVIDENCE_TENANT_MISMATCH"

# SQLite: textgleich database.py ALLOCATION_PUBLICATION_SQLITE_TRIGGERS +
# ALLOCATION_PUBLICATION_SQLITE_TENANT_GUARDS (eingefroren).
_SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS trg_allocation_publication_decisions_no_replace "
    "BEFORE INSERT ON allocation_publication_decisions FOR EACH ROW "
    "WHEN EXISTS (SELECT 1 FROM allocation_publication_decisions d WHERE d.id = NEW.id "
    "OR (d.mandate_id = NEW.mandate_id AND d.publication_sequence = NEW.publication_sequence)) "
    "BEGIN SELECT RAISE(ABORT, 'allocation_publication_decisions row already exists (no replace)'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_allocation_publication_decisions_sequence "
    "BEFORE INSERT ON allocation_publication_decisions FOR EACH ROW "
    "WHEN NEW.publication_sequence IS NOT (SELECT COALESCE(MAX(d.publication_sequence), 0) + 1 "
    "FROM allocation_publication_decisions d WHERE d.mandate_id = NEW.mandate_id) "
    "BEGIN SELECT RAISE(ABORT, 'CCX_PUBLICATION_RACE'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_allocation_publication_decisions_envelope "
    "BEFORE INSERT ON allocation_publication_decisions FOR EACH ROW "
    "WHEN NEW.publishable = 1 AND NOT EXISTS (SELECT 1 FROM advisory_decision_envelopes e "
    "WHERE e.id = NEW.envelope_id AND e.tenant_id = NEW.tenant_id AND e.mandate_id = NEW.mandate_id "
    "AND e.status = 'SEALED' AND e.freshness_status = 'FRESH' AND e.envelope_hash = NEW.published_envelope_hash) "
    "BEGIN SELECT RAISE(ABORT, 'CCX_ALLOCATION_NOT_PUBLISHABLE'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_allocation_publication_decisions_no_update "
    "BEFORE UPDATE ON allocation_publication_decisions FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'allocation_publication_decisions is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_allocation_publication_decisions_no_delete "
    "BEFORE DELETE ON allocation_publication_decisions FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'allocation_publication_decisions is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_allocation_active_publications_insert "
    "BEFORE INSERT ON allocation_active_publications FOR EACH ROW "
    "WHEN EXISTS (SELECT 1 FROM allocation_active_publications p WHERE p.id = NEW.id "
    "OR p.mandate_id = NEW.mandate_id) OR NEW.optimistic_version IS NOT 1 "
    "OR NOT EXISTS (SELECT 1 FROM allocation_publication_decisions d WHERE d.id = NEW.publication_id "
    "AND d.tenant_id = NEW.tenant_id AND d.mandate_id = NEW.mandate_id AND d.publishable = 1) "
    "BEGIN SELECT RAISE(ABORT, 'CCX_PUBLICATION_RACE'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_allocation_active_publications_update "
    "BEFORE UPDATE ON allocation_active_publications FOR EACH ROW "
    "WHEN NEW.id IS NOT OLD.id OR NEW.tenant_id IS NOT OLD.tenant_id OR NEW.mandate_id IS NOT OLD.mandate_id "
    "OR NEW.optimistic_version IS NOT OLD.optimistic_version + 1 "
    "OR NOT EXISTS (SELECT 1 FROM allocation_publication_decisions d WHERE d.id = NEW.publication_id "
    "AND d.tenant_id = NEW.tenant_id AND d.mandate_id = NEW.mandate_id AND d.publishable = 1 "
    "AND d.publication_sequence > (SELECT o.publication_sequence FROM allocation_publication_decisions o "
    "WHERE o.id = OLD.publication_id)) "
    "BEGIN SELECT RAISE(ABORT, 'CCX_PUBLICATION_RACE'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_allocation_active_publications_no_delete "
    "BEFORE DELETE ON allocation_active_publications FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'allocation_active_publications: pointer is never deleted'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_allocation_publication_decisions_tenant_guard "
    "BEFORE INSERT ON allocation_publication_decisions FOR EACH ROW "
    "WHEN NEW.tenant_id IS NOT (SELECT m.tenant_id FROM mandates m WHERE m.id = NEW.mandate_id) "
    "BEGIN SELECT RAISE(ABORT, 'MANDATE_EVIDENCE_TENANT_MISMATCH'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_allocation_active_publications_tenant_guard "
    "BEFORE INSERT ON allocation_active_publications FOR EACH ROW "
    "WHEN NEW.tenant_id IS NOT (SELECT m.tenant_id FROM mandates m WHERE m.id = NEW.mandate_id) "
    "BEGIN SELECT RAISE(ABORT, 'MANDATE_EVIDENCE_TENANT_MISMATCH'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_allocation_publication_decisions_binding_guard "
    "BEFORE INSERT ON allocation_publication_decisions FOR EACH ROW "
    "WHEN (NEW.target_allocation_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM target_allocations t "
    "WHERE t.id = NEW.target_allocation_id AND t.mandate_id = NEW.mandate_id)) "
    "OR NEW.tenant_id IS NOT (SELECT COALESCE(NULLIF(u.tenant_id, ''), 'main') FROM users u WHERE u.id = NEW.created_by) "
    "OR (NEW.approved_by IS NOT NULL AND NEW.tenant_id IS NOT (SELECT COALESCE(NULLIF(u.tenant_id, ''), 'main') "
    "FROM users u WHERE u.id = NEW.approved_by)) "
    "BEGIN SELECT RAISE(ABORT, 'MANDATE_EVIDENCE_TENANT_MISMATCH'); END",
)
_SQLITE_TRIGGER_NAMES = (
    "trg_allocation_publication_decisions_no_replace",
    "trg_allocation_publication_decisions_sequence",
    "trg_allocation_publication_decisions_envelope",
    "trg_allocation_publication_decisions_no_update",
    "trg_allocation_publication_decisions_no_delete",
    "trg_allocation_active_publications_insert",
    "trg_allocation_active_publications_update",
    "trg_allocation_active_publications_no_delete",
    "trg_allocation_publication_decisions_tenant_guard",
    "trg_allocation_active_publications_tenant_guard",
    "trg_allocation_publication_decisions_binding_guard",
)

# PostgreSQL: dieselben Regeln als plpgsql (ein Guard je Tabelle). Unter RLS
# sieht die Mandats-/Envelope-/Entscheid-Abfrage nur den Mandanten der Session.
_PG_FUNCTIONS = (
    f"""CREATE OR REPLACE FUNCTION {DECISIONS}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text;
DECLARE expected integer;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION '{DECISIONS} is append-only';
  END IF;
  SELECT m.tenant_id INTO derived FROM mandates m WHERE m.id = NEW.mandate_id;
  IF derived IS NULL OR NEW.tenant_id IS DISTINCT FROM derived THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  SELECT COALESCE(MAX(d.publication_sequence), 0) + 1 INTO expected
    FROM {DECISIONS} d WHERE d.mandate_id = NEW.mandate_id;
  IF NEW.publication_sequence IS DISTINCT FROM expected THEN
    RAISE EXCEPTION 'CCX_PUBLICATION_RACE';
  END IF;
  IF (NEW.target_allocation_id IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM target_allocations t WHERE t.id = NEW.target_allocation_id AND t.mandate_id = NEW.mandate_id))
     OR NEW.tenant_id IS DISTINCT FROM (SELECT COALESCE(NULLIF(u.tenant_id, ''), 'main') FROM users u
       WHERE u.id = NEW.created_by)
     OR (NEW.approved_by IS NOT NULL AND NEW.tenant_id IS DISTINCT FROM (
       SELECT COALESCE(NULLIF(u.tenant_id, ''), 'main') FROM users u WHERE u.id = NEW.approved_by))
     OR (NEW.approval_mode = 'single_approver_attested' AND NOT EXISTS (
       SELECT 1 FROM tenants tn WHERE tn.id = NEW.tenant_id AND tn.single_person_firm = 1)) THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  IF NEW.publishable = 1 AND NOT EXISTS (
    SELECT 1 FROM {ENVELOPES} e WHERE e.id = NEW.envelope_id AND e.tenant_id = NEW.tenant_id
      AND e.mandate_id = NEW.mandate_id AND e.status = 'SEALED' AND e.freshness_status = 'FRESH'
      AND e.envelope_hash = NEW.published_envelope_hash
  ) THEN
    RAISE EXCEPTION 'CCX_ALLOCATION_NOT_PUBLISHABLE';
  END IF;
  RETURN NEW;
END $$""",
    f"""CREATE OR REPLACE FUNCTION {POINTER}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text;
DECLARE old_sequence integer;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION '{POINTER}: pointer is never deleted';
  END IF;
  IF TG_OP = 'INSERT' THEN
    SELECT m.tenant_id INTO derived FROM mandates m WHERE m.id = NEW.mandate_id;
    IF derived IS NULL OR NEW.tenant_id IS DISTINCT FROM derived THEN
      RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
    END IF;
    IF NEW.optimistic_version IS DISTINCT FROM 1 OR NOT EXISTS (
      SELECT 1 FROM {DECISIONS} d WHERE d.id = NEW.publication_id AND d.tenant_id = NEW.tenant_id
        AND d.mandate_id = NEW.mandate_id AND d.publishable = 1
    ) THEN
      RAISE EXCEPTION 'CCX_PUBLICATION_RACE';
    END IF;
    RETURN NEW;
  END IF;
  SELECT o.publication_sequence INTO old_sequence FROM {DECISIONS} o WHERE o.id = OLD.publication_id;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
     OR NEW.mandate_id IS DISTINCT FROM OLD.mandate_id
     OR NEW.optimistic_version IS DISTINCT FROM OLD.optimistic_version + 1
     OR NOT EXISTS (
       SELECT 1 FROM {DECISIONS} d WHERE d.id = NEW.publication_id AND d.tenant_id = NEW.tenant_id
         AND d.mandate_id = NEW.mandate_id AND d.publishable = 1 AND d.publication_sequence > old_sequence
     ) THEN
    RAISE EXCEPTION 'CCX_PUBLICATION_RACE';
  END IF;
  RETURN NEW;
END $$""",
)
_PG_TRIGGERS = tuple(
    f"CREATE TRIGGER trg_{table}_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} "
    f"FOR EACH ROW EXECUTE FUNCTION {table}_guard()"
    for table in (DECISIONS, POINTER)
)


def _dialect() -> str:
    if context.is_offline_mode():
        return context.get_context().dialect.name
    return op.get_bind().dialect.name


def upgrade() -> None:
    # N-910-02: Ein-Personen-Firma als ausdrueckliche Tenant-Einstellung.
    op.add_column("tenants", sa.Column("single_person_firm", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        DECISIONS,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("envelope_id", sa.String(), nullable=True),
        sa.Column("target_allocation_id", sa.String(), nullable=True),
        sa.Column("publication_sequence", sa.Integer(), nullable=False),
        sa.Column("validation_hash", sa.String(), nullable=False),
        sa.Column("approval_hash", sa.String(), nullable=True),
        sa.Column("approval_mode", sa.String(), nullable=True),
        sa.Column("approved_at", sa.String(), nullable=True),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("publishable", sa.Integer(), nullable=False),
        sa.Column("blocker_codes_json", sa.String(), nullable=False),
        sa.Column("published_envelope_hash", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("eligible_approver_count", sa.Integer(), nullable=True),
        sa.Column("single_person_firm", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "schema_version = 'ares/allocation-publication/1'",
            name="ck_allocation_publication_decisions_schema_version",
        ),
        sa.CheckConstraint("publication_sequence >= 1", name="ck_allocation_publication_decisions_sequence_min"),
        sa.CheckConstraint("length(validation_hash) = 64", name="ck_allocation_publication_decisions_validation"),
        sa.CheckConstraint(
            "approval_hash IS NULL OR length(approval_hash) = 64",
            name="ck_allocation_publication_decisions_approval",
        ),
        sa.CheckConstraint(
            "approval_mode IS NULL OR approval_mode IN ('four_eyes','single_approver_attested')",
            name="ck_allocation_publication_decisions_mode",
        ),
        sa.CheckConstraint("publishable IN (0, 1)", name="ck_allocation_publication_decisions_flag"),
        sa.CheckConstraint(
            "published_envelope_hash IS NULL OR length(published_envelope_hash) = 64",
            name="ck_allocation_publication_decisions_envelope_hash",
        ),
        sa.CheckConstraint(
            "publishable = 0 OR (envelope_id IS NOT NULL AND target_allocation_id IS NOT NULL "
            "AND approval_hash IS NOT NULL AND approval_mode IS NOT NULL AND approved_at IS NOT NULL "
            "AND approved_by IS NOT NULL AND published_envelope_hash IS NOT NULL "
            "AND blocker_codes_json = '[]' "
            "AND eligible_approver_count IS NOT NULL AND single_person_firm IS NOT NULL)",
            name="ck_allocation_publication_decisions_published",
        ),
        sa.CheckConstraint(
            "eligible_approver_count IS NULL OR eligible_approver_count >= 0",
            name="ck_allocation_publication_decisions_approver_count",
        ),
        sa.CheckConstraint(
            "single_person_firm IS NULL OR single_person_firm IN (0, 1)",
            name="ck_allocation_publication_decisions_single_flag",
        ),
        sa.CheckConstraint(
            "approval_mode IS NULL OR approval_mode <> 'single_approver_attested' "
            "OR (single_person_firm = 1 AND eligible_approver_count = 1)",
            name="ck_allocation_publication_decisions_single",
        ),
        sa.CheckConstraint(
            "publishable = 1 OR (published_envelope_hash IS NULL AND approval_hash IS NULL "
            "AND blocker_codes_json <> '[]')",
            name="ck_allocation_publication_decisions_blocked",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["target_allocation_id"], ["target_allocations.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "envelope_id"], [f"{ENVELOPES}.tenant_id", f"{ENVELOPES}.id"],
            name="fk_allocation_publication_decisions_envelope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_allocation_publication_decisions_tenant_id"),
        sa.UniqueConstraint(
            "mandate_id", "publication_sequence", name="uq_allocation_publication_decisions_sequence",
        ),
    )
    op.create_index("ix_allocation_publication_decisions_tenant_id", DECISIONS, ["tenant_id"])
    op.create_index("ix_allocation_publication_decisions_mandate", DECISIONS, ["tenant_id", "mandate_id"])
    op.create_index(
        "ux_allocation_publication_decisions_one_per_envelope", DECISIONS, ["envelope_id"], unique=True,
        sqlite_where=sa.text("publishable = 1"), postgresql_where=sa.text("publishable = 1"),
    )

    op.create_table(
        POINTER,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("publication_id", sa.String(), nullable=False),
        sa.Column("optimistic_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=False),
        sa.CheckConstraint("optimistic_version >= 1", name="ck_allocation_active_publications_version"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "publication_id"], [f"{DECISIONS}.tenant_id", f"{DECISIONS}.id"],
            name="fk_allocation_active_publications_publication",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mandate_id", name="uq_allocation_active_publications_mandate"),
    )
    op.create_index("ix_allocation_active_publications_tenant_id", POINTER, ["tenant_id"])

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
        for table in (POINTER, DECISIONS):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_guard ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_guard()")
    elif dialect == "sqlite":
        for name in _SQLITE_TRIGGER_NAMES:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("ix_allocation_active_publications_tenant_id", table_name=POINTER)
    op.drop_table(POINTER)
    op.drop_index("ux_allocation_publication_decisions_one_per_envelope", table_name=DECISIONS)
    op.drop_index("ix_allocation_publication_decisions_mandate", table_name=DECISIONS)
    op.drop_index("ix_allocation_publication_decisions_tenant_id", table_name=DECISIONS)
    op.drop_table(DECISIONS)
    op.drop_column("tenants", "single_person_firm")
