"""Goal-Lifecycle: Entscheidungs-Spalte + append-only Transitionsprotokoll (ADR-3).

GOAL-PAST-DATE-LIFECYCLE-001. Owner-Entscheide vom 2026-10-11:
3a (sechs Zustaende, append-only auditiert), 3b Variante 3 (fail-closed),
3c (Begruendung + Actor + Zeitstempel fuer Terminal-Zustaende).

Revision ID: f4a81c6b2e37
Revises: b6e1d93af274
Create Date: 2026-10-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a81c6b2e37"
down_revision: Union[str, Sequence[str], None] = "b6e1d93af274"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Wiederkehrende Zieltypen -- dort kann `horizon_years` allein den
# Zahlungsplan nicht ausdruecken (siehe Quarantaene-Begruendung unten).
_RECURRING_GOAL_TYPES = ("Wiederkehrende_Ausgabe", "Pensionsausgabe")


def upgrade() -> None:
    op.add_column("goals", sa.Column("lifecycle_decision", sa.String(), nullable=True))

    op.create_table(
        "goal_lifecycle_transitions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("goal_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("from_state", sa.String(), nullable=True),
        sa.Column("to_state", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"]),
        sa.ForeignKeyConstraint(["mandate_id"], ["mandates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_goal_lifecycle_transitions_goal_id",
        "goal_lifecycle_transitions",
        ["goal_id"],
    )

    # ------------------------------------------------------------------
    # Legacy-Quarantaene
    # ------------------------------------------------------------------
    # Codex-Review 2026-10-11: "Legacy-Zeilen ohne eindeutigen Anker werden
    # weiter interpretiert statt quarantaenisiert." Richtig -- aber nur fuer
    # die Zeilen, bei denen der Plan WIRKLICH nicht ableitbar ist.
    #
    # Abgrenzung (bewusst enger als "alle datumslosen Ziele"):
    #
    #   Einmalziel ohne target_date      -> `horizon_years = N` heisst
    #                                       eindeutig "in N Jahren faellig".
    #                                       NICHT quarantaenisiert.
    #   Wiederkehrender Strom ohne
    #   start_date UND ohne target_date  -> eine einzige Zahl kann nicht
    #                                       gleichzeitig Beginn UND Dauer
    #                                       ausdruecken. Der Zahlungsplan
    #                                       ist nicht ableitbar.
    #                                       QUARANTAENISIERT.
    #
    # Alle datumslosen Ziele zu quarantaenisieren haette echte Information
    # verworfen; nur die wirklich mehrdeutigen zu markieren ist die
    # praezisere Regel.
    #
    # WIRKUNG, ausdruecklich: `historical_unknown` ist wirtschaftlich NULL
    # (services/goal_lifecycle.py::ECONOMICALLY_NULL_STATES). Die
    # Verbindlichkeit betroffener Mandate sinkt dadurch. Das ist die
    # fail-closed Richtung -- wir wissen nicht, wann das Geld gebraucht
    # wird, also erfinden wir es nicht -- aber es ist eine inhaltliche
    # Aenderung, keine reine Schema-Migration.
    #
    # Diese Ziele BLOCKIEREN die Berechnung NICHT (anders als `overdue`).
    # Begruendung: das ist ein Artefakt unserer Schema-Historie, keine
    # Beraterentscheidung. Jeden Berater mit Alt-Mandaten auszusperren,
    # bis er Daten nachtraegt, die er nie erfassen konnte, waere eine
    # Strafe fuer unsere Vergangenheit. Das Ziel bleibt sichtbar und
    # traegt einen Zustand, der eine Klaerung verlangt.
    bind = op.get_bind()
    placeholders = ", ".join(f"'{t}'" for t in _RECURRING_GOAL_TYPES)
    result = bind.execute(
        sa.text(
            f"""
            UPDATE goals
               SET lifecycle_decision = 'historical_unknown'
             WHERE deleted_at IS NULL
               AND lifecycle_decision IS NULL
               AND goal_type IN ({placeholders})
               AND (start_date IS NULL OR TRIM(start_date) = '')
               AND (target_date IS NULL OR TRIM(target_date) = '')
            """
        )
    )
    affected = getattr(result, "rowcount", None)
    if affected:
        print(
            f"[ADR-3] {affected} wiederkehrende Ziel(e) ohne Start- und "
            "Enddatum auf 'historical_unknown' gesetzt -- wirtschaftlich "
            "null bis ein Berater entscheidet."
        )


def downgrade() -> None:
    op.drop_index(
        "ix_goal_lifecycle_transitions_goal_id",
        table_name="goal_lifecycle_transitions",
    )
    op.drop_table("goal_lifecycle_transitions")
    op.drop_column("goals", "lifecycle_decision")
