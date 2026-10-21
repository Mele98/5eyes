"""Append-only RiskProfileSignoffV1 + Signoff-Pointer/-Status am Assessment.

RISK-PROFILE-SIGNOFF-001 (Codex-Closure-Review zu PR #657, 2026-10-20):
jede Signatur des Risikoprofils schreibt eine unveraenderliche, gehashte
Signoff-Zeile, gebunden an Assessment-Version, wirksames Profil und die
verifizierte Override-Decision (oder 'no_override'). risk_assessments traegt
nur Pointer (signoff_id/_hash) und Status (signoff_status). Ein Override
setzt den Status auf 'signature_required'. UPDATE/DELETE auf der Signoff-
Tabelle sind per Trigger verboten (SQLite und PostgreSQL); wie
risk_override_decisions KEIN FK auf risk_assessments/mandates (Purge-fest).

Altbestand: vorhandene Signaturen ohne Snapshot werden als 'legacy_unbound'
("Altsignatur, nicht an Decision gebunden") markiert -- sichtbar, nie still
als gebunden ausgegeben, keine rueckdatierte synthetische Evidence.

Revision ID: d7b3f1a9c2e4
Revises: c4e9a7d2b815
Create Date: 2026-10-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7b3f1a9c2e4"
down_revision: Union[str, Sequence[str], None] = "c4e9a7d2b815"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS trg_risk_profile_signoffs_no_update "
    "BEFORE UPDATE ON risk_profile_signoffs FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'risk_profile_signoffs is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_risk_profile_signoffs_no_delete "
    "BEFORE DELETE ON risk_profile_signoffs FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'risk_profile_signoffs is immutable'); END",
)

_PG_FUNCTION = """
CREATE OR REPLACE FUNCTION risk_profile_signoffs_immutable()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'risk_profile_signoffs is immutable';
END;
$$ LANGUAGE plpgsql
"""

_PG_TRIGGER = """
CREATE TRIGGER trg_risk_profile_signoffs_immutable
BEFORE UPDATE OR DELETE ON risk_profile_signoffs
FOR EACH ROW EXECUTE FUNCTION risk_profile_signoffs_immutable()
"""

_LEGACY_BACKFILL = (
    "UPDATE risk_assessments SET signoff_status = 'legacy_unbound' "
    "WHERE client_signed_at IS NOT NULL AND signoff_id IS NULL "
    "AND signoff_status IS NULL"
)


def upgrade() -> None:
    op.create_table(
        "risk_profile_signoffs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("assessment_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=True),
        sa.Column("assessment_version", sa.Integer(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("previous_signoff_id", sa.String(), nullable=True),
        sa.Column("effective_score_x10", sa.Integer(), nullable=False),
        sa.Column("effective_profile", sa.String(), nullable=False),
        sa.Column("final_score_x10", sa.Integer(), nullable=False),
        sa.Column("final_profile", sa.String(), nullable=True),
        sa.Column("is_overridden", sa.Integer(), nullable=False),
        sa.Column("override_binding", sa.String(), nullable=False),
        sa.Column("override_decision_id", sa.String(), nullable=True),
        sa.Column("override_decision_hash", sa.String(), nullable=True),
        sa.Column("override_rules_version", sa.String(), nullable=True),
        sa.Column("assessment_input_hash", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=True),
        sa.Column("document_hash", sa.String(), nullable=True),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("evidence_level", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("actor_role", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("signed_at", sa.String(), nullable=False),
        sa.Column("rules_version", sa.String(), nullable=False),
        sa.Column("signoff_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        # Wie audit_log/risk_override_decisions: nur der Akteur per FK.
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "override_binding IN ('decision','no_override')",
            name="ck_risk_profile_signoff_binding",
        ),
        sa.CheckConstraint(
            "(override_binding = 'decision' AND override_decision_id IS NOT NULL "
            "AND override_decision_hash IS NOT NULL) OR (override_binding = 'no_override' "
            "AND override_decision_id IS NULL AND override_decision_hash IS NULL)",
            name="ck_risk_profile_signoff_binding_refs",
        ),
        sa.CheckConstraint(
            "method IN ('advisor_recorded','portal')",
            name="ck_risk_profile_signoff_method",
        ),
        sa.CheckConstraint(
            "evidence_level IN ('advisor_attested','client_portal')",
            name="ck_risk_profile_signoff_evidence",
        ),
    )
    op.create_index(
        "ux_risk_profile_signoff_sequence",
        "risk_profile_signoffs",
        ["assessment_id", "sequence_no"],
        unique=True,
    )
    op.create_index(
        "ix_risk_profile_signoffs_mandate",
        "risk_profile_signoffs",
        ["mandate_id"],
    )
    op.add_column("risk_assessments", sa.Column("signoff_id", sa.String(), nullable=True))
    op.add_column("risk_assessments", sa.Column("signoff_hash", sa.String(), nullable=True))
    op.add_column("risk_assessments", sa.Column("signoff_status", sa.String(), nullable=True))
    # System-Ereignis-Kennzeichnung im Beratungsprotokoll: ein Portal-Signoff
    # ist kein Beratungsgespraech und zaehlt nie als "letzter Termin".
    op.add_column("advisory_log", sa.Column("system_event", sa.String(), nullable=True))
    op.execute(_LEGACY_BACKFILL)

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for ddl in _SQLITE_TRIGGERS:
            op.execute(ddl)
    elif dialect == "postgresql":
        op.execute(_PG_FUNCTION)
        op.execute(_PG_TRIGGER)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_risk_profile_signoffs_immutable ON risk_profile_signoffs")
        op.execute("DROP FUNCTION IF EXISTS risk_profile_signoffs_immutable()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_risk_profile_signoffs_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_risk_profile_signoffs_no_delete")
    op.drop_column("advisory_log", "system_event")
    op.drop_column("risk_assessments", "signoff_status")
    op.drop_column("risk_assessments", "signoff_hash")
    op.drop_column("risk_assessments", "signoff_id")
    op.drop_index("ix_risk_profile_signoffs_mandate", table_name="risk_profile_signoffs")
    op.drop_index("ux_risk_profile_signoff_sequence", table_name="risk_profile_signoffs")
    op.drop_table("risk_profile_signoffs")
