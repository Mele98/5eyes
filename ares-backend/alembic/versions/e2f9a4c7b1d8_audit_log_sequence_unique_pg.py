"""audit_log.sequence: UNIQUE unter PostgreSQL (zweite Verteidigungslinie).

H-865-3 (Dok. 86, Pruefrunde #865): services/audit.py::log() vergibt
``sequence`` unter der Zeilensperre auf ``audit_log_sequence_counter``; die
Lock-Argumentation traegt auch ohne Index. Der Index macht einen kuenftigen
Regress (doppelt vergebene Sequenz) aber sofort als Fehler sichtbar, statt
die Kette still zu gabeln.

Es gibt EINE globale Kette ueber alle Tenants (ein Zaehler, ein
``last_hash``), keine Teilkette pro Tenant. Der Index ist deshalb global und
nicht nach ``tenant_id`` partitioniert. Altzeilen vor SEC-003 haben
``sequence IS NULL`` und fallen nicht unter den Index.

Fail-closed: Vor dem Anlegen prueft die Revision (im RLS-Operator-Bypass,
damit FORCE-RLS-Zeilen mitzaehlen) auf doppelte Sequenzen und bricht mit der
Liste ab. Eine Reparatur ist bewusst KEIN Migrationsschritt (audit_log ist
unveraenderlich); der Befund gehoert zum Betreiber.

SQLite (Desktop) bleibt unveraendert: dort weist ``trg_audit_log_no_replace``
eine vergebene Sequenz ab, ``idx_audit_sequence`` beschleunigt die Pruefung.

Revision ID: e2f9a4c7b1d8
Revises: d3b7f1a5c9e2
Create Date: 2026-11-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

from services.tenant_context import BYPASS_GUC


revision: str = "e2f9a4c7b1d8"
down_revision: Union[str, Sequence[str], None] = "d3b7f1a5c9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ux_audit_log_sequence"
_WHERE = "sequence IS NOT NULL"
_DUPLICATES_SQL = (
    "SELECT sequence, count(*) AS n FROM audit_log WHERE sequence IS NOT NULL "
    "GROUP BY sequence HAVING count(*) > 1 ORDER BY sequence LIMIT 50"
)


def _dialect() -> str:
    if context.is_offline_mode():
        return context.get_context().dialect.name
    return op.get_bind().dialect.name


def upgrade() -> None:
    if _dialect() != "postgresql":
        return
    if not context.is_offline_mode():
        bind = op.get_bind()
        bind.execute(sa.text(f"SELECT set_config('{BYPASS_GUC}', 'on', true)"))
        duplicates = bind.execute(sa.text(_DUPLICATES_SQL)).all()
        if duplicates:
            listed = ", ".join(f"{int(seq)} ({int(n)}x)" for seq, n in duplicates)
            raise RuntimeError(
                "H-865-3-Migration abgebrochen: audit_log enthaelt doppelt vergebene "
                f"Sequenznummern: {listed}. Die Audit-Kette ist gegabelt; bitte "
                "verify_audit_chain ausfuehren und den Befund klaeren. audit_log ist "
                "unveraenderlich, die Migration repariert nichts."
            )
    op.create_index(
        INDEX_NAME,
        "audit_log",
        ["sequence"],
        unique=True,
        postgresql_where=sa.text(_WHERE),
    )


def downgrade() -> None:
    if _dialect() != "postgresql":
        return
    op.drop_index(INDEX_NAME, table_name="audit_log")
