"""CCX-P5 Kanal-Envelope (Vertrag 2026-11-13 §8).

Neue append-only Tabelle ``advisory_channel_publications`` (kein Backfill --
Bestand hat keine Kanalzeile und wird nie als ausgeliefert markiert): je
ausgeliefertem Artefakt eines versiegelten Beratungsentscheids eine Zeile mit
``bound_envelope_hash``, ``channel_payload_hash``, ``render_hash``,
``parameter_set_hash`` (M-2) und ``goal_metric_payload_hash`` (M-3). Eine Zeile
entsteht nur fuer einen SEALED-Envelope desselben Mandanten/Mandats mit genau
diesem Hash; Updates und Deletes sind verboten.

Mandantengebunden (INSERT-Guard aus Mandat und Ersteller; RLS ENABLE + FORCE
folgen beim Boot ueber ``ensure_postgres_rls_policies``). Gleiche DDL wie
database.py (SQLite-Laufzeitpatch) und ares_schema.sql.

Platz ``CCX_P5_REV``; lineare Kette ... P4 ``24e7606245d3`` -> H12
``b3f1c9d2e4a7`` -> K1 ``63332bb56098`` -> P5 (diese Revision).

Revision ID: c2546c196134
Revises: 63332bb56098
Create Date: 2026-11-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "c2546c196134"
down_revision: Union[str, Sequence[str], None] = "63332bb56098"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "advisory_channel_publications"
ENVELOPES = "advisory_decision_envelopes"
TENANT_ERROR = "MANDATE_EVIDENCE_TENANT_MISMATCH"
CHANNELS = "'API','CLASSIC','REACT','PDF','ADVISOR_SIGNATURE','ONSITE_SIGNATURE','HANDOFF','ARCHIVE'"
RENDER_CHANNELS = "'PDF','ARCHIVE','ADVISOR_SIGNATURE','ONSITE_SIGNATURE'"

# SQLite: textgleich database.py CHANNEL_PUBLICATION_SQLITE_TRIGGERS +
# CHANNEL_PUBLICATION_SQLITE_TENANT_GUARDS (eingefroren).
_SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_channel_publications_envelope "
    "BEFORE INSERT ON advisory_channel_publications FOR EACH ROW "
    "WHEN NOT EXISTS (SELECT 1 FROM advisory_decision_envelopes e WHERE e.id = NEW.envelope_id "
    "AND e.tenant_id = NEW.tenant_id AND e.mandate_id = NEW.mandate_id AND e.status = 'SEALED' "
    "AND e.envelope_hash = NEW.bound_envelope_hash) "
    "BEGIN SELECT RAISE(ABORT, 'CCX_CHANNEL_BINDING_MISSING'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_channel_publications_no_update "
    "BEFORE UPDATE ON advisory_channel_publications FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'advisory_channel_publications is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_channel_publications_no_delete "
    "BEFORE DELETE ON advisory_channel_publications FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'advisory_channel_publications is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_channel_publications_tenant_guard "
    "BEFORE INSERT ON advisory_channel_publications FOR EACH ROW "
    "WHEN NEW.tenant_id IS NOT (SELECT m.tenant_id FROM mandates m WHERE m.id = NEW.mandate_id) "
    "OR NEW.tenant_id IS NOT (SELECT COALESCE(NULLIF(u.tenant_id, ''), 'main') FROM users u WHERE u.id = NEW.created_by) "
    "BEGIN SELECT RAISE(ABORT, 'MANDATE_EVIDENCE_TENANT_MISMATCH'); END",
)
_SQLITE_TRIGGER_NAMES = (
    "trg_advisory_channel_publications_envelope",
    "trg_advisory_channel_publications_no_update",
    "trg_advisory_channel_publications_no_delete",
    "trg_advisory_channel_publications_tenant_guard",
)

# PostgreSQL: dieselben Regeln als plpgsql. Unter RLS sieht die Mandats-/
# Envelope-Abfrage nur den Mandanten der Session.
_PG_FUNCTIONS = (
    f"""CREATE OR REPLACE FUNCTION {TABLE}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION '{TABLE} is append-only';
  END IF;
  SELECT m.tenant_id INTO derived FROM mandates m WHERE m.id = NEW.mandate_id;
  IF derived IS NULL OR NEW.tenant_id IS DISTINCT FROM derived
     OR NEW.tenant_id IS DISTINCT FROM (SELECT COALESCE(NULLIF(u.tenant_id, ''), 'main') FROM users u
       WHERE u.id = NEW.created_by) THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM {ENVELOPES} e WHERE e.id = NEW.envelope_id AND e.tenant_id = NEW.tenant_id
      AND e.mandate_id = NEW.mandate_id AND e.status = 'SEALED' AND e.envelope_hash = NEW.bound_envelope_hash
  ) THEN
    RAISE EXCEPTION 'CCX_CHANNEL_BINDING_MISSING';
  END IF;
  RETURN NEW;
