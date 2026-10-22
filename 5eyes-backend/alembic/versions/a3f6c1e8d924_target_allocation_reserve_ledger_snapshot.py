"""TargetAllocation: Reserve-Funding-Ledger-Snapshot + Hash.

RESERVE-LEDGER-SNAPSHOT-001 (Codex-Closure-Review zu PR #648, 2026-10-19):
der beim Generate publizierte ReserveFundingLedgerV1 wird als kanonisches
JSON (``reserve_funding_ledger_json``) plus Contract-Hash
(``reserve_funding_ledger_hash``) an der Soll-Allokation persistiert; die
Referenz ist zusaetzlich in ``effective_constraints_json`` und damit im
``allocation_context_hash`` gebunden.

Altbestand: beide Spalten bleiben NULL -- "nicht replay-verifizierbar", keine
rueckwirkend erfundene Evidence (Finalisierung verlangt Neuberechnung).
Retention: der Snapshot lebt und stirbt mit seiner TargetAllocation-Zeile.

Revision ID: a3f6c1e8d924
Revises: d7b3f1a9c2e4
Create Date: 2026-10-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3f6c1e8d924"
down_revision: Union[str, Sequence[str], None] = "d7b3f1a9c2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "target_allocations",
        sa.Column("reserve_funding_ledger_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "target_allocations",
        sa.Column("reserve_funding_ledger_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("target_allocations", "reserve_funding_ledger_hash")
    op.drop_column("target_allocations", "reserve_funding_ledger_json")
