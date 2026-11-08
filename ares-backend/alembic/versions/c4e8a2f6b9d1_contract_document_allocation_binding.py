"""contract_documents: Bindung an die Soll-Allokation (N-888-09).

ESG E3 Pruefrunde 4287cca8 (Dok. 86): ein archiviertes Empfehlungsdokument
(Anlagestrategie, Anlagerezept, Beratungsprotokoll, Kostenausweis) traegt die
ID der Soll-Allokation und den SHA-256 ihres Praeferenz-Snapshots. Signatur
und Vor-Ort-Signatur pruefen genau diesen Inhalt gegen die aktuelle
Nachhaltigkeitspraeferenz; ein Dokument ohne Bindung ist fail-closed nicht
signierbar, sobald wirksame Kundenausschluesse bestehen.

Nur nullable ADD COLUMN, kein Backfill (Altbestand = ungebunden). Gleiche
Spalten wie database.py (SQLite-Laufzeitpatch).

Revision ID: c4e8a2f6b9d1
Revises: f3a8c1e5b7d2
Create Date: 2026-11-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4e8a2f6b9d1"
down_revision: Union[str, Sequence[str], None] = "f3a8c1e5b7d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ("bound_target_allocation_id", "bound_preferences_sha256")


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column("contract_documents", sa.Column(column, sa.String(), nullable=True))


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column("contract_documents", column)
