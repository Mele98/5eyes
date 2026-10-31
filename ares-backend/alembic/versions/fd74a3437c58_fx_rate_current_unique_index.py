"""Enforce a unique current FX-rate row per currency.

Revision ID: fd74a3437c58
Revises: c3d8f4a1e6b2
Create Date: 2026-09-04

FX-REF-001 (Marktpreis-/FX-Referenzintegritaetsaudit, 2026-08-27): the
"at most one is_current=1 row per currency" invariant on ``fx_rates`` was
previously enforced only in application code
(``routers/fx_rates.py::upsert_fx_rates``, via ``with_for_update()`` plus
manual invalidation of old rows). That protects the common single-writer
path but is not an atomic database guarantee: a bug elsewhere, a direct DB
write, or two genuinely concurrent first-writers for a currency that has no
existing current row yet (nothing for ``FOR UPDATE`` to lock) could leave two
effective current rows behind. The model loader
(``FXRateSource.from_db_for_model``) and the legacy/reporting loader
(``FXRateSource.from_db``) would then be free to pick different rows,
silently diverging on the effective FX basis.

This mirrors the exact pattern already established for other "current
anchor" tables in d4e8f1a9c2b7_current_anchor_unique_indexes.py
(risk_assessments, target_allocations, optimizer_policies).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "fd74a3437c58"
down_revision: Union[str, Sequence[str], None] = "c3d8f4a1e6b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ux_fx_rate_one_current",
        "fx_rates",
        ["currency"],
        unique=True,
        sqlite_where=sa.text("is_current = 1 AND valid_until IS NULL"),
        postgresql_where=sa.text("is_current = 1 AND valid_until IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_fx_rate_one_current", table_name="fx_rates")
