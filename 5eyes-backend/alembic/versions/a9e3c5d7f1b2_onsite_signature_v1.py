"""Vor-Ort-Signatur mit kundeneigenem Faktor (SIGN-001): drei append-only Tabellen.

onsite_signature_events (hash-verkettete Zustandsmaschine),
onsite_signature_challenges (dokumentgebundene Kunden-Challenge, nur HMAC
des Codes) und onsite_signature_evidence (Evidence-Paket je Signatur).
UPDATE/DELETE per Trigger verboten (SQLite und PostgreSQL); kein FK auf
mandates/clients (Muster audit_log, Purge-fest), nur Akteure -> users.
Rein additiv, kein Backfill.

Revision ID: a9e3c5d7f1b2
Revises: a7c4e9b2d1f3
Create Date: 2026-10-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9e3c5d7f1b2"
down_revision: Union[str, Sequence[str], None] = "a7c4e9b2d1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("onsite_signature_events", "onsite_signature_challenges", "onsite_signature_evidence")
_SINGLE_USE_PREDICATE = (
    "challenge_id IS NOT NULL AND event_type IN ('FACTOR_VERIFIED','FACTOR_REJECTED')"
)


def _sqlite_triggers(table: str) -> tuple[str, str]:
    return (
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update "
        f"BEFORE UPDATE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete "
        f"BEFORE DELETE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
    )


def _pg_ddl(table: str) -> tuple[str, str]:
    return (
        f"CREATE OR REPLACE FUNCTION {table}_immutable() RETURNS trigger AS $$\n"
        f"BEGIN\n    RAISE EXCEPTION '{table} is immutable';\nEND;\n$$ LANGUAGE plpgsql",
        f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {table}_immutable()",
    )


def upgrade() -> None:
    op.create_table(
        "onsite_signature_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("transaction_id", sa.String(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("document_hash", sa.String(length=64), nullable=False),
        sa.Column("challenge_id", sa.String(), nullable=True),
        sa.Column("reason_code", sa.String(), nullable=True),
        sa.Column("payload_json", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("actor_role", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.String(), nullable=False),
        sa.Column("time_source", sa.String(), nullable=False),
        sa.Column("previous_event_hash", sa.String(length=64), nullable=True),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_onsite_signature_events_sequence", "onsite_signature_events",
        ["transaction_id", "sequence_no"], unique=True,
    )
    op.create_index("ix_onsite_signature_events_document", "onsite_signature_events", ["document_id"])
    op.create_index("ix_onsite_signature_events_mandate", "onsite_signature_events", ["mandate_id"])
    op.create_index(
        "ux_onsite_signature_events_challenge_use", "onsite_signature_events", ["challenge_id"],
        unique=True,
        sqlite_where=sa.text(_SINGLE_USE_PREDICATE),
        postgresql_where=sa.text(_SINGLE_USE_PREDICATE),
    )

    op.create_table(
        "onsite_signature_challenges",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("transaction_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("document_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("nonce", sa.String(), nullable=False),
        sa.Column("issued_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("delivery_channel", sa.String(), nullable=False),
        sa.Column("code_salt", sa.String(), nullable=False),
        sa.Column("code_hmac", sa.String(length=64), nullable=False),
        sa.Column("binding_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_onsite_signature_challenges_transaction", "onsite_signature_challenges", ["transaction_id"],
    )

    op.create_table(
        "onsite_signature_evidence",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("transaction_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("document_type", sa.String(), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("document_content_hash", sa.String(), nullable=False),
        sa.Column("template_version", sa.String(), nullable=True),
        sa.Column("document_class", sa.String(), nullable=False),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("displayed_document_hash", sa.String(length=64), nullable=False),
        sa.Column("final_document_hash", sa.String(length=64), nullable=False),
        sa.Column("signer_role", sa.String(), nullable=False),
        sa.Column("consent_text_version", sa.String(), nullable=False),
        sa.Column("consent_text_hash", sa.String(length=64), nullable=False),
        sa.Column("signed_at", sa.String(), nullable=False),
        sa.Column("time_source", sa.String(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("identity_check_result", sa.String(), nullable=False),
        sa.Column("identity_check_method", sa.String(), nullable=False),
        sa.Column("id_document_kind", sa.String(), nullable=False),
        sa.Column("id_document_country", sa.String(), nullable=False),
        sa.Column("id_document_valid", sa.Integer(), nullable=False),
        sa.Column("customer_factor_kind", sa.String(), nullable=False),
        sa.Column("customer_factor_challenge_id", sa.String(), nullable=False),
        sa.Column("customer_factor_binding_hash", sa.String(length=64), nullable=False),
        sa.Column("customer_factor_channel", sa.String(), nullable=False),
        sa.Column("customer_factor_verified_at", sa.String(), nullable=False),
        sa.Column("customer_factor_actor_id", sa.String(), nullable=False),
        sa.Column("advisor_id", sa.String(), nullable=False),
        sa.Column("advisor_auth_method", sa.String(), nullable=False),
        sa.Column("witness_statement_version", sa.String(), nullable=False),
        sa.Column("witness_statement_hash", sa.String(length=64), nullable=False),
        sa.Column("device_app_version", sa.String(), nullable=False),
        sa.Column("qes_provider", sa.String(), nullable=True),
        sa.Column("qes_receipt_hash", sa.String(length=64), nullable=True),
        sa.Column("qes_certificate_chain_hash", sa.String(length=64), nullable=True),
        sa.Column("qes_timestamp", sa.String(), nullable=True),
        sa.Column("qes_validation_result", sa.String(), nullable=True),
        sa.Column("signed_event_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["advisor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_onsite_signature_evidence_transaction", "onsite_signature_evidence",
        ["transaction_id"], unique=True,
    )
    op.create_index("ix_onsite_signature_evidence_mandate", "onsite_signature_evidence", ["mandate_id"])

    dialect = op.get_bind().dialect.name
    for table in _TABLES:
        if dialect == "sqlite":
            for ddl in _sqlite_triggers(table):
                op.execute(ddl)
        elif dialect == "postgresql":
            for ddl in _pg_ddl(table):
                op.execute(ddl)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    for table in _TABLES:
        if dialect == "postgresql":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
        elif dialect == "sqlite":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
    op.drop_index("ix_onsite_signature_evidence_mandate", table_name="onsite_signature_evidence")
    op.drop_index("ux_onsite_signature_evidence_transaction", table_name="onsite_signature_evidence")
    op.drop_table("onsite_signature_evidence")
    op.drop_index("ix_onsite_signature_challenges_transaction", table_name="onsite_signature_challenges")
    op.drop_table("onsite_signature_challenges")
    op.drop_index("ux_onsite_signature_events_challenge_use", table_name="onsite_signature_events")
    op.drop_index("ix_onsite_signature_events_mandate", table_name="onsite_signature_events")
    op.drop_index("ix_onsite_signature_events_document", table_name="onsite_signature_events")
    op.drop_index("ux_onsite_signature_events_sequence", table_name="onsite_signature_events")
    op.drop_table("onsite_signature_events")
