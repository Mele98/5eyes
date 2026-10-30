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
Revises: c8e2f4a6b1d3
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2f8b6a1c4e9"
down_revision: Union[str, Sequence[str], None] = "c8e2f4a6b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Red-Team 2026-10-28 Befund 5: DDL dieser Revision eingefroren (Literal,
# kein Import aus dem lebenden Modell). Spaetere Aenderungen gehoeren in eine
# neue Revision (z.B. e5b3c9d1a7f4: holdings_basis Pflicht bei INSERT).
SQLITE_TRIGGERS: tuple[str, ...] = (
    (
        'CREATE TRIGGER IF NOT EXISTS trg_portfolio_handoffs_invariants_insert'
        ' BEFORE INSERT ON portfolio_handoffs'
        ' FOR EACH ROW'
        " WHEN NEW.status IS NULL OR NEW.status NOT IN ('Vorbereitet', 'Gesendet', 'Ausgeführt', 'Storniert') OR NEW.position_count IS NULL OR NEW.position_count < 0"
        " OR (NEW.holdings_basis IS NOT NULL AND NEW.holdings_basis NOT IN ('recorded_depot', 'confirmed_no_holdings'))"
        " OR NEW.snapshot_sha256 IS NULL OR length(NEW.snapshot_sha256) <> 64 OR NEW.snapshot_sha256 GLOB '*[^0-9a-f]*'"
        " BEGIN SELECT RAISE(ABORT, 'portfolio_handoffs invariant violated'); END"
    ),
    (
        'CREATE TRIGGER IF NOT EXISTS trg_portfolio_handoffs_invariants_update'
        ' BEFORE UPDATE OF status, position_count, snapshot_sha256, holdings_basis ON portfolio_handoffs'
        ' FOR EACH ROW'
        " WHEN NEW.status IS NULL OR NEW.status NOT IN ('Vorbereitet', 'Gesendet', 'Ausgeführt', 'Storniert') OR NEW.position_count IS NULL OR NEW.position_count < 0"
        " OR (NEW.holdings_basis IS NOT NULL AND NEW.holdings_basis NOT IN ('recorded_depot', 'confirmed_no_holdings'))"
        " OR (NEW.snapshot_sha256 IS NOT OLD.snapshot_sha256 AND (NEW.snapshot_sha256 IS NULL OR length(NEW.snapshot_sha256) <> 64 OR NEW.snapshot_sha256 GLOB '*[^0-9a-f]*'))"
        " BEGIN SELECT RAISE(ABORT, 'portfolio_handoffs invariant violated'); END"
    ),
)
PG_FUNCTION = """
CREATE OR REPLACE FUNCTION portfolio_handoffs_invariants()
RETURNS trigger AS $$
BEGIN
    IF NEW.status IS NULL OR NEW.status NOT IN ('Vorbereitet', 'Gesendet', 'Ausgeführt', 'Storniert')
       OR NEW.position_count IS NULL OR NEW.position_count < 0
       OR (NEW.holdings_basis IS NOT NULL AND NEW.holdings_basis NOT IN ('recorded_depot', 'confirmed_no_holdings')) THEN
        RAISE EXCEPTION 'portfolio_handoffs invariant violated';
    END IF;
    IF (TG_OP = 'INSERT' OR NEW.snapshot_sha256 IS DISTINCT FROM OLD.snapshot_sha256)
       AND (NEW.snapshot_sha256 IS NULL OR NEW.snapshot_sha256 !~ '^[0-9a-f]{64}$') THEN
        RAISE EXCEPTION 'portfolio_handoffs invariant violated';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""
PG_TRIGGER = """
CREATE TRIGGER trg_portfolio_handoffs_invariants
BEFORE INSERT OR UPDATE OF status, position_count, snapshot_sha256, holdings_basis
ON portfolio_handoffs
FOR EACH ROW EXECUTE FUNCTION portfolio_handoffs_invariants()
"""


def upgrade() -> None:
    op.add_column("portfolio_handoffs", sa.Column("holdings_basis", sa.String(), nullable=True))
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for ddl in SQLITE_TRIGGERS:
            op.execute(ddl)
    elif dialect == "postgresql":
        op.execute(PG_FUNCTION)
        op.execute(PG_TRIGGER)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_portfolio_handoffs_invariants ON portfolio_handoffs")
        op.execute("DROP FUNCTION IF EXISTS portfolio_handoffs_invariants()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_portfolio_handoffs_invariants_insert")
        op.execute("DROP TRIGGER IF EXISTS trg_portfolio_handoffs_invariants_update")
    op.drop_column("portfolio_handoffs", "holdings_basis")
