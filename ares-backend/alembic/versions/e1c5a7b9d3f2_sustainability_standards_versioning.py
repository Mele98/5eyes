"""Hausstandard Nachhaltigkeit versioniert, Lockerung mit Vier-Augen-Freigabe.

Audit 2026-11 / 05, Paket T1, Pruefrunde #863 Hinweis H-1 (Entscheid
Owner-Vertretung): Eine Lockerung des Hausstandards unter die T-E1-Defaults
(hoehere Schwelle oder Kategorie deaktiviert) braucht eine Vier-Augen-
Freigabe; Verschaerfungen wirken sofort. T3 muss die verwendete Schwelle samt
Version im Snapshot speichern koennen.

``sustainability_exclusion_standards`` bekommt:
``status`` (draft/approved/retired, Default fuer Bestand 'approved'),
``is_disabled`` (0/1, Default 0), ``created_by``, ``approved_by``,
``approved_at``, ``approval_mode``, ``valid_from``, ``valid_to``.
Der Unique-Index (tenant, category) wird ersetzt durch je einen partiellen
Unique-Index fuer die aktuelle freigegebene Version und fuer den offenen
Entwurf. CHECKs: Status, is_disabled, Vier-Augen (approved_by <> created_by,
ausser immediate_tightening/single_approver_attested/pre_versioning).

Bestand (vor dieser Revision gesetzte Tenant-Werte): status 'approved',
valid_from/approved_at = updated_at, created_by/approved_by = updated_by,
approval_mode 'pre_versioning' -- die Herkunft bleibt erkennbar, nichts wird
als Vier-Augen-Freigabe ausgegeben.

Batch-Modus (SQLite: Tabelle neu aufbauen; Postgres: ALTER). Die RLS-Policy
der Tabelle (strikt, d7f3b1a9c5e2) bleibt unberuehrt; Postgres behaelt sie
beim ALTER, SQLite kennt kein RLS. Downgrade loescht Entwuerfe und abgeloeste
Versionen (der alte Unique-Index erlaubt nur eine Zeile je Kategorie).

Revision ID: e1c5a7b9d3f2
Revises: d7f3b1a9c5e2
Create Date: 2026-11-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1c5a7b9d3f2"
down_revision: Union[str, Sequence[str], None] = "d7f3b1a9c5e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "sustainability_exclusion_standards"
_FOUR_EYES = (
    "approved_by IS NULL OR created_by IS NULL OR approved_by <> created_by "
    "OR approval_mode IN ('immediate_tightening', 'single_approver_attested', 'pre_versioning')"
)
_CURRENT_WHERE = "status = 'approved' AND valid_to IS NULL"
_PENDING_WHERE = "status = 'draft'"


def upgrade() -> None:
    op.drop_index("ux_ses_tenant_category", table_name=TABLE)
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(sa.Column("is_disabled", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'approved'")))
        batch.add_column(sa.Column("created_by", sa.String(), nullable=True))
        batch.add_column(sa.Column("approved_by", sa.String(), nullable=True))
        batch.add_column(sa.Column("approved_at", sa.String(), nullable=True))
        batch.add_column(sa.Column("approval_mode", sa.String(), nullable=True))
        batch.add_column(sa.Column("valid_from", sa.String(), nullable=True))
        batch.add_column(sa.Column("valid_to", sa.String(), nullable=True))
    op.execute(
        f"UPDATE {TABLE} SET created_by = updated_by, approved_by = updated_by, approved_at = updated_at, "
        "valid_from = updated_at, approval_mode = 'pre_versioning' WHERE valid_from IS NULL"
    )
    with op.batch_alter_table(TABLE) as batch:
        batch.create_foreign_key("fk_ses_created_by", "users", ["created_by"], ["id"])
        batch.create_foreign_key("fk_ses_approved_by", "users", ["approved_by"], ["id"])
        batch.create_check_constraint("ck_ses_status", "status IN ('draft', 'approved', 'retired')")
        batch.create_check_constraint("ck_ses_is_disabled", "is_disabled IN (0, 1)")
        batch.create_check_constraint("ck_ses_four_eyes", _FOUR_EYES)
    op.create_index("ix_ses_tenant_category", TABLE, ["tenant_id", "category", "status"])
    op.create_index(
        "ux_ses_tenant_category_current", TABLE, ["tenant_id", "category"], unique=True,
        sqlite_where=sa.text(_CURRENT_WHERE), postgresql_where=sa.text(_CURRENT_WHERE),
    )
    op.create_index(
        "ux_ses_tenant_category_pending", TABLE, ["tenant_id", "category"], unique=True,
        sqlite_where=sa.text(_PENDING_WHERE), postgresql_where=sa.text(_PENDING_WHERE),
    )


def downgrade() -> None:
    op.drop_index("ux_ses_tenant_category_pending", table_name=TABLE)
    op.drop_index("ux_ses_tenant_category_current", table_name=TABLE)
    op.drop_index("ix_ses_tenant_category", table_name=TABLE)
    op.execute(f"DELETE FROM {TABLE} WHERE status <> 'approved' OR valid_to IS NOT NULL")
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint("ck_ses_four_eyes", type_="check")
        batch.drop_constraint("ck_ses_is_disabled", type_="check")
        batch.drop_constraint("ck_ses_status", type_="check")
        batch.drop_constraint("fk_ses_approved_by", type_="foreignkey")
        batch.drop_constraint("fk_ses_created_by", type_="foreignkey")
    with op.batch_alter_table(TABLE) as batch:
        for name in ("valid_to", "valid_from", "approval_mode", "approved_at", "approved_by",
                     "created_by", "status", "is_disabled"):
            batch.drop_column(name)
    op.create_index("ux_ses_tenant_category", TABLE, ["tenant_id", "category"], unique=True)
