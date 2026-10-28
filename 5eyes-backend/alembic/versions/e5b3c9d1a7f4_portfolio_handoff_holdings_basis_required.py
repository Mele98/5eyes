"""portfolio_handoffs: Bestandsbasis Pflicht fuer neue Zeilen.

Red-Team 2026-10-28 Befund 4: der Insert-Trigger aus d2f8b6a1c4e9 liess
``holdings_basis IS NULL`` zu. Neu verlangt er fuer jede NEUE Zeile eine Basis
(``recorded_depot`` oder ``confirmed_no_holdings``); Altzeilen ohne Basis
bleiben lesbar, aenderbar und abschliessbar (UPDATE unveraendert). Die DDL
ist hier eingefroren (Literal); ``models/portfolio_handoff.py`` fuehrt die
gleiche DDL fuer create_all und den SQLite-Runtime-Patch, ein Test prueft die
Gleichheit.

Revision ID: e5b3c9d1a7f4
Revises: d2f8b6a1c4e9
Create Date: 2026-10-28
"""
from typing import Sequence, Union

from alembic import op


revision: str = "e5b3c9d1a7f4"
down_revision: Union[str, Sequence[str], None] = "d2f8b6a1c4e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQLITE_INSERT_TRIGGER_NAME = "trg_portfolio_handoffs_invariants_insert"

SQLITE_INSERT_TRIGGER = (
    'CREATE TRIGGER IF NOT EXISTS trg_portfolio_handoffs_invariants_insert'
    ' BEFORE INSERT ON portfolio_handoffs'
    ' FOR EACH ROW'
    " WHEN NEW.status IS NULL OR NEW.status NOT IN ('Vorbereitet', 'Gesendet', 'Ausgeführt', 'Storniert') OR NEW.position_count IS NULL OR NEW.position_count < 0"
    " OR (NEW.holdings_basis IS NOT NULL AND NEW.holdings_basis NOT IN ('recorded_depot', 'confirmed_no_holdings'))"
    " OR NEW.snapshot_sha256 IS NULL OR length(NEW.snapshot_sha256) <> 64 OR NEW.snapshot_sha256 GLOB '*[^0-9a-f]*'"
    ' OR NEW.holdings_basis IS NULL'
    " BEGIN SELECT RAISE(ABORT, 'portfolio_handoffs invariant violated'); END"
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
    IF TG_OP = 'INSERT' AND NEW.holdings_basis IS NULL THEN
        RAISE EXCEPTION 'portfolio_handoffs invariant violated';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

# Stand d2f8b6a1c4e9 (fuer den Downgrade).
PREVIOUS_SQLITE_INSERT_TRIGGER = (
    'CREATE TRIGGER IF NOT EXISTS trg_portfolio_handoffs_invariants_insert'
    ' BEFORE INSERT ON portfolio_handoffs'
    ' FOR EACH ROW'
    " WHEN NEW.status IS NULL OR NEW.status NOT IN ('Vorbereitet', 'Gesendet', 'Ausgeführt', 'Storniert') OR NEW.position_count IS NULL OR NEW.position_count < 0"
    " OR (NEW.holdings_basis IS NOT NULL AND NEW.holdings_basis NOT IN ('recorded_depot', 'confirmed_no_holdings'))"
    " OR NEW.snapshot_sha256 IS NULL OR length(NEW.snapshot_sha256) <> 64 OR NEW.snapshot_sha256 GLOB '*[^0-9a-f]*'"
    " BEGIN SELECT RAISE(ABORT, 'portfolio_handoffs invariant violated'); END"
)
PREVIOUS_PG_FUNCTION = """
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


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {SQLITE_INSERT_TRIGGER_NAME}")
        op.execute(SQLITE_INSERT_TRIGGER)
    elif dialect == "postgresql":
        op.execute(PG_FUNCTION)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {SQLITE_INSERT_TRIGGER_NAME}")
        op.execute(PREVIOUS_SQLITE_INSERT_TRIGGER)
    elif dialect == "postgresql":
        op.execute(PREVIOUS_PG_FUNCTION)
