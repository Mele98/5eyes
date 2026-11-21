"""H-179 L2/L3 Vertragsschicht: Owner-Inhalte, Vier-Augen-Freigabe, Gruende der
Empfehlung (Art. 15 FIDLEG), W033-Kundenbestaetigung.

Dok. 112 Kap. 7.1 (V-1, A-1, D-1, R-1, P-1, E-1), Dok. 113 E-113-4/5:

- ``owner_content_versions``: versionierte Owner-Inhalte je Firma und
  Katalogschluessel (Vertragsklauseln, Datenschutzabschnitt der
  Kundeninformation, W033-Texte, Mindesthorizont, Zuwendungen der Depotbank).
  Ares legt KEINEN Inhalt an. UNIQUE (tenant_id, content_key, version).
- ``owner_content_approvals``: Vier-Augen-Freigabe je Version (zweite Person,
  gesehener Hash, Freigabereferenz, Siegel); lineare Kette je Firma/Schluessel
  (UNIQUE auf den Vorgaenger, erste Freigabe mit 'GENESIS').
- ``advice_rationales``: Kundenbeduerfnisse und Gruende der Empfehlung je
  Empfehlungslauf (P-1).
- ``w033_client_declarations``: Kundenbestaetigung je Risikoprofil-Version,
  gebunden an die gezeigte Owner-Textversion (E-1).

Alle vier Tabellen sind append-only (Trigger SQLite/PostgreSQL) und
``tenant_direct`` (RLS ENABLE + FORCE und die strikte Policy folgen beim Boot
ueber ``ensure_postgres_rls_policies``). Die beiden Mandats-Tabellen bekommen
auf PostgreSQL denselben INSERT-Guard wie die uebrige Mandats-Evidenz
(Funktion ``mandate_evidence_tenant_from_mandate`` aus b8d4f2a6c9e1). Kein FK
auf mandates/clients (Purge-fest), nur die Akteure verweisen auf users.
Neue Tabellen, kein Backfill. SQLite legt dieselben Tabellen ueber create_all
an (models/contract_layer.py).

Downgrade (fail-closed): liegt irgendeine Zeile vor, bricht der Downgrade ab
(freigegebene Owner-Inhalte und Kundenbestaetigungen sind Nachweise).

Revision ID: c7e1a9d3f5b2
Revises: 63332bb56098
Create Date: 2026-11-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "c7e1a9d3f5b2"
down_revision: Union[str, Sequence[str], None] = "63332bb56098"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("owner_content_versions", "owner_content_approvals", "advice_rationales", "w033_client_declarations")
MANDATE_GUARDED = ("advice_rationales", "w033_client_declarations")
PG_GUARD_FUNCTION = "mandate_evidence_tenant_from_mandate"  # aus b8d4f2a6c9e1
TENANT_ERROR = "MANDATE_EVIDENCE_TENANT_MISMATCH"


def _dialect() -> str:
    if context.is_offline_mode():
        return context.get_context().dialect.name
    return op.get_bind().dialect.name


def _sqlite_append_only(table: str) -> tuple[str, str]:
    return (
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update "
        f"BEFORE UPDATE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete "
        f"BEFORE DELETE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
    )


def _sqlite_guard(table: str) -> str:
    return (
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_tenant_guard "
        f"BEFORE INSERT ON {table} FOR EACH ROW "
        f"WHEN NEW.tenant_id IS NOT (SELECT m.tenant_id FROM mandates m WHERE m.id = NEW.mandate_id) "
        f"OR EXISTS (SELECT 1 FROM mandates m WHERE m.id = NEW.mandate_id "
        f"AND m.client_id IS NOT NEW.client_id) "
        f"BEGIN SELECT RAISE(ABORT, '{TENANT_ERROR}'); END"
    )


def _pg_append_only(table: str) -> tuple[str, str]:
    return (
        f"CREATE OR REPLACE FUNCTION {table}_immutable() RETURNS trigger AS $$\n"
        "BEGIN\n"
        f"    RAISE EXCEPTION '{table} is immutable';\n"
        "END;\n"
        "$$ LANGUAGE plpgsql",
        f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {table}_immutable()",
    )


def upgrade() -> None:
    op.create_table(
        "owner_content_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("content_key", sa.String(), nullable=False),
        sa.Column("catalog_version", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body_text", sa.String(), nullable=True),
        sa.Column("value_json", sa.String(), nullable=True),
        sa.Column("source_reference", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_owner_content_versions_version"),
        sa.CheckConstraint(
            "body_text IS NOT NULL OR value_json IS NOT NULL", name="ck_owner_content_versions_payload",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "content_key", "version", name="uq_owner_content_versions_version"),
    )
    op.create_index("ix_owner_content_versions_tenant_id", "owner_content_versions", ["tenant_id"])
    op.create_table(
        "owner_content_approvals",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("content_key", sa.String(), nullable=False),
        sa.Column("content_row_id", sa.String(), nullable=False),
        sa.Column("predecessor_approval_id", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=False),
        sa.Column("approved_at", sa.String(), nullable=False),
        sa.Column("approval_reference", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("approval_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_row_id"),
        sa.UniqueConstraint(
            "tenant_id", "content_key", "predecessor_approval_id", name="uq_owner_content_approvals_chain",
        ),
    )
    op.create_index("ix_owner_content_approvals_tenant_id", "owner_content_approvals", ["tenant_id"])
    op.create_table(
        "advice_rationales",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("recommendation_run_id", sa.String(), nullable=False),
        sa.Column("client_needs", sa.String(), nullable=False),
        sa.Column("recommendation_reasons", sa.String(), nullable=False),
        sa.Column("recorded_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.String(), nullable=False),
        sa.Column("rationale_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_advice_rationales_tenant_id", "advice_rationales", ["tenant_id"])
    op.create_index("ix_advice_rationales_run", "advice_rationales", ["mandate_id", "recommendation_run_id"])
    op.create_table(
        "w033_client_declarations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("risk_assessment_id", sa.String(), nullable=False),
        sa.Column("declaration_kind", sa.String(), nullable=False),
        sa.Column("content_key", sa.String(), nullable=False),
        sa.Column("content_row_id", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("horizon_years", sa.Integer(), nullable=True),
        sa.Column("min_horizon_years", sa.Integer(), nullable=True),
        sa.Column("capture_channel", sa.String(), nullable=False),
        sa.Column("confirmed_at", sa.String(), nullable=False),
        sa.Column("recorded_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.String(), nullable=False),
        sa.Column("declaration_hash", sa.String(), nullable=False),
        sa.CheckConstraint(
            "declaration_kind IN ('angaben_wahr_meldepflicht','horizont_abraten')",
            name="ck_w033_client_declarations_kind",
        ),
        sa.CheckConstraint(
            "capture_channel IN ('persoenlich_papier','vor_ort','kundenportal')",
            name="ck_w033_client_declarations_channel",
        ),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_w033_client_declarations_tenant_id", "w033_client_declarations", ["tenant_id"])
    op.create_index(
        "ix_w033_client_declarations_assessment", "w033_client_declarations", ["mandate_id", "risk_assessment_id"],
    )

    dialect = _dialect()
    if dialect == "sqlite":
        for table in TABLES:
            for ddl in _sqlite_append_only(table):
                op.execute(ddl)
        for table in MANDATE_GUARDED:
            op.execute(_sqlite_guard(table))
    elif dialect == "postgresql":
        for table in TABLES:
            for ddl in _pg_append_only(table):
                op.execute(ddl)
        for table in MANDATE_GUARDED:
            op.execute(sa.text(
                f"CREATE TRIGGER trg_{table}_tenant_guard BEFORE INSERT ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION {PG_GUARD_FUNCTION}()"
            ))


def downgrade() -> None:
    bind = op.get_bind()
    found = [t for t in TABLES if bind.execute(sa.text(f"SELECT COUNT(*) FROM {t}")).scalar()]
    if found:
        raise RuntimeError(
            "H-179 Downgrade abgelehnt (fail-closed): vorhandene Nachweise wuerden vernichtet: "
            + ", ".join(found) + ". Datenbank aus Sicherung wiederherstellen statt zurueckzumigrieren."
        )
    dialect = _dialect()
    for table in TABLES:
        if dialect == "postgresql":
            if table in MANDATE_GUARDED:
                op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_tenant_guard ON {table}")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
        elif dialect == "sqlite":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_tenant_guard")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
    op.drop_index("ix_w033_client_declarations_assessment", table_name="w033_client_declarations")
    op.drop_index("ix_w033_client_declarations_tenant_id", table_name="w033_client_declarations")
    op.drop_table("w033_client_declarations")
    op.drop_index("ix_advice_rationales_run", table_name="advice_rationales")
    op.drop_index("ix_advice_rationales_tenant_id", table_name="advice_rationales")
    op.drop_table("advice_rationales")
    op.drop_index("ix_owner_content_approvals_tenant_id", table_name="owner_content_approvals")
    op.drop_table("owner_content_approvals")
    op.drop_index("ix_owner_content_versions_tenant_id", table_name="owner_content_versions")
    op.drop_table("owner_content_versions")
