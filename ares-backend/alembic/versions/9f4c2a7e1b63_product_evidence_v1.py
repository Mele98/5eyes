"""C-COMP-02: granular product evidence and immutable run snapshot.

Revision ID: 9f4c2a7e1b63
Revises: d3b7e1f9a5c2
Create Date: 2026-11-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "9f4c2a7e1b63"
down_revision: Union[str, Sequence[str], None] = "d3b7e1f9a5c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KINDS = (
    "instrument_identity", "kid", "costs", "retrocession", "suitability",
    "liquidity", "currency", "sustainability", "price_source",
)
_HASH_CHECK = (
    "length(source_document_sha256) = 64 AND length(canonical_payload_hash) = 64 "
    "AND ltrim(source_document_sha256, '0123456789abcdef') = '' "
    "AND ltrim(canonical_payload_hash, '0123456789abcdef') = ''"
)
_APPROVAL_CHECK = (
    "status = 'draft' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL AND approval_mode IS NOT NULL "
    "AND approval_mode IN ('four_eyes', 'single_approver_attested'))"
)
_FOUR_EYES_CHECK = (
    "approved_by IS NULL OR approved_by <> created_by "
    "OR COALESCE(approval_mode, '') = 'single_approver_attested'"
)
_CLOSURE_CHECK = (
    "status NOT IN ('retired', 'revoked') OR (retired_or_revoked_by IS NOT NULL "
    "AND retired_or_revoked_at IS NOT NULL AND reason_code IS NOT NULL)"
)
_TENANT_MISMATCH = (
    "EXISTS (SELECT 1 FROM products p WHERE p.id = NEW.product_id AND p.tenant_id IS NOT NULL "
    "AND (NEW.tenant_id IS NULL OR p.tenant_id <> NEW.tenant_id))"
)
_TENANT_MESSAGE = "product_evidence_items: Produkt und Nachweis gehoeren zu verschiedenen Tenants"
_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')"
_BYPASS = "current_setting('app.rls_bypass', true) = 'on'"
# Identisch zu services/postgres_rls.py (Test sichert die Deckung).
_READ = f"(tenant_id::text = {_TENANT} OR tenant_id IS NULL OR {_BYPASS})"
_WRITE = f"(tenant_id::text = {_TENANT} OR {_BYPASS})"
ITEMS_TABLE = "product_evidence_items"


def upgrade() -> None:
    op.create_table(
        "product_evidence_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id")),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("stable_instrument_id", sa.String(), nullable=False),
        sa.Column("share_class_id", sa.String()),
        sa.Column("jurisdiction", sa.String(), nullable=False),
        sa.Column("evidence_kind", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_reference", sa.String(), nullable=False),
        sa.Column("source_document_title", sa.String(), nullable=False),
        sa.Column("source_document_version", sa.String()),
        sa.Column("source_document_date", sa.String()),
        sa.Column("retrieved_at", sa.String(), nullable=False),
        sa.Column("source_document_sha256", sa.String(), nullable=False),
        sa.Column("canonical_payload_json", sa.String(), nullable=False),
        sa.Column("canonical_payload_hash", sa.String(), nullable=False),
        sa.Column("as_of", sa.String(), nullable=False),
        sa.Column("valid_from", sa.String(), nullable=False),
        sa.Column("valid_until", sa.String()),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("note", sa.String()),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.String()),
        sa.Column("approval_mode", sa.String()),
        sa.Column("supersedes_id", sa.String(), sa.ForeignKey("product_evidence_items.id")),
        sa.Column("retired_or_revoked_by", sa.String(), sa.ForeignKey("users.id")),
        sa.Column("retired_or_revoked_at", sa.String()),
        sa.Column("reason_code", sa.String()),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint("status IN ('draft','approved','retired','revoked')", name="ck_product_evidence_item_status"),
        sa.CheckConstraint("evidence_kind IN (" + ",".join(repr(kind) for kind in _KINDS) + ")", name="ck_product_evidence_item_kind"),
        sa.CheckConstraint("valid_until IS NULL OR valid_until >= valid_from", name="ck_product_evidence_item_validity"),
        sa.CheckConstraint(_HASH_CHECK, name="ck_product_evidence_item_hash_hex"),
        sa.CheckConstraint(_APPROVAL_CHECK, name="ck_product_evidence_item_approval"),
        sa.CheckConstraint(_FOUR_EYES_CHECK, name="ck_product_evidence_item_four_eyes"),
        sa.CheckConstraint(_CLOSURE_CHECK, name="ck_product_evidence_item_closure"),
    )
    op.create_index("ix_product_evidence_item_lookup", "product_evidence_items", ["product_id", "tenant_id", "jurisdiction", "evidence_kind", "status"])
    op.create_index(
        "ux_product_evidence_item_active_tenant", "product_evidence_items",
        ["product_id", "stable_instrument_id", sa.text("COALESCE(share_class_id, '')"), "tenant_id", "jurisdiction", "evidence_kind", "as_of"], unique=True,
        sqlite_where=sa.text("tenant_id IS NOT NULL AND status = 'approved'"),
        postgresql_where=sa.text("tenant_id IS NOT NULL AND status = 'approved'"),
    )
    op.create_index(
        "ux_product_evidence_item_active_global", "product_evidence_items",
        ["product_id", "stable_instrument_id", sa.text("COALESCE(share_class_id, '')"), "jurisdiction", "evidence_kind", "as_of"], unique=True,
        sqlite_where=sa.text("tenant_id IS NULL AND status = 'approved'"),
        postgresql_where=sa.text("tenant_id IS NULL AND status = 'approved'"),
    )

    op.create_table(
        "product_evidence_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("recommendation_run_id", sa.String(), nullable=False),
        sa.Column("product_ids_json", sa.String(), nullable=False),
        sa.Column("item_ids_json", sa.String(), nullable=False),
        sa.Column("item_hashes_json", sa.String(), nullable=False),
        sa.Column("eligibility_snapshot_id", sa.String()),
        sa.Column("cost_snapshot_id", sa.String()),
        sa.Column("conflict_snapshot_id", sa.String()),
        sa.Column("as_of", sa.String(), nullable=False),
        sa.Column("evaluated_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason_codes_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("canonical_payload_json", sa.String(), nullable=False),
        sa.Column("product_evidence_hash", sa.String(), nullable=False, unique=True),
        sa.Column("schema_version", sa.String(), nullable=False, server_default="ares-product-evidence/v1"),
        sa.Column("evaluator_version", sa.String(), nullable=False, server_default="ares-product-evidence/1"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint("status IN ('verified','missing','stale','conflict','revoked','hash_mismatch')", name="ck_product_evidence_snapshot_status"),
    )
    op.create_index("ix_product_evidence_snapshot_run", "product_evidence_snapshots", ["recommendation_run_id"])

    # SQLite-Batch-Rebuild ist hier unzulaessig: bestehende Tenant-Guard-
    # Trigger referenzieren recommendation_runs und verhindern das temporaere
    # Umbenennen. Additive Spalten funktionieren nativ; PostgreSQL erhaelt
    # zusaetzlich den echten FK. Die Anwendung erzwingt die Bindung auch auf
    # SQLite fail-closed ueber assert_run_product_evidence().
    op.add_column("recommendation_runs", sa.Column("product_evidence_snapshot_id", sa.String()))
    op.add_column("recommendation_runs", sa.Column("product_evidence_hash", sa.String()))
    op.add_column("recommendation_runs", sa.Column("product_evidence_status", sa.String()))
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_recommendation_runs_product_evidence_snapshot",
            "recommendation_runs", "product_evidence_snapshots",
            ["product_evidence_snapshot_id"], ["id"],
        )

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER trg_product_evidence_tenant_insert BEFORE INSERT ON product_evidence_items FOR EACH ROW "
            f"WHEN {_TENANT_MISMATCH} BEGIN SELECT RAISE(ABORT, '{_TENANT_MESSAGE}'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_product_evidence_tenant_update BEFORE UPDATE OF tenant_id, product_id "
            "ON product_evidence_items FOR EACH ROW "
            f"WHEN {_TENANT_MISMATCH} BEGIN SELECT RAISE(ABORT, '{_TENANT_MESSAGE}'); END"
        )
        op.execute("""
        CREATE TRIGGER trg_product_evidence_immutable_update
        BEFORE UPDATE ON product_evidence_items FOR EACH ROW
        WHEN OLD.status <> 'draft' AND NOT (
          OLD.status = 'approved' AND NEW.status IN ('retired','revoked')
          AND NEW.id IS OLD.id AND NEW.tenant_id IS OLD.tenant_id
          AND NEW.product_id IS OLD.product_id AND NEW.stable_instrument_id IS OLD.stable_instrument_id
          AND NEW.share_class_id IS OLD.share_class_id AND NEW.jurisdiction IS OLD.jurisdiction
          AND NEW.evidence_kind IS OLD.evidence_kind AND NEW.source_type IS OLD.source_type
          AND NEW.source_reference IS OLD.source_reference
          AND NEW.source_document_title IS OLD.source_document_title
          AND NEW.source_document_version IS OLD.source_document_version
          AND NEW.source_document_date IS OLD.source_document_date
          AND NEW.retrieved_at IS OLD.retrieved_at
          AND NEW.source_document_sha256 IS OLD.source_document_sha256
          AND NEW.canonical_payload_json IS OLD.canonical_payload_json
          AND NEW.canonical_payload_hash IS OLD.canonical_payload_hash
          AND NEW.as_of IS OLD.as_of AND NEW.valid_from IS OLD.valid_from
          AND NEW.valid_until IS OLD.valid_until AND NEW.note IS OLD.note
          AND NEW.created_by IS OLD.created_by AND NEW.created_at IS OLD.created_at
          AND NEW.approved_by IS OLD.approved_by AND NEW.approved_at IS OLD.approved_at
          AND NEW.approval_mode IS OLD.approval_mode AND NEW.supersedes_id IS OLD.supersedes_id
        ) BEGIN SELECT RAISE(ABORT, 'product_evidence_items: freigegebener Nachweis ist unveränderlich'); END
        """)
        op.execute("""
        CREATE TRIGGER trg_product_evidence_immutable_delete
        BEFORE DELETE ON product_evidence_items FOR EACH ROW WHEN OLD.status <> 'draft'
        BEGIN SELECT RAISE(ABORT, 'product_evidence_items: freigegebener Nachweis ist unveränderlich'); END
        """)
        op.execute("""
        CREATE TRIGGER trg_product_evidence_snapshot_immutable_update
        BEFORE UPDATE ON product_evidence_snapshots FOR EACH ROW
        BEGIN SELECT RAISE(ABORT, 'product_evidence_snapshots: Snapshot ist unveränderlich'); END
        """)
        op.execute("""
        CREATE TRIGGER trg_product_evidence_snapshot_immutable_delete
        BEFORE DELETE ON product_evidence_snapshots FOR EACH ROW
        BEGIN SELECT RAISE(ABORT, 'product_evidence_snapshots: Snapshot ist unveränderlich'); END
        """)
    elif bind.dialect.name == "postgresql":
        _install_postgres_guards_and_rls()


def _install_postgres_guards_and_rls() -> None:
    op.execute("""
    CREATE FUNCTION product_evidence_items_immutable() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
          RAISE EXCEPTION 'product_evidence_items: freigegebener Nachweis ist unveränderlich';
        END IF;
        RETURN OLD;
      END IF;
      IF @@MISMATCH@@ THEN
        RAISE EXCEPTION '@@MESSAGE@@';
      END IF;
      IF TG_OP = 'UPDATE' AND OLD.status <> 'draft' AND NOT (
        OLD.status = 'approved' AND NEW.status IN ('retired','revoked')
        AND to_jsonb(NEW) - ARRAY['status','retired_or_revoked_by','retired_or_revoked_at','reason_code','updated_at']
          = to_jsonb(OLD) - ARRAY['status','retired_or_revoked_by','retired_or_revoked_at','reason_code','updated_at']
      ) THEN RAISE EXCEPTION 'product_evidence_items: freigegebener Nachweis ist unveränderlich'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql
    """.replace("@@MISMATCH@@", _TENANT_MISMATCH).replace("@@MESSAGE@@", _TENANT_MESSAGE))
    op.execute("CREATE TRIGGER trg_product_evidence_immutable BEFORE INSERT OR UPDATE OR DELETE ON product_evidence_items FOR EACH ROW EXECUTE FUNCTION product_evidence_items_immutable()")
    op.execute("""
    CREATE FUNCTION product_evidence_snapshots_immutable() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'product_evidence_snapshots: Snapshot ist unveränderlich'; END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER trg_product_evidence_snapshot_immutable BEFORE UPDATE OR DELETE ON product_evidence_snapshots FOR EACH ROW EXECUTE FUNCTION product_evidence_snapshots_immutable()")
    read, write = _READ, _WRITE
    op.execute("ALTER TABLE product_evidence_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE product_evidence_items FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_reference_select ON product_evidence_items FOR SELECT USING ({read})")
    op.execute(f"CREATE POLICY tenant_reference_insert ON product_evidence_items FOR INSERT WITH CHECK ({write})")
    op.execute(f"CREATE POLICY tenant_reference_update ON product_evidence_items FOR UPDATE USING ({write}) WITH CHECK ({write})")
    op.execute(f"CREATE POLICY tenant_reference_delete ON product_evidence_items FOR DELETE USING ({write})")
    op.execute("ALTER TABLE product_evidence_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE product_evidence_snapshots FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON product_evidence_snapshots USING ({write}) WITH CHECK ({write})")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS product_evidence_snapshots_immutable() CASCADE")
        op.execute("DROP FUNCTION IF EXISTS product_evidence_items_immutable() CASCADE")
        op.drop_constraint(
            "fk_recommendation_runs_product_evidence_snapshot",
            "recommendation_runs", type_="foreignkey",
        )
    op.drop_column("recommendation_runs", "product_evidence_status")
    op.drop_column("recommendation_runs", "product_evidence_hash")
    op.drop_column("recommendation_runs", "product_evidence_snapshot_id")
    op.drop_table("product_evidence_snapshots")
    op.drop_table("product_evidence_items")
