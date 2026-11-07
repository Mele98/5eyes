"""H8: Kundeninformation (Art. 8/9 FIDLEG).

Compliance-Audit 2026-11-07 (Dok. 104), Paket H8:

- ``tenant_legal_profiles``: rechtliche Angaben der Firma (C-2), ohne
  Vorbelegung; Aenderungen feldweise im Audit-Log.
- ``client_information_deliveries``: append-only Abgabenachweis der
  Kundeninformation (Fassung, Byte-Hash, Version, Zeitpunkt, Kanal).

Append-only per Trigger (SQLite und PostgreSQL), wie
financial_coverage_attestations. Kein FK auf mandates/clients (Purge-fest),
nur die Akteure verweisen auf users. Dieselben Tabellen legt der SQLite-Pfad
ueber create_all an (Modelle in models/tenant.py, models/clients.py,
models/review.py; Trigger database.py::*_SQLITE_TRIGGERS).

Revision ID: d8e4b2a6c1f9
Revises: d3b7f1a5c9e2
Create Date: 2026-11-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d8e4b2a6c1f9"
down_revision: Union[str, Sequence[str], None] = "d3b7f1a5c9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPEND_ONLY_TABLES = (
    "client_information_deliveries",
)


def _sqlite_triggers(table: str) -> tuple[str, str]:
    return (
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update "
        f"BEFORE UPDATE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete "
        f"BEFORE DELETE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
    )


def _pg_function(table: str) -> str:
    return (
        f"CREATE OR REPLACE FUNCTION {table}_immutable() RETURNS trigger AS $$\n"
        "BEGIN\n"
        f"    RAISE EXCEPTION '{table} is immutable';\n"
        "END;\n"
        "$$ LANGUAGE plpgsql"
    )


def _pg_trigger(table: str) -> str:
    return (
        f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {table}_immutable()"
    )


def upgrade() -> None:
    op.create_table(
        "tenant_legal_profiles",
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("legal_name", sa.String(), nullable=True),
        sa.Column("address_street", sa.String(), nullable=True),
        sa.Column("address_postal_code", sa.String(), nullable=True),
        sa.Column("address_city", sa.String(), nullable=True),
        sa.Column("address_country", sa.String(), nullable=True),
        sa.Column("business_activity", sa.String(), nullable=True),
        sa.Column("supervision_type", sa.String(), nullable=True),
        sa.Column("supervisory_authority", sa.String(), nullable=True),
        sa.Column("supervisory_organisation", sa.String(), nullable=True),
        sa.Column("license_reference", sa.String(), nullable=True),
        sa.Column("ombudsman_name", sa.String(), nullable=True),
        sa.Column("ombudsman_address", sa.String(), nullable=True),
        sa.Column("contact_phone", sa.String(), nullable=True),
        sa.Column("contact_email", sa.String(), nullable=True),
        sa.Column("contact_website", sa.String(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("profile_hash", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_table(
        "client_information_deliveries",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("contract_document_id", sa.String(), nullable=False),
        sa.Column("template_version", sa.String(), nullable=False),
        sa.Column("legal_profile_revision", sa.Integer(), nullable=False),
        sa.Column("legal_profile_hash", sa.String(), nullable=False),
        sa.Column("pdf_sha256", sa.String(), nullable=False),
        sa.Column("delivered_at", sa.String(), nullable=False),
        sa.Column("delivery_channel", sa.String(), nullable=False),
        sa.Column("recorded_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.String(), nullable=False),
        sa.Column("delivery_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    dialect = op.get_bind().dialect.name
    for table in APPEND_ONLY_TABLES:
        if dialect == "sqlite":
            for ddl in _sqlite_triggers(table):
                op.execute(ddl)
        elif dialect == "postgresql":
            op.execute(_pg_function(table))
            op.execute(_pg_trigger(table))


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    for table in APPEND_ONLY_TABLES:
        if dialect == "postgresql":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
        elif dialect == "sqlite":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
    op.drop_table("client_information_deliveries")
    op.drop_table("tenant_legal_profiles")
