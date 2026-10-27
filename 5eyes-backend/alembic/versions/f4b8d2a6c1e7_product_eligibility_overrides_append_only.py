"""product_eligibility_overrides append-only + approval_mode.

ELIG-OVERRIDE-APPEND-ONLY-001 / ELIG-OVERRIDE-SINGLE-APPROVER-001 (CIO
decisions 2026-10-27, follow-up to ELIG-OVERRIDE-CAPTURE-001):

* UPDATE/DELETE on ``product_eligibility_overrides`` are rejected by a
  trigger (SQLite and PostgreSQL). The capture workflow only inserts
  (request row, then approval row); no status transition is needed.
* The hard FK ``recommendation_run_id -> recommendation_runs`` is dropped,
  like on every other append-only evidence table (Purge-fest): the demo
  purge and the draft-run cleanup hard-delete runs; the evidence stays.
* New nullable column ``approval_mode`` ('four_eyes' |
  'single_approver_attested').

Shared DDL: services/product_eligibility_override_schema.py.

Revision ID: f4b8d2a6c1e7
Revises: a7c4e9b2d1f3
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from services import product_eligibility_override_schema as schema


revision: str = "f4b8d2a6c1e7"
down_revision: Union[str, Sequence[str], None] = "a7c4e9b2d1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        # Rebuild without the run FK, add approval_mode, install triggers.
        schema.ensure_sqlite_override_append_only(op.get_bind())
        return
    op.execute(f"ALTER TABLE {schema.TABLE} DROP CONSTRAINT IF EXISTS {schema.POSTGRES_RUN_FK_NAME}")
    op.add_column(schema.TABLE, sa.Column("approval_mode", sa.String(), nullable=True))
    if dialect == "postgresql":
        op.execute(schema.POSTGRES_FUNCTION)
        op.execute(schema.POSTGRES_TRIGGER)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {schema.POSTGRES_TRIGGER_NAME} ON {schema.TABLE}")
        op.execute(f"DROP FUNCTION IF EXISTS {schema.POSTGRES_FUNCTION_NAME}()")
    elif dialect == "sqlite":
        # The run FK is not rebuilt on SQLite (orphaned evidence rows of
        # purged runs would make it fail); triggers and column are reverted.
        for name in schema.SQLITE_TRIGGER_NAMES:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_column(schema.TABLE, "approval_mode")
    if dialect == "postgresql":
        # NOT VALID: evidence rows of purged runs may remain (append-only).
        op.execute(
            f"ALTER TABLE {schema.TABLE} ADD CONSTRAINT {schema.POSTGRES_RUN_FK_NAME} "
            "FOREIGN KEY (recommendation_run_id) REFERENCES recommendation_runs (id) NOT VALID"
        )
