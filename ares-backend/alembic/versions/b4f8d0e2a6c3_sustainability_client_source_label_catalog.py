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
VIOLATIONS_SQL = f"SELECT id, source_type, client_source_label FROM {TABLE} WHERE NOT ({CHECK_SQL})"


class ClientSourceLabelMigrationError(RuntimeError):
    """Bestand verletzt den Katalog -- Migration bricht fail-closed ab."""


def _assert_no_violations() -> None:
    if getattr(op.get_context(), "as_sql", False):
        return  # Offline-DDL: in Postgres prueft ADD CONSTRAINT den Bestand.
    rows = op.get_bind().execute(sa.text(VIOLATIONS_SQL + " LIMIT 20")).fetchall()
    if rows:
        listed = ", ".join(f"{r[0]} ({r[1]} / {r[2]!r})" for r in rows)
        raise ClientSourceLabelMigrationError(
            "b4f8d0e2a6c3 abgebrochen: client_source_label ausserhalb des Katalogs oder abweichend "
            f"vom Quellentyp bei {len(rows)} Nachweis(en): {listed}. Bitte bewusst und auditiert "
            "bereinigen (Label auf den Quellentyp setzen oder leeren) und die Migration erneut starten."
        )


def upgrade() -> None:
    _assert_no_violations()
    if op.get_context().dialect.name.startswith("postgresql"):
        op.create_check_constraint("ck_psa_client_source_label", TABLE, CHECK_SQL)


def downgrade() -> None:
    if op.get_context().dialect.name.startswith("postgresql"):
        op.drop_constraint("ck_psa_client_source_label", TABLE, type_="check")
