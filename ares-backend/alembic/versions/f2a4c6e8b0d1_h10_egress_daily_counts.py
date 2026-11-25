"""H10 Nachtrag 3: Zaehler erlaubter Uebertragungen je Kanal und Tag.

``privacy_egress_daily_counts`` (tenant_id direkt, RLS beim Boot): nur Tag,
Kanal-ID und Anzahl -- kein Inhalt, keine Ziel-URL, kein Payload. Eindeutig
je ``(tenant_id, day, channel_id)``. Neue Tabelle, kein Backfill.

Revision ID: f2a4c6e8b0d1
Revises: e8f1b3c5a7d9
Create Date: 2026-11-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f2a4c6e8b0d1"
down_revision: Union[str, Sequence[str], None] = "e8f1b3c5a7d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "privacy_egress_daily_counts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("day", sa.String(), nullable=False),
        sa.Column("channel_id", sa.String(), nullable=False),
        sa.Column("allowed_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.UniqueConstraint("tenant_id", "day", "channel_id", name="uq_privacy_egress_daily_count"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("privacy_egress_daily_counts")