END $$""",
)
_PG_TRIGGERS = (
    f"CREATE TRIGGER trg_{TABLE}_guard BEFORE INSERT OR UPDATE OR DELETE ON {TABLE} "
    f"FOR EACH ROW EXECUTE FUNCTION {TABLE}_guard()",
)


def _dialect() -> str:
    if context.is_offline_mode():
        return context.get_context().dialect.name
    return op.get_bind().dialect.name


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("envelope_id", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("channel_payload_hash", sa.String(), nullable=False),
        sa.Column("render_hash", sa.String(), nullable=True),
        sa.Column("rounding_policy_version", sa.String(), nullable=False),
        sa.Column("bound_envelope_hash", sa.String(), nullable=False),
        sa.Column("parameter_contract_version", sa.String(), nullable=False),
        sa.Column("parameter_set_hash", sa.String(), nullable=False),
        sa.Column("goal_metric_contract_version", sa.String(), nullable=False),
        sa.Column("goal_metric_payload_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.CheckConstraint(f"channel IN ({CHANNELS})", name="ck_advisory_channel_publications_channel"),
        sa.CheckConstraint("schema_version = 'ares/channel-publication/1'",
                           name="ck_advisory_channel_publications_schema_version"),
        sa.CheckConstraint("length(channel_payload_hash) = 64", name="ck_advisory_channel_publications_payload"),
        sa.CheckConstraint("render_hash IS NULL OR length(render_hash) = 64",
                           name="ck_advisory_channel_publications_render_hash"),
        sa.CheckConstraint("length(bound_envelope_hash) = 64",
                           name="ck_advisory_channel_publications_envelope_hash"),
        sa.CheckConstraint("length(parameter_set_hash) = 64", name="ck_advisory_channel_publications_parameter"),
        sa.CheckConstraint("length(goal_metric_payload_hash) = 64", name="ck_advisory_channel_publications_goal"),
        sa.CheckConstraint("status = 'PUBLISHED'", name="ck_advisory_channel_publications_status"),
        sa.CheckConstraint(f"channel NOT IN ({RENDER_CHANNELS}) OR render_hash IS NOT NULL",
                           name="ck_advisory_channel_publications_render"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "envelope_id"], [f"{ENVELOPES}.tenant_id", f"{ENVELOPES}.id"],
            name="fk_advisory_channel_publications_envelope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_advisory_channel_publications_tenant_id"),
        sa.UniqueConstraint("envelope_id", "channel", "artifact_id",
                            name="uq_advisory_channel_publications_artifact"),
    )
    op.create_index("ix_advisory_channel_publications_tenant_id", TABLE, ["tenant_id"])
    op.create_index("ix_advisory_channel_publications_mandate", TABLE, ["tenant_id", "mandate_id"])
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
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_guard ON {TABLE}")
        op.execute(f"DROP FUNCTION IF EXISTS {TABLE}_guard()")
    elif dialect == "sqlite":
        for name in _SQLITE_TRIGGER_NAMES:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("ix_advisory_channel_publications_mandate", table_name=TABLE)
    op.drop_index("ix_advisory_channel_publications_tenant_id", table_name=TABLE)
    op.drop_table(TABLE)
