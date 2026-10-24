"""Berater-Bestaetigung eines Alt-Prognose-Horizonts.

SIM-HORIZON-CONFIRM-001 (2026-10-17).

Bis SIM-HORIZON-ALWAYS-EXPLICIT-001 (#611) schrieb der Monolith
`simulation.horizonYears` IMMER in die Anlagepraeferenzen -- den Select-
Default '10' bzw. die flache Lebenserwartung. Ein so gespeicherter Horizont
ist keine belegte Berater-Wahl. CIO-Entscheid: KEINE automatische Migration
dieser Werte; der Berater bestaetigt (oder aendert) sie einmalig.

`target_allocations.preferences_json` ist Teil des `allocation_context_hash`
und wird NICHT veraendert. Die Bestaetigung wird daher in eigenen Spalten
neben dem Snapshot vermerkt. NULL = nicht bestaetigt -- fuer alle
Bestandszeilen korrekt: niemand hat sie bestaetigt, und ein rueckwirkendes
Befuellen waere eine Erfindung.

Revision ID: e7b2c9d41f08
Revises: c4e9a1f73b28
Create Date: 2026-10-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7b2c9d41f08"
down_revision: Union[str, Sequence[str], None] = "c4e9a1f73b28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "target_allocations"
_COLUMNS = ("sim_horizon_confirmed_at", "sim_horizon_confirmed_by")


def _existing_columns() -> set[str] | None:
    """Vorhandene Spalten -- oder None, wenn nicht introspizierbar.

    Gleiche Begruendung wie in c4e9a1f73b28: unter `alembic upgrade --sql`
    ist der Bind eine `MockConnection`; das SQL-Skript soll die Anweisungen
    ENTHALTEN statt sie anhand eines unbekannten Zustands wegzulassen.
    """
    context = op.get_context()
    if getattr(context, "as_sql", False):
        return None
    return {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(_TABLE)
    }


def upgrade() -> None:
    existing = _existing_columns()
    for column in _COLUMNS:
        if existing is not None and column in existing:
            continue
        op.add_column(_TABLE, sa.Column(column, sa.String(), nullable=True))


def downgrade() -> None:
    existing = _existing_columns()
    for column in reversed(_COLUMNS):
        if existing is not None and column not in existing:
            continue
        op.drop_column(_TABLE, column)
