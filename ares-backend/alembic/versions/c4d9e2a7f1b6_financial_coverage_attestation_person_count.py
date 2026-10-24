"""FinancialCoverageAttestation: hash-gebundene Personenzahl (Schema V2).

DSG-ERASURE-NEW-EVIDENCE-001 (Nachzug zu #681 DSG-ERASURE-APPEND-ONLY-001,
2026-10-23): financial_coverage_attestations ist append-only. Personennamen
(``household_persons_json``) und Notiz (``note``) werden ab
FinancialCoverageAttestationV2 pro Kunde versiegelt (services/pii_vault.py,
Crypto-Shredding). Damit die Gueltigkeitspruefung keine Klartext-Namen mehr
lesen muss, bindet V2 die Personenzahl als eigene Spalte in den Hash.

Altbestand (V1): Spalte bleibt NULL; V1-Zeilen verifizieren weiter mit dem
V1-Hashvertrag. ADD COLUMN beruehrt keine Zeile (Immutability-Trigger
bleiben unangetastet).

Revision ID: c4d9e2a7f1b6
Revises: a3f6c1e8d924
Create Date: 2026-10-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d9e2a7f1b6"
down_revision: Union[str, Sequence[str], None] = "a3f6c1e8d924"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "financial_coverage_attestations",
        sa.Column("household_person_count", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    # Kein batch_alter_table: der SQLite-Tabellen-Neubau wuerde die
    # Immutability-Trigger verwerfen (Lehre aus dem audit_log-RENAME-Fund).
    op.drop_column("financial_coverage_attestations", "household_person_count")
