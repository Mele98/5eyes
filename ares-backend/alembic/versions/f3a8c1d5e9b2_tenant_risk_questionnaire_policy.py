"""tenants: Risikoprofil-Fragebogen v2 als Firmen-Policy (Default aus).

H5 (N-886-08, 2026-11-07): Die Aktivierung von Fragebogen v2 ist keine
Code-Konstante mehr, sondern eine auditierte Firmen-Einstellung
(PUT /tenants/me/risk-questionnaire-policy). Wirksam nur mit Vermerk der
IC-/Compliance-Freigabe der Grenzwerte.

Nur ADD COLUMN; das Flag ist NOT NULL mit Server-Default 0 (Bestandsfirmen
bleiben aus). Gleiche Spalten wie database.py (SQLite-Laufzeitpatch) und ORM.
Downgrade entfernt die Spalten.

Revision ID: f3a8c1d5e9b2
Revises: e7c4a9b2d6f1
Create Date: 2026-11-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f3a8c1d5e9b2"
down_revision: Union[str, Sequence[str], None] = "e7c4a9b2d6f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TEXT_COLUMNS = (
    "risk_questionnaire_v2_approval_ref",
    "risk_questionnaire_v2_changed_at",
    "risk_questionnaire_v2_changed_by",
)


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("risk_questionnaire_v2_enabled", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    for column in TEXT_COLUMNS:
        op.add_column("tenants", sa.Column(column, sa.String(), nullable=True))


def downgrade() -> None:
    for column in reversed(TEXT_COLUMNS):
        op.drop_column("tenants", column)
    op.drop_column("tenants", "risk_questionnaire_v2_enabled")
