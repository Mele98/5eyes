"""InvestmentPreferenceDecisionV1 + Tenant-Review-Frist (E1 Nachhaltigkeit).

E1 Nachhaltigkeitspraeferenzen (Dok. 106, Entscheid E0, 2026-11-07): die
Nachhaltigkeitspraeferenz des Kunden wird je Mandat versioniert erfasst
(Antworten, neutraler Profilcode, Fragebogen-Version, Definitions-Hash,
Kenntnisnahme, Kundenbestaetigung, Review-Frist, Decision-Hash). Append-only:
UPDATE/DELETE per Trigger verboten (SQLite und PostgreSQL); KEIN FK auf
mandates/clients (Purge-fest), nur captured_by -> users.

Mandantentrennung: ``tenant_id`` direkt (RLS ENABLE + FORCE und die strikte
Policy folgen beim Boot ueber ``ensure_postgres_rls_policies``); auf
PostgreSQL derselbe INSERT-Guard wie fuer die uebrige Mandats-Evidenz
(Funktion ``mandate_evidence_tenant_from_mandate`` aus b8d4f2a6c9e1): Mandant
aus dem Mandat abgeleitet, Kunde = Kunde des Mandats. Neue Tabelle, kein
Backfill.

Dazu ``tenants.sustainability_review_months`` (nullable, NULL = Default 36
Monate als Hauspolitik, keine gesetzliche Frist) und
``contract_documents.bound_preference_decision_hash`` (E2a: Bindung eines
Kundendokuments an die bei der Erzeugung aktuelle Erfassung; nullable, kein
Backfill). Gleiche DDL wie database.py (SQLite-Laufzeitpatch) und
ares_schema.sql.

E2a (Codex-Vertrag 2026-11-08): Spalten ``preference_waived`` /
``waiver_reason_sealed`` (dokumentierter Verzicht, nur Anlageberatung),
``capture_channel`` (Kanal der Erhebung) und ``review_policy_version``.

Revision ID: f3a8c1e5b7d2
Revises: f2a4c6e8b0d1
Create Date: 2026-11-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "f3a8c1e5b7d2"
down_revision: Union[str, Sequence[str], None] = "f2a4c6e8b0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "investment_preference_decisions"
PG_GUARD_FUNCTION = "mandate_evidence_tenant_from_mandate"  # aus b8d4f2a6c9e1
TENANT_ERROR = "MANDATE_EVIDENCE_TENANT_MISMATCH"

_SQLITE_TRIGGERS = (
    f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_no_update "
    f"BEFORE UPDATE ON {TABLE} FOR EACH ROW "
    f"BEGIN SELECT RAISE(ABORT, '{TABLE} is immutable'); END",
    f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_no_delete "
    f"BEFORE DELETE ON {TABLE} FOR EACH ROW "
    f"BEGIN SELECT RAISE(ABORT, '{TABLE} is immutable'); END",
)
_SQLITE_GUARD = (
    f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_tenant_guard "
    f"BEFORE INSERT ON {TABLE} FOR EACH ROW "
    f"WHEN NEW.tenant_id IS NOT (SELECT m.tenant_id FROM mandates m WHERE m.id = NEW.mandate_id) "
    f"OR EXISTS (SELECT 1 FROM mandates m WHERE m.id = NEW.mandate_id "
    f"AND m.client_id IS NOT NEW.client_id) "
    f"BEGIN SELECT RAISE(ABORT, '{TENANT_ERROR}'); END"
)

_PG_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {TABLE}_immutable()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '{TABLE} is immutable';
END;
$$ LANGUAGE plpgsql
"""

_PG_TRIGGER = f"""
CREATE TRIGGER trg_{TABLE}_immutable
BEFORE UPDATE OR DELETE ON {TABLE}
FOR EACH ROW EXECUTE FUNCTION {TABLE}_immutable()
"""


def _dialect() -> str:
    if context.is_offline_mode():
        return context.get_context().dialect.name
    return op.get_bind().dialect.name


