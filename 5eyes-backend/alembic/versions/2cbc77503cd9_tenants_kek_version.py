"""tenants.kek_version: Generation der Master-KEK, unter der encrypted_dek verpackt ist.

AF-5 (Tenant-Crypto-Haertung): ``tenants`` kannte bisher nur ``dek_version``
(Generation des DEK selbst). Fuer einen spaeteren KEK-Rewrap (neuer KEK,
gleicher DEK) muss pro Zeile erkennbar sein, unter welcher KEK-Generation der
DEK verpackt ist. Bestand und neue Zeilen: 1 (der heutige KEK-Vertrag).

Reine Schema-Erweiterung, keine Logikaenderung: die Version wird nur
gespeichert. ADD COLUMN mit Server-Default fuellt Bestandszeilen mit 1.

Revision ID: 2cbc77503cd9
Revises: e2b7c4f9a1d6
Create Date: 2026-10-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2cbc77503cd9"
down_revision: Union[str, Sequence[str], None] = "e2b7c4f9a1d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "kek_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "kek_version")
