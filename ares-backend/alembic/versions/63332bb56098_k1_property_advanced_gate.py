"""K1 Property-Gate: Owner-Review-Spalte und Neutralisierung von Altwerten.

Codex-Entscheid 2026-11-19 ("Bis P1-Schliessung hart deaktivieren"): aktive
Werte deaktivierter Property-/Collateral-Funktionen im Bestand werden auf
Ignorieren/false/0 gesetzt und je Position als Owner-Review-Fall in der neuen
Spalte ``wealth_positions.property_gate_review_json`` festgehalten (alter Wert,
Aktion) -- nicht still verworfen:

* ``is_available_for_goal_funding = 1`` auf illiquiden Positionen -> 0;
* ``goal_funding_method`` Belehnung (jede Position) bzw. Verkauf/Automatisch
  (illiquide Positionen) -> ``Ignorieren``;
* ``mortgage_amortization_rappen > 0`` -> 0 (keine Amortisationsprojektion);
* ``asset_expected_return_bps`` einer Direktimmobilie -> NULL.

Altbestand mit Hypothekartyp "Gemischt" bleibt unveraendert und wird offen
gemeldet. Gleiche Logik wie der SQLite-Startpfad
(``services.property_advanced_gate.neutralize_legacy_property_values``); gleiche
Spalte wie ORM (``models/wealth.py``), Bootstrap (``ares_schema.sql``) und
SQLite-Laufzeitpatch (``database.ensure_runtime_columns``).

Downgrade entfernt nur die Spalte; neutralisierte Werte werden bewusst nicht
zurueckgeschrieben (die alten Werte stehen im Review-JSON, das mit der Spalte
entfaellt -- deshalb vor einem Downgrade exportieren).

Lineare Kette ... P4 ``24e7606245d3`` -> K1 (diese Revision).

Revision ID: 63332bb56098
Revises: 24e7606245d3
Create Date: 2026-11-19
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

from services.property_advanced_gate import neutralize_legacy_property_values
from services.tenant_context import BYPASS_GUC


revision: str = "63332bb56098"
down_revision: Union[str, Sequence[str], None] = "24e7606245d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("wealth_positions", sa.Column("property_gate_review_json", sa.String(), nullable=True))
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # wealth_positions hat FORCE RLS: Bestand vollstaendig ueber den
        # Operator-Bypass (nur fuer diese Transaktion) migrieren.
        op.execute(sa.text(f"SELECT set_config('{BYPASS_GUC}', 'on', true)"))
    neutralize_legacy_property_values(bind)


def downgrade() -> None:
    op.drop_column("wealth_positions", "property_gate_review_json")
