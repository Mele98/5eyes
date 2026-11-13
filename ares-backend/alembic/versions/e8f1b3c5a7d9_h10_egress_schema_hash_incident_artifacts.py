"""H10 Nachtrag 2 (Codex-Pruefung H-154, C-900-02/03).

- ``privacy_egress_events``: zusaetzlich ``manifest_sha256`` und
  ``payload_schema_hash`` (Form des blockierten Payloads, nie Werte).
- ``privacy_security_incident_artifacts``: Nachweis-Artefakte mit Digest,
  Medientyp, Groesse, Erfassungszeit, Zeilensiegel und Bindung an das
  Ereignis der Fallkette; append-only per Trigger (SQLite und PostgreSQL),
  tenant_id direkt (RLS beim Boot), ohne FK. Kein Backfill.

Revision ID: e8f1b3c5a7d9
Revises: c4e8a2f6d0b7
Create Date: 2026-11-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e8f1b3c5a7d9"
down_revision: Union[str, Sequence[str], None] = "c4e8a2f6d0b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ARTIFACTS = "privacy_security_incident_artifacts"


def upgrade() -> None:
    with op.batch_alter_table("privacy_egress_events") as batch:
        batch.add_column(sa.Column("manifest_sha256", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("payload_schema_hash", sa.String(length=64), nullable=True))
    op.create_table(
        ARTIFACTS,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("incident_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("recorded_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.String(), nullable=False),
        sa.Column("event_sha256", sa.String(length=64), nullable=True),
        sa.Column("row_sha256", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_privacy_security_incident_artifacts_incident", ARTIFACTS, ["tenant_id", "incident_id"])
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for verb in ("update", "delete"):
            op.execute(
                f"CREATE TRIGGER IF NOT EXISTS trg_{ARTIFACTS}_no_{verb} BEFORE {verb.upper()} ON {ARTIFACTS} "
                f"FOR EACH ROW BEGIN SELECT RAISE(ABORT, '{ARTIFACTS} is immutable'); END"
            )
    elif dialect == "postgresql":
        op.execute(
            f"CREATE OR REPLACE FUNCTION {ARTIFACTS}_immutable() RETURNS trigger AS $$\n"
            f"BEGIN\n    RAISE EXCEPTION '{ARTIFACTS} is immutable';\nEND;\n$$ LANGUAGE plpgsql"
        )
        op.execute(
            f"CREATE TRIGGER trg_{ARTIFACTS}_immutable BEFORE UPDATE OR DELETE ON {ARTIFACTS} "
            f"FOR EACH ROW EXECUTE FUNCTION {ARTIFACTS}_immutable()"
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS trg_{ARTIFACTS}_immutable ON {ARTIFACTS}")
        op.execute(f"DROP FUNCTION IF EXISTS {ARTIFACTS}_immutable()")
    elif dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS trg_{ARTIFACTS}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{ARTIFACTS}_no_delete")
    op.drop_index("ix_privacy_security_incident_artifacts_incident", table_name=ARTIFACTS)
    op.drop_table(ARTIFACTS)
    with op.batch_alter_table("privacy_egress_events") as batch:
        batch.drop_column("payload_schema_hash")
        batch.drop_column("manifest_sha256")
