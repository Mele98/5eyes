"""H-179 N-927R-01: Rolle und Bereitschaft des Freigebers eingefroren.

``owner_content_approvals.approver_role`` / ``approver_ready``: Stand des
Freigebers zum Freigabezeitpunkt, im Siegel der Freigabezeile (Muster
``kyc_review_policy_activations.approver_ready``, N-897-13). Beim Lesen gilt
der eingefrorene Stand; ein spaeterer Rollenwechsel oder eine Deaktivierung
entwertet eine gueltig erteilte Freigabe nicht, nur ein auditierter Widerruf
wegen Kompromittierung ab dessen Zeitpunkt. Nullable, kein Backfill:
Altzeilen ohne Stand werden mit dem heutigen Stand nachgerechnet.

ADD COLUMN feuert den Append-only-Trigger nicht (SQLite und PostgreSQL).
Gleiche Spalten im SQLite-Laufzeitpatch (database.py::ensure_runtime_columns).

Downgrade (fail-closed): liegt eine Freigabe mit eingefrorenem Stand vor,
bricht der Downgrade ab (das Siegel der Zeile umfasst die Spalten).

Revision ID: e5a9c3d7b1f4
Revises: c7e1a9d3f5b2
Create Date: 2026-11-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "e5a9c3d7b1f4"
down_revision: Union[str, Sequence[str], None] = "c7e1a9d3f5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "owner_content_approvals"


def _dialect() -> str:
    if context.is_offline_mode():
        return context.get_context().dialect.name
    return op.get_bind().dialect.name


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("approver_role", sa.String(), nullable=True))
    op.add_column(TABLE, sa.Column("approver_ready", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text(
        f"SELECT COUNT(*) FROM {TABLE} WHERE approver_role IS NOT NULL OR approver_ready IS NOT NULL"
    )).scalar():
        raise RuntimeError(
            "N-927R-01 Downgrade abgelehnt (fail-closed): Freigaben mit eingefrorenem Stand "
            "wuerden ihr Siegel verlieren. Datenbank aus Sicherung wiederherstellen."
        )
    dialect = _dialect()
    if dialect == "sqlite":
        # batch_alter_table baut die Tabelle neu: Append-only-Trigger danach wieder anlegen.
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_delete")
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("approver_ready")
        batch.drop_column("approver_role")
    if dialect == "sqlite":
        op.execute(
            f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_no_update BEFORE UPDATE ON {TABLE} FOR EACH ROW "
            f"BEGIN SELECT RAISE(ABORT, '{TABLE} is immutable'); END"
        )
        op.execute(
            f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_no_delete BEFORE DELETE ON {TABLE} FOR EACH ROW "
            f"BEGIN SELECT RAISE(ABORT, '{TABLE} is immutable'); END"
        )
