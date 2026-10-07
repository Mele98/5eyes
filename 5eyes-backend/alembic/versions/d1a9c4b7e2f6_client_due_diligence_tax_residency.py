"""KYC-01 (Audit-Finding, 2026-10-07): GwG/FINMA-Sorgfaltspflicht-Datenmodell.

Bislang hatte das Datenmodell KEINE Felder fuer die GwG Art. 3-6 /
FINMA-RS 2016/7 Kunden-Sorgfaltspflichten (PEP-Status, wirtschaftliche
Berechtigung, Herkunft des Vermoegens, ID-Dokument-Verifikation,
FATCA/CRS-Steuerdomizil). Diese Revision legt die zwei neuen Tabellen an
(siehe models/clients.py::ClientDueDiligence/ClientTaxResidency):

- client_due_diligence: 1:1 mit clients (client_id UNIQUE).
- client_tax_residencies: 1:n mit clients (ein Kunde kann mehrere
  steuerliche Ansaessigkeiten haben, analog client_nationalities).

Fuer SQLite (Dev/Test/Electron-Desktop) uebernimmt
Base.metadata.create_all() das automatisch -- diese Revision betrifft
ausschliesslich den Postgres-Produktionspfad (siehe database.py::
_create_or_migrate_schema).

Revision ID: d1a9c4b7e2f6
Revises: a1c5e7f92b46
Create Date: 2026-10-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1a9c4b7e2f6"
down_revision: Union[str, Sequence[str], None] = "a1c5e7f92b46"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "client_due_diligence",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("pep_status", sa.Integer(), nullable=False),
        sa.Column("pep_details", sa.String(), nullable=True),
        sa.Column("acting_for_own_account", sa.Integer(), nullable=False),
        sa.Column("beneficial_owner_name", sa.String(), nullable=True),
        sa.Column("source_of_wealth", sa.String(), nullable=True),
        sa.Column("id_document_type", sa.String(), nullable=True),
        sa.Column("id_document_number", sa.String(), nullable=True),
        sa.Column("id_document_issuing_country", sa.String(), nullable=True),
        sa.Column("id_document_expiry", sa.String(), nullable=True),
        sa.Column("fatca_crs_self_certified", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
    )
    op.create_table(
        "client_tax_residencies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("country_code", sa.String(), nullable=False),
        sa.Column("tax_id_number", sa.String(), nullable=True),
        sa.Column("is_primary", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("client_tax_residencies")
    op.drop_table("client_due_diligence")
