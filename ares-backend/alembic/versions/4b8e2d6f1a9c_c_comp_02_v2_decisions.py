"""C-COMP-02 V2: Vorab-Entscheide 6.1, 6.3 und 6.4 an der DB-Grenze.

* 6.1 Envelope-Schema: ``advisory_decision_envelopes.schema_version`` erlaubt
  zusaetzlich ``ares/advisory-envelope/2`` (neuer versiegelter Bestandteil
  ``product_evidence_set_hash``). Bestehende Zeilen bleiben unveraendert
  (nur gelockerter CHECK, keine Hochstufung, kein Neuversiegeln); V1 bleibt
  historisch pruefbar und ist fuer neue Kundenkanaele LEGACY/STALE.
* 6.3 ``product_evidence_snapshots``: neue Saetze nur mit allen drei
  Dimensionsbindungen (``eligibility_snapshot_id``, ``cost_snapshot_id``,
  ``conflict_snapshot_id`` = ``<dimension>:<sha256>``) und Schema 2. Altsaetze
  bleiben unberuehrt (Snapshots sind unveraenderlich) und werden STALE.
* 6.4 ``product_evidence_items``: Produkt-/Anteilsklassenidentitaet per
  Trigger (INSERT und UPDATE der Identitaetsspalten); eine fremde oder
  abweichende Anteilsklassenzeile scheitert an der Datenbank.

SQL eingefroren (Stand dieser Revision; Quelle core/product_evidence.py).
SQLite: der Envelope-CHECK wird nach dem dokumentierten writable_schema-
Verfahren gelockert (kein Tabellen-Neuaufbau, Trigger/FKs bleiben); die
Desktop-Laufzeit nutzt dafuer services/sqlite_check_constraint_upgrade.py
(Sicherung + Pruefung).

Revision ID: 4b8e2d6f1a9c
Revises: 9f4c2a7e1b63
Create Date: 2026-11-27
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op


revision: str = "4b8e2d6f1a9c"
down_revision: Union[str, Sequence[str], None] = "9f4c2a7e1b63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENVELOPES = "advisory_decision_envelopes"
ENVELOPE_CHECK = "ck_advisory_decision_envelopes_schema_version"
ENVELOPE_CHECK_V1 = "schema_version = 'ares/advisory-envelope/1'"
ENVELOPE_CHECK_V2 = "schema_version IN ('ares/advisory-envelope/1','ares/advisory-envelope/2')"
_LEGACY_CHECK = re.compile(r"CHECK\s*\(\s*schema_version\s*=\s*'ares/advisory-envelope/1'\s*\)", re.IGNORECASE)
_WIDE_CHECK = "CHECK(" + ENVELOPE_CHECK_V2 + ")"
_WIDE_CHECK_PATTERN = re.compile(
    r"CHECK\s*\(\s*schema_version\s+IN\s*\(\s*'ares/advisory-envelope/1'\s*,\s*'ares/advisory-envelope/2'\s*\)\s*\)",
    re.IGNORECASE,
)

SQLITE_IDENTITY_TRIGGERS = ("CREATE TRIGGER IF NOT EXISTS trg_product_evidence_identity_insert BEFORE INSERT ON product_evidence_items FOR EACH ROW WHEN EXISTS (SELECT 1 FROM products p WHERE p.id = NEW.product_id AND (NULLIF(trim(NEW.stable_instrument_id, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), '') IS NOT COALESCE(NULLIF(trim(p.isin, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), ''), NULLIF(trim(p.internal_product_id, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), ''), NULLIF(trim(p.figi, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), ''), p.id) OR NULLIF(trim(NEW.share_class_id, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), '') IS NOT NULLIF(trim(p.share_class_figi, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), ''))) BEGIN SELECT RAISE(ABORT, 'PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH: product_evidence_items: Nachweis gehoert nicht zur Produkt- oder Anteilsklassenidentitaet'); END", "CREATE TRIGGER IF NOT EXISTS trg_product_evidence_identity_update BEFORE UPDATE OF product_id, stable_instrument_id, share_class_id ON product_evidence_items FOR EACH ROW WHEN EXISTS (SELECT 1 FROM products p WHERE p.id = NEW.product_id AND (NULLIF(trim(NEW.stable_instrument_id, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), '') IS NOT COALESCE(NULLIF(trim(p.isin, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), ''), NULLIF(trim(p.internal_product_id, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), ''), NULLIF(trim(p.figi, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), ''), p.id) OR NULLIF(trim(NEW.share_class_id, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), '') IS NOT NULLIF(trim(p.share_class_figi, ' ' || char(9) || char(10) || char(11) || char(12) || char(13)), ''))) BEGIN SELECT RAISE(ABORT, 'PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH: product_evidence_items: Nachweis gehoert nicht zur Produkt- oder Anteilsklassenidentitaet'); END")
SQLITE_SNAPSHOT_BINDING_TRIGGER = "CREATE TRIGGER IF NOT EXISTS trg_product_evidence_snapshot_binding_insert BEFORE INSERT ON product_evidence_snapshots FOR EACH ROW WHEN NOT ((NEW.eligibility_snapshot_id IS NOT NULL AND substr(NEW.eligibility_snapshot_id, 1, 12) = 'eligibility:' AND length(NEW.eligibility_snapshot_id) = 76 AND ltrim(substr(NEW.eligibility_snapshot_id, 13), '0123456789abcdef') = '') AND (NEW.cost_snapshot_id IS NOT NULL AND substr(NEW.cost_snapshot_id, 1, 5) = 'cost:' AND length(NEW.cost_snapshot_id) = 69 AND ltrim(substr(NEW.cost_snapshot_id, 6), '0123456789abcdef') = '') AND (NEW.conflict_snapshot_id IS NOT NULL AND substr(NEW.conflict_snapshot_id, 1, 9) = 'conflict:' AND length(NEW.conflict_snapshot_id) = 73 AND ltrim(substr(NEW.conflict_snapshot_id, 10), '0123456789abcdef') = '') AND NEW.schema_version = 'ares-product-evidence/v2') BEGIN SELECT RAISE(ABORT, 'product_evidence_snapshots: Eignungs-, Kosten- und Konfliktsnapshot muessen gebunden sein (Schema ares-product-evidence/v2)'); END"
PG_IDENTITY_FUNCTION = "\nCREATE OR REPLACE FUNCTION product_evidence_items_identity()\nRETURNS trigger AS $$\nBEGIN\n    IF EXISTS (SELECT 1 FROM products p WHERE p.id = NEW.product_id AND (NULLIF(btrim(NEW.stable_instrument_id::text, ' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)), '') IS DISTINCT FROM COALESCE(NULLIF(btrim(p.isin::text, ' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)), ''), NULLIF(btrim(p.internal_product_id::text, ' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)), ''), NULLIF(btrim(p.figi::text, ' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)), ''), p.id) OR NULLIF(btrim(NEW.share_class_id::text, ' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)), '') IS DISTINCT FROM NULLIF(btrim(p.share_class_figi::text, ' ' || chr(9) || chr(10) || chr(11) || chr(12) || chr(13)), ''))) THEN\n        RAISE EXCEPTION 'PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH: product_evidence_items: Nachweis gehoert nicht zur Produkt- oder Anteilsklassenidentitaet';\n    END IF;\n    RETURN NEW;\nEND;\n$$ LANGUAGE plpgsql\n"
PG_IDENTITY_TRIGGER = 'CREATE TRIGGER trg_product_evidence_identity BEFORE INSERT OR UPDATE OF product_id, stable_instrument_id, share_class_id ON product_evidence_items FOR EACH ROW EXECUTE FUNCTION product_evidence_items_identity()'
PG_SNAPSHOT_BINDING_FUNCTION = "\nCREATE OR REPLACE FUNCTION product_evidence_snapshots_binding()\nRETURNS trigger AS $$\nBEGIN\n    IF NOT ((NEW.eligibility_snapshot_id IS NOT NULL AND substr(NEW.eligibility_snapshot_id, 1, 12) = 'eligibility:' AND length(NEW.eligibility_snapshot_id) = 76 AND ltrim(substr(NEW.eligibility_snapshot_id, 13), '0123456789abcdef') = '') AND (NEW.cost_snapshot_id IS NOT NULL AND substr(NEW.cost_snapshot_id, 1, 5) = 'cost:' AND length(NEW.cost_snapshot_id) = 69 AND ltrim(substr(NEW.cost_snapshot_id, 6), '0123456789abcdef') = '') AND (NEW.conflict_snapshot_id IS NOT NULL AND substr(NEW.conflict_snapshot_id, 1, 9) = 'conflict:' AND length(NEW.conflict_snapshot_id) = 73 AND ltrim(substr(NEW.conflict_snapshot_id, 10), '0123456789abcdef') = '') AND NEW.schema_version = 'ares-product-evidence/v2') THEN\n        RAISE EXCEPTION 'product_evidence_snapshots: Eignungs-, Kosten- und Konfliktsnapshot muessen gebunden sein (Schema ares-product-evidence/v2)';\n    END IF;\n    RETURN NEW;\nEND;\n$$ LANGUAGE plpgsql\n"
PG_SNAPSHOT_BINDING_TRIGGER = 'CREATE TRIGGER trg_product_evidence_snapshot_binding BEFORE INSERT ON product_evidence_snapshots FOR EACH ROW EXECUTE FUNCTION product_evidence_snapshots_binding()'


def _sqlite_rewrite_envelope_check(pattern: "re.Pattern[str]", replacement: str) -> None:
    """Dokumentiertes writable_schema-Verfahren (nur CHECK-Text, kein Neubau)."""
    bind = op.get_bind()
    table_sql = bind.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (ENVELOPES,),
    ).scalar()
    if table_sql is None:
        return
    matches = list(pattern.finditer(table_sql))
    if not matches:
        return  # bereits im Zielzustand
    if len(matches) != 1:
        raise RuntimeError(f"{ENVELOPES}: unbekannte CHECK-Form, manuelle Migration erforderlich")
    new_sql = table_sql[:matches[0].start()] + replacement + table_sql[matches[0].end():]
    version = bind.exec_driver_sql("PRAGMA schema_version").scalar()
    bind.exec_driver_sql("PRAGMA writable_schema = ON")
    try:
        bind.exec_driver_sql(
            "UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = ?", (new_sql, ENVELOPES),
        )
        bind.exec_driver_sql(f"PRAGMA schema_version = {int(version) + 1}")
    finally:
        bind.exec_driver_sql("PRAGMA writable_schema = OFF")
    problems = [row[0] for row in bind.exec_driver_sql("PRAGMA integrity_check").fetchall() if row[0] != "ok"]
    if problems:
        raise RuntimeError(f"{ENVELOPES}: integrity_check nach CHECK-Umschreibung: {problems[:3]}")


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.drop_constraint(ENVELOPE_CHECK, ENVELOPES, type_="check")
        op.create_check_constraint(ENVELOPE_CHECK, ENVELOPES, ENVELOPE_CHECK_V2)
        op.execute(PG_IDENTITY_FUNCTION)
        op.execute(PG_IDENTITY_TRIGGER)
        op.execute(PG_SNAPSHOT_BINDING_FUNCTION)
        op.execute(PG_SNAPSHOT_BINDING_TRIGGER)
    elif dialect == "sqlite":
        _sqlite_rewrite_envelope_check(_LEGACY_CHECK, _WIDE_CHECK)
        for statement in SQLITE_IDENTITY_TRIGGERS:
            op.execute(statement)
        op.execute(SQLITE_SNAPSHOT_BINDING_TRIGGER)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    remaining = op.get_bind().exec_driver_sql(
        "SELECT COUNT(*) FROM advisory_decision_envelopes WHERE schema_version = 'ares/advisory-envelope/2'"
    ).scalar()
    if remaining:
        # V2-Entscheide sind versiegelte Belege: kein stilles Verwerfen.
        raise RuntimeError("Downgrade verweigert: es existieren V2-Beratungsentscheide (ares/advisory-envelope/2)")
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_product_evidence_snapshot_binding ON product_evidence_snapshots")
        op.execute("DROP FUNCTION IF EXISTS product_evidence_snapshots_binding()")
        op.execute("DROP TRIGGER IF EXISTS trg_product_evidence_identity ON product_evidence_items")
        op.execute("DROP FUNCTION IF EXISTS product_evidence_items_identity()")
        op.drop_constraint(ENVELOPE_CHECK, ENVELOPES, type_="check")
        op.create_check_constraint(ENVELOPE_CHECK, ENVELOPES, ENVELOPE_CHECK_V1)
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_product_evidence_snapshot_binding_insert")
        op.execute("DROP TRIGGER IF EXISTS trg_product_evidence_identity_insert")
        op.execute("DROP TRIGGER IF EXISTS trg_product_evidence_identity_update")
        _sqlite_rewrite_envelope_check(_WIDE_CHECK_PATTERN, "CHECK (" + ENVELOPE_CHECK_V1 + ")")
