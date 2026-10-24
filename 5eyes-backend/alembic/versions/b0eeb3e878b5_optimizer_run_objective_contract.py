"""optimizer_runs: persistierter Objective-Vertrag (OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001).

Der eingefrorene Vertrag eines Laufs (Version, alle gebundenen Felder, Hash)
existierte nur im Prozess; ``as_evidence()`` erreichte keine Run-Zeile. Drei
nullable Spalten verankern ihn:

- ``objective_contract_version`` / ``objective_contract_hash``: Anker zum
  Vergleich mit der Allokations-Modellbasis;
- ``objective_contract_json``: der vollstaendige Nachweisblock, aus dem der
  Hash versionsgenau nachgerechnet wird.

NULL heisst "Bestand ohne Vertragsnachweis" und wird als ``unverifiable``
ausgewiesen -- kein erfundener Default.

Revision ID: b0eeb3e878b5
Revises: 94089093281c
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b0eeb3e878b5"
down_revision: Union[str, Sequence[str], None] = "94089093281c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("optimizer_runs", sa.Column("objective_contract_version", sa.String()))
    op.add_column("optimizer_runs", sa.Column("objective_contract_hash", sa.String()))
    op.add_column("optimizer_runs", sa.Column("objective_contract_json", sa.String()))


def downgrade() -> None:
    op.drop_column("optimizer_runs", "objective_contract_json")
    op.drop_column("optimizer_runs", "objective_contract_hash")
    op.drop_column("optimizer_runs", "objective_contract_version")
