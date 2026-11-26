"""Kunden-Quellbezeichnung der Nachhaltigkeitsnachweise als Katalogwert.

Audit 2026-11 / 05, Paket T1, Delta-Pruefungen #863 N-863-6/-8/-9:
``client_source_label`` ist kein Freitext mehr, sondern ein Katalogwert, der
fest an ``source_type`` gebunden ist (Texte in
``models.product_eligibility.SUSTAINABILITY_CLIENT_SOURCE_LABELS``).

N-863-9 (fail-closed): Diese Revision aendert KEINE Daten und setzt keinen
Trigger aus. Gibt es Zeilen, deren Label nicht dem Katalog bzw. nicht dem
Quellentyp entspricht, bricht sie mit einer klaren Meldung ab; die
Bereinigung ist dann eine bewusste, auditierte Handlung. Das Feld entsteht
erst in diesem Paket (f2d6b8c0e4a3), der Bestand ist ausserhalb von Test-
und Entwicklungs-DBs leer.

- Postgres: CHECK ``ck_psa_client_source_label`` (ADD CONSTRAINT prueft den
  Bestand ebenfalls und scheitert bei Verstoessen).
- SQLite (Alembic-Pfad, nur Tests): nur die Bestandspruefung; ein
  nachtraeglicher CHECK braeuchte einen Tabellenneubau, der die
  Unveraenderlichkeits-Trigger verlieren wuerde. Die Desktop-Installation
  (create_all) bekommt den CHECK aus dem ORM, die API prueft immer.
- Downgrade: CHECK entfernen (Postgres).

Revision ID: b4f8d0e2a6c3
Revises: a3e7c9d1f5b4
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4f8d0e2a6c3"
down_revision: Union[str, Sequence[str], None] = "a3e7c9d1f5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "product_sustainability_attributes"
CODES = (
    "prospectus", "fund_contract", "kid", "factsheet", "provider_exclusion_policy",
    "provider_confirmation", "data_vendor", "house_analysis",
)
_IN = ", ".join(f"'{c}'" for c in CODES)
CHECK_SQL = (
    f"client_source_label IS NULL OR (client_source_label = source_type AND client_source_label IN ({_IN}))"
)
VIOLATIONS_SQL = f"SELECT id, source_type, client_source_label, status FROM {TABLE} WHERE NOT ({CHECK_SQL})"


class ClientSourceLabelMigrationError(RuntimeError):
    """Bestand verletzt den Katalog -- Migration bricht fail-closed ab."""


def _assert_no_violations() -> None:
    if getattr(op.get_context(), "as_sql", False):
        return  # Offline-DDL: in Postgres prueft ADD CONSTRAINT den Bestand.
    rows = op.get_bind().execute(sa.text(VIOLATIONS_SQL + " LIMIT 20")).fetchall()
    if not rows:
        return
    listed = ", ".join(f"{r[0]} ({r[3]}: {r[1]} / {r[2]!r})" for r in rows)
    drafts = [r for r in rows if r[3] == "draft"]
    locked = [r for r in rows if r[3] != "draft"]
    steps = []
    if drafts:
        steps.append(
            "Entwuerfe: client_source_label auf den Quellentyp setzen oder leeren "
            "(z. B. UPDATE product_sustainability_attributes SET client_source_label = NULL "
            "WHERE status = 'draft' AND id IN (...)) oder den Entwurf loeschen."
        )
    if locked:
        steps.append(
            "Freigegebene/zurueckgezogene Nachweise sind per Trigger unveraenderlich und "
            "koennen nicht korrigiert werden. Entwicklungs-/Test-DB: neu aufsetzen (Datei bzw. "
            "Schema loeschen und 'alembic upgrade head' erneut ausfuehren). Produktiv kann dieser "
            "Fall nicht auftreten: das Feld entsteht erst in diesem Paket (f2d6b8c0e4a3) und die "
            "API schreibt nur den aus dem Quellentyp abgeleiteten Wert; sonst nicht weiter "
            "migrieren und den Betrieb informieren (keine Trigger-Aussetzung)."
        )
    raise ClientSourceLabelMigrationError(
        "b4f8d0e2a6c3 abgebrochen: client_source_label ausserhalb des Katalogs oder abweichend "
        f"vom Quellentyp bei {len(rows)} Nachweis(en): {listed}. " + " ".join(steps)
    )


def upgrade() -> None:
    _assert_no_violations()
    if op.get_context().dialect.name.startswith("postgresql"):
        op.create_check_constraint("ck_psa_client_source_label", TABLE, CHECK_SQL)


def downgrade() -> None:
    if op.get_context().dialect.name.startswith("postgresql"):
        op.drop_constraint("ck_psa_client_source_label", TABLE, type_="check")
