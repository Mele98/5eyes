"""PensionTransferLedgerSnapshotV1 an der Soll-Allokation.

PENSION-TRANSFER-LEDGER-001, Restbefund B (Codex-Closure-Review PR #651,
2026-10-19): Der Vorsorge-Transfer-Ledger war transient. Generate und der
manuelle Speicherpfad persistieren jetzt den unveraenderlichen Snapshot
(kanonisches JSON) in `target_allocations.pension_transfer_ledger_snapshot_json`;
die Referenz (ID + Hashes) liegt in `effective_constraints_json` und damit im
`allocation_context_hash`.

NULL fuer alle Bestandszeilen ist korrekt: fuer sie wurde nie ein Snapshot
gebildet, und ein rueckwirkendes Befuellen waere eine Erfindung. Der Verifier
akzeptiert NULL nur zusammen mit fehlender Referenz.

Revision ID: b8e4d2a7c913
Revises: f3a8d1c6b4e2
Create Date: 2026-10-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8e4d2a7c913"
down_revision: Union[str, Sequence[str], None] = "f3a8d1c6b4e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "target_allocations"
_COLUMN = "pension_transfer_ledger_snapshot_json"


def _existing_columns() -> set[str] | None:
    """Vorhandene Spalten -- oder None unter `alembic upgrade --sql`
    (MockConnection; das Skript soll die Anweisung enthalten)."""
    context = op.get_context()
    if getattr(context, "as_sql", False):
        return None
    return {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)
    }


def upgrade() -> None:
    existing = _existing_columns()
    if existing is not None and _COLUMN in existing:
        return
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(), nullable=True))


def downgrade() -> None:
    existing = _existing_columns()
    if existing is not None and _COLUMN not in existing:
        return
    op.drop_column(_TABLE, _COLUMN)
