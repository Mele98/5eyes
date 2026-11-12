"""goals: ux_goals_rank_active und CHECK (rank >= 1) auch unter PostgreSQL.

N-868-1 (Dok. 86, Pruefrunde #868): Das Rohschema der Desktop-App
(ares_schema.sql) fuehrt den partiellen Unique-Index
``ux_goals_rank_active ON goals(mandate_id, rank) WHERE is_active = 1 AND
deleted_at IS NULL`` und ``CHECK(rank >= 1)``. Die Alembic-Kette (einziger
Schemaweg fuer PostgreSQL) hatte beides nicht: parallele Neuanlagen,
Reorder-Wettlaeufe und Reaktivierungen konnten still doppelte aktive Raenge
erzeugen. Der Rang ist die kanonische Prioritaet (Default-Gewicht,
Hauptziel); doppelte Raenge machen die Allokation nicht deterministisch.

Fail-closed (Muster d4e8f1a9c2b7/94089093281c): Vor dem Anlegen prueft die
Revision im RLS-Operator-Bypass auf doppelte aktive Raenge je Mandat und auf
Raenge < 1 und bricht mit der Liste ab. Reparatur ist ein Operator-Schritt,
keine stille Umnummerierung in der Migration: je betroffenem Mandat die
Reihenfolge ueber ``PUT /mandates/{id}/goals/order`` festlegen (auditiert).

PostgreSQL: Index + ``ck_goals_rank_positive``. SQLite (nur Alembic-Pfad,
z. B. Migrationstests): Index mit ``IF NOT EXISTS``, weil das Rohschema ihn
bereits anlegt; der CHECK steht dort im CREATE TABLE (SQLite kennt kein
ADD CONSTRAINT).

Revision ID: f8c1d5a3e7b2
Revises: e2f9a4c7b1d8
Create Date: 2026-11-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op

from services.tenant_context import BYPASS_GUC


revision: str = "f8c1d5a3e7b2"
down_revision: Union[str, Sequence[str], None] = "e2f9a4c7b1d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ux_goals_rank_active"
CHECK_NAME = "ck_goals_rank_positive"
_WHERE = "is_active = 1 AND deleted_at IS NULL"
_DUPLICATES_SQL = (
    "SELECT mandate_id, rank, count(*) AS n FROM goals "
    f"WHERE {_WHERE} GROUP BY mandate_id, rank HAVING count(*) > 1 "
    "ORDER BY mandate_id, rank LIMIT 50"
)
_NON_POSITIVE_SQL = "SELECT id, rank FROM goals WHERE rank < 1 ORDER BY id LIMIT 50"


def _dialect() -> str:
    if context.is_offline_mode():
        return context.get_context().dialect.name
    return op.get_bind().dialect.name


def _precheck(dialect: str) -> None:
    bind = op.get_bind()
    if dialect == "postgresql":
        bind.execute(sa.text(f"SELECT set_config('{BYPASS_GUC}', 'on', true)"))
    problems: list[str] = []
    duplicates = bind.execute(sa.text(_DUPLICATES_SQL)).all()
    if duplicates:
        problems.append(
            "doppelte aktive Raenge (Mandat/Rang/Anzahl): "
            + ", ".join(f"{mid}/{int(rank)}/{int(n)}" for mid, rank, n in duplicates)
        )
    non_positive = bind.execute(sa.text(_NON_POSITIVE_SQL)).all()
    if non_positive:
        problems.append(
            "Raenge < 1 (Ziel/Rang): " + ", ".join(f"{gid}/{int(rank)}" for gid, rank in non_positive)
        )
    if problems:
        raise RuntimeError(
            "N-868-1-Migration abgebrochen: " + "; ".join(problems) + ". Bitte je "
            "Mandat die Reihenfolge ueber PUT /mandates/{id}/goals/order festlegen "
            "(auditiert) und die Migration erneut starten. Keine stille Umnummerierung."
        )


def upgrade() -> None:
    dialect = _dialect()
    if not context.is_offline_mode():
        _precheck(dialect)
    if dialect == "postgresql":
        op.create_index(
            INDEX_NAME,
            "goals",
            ["mandate_id", "rank"],
            unique=True,
            postgresql_where=sa.text(_WHERE),
        )
        op.create_check_constraint(CHECK_NAME, "goals", "rank >= 1")
    else:
        op.create_index(
            INDEX_NAME,
            "goals",
            ["mandate_id", "rank"],
            unique=True,
            sqlite_where=sa.text(_WHERE),
            if_not_exists=True,
        )


def downgrade() -> None:
    if _dialect() == "postgresql":
        op.drop_constraint(CHECK_NAME, "goals", type_="check")
        op.drop_index(INDEX_NAME, table_name="goals")
    else:
        op.drop_index(INDEX_NAME, table_name="goals", if_exists=True)
