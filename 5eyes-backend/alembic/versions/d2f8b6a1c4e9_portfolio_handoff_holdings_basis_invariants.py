"""portfolio_handoffs: Bestandsbasis + DB-seitige Invarianten.

- ``holdings_basis`` (HANDOFF-NEW-PRODUCT-001): ``recorded_depot`` oder
  ``confirmed_no_holdings``; nullable, kein Backfill (Altbestand bleibt NULL).
- Trigger ``trg_portfolio_handoffs_invariants*`` (HANDOFF-DB-INVARIANT-001):
  Status nur aus der Zustandsmaschine, ``position_count >= 0``,
  ``snapshot_sha256`` Pflicht und 64 Hex-Zeichen fuer neue Zeilen, gueltige
  ``holdings_basis``. Trigger statt CHECK (Repo-Muster; SQLite kann CHECK
  nicht nachruesten): sie pruefen nur INSERT und UPDATE der betroffenen
  Spalten, Altzeilen (z.B. Hash NULL) bleiben unveraendert lesbar und
  abschliessbar -- eine Bestandspruefung vor dem Anlegen ist darum nicht
  noetig und nichts wird nachtraeglich "beglaubigt".

Revision ID: d2f8b6a1c4e9
Revises: c7e4a19b3d52
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from models.portfolio_handoff import (
    HANDOFF_INVARIANT_PG_FUNCTION,
    HANDOFF_INVARIANT_PG_TRIGGER,
    HANDOFF_INVARIANT_SQLITE_TRIGGERS,
)


revision: str = "d2f8b6a1c4e9"
down_revision: Union[str, Sequence[str], None] = "c7e4a19b3d52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("portfolio_handoffs", sa.Column("holdings_basis", sa.String(), nullable=True))
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for ddl in HANDOFF_INVARIANT_SQLITE_TRIGGERS:
            op.execute(ddl)
    elif dialect == "postgresql":
        op.execute(HANDOFF_INVARIANT_PG_FUNCTION)
        op.execute(HANDOFF_INVARIANT_PG_TRIGGER)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_portfolio_handoffs_invariants ON portfolio_handoffs")
        op.execute("DROP FUNCTION IF EXISTS portfolio_handoffs_invariants()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_portfolio_handoffs_invariants_insert")
        op.execute("DROP TRIGGER IF EXISTS trg_portfolio_handoffs_invariants_update")
    op.drop_column("portfolio_handoffs", "holdings_basis")
