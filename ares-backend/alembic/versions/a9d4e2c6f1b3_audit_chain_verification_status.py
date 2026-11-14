"""audit_chain_verification_status: sichtbarer Status der Audit-Kettenpruefung.

F6 (Codex-Entscheid Runde 3, 2026-11-07): Die synchrone Startpruefung der
Audit-Kette ist auf ``audit_startup_check_max_rows`` begrenzt. Darueber laeuft
die Vollpruefung chunked im Hintergrund; Fortschritt und letzter erfolgreich
gepruefter Kettenkopf werden in dieser Singleton-Tabelle persistiert, bis zum
Erfolg gilt die Integritaet als nicht bestaetigt.

system_only: keine tenant_id, keine RLS-Policy (wie
audit_log_sequence_counter). Inhalt nur Zaehler, Sequenznummern, Ketten-Hashes
und Zeitpunkte. Gleiche Spalten wie ``database.py::
_AUDIT_CHAIN_VERIFICATION_STATUS_SQL`` (SQLite-Pfad).

Downgrade entfernt die Tabelle (der Status wird beim naechsten Start neu
geschrieben).

Revision ID: a9d4e2c6f1b3
Revises: d8e4b2a6c1f9
Create Date: 2026-11-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a9d4e2c6f1b3"
down_revision: Union[str, Sequence[str], None] = "d8e4b2a6c1f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_chain_verification_status",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("total_rows", sa.Integer()),
        sa.Column("threshold", sa.Integer()),
        sa.Column("target_sequence", sa.Integer()),
        sa.Column("verified_through_sequence", sa.Integer()),
        sa.Column("checked", sa.Integer()),
        sa.Column("finding_count", sa.Integer()),
        sa.Column("last_ok_sequence", sa.Integer()),
        sa.Column("last_ok_hash", sa.String(length=64)),
        sa.Column("last_ok_at", sa.String()),
        sa.Column("started_at", sa.String()),
        sa.Column("updated_at", sa.String()),
        sa.Column("finished_at", sa.String()),
        sa.Column("detail_json", sa.String()),
    )


def downgrade() -> None:
    op.drop_table("audit_chain_verification_status")
