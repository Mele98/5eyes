"""Produkt-Stammdaten und Retrozessionssatz am Produkt.

Audit 2026-11, Paket P1 (Entscheid PO-6, Luecke L1: Art. 26 FIDLEG,
Art. 400 OR, BGE 132 III 460 / 137 III 393).

Neue, ausnahmslos NULLABLE Spalten auf ``products``:

``domicile``                  ISO 3166-1 alpha-2 des Fondsdomizils
``is_hedged``                 1/0, Anteilsklasse waehrungsgesichert
``hedge_currency``            ISO 4217 der Absicherung
``ter_source``, ``ter_as_of`` Herkunft und Stichtag der TER
``retrocession_bps``          Retrozessionssatz p.a.; NULL = UNBEKANNT,
                              0 = ausdruecklich retrozessionsfrei
``retrocession_source``       Herkunft des Satzes
``is_house_product``          1/0, Haus-/Eigenprodukt
``distribution_policy``       'accumulating' | 'distributing'
``valor``                     Valorennummer (optional)
``minimum_investment_minor_units`` Mindestanlage in Minor Units (optional)

Bewusst KEIN ``server_default`` und KEIN Backfill: ein Default wuerde fuer
den Bestand eine Aussage erfinden (z.B. "nicht abgesichert", "kein
Hausprodukt", "keine Retrozession"). Der Bestand bleibt "nicht erfasst"
und wird im Katalog und im Kostenausweis als solcher gekennzeichnet.

SQLite-Pfad identisch ueber ``database.py::ensure_runtime_columns``. Die
Tabelle ``products`` hat unter Postgres bereits RLS (globale Zeilen mit
``tenant_id IS NULL``, Revision e2b7c4f9a1d6); zusaetzliche Spalten
aendern die Policies nicht.

Revision ID: a8d3c5e7f9b1
Revises: f6a2c8e4b1d7
Create Date: 2026-11-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8d3c5e7f9b1"
down_revision: Union[str, Sequence[str], None] = "f6a2c8e4b1d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "products"
_COLUMNS = (
    ("domicile", sa.String()),
    ("is_hedged", sa.Integer()),
    ("hedge_currency", sa.String()),
    ("ter_source", sa.String()),
    ("ter_as_of", sa.String()),
    ("retrocession_bps", sa.Integer()),
    ("retrocession_source", sa.String()),
    ("is_house_product", sa.Integer()),
    ("distribution_policy", sa.String()),
    ("valor", sa.String()),
    ("minimum_investment_minor_units", sa.BigInteger()),
)


def _existing_columns() -> set[str] | None:
    """Vorhandene Spalten -- oder None im Offline-Modus (``--sql``), gleiche
    Begruendung wie in d7c3e9a2f5b1."""
    context = op.get_context()
    if getattr(context, "as_sql", False):
        return None
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    existing = _existing_columns()
    for name, column_type in _COLUMNS:
        if existing is not None and name in existing:
            continue
        op.add_column(_TABLE, sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    existing = _existing_columns()
    for name, _column_type in reversed(_COLUMNS):
        if existing is not None and name not in existing:
            continue
        op.drop_column(_TABLE, name)
