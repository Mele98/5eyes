"""K1 Property-Gate: Owner-Review-Spalte und Neutralisierung von Altwerten.

Codex-Entscheid 2026-11-19 ("Bis P1-Schliessung hart deaktivieren"): aktive
Werte deaktivierter Property-/Collateral-Funktionen im Bestand werden auf
Ignorieren/false/NULL gesetzt und je Position als Owner-Review-Fall in der neuen
Spalte ``wealth_positions.property_gate_review_json`` festgehalten (alter Wert,
Aktion) -- nicht still verworfen:

* ``is_available_for_goal_funding = 1`` auf illiquiden Positionen
  (Immobilien, Alternative, Custom, Vorsorge-Police) -> 0;
* ``goal_funding_method`` Belehnung (jede Position) bzw. Verkauf/Automatisch
  (illiquide Positionen) -> ``Ignorieren``;
* ``asset_expected_return_bps`` einer Direktimmobilie -> NULL.

Amortisationsbetraege bleiben (K1-Nachtrag 1, N-913-01: konstante Ausgabe).
Altbestand mit Hypothekartyp "Gemischt" bleibt unveraendert und wird offen
gemeldet.

N-913-06: die Regeln sind hier eingefroren (keine App-Importe); der SQLite-
Startpfad (``database.neutralize_legacy_property_values`` mit
``core.property_gate``) wendet dieselben Regeln an (Paritaetstest). Im
Offline-Modus (SQL-Skript) wird die Spalte angelegt; fuer PostgreSQL bricht das
Skript an dieser Stelle ab, falls neutralisierungspflichtige Altwerte existieren
(die Neutralisierung mit Review-JSON braucht den Online-Lauf) -- nie ein stilles
Ueberspringen.

Downgrade entfernt nur die Spalte; neutralisierte Werte werden bewusst nicht
zurueckgeschrieben (die alten Werte stehen im Review-JSON, das mit der Spalte
entfaellt -- deshalb vor einem Downgrade exportieren).

Lineare Kette ... P4 ``24e7606245d3`` -> K1 (diese Revision).

Revision ID: 63332bb56098
Revises: 24e7606245d3
Create Date: 2026-11-19
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "63332bb56098"
down_revision: Union[str, Sequence[str], None] = "24e7606245d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BYPASS_GUC = "app.rls_bypass"  # = services.tenant_context.BYPASS_GUC (eingefroren)
_ILLIQUID = {"Immobilien", "Immobilie", "Liegenschaft", "Alternative", "Custom"}
_PROPERTY = {"Immobilien", "Immobilie", "Liegenschaft"}
_MORTGAGE = "Hypothek"
_LEGACY_PREDICATE = (
    "deleted_at IS NULL AND ("
    "(is_available_for_goal_funding = 1 AND (position_type IN ('Immobilien','Immobilie','Liegenschaft',"
    "'Alternative','Custom') OR (position_type IN ('Vorsorge','Pensionskasse') AND pension_vehicle = 'Police'))) "
    "OR goal_funding_method = 'Belehnung' "
    "OR (goal_funding_method IN ('Verkauf','Automatisch') AND (position_type IN ('Immobilien','Immobilie',"
    "'Liegenschaft','Alternative','Custom') OR (position_type IN ('Vorsorge','Pensionskasse') "
    "AND pension_vehicle = 'Police'))) "
    "OR (position_type IN ('Immobilien','Immobilie','Liegenschaft') AND COALESCE(asset_expected_return_bps, 0) <> 0) "
    "OR (position_type = 'Hypothek' AND mortgage_type = 'Gemischt' AND property_gate_review_json IS NULL))"
)


def _findings(row) -> list[dict]:
    ptype = str(row["position_type"] or "").strip()
    illiquid = ptype in _ILLIQUID or (ptype in ("Vorsorge", "Pensionskasse") and row["pension_vehicle"] == "Police")
    out: list[dict] = []
    if int(row["is_available_for_goal_funding"] or 0) == 1 and illiquid:
        out.append({"feature": "goal_funding_collateral", "field": "is_available_for_goal_funding",
                    "previous": 1, "action": "set_0"})
    method = row["goal_funding_method"]
    if method == "Belehnung" or (method in ("Verkauf", "Automatisch") and illiquid):
        out.append({"feature": "goal_funding_method", "field": "goal_funding_method",
                    "previous": method, "action": "set_Ignorieren"})
    growth = int(row["asset_expected_return_bps"] or 0)
    if ptype in _PROPERTY and growth != 0:
        out.append({"feature": "property_return_input", "field": "asset_expected_return_bps",
                    "previous": growth, "action": "set_null"})
    if ptype == _MORTGAGE and row["mortgage_type"] == "Gemischt":
        out.append({"feature": "mortgage_type_mixed_legacy", "field": "mortgage_type",
                    "previous": "Gemischt", "action": "keep_open"})
    return out


_NEUTRAL = {"set_0": 0, "set_Ignorieren": "Ignorieren", "set_null": None}


def _neutralize(bind) -> None:
    recorded = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = bind.execute(sa.text(
        "SELECT id, position_type, pension_vehicle, is_available_for_goal_funding, goal_funding_method, "
        "asset_expected_return_bps, mortgage_type, property_gate_review_json FROM wealth_positions "
        f"WHERE {_LEGACY_PREDICATE} ORDER BY id"
    )).mappings().all()
    for row in rows:
        findings = _findings(row)
        actionable = [f for f in findings if f["action"] != "keep_open"]
        if not actionable and (not findings or row["property_gate_review_json"]):
            continue
        update = {f["field"]: _NEUTRAL[f["action"]] for f in actionable}
        update["property_gate_review_json"] = json.dumps(
            {"schema": "ares/property-gate-review/1", "reason_code": "PROPERTY_ADVANCED_FEATURE_DISABLED",
             "status": "OPEN", "recorded_at": recorded, "findings": findings},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        assignments = ", ".join(f"{column} = :{column}" for column in update)
        bind.execute(sa.text(f"UPDATE wealth_positions SET {assignments} WHERE id = :position_id"),
                     {**update, "position_id": row["id"]})


def upgrade() -> None:
    op.add_column("wealth_positions", sa.Column("property_gate_review_json", sa.String(), nullable=True))
    if context.is_offline_mode():
        if context.get_context().dialect.name == "postgresql":
            op.execute(
                "DO $$ BEGIN IF EXISTS (SELECT 1 FROM wealth_positions WHERE "
                + _LEGACY_PREDICATE
                + ") THEN RAISE EXCEPTION 'K1 63332bb56098: Altwerte deaktivierter Property-Funktionen "
                "vorhanden -- Migration online ausfuehren (Neutralisierung mit Owner-Review-JSON)'; "
                "END IF; END $$;"
            )
        return
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # wealth_positions hat FORCE RLS: Bestand vollstaendig ueber den
        # Operator-Bypass (nur fuer diese Transaktion) migrieren.
        op.execute(sa.text(f"SELECT set_config('{BYPASS_GUC}', 'on', true)"))
    _neutralize(bind)


def downgrade() -> None:
    op.drop_column("wealth_positions", "property_gate_review_json")
