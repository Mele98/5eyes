"""H8: Kundeninformation (Art. 8/9 FIDLEG), KYC-Bestaetigung (GwG), Vertretung (ZGB).

Compliance-Audit 2026-11-07 (Dok. 104), Paket H8:

- ``tenant_legal_profiles``: rechtliche Angaben der Firma (C-2), ohne
  Vorbelegung; Aenderungen feldweise im Audit-Log.
- ``client_information_deliveries``: append-only Abgabenachweis der
  Kundeninformation (Fassung, Byte-Hash, Version, Zeitpunkt, Kanal).
- ``kyc_confirmations`` / ``kyc_confirmation_approvals``: append-only
  GwG-Bestaetigung (Abklaerung im SRO-/Fremdprozess) samt Vier-Augen-Freigabe.
- ``client_representations``: Vollmacht, Vorsorgeauftrag, Beistandschaft,
  Gemeinschaftsdepot (dokumentarisch, Widerruf statt Loeschen).
- ``client_due_diligence.acting_for_own_account_answered`` (NOT NULL DEFAULT 0:
  Bestandszeilen gelten als unbeantwortet) und
  ``client_opt_history.opt_out_criteria_json`` (Art. 5 FIDLEG).

Append-only per Trigger (SQLite und PostgreSQL), wie
financial_coverage_attestations. Kein FK auf mandates/clients (Purge-fest),
nur die Akteure verweisen auf users. Dieselben Tabellen legt der SQLite-Pfad
ueber create_all an (Modelle in models/tenant.py, models/clients.py,
models/review.py; Trigger database.py::*_SQLITE_TRIGGERS).

Revision ID: d8e4b2a6c1f9
Revises: e1c6a7d4b2f9 (H7; nach Merge linearisiert, N-890-06/07)
Create Date: 2026-11-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d8e4b2a6c1f9"
down_revision: Union[str, Sequence[str], None] = "e1c6a7d4b2f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPEND_ONLY_TABLES = (
    "client_information_deliveries",
    "kyc_confirmations",
    "kyc_confirmation_approvals",
)


# N-890-09: KYC-Freitexte duerfen im Loeschvorgang nur auf den Redaktions-
# marker gesetzt werden (gleiche Listen wie database.py::KYC_*_COLUMNS).
REDACTION_MARKER = "[ERASED-DSG-ART-32]"
REDACTION_ONLY = {
    "kyc_confirmations": (
        ("id", "tenant_id", "client_id", "mandate_id", "process_scope", "form_type",
         "form_completed_on", "risk_category", "is_pep", "identification_confirmed",
         "identification_date", "next_review_due", "requires_second_approval",
         "recorded_by", "recorded_at", "confirmation_hash"),
        ("external_reference", "note"),
    ),
    "kyc_confirmation_approvals": (
        ("id", "tenant_id", "confirmation_id", "client_id", "approved_by", "approved_at",
         "approval_hash"),
        ("note",),
    ),
}


def _sqlite_triggers(table: str) -> tuple[str, str]:
    when = ""
    if table in REDACTION_ONLY:
        fixed, redactable = REDACTION_ONLY[table]
        changed = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in fixed)
        bad = " OR ".join(
            f"(NEW.{c} IS NOT OLD.{c} AND NEW.{c} IS NOT NULL AND NEW.{c} != '{REDACTION_MARKER}')"
            for c in redactable
        )
        when = f"WHEN {changed} OR {bad} "
    return (
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update "
        f"BEFORE UPDATE ON {table} FOR EACH ROW {when}"
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete "
        f"BEFORE DELETE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
    )


def _pg_function(table: str) -> str:
    if table not in REDACTION_ONLY:
        return (
            f"CREATE OR REPLACE FUNCTION {table}_immutable() RETURNS trigger AS $$\n"
            "BEGIN\n"
            f"    RAISE EXCEPTION '{table} is immutable';\n"
            "END;\n"
            "$$ LANGUAGE plpgsql"
        )
    fixed, redactable = REDACTION_ONLY[table]
    changed = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in fixed)
    bad = " OR ".join(
        f"(NEW.{c} IS DISTINCT FROM OLD.{c} AND NEW.{c} IS NOT NULL AND NEW.{c} <> '{REDACTION_MARKER}')"
        for c in redactable
    )
    return (
        f"CREATE OR REPLACE FUNCTION {table}_immutable() RETURNS trigger AS $$\n"
        "BEGIN\n"
        "    IF TG_OP = 'DELETE' THEN\n"
        f"        RAISE EXCEPTION '{table} is immutable';\n"
        "    END IF;\n"
        "    IF " + changed + " OR " + bad + " THEN\n"
        f"        RAISE EXCEPTION '{table} is immutable';\n"
        "    END IF;\n"
        "    RETURN NEW;\n"
        "END;\n"
        "$$ LANGUAGE plpgsql"
    )


def _pg_trigger(table: str) -> str:
    return (
        f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {table}_immutable()"
    )


def upgrade() -> None:
    op.create_table(
        "tenant_legal_profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("legal_name", sa.String(), nullable=True),
        sa.Column("address_street", sa.String(), nullable=True),
        sa.Column("address_postal_code", sa.String(), nullable=True),
        sa.Column("address_city", sa.String(), nullable=True),
        sa.Column("address_country", sa.String(), nullable=True),
        sa.Column("business_activity", sa.String(), nullable=True),
        sa.Column("supervision_type", sa.String(), nullable=True),
        sa.Column("supervisory_authority", sa.String(), nullable=True),
        sa.Column("supervisory_organisation", sa.String(), nullable=True),
        sa.Column("license_reference", sa.String(), nullable=True),
        sa.Column("ombudsman_name", sa.String(), nullable=True),
        sa.Column("ombudsman_address", sa.String(), nullable=True),
        sa.Column("contact_phone", sa.String(), nullable=True),
        sa.Column("contact_email", sa.String(), nullable=True),
        sa.Column("contact_website", sa.String(), nullable=True),
        sa.Column("revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("profile_hash", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )
    op.create_table(
        "client_information_deliveries",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("contract_document_id", sa.String(), nullable=False),
        sa.Column("template_version", sa.String(), nullable=False),
        sa.Column("legal_profile_revision", sa.Integer(), nullable=False),
        sa.Column("legal_profile_hash", sa.String(), nullable=False),
        sa.Column("pdf_sha256", sa.String(), nullable=False),
        sa.Column("delivered_at", sa.String(), nullable=False),
        sa.Column("delivery_channel", sa.String(), nullable=False),
        sa.Column("delivery_timing", sa.String(), nullable=False),
        sa.Column("backdating_reason", sa.String(), nullable=True),
        sa.Column("recorded_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.String(), nullable=False),
        sa.Column("delivery_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "kyc_confirmations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=True),
        sa.Column("process_scope", sa.String(), nullable=False),
        sa.Column("form_type", sa.String(), nullable=False),
        sa.Column("form_completed_on", sa.String(), nullable=False),
        sa.Column("external_reference", sa.String(), nullable=False),
        sa.Column("risk_category", sa.String(), nullable=False),
        sa.Column("is_pep", sa.Integer(), nullable=False),
        sa.Column("identification_confirmed", sa.Integer(), nullable=False),
        sa.Column("identification_date", sa.String(), nullable=False),
        sa.Column("next_review_due", sa.String(), nullable=False),
        sa.Column("requires_second_approval", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("recorded_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.String(), nullable=False),
        sa.Column("confirmation_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "kyc_confirmation_approvals",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("confirmation_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=False),
        sa.Column("approved_at", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("approval_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("confirmation_id"),
    )
    op.create_table(
        "client_representations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=True),
        sa.Column("representation_type", sa.String(), nullable=False),
        sa.Column("representative_name", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("evidence_reference", sa.String(), nullable=False),
        sa.Column("effective_from", sa.String(), nullable=True),
        sa.Column("effective_until", sa.String(), nullable=True),
        sa.Column("disposal_rule", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("recorded_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.String(), nullable=False),
        sa.Column("revoked_at", sa.String(), nullable=True),
        sa.Column("revoked_by", sa.String(), nullable=True),
        sa.Column("revocation_reason", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column(
        "client_due_diligence",
        sa.Column(
            "acting_for_own_account_answered", sa.Integer(),
            server_default=sa.text("0"), nullable=False,
        ),
    )
    op.add_column("client_opt_history", sa.Column("opt_out_criteria_json", sa.String(), nullable=True))

    dialect = op.get_bind().dialect.name
    for table in APPEND_ONLY_TABLES:
        if dialect == "sqlite":
            for ddl in _sqlite_triggers(table):
                op.execute(ddl)
        elif dialect == "postgresql":
            op.execute(_pg_function(table))
            op.execute(_pg_trigger(table))


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    for table in APPEND_ONLY_TABLES:
        if dialect == "postgresql":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
        elif dialect == "sqlite":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
    with op.batch_alter_table("client_opt_history") as batch:
        batch.drop_column("opt_out_criteria_json")
    with op.batch_alter_table("client_due_diligence") as batch:
        batch.drop_column("acting_for_own_account_answered")
    op.drop_table("client_representations")
    op.drop_table("kyc_confirmation_approvals")
    op.drop_table("kyc_confirmations")
    op.drop_table("client_information_deliveries")
    op.drop_table("tenant_legal_profiles")
