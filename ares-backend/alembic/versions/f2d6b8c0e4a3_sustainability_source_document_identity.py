"""Nachhaltigkeitsnachweise: Identitaet des Quelldokuments und neutrale
Kunden-Quellbezeichnung.

Audit 2026-11 / 05, Paket T1, Pruefrunde #863 (FINMA-Sicht 9b/9c): Die Quelle
muss spaeter belegbar sein (Titel/Version, Dokumentdatum, optional SHA-256
der abgelegten Datei), und Kundendokumente brauchen eine neutrale
Quellbezeichnung ohne Dritt- oder Markennamen, getrennt vom internen
``source_provider``.

Neue, nullable Spalten auf ``product_sustainability_attributes``:
``source_document_title``, ``source_document_version``,
``source_document_date``, ``source_document_sha256``, ``client_source_label``.
Kein Backfill und kein server_default (nichts erfinden). Die RLS-Policies der
Tabelle bleiben unberuehrt.

Revision ID: f2d6b8c0e4a3
Revises: e1c5a7b9d3f2
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2d6b8c0e4a3"
down_revision: Union[str, Sequence[str], None] = "e1c5a7b9d3f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "product_sustainability_attributes"
COLUMNS = (
    "source_document_title",
    "source_document_version",
    "source_document_date",
    "source_document_sha256",
    "client_source_label",
)


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column(TABLE, sa.Column(name, sa.String(), nullable=True))


def downgrade() -> None:
    for name in reversed(COLUMNS):
        op.drop_column(TABLE, name)
