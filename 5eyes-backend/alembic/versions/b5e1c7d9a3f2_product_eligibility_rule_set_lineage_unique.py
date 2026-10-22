"""Unique find-or-create key for product eligibility rule sets (ELIG-GOVERNANCE-001).

Revision ID: b5e1c7d9a3f2
Revises: d7b3f1a9c2e4
Create Date: 2026-10-21

services.product_eligibility.ensure_rule_set() finds-or-creates one rule
set per (tenant_scope, tenant_id, jurisdiction, created_by). Until now that
check-then-insert had no database-level backing: two concurrent requests
could both pass the lookup and insert two rule sets for the same lineage.

Two partial unique indexes because NULL compares as distinct in unique
indexes on both SQLite and PostgreSQL (global rule sets carry tenant_id
NULL on SQLite). An installation that already holds duplicate lineages
fails loudly here instead of silently picking a winner -- same
fail-closed convention as f2c8a4e9b1d3.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b5e1c7d9a3f2"
down_revision: Union[str, Sequence[str], None] = "d7b3f1a9c2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ux_product_eligibility_rule_sets_lineage_tenant",
        "product_eligibility_rule_sets",
        ["tenant_scope", "tenant_id", "jurisdiction", "created_by", "version"],
        unique=True,
        sqlite_where=sa.text("tenant_id IS NOT NULL"),
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )
    op.create_index(
        "ux_product_eligibility_rule_sets_lineage_global",
        "product_eligibility_rule_sets",
        ["tenant_scope", "jurisdiction", "created_by", "version"],
        unique=True,
        sqlite_where=sa.text("tenant_id IS NULL"),
        postgresql_where=sa.text("tenant_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_product_eligibility_rule_sets_lineage_global",
        table_name="product_eligibility_rule_sets",
    )
    op.drop_index(
        "ux_product_eligibility_rule_sets_lineage_tenant",
        table_name="product_eligibility_rule_sets",
    )
