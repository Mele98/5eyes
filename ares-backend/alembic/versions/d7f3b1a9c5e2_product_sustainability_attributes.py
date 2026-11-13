"""Nachhaltigkeits- und Ausschlussmerkmale je Produkt, Hausstandard je Tenant.

Audit 2026-11 / 05, Paket T1 (Zielbild §4.1/§4.2, Entscheide T-E1..T-E3).
Zwei neue Tabellen, KEINE Aenderung an ``products`` und kein Backfill:

``product_sustainability_attributes``
    Ein Nachweis je Produkt x Kategorie x Art x Stichtag mit Schwelle bzw.
    gemessener Exposure, Quelle (Typ + Referenz, Pflicht), Stichtag, gueltig
    bis (Default Stichtag + 12 Monate) und Vier-Augen-Status
    draft/approved/retired. ``tenant_id`` NULL = Plattform-Nachweis
    (globaler Katalog), gesetzt = Tenant-Overlay.
``sustainability_exclusion_standards``
    Hausschwelle je Tenant und Kategorie; fehlt die Zeile, gilt der
    Code-Default nach T-E1.

Die bestehenden Seed-Werte ``products.sfdr_class`` u. a. werden bewusst NICHT
uebernommen (T-E2: unbelegte Seed-Werte erfuellen kein Kriterium).

Postgres-RLS: ``product_sustainability_attributes`` ist eine globale
Referenztabelle wie ``products`` (SELECT eigener Tenant ODER tenant_id IS
NULL, Schreiben nur eigener Tenant oder Operator-Bypass);
``sustainability_exclusion_standards`` ist strikt tenant-gebunden. Gleiche DDL
wie ``services/postgres_rls.py::rls_policy_sql`` (init_db wendet sie bei
jedem Start erneut an), hier eingefroren wie in ``e2b7c4f9a1d6``. SQLite
(auch SQLCipher): kein RLS; die Desktop-Installation legt die Tabellen ueber
``Base.metadata.create_all`` an (gleiche DDL aus dem ORM).

Revision ID: d7f3b1a9c5e2
Revises: d4f7a9c2e1b6
Create Date: 2026-11-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7f3b1a9c5e2"
down_revision: Union[str, Sequence[str], None] = "d4f7a9c2e1b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ATTRIBUTES = "product_sustainability_attributes"
STANDARDS = "sustainability_exclusion_standards"

_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')"
_BYPASS = "current_setting('app.rls_bypass', true) = 'on'"
_WRITE = f"(tenant_id::text = {_TENANT} OR {_BYPASS})"
_READ = f"(tenant_id::text = {_TENANT} OR tenant_id IS NULL OR {_BYPASS})"
_REFERENCE_POLICIES = (
    "tenant_reference_select",
    "tenant_reference_insert",
    "tenant_reference_update",
    "tenant_reference_delete",
)


def _is_postgres() -> bool:
    return op.get_context().dialect.name.startswith("postgresql")


def _enable_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    for name in _REFERENCE_POLICIES:
        op.execute(f'DROP POLICY IF EXISTS {name} ON "{table}"')


def upgrade() -> None:
    op.create_table(
        ATTRIBUTES,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("product_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("revenue_threshold_bps", sa.Integer(), nullable=True),
        sa.Column("measured_exposure_bps", sa.Integer(), nullable=True),
        sa.Column("value", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_reference", sa.String(), nullable=False),
        sa.Column("source_provider", sa.String(), nullable=True),
        sa.Column("source_retrieved_on", sa.String(), nullable=True),
        sa.Column("as_of", sa.String(), nullable=False),
        sa.Column("valid_until", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approved_at", sa.String(), nullable=True),
        sa.Column("approval_mode", sa.String(), nullable=True),
        sa.Column("retired_by", sa.String(), nullable=True),
        sa.Column("retired_at", sa.String(), nullable=True),
        sa.Column("supersedes_id", sa.String(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'approved', 'retired')", name="ck_psa_status"),
        sa.CheckConstraint(
            "kind IN ('exclusion_policy', 'measured_exposure', 'certification', 'classification')",
            name="ck_psa_kind",
        ),
        sa.CheckConstraint(
            "revenue_threshold_bps IS NULL OR (revenue_threshold_bps >= 0 AND revenue_threshold_bps <= 10000)",
            name="ck_psa_revenue_threshold_bps",
        ),
        sa.CheckConstraint(
            "measured_exposure_bps IS NULL OR (measured_exposure_bps >= 0 AND measured_exposure_bps <= 10000)",
            name="ck_psa_measured_exposure_bps",
        ),
        sa.CheckConstraint("valid_until >= as_of", name="ck_psa_valid_until"),
        sa.CheckConstraint(
            "approved_by IS NULL OR approved_by <> created_by "
            "OR approval_mode = 'single_approver_attested'",
            name="ck_psa_four_eyes",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["retired_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["supersedes_id"], [f"{ATTRIBUTES}.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_psa_product_category_status", ATTRIBUTES, ["product_id", "category", "status"])
    op.create_index("ix_psa_tenant_id", ATTRIBUTES, ["tenant_id"])
    tenant_where = "tenant_id IS NOT NULL AND status <> 'retired'"
    global_where = "tenant_id IS NULL AND status <> 'retired'"
    op.create_index(
        "ux_psa_active_tenant", ATTRIBUTES, ["product_id", "tenant_id", "category", "kind", "as_of"],
        unique=True, sqlite_where=sa.text(tenant_where), postgresql_where=sa.text(tenant_where),
    )
    op.create_index(
        "ux_psa_active_global", ATTRIBUTES, ["product_id", "category", "kind", "as_of"],
        unique=True, sqlite_where=sa.text(global_where), postgresql_where=sa.text(global_where),
    )

    op.create_table(
        STANDARDS,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("max_revenue_threshold_bps", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "max_revenue_threshold_bps IS NULL OR "
            "(max_revenue_threshold_bps >= 0 AND max_revenue_threshold_bps <= 10000)",
            name="ck_ses_threshold_bps",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ux_ses_tenant_category", STANDARDS, ["tenant_id", "category"], unique=True)

    if not _is_postgres():
        return
    _enable_rls(ATTRIBUTES)
    op.execute(f'CREATE POLICY tenant_reference_select ON "{ATTRIBUTES}" FOR SELECT USING ({_READ})')
    op.execute(f'CREATE POLICY tenant_reference_insert ON "{ATTRIBUTES}" FOR INSERT WITH CHECK ({_WRITE})')
    op.execute(
        f'CREATE POLICY tenant_reference_update ON "{ATTRIBUTES}" FOR UPDATE '
        f"USING ({_WRITE}) WITH CHECK ({_WRITE})"
    )
    op.execute(f'CREATE POLICY tenant_reference_delete ON "{ATTRIBUTES}" FOR DELETE USING ({_WRITE})')
    _enable_rls(STANDARDS)
    op.execute(f'CREATE POLICY tenant_isolation ON "{STANDARDS}" USING ({_WRITE}) WITH CHECK ({_WRITE})')


def downgrade() -> None:
    # DROP TABLE entfernt Policies und Indizes mit.
    op.drop_index("ux_ses_tenant_category", table_name=STANDARDS)
    op.drop_table(STANDARDS)
    for name in ("ux_psa_active_global", "ux_psa_active_tenant", "ix_psa_tenant_id", "ix_psa_product_category_status"):
        op.drop_index(name, table_name=ATTRIBUTES)
    op.drop_table(ATTRIBUTES)
