"""CCX-05: jede bestehende Position bleibt sichtbar und erhaelt einen Entscheid.

``reconcile_existing_positions`` ist die reine Regel (12er-Vertrag): jede
bestehende Position erscheint im Ergebnis; was die Empfehlung weiterfuehrt,
ist KEEP, was zur Pruefung markiert ist REVIEW, alles andere SELL. Eine
Position verschwindet nie still aus dem Ledger.

``decide_positions`` wendet die Regel auf die Depotzeilen eines
Bewertungs-Snapshots an (Empfehlungsziel > 0 bps -> KEEP; nicht
uebernommene Altbestaende -> REVIEW), ``write_position_ledger`` schreibt den
Ledger im Envelope-DRAFT und ``ledger_child_hash`` bindet ihn per Kind-Hash
(ohne DB-IDs, die erst nach dem Hash entstehen).
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from core.advisory_envelope_codec import child_hash
from core.reason_codes import ReasonCode

KEEP = "KEEP"
SELL = "SELL"
REVIEW = "REVIEW"
LEDGER_KIND = "position-decision-ledger"


def reconcile_existing_positions(
    existing: Iterable[Any], selected: Iterable[Any], *, review: Iterable[Any] = (),
) -> dict[Any, str]:
    kept = set(selected)
    flagged = set(review)
    out: dict[Any, str] = {}
    for item in existing:
        if item in flagged:
            out[item] = REVIEW
        elif item in kept:
            out[item] = KEEP
        else:
            out[item] = SELL
    return out


def _decision_reason(decision: str) -> ReasonCode:
    if decision == KEEP:
        return ReasonCode.CCX_POSITION_IN_TARGET
    if decision == SELL:
        return ReasonCode.CCX_POSITION_NOT_IN_TARGET
    return ReasonCode.CCX_POSITION_NOT_CARRIED_OVER


def decide_positions(
    depot_rows: Iterable[Mapping[str, Any]], target_weight_by_product: Mapping[str, int],
) -> list[dict[str, Any]]:
    """Entscheid je Depotzeile (``position_id``, ``instrument_id``, ``data_quality``)."""
    rows = list(depot_rows)
    selected = {
        row["position_id"] for row in rows
        if int(target_weight_by_product.get(str(row.get("instrument_id") or ""), 0) or 0) > 0
    }
    review = {row["position_id"] for row in rows if row.get("data_quality") == "NOT_CARRIED_OVER"}
    decisions = reconcile_existing_positions([row["position_id"] for row in rows], selected, review=review)
    return [
        {"position_id": position_id, "decision": decision, "reason_code": str(_decision_reason(decision))}
        for position_id, decision in sorted(decisions.items())
    ]


def ledger_child_hash(entries: Iterable[Mapping[str, Any]], source_snapshot_hash: str) -> str:
    body = {
        "source_snapshot_hash": source_snapshot_hash,
        "decisions": [
            {"position_id": e["position_id"], "decision": e["decision"], "decision_reason": e["reason_code"]}
            for e in sorted(entries, key=lambda e: str(e["position_id"]))
        ],
    }
    return child_hash(LEDGER_KIND, json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def missing_decisions(position_ids: Iterable[str], entries: Iterable[Mapping[str, Any]]) -> list[str]:
    """Positionen ohne Entscheid (``CCX_POSITION_DECISION_MISSING``)."""
    decided = {str(e["position_id"]) for e in entries}
    return sorted(str(pid) for pid in position_ids if str(pid) not in decided)
