"""CCX-P5b: Kanalzeile mit Mandats-FK und monotoner Nummer; IC-Freigabespalten.

N-925-08 (Vertrag 2026-11-13 §1 "monotone Version"):

* ``advisory_channel_publications.mandate_id`` erhaelt einen Fremdschluessel auf
  ``mandates(id)``.
* ``advisory_channel_publications.channel_sequence`` (INTEGER NOT NULL, >= 1):
  laufende Nummer je Mandat, eindeutig ``(mandate_id, channel_sequence)``, beim
  Einfuegen genau ``MAX + 1`` (Trigger). Bestand wird in Einfuegereihenfolge
  (``created_at``, ``id``) nachgetragen.
* ``optimizer_policies.ic_release_ref`` / ``ic_released_at`` (TEXT, leer): IC-
  Freigabe der Risikoparameter. Es wird NICHTS vorbelegt -- leer, bis das
  Anlagekomitee freigibt.

Gleiche DDL wie database.py (SQLite-Laufzeitpatch) und ares_schema.sql.

Lineare Kette: ... CCX-P5 ``c2546c196134`` -> CCX-P5b (diese Revision).

Revision ID: 74e3e973ea09
Revises: c2546c196134
Create Date: 2026-11-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "74e3e973ea09"
down_revision: Union[str, Sequence[str], None] = "c2546c196134"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "advisory_channel_publications"
ENVELOPES = "advisory_decision_envelopes"
TENANT_ERROR = "MANDATE_EVIDENCE_TENANT_MISMATCH"
SEQUENCE_ERROR = "CCX_CHANNEL_SEQUENCE_RACE"
SEQUENCE_INDEX = "ux_advisory_channel_publications_sequence"
MANDATE_FK = "fk_advisory_channel_publications_mandate"

_BACKFILL = (
    f"UPDATE {TABLE} SET channel_sequence = ("
    f"SELECT COUNT(*) FROM {TABLE} q "
    f"WHERE q.mandate_id = {TABLE}.mandate_id "
    f"AND (q.created_at < {TABLE}.created_at "
    f"OR (q.created_at = {TABLE}.created_at AND q.id <= {TABLE}.id)))"
)

# SQLite: textgleich database.py (eingefroren). Die P5-Trigger aus
# c2546c196134 werden nach dem Tabellen-Neuaufbau unveraendert neu angelegt.
_SQLITE_SEQUENCE_TRIGGER = (
    "CREATE TRIGGER IF NOT EXISTS trg_advisory_channel_publications_sequence "
    "BEFORE INSERT ON advisory_channel_publications FOR EACH ROW "
    "WHEN NEW.channel_sequence IS NOT (SELECT COALESCE(MAX(p.channel_sequence), 0) + 1 "
    "FROM advisory_channel_publications p WHERE p.mandate_id = NEW.mandate_id) "
    "BEGIN SELECT RAISE(ABORT, 'CCX_CHANNEL_SEQUENCE_RACE'); END"
)
_SQLITE_TRIGGERS = (_SQLITE_SEQUENCE_TRIGGER,)

_PG_GUARD_WITH_SEQUENCE = f"""CREATE OR REPLACE FUNCTION {TABLE}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION '{TABLE} is append-only';
  END IF;
  SELECT m.tenant_id INTO derived FROM mandates m WHERE m.id = NEW.mandate_id;
  IF derived IS NULL OR NEW.tenant_id IS DISTINCT FROM derived
     OR NEW.tenant_id IS DISTINCT FROM (SELECT COALESCE(NULLIF(u.tenant_id, ''), 'main') FROM users u
       WHERE u.id = NEW.created_by) THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  PERFORM 1 FROM {ENVELOPES} e WHERE e.id = NEW.envelope_id AND e.tenant_id = NEW.tenant_id
    AND e.mandate_id = NEW.mandate_id AND e.status = 'SEALED' AND e.envelope_hash = NEW.bound_envelope_hash;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'CCX_CHANNEL_BINDING_MISSING';
  END IF;
  IF NEW.channel_sequence IS DISTINCT FROM (SELECT COALESCE(MAX(p.channel_sequence), 0) + 1
       FROM {TABLE} p WHERE p.mandate_id = NEW.mandate_id) THEN
    RAISE EXCEPTION '{SEQUENCE_ERROR}' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$"""

# Funktion aus c2546c196134 (fuer den Downgrade, textgleich).
_PG_GUARD_P5 = f"""CREATE OR REPLACE FUNCTION {TABLE}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION '{TABLE} is append-only';
  END IF;
  SELECT m.tenant_id INTO derived FROM mandates m WHERE m.id = NEW.mandate_id;
  IF derived IS NULL OR NEW.tenant_id IS DISTINCT FROM derived
     OR NEW.tenant_id IS DISTINCT FROM (SELECT COALESCE(NULLIF(u.tenant_id, ''), 'main') FROM users u
       WHERE u.id = NEW.created_by) THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  PERFORM 1 FROM {ENVELOPES} e WHERE e.id = NEW.envelope_id AND e.tenant_id = NEW.tenant_id
    AND e.mandate_id = NEW.mandate_id AND e.status = 'SEALED' AND e.envelope_hash = NEW.bound_envelope_hash;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'CCX_CHANNEL_BINDING_MISSING';
  END IF;
  RETURN NEW;
