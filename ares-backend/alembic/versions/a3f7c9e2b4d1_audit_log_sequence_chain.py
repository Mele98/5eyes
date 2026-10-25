"""Add atomic sequence/previous_hash chain to audit_log (SEC-003).

Revision ID: a3f7c9e2b4d1
Revises: f2c8a4e9b1d3
Create Date: 2026-08-28

SEC-003 (Codex-Audit 2026-08-26): services/audit.py::log() determined the
"previous" entry via ORDER BY created_at DESC, id DESC with no lock or
sequence. Two near-simultaneous calls could both read the same latest row
and both compute a hash chained from it -- a fork instead of a linear
chain. `integrity_hash` alone was persisted; `previous_hash` was baked
into the hash payload but never stored on its own, so the chain could
only be reconstructed (unreliably) via timestamp ordering.

This migration adds:
- `audit_log.sequence` (nullable INTEGER) and `audit_log.previous_hash`
  (nullable VARCHAR(64)). NULL for all pre-migration rows -- the existing
  audit_log immutability triggers (trg_audit_log_no_update /
  trg_audit_log_no_delete) intentionally forbid retroactively backfilling
  historical rows. Historical rows remain tamper-evident per-row via
  their existing `integrity_hash`; they do not retroactively claim the
  new strict linear-chain guarantee. The new sequence contract starts
  with the first audit-log entry written after this migration.
- `audit_log_sequence_counter`, a single-row table used by
  services/audit.py::_claim_next_audit_sequence() to atomically claim the
  next sequence number via `UPDATE ... SET value = value + 1`. The write
  lock held by that UPDATE (row lock on PostgreSQL, whole-file lock on
  SQLite until commit) serializes concurrent log() calls for real,
  instead of relying on an unlocked SELECT.

See models/review.py::AuditLog.sequence / AuditLogSequenceCounter for the
full design rationale.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3f7c9e2b4d1"
down_revision: Union[str, Sequence[str], None] = "f2c8a4e9b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("sequence", sa.Integer(), nullable=True))
    op.add_column("audit_log", sa.Column("previous_hash", sa.String(64), nullable=True))
    op.create_table(
        "audit_log_sequence_counter",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False),
    )
    op.execute(
        "INSERT INTO audit_log_sequence_counter (id, value) VALUES ('singleton', 0)"
    )


def downgrade() -> None:
    op.drop_table("audit_log_sequence_counter")
    op.drop_column("audit_log", "previous_hash")
    op.drop_column("audit_log", "sequence")
