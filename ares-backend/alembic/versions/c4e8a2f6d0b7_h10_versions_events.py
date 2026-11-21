"""H10 Nachtrag 1 (Codex-Vertrag 2026-11-12): versionierte Freigaben,
append-only Ereignisse, persistentes Egress-Protokoll, optimistische Sperre.

- ``processing_activity_versions`` / ``outbound_processing_manifest_versions``:
  Fassungen je Mandant und Bearbeitung bzw. Kanal (Status
  INVENTORY_REQUIRED/APPROVED, Content-Hash, gueltig ab; eindeutig je
  ``(tenant_id, schluessel, valid_from)``). Kein Backfill: der Bestand wird
  beim Start als INVENTORY_REQUIRED erfasst, nie als genehmigt.
- ``privacy_egress_events``: blockierte Verbindungen ohne Payload.
- ``privacy_subject_request_events`` / ``privacy_security_incident_events``:
  verkettete Ereignisse, ``(case_id, sequence)`` eindeutig.
- ``row_version`` auf ``privacy_subject_requests`` und
  ``privacy_security_incidents`` (optimistische Sperre).

Alle neuen Tabellen append-only per Trigger (SQLite und PostgreSQL), tenant_id
direkt (RLS beim Boot), ohne FK.

Revision ID: c4e8a2f6d0b7
Revises: a7c3e9f1b5d2
Create Date: 2026-11-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4e8a2f6d0b7"
down_revision: Union[str, Sequence[str], None] = "a7c3e9f1b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPEND_ONLY_TABLES = (
    "processing_activity_versions",
    "outbound_processing_manifest_versions",
    "privacy_egress_events",
    "privacy_subject_request_events",
    "privacy_security_incident_events",
)
VERSIONED_CASE_TABLES = ("privacy_subject_requests", "privacy_security_incidents")


def _sqlite_triggers(table: str) -> tuple[str, str]:
    return (
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update "
        f"BEFORE UPDATE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete "
        f"BEFORE DELETE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
    )


def upgrade() -> None:
    for table in VERSIONED_CASE_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("row_version", sa.Integer(), server_default="1", nullable=False))
    op.create_table(
        "processing_activity_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("activity_key", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("register_version", sa.String(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("valid_from", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approved_at", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'activity_key', 'valid_from', name="uq_processing_activity_version_valid_from"),
        sa.CheckConstraint("status IN ('INVENTORY_REQUIRED','APPROVED')", name="ck_processing_activity_version_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_processing_activity_versions_key", "processing_activity_versions", ['tenant_id', 'activity_key', 'valid_from'])
    op.create_table(
        "outbound_processing_manifest_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("manifest_version", sa.String(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("valid_from", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approved_at", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'channel_id', 'valid_from', name="uq_outbound_manifest_version_valid_from"),
        sa.CheckConstraint("status IN ('INVENTORY_REQUIRED','APPROVED')", name="ck_outbound_manifest_version_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbound_manifest_versions_key", "outbound_processing_manifest_versions", ['tenant_id', 'channel_id', 'valid_from'])
    op.create_table(
        "privacy_egress_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("occurred_at", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=True),
        sa.Column("channel_class", sa.String(), nullable=True),
        sa.Column("destination_host", sa.String(), nullable=False),
        sa.Column("reason_code", sa.String(), nullable=False),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("manifest_version", sa.String(), nullable=True),
        sa.Column("channel_sha256", sa.String(length=64), nullable=True),
        sa.CheckConstraint("result IN ('BLOCKED')", name="ck_privacy_egress_event_result"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_privacy_egress_events_time", "privacy_egress_events", ['tenant_id', 'occurred_at'])
    op.create_table(
        "privacy_subject_request_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("previous_sha256", sa.String(length=64), nullable=True),
        sa.Column("event_sha256", sa.String(length=64), nullable=False),
        sa.UniqueConstraint('case_id', 'sequence', name="uq_privacy_subject_request_event_sequence"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_privacy_subject_request_events_case", "privacy_subject_request_events", ['tenant_id', 'case_id'])
    op.create_table(
        "privacy_security_incident_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("previous_sha256", sa.String(length=64), nullable=True),
        sa.Column("event_sha256", sa.String(length=64), nullable=False),
        sa.UniqueConstraint('case_id', 'sequence', name="uq_privacy_security_incident_event_sequence"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_privacy_security_incident_events_case", "privacy_security_incident_events", ['tenant_id', 'case_id'])
    dialect = op.get_bind().dialect.name
    for table in APPEND_ONLY_TABLES:
        if dialect == "sqlite":
            for ddl in _sqlite_triggers(table):
                op.execute(ddl)
        elif dialect == "postgresql":
            op.execute(
                f"CREATE OR REPLACE FUNCTION {table}_immutable() RETURNS trigger AS $$\n"
                f"BEGIN\n    RAISE EXCEPTION '{table} is immutable';\nEND;\n$$ LANGUAGE plpgsql"
            )
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION {table}_immutable()"
            )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    for table in reversed(APPEND_ONLY_TABLES):
        if dialect == "postgresql":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
        elif dialect == "sqlite":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
        op.drop_table(table)
    for table in VERSIONED_CASE_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("row_version")
