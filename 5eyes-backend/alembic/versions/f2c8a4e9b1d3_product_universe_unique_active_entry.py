"""Enforce a unique active ProductUniverseEntry per (tenant, jurisdiction, product).

Revision ID: f2c8a4e9b1d3
Revises: d4e8f1a9c2b7
Create Date: 2026-08-26

REC-008 (Codex-Audit 2026-08-25): product_universe_entries only carried a
non-unique index on (tenant_id, jurisdiction). The create endpoint
(routers/review.py::create_product_universe_entry) pre-checks for an
existing active row before inserting, but that check-then-insert has no
database-level backing -- two near-simultaneous requests for the same
(tenant_id, jurisdiction, product_id) could both pass the precheck and
both insert, leaving two active rows for the same product with
potentially different override_ter_bps. Downstream consumers
(services/cost_disclosure.py, services/portfolio_engine_payload.py::
_filter_products_by_universe) would then pick whichever row a query
happens to return first -- a nondeterministic TER/candidate pool.

Mirrors the sqlite_where/postgresql_where partial-unique-index pattern
already used for the current-anchor indexes (see d4e8f1a9c2b7). Applying
this to an existing installation that already has duplicate active rows
will fail loudly (constraint violation) instead of silently picking a
winner -- consistent with this codebase's fail-closed migration
philosophy for anchor uniqueness.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2c8a4e9b1d3"
down_revision: Union[str, Sequence[str], None] = "d4e8f1a9c2b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ux_product_universe_active_entry",
        "product_universe_entries",
        ["tenant_id", "jurisdiction", "product_id"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_product_universe_active_entry", table_name="product_universe_entries")
