"""RiskCapacityPlausibilityEvaluationV1 -- append-only, gehashte Evidenz der
Plausibilitaetspruefung der Risikofaehigkeit.

RISK-CAPACITY-EVALUATION-SNAPSHOT-001 (Residual der Codex-Closure-Reviews
PR #647/#653/#677): die Bewertung wurde nur live gerechnet; spaetere
Datenaenderungen veraenderten nachtraeglich, was bei der Beratung galt. Jede
beim Speichern des Risikoprofils bzw. bei der Generierung gebundene Bewertung
wird jetzt mit Eingaben, Regelversion, Ergebnis und kanonischem Hash
gespeichert. UPDATE/DELETE per Trigger verboten (SQLite und PostgreSQL).

Mandantentrennung: ``tenant_id`` direkt (RLS ENABLE + FORCE und die strikte
Policy folgen beim Boot ueber ``ensure_postgres_rls_policies``); auf
PostgreSQL zusaetzlich derselbe INSERT-Guard wie fuer die uebrige
Risiko-Evidence (services/risk_evidence_tenant_boundary.py): Mandant aus dem
Mandat abgeleitet, Kunde = Kunde des Mandats, Assessment gehoert zum Mandat.
Neue Tabelle, kein Backfill.

Revision ID: a7c4e9b2d1f3
Revises: b5d2e8f41a73
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

from services import risk_evidence_tenant_boundary as retb


revision: str = "a7c4e9b2d1f3"
down_revision: Union[str, Sequence[str], None] = "b5d2e8f41a73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "risk_capacity_plausibility_evaluations"

_SQLITE_TRIGGERS = (
    f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_no_update "
    f"BEFORE UPDATE ON {TABLE} FOR EACH ROW "
    f"BEGIN SELECT RAISE(ABORT, '{TABLE} is immutable'); END",
    f"CREATE TRIGGER IF NOT EXISTS trg_{TABLE}_no_delete "
    f"BEFORE DELETE ON {TABLE} FOR EACH ROW "
    f"BEGIN SELECT RAISE(ABORT, '{TABLE} is immutable'); END",
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
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=True),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=True),
        sa.Column("assessment_id", sa.String(), nullable=True),
        sa.Column("binding_context", sa.String(), nullable=False),
        sa.Column("binding_record_id", sa.String(), nullable=False),
        sa.Column("as_of_date", sa.String(), nullable=False),
        sa.Column("rules_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("inputs_json", sa.Text(), nullable=True),
        sa.Column("inputs_hash", sa.String(length=64), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("evaluation_hash", sa.String(length=64), nullable=True),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("evaluated_at", sa.String(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "binding_context IN ('risk_assessment_saved','allocation_generated')",
            name="ck_risk_capacity_evaluation_binding_context",
        ),
        # Muster audit_log/risk_profile_signoffs: kein FK auf mandates/
        # risk_assessments (Purge-fest), nur der Akteur verweist auf users.
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_risk_capacity_plausibility_evaluations_mandate", TABLE, ["mandate_id", "evaluated_at"],
    )
    op.create_index("ix_risk_capacity_plausibility_evaluations_tenant_id", TABLE, ["tenant_id"])

    dialect = _dialect()
    if dialect == "sqlite":
        for ddl in _SQLITE_TRIGGERS:
            op.execute(ddl)
    elif dialect == "postgresql":
        op.execute(_PG_FUNCTION)
        op.execute(_PG_TRIGGER)
        op.execute(retb.POSTGRES_FUNCTION)
        for ddl in retb.postgres_triggers(TABLE):
            op.execute(ddl)


def downgrade() -> None:
    dialect = _dialect()
    if dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {retb.guard_trigger_name(TABLE)} ON {TABLE}")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_immutable ON {TABLE}")
        op.execute(f"DROP FUNCTION IF EXISTS {TABLE}_immutable()")
    elif dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_no_delete")
    op.drop_index("ix_risk_capacity_plausibility_evaluations_tenant_id", table_name=TABLE)
    op.drop_index("ix_risk_capacity_plausibility_evaluations_mandate", table_name=TABLE)
    op.drop_table(TABLE)
