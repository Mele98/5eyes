"""L2c (H-192) DSG-Vollstaendigkeit: versiegelte Protokoll-Freitexte.

- ``mandate_report_note_versions``: Berichtsnotizen als append-only Versionen
  (Versionierung statt Ueberschreiben), Freitexte mit dem Kundenschluessel
  versiegelt (services/pii_vault.py), ``content_hash`` ueber die Umschlaege.
  tenant_direct mit INSERT-Guard aus dem Mandat (Funktion
  ``mandate_evidence_tenant_from_mandate`` aus b8d4f2a6c9e1); RLS ENABLE +
  FORCE und die strikte Policy folgen beim Boot ueber
  ``ensure_postgres_rls_policies``.
- ``conflict_of_interest_disclosures.text_seal``: Siegel ueber die
  versiegelte Beschreibung und Massnahme.
- Daten: Altzeilen im Klartext werden versiegelt
  (``services.advisory_log_integrity.seal_legacy_protocol_texts``, dieselbe
  Funktion wie im SQLite-Startpfad). Protokolleintraege mit nicht passendem
  Siegel bleiben im Klartext (veraendert, die DSG-Loeschung meldet sie).

Downgrade (fail-closed): existieren versiegelte Zeilen oder Notiz-Versionen,
bricht der Downgrade ab -- ohne Schluesselpfad waeren sie fuer aeltere Staende
unlesbar bzw. wuerden vernichtet.

Revision ID: e2b7c4d9a1f3
Revises: c7e1a9d3f5b2 (H-179 L2/L3)
Create Date: 2026-11-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

from services.advisory_log_integrity import count_sealed_protocol_rows, seal_legacy_protocol_texts
from services.tenant_context import BYPASS_GUC

revision: str = "e2b7c4d9a1f3"
down_revision: Union[str, Sequence[str], None] = "c7e1a9d3f5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "mandate_report_note_versions"
PG_GUARD_FUNCTION = "mandate_evidence_tenant_from_mandate"  # aus b8d4f2a6c9e1
TENANT_ERROR = "MANDATE_EVIDENCE_TENANT_MISMATCH"
NOTE_FIELDS = (
    "aa_anmerkungen", "waehrungen_erklaerung", "branchen_analyse",
    "vorgehen_block_optimierungen", "vorgehen_block_zielstrategie",
    "vorgehen_offene_fragen_json", "vorgehen_naechster_termin",
    "vorgehen_todos_json", "vorgehen_dokumente_json",
)


def _dialect() -> str:
    if context.is_offline_mode():
        return context.get_context().dialect.name
    return op.get_bind().dialect.name


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *[sa.Column(field, sa.String(), nullable=True) for field in NOTE_FIELDS],
        sa.Column("edited_by", sa.String(), nullable=False),
        sa.Column("edited_at", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_mandate_report_note_versions_version"),
        sa.ForeignKeyConstraint(["edited_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mandate_id", "version", name="uq_mandate_report_note_versions_version"),
    )
    op.create_index("ix_mandate_report_note_versions_tenant_id", TABLE, ["tenant_id"])
    with op.batch_alter_table("conflict_of_interest_disclosures") as batch:
        batch.add_column(sa.Column("text_seal", sa.String(), nullable=True))

    dialect = _dialect()
    if dialect == "sqlite":
        op.execute(
            f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_no_update BEFORE UPDATE ON {TABLE} FOR EACH ROW "
            f"BEGIN SELECT RAISE(ABORT, '{TABLE} is immutable'); END"
        )
        op.execute(
            f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_no_delete BEFORE DELETE ON {TABLE} FOR EACH ROW "
            f"BEGIN SELECT RAISE(ABORT, '{TABLE} is immutable'); END"
        )
        op.execute(
            f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_tenant_guard BEFORE INSERT ON {TABLE} FOR EACH ROW "
            f"WHEN NEW.tenant_id IS NOT (SELECT m.tenant_id FROM mandates m WHERE m.id = NEW.mandate_id) "
            f"OR EXISTS (SELECT 1 FROM mandates m WHERE m.id = NEW.mandate_id "
            f"AND m.client_id IS NOT NEW.client_id) "
            f"BEGIN SELECT RAISE(ABORT, '{TENANT_ERROR}'); END"
        )
    elif dialect == "postgresql":
        op.execute(
            f"CREATE OR REPLACE FUNCTION {TABLE}_immutable() RETURNS trigger AS $$\n"
            "BEGIN\n"
            f"    RAISE EXCEPTION '{TABLE} is immutable';\n"
            "END;\n"
            "$$ LANGUAGE plpgsql"
        )
        op.execute(
            f"CREATE TRIGGER trg_{TABLE}_immutable BEFORE UPDATE OR DELETE ON {TABLE} "
            f"FOR EACH ROW EXECUTE FUNCTION {TABLE}_immutable()"
        )
        op.execute(
            f"CREATE TRIGGER trg_{TABLE}_tenant_guard BEFORE INSERT ON {TABLE} "
            f"FOR EACH ROW EXECUTE FUNCTION {PG_GUARD_FUNCTION}()"
        )

    if context.is_offline_mode():
        return
    if dialect == "postgresql":
        # Datenmigration ueber alle Mandanten (Owner-Lauf, RLS-Bypass nur fuer
        # diese Transaktion).
        op.execute(sa.text(f"SELECT set_config('{BYPASS_GUC}', 'on', true)"))
    seal_legacy_protocol_texts(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    found = count_sealed_protocol_rows(bind)
    if found:
        raise RuntimeError(
            "L2c Downgrade abgelehnt (fail-closed): versiegelte Protokoll-Freitexte bzw. "
            "Notiz-Versionen vorhanden: " + ", ".join(f"{t} ({n})" for t, n in sorted(found.items()))
            + ". Datenbank aus Sicherung wiederherstellen statt zurueckzumigrieren."
        )
    dialect = _dialect()
    if dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_tenant_guard ON {TABLE}")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_immutable ON {TABLE}")
        op.execute(f"DROP FUNCTION IF EXISTS {TABLE}_immutable()")
    elif dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_tenant_guard")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_delete")
    with op.batch_alter_table("conflict_of_interest_disclosures") as batch:
        batch.drop_column("text_seal")
    op.drop_index("ix_mandate_report_note_versions_tenant_id", table_name=TABLE)
    op.drop_table(TABLE)
