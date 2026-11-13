"""C-890-01: Wiedervorlage-Policy der KYC-Bestaetigung (fail-closed ohne Owner-Frist).

Codex-Befund C-890-01 (First-Customer-Blocker): ``next_review_due`` musste nur
nach ``form_completed_on`` liegen; ein Termin im Jahr 2099 war gueltig. Diese
Revision legt die Datenbasis fuer einen tenant-/jurisdiktionsbezogen
freigegebenen Maximalabstand an -- OHNE eine Frist zu setzen:

- ``kyc_review_policies``: versionierte Policy (Normalfrist, optional
  strengere PEP-/Hochrisiko-Frist in Kalendermonaten, Gueltigkeit, Quelle,
  Ersteller, Inhalts-Hash). CHECKs: Abstand > 0, PEP-/Hochrisiko-Frist nie
  lockerer als die Normalfrist, Gueltigkeitsende nicht vor dem Beginn;
  UNIQUE (tenant_id, jurisdiction, version).
- ``kyc_review_policy_activations``: Vier-Augen-Freigabe = Aktivierung
  (Freigeber, Zeitpunkt, unveraenderliche Freigabereferenz, gesehener
  Policy-Hash, Siegel). UNIQUE (tenant_id, jurisdiction,
  predecessor_activation_id): die Aktivierungen bilden je Tenant/
  Jurisdiktion eine lineare Kette (erste mit Vorgaenger 'GENESIS'); zwei
  parallele Aktivierungen auf denselben Stand koennen nie beide gelingen.
- ``kyc_confirmations``: acht nullable Bindungsspalten (Policy-Zeile,
  Aktivierung, Policy-ID/-Version/-Hash, Risikoklasse, Abstand, berechnete
  Obergrenze). KEIN Backfill: Bestandsbestaetigungen bleiben ohne Bindung
  und gelten als "policy_binding_missing" (gesperrt bis zur Aktivierung einer
  Policy und einer neuen Bestaetigung).
- Beide neuen Tabellen sind append-only (Trigger SQLite/PostgreSQL); der
  Redaktions-Trigger von ``kyc_confirmations`` schuetzt die Bindungsspalten
  mit (gleiche Spaltenliste wie database.py::KYC_CONFIRMATION_FIXED_COLUMNS).

SQLite legt dieselben Tabellen ueber create_all an (Modelle in
models/tenant.py, Bindungsspalten in models/clients.py; Runtime-Patch und
Trigger-Ersatz in database.py::ensure_runtime_columns).

Downgrade (fail-closed): eine Rueckkehr ohne diese Tabellen/Spalten wuerde
freigegebene Policies bzw. die im Siegel gebundene KYC-Evidenz vernichten.
Liegt irgendeine Policy, Aktivierung oder gebundene Bestaetigung vor, bricht
der Downgrade mit einer Fehlermeldung ab; nur eine Datenbank ohne solche
Evidenz wird zurueckgebaut.

Revision ID: f4c2e8a6d1b3
Revises: a9d4e2c6f1b3 (H4, hinter H8; RC-CH-1 I-03)
Create Date: 2026-11-11
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f4c2e8a6d1b3"
down_revision: Union[str, Sequence[str], None] = "a9d4e2c6f1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_APPEND_ONLY_TABLES = ("kyc_review_policies", "kyc_review_policy_activations")
BINDING_COLUMNS: tuple[tuple[str, type], ...] = (
    ("review_policy_row_id", sa.String),
    ("review_policy_activation_id", sa.String),
    ("review_policy_id", sa.String),
    ("review_policy_version", sa.Integer),
    ("review_policy_hash", sa.String),
    ("review_risk_class", sa.String),
    ("review_interval_months", sa.Integer),
    ("review_max_due", sa.String),
)
REDACTION_MARKER = "[ERASED-DSG-ART-32]"
KYC_FIXED_BASE = (
    "id", "tenant_id", "client_id", "mandate_id", "process_scope", "form_type",
    "form_completed_on", "risk_category", "is_pep", "identification_confirmed",
    "identification_date", "next_review_due", "requires_second_approval",
    "recorded_by", "recorded_at", "confirmation_hash",
)
KYC_REDACTABLE = ("external_reference", "note")


def _kyc_sqlite_triggers(fixed: tuple[str, ...]) -> tuple[str, str]:
    changed = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in fixed)
    bad = " OR ".join(
        f"(NEW.{c} IS NOT OLD.{c} AND NEW.{c} IS NOT NULL AND NEW.{c} != '{REDACTION_MARKER}')"
        for c in KYC_REDACTABLE
    )
    return (
        "CREATE TRIGGER IF NOT EXISTS trg_kyc_confirmations_no_update "
        f"BEFORE UPDATE ON kyc_confirmations FOR EACH ROW WHEN {changed} OR {bad} "
        "BEGIN SELECT RAISE(ABORT, 'kyc_confirmations is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_kyc_confirmations_no_delete "
        "BEFORE DELETE ON kyc_confirmations FOR EACH ROW "
        "BEGIN SELECT RAISE(ABORT, 'kyc_confirmations is immutable'); END",
    )


def _kyc_pg_function(fixed: tuple[str, ...]) -> str:
    changed = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in fixed)
    bad = " OR ".join(
        f"(NEW.{c} IS DISTINCT FROM OLD.{c} AND NEW.{c} IS NOT NULL AND NEW.{c} <> '{REDACTION_MARKER}')"
        for c in KYC_REDACTABLE
    )
    return (
        "CREATE OR REPLACE FUNCTION kyc_confirmations_immutable() RETURNS trigger AS $$\n"
        "BEGIN\n"
        "    IF TG_OP = 'DELETE' THEN\n"
        "        RAISE EXCEPTION 'kyc_confirmations is immutable';\n"
        "    END IF;\n"
        "    IF " + changed + " OR " + bad + " THEN\n"
        "        RAISE EXCEPTION 'kyc_confirmations is immutable';\n"
        "    END IF;\n"
        "    RETURN NEW;\n"
        "END;\n"
        "$$ LANGUAGE plpgsql"
    )


def _append_only_sqlite(table: str) -> tuple[str, str]:
    return (
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_update "
        f"BEFORE UPDATE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
        f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_delete "
        f"BEFORE DELETE ON {table} FOR EACH ROW "
        f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END",
    )


def _append_only_pg(table: str) -> tuple[str, str]:
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
        "kyc_review_policies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("jurisdiction", sa.String(), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("normal_max_months", sa.Integer(), nullable=False),
        sa.Column("elevated_max_months", sa.Integer(), nullable=True),
        sa.Column("valid_from", sa.String(), nullable=False),
        sa.Column("valid_until", sa.String(), nullable=True),
        sa.Column("source_reference", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("policy_hash", sa.String(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_kyc_review_policies_version"),
        sa.CheckConstraint("normal_max_months > 0", name="ck_kyc_review_policies_normal"),
        sa.CheckConstraint(
            "elevated_max_months IS NULL OR "
            "(elevated_max_months > 0 AND elevated_max_months <= normal_max_months)",
            name="ck_kyc_review_policies_elevated",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="ck_kyc_review_policies_validity",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "jurisdiction", "version", name="uq_kyc_review_policies_version"),
    )
    op.create_table(
        "kyc_review_policy_activations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("jurisdiction", sa.String(), nullable=False),
        sa.Column("policy_row_id", sa.String(), nullable=False),
        sa.Column("predecessor_activation_id", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=False),
        sa.Column("approved_at", sa.String(), nullable=False),
        sa.Column("approval_reference", sa.String(), nullable=False),
        sa.Column("policy_hash", sa.String(), nullable=False),
        sa.Column("activation_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_row_id"),
        sa.UniqueConstraint(
            "tenant_id", "jurisdiction", "predecessor_activation_id",
            name="uq_kyc_review_policy_activations_chain",
        ),
    )
    for name, type_ in BINDING_COLUMNS:
        op.add_column("kyc_confirmations", sa.Column(name, type_(), nullable=True))

    fixed = KYC_FIXED_BASE + tuple(name for name, _type in BINDING_COLUMNS)
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_kyc_confirmations_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_kyc_confirmations_no_delete")
        for ddl in _kyc_sqlite_triggers(fixed):
            op.execute(ddl)
        for table in NEW_APPEND_ONLY_TABLES:
            for ddl in _append_only_sqlite(table):
                op.execute(ddl)
    elif dialect == "postgresql":
        # Funktion ersetzen; der Trigger trg_kyc_confirmations_immutable (H8)
        # ruft sie unveraendert auf.
        op.execute(_kyc_pg_function(fixed))
        for table in NEW_APPEND_ONLY_TABLES:
            for ddl in _append_only_pg(table):
                op.execute(ddl)


def _evidence_present() -> list[str]:
    bind = op.get_bind()
    found: list[str] = []
    for table in NEW_APPEND_ONLY_TABLES:
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar():
            found.append(table)
    if bind.execute(sa.text(
        "SELECT COUNT(*) FROM kyc_confirmations WHERE review_policy_row_id IS NOT NULL"
    )).scalar():
        found.append("kyc_confirmations (Policy-Bindung)")
    return found


def downgrade() -> None:
    found = _evidence_present()
    if found:
        raise RuntimeError(
            "C-890-01 Downgrade abgelehnt (fail-closed): vorhandene Evidenz wuerde "
            "vernichtet: " + ", ".join(found) + ". Datenbank aus Sicherung "
            "wiederherstellen statt zurueckzumigrieren."
        )
    dialect = op.get_bind().dialect.name
    for table in NEW_APPEND_ONLY_TABLES:
        if dialect == "postgresql":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
        elif dialect == "sqlite":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
    if dialect == "sqlite":
        # batch_alter_table baut die Tabelle neu; die Trigger zuerst entfernen
        # und danach mit der H8-Spaltenliste neu anlegen.
        op.execute("DROP TRIGGER IF EXISTS trg_kyc_confirmations_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_kyc_confirmations_no_delete")
    with op.batch_alter_table("kyc_confirmations") as batch:
        for name, _type in reversed(BINDING_COLUMNS):
            batch.drop_column(name)
    if dialect == "sqlite":
        for ddl in _kyc_sqlite_triggers(KYC_FIXED_BASE):
            op.execute(ddl)
    elif dialect == "postgresql":
        op.execute(_kyc_pg_function(KYC_FIXED_BASE))
    op.drop_table("kyc_review_policy_activations")
    op.drop_table("kyc_review_policies")