END $$"""


def _dialect() -> str:
    if context.is_offline_mode():
        return context.get_context().dialect.name
    return op.get_bind().dialect.name


def _p5_sqlite_triggers() -> tuple[str, ...]:
    """Die eingefrorenen P5-Trigger aus der Vorgaenger-Revision (Neuaufbau)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).with_name("c2546c196134_ccx_p5_channel_envelope.py")
    spec = importlib.util.spec_from_file_location("ares_ccx_p5_revision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return tuple(module._SQLITE_TRIGGERS), tuple(module._SQLITE_TRIGGER_NAMES)


def upgrade() -> None:
    dialect = _dialect()
    op.add_column("optimizer_policies", sa.Column("ic_release_ref", sa.String(), nullable=True))
    op.add_column("optimizer_policies", sa.Column("ic_released_at", sa.String(), nullable=True))
    if dialect == "sqlite":
        p5_triggers, p5_names = _p5_sqlite_triggers()
        for name in p5_names:  # Neuaufbau verwirft Trigger; danach unveraendert neu
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
        op.add_column(TABLE, sa.Column("channel_sequence", sa.Integer(), nullable=True))
        op.execute(_BACKFILL)
        with op.batch_alter_table(TABLE, recreate="always") as batch:
            batch.alter_column("channel_sequence", existing_type=sa.Integer(), nullable=False)
            batch.create_check_constraint("ck_advisory_channel_publications_sequence", "channel_sequence >= 1")
            batch.create_foreign_key(MANDATE_FK, "mandates", ["mandate_id"], ["id"])
        op.create_index(SEQUENCE_INDEX, TABLE, ["mandate_id", "channel_sequence"], unique=True)
        for ddl in p5_triggers + _SQLITE_TRIGGERS:
            op.execute(ddl)
        return
    op.add_column(TABLE, sa.Column("channel_sequence", sa.Integer(), nullable=True))
    if dialect == "postgresql":
        # Nachtrag unter Operator-Bypass (RLS FORCE) und ohne append-only-Guard.
        op.execute("SET LOCAL app.rls_bypass = 'on'")
        op.execute(f"ALTER TABLE {TABLE} DISABLE TRIGGER trg_{TABLE}_guard")
        op.execute(_BACKFILL)
        op.execute(f"ALTER TABLE {TABLE} ENABLE TRIGGER trg_{TABLE}_guard")
        op.execute("SET LOCAL app.rls_bypass = 'off'")
    else:
        op.execute(_BACKFILL)
    op.alter_column(TABLE, "channel_sequence", existing_type=sa.Integer(), nullable=False)
    op.create_check_constraint("ck_advisory_channel_publications_sequence", TABLE, "channel_sequence >= 1")
    op.create_foreign_key(MANDATE_FK, TABLE, "mandates", ["mandate_id"], ["id"])
    op.create_index(SEQUENCE_INDEX, TABLE, ["mandate_id", "channel_sequence"], unique=True)
    if dialect == "postgresql":
        op.execute(_PG_GUARD_WITH_SEQUENCE)


def downgrade() -> None:
    dialect = _dialect()
    op.drop_index(SEQUENCE_INDEX, table_name=TABLE)
    if dialect == "sqlite":
        p5_triggers, p5_names = _p5_sqlite_triggers()
        for name in p5_names + ("trg_advisory_channel_publications_sequence",):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
        with op.batch_alter_table(TABLE, recreate="always") as batch:
            batch.drop_constraint(MANDATE_FK, type_="foreignkey")
            batch.drop_constraint("ck_advisory_channel_publications_sequence", type_="check")
            batch.drop_column("channel_sequence")
        for ddl in p5_triggers:
            op.execute(ddl)
    else:
        if dialect == "postgresql":
            op.execute(_PG_GUARD_P5)
        op.drop_constraint(MANDATE_FK, TABLE, type_="foreignkey")
        op.drop_constraint("ck_advisory_channel_publications_sequence", TABLE, type_="check")
        op.drop_column(TABLE, "channel_sequence")
    with op.batch_alter_table("optimizer_policies") as batch:
        batch.drop_column("ic_released_at")
        batch.drop_column("ic_release_ref")
