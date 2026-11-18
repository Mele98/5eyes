"""C-890-01 Nachtrag 2: begruendete Ablehnung der KYC-Zweitfreigabe.

Die H8-Vier-Augen-Freigabe (PEP, erhoehtes Risiko, Herabstufung,
PEP-Ruecknahme) kann jetzt auch die externe Compliance-Person (Rolle
``compliance_reviewer``) erteilen -- oder begruendet ablehnen. Die Ablehnung
ist ein eigener, append-only Nachweis:

- ``kyc_confirmation_rejections``: Bestaetigung (UNIQUE), Kunde, Mandant,
  ablehnende Person, Zeitpunkt, Begruendung, gesehener Siegel-Hash der
  Bestaetigung, eigenes Siegel. Trigger (SQLite/PG): unveraenderlich; nur die
  Begruendung darf im DSG-Loeschvorgang auf den Redaktionsmarker gesetzt
  werden (gleiche Regel wie ``kyc_confirmation_approvals.note``).

SQLite legt die Tabelle ueber create_all an (models/clients.py, Trigger
database.py::KYC_CONFIRMATION_REJECTION_SQLITE_TRIGGERS).

Downgrade fail-closed: liegt eine Ablehnung vor, bricht er ab (Evidenz).

Revision ID: a7d3c9e1f5b2
Revises: f4c2e8a6d1b3
Create Date: 2026-11-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a7d3c9e1f5b2"
down_revision: Union[str, Sequence[str], None] = "f4c2e8a6d1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "kyc_confirmation_rejections"
REDACTION_MARKER = "[ERASED-DSG-ART-32]"
FIXED = ("id", "tenant_id", "confirmation_id", "client_id", "rejected_by", "rejected_at",
         "confirmation_hash", "rejection_hash")
REDACTABLE = ("reason",)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("confirmation_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("rejected_by", sa.String(), nullable=False),
        sa.Column("rejected_at", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("confirmation_hash", sa.String(), nullable=False),
        sa.Column("rejection_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["rejected_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("confirmation_id"),
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        changed = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in FIXED)
        bad = " OR ".join(
            f"(NEW.{c} IS NOT OLD.{c} AND NEW.{c} IS NOT NULL AND NEW.{c} != '{REDACTION_MARKER}')"
            for c in REDACTABLE
        )
        op.execute(
            f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_no_update BEFORE UPDATE ON {TABLE} "
            f"FOR EACH ROW WHEN {changed} OR {bad} "
            f"BEGIN SELECT RAISE(ABORT, '{TABLE} is immutable'); END"
        )
        op.execute(
            f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_no_delete BEFORE DELETE ON {TABLE} "
            f"FOR EACH ROW BEGIN SELECT RAISE(ABORT, '{TABLE} is immutable'); END"
        )
    elif dialect == "postgresql":
        changed = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in FIXED)
        bad = " OR ".join(
            f"(NEW.{c} IS DISTINCT FROM OLD.{c} AND NEW.{c} IS NOT NULL AND NEW.{c} <> '{REDACTION_MARKER}')"
            for c in REDACTABLE
        )
        op.execute(
            f"CREATE OR REPLACE FUNCTION {TABLE}_immutable() RETURNS trigger AS $$\n"
            "BEGIN\n"
            "    IF TG_OP = 'DELETE' THEN\n"
            f"        RAISE EXCEPTION '{TABLE} is immutable';\n"
            "    END IF;\n"
            "    IF " + changed + " OR " + bad + " THEN\n"
            f"        RAISE EXCEPTION '{TABLE} is immutable';\n"
            "    END IF;\n"
            "    RETURN NEW;\n"
            "END;\n"
            "$$ LANGUAGE plpgsql"
        )
        op.execute(
            f"CREATE TRIGGER trg_{TABLE}_immutable BEFORE UPDATE OR DELETE ON {TABLE} "
            f"FOR EACH ROW EXECUTE FUNCTION {TABLE}_immutable()"
        )


def downgrade() -> None:
    if op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar():
        raise RuntimeError(
            "C-890-01 Nachtrag 2 Downgrade abgelehnt (fail-closed): vorhandene "
            "Ablehnungen von KYC-Zweitfreigaben wuerden vernichtet."
        )
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_immutable ON {TABLE}")
        op.execute(f"DROP FUNCTION IF EXISTS {TABLE}_immutable()")
    elif dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_delete")
    op.drop_table(TABLE)
