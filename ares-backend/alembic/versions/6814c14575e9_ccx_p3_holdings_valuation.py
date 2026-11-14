"""CCX-P3 Markt- und Depot-Wahrheit (Vertrag 2026-11-13 §6 + Nachtrag P3-FX).

Drei neue Tabellen (kein Backfill -- Bestand wird nie als bewertet,
vollstaendig oder entschieden markiert) und eine neue Spalte:

* ``holdings_valuation_snapshots``: Stichtag, Quelle, Beobachtungszeitpunkt,
  Referenzwaehrung, gebundene FX-Basis (``fx_basis_hash`` + Kurse),
  ``coverage_status`` COMPLETE|PARTIAL|UNKNOWN; COMPLETE verlangt Gesamt- und
  Beratungsvermoegen, sonst sind beide NULL (nie eine erfundene Summe).
* ``holdings_valuation_rows``: verlustfreie Positionsprojektion; einfuegbar nur
  bis ``position_count`` (danach geschlossen), unveraenderlich.
* ``position_decision_ledger``: KEEP|SELL|REVIEW je Depotposition, nur
  einfuegbar solange der P1-Envelope DRAFT ist, danach unveraenderlich.
* ``wealth_inflows.currency``: Waehrung des Vermoegenszuflusses; NULL =
  unbekannt (wird nie geraten).

Alle drei Tabellen sind append-only (no-replace/no-update/no-delete) und
mandantengebunden (INSERT-Guard aus dem Mandat; RLS ENABLE + FORCE folgen beim
Boot ueber ``ensure_postgres_rls_policies``). Gleiche DDL wie database.py
(SQLite-Laufzeitpatch) und ares_schema.sql.

Platz ``CCX_P3_REV``. Lineare Ordnung P1 ``2c62f9012c73`` -> P2
``d868f4eaa028`` -> P3 (diese Revision); bei der Integration (CCX-P4) wurde
``down_revision`` von der P1- auf die P2-Revision umgestellt.

Revision ID: 6814c14575e9
Revises: d868f4eaa028
Create Date: 2026-11-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "6814c14575e9"
down_revision: Union[str, Sequence[str], None] = "d868f4eaa028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SNAPSHOTS = "holdings_valuation_snapshots"
ROWS = "holdings_valuation_rows"
LEDGER = "position_decision_ledger"
ENVELOPES = "advisory_decision_envelopes"
TENANT_ERROR = "MANDATE_EVIDENCE_TENANT_MISMATCH"

# SQLite: textgleich database.py HOLDINGS_VALUATION_SQLITE_TRIGGERS +
# HOLDINGS_VALUATION_SQLITE_TENANT_GUARDS (eingefroren).
_SQLITE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS trg_holdings_valuation_snapshots_no_replace "
    "BEFORE INSERT ON holdings_valuation_snapshots FOR EACH ROW "
    "WHEN EXISTS (SELECT 1 FROM holdings_valuation_snapshots s WHERE s.id = NEW.id) "
    "OR EXISTS (SELECT 1 FROM holdings_valuation_snapshots s WHERE s.tenant_id = NEW.tenant_id "
    "AND s.mandate_id = NEW.mandate_id AND s.snapshot_hash = NEW.snapshot_hash) "
    "BEGIN SELECT RAISE(ABORT, 'holdings_valuation_snapshots row already exists (no replace)'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_holdings_valuation_snapshots_no_update "
    "BEFORE UPDATE ON holdings_valuation_snapshots FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'holdings_valuation_snapshots is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_holdings_valuation_snapshots_no_delete "
    "BEFORE DELETE ON holdings_valuation_snapshots FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'holdings_valuation_snapshots is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_holdings_valuation_rows_insert_guard "
    "BEFORE INSERT ON holdings_valuation_rows FOR EACH ROW "
    "WHEN (SELECT s.position_count FROM holdings_valuation_snapshots s "
    "WHERE s.id = NEW.snapshot_id AND s.tenant_id = NEW.tenant_id) IS NULL "
    "OR (SELECT count(*) FROM holdings_valuation_rows r WHERE r.snapshot_id = NEW.snapshot_id) "
    ">= (SELECT s.position_count FROM holdings_valuation_snapshots s WHERE s.id = NEW.snapshot_id) "
    "BEGIN SELECT RAISE(ABORT, 'holdings_valuation_rows: snapshot is closed'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_holdings_valuation_rows_no_replace "
    "BEFORE INSERT ON holdings_valuation_rows FOR EACH ROW "
    "WHEN EXISTS (SELECT 1 FROM holdings_valuation_rows r WHERE r.id = NEW.id) "
    "OR EXISTS (SELECT 1 FROM holdings_valuation_rows r WHERE r.snapshot_id = NEW.snapshot_id "
    "AND r.position_id = NEW.position_id) "
    "BEGIN SELECT RAISE(ABORT, 'holdings_valuation_rows row already exists (no replace)'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_holdings_valuation_rows_no_update "
    "BEFORE UPDATE ON holdings_valuation_rows FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'holdings_valuation_rows is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_holdings_valuation_rows_no_delete "
    "BEFORE DELETE ON holdings_valuation_rows FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'holdings_valuation_rows is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_position_decision_ledger_insert_guard "
    "BEFORE INSERT ON position_decision_ledger FOR EACH ROW "
    "WHEN (SELECT e.status FROM advisory_decision_envelopes e WHERE e.id = NEW.envelope_id) IS NOT 'DRAFT' "
    "OR (SELECT e.mandate_id FROM advisory_decision_envelopes e WHERE e.id = NEW.envelope_id) "
    "IS NOT NEW.mandate_id "
    "BEGIN SELECT RAISE(ABORT, 'position_decision_ledger: envelope is not DRAFT'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_position_decision_ledger_no_replace "
    "BEFORE INSERT ON position_decision_ledger FOR EACH ROW "
    "WHEN EXISTS (SELECT 1 FROM position_decision_ledger d WHERE d.id = NEW.id) "
    "OR EXISTS (SELECT 1 FROM position_decision_ledger d WHERE d.envelope_id = NEW.envelope_id "
    "AND d.position_id = NEW.position_id) "
    "BEGIN SELECT RAISE(ABORT, 'position_decision_ledger row already exists (no replace)'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_position_decision_ledger_no_update "
    "BEFORE UPDATE ON position_decision_ledger FOR EACH ROW "
    "BEGIN SELECT RAISE(ABORT, 'position_decision_ledger is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_position_decision_ledger_no_delete "
    "BEFORE DELETE ON position_decision_ledger FOR EACH ROW "
    "WHEN (SELECT e.status FROM advisory_decision_envelopes e WHERE e.id = OLD.envelope_id) IS NOT 'DRAFT' "
    "BEGIN SELECT RAISE(ABORT, 'position_decision_ledger is immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_holdings_valuation_snapshots_tenant_guard "
    "BEFORE INSERT ON holdings_valuation_snapshots FOR EACH ROW "
    "WHEN NEW.tenant_id IS NOT (SELECT m.tenant_id FROM mandates m WHERE m.id = NEW.mandate_id) "
    "BEGIN SELECT RAISE(ABORT, 'MANDATE_EVIDENCE_TENANT_MISMATCH'); END",
    "CREATE TRIGGER IF NOT EXISTS trg_position_decision_ledger_tenant_guard "
    "BEFORE INSERT ON position_decision_ledger FOR EACH ROW "
    "WHEN NEW.tenant_id IS NOT (SELECT m.tenant_id FROM mandates m WHERE m.id = NEW.mandate_id) "
    "BEGIN SELECT RAISE(ABORT, 'MANDATE_EVIDENCE_TENANT_MISMATCH'); END",
)
_SQLITE_TRIGGER_NAMES = (
    "trg_holdings_valuation_snapshots_no_replace",
    "trg_holdings_valuation_snapshots_no_update",
    "trg_holdings_valuation_snapshots_no_delete",
    "trg_holdings_valuation_rows_insert_guard",
    "trg_holdings_valuation_rows_no_replace",
    "trg_holdings_valuation_rows_no_update",
    "trg_holdings_valuation_rows_no_delete",
    "trg_position_decision_ledger_insert_guard",
    "trg_position_decision_ledger_no_replace",
    "trg_position_decision_ledger_no_update",
    "trg_position_decision_ledger_no_delete",
    "trg_holdings_valuation_snapshots_tenant_guard",
    "trg_position_decision_ledger_tenant_guard",
)

# PostgreSQL: dieselben Regeln als plpgsql (ein Guard je Tabelle). Unter RLS
# sieht die Mandats-/Snapshot-/Envelope-Abfrage nur den Mandanten der Session.
_PG_FUNCTIONS = (
    f"""CREATE OR REPLACE FUNCTION {SNAPSHOTS}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION '{SNAPSHOTS} is immutable';
  END IF;
  SELECT m.tenant_id INTO derived FROM mandates m WHERE m.id = NEW.mandate_id;
  IF derived IS NULL OR NEW.tenant_id IS DISTINCT FROM derived THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$""",
    f"""CREATE OR REPLACE FUNCTION {ROWS}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE expected integer;
