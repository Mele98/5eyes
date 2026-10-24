"""AUTH-TEN-08 (Teil 2): bootstrap_lock Singleton-Tabelle.

Revision ID: c3d8f4a1e6b2
Revises: a3f7c9e2b4d1
Create Date: 2026-09-03

Siehe models/bootstrap_lock.py fuer die Sicherheits-Begruendung: der
In-Prozess-Lock in routers.auth.bootstrap_admin deckt nur einen einzelnen
Backend-Worker-Prozess ab (Tier-1). Diese Tabelle traegt eine feste
Primary-Key-Zeile (id='singleton'), deren Insert der eigentliche atomare
Claim-Mechanismus ist -- ein zweiter, nahezu gleichzeitiger Bootstrap-
Versuch (egal ob im selben oder einem anderen Prozess) bekommt beim Commit
eine IntegrityError statt still einen zweiten "ersten" Admin anzulegen.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d8f4a1e6b2"
down_revision: Union[str, Sequence[str], None] = "a3f7c9e2b4d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bootstrap_lock",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("bootstrap_lock")
