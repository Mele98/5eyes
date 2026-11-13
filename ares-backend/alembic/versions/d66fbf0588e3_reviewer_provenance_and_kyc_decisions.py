"""C-890-01 Nachtrag 3: Herkunft von Freigeberkonten, ein Entscheid je KYC-Bestaetigung.

- ``users``: neun nullable Spalten (N-897-02) -- ``credentials_set_by`` /
  ``credentials_set_at`` und ``totp_set_by`` / ``totp_set_at`` ("self" oder
  Admin-ID), ``invited_by`` / ``invited_at`` / ``activated_at`` und die
  Identitaet externer Compliance-Personen (``reviewer_organisation``,
  ``reviewer_reference``; Name = ``full_name``). Kein Backfill: Bestandskonten
  haben eine unbekannte Herkunft und zaehlen als Freigeber der Rolle
  compliance_reviewer nicht.
- Nachtrag 4 (N-897-13, Revision vor Veroeffentlichung erweitert): ``users``
  zusaetzlich ``compromised_since/_at/_by`` und ``compromise_reason``
  (auditierter Widerruf wegen Kompromittierung); ``kyc_confirmation_decisions``
  mit ``approver_ready`` (Bereitschaft zum Entscheidzeitpunkt eingefroren) und
  Siegel ``decision_hash``; ``kyc_review_policy_activations.approver_ready``
  (nullable, Teil des Aktivierungssiegels).
- ``kyc_confirmation_decisions`` (N-897-08): eigene ``id``, UNIQUE
  ``confirmation_id`` -- genau ein Entscheid (Freigabe oder Ablehnung) je
  Bestaetigung, append-only (Trigger SQLite/PG).

SQLite: create_all + database.ensure_runtime_columns.
Downgrade fail-closed, sobald ein Entscheid oder eine Konto-Herkunft vorliegt.

Revision ID: d66fbf0588e3
Revises: a7d3c9e1f5b2
Create Date: 2026-11-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d66fbf0588e3"
down_revision: Union[str, Sequence[str], None] = "a7d3c9e1f5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USER_COLUMNS = ('credentials_set_by', 'credentials_set_at', 'totp_set_by', 'totp_set_at', 'invited_by', 'invited_at', 'activated_at', 'reviewer_organisation', 'reviewer_reference', 'compromised_since', 'compromised_at', 'compromised_by', 'compromise_reason')
TABLE = "kyc_confirmation_decisions"


def upgrade() -> None:
    for name in USER_COLUMNS:
        op.add_column("users", sa.Column(name, sa.String(), nullable=True))
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("confirmation_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("decided_by", sa.String(), nullable=False),
        sa.Column("decided_at", sa.String(), nullable=False),
        sa.Column("record_id", sa.String(), nullable=False),
        sa.Column("approver_ready", sa.Integer(), nullable=False),
        sa.Column("decision_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("confirmation_id"),
    )
    op.add_column("kyc_review_policy_activations", sa.Column("approver_ready", sa.Integer(), nullable=True))
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for kind in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_no_{kind.lower()} BEFORE {kind} ON {TABLE} "
                f"FOR EACH ROW BEGIN SELECT RAISE(ABORT, '{TABLE} is immutable'); END"
            )
    elif dialect == "postgresql":
        op.execute(
            f"CREATE OR REPLACE FUNCTION {TABLE}_immutable() RETURNS trigger AS $$\n"
            "BEGIN\n"
            f"    RAISE EXCEPTION '{TABLE} is immutable';\n"
            "END;\n"
            "$$ LANGUAGE plpgsql"
        )
        op.execute(
            f"CREATE TRIGGER trg_{TABLE}_immutable BEFORE UPDATE OR DELETE ON {TABLE} "
            f"FOR EACH ROW EXECUTE FUNCTION {TABLE}_immutable()"
        )


def downgrade() -> None:
    bind = op.get_bind()
    used = bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar() or bind.execute(sa.text(
        "SELECT COUNT(*) FROM users WHERE " + " OR ".join(f"{c} IS NOT NULL" for c in USER_COLUMNS)
    )).scalar()
    if used:
        raise RuntimeError(
            "C-890-01 Nachtrag 3 Downgrade abgelehnt (fail-closed): Entscheide bzw. "
            "Herkunftsnachweise von Freigeberkonten wuerden vernichtet."
        )
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_immutable ON {TABLE}")
        op.execute(f"DROP FUNCTION IF EXISTS {TABLE}_immutable()")
    elif dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_delete")
    op.drop_table(TABLE)
    with op.batch_alter_table("kyc_review_policy_activations") as batch:
        batch.drop_column("approver_ready")
    if dialect == "sqlite":
        # batch_alter_table baut die Tabelle neu -- Append-only-Trigger wieder anlegen.
        for kind in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER IF NOT EXISTS trg_kyc_review_policy_activations_no_{kind.lower()} "
                f"BEFORE {kind} ON kyc_review_policy_activations FOR EACH ROW "
                "BEGIN SELECT RAISE(ABORT, 'kyc_review_policy_activations is immutable'); END"
            )
    with op.batch_alter_table("users") as batch:
        for name in reversed(USER_COLUMNS):
            batch.drop_column(name)
