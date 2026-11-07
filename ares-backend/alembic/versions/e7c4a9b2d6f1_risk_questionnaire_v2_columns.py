"""risk_assessments: Fragebogen-Version, v2-Definitions-Hash, v2-Evidenz, Beraternotiz.

H5b Risikoprofil (Dok. 105, 2026-11-07): Fragebogen v2 ist versioniert. Die
Version steht am Profil (NULL = Altprofil v1: bleibt gueltig und wird nie mit
v2-Regeln neu berechnet), dazu der Hash der v2-Definition, die kanonische
v2-Evidenz (Antworten 12-14, Kern-Bereitschaft, wirksame Kappungen,
Konsistenz-Flags) und die Pflicht-Beraternotiz bei Konsistenz-Flags.

Nur nullable ADD COLUMN, kein Backfill (Altprofile bleiben byte-gleich).
Gleiche Spalten wie database.py (SQLite-Laufzeitpatch) und ares_schema.sql.
Downgrade entfernt die Spalten.

Revision ID: e7c4a9b2d6f1
Revises: d3b7f1a5c9e2
Create Date: 2026-11-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e7c4a9b2d6f1"
down_revision: Union[str, Sequence[str], None] = "d3b7f1a5c9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = (
    "questionnaire_version",
    "questionnaire_hash",
    "willingness_v2_json",
    "consistency_note",
)


def upgrade() -> None:
    # op.add_column statt batch_alter_table: kein Tabellen-Neuaufbau, CHECKs,
    # Indizes und Trigger von risk_assessments bleiben unberuehrt (gleiches
    # Muster wie d7b3f1a9c2e4).
    for column in COLUMNS:
        op.add_column("risk_assessments", sa.Column(column, sa.String(), nullable=True))


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.drop_column("risk_assessments", column)
