"""Add independent-validation anchor to optimizer_runs (OPTIMIZER-POST-SELECTION-CERTIFICATION-001).

Revision ID: b6e1d93af274
Revises: a3f7c1e9b542
Create Date: 2026-10-10

Der Optimizer selektierte den besten Kandidaten auf demselben Szenario-Cube,
auf dem er ihn danach zertifizierte (Post-Selection-Bias / Winner's Curse).
`seed`/`n_paths` beschreiben diesen Trainings-Cube. Diese drei Spalten
verankern die davon UNABHAENGIGE Validierungsstichprobe, auf der der
Gewinner nachzertifiziert wird.

Bewusst nullable: NULL bedeutet "dieser Lauf wurde nie unabhaengig
validiert". Vorher existierte kein Feld, dessen NULL-heit das ausdruecken
konnte -- ein nicht validierter Lauf war von einem validierten nicht
unterscheidbar, und nichts konnte auf eine fehlende Validierung pruefen.
Bestandszeilen bleiben daher korrekt als "nicht validiert" markiert, statt
mit einem erfundenen Default-Wert als validiert zu erscheinen.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6e1d93af274"
down_revision: Union[str, Sequence[str], None] = "a3f7c1e9b542"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("optimizer_runs", sa.Column("validation_seed", sa.Integer()))
    op.add_column("optimizer_runs", sa.Column("validation_cube_hash", sa.String()))
    op.add_column("optimizer_runs", sa.Column("validation_n_paths", sa.Integer()))


def downgrade() -> None:
    op.drop_column("optimizer_runs", "validation_n_paths")
    op.drop_column("optimizer_runs", "validation_cube_hash")
    op.drop_column("optimizer_runs", "validation_seed")
