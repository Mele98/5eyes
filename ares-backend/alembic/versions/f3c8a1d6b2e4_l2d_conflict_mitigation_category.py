"""L2d (N-938-01): Massnahme eines Interessenkonflikts als Kategorie.

``conflict_of_interest_disclosures.mitigation_action`` war nur im
Desktop-Schema (ares_schema.sql) eine CHECK-Liste. Auf Postgres nahm die
Spalte jeden Freitext an; dieser stand unversiegelt in der Zeile und im
Audit-Log. Ab L2d gilt dieselbe Liste ueberall (API-``Literal``, ORM,
Postgres-CHECK ``ck_coi_mitigation_action``, Classic-Auswahlliste).

Fail-closed (gleiches Muster wie b4f8d0e2a6c3): Diese Revision aendert KEINE
Daten. Gibt es Zeilen mit einem Wert ausserhalb der Liste, bricht sie mit
einer klaren Meldung ab. Begruendung:
- Eine automatische Zuordnung eines Freitexts zu einer Kategorie waere eine
  erfundene fachliche Aussage (welche Massnahme getroffen wurde).
- Ein Versiegeln in ein neues Feld braeuchte ein weiteres versiegeltes Feld in
  Siegel, Auskunft und Loeschinventar -- fuer einen Bestand, den es nicht
  geben kann: Auf SQLite (Desktop) galt die CHECK-Liste schon immer, und eine
  Server-Installation (Postgres) ist vor dem Launch nicht in Betrieb.
- Die Meldung nennt die betroffenen Zeilen (ID, nicht den Text). Die
  Bereinigung ist eine bewusste Handlung des Betriebs: Freitext sichern, in
  die Beschreibung uebernehmen oder eine Kategorie waehlen, dann erneut
  migrieren.

- Postgres: CHECK (ADD CONSTRAINT prueft den Bestand zusaetzlich).
- SQLite (Alembic-Pfad, nur Tests): nur die Bestandspruefung; ein
  nachtraeglicher CHECK braeuchte einen Tabellenneubau. Die Desktop-
  Installation hat den CHECK aus ares_schema.sql, create_all aus dem ORM.
- Downgrade: CHECK entfernen (Postgres).

Revision ID: f3c8a1d6b2e4
Revises: e2b7c4d9a1f3 (L2c)
Create Date: 2026-11-22
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3c8a1d6b2e4"
down_revision: Union[str, Sequence[str], None] = "e2b7c4d9a1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "conflict_of_interest_disclosures"
CONSTRAINT = "ck_coi_mitigation_action"
# Eingefroren (Migrationen importieren keine veraenderlichen Modelle); ein Test
# prueft die Gleichheit mit models.review.CONFLICT_MITIGATION_ACTIONS und
# ares_schema.sql.
ACTIONS = (
    "Weitergabe an Kunden",
    "Ablehnung",
    "Offenlegung ohne Mitigation",
    "Strukturelle Massnahme",
)
CHECK_SQL = "mitigation_action IS NULL OR mitigation_action IN (" + ", ".join(f"'{a}'" for a in ACTIONS) + ")"


class ConflictMitigationMigrationError(RuntimeError):
    """Bestand ausserhalb der Kategorien -- Migration bricht fail-closed ab."""


def _assert_no_violations() -> None:
    if getattr(op.get_context(), "as_sql", False):
        return  # Offline-DDL: Postgres prueft den Bestand bei ADD CONSTRAINT.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Owner-Lauf ueber alle Mandanten (RLS-Bypass nur fuer diese Transaktion).
        from services.tenant_context import BYPASS_GUC

        bind.execute(sa.text(f"SELECT set_config('{BYPASS_GUC}', 'on', true)"))
    rows = bind.execute(sa.text(f"SELECT id FROM {TABLE} WHERE NOT ({CHECK_SQL}) ORDER BY id LIMIT 20")).fetchall()
    if not rows:
        return
    total = bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE} WHERE NOT ({CHECK_SQL})")).scalar()
    raise ConflictMitigationMigrationError(
        f"f3c8a1d6b2e4 abgebrochen: {total} Interessenkonflikt(e) mit einer Massnahme ausserhalb der "
        f"Kategorien ({', '.join(ACTIONS)}). Betroffene IDs: {', '.join(str(r[0]) for r in rows)}. "
        "Es wird nichts automatisch zugeordnet. Den Text je Zeile sichern bzw. in die Beschreibung "
        "uebernehmen, dann eine Kategorie setzen oder leeren und erneut migrieren."
    )


def upgrade() -> None:
    _assert_no_violations()
    if op.get_context().dialect.name.startswith("postgresql"):
        op.create_check_constraint(CONSTRAINT, TABLE, CHECK_SQL)


def downgrade() -> None:
    if op.get_context().dialect.name.startswith("postgresql"):
        op.drop_constraint(CONSTRAINT, TABLE, type_="check")
