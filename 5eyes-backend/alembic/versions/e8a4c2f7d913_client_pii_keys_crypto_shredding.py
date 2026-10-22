"""Kundenschluessel fuer Crypto-Shredding append-only Freitexte (DSG Art. 32).

DSG-ERASURE-APPEND-ONLY-001 (2026-10-21): risk_override_decisions.reason und
risk_profile_signoffs.note (append-only, UPDATE/DELETE per Trigger verboten)
sowie ihre audit_log-Snapshots tragen Freitext nur noch versiegelt
(services/pii_vault.py). Der Schluessel pro Kunde liegt in client_pii_keys;
die DSG-Art.-32-Erasure vernichtet ihn (key_material -> NULL). Der Trigger
erlaubt NUR diese Richtung (kein Ersetzen/Wiederbeleben, kein DELETE --
der Tombstone belegt die Vernichtung). Kein FK auf clients (Purge-fest).

Altbestand (Klartext-Zeilen vor diesem Fix) wird NICHT umgeschrieben -- das
waere eine Aenderung unveraenderlicher Evidence; die Erasure meldet ihn.

Revision ID: e8a4c2f7d913
Revises: d7b3f1a9c2e4
Create Date: 2026-10-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8a4c2f7d913"
down_revision: Union[str, Sequence[str], None] = "d7b3f1a9c2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS trg_client_pii_keys_shred_only "
    "BEFORE UPDATE ON client_pii_keys FOR EACH ROW "
    "WHEN NEW.client_id IS NOT OLD.client_id OR NEW.key_id IS NOT OLD.key_id "
    "OR (NEW.key_material IS NOT NULL AND NEW.key_material IS NOT OLD.key_material) "
    "OR (OLD.shredded_at IS NOT NULL AND NEW.shredded_at IS NOT OLD.shredded_at) "
    "BEGIN SELECT RAISE(ABORT, 'client_pii_keys is shred-only'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_client_pii_keys_no_delete "
    "BEFORE DELETE ON client_pii_keys FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'client_pii_keys is shred-only'); END",
)

_PG_FUNCTION = """
CREATE OR REPLACE FUNCTION client_pii_keys_shred_only()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'client_pii_keys is shred-only';
    END IF;
    IF NEW.client_id IS DISTINCT FROM OLD.client_id
       OR NEW.key_id IS DISTINCT FROM OLD.key_id
       OR (NEW.key_material IS NOT NULL AND NEW.key_material IS DISTINCT FROM OLD.key_material)
       OR (OLD.shredded_at IS NOT NULL AND NEW.shredded_at IS DISTINCT FROM OLD.shredded_at) THEN
        RAISE EXCEPTION 'client_pii_keys is shred-only';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

_PG_TRIGGER = """
CREATE TRIGGER trg_client_pii_keys_shred_only
BEFORE UPDATE OR DELETE ON client_pii_keys
FOR EACH ROW EXECUTE FUNCTION client_pii_keys_shred_only()
"""


def upgrade() -> None:
    op.create_table(
        "client_pii_keys",
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("key_id", sa.String(), nullable=False),
        sa.Column("key_material", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("shredded_at", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("client_id"),
        sa.UniqueConstraint("key_id"),
        sa.CheckConstraint(
            "(key_material IS NULL) = (shredded_at IS NOT NULL)",
            name="ck_client_pii_keys_shredded",
        ),
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for ddl in _SQLITE_TRIGGERS:
            op.execute(ddl)
    elif dialect == "postgresql":
        op.execute(_PG_FUNCTION)
        op.execute(_PG_TRIGGER)


def downgrade() -> None:
    # ACHTUNG: entfernt alle Kundenschluessel -- versiegelte Freitexte sind
    # danach fuer ALLE Kunden unlesbar (wirkt wie Shredding fuer jeden).
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_client_pii_keys_shred_only ON client_pii_keys")
        op.execute("DROP FUNCTION IF EXISTS client_pii_keys_shred_only()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_client_pii_keys_shred_only")
        op.execute("DROP TRIGGER IF EXISTS trg_client_pii_keys_no_delete")
    op.drop_table("client_pii_keys")
