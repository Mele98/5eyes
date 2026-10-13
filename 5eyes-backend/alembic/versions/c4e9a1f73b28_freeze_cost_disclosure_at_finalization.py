"""Eingefrorener Kostenausweis pro Empfehlungslauf.

COST-CONTEXT-001b / COST-EVIDENCE-001 (CERT-COST-CONFLICT-001).

`build_cost_disclosure()` rechnete bei JEDEM Aufruf neu und las dabei live
`Product.ter_bps`. Gemessen am Reproducer: eine spaetere TER-Korrektur von
50 auf 500 bps -- ohne jeden neuen Lauf -- aenderte die Totale eines bereits
FINALISIERTEN Laufs rueckwirkend. Ein Dokument, das dem Kunden nach FIDLEG
Art. 8/9 ausgehaendigt wurde, war damit nicht reproduzierbar: wer es spaeter
nachrechnet, bekommt andere Zahlen als der Kunde gesehen hat.

Dieselbe Spalte traegt den Nachweis fuer COST-EVIDENCE-001: das
Beratungsprotokoll speicherte bisher sechs reduzierte Summenfelder aus dem
MANDATSWEITEN Bauer und band weder den gewaehlten Lauf noch die Posten,
Warnungen oder einen Hash.

NULL bedeutet "nicht eingefroren" -- fuer Entwuerfe der Normalfall, und fuer
Laeufe, die vor dieser Spalte finalisiert wurden, ebenfalls. Der Leser
rechnet dann live UND legt das offen (`evidence_frozen=False`), statt eine
Reproduzierbarkeit zu behaupten, die es fuer diese Altlaeufe nicht gibt.
Rueckwirkend einzufrieren waere die falsche Richtung: der heutige Live-Wert
ist nicht der Wert von damals, und ihn als "eingefroren" zu etikettieren
waere eine Erfindung.

Revision ID: c4e9a1f73b28
Revises: b8f3d2a71c45
Create Date: 2026-10-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e9a1f73b28"
down_revision: Union[str, Sequence[str], None] = "b8f3d2a71c45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "recommendation_runs"
_COLUMN = "cost_disclosure_snapshot_json"


def _column_exists() -> bool | None:
    """True/False -- oder None, wenn nicht introspizierbar (Offline-Modus).

    Gleiche Begruendung wie in b8f3d2a71c45: unter `alembic upgrade --sql`
    ist der Bind eine `MockConnection`, und ein SQL-Skript soll die
    Anweisung ENTHALTEN statt sie anhand eines unbekannten Zustands
    weglassen.
    """
    context = op.get_context()
    if getattr(context, "as_sql", False):
        return None
    return _COLUMN in {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)
    }


def upgrade() -> None:
    exists = _column_exists()
    if exists:
        return
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(), nullable=True))


def downgrade() -> None:
    exists = _column_exists()
    if exists is False:
        return
    op.drop_column(_TABLE, _COLUMN)
