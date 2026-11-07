"""Eigene Fonds (kotiert/nicht kotiert), Bewertungsquelle, Liquiditaetsrhythmus.

Audit 2026-11, Paket P1, Owner-Anforderung: Vermoegensverwalter und Banken
wollen teils NUR ihre eigenen Fonds verwenden, kotiert oder nicht kotiert.
Neue, nullable Spalten auf ``products``:

``listing_status``           'listed' | 'unlisted'
``internal_product_id``      interne, tenant-eindeutige Produkt-ID
                             (Pflicht bei unlisted ohne ISIN; Router-Pruefung)
``price_source``             'market' | 'manual_nav' | 'provider'
``nav_frequency``            'daily' | 'weekly' | 'monthly' | 'quarterly'
``nav_as_of``                NAV-Stichtag (manuell pflegbar)
``redemption_period_days``   Ruecknahmefrist (Tage)
``notice_period_days``       Kuendigungsfrist (Tage)
``has_gating``               1/0, Gating moeglich
``gating_terms``             Gating-Bedingungen (Freitext)

Dazu der partielle Unique-Index ``ux_products_tenant_internal_id`` auf
``(tenant_id, internal_product_id)`` fuer aktive Zeilen mit gesetzter ID
(Postgres und SQLite unterstuetzen partielle Indizes). Fuer den globalen
Katalog (tenant_id NULL) greift die Router-Pruefung, weil NULL-Werte im
Index als verschieden gelten.

Kein server_default, kein Backfill (nichts erfinden). Grundlage fuer den
Universe-Modus "nur eigene Fonds" (P3/P4) und spaeter Liquiditaets-/
Illiquiditaetslimits und Kostentransparenz. SQLite-Pfad identisch ueber
``database.py::ensure_runtime_columns``.

Revision ID: c2e6f8a1b3d5
Revises: a8d3c5e7f9b1
Create Date: 2026-11-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2e6f8a1b3d5"
down_revision: Union[str, Sequence[str], None] = "a8d3c5e7f9b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "products"
_INDEX = "ux_products_tenant_internal_id"
_COLUMNS = (
    ("listing_status", sa.String()),
    ("internal_product_id", sa.String()),
    ("price_source", sa.String()),
    ("nav_frequency", sa.String()),
    ("nav_as_of", sa.String()),
    ("redemption_period_days", sa.Integer()),
    ("notice_period_days", sa.Integer()),
    ("has_gating", sa.Integer()),
    ("gating_terms", sa.String()),
)
_WHERE = "internal_product_id IS NOT NULL AND deleted_at IS NULL"


def _inspector():
    context = op.get_context()
    if getattr(context, "as_sql", False):
        return None
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    inspector = _inspector()
    existing = None if inspector is None else {c["name"] for c in inspector.get_columns(_TABLE)}
    for name, column_type in _COLUMNS:
        if existing is not None and name in existing:
            continue
        op.add_column(_TABLE, sa.Column(name, column_type, nullable=True))
    indexes = None if inspector is None else {i["name"] for i in inspector.get_indexes(_TABLE)}
    if indexes is None or _INDEX not in indexes:
        op.create_index(
            _INDEX, _TABLE, ["tenant_id", "internal_product_id"], unique=True,
            postgresql_where=sa.text(_WHERE), sqlite_where=sa.text(_WHERE),
        )


def downgrade() -> None:
    inspector = _inspector()
    indexes = None if inspector is None else {i["name"] for i in inspector.get_indexes(_TABLE)}
    if indexes is None or _INDEX in indexes:
        op.drop_index(_INDEX, table_name=_TABLE)
    existing = None if inspector is None else {c["name"] for c in inspector.get_columns(_TABLE)}
    for name, _column_type in reversed(_COLUMNS):
        if existing is not None and name not in existing:
            continue
        op.drop_column(_TABLE, name)
