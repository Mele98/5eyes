"""Freigegebene Nachhaltigkeitsnachweise in der DB unveraenderlich (H-6).

Audit 2026-11 / 05, Paket T1, Pruefrunde #863 Hinweis H-6: Die
Unveraenderlichkeit freigegebener Nachweise war nur in der API durchgesetzt.
Jetzt in SQLite und Postgres per Trigger:

- Entwurf (status 'draft'): frei aenderbar und loeschbar.
- Freigegeben (status 'approved'): einzig erlaubt ist der Wechsel nach
  'retired', dabei duerfen sich nur retired_by, retired_at und updated_at
  aendern; jede andere Aenderung bricht ab.
- Zurueckgezogen ('retired'): keine Aenderung mehr.
- DELETE eines freigegebenen oder zurueckgezogenen Nachweises bricht ab.

Spaltenliste hier eingefroren (Stand f2d6b8c0e4a3); ein Test vergleicht sie
mit ``models.product_eligibility.SUSTAINABILITY_ATTRIBUTE_IMMUTABLE_COLUMNS``
(gleiche DDL fuer den SQLite-create_all-Pfad). Kommt eine Spalte dazu, muss
eine neue Revision den Trigger neu anlegen.

Revision ID: a3e7c9d1f5b4
Revises: f2d6b8c0e4a3
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a3e7c9d1f5b4"
down_revision: Union[str, Sequence[str], None] = "f2d6b8c0e4a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "product_sustainability_attributes"
IMMUTABLE_COLUMNS = (
    "id", "product_id", "tenant_id", "category", "kind", "revenue_threshold_bps", "measured_exposure_bps",
    "value", "source_type", "source_reference", "source_provider", "source_retrieved_on",
    "source_document_title", "source_document_version", "source_document_date", "source_document_sha256",
    "client_source_label", "as_of", "valid_until", "note", "created_by", "created_at", "approved_by",
    "approved_at", "approval_mode", "supersedes_id",
)
_MESSAGE = "product_sustainability_attributes: freigegebener Nachweis ist unveraenderlich"
_SQLITE_UNCHANGED = " AND ".join(f"NEW.{c} IS OLD.{c}" for c in IMMUTABLE_COLUMNS)
SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS trg_psa_immutable_update "
    f"BEFORE UPDATE ON {TABLE} FOR EACH ROW "
    "WHEN OLD.status <> 'draft' AND NOT (OLD.status = 'approved' AND NEW.status = 'retired' AND "
    + _SQLITE_UNCHANGED + ") "
    f"BEGIN SELECT RAISE(ABORT, '{_MESSAGE}'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_psa_immutable_delete "
    f"BEFORE DELETE ON {TABLE} FOR EACH ROW "
    "WHEN OLD.status <> 'draft' "
    f"BEGIN SELECT RAISE(ABORT, '{_MESSAGE}'); END",
)
_PG_UNCHANGED = " AND ".join(f"NEW.{c} IS NOT DISTINCT FROM OLD.{c}" for c in IMMUTABLE_COLUMNS)
PG_FUNCTION = f"""
CREATE OR REPLACE FUNCTION product_sustainability_attributes_immutable()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION '{_MESSAGE}';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status <> 'draft' AND NOT (OLD.status = 'approved' AND NEW.status = 'retired' AND {_PG_UNCHANGED}) THEN
        RAISE EXCEPTION '{_MESSAGE}';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""
PG_TRIGGER = (
    "CREATE TRIGGER trg_psa_immutable BEFORE UPDATE OR DELETE ON product_sustainability_attributes "
    "FOR EACH ROW EXECUTE FUNCTION product_sustainability_attributes_immutable()"
)


def _is_postgres() -> bool:
    return op.get_context().dialect.name.startswith("postgresql")


def upgrade() -> None:
    if _is_postgres():
        op.execute(PG_FUNCTION)
        op.execute(f"DROP TRIGGER IF EXISTS trg_psa_immutable ON {TABLE}")
        op.execute(PG_TRIGGER)
        return
    if op.get_context().dialect.name == "sqlite":
        for ddl in SQLITE_TRIGGERS:
            op.execute(ddl)


def downgrade() -> None:
    if _is_postgres():
        op.execute(f"DROP TRIGGER IF EXISTS trg_psa_immutable ON {TABLE}")
        op.execute("DROP FUNCTION IF EXISTS product_sustainability_attributes_immutable()")
        return
    if op.get_context().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_psa_immutable_update")
        op.execute("DROP TRIGGER IF EXISTS trg_psa_immutable_delete")
