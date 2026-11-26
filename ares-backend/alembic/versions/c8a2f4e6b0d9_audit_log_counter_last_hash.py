"""audit_log_sequence_counter.last_hash: Verkettung ohne Lesen von audit_log.

N-869-4 (Pruefrunde #869): ``services.audit.log()`` las den Vorgaenger-Hash
per ``SELECT ... FROM audit_log WHERE sequence = N-1``. ``audit_log`` traegt
``tenant_id`` und steht unter PostgreSQL unter der strikten RLS-Policy
(``services/postgres_rls.py``): bei einem Tenant-Wechsel (oder einem
Vorgaenger ohne tenant_id) war der Vorgaenger unsichtbar, ``previous_hash``
wurde ``''`` und die Kette brach bei jedem Wechsel.

Neu fuehrt die Zaehlerzeile (system_only, keine RLS) den Hash des letzten
Eintrags mit, atomar mit ``value`` unter demselben Row-Lock fortgeschrieben.

Upgrade: Spalte anlegen und einmalig aus der Zeile mit ``sequence = value``
nachtragen. ``audit_log`` hat FORCE ROW LEVEL SECURITY, die Policy gilt also
auch fuer den Tabellen-Owner -- der Nachtrag laeuft deshalb unter dem
expliziten Operator-Bypass (``SET LOCAL app.rls_bypass = 'on'``, nur in
dieser Transaktion). Gleiche Anweisung wie ``database.py::
_COUNTER_LAST_HASH_BACKFILL_SQL`` (SQLite-Pfad).

Downgrade: Spalte entfernen; ``log()`` faellt dann (Code-Stand davor) auf das
Lesen des Vorgaengers zurueck.

Revision ID: c8a2f4e6b0d9
Revises: b5e1d3f7a9c4
Create Date: 2026-11-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c8a2f4e6b0d9"
down_revision: Union[str, Sequence[str], None] = "b5e1d3f7a9c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BACKFILL_SQL = (
    "UPDATE audit_log_sequence_counter SET last_hash = ("
    "SELECT a.integrity_hash FROM audit_log a "
    "WHERE a.sequence = audit_log_sequence_counter.value ORDER BY a.id LIMIT 1) "
    "WHERE id = 'singleton' AND last_hash IS NULL AND value > 0"
)


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    op.add_column(
        "audit_log_sequence_counter",
        sa.Column("last_hash", sa.String(length=64), nullable=True),
    )
    if _is_postgres():
        op.execute("SET LOCAL app.rls_bypass = 'on'")
    op.execute(BACKFILL_SQL)
    if _is_postgres():
        op.execute("SET LOCAL app.rls_bypass = 'off'")


def downgrade() -> None:
    op.drop_column("audit_log_sequence_counter", "last_hash")
