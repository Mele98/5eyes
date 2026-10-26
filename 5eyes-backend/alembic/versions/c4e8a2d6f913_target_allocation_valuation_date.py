"""target_allocations.valuation_date (GOAL-CALENDAR-HORIZON-PARITY-001, ADR-1b).

Owner-Entscheid 1b (2026-10-11): jeder Lauf bindet den Bewertungsstichtag beim
Ausloesen und persistiert ihn; Reload, Staleness-Pruefung und Report-
Simulation lesen den gespeicherten Stichtag statt erneut die Wanduhr. Vorher
verschob ein Reload nach dem Jahreswechsel Liability-Buckets, Zeitachse und
Zielerreichung, ohne dass sich an den Daten etwas geaendert hatte.

NULL = Bestand vor ADR-1b; diese Allokationen behalten das bisherige
Verhalten (Wanduhr, Input-Hash ohne Stichtag).

Revision ID: c4e8a2d6f913
Revises: b5d2e8f41a73
Create Date: 2026-10-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e8a2d6f913"
down_revision: Union[str, Sequence[str], None] = "b5d2e8f41a73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("target_allocations", sa.Column("valuation_date", sa.String()))


def downgrade() -> None:
    op.drop_column("target_allocations", "valuation_date")
