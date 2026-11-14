"""Optionale Produktbindung am Interessenkonflikt (Retrozession).

Pruefrunde #861, Befund N-861-1: Eine manuelle Retrozessions-Zeile wurde
bisher nur ueber den Anbieternamen einem empfohlenen Produkt zugeordnet.
``conflict_of_interest_disclosures.product_id`` (nullable) erlaubt die
Bindung an genau ein Produkt; leer = Zuordnung wie bisher ueber den
Anbieter. Ohne Fremdschluessel-Constraint (Muster wie
``waiver_document_id``), der Router prueft die Sichtbarkeit fuer den Tenant.
Kein Default, kein Backfill. SQLite-Pfad: ``ensure_runtime_columns``.

Revision ID: d4f7a9c2e1b6
Revises: c2e6f8a1b3d5
Create Date: 2026-11-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4f7a9c2e1b6"
down_revision: Union[str, Sequence[str], None] = "c2e6f8a1b3d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "conflict_of_interest_disclosures"
_COLUMN = "product_id"


def _existing_columns() -> set[str] | None:
    if getattr(op.get_context(), "as_sql", False):
        return None
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    existing = _existing_columns()
    if existing is None or _COLUMN not in existing:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(), nullable=True))


def downgrade() -> None:
    existing = _existing_columns()
    if existing is None or _COLUMN in existing:
        op.drop_column(_TABLE, _COLUMN)
