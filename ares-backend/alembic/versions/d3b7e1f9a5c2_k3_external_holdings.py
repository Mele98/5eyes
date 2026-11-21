"""K3 Bestand ausserhalb der Empfehlung (N-915-06): Fremdbestand am Depot.

Neue Spalte ``wealth_positions.external_holdings_json`` (TEXT, NULL). Sie haelt
die Titel eines erfassten Wertschriftendepots (Beratungsvermoegen), die nicht in
der Empfehlung stehen: Bezeichnung, optional ISIN, Anlageklasse, Waehrung,
Marktwert und Stichtag. NULL = keine Fremdtitel erfasst. Kein Backfill -- ein
Bestand wird nie angenommen.

Die Spalte gehoert zur bestehenden Tabelle ``wealth_positions``: Mandanten-,
Loesch- und Exportinventar sowie der Freshness-Hook (Abhaengigkeit
``positions``) decken sie ohne weitere Aenderung ab. Gleiche DDL wie
database.py (SQLite-Laufzeitpatch) und ares_schema.sql.

Downgrade entfernt die Spalte (erfasste Fremdtitel entfallen -- vorher
exportieren).

Lineare Kette ... H-179 ``c7e1a9d3f5b2`` -> K3 (diese Revision).

Revision ID: d3b7e1f9a5c2
Revises: c7e1a9d3f5b2
Create Date: 2026-11-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d3b7e1f9a5c2"
down_revision: Union[str, Sequence[str], None] = "c7e1a9d3f5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("wealth_positions") as batch:
        batch.add_column(sa.Column("external_holdings_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("wealth_positions") as batch:
        batch.drop_column("external_holdings_json")
