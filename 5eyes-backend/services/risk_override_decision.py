"""RiskOverrideDecisionV1 -- append-only, gehashter Nachweis jeder Override-
Entscheidung (RISK-OVERRIDE-WRITE-BOUNDARY-001, Restbefund B, Codex-Closure-
Review zu PR #646 vom 2026-10-19).

Vorher hielt das Assessment nur den LETZTEN Override und das Audit-Log nur den
Profilnamen -- fruehere Entscheidungen waren nicht rekonstruierbar. Jetzt:

* jede Entscheidung = eine unveraenderliche Zeile in risk_override_decisions;
* decision_hash = SHA-256 ueber den kanonischen JSON-Snapshot (sortierte
  Keys, ohne decision_hash selbst) -- jede nachtraegliche Aenderung eines
  gebundenen Felds faellt bei verify_decision() auf;
* das Assessment traegt nur den Pointer (override_decision_id/_hash);
* das Audit-Log traegt den Snapshot inkl. ID/Hash (replaybar).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA_VERSION = "RiskOverrideDecisionV1"

# Genau diese Felder gehen in den Hash ein (Reihenfolge irrelevant, die
# Serialisierung sortiert). Neue Felder nur mit neuer SCHEMA_VERSION.
HASHED_FIELDS: tuple[str, ...] = (
    "id",
    "schema_version",
    "assessment_id",
    "mandate_id",
    "client_id",
    "assessment_version",
    "sequence_no",
    "previous_decision_id",
    "basis_final_score_x10",
    "basis_final_profile",
    "basis_capacity_score_x10",
    "basis_willingness_score_x10",
    "requested_score_x10",
    "requested_profile",
    "reason",
    "client_confirmed",
    "warning_delivered",
    "warning_document_id",
    "required_client_confirmation",
    "required_warning",
    "actor_id",
    "decided_at",
    "rules_version",
)


def _value(decision: Any, name: str) -> Any:
    if isinstance(decision, dict):
        return decision.get(name)
    return getattr(decision, name, None)


def decision_payload(decision: Any) -> dict[str, Any]:
    """Kanonischer Snapshot (ohne Hash) eines Decision-Objekts oder -Dicts."""
    return {name: _value(decision, name) for name in HASHED_FIELDS}


def compute_decision_hash(decision: Any) -> str:
    canonical = json.dumps(
        decision_payload(decision), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_decision(decision: Any) -> bool:
    stored = _value(decision, "decision_hash")
    return bool(stored) and stored == compute_decision_hash(decision)


def decision_snapshot(decision: Any) -> dict[str, Any]:
    """Replaybarer Audit-Snapshot: Payload + decision_id + decision_hash.

    Profil und Score stehen vorne, weil die Audit-Ansicht im Monolithen nur
    die ersten Zeichen von new_value anzeigt (Reihenfolge ist fuer
    json.loads bedeutungslos)."""
    payload = decision_payload(decision)
    snapshot: dict[str, Any] = {
        "requested_profile": payload["requested_profile"],
        "requested_score_x10": payload["requested_score_x10"],
        "decision_id": payload["id"],
        "decision_hash": _value(decision, "decision_hash"),
    }
    for key in sorted(payload):
        snapshot.setdefault(key, payload[key])
    return snapshot


def decision_reference(decision_id: str | None, decision_hash: str | None) -> str:
    """Kurzreferenz fuer Meldungen/PDF: ``<id> (SHA-256 <erste 12 Hex>)``."""
    if not decision_id:
        return ""
    if not decision_hash:
        return str(decision_id)
    return f"{decision_id} (SHA-256 {str(decision_hash)[:12]})"


def resolve_assessment_decision(db, assessment: Any) -> tuple[str | None, str | None, bool | None]:
    """(decision_id, decision_hash, verified) fuer den wirksamen Override.

    verified ist nur True, wenn die Decision-Zeile existiert, zum Assessment
    gehoert, ihr neu berechneter Hash dem gespeicherten UND dem Pointer am
    Assessment entspricht und die Projektion (Score/Profil) mit ihr
    uebereinstimmt. (None, None, None) = kein Decision-Nachweis (Altbestand).
    """
    decision_id = getattr(assessment, "override_decision_id", None)
    pointer_hash = getattr(assessment, "override_decision_hash", None)
    if not decision_id:
        return None, None, None
    from models.profiling import RiskOverrideDecision

    decision = db.get(RiskOverrideDecision, decision_id)
    verified = bool(
        decision is not None
        and decision.assessment_id == getattr(assessment, "id", None)
        and decision.decision_hash == pointer_hash
        and verify_decision(decision)
        and decision.requested_score_x10 == getattr(assessment, "override_score_x10", None)
        and decision.requested_profile == getattr(assessment, "override_profile", None)
    )
    return decision_id, pointer_hash, verified
