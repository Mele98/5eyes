"""target_allocations.goal_driver_evidence_json (OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001).

Generate lieferte die verlustfreien Goal-Driver nur im unmittelbaren Response;
der Reload las den Shadow-Container nicht und gab still ``[]`` zurueck, im
stochastischen Modus wurden die Driver gar nicht persistiert. Die Spalte haelt
einen versionierten, gehashten Snapshot (Driver, Rangsemantik,
Objective-Vertrag), den der Reload verifiziert abspielt.

NULL = Bestand ohne Snapshot; der Reload weist das als ``unverifiable``
(Legacy-Driver aus dem Shadow-Container), ``unavailable`` oder
``not_applicable`` aus -- nie als leere, scheinbar gueltige Liste.

Revision ID: 3960ca037812
Revises: b0eeb3e878b5
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3960ca037812"
down_revision: Union[str, Sequence[str], None] = "b0eeb3e878b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("target_allocations", sa.Column("goal_driver_evidence_json", sa.String()))


def downgrade() -> None:
    op.drop_column("target_allocations", "goal_driver_evidence_json")
