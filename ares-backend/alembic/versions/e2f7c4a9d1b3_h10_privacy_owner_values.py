"""H10 C-DSG-01: Angaben des Verantwortlichen zum Bearbeitungsverzeichnis.

DSG-Technikaudit 2026-11-11, Befund C-DSG-01 (mit C-DSG-05/06 als
Owner-Angaben): ``privacy_owner_values`` haelt je Mandant und Owner-Feld des
Registers (``config/processing_activities.json``) die bestaetigte Angabe der
Firma, versioniert (neue Zeile je Aenderung, bisherige ``RETIRED``). Keine
Vorbelegung, kein Backfill. ``tenant_id`` direkt (RLS ENABLE + FORCE und die
strikte Policy folgen beim Boot ueber ``ensure_postgres_rls_policies``).
Kein FK auf users (Purge-fest, wie die PRIVACY-001-Tabellen). SQLite legt
die Tabelle ueber create_all an (Modell in models/privacy.py).

Revision ID: e2f7c4a9d1b3
Revises: d8e4b2a6c1f9
Create Date: 2026-11-11
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e2f7c4a9d1b3"
down_revision: Union[str, Sequence[str], None] = "d8e4b2a6c1f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "privacy_owner_values",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("field_key", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("value_sha256", sa.String(length=64), nullable=False),
        sa.Column("confirmed_by", sa.String(), nullable=False),
        sa.Column("confirmed_at", sa.String(), nullable=False),
        sa.Column("retired_at", sa.String(), nullable=True),
        sa.CheckConstraint("status IN ('CONFIRMED','RETIRED')", name="ck_privacy_owner_value_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_privacy_owner_values_lookup", "privacy_owner_values", ["tenant_id", "field_key", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_privacy_owner_values_lookup", table_name="privacy_owner_values")
    op.drop_table("privacy_owner_values")