DECLARE present integer;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION '{ROWS} is immutable';
  END IF;
  SELECT s.position_count INTO expected FROM {SNAPSHOTS} s
    WHERE s.id = NEW.snapshot_id AND s.tenant_id = NEW.tenant_id;
  SELECT count(*) INTO present FROM {ROWS} r WHERE r.snapshot_id = NEW.snapshot_id;
  IF expected IS NULL OR present >= expected THEN
    RAISE EXCEPTION '{ROWS}: snapshot is closed';
  END IF;
  RETURN NEW;
END $$""",
    f"""CREATE OR REPLACE FUNCTION {LEDGER}_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE derived text;
DECLARE envelope_status text;
DECLARE envelope_mandate text;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION '{LEDGER} is immutable';
  END IF;
  IF TG_OP = 'DELETE' THEN
    SELECT e.status INTO envelope_status FROM {ENVELOPES} e WHERE e.id = OLD.envelope_id;
    IF envelope_status IS DISTINCT FROM 'DRAFT' THEN
      RAISE EXCEPTION '{LEDGER} is immutable';
    END IF;
    RETURN OLD;
  END IF;
  SELECT e.status, e.mandate_id INTO envelope_status, envelope_mandate
    FROM {ENVELOPES} e WHERE e.id = NEW.envelope_id;
  IF envelope_status IS DISTINCT FROM 'DRAFT' OR envelope_mandate IS DISTINCT FROM NEW.mandate_id THEN
    RAISE EXCEPTION '{LEDGER}: envelope is not DRAFT';
  END IF;
  SELECT m.tenant_id INTO derived FROM mandates m WHERE m.id = NEW.mandate_id;
  IF derived IS NULL OR NEW.tenant_id IS DISTINCT FROM derived THEN
    RAISE EXCEPTION '{TENANT_ERROR}' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$""",
)
_PG_TRIGGERS = tuple(
    f"CREATE TRIGGER trg_{table}_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} "
    f"FOR EACH ROW EXECUTE FUNCTION {table}_guard()"
    for table in (SNAPSHOTS, ROWS, LEDGER)
)


def _dialect() -> str:
    if context.is_offline_mode():
        return context.get_context().dialect.name
    return op.get_bind().dialect.name


def upgrade() -> None:
    op.create_table(
        SNAPSHOTS,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("as_of", sa.String(), nullable=False),
        sa.Column("source_observed_at", sa.String(), nullable=True),
        sa.Column("source_system", sa.String(), nullable=False),
        sa.Column("base_currency", sa.String(), nullable=False),
        sa.Column("fx_basis_hash", sa.String(), nullable=False),
        sa.Column("fx_basis_json", sa.String(), nullable=False),
        sa.Column("coverage_status", sa.String(), nullable=False),
        sa.Column("holdings_basis", sa.String(), nullable=False),
        sa.Column("position_count", sa.Integer(), nullable=False),
        sa.Column("total_base_minor", sa.BigInteger(), nullable=True),
        sa.Column("advisory_base_minor", sa.BigInteger(), nullable=True),
        sa.Column("blocker_codes_json", sa.String(), nullable=False),
        sa.Column("snapshot_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.CheckConstraint(
            "schema_version = 'ares/holdings-valuation/1'",
            name="ck_holdings_valuation_snapshots_schema_version",
        ),
        sa.CheckConstraint("length(fx_basis_hash) = 64", name="ck_holdings_valuation_snapshots_fx_hash"),
        sa.CheckConstraint(
            "coverage_status IN ('COMPLETE','PARTIAL','UNKNOWN')",
            name="ck_holdings_valuation_snapshots_coverage",
        ),
        sa.CheckConstraint(
            "holdings_basis IN ('recorded','confirmed_no_holdings')",
            name="ck_holdings_valuation_snapshots_basis",
        ),
        sa.CheckConstraint("position_count >= 0", name="ck_holdings_valuation_snapshots_count"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_holdings_valuation_snapshots_hash"),
        sa.CheckConstraint(
            "coverage_status <> 'COMPLETE' OR (total_base_minor IS NOT NULL AND advisory_base_minor IS NOT NULL "
            "AND blocker_codes_json = '[]')",
            name="ck_holdings_valuation_snapshots_complete_total",
        ),
        sa.CheckConstraint(
            "coverage_status = 'COMPLETE' OR (total_base_minor IS NULL AND advisory_base_minor IS NULL "
            "AND blocker_codes_json <> '[]')",
            name="ck_holdings_valuation_snapshots_unknown_total",
        ),
        sa.CheckConstraint(
            "holdings_basis = 'recorded' OR position_count = 0",
            name="ck_holdings_valuation_snapshots_no_holdings",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_holdings_valuation_snapshots_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id", "mandate_id", "snapshot_hash", name="uq_holdings_valuation_snapshots_hash",
        ),
    )
    op.create_index("ix_holdings_valuation_snapshots_tenant_id", SNAPSHOTS, ["tenant_id"])
    op.create_index("ix_holdings_valuation_snapshots_mandate", SNAPSHOTS, ["tenant_id", "mandate_id", "as_of"])

    op.create_table(
        ROWS,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("position_id", sa.String(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("instrument_id", sa.String(), nullable=True),
        sa.Column("assignment", sa.String(), nullable=True),
        sa.Column("quantity_decimal_string", sa.String(), nullable=True),
        sa.Column("price_minor", sa.BigInteger(), nullable=True),
        sa.Column("price_currency", sa.String(), nullable=True),
        sa.Column("source_amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("fx_rate_ppm", sa.BigInteger(), nullable=True),
        sa.Column("fx_rate_ratio", sa.String(), nullable=True),
        sa.Column("fx_source", sa.String(), nullable=True),
        sa.Column("fx_observed_at", sa.String(), nullable=True),
        sa.Column("base_value_minor", sa.BigInteger(), nullable=True),
        sa.Column("price_observed_at", sa.String(), nullable=True),
        sa.Column("data_quality", sa.String(), nullable=False),
        sa.Column("included_in_total", sa.Integer(), nullable=False),
        sa.Column("row_hash", sa.String(), nullable=False),
        sa.CheckConstraint(
            "source_kind IN ('wealth_position','depot_holding')",
            name="ck_holdings_valuation_rows_source_kind",
        ),
        sa.CheckConstraint("included_in_total IN (0, 1)", name="ck_holdings_valuation_rows_included"),
        sa.CheckConstraint("length(row_hash) = 64", name="ck_holdings_valuation_rows_hash"),
        sa.CheckConstraint(
            "data_quality <> 'OK' OR base_value_minor IS NOT NULL",
            name="ck_holdings_valuation_rows_ok_value",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "snapshot_id"], [f"{SNAPSHOTS}.tenant_id", f"{SNAPSHOTS}.id"],
            name="fk_holdings_valuation_rows_snapshot",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "position_id", name="uq_holdings_valuation_rows_position"),
    )
    op.create_index("ix_holdings_valuation_rows_tenant_id", ROWS, ["tenant_id"])

    op.create_table(
        LEDGER,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("mandate_id", sa.String(), nullable=False),
        sa.Column("envelope_id", sa.String(), nullable=False),
        sa.Column("position_id", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("reason_code", sa.String(), nullable=False),
        sa.Column("source_snapshot_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.CheckConstraint("decision IN ('KEEP','SELL','REVIEW')", name="ck_position_decision_ledger_decision"),
        sa.CheckConstraint(
            "length(source_snapshot_hash) = 64", name="ck_position_decision_ledger_snapshot_hash",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "envelope_id"], [f"{ENVELOPES}.tenant_id", f"{ENVELOPES}.id"],
            name="fk_position_decision_ledger_envelope",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("envelope_id", "position_id", name="uq_position_decision_ledger_position"),
    )
    op.create_index("ix_position_decision_ledger_tenant_id", LEDGER, ["tenant_id"])
    op.create_index("ix_position_decision_ledger_mandate", LEDGER, ["tenant_id", "mandate_id"])

    op.add_column("wealth_inflows", sa.Column("currency", sa.String(), nullable=True))

    dialect = _dialect()
    if dialect == "sqlite":
        for ddl in _SQLITE_TRIGGERS:
            op.execute(ddl)
    elif dialect == "postgresql":
        for ddl in _PG_FUNCTIONS + _PG_TRIGGERS:
            op.execute(ddl)


def downgrade() -> None:
    dialect = _dialect()
    if dialect == "postgresql":
        for table in (LEDGER, ROWS, SNAPSHOTS):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_guard ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_guard()")
    elif dialect == "sqlite":
        for name in _SQLITE_TRIGGER_NAMES:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_column("wealth_inflows", "currency")
    op.drop_index("ix_position_decision_ledger_mandate", table_name=LEDGER)
    op.drop_index("ix_position_decision_ledger_tenant_id", table_name=LEDGER)
    op.drop_table(LEDGER)
    op.drop_index("ix_holdings_valuation_rows_tenant_id", table_name=ROWS)
    op.drop_table(ROWS)
    op.drop_index("ix_holdings_valuation_snapshots_mandate", table_name=SNAPSHOTS)
    op.drop_index("ix_holdings_valuation_snapshots_tenant_id", table_name=SNAPSHOTS)
    op.drop_table(SNAPSHOTS)
