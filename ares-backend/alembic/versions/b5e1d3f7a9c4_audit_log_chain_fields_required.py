"""PostgreSQL: neue audit_log-Zeilen muessen Teil der Hash-Kette sein.

N-869-3 (Pruefrunde #869): Der Architektur-Test (tests/test_audit_log_single_
writer.py) faengt versehentliche Schreibzugriffe an ``services.audit.log()``
vorbei nur im Review ab. Der eigentliche Schutz liegt in der Datenbank: eine
CHECK-Constraint verlangt fuer jede NEUE Zeile ``sequence``,
``integrity_hash`` und ``previous_hash`` (bei der Genesis ``''``, nie NULL).

``NOT VALID``: bestehende Altzeilen ohne sequence (vor SEC-003, sowie die
BACKFILL-Zeilen vor N-865-2) bleiben unveraendert und werden nicht geprueft
-- ein UPDATE verbieten ohnehin die Unveraenderlichkeits-Trigger. Geprueft
wird jedes INSERT ab jetzt.

SQLite: dort erzwingt der Trigger ``trg_audit_log_require_chain``
(database.py::_AUDIT_LOG_TRIGGER_DDL) dasselbe; Alembic laeuft fuer SQLite
nicht im Boot-Pfad, die Revision ist dort ein No-op.

Revision ID: b5e1d3f7a9c4
Revises: b4f8d0e2a6c3
Create Date: 2026-11-05
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "b5e1d3f7a9c4"
down_revision: Union[str, Sequence[str], None] = "b4f8d0e2a6c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ck_audit_log_chain_fields_required"


def _is_postgres() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    op.execute(
        f"ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS {CONSTRAINT_NAME}"
    )
    op.execute(
        f"ALTER TABLE audit_log ADD CONSTRAINT {CONSTRAINT_NAME} CHECK ("
        "sequence IS NOT NULL AND integrity_hash IS NOT NULL AND previous_hash IS NOT NULL"
        ") NOT VALID"
    )


def downgrade() -> None:
    if not _is_postgres():
        return
    op.execute(f"ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS {CONSTRAINT_NAME}")
