"""Version the remaining legacy-bootstrap schema for PostgreSQL.

Revision ID: e84f9a2d1c70
Revises: 7b31f8d2a6c4
Create Date: 2026-08-10

Historically the two market-data tables and several integrity objects were
created lazily with SQLite-specific raw SQL.  PostgreSQL startup is
Alembic-only, so the equivalent tables, indexes, constraints and immutable
audit-log triggers must exist before runtime services start.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e84f9a2d1c70"
down_revision: Union[str, Sequence[str], None] = "7b31f8d2a6c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


AUDIT_ACTIONS: tuple[str, ...] = (
    "CREATE",
    "UPDATE",
    "DELETE",
    "LOGIN",
    "EXPORT",
    "PASSWORD_RESET",
    "2FA_DISABLE",
    "2FA_ENABLE",
    "2FA_RECOVERY_REGEN",
    "2FA_RECOVERY_USED",
    "ACTIVATE",
    "APPROVE",
    "BACKFILL",
    "BACKUP",
    "CLONE",
    "DB_OPTIMIZE",
    "FOUNDATION_EXAMPLE",
    "FOUNDATION_PURGE",
    "INVITE",
    "INVITE_ACCEPT",
    "INVITE_RESEND",
    "INVITE_REVOKE",
    "MARKET_DATA_PURGE",
    "MARKET_DATA_REFRESH",
    "OPTIMIZER_MODE_CHANGE",
    "PASSWORD_CHANGE",
    "PASSWORD_RESET_CONFIRM",
    "PASSWORD_RESET_REQUEST",
    "REPLACE",
    "REPLACE_ALL",
    "SENSITIVITY",
    "SUPPORT_BUNDLE",
    "UPSERT",
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # Objects created by SQLite's legacy ensure_* path but absent from the
    # ORM-generated Alembic baseline.
    # ``uq_acr_year_class`` is intentionally not copied: that obsolete
    # two-column SQLite index conflicts with the supported sub-asset rows,
    # whose logical key also includes ``sub_asset_class``.
    op.create_index(
        "ix_strategy_snapshots_mandate",
        "strategy_snapshots",
        ["mandate_id", "deleted_at", "snapshot_date"],
        unique=False,
    )
    op.create_index(
        "idx_risk_answers",
        "risk_assessment_answers",
        ["assessment_id"],
        unique=False,
    )
    for index_name, columns in (
        ("idx_audit_mandate_table", ["mandate_id", "table_name"]),
        ("idx_audit_record", ["table_name", "record_id"]),
        ("idx_audit_mandate", ["mandate_id"]),
        ("idx_audit_user", ["user_id"]),
        ("idx_audit_time", ["created_at"]),
    ):
        op.create_index(index_name, "audit_log", columns, unique=False)

    # ALTER-based constraints and PL/pgSQL triggers are production-only.
    # SQLite receives their equivalents from its unchanged legacy path.
    if _is_postgres():
        op.create_check_constraint(
            "ck_risk_answers_question_number",
            "risk_assessment_answers",
            "question_number BETWEEN 1 AND 12",
        )
        op.create_check_constraint(
            "ck_risk_answers_question_section",
            "risk_assessment_answers",
            "question_section IN ('Kenntnisse & Erfahrungen', "
            "'Risikofähigkeit', 'Risikobereitschaft')",
        )
        op.create_unique_constraint(
            "uq_risk_answers_assessment_question",
            "risk_assessment_answers",
            ["assessment_id", "question_number"],
        )
        allowed_actions = ", ".join(f"'{action}'" for action in AUDIT_ACTIONS)
        op.create_check_constraint(
            "ck_audit_log_action_allowed",
            "audit_log",
            f"action IN ({allowed_actions})",
        )
        op.execute(
            """
            CREATE FUNCTION fn_5eyes_audit_log_immutable()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_log is immutable';
                RETURN OLD;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_log_no_update
            BEFORE UPDATE ON audit_log
            FOR EACH ROW EXECUTE FUNCTION fn_5eyes_audit_log_immutable()
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_log_no_delete
            BEFORE DELETE ON audit_log
            FOR EACH ROW EXECUTE FUNCTION fn_5eyes_audit_log_immutable()
            """
        )

    op.create_table(
        "provider_health_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("provider_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("operation", sa.String(), nullable=True),
        sa.Column("error_type", sa.String(), nullable=True),
        sa.Column(
            "consecutive_errors",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("observed_at", sa.String(), nullable=False),
        sa.Column("unhealthy_until", sa.String(), nullable=True),
        sa.Column("recovered_at", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_provider_health_events_provider_observed",
        "provider_health_events",
        ["provider_name", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_provider_health_events_status",
        "provider_health_events",
        ["status", "recovered_at"],
        unique=False,
    )

    op.create_table(
        "market_data_purge_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.Column(
            "purged_rows",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("skipped_providers_json", sa.String(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("errors_json", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_market_data_purge_history_started",
        "market_data_purge_history",
        ["started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_market_data_purge_history_started",
        table_name="market_data_purge_history",
    )
    op.drop_table("market_data_purge_history")
    op.drop_index(
        "ix_provider_health_events_status",
        table_name="provider_health_events",
    )
    op.drop_index(
        "ix_provider_health_events_provider_observed",
        table_name="provider_health_events",
    )
    op.drop_table("provider_health_events")

    if _is_postgres():
        op.execute("DROP TRIGGER trg_audit_log_no_delete ON audit_log")
        op.execute("DROP TRIGGER trg_audit_log_no_update ON audit_log")
        op.execute("DROP FUNCTION fn_5eyes_audit_log_immutable()")
        op.drop_constraint(
            "ck_audit_log_action_allowed",
            "audit_log",
            type_="check",
        )
        op.drop_constraint(
            "uq_risk_answers_assessment_question",
            "risk_assessment_answers",
            type_="unique",
        )
        op.drop_constraint(
            "ck_risk_answers_question_section",
            "risk_assessment_answers",
            type_="check",
        )
        op.drop_constraint(
            "ck_risk_answers_question_number",
            "risk_assessment_answers",
            type_="check",
        )

    for index_name in (
        "idx_audit_time",
        "idx_audit_user",
        "idx_audit_mandate",
        "idx_audit_record",
        "idx_audit_mandate_table",
    ):
        op.drop_index(index_name, table_name="audit_log")
    op.drop_index("idx_risk_answers", table_name="risk_assessment_answers")
    op.drop_index(
        "ix_strategy_snapshots_mandate",
        table_name="strategy_snapshots",
    )
