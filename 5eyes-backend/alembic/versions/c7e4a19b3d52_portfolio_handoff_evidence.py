"""portfolio_handoffs: Snapshot-Hash, fachlicher Schluessel, Ausfuehrungs-Evidence.

CERT-HANDOFF-EXECUTION-001:

- ``snapshot_sha256`` (HANDOFF-INTEGRITY-001): SHA-256 ueber den gespeicherten
  Trade-Snapshot; die Response verifiziert ihn.
- ``business_key_hash`` + partieller Unique-Index
  ``ux_portfolio_handoffs_open_business_key`` (HANDOFF-IDEMPOTENCY-001):
  hoechstens ein offener Handoff je fachlicher Identitaet.
- ``execution_evidence_kind`` / ``execution_external_reference`` /
  ``execution_confirmed_on`` (HANDOFF-EXECUTION-001): Ausfuehrung nur mit
  externer Referenz und Datum, als manuelle Bestaetigung ausgewiesen.

Alle Spalten nullable: Bestandszeilen bleiben unveraendert (kein Backfill --
ein nachtraeglich berechneter Hash wuerde ungeprueften Altbestand
"beglaubigen").

Revision ID: c7e4a19b3d52
Revises: b5d2e8f41a73
Create Date: 2026-10-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7e4a19b3d52"
down_revision: Union[str, Sequence[str], None] = "b5d2e8f41a73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    "snapshot_sha256",
    "business_key_hash",
    "execution_evidence_kind",
    "execution_external_reference",
    "execution_confirmed_on",
)
_INDEX = "ux_portfolio_handoffs_open_business_key"
_PREDICATE = "business_key_hash IS NOT NULL AND status IN ('Vorbereitet', 'Gesendet')"


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column("portfolio_handoffs", sa.Column(name, sa.String(), nullable=True))
    op.create_index(
        _INDEX, "portfolio_handoffs", ["business_key_hash"], unique=True,
        sqlite_where=sa.text(_PREDICATE), postgresql_where=sa.text(_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="portfolio_handoffs")
    for name in reversed(_COLUMNS):
        op.drop_column("portfolio_handoffs", name)
