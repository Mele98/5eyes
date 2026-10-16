"""Produktkatalog: EU-Klima-Benchmark und Themen-Tags.

ESG-PREMIUM-CRITERIA-001 (Owner-Entscheid 2026-10-14).

Zwei neue, optionale Katalogfelder auf ``products``:

``climate_benchmark``
    'PAB' (EU Paris-aligned Benchmark) oder 'CTB' (EU Climate Transition
    Benchmark), sonst NULL. Kriterium der ESG-Policy ``net_zero``: zulaessig
    sind Produkte nach SFDR Art. 9 ODER mit PAB/CTB. Vorher bildete
    ``net_zero`` -- wie alle SFDR-gebundenen Policies -- nur auf SFDR 8/9 ab
    und versprach damit im Dokument mehr, als die Engine pruefte.

``theme_tags``
    JSON-Liste von Themen-Keys (fossil, defense, tobacco, alcohol, gaming,
    nuclear). Ein Produkt ist Themenprodukt, wenn seine Sub-Anlageklasse
    "Thema X" ist ODER theme_tags X enthaelt -- damit kann ein Asset Manager
    ein Produkt einem kontroversen Thema zuordnen, ohne seine
    Sub-Anlageklasse (und damit seinen Baustein) zu aendern.

Backfill: bestehende Produkte mit Sub-Anlageklasse "Thema X" erhalten den Tag
X, aber nur, wenn noch keine Tags gepflegt sind. Identisch zum SQLite-Pfad
(``database.py::ensure_runtime_columns`` / ``THEME_TAG_BACKFILL``). Der
Backfill ist fuer die Engine nicht zwingend (sie liest die Sub-Anlageklasse
ohnehin), macht die Klassifikation aber im Katalog sichtbar und exportierbar.

Revision ID: d7c3e9a2f5b1
Revises: c4e9a1f73b28
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7c3e9a2f5b1"
down_revision: Union[str, Sequence[str], None] = "c4e9a1f73b28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "products"
_COLUMNS = ("climate_benchmark", "theme_tags")
_THEME_TAG_BACKFILL = (
    ("Thema Fossile Energie", '["fossil"]'),
    ("Thema Verteidigung", '["defense"]'),
    ("Thema Tabak", '["tobacco"]'),
    ("Thema Alkohol", '["alcohol"]'),
    ("Thema Gluecksspiel", '["gaming"]'),
    ("Thema Kernenergie", '["nuclear"]'),
)


def _existing_columns() -> set[str] | None:
    """Vorhandene Spalten -- oder None, wenn nicht introspizierbar
    (Offline-Modus ``alembic upgrade --sql``, gleiche Begruendung wie in
    b8f3d2a71c45 / c4e9a1f73b28)."""
    context = op.get_context()
    if getattr(context, "as_sql", False):
        return None
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    existing = _existing_columns()
    for column in _COLUMNS:
        if existing is not None and column in existing:
            continue
        op.add_column(_TABLE, sa.Column(column, sa.String(), nullable=True))
    products = sa.table(
        _TABLE,
        sa.column("sub_asset_class", sa.String()),
        sa.column("theme_tags", sa.String()),
    )
    for sub_asset_class, theme_tags in _THEME_TAG_BACKFILL:
        op.execute(
            products.update()
            .where(products.c.sub_asset_class == sub_asset_class)
            .where(products.c.theme_tags.is_(None))
            .values(theme_tags=theme_tags)
        )


def downgrade() -> None:
    existing = _existing_columns()
    for column in reversed(_COLUMNS):
        if existing is not None and column not in existing:
            continue
        op.drop_column(_TABLE, column)
