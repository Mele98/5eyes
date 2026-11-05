"""audit_log: hoechstens ein Bestandssiegel (partieller Unique-Index).

N-869-9 (Delta 2 #869): Das Bestandssiegel (services/audit.py::
ensure_legacy_seal, field_name='LEGACY_SEAL' auf table_name='audit_log') wird
beim Start genau einmal geschrieben. Gegen zwei gleichzeitige Starts sperrt
ensure_legacy_seal die Zaehlerzeile und prueft unter der Sperre erneut; dieser
partielle Unique-Index ist die zweite Verteidigungslinie in der Datenbank.
Gleiche Anweisung wie database.py::_LEGACY_SEAL_UNIQUE_INDEX_SQL (SQLite-Pfad).

Downgrade entfernt den Index.

Revision ID: d3b7f1a5c9e2
Revises: c8a2f4e6b0d9
Create Date: 2026-11-06
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d3b7f1a5c9e2"
down_revision: Union[str, Sequence[str], None] = "c8a2f4e6b0d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ux_audit_log_legacy_seal"


_WHERE = "field_name = 'LEGACY_SEAL' AND table_name = 'audit_log'"


def upgrade() -> None:
    # op.create_index statt Roh-SQL mit IF NOT EXISTS: die Postgres-DDL darf
    # keine SQLite-Sonderformen enthalten (test_postgres_bootstrap_migrations).
    op.create_index(
        INDEX_NAME,
        "audit_log",
        ["field_name"],
        unique=True,
        postgresql_where=sa.text(_WHERE),
        sqlite_where=sa.text(_WHERE),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="audit_log")