def upgrade() -> None:
    op.add_column("tenants", sa.Column("sustainability_review_months", sa.Integer(), nullable=True))
    op.add_column("contract_documents", sa.Column("bound_preference_decision_hash", sa.String(), nullable=True))
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=True),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("supersedes_id", sa.String(), nullable=True),
        sa.Column("questionnaire_version", sa.String(), nullable=False),
        sa.Column("definition_hash", sa.String(), nullable=False),
        sa.Column("derivation_version", sa.String(), nullable=False),
        sa.Column("response_status", sa.String(), nullable=False),
        sa.Column("esg_relevance", sa.String(), nullable=True),
        sa.Column("esg_characteristic", sa.String(), nullable=True),
        sa.Column("exclusions_json", sa.String(), nullable=False),
        sa.Column("preference_waived", sa.Integer(), nullable=False),
        sa.Column("waiver_reason_sealed", sa.String(), nullable=True),
        sa.Column("profile_code", sa.String(), nullable=False),
        sa.Column("information_acknowledged", sa.Integer(), nullable=False),
        sa.Column("client_confirmed", sa.Integer(), nullable=False),
        sa.Column("capture_channel", sa.String(), nullable=False),
        sa.Column("mandate_type_at_capture", sa.String(), nullable=True),
        sa.Column("review_policy_version", sa.String(), nullable=False),
        sa.Column("review_policy_months", sa.Integer(), nullable=False),
        sa.Column("review_due_on", sa.String(), nullable=False),
        sa.Column("captured_by", sa.String(), nullable=False),
        sa.Column("captured_at", sa.String(), nullable=False),
        sa.Column("decision_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint("sequence_no >= 1", name="ck_investment_preference_sequence"),
        sa.CheckConstraint(
            "response_status IN ('answered','declined')",
            name="ck_investment_preference_response_status",
        ),
        sa.CheckConstraint(
            "esg_relevance IS NULL OR esg_relevance IN ('yes','not_relevant')",
            name="ck_investment_preference_relevance",
        ),
        sa.CheckConstraint(
            "esg_characteristic IS NULL OR esg_characteristic IN "
            "('sdg_alignment','esg_factors','no_specific')",
            name="ck_investment_preference_characteristic",
        ),
        sa.CheckConstraint(
            "profile_code IN ('no_preference','sdg_goals','esg_factors','unspecified','declined')",
            name="ck_investment_preference_profile_code",
        ),
        sa.CheckConstraint(
            "information_acknowledged IN (0,1)", name="ck_investment_preference_information",
        ),
        sa.CheckConstraint("client_confirmed IN (0,1)", name="ck_investment_preference_confirmed"),
        sa.CheckConstraint("preference_waived IN (0,1)", name="ck_investment_preference_waived"),
        sa.CheckConstraint(
            "capture_channel IN ('in_person','phone','video','written')",
            name="ck_investment_preference_channel",
        ),
        # Muster risk_capacity_plausibility_evaluations: kein FK auf mandates/
        # clients (Purge-fest), nur der Erfasser verweist auf users.
        sa.ForeignKeyConstraint(["captured_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_investment_preference_decisions_sequence", TABLE, ["mandate_id", "sequence_no"], unique=True,
    )
    op.create_index("ix_investment_preference_decisions_tenant_id", TABLE, ["tenant_id"])

    dialect = _dialect()
    if dialect == "sqlite":
        for ddl in _SQLITE_TRIGGERS:
            op.execute(ddl)
        op.execute(_SQLITE_GUARD)
    elif dialect == "postgresql":
        op.execute(_PG_FUNCTION)
        op.execute(_PG_TRIGGER)
        op.execute(sa.text(
            f"CREATE TRIGGER trg_{TABLE}_tenant_guard BEFORE INSERT ON {TABLE} "
            f"FOR EACH ROW EXECUTE FUNCTION {PG_GUARD_FUNCTION}()"
        ))


def downgrade() -> None:
    dialect = _dialect()
    if dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_tenant_guard ON {TABLE}")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_immutable ON {TABLE}")
        op.execute(f"DROP FUNCTION IF EXISTS {TABLE}_immutable()")
    elif dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_tenant_guard")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_delete")
    op.drop_index("ix_investment_preference_decisions_tenant_id", table_name=TABLE)
    op.drop_index("ux_investment_preference_decisions_sequence", table_name=TABLE)
    op.drop_table(TABLE)
    op.drop_column("contract_documents", "bound_preference_decision_hash")
    op.drop_column("tenants", "sustainability_review_months")
