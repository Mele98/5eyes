"""recommendation_runs.sustainability_evidence_json (E2b Nachtrag 1).

Belege der Produktauswahl fuer die Kundenausschluesse der Nachhaltigkeits-
praeferenz: decision_hash, Themen, Stichtag und die Nachweis-ID je gewaehlter
Position. Kunden-PDFs, Protokoll und Handoff pruefen damit ohne neue
Kopplung, ob der Ausschluss am Produkt belegt umgesetzt ist. Nur nullable
ADD COLUMN, kein Backfill (Altlauf = nicht belegt). Gleiche Spalte wie
database.py (SQLite-Laufzeitpatch).

Revision ID: e7b3d9f1a2c4
Revises: c4e8a2f6b9d1
Create Date: 2026-11-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e7b3d9f1a2c4"
down_revision: Union[str, Sequence[str], None] = "c4e8a2f6b9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("recommendation_runs", sa.Column("sustainability_evidence_json", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("recommendation_runs", "sustainability_evidence_json")
