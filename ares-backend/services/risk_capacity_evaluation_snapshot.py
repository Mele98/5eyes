"""RiskCapacityPlausibilityEvaluationV1 -- persistierte, replaybare Evidenz
der Plausibilitaetspruefung der Risikofaehigkeit.

RISK-CAPACITY-EVALUATION-SNAPSHOT-001 (Residual der Codex-Closure-Reviews
PR #647, #653 und #677): die Pruefung (services/risk_capacity_plausibility.py)
wurde nur zur Laufzeit gerechnet. Aenderten sich spaeter Cashflows,
Positionen, Ziele oder die Coverage-Bestaetigung, zeigte dieselbe Beratung
nachtraeglich ein anderes Ergebnis; was bei der Beratung galt, war nicht
mehr belegbar.

Jetzt gilt:

* Beim Speichern des Risikoprofils (``risk_assessment_saved``) und bei der
  Generierung der Soll-Allokation (``allocation_generated``) wird genau die
  angezeigte Bewertung als append-only Zeile gespeichert: verwendete
  Eingaben (Fragebogen-Baender, erfasste Finanzdaten in CHF-Rappen,
  Coverage-Bestaetigung, Schwellen), Regelversion, strukturiertes Ergebnis
  (Status, Reason-/Verification-Code, Pruef-IDs, Coverage, Datengrundlage)
  und ein SHA-256 ueber den kanonischen Snapshot. Mandant, Mandat, Kunde,
  Assessment, Akteur und Bindungsdatensatz sind im Hash gebunden.
* Kein Freitext: Ziel-Bezeichnungen und die daraus gebildeten Meldungstexte
  werden NICHT gespeichert (append-only, DSG Art. 32); das strukturierte
  Ergebnis haengt nicht von ihnen ab.
* Replay (``replay_snapshot``) prueft den Hash (Manipulation), rechnet das
  Ergebnis aus den gespeicherten Eingaben mit den Regeln neu (Abweichung)
  und vergleicht die Eingaben mit einer Live-Bewertung (Aktualitaet). Neue
  Daten, ein anderes aktuelles Risikoprofil oder geaenderte Regeln machen
  die Evidenz "neu zu pruefen" (``RECHECK_CODE``) -- die Zeile selbst wird
  nie ueberschrieben.

Die Pruefregeln und Schwellen bleiben unveraendert; dieses Modul bewertet
nichts selbst, es haelt nur fest und spielt nach.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from core.evidence import canonical_json

SCHEMA_VERSION = "RiskCapacityPlausibilityEvaluationV1"

CONTEXT_RISK_ASSESSMENT_SAVED = "risk_assessment_saved"
CONTEXT_ALLOCATION_GENERATED = "allocation_generated"
BINDING_CONTEXTS: tuple[str, ...] = (CONTEXT_RISK_ASSESSMENT_SAVED, CONTEXT_ALLOCATION_GENERATED)

INTEGRITY_VERIFIED = "verified"
INTEGRITY_NOT_REPLAYABLE = "not_replayable"   # Hash ok, Bewertung ohne auswertbare Eingaben
INTEGRITY_HASH_MISMATCH = "hash_mismatch"
INTEGRITY_RESULT_MISMATCH = "result_mismatch"
INTEGRITY_RULES_CHANGED = "rules_changed"
INTEGRITY_UNKNOWN_SCHEMA = "unknown_schema"
INTEGRITY_BINDING_MISMATCH = "binding_mismatch"

CURRENCY_CURRENT = "current"
CURRENCY_STALE = "stale"

STALE_NO_CURRENT_ASSESSMENT = "NO_CURRENT_RISK_ASSESSMENT"
STALE_ASSESSMENT_CHANGED = "RISK_ASSESSMENT_CHANGED"
STALE_INPUTS_CHANGED = "EVALUATION_INPUTS_CHANGED"
STALE_RULES_CHANGED = "PLAUSIBILITY_RULES_CHANGED"
STALE_INPUTS_UNAVAILABLE = "EVALUATION_INPUTS_UNAVAILABLE"
STALE_INTEGRITY = "EVALUATION_INTEGRITY_FAILED"

RECHECK_CODE = "RISK_CAPACITY_EVALUATION_RECHECK_REQUIRED"
RECHECK_LABEL = "neu zu prüfen"
RECHECK_TEXT = (
    "Plausibilitätsprüfung Risikofähigkeit neu zu prüfen: die bei der Beratung "
    "gespeicherte Bewertung entspricht nicht mehr der aktuellen Datenlage."
)

_STALE_TEXTS = {
    STALE_NO_CURRENT_ASSESSMENT: "Kein aktuelles Risikoprofil vorhanden.",
    STALE_ASSESSMENT_CHANGED: "Das aktuelle Risikoprofil ist ein anderes als das bewertete.",
    STALE_INPUTS_CHANGED: "Fragebogen-Angaben oder erfasste Finanzdaten haben sich seither geändert.",
    STALE_RULES_CHANGED: "Die Prüfregeln haben sich seither geändert.",
    STALE_INPUTS_UNAVAILABLE: "Die Bewertung konnte nicht vollständig ausgewertet werden.",
    STALE_INTEGRITY: "Die gespeicherte Bewertung ist nicht verifizierbar.",
}

# Reihenfolge = kanonischer Snapshot. Neue Felder nur mit neuer
# SCHEMA_VERSION -- sonst gaelten bestehende Zeilen als manipuliert.
HASHED_FIELDS: tuple[str, ...] = (
    "id",
    "schema_version",
    "tenant_id",
    "mandate_id",
    "client_id",
    "assessment_id",
    "binding_context",
    "binding_record_id",
    "as_of_date",
    "rules_version",
    "status",
    "inputs_json",
    "inputs_hash",
    "result_json",
    "evaluation_hash",
    "actor_id",
    "evaluated_at",
)


def _value(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _canonical(payload: Any) -> str:
    return canonical_json(payload)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshot_payload(row: Any) -> dict[str, Any]:
    return {name: _value(row, name) for name in HASHED_FIELDS}


def compute_snapshot_hash(row: Any) -> str:
    return _sha256(_canonical(snapshot_payload(row)))


# ---------------------------------------------------------------------------
# Eingaben und strukturiertes Ergebnis
# ---------------------------------------------------------------------------

def inputs_payload(captured: dict | None) -> dict | None:
    """Kanonische Eingaben einer vollstaendig ausgewerteten Bewertung.

    ``None``, wenn die Bewertung keine auswertbaren Eingaben hatte (kein
    Profil, Datenfehler, Programmfehler) -- sie bleibt dann als
    ``not_evaluable`` belegt, ist aber nicht nachrechenbar.
    """
    from services.risk_capacity_plausibility import PLAUSIBILITY_RULES_VERSION, THRESHOLDS

    if not captured or captured.get("declared") is None or captured.get("recorded") is None:
        return None
    recorded = asdict(captured["recorded"])
    # Freitext (Ziel-Bezeichnungen) nie in die append-only Evidenz.
    recorded["near_term_goal_labels"] = []
    attestation = captured.get("coverage_attestation") or {}
    return {
        "rules_version": PLAUSIBILITY_RULES_VERSION,
        "thresholds": dict(THRESHOLDS),
        "as_of_date": captured.get("as_of_date"),
        "declared": asdict(captured["declared"]),
        "recorded": recorded,
        "coverage_attestation": {
            "status": attestation.get("status"),
            "attestation_id": attestation.get("attestation_id"),
            "attestation_hash": attestation.get("attestation_hash"),
            "policy_version": attestation.get("policy_version"),
        },
    }


def inputs_hash(inputs: dict | None) -> str | None:
    return _sha256(_canonical(inputs)) if inputs is not None else None


def _input_fingerprint(inputs: dict | None) -> str | None:
    """Hash der Eingaben OHNE Stichtag -- fuer den Aktualitaetsvergleich."""
    if inputs is None:
        return None
    return inputs_hash({k: v for k, v in inputs.items() if k != "as_of_date"})


def structured_result(result: dict) -> dict:
    """Betragstreues, freitextfreies Ergebnis (ohne Meldungstexte)."""
    return {
        "status": result.get("status"),
        "reason_code": result.get("reason_code"),
        "verification_code": result.get("verification_code"),
        "findings": [
            {
                "check": f.get("check"),
                "question_number": f.get("question_number"),
                "declared": f.get("declared"),
                "recorded": f.get("recorded"),
            }
            for f in result.get("findings") or []
        ],
        "not_evaluable": [
            {
                "check": r.get("check"),
                "question_number": r.get("question_number"),
                "reason": r.get("reason"),
            }
            for r in result.get("not_evaluable") or []
        ],
        "coverage": dict(result.get("coverage") or {}),
        "capacity_binding": result.get("capacity_binding"),
        "override_down": bool(result.get("override_down")),
        "coverage_attestation_required": bool(result.get("coverage_attestation_required")),
        "data_basis": dict(result.get("data_basis") or {}),
    }


def _recompute_from_inputs(inputs: dict) -> dict:
    """Wendet die aktuellen Regeln auf die gespeicherten Eingaben an."""
    from services.risk_capacity_plausibility import (
        DeclaredCapacity,
        RecordedFinancials,
        assess_plausibility,
    )

    recorded = dict(inputs["recorded"])
    recorded["near_term_goal_labels"] = tuple(recorded.get("near_term_goal_labels") or ())
    result = assess_plausibility(DeclaredCapacity(**inputs["declared"]), RecordedFinancials(**recorded))
    return structured_result(result)


def _rules_changed(inputs: dict | None, rules_version: str | None) -> bool:
    from services.risk_capacity_plausibility import PLAUSIBILITY_RULES_VERSION, THRESHOLDS

    if rules_version != PLAUSIBILITY_RULES_VERSION:
        return True
    if inputs is not None:
        stored = inputs.get("thresholds")
        if json.loads(_canonical(stored)) != json.loads(_canonical(dict(THRESHOLDS))):
            return True
    return False


# ---------------------------------------------------------------------------
# Persistieren
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def record_snapshot(
    db,
    mandate: Any,
    assessment: Any,
    result: dict | None,
    captured: dict | None,
    *,
    actor: Any,
    binding_context: str,
    binding_record_id: str,
    now: str | None = None,
):
    """Legt die Evidenz der angezeigten Bewertung an (``db.add``, kein Commit).

    ``result`` ist genau das Ergebnis, das Strategie/Profil anzeigen;
    ``captured`` die von ``evaluate_mandate_safely(..., capture=...)``
    eingetragenen Eingaben. Ohne Ergebnis (Pruefung deaktiviert) wird nichts
    geschrieben. Das Ergebnis erhaelt einen Verweis
    ``evaluation_snapshot`` (ID, Hash, Kontext) -- keine Betraege.
    """
    if not isinstance(result, dict):
        return None
    if binding_context not in BINDING_CONTEXTS:
        raise ValueError(f"Unbekannter Bindungskontext: {binding_context!r}")
    from database import new_uuid
    from models.profiling import RiskCapacityPlausibilityEvaluation
    from services.risk_capacity_plausibility import PLAUSIBILITY_RULES_VERSION

    now = now or _now()
    inputs = inputs_payload(captured)
    inputs_json = _canonical(inputs) if inputs is not None else None
    as_of = (inputs or {}).get("as_of_date") or now[:10]
    row = RiskCapacityPlausibilityEvaluation(
        id=new_uuid(),
        schema_version=SCHEMA_VERSION,
        tenant_id=getattr(mandate, "tenant_id", None),
        mandate_id=mandate.id,
        client_id=getattr(mandate, "client_id", None),
        assessment_id=getattr(assessment, "id", None) if assessment is not None else None,
        binding_context=binding_context,
        binding_record_id=str(binding_record_id),
        as_of_date=as_of,
        rules_version=str(result.get("version") or PLAUSIBILITY_RULES_VERSION),
        status=str(result.get("status") or ""),
        inputs_json=inputs_json,
        inputs_hash=inputs_hash(inputs),
        result_json=_canonical(structured_result(result)),
        evaluation_hash=result.get("evaluation_hash"),
        actor_id=actor.id,
        evaluated_at=now,
        created_at=now,
    )
    row.snapshot_hash = compute_snapshot_hash(row)
    db.add(row)
    result["evaluation_snapshot"] = {
        "evaluation_id": row.id,
        "schema_version": SCHEMA_VERSION,
        "binding_context": binding_context,
        "snapshot_hash": row.snapshot_hash,
    }
    return row


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def verify_integrity(row: Any, mandate: Any) -> str:
    """Integritaet einer Zeile: Schema, Hash, Mandantenbindung, Regel-Replay."""
    if _value(row, "schema_version") != SCHEMA_VERSION:
        return INTEGRITY_UNKNOWN_SCHEMA
    stored = _value(row, "snapshot_hash")
    if not stored or stored != compute_snapshot_hash(row):
        return INTEGRITY_HASH_MISMATCH
    if (
        _value(row, "mandate_id") != getattr(mandate, "id", None)
        or _value(row, "client_id") != getattr(mandate, "client_id", None)
        or _value(row, "tenant_id") != getattr(mandate, "tenant_id", None)
    ):
        return INTEGRITY_BINDING_MISMATCH
    raw_inputs = _value(row, "inputs_json")
    if raw_inputs is None:
        return INTEGRITY_NOT_REPLAYABLE
    try:
        inputs = json.loads(raw_inputs)
        stored_result = json.loads(_value(row, "result_json"))
    except (TypeError, ValueError):
        return INTEGRITY_HASH_MISMATCH
    if inputs_hash(inputs) != _value(row, "inputs_hash"):
        return INTEGRITY_HASH_MISMATCH
    if _rules_changed(inputs, _value(row, "rules_version")):
        return INTEGRITY_RULES_CHANGED
    try:
        replayed = _recompute_from_inputs(inputs)
    except (TypeError, ValueError, KeyError):
        return INTEGRITY_RESULT_MISMATCH
    if json.loads(_canonical(replayed)) != stored_result:
        return INTEGRITY_RESULT_MISMATCH
    if stored_result.get("status") != _value(row, "status"):
        return INTEGRITY_RESULT_MISMATCH
    return INTEGRITY_VERIFIED


def live_evaluation(db, mandate, assessment, *, today=None, result: dict | None = None,
                    captured: dict | None = None) -> dict:
    """Aktuelle Bewertung fuer den Aktualitaetsvergleich.

    ``assessment`` = das aktuelle Risikoprofil (vom Aufrufer eindeutig
    aufgeloest). Hat der Aufrufer die Live-Bewertung schon gerechnet, gibt
    er ``result``/``captured`` mit -- keine zweite Auswertung.
    """
    from services.risk_capacity_plausibility import evaluate_mandate_safely

    if result is None:
        captured = {}
        result = evaluate_mandate_safely(db, mandate, assessment, today=today, capture=captured)
    return {
        "assessment_id": getattr(assessment, "id", None) if assessment is not None else None,
        "result": result,
        "inputs": inputs_payload(captured),
    }


def replay_snapshot(row: Any, mandate: Any, live: dict) -> dict:
    """Integritaet + Aktualitaet einer Zeile, betragsfrei."""
    integrity = verify_integrity(row, mandate)
    reasons: list[str] = []
    if integrity not in (INTEGRITY_VERIFIED, INTEGRITY_NOT_REPLAYABLE):
        reasons.append(STALE_RULES_CHANGED if integrity == INTEGRITY_RULES_CHANGED else STALE_INTEGRITY)
    if live.get("assessment_id") is None:
        reasons.append(STALE_NO_CURRENT_ASSESSMENT)
    elif live.get("assessment_id") != _value(row, "assessment_id"):
        reasons.append(STALE_ASSESSMENT_CHANGED)
    stored_inputs = None
    if integrity in (INTEGRITY_VERIFIED, INTEGRITY_RULES_CHANGED):
        stored_inputs = json.loads(_value(row, "inputs_json"))
    live_inputs = live.get("inputs")
    if stored_inputs is None or live_inputs is None:
        reasons.append(STALE_INPUTS_UNAVAILABLE)
    elif _input_fingerprint(stored_inputs) != _input_fingerprint(live_inputs):
        reasons.append(
            STALE_RULES_CHANGED
            if stored_inputs.get("rules_version") != live_inputs.get("rules_version")
            or stored_inputs.get("thresholds") != live_inputs.get("thresholds")
            else STALE_INPUTS_CHANGED
        )
    reasons = list(dict.fromkeys(reasons))
    needs_recheck = bool(reasons)
    try:
        stored_result = json.loads(_value(row, "result_json") or "{}")
    except (TypeError, ValueError):
        stored_result = {}
    return {
        "evaluation_id": _value(row, "id"),
        "schema_version": _value(row, "schema_version"),
        "binding_context": _value(row, "binding_context"),
        "binding_record_id": _value(row, "binding_record_id"),
        "risk_assessment_id": _value(row, "assessment_id"),
        "as_of_date": _value(row, "as_of_date"),
        "evaluated_at": _value(row, "evaluated_at"),
        "rules_version": _value(row, "rules_version"),
        "status": _value(row, "status"),
        "reason_code": stored_result.get("reason_code"),
        "verification_code": stored_result.get("verification_code"),
        "checks": [f.get("check") for f in stored_result.get("findings") or []],
        "not_evaluable": [r.get("check") for r in stored_result.get("not_evaluable") or []],
        "inputs_hash": _value(row, "inputs_hash"),
        "snapshot_hash": _value(row, "snapshot_hash"),
        "integrity": integrity,
        "currency": CURRENCY_STALE if needs_recheck else CURRENCY_CURRENT,
        "stale_reasons": reasons,
        "needs_recheck": needs_recheck,
        "recheck_code": RECHECK_CODE if needs_recheck else None,
        "recheck_label": RECHECK_LABEL if needs_recheck else None,
        "recheck_text": (
            RECHECK_TEXT + " " + " ".join(_STALE_TEXTS[r] for r in reasons)
            if needs_recheck else None
        ),
    }


def list_snapshots(db, mandate, *, limit: int = 20) -> list:
    """Zeilen des Mandats (neueste zuerst), strikt mandantengetrennt."""
    from models.profiling import RiskCapacityPlausibilityEvaluation as Row

    query = db.query(Row).filter(Row.mandate_id == mandate.id)
    tenant_id = getattr(mandate, "tenant_id", None)
    query = query.filter(Row.tenant_id.is_(None) if tenant_id is None else Row.tenant_id == tenant_id)
    return query.order_by(Row.evaluated_at.desc(), Row.created_at.desc()).limit(limit).all()


def bound_evaluation_status(db, mandate, live: dict) -> dict | None:
    """Status der zuletzt gebundenen Bewertung (``None``: noch keine)."""
    rows = list_snapshots(db, mandate, limit=1)
    if not rows:
        return None
    return replay_snapshot(rows[0], mandate, live)


__all__ = [
    "SCHEMA_VERSION",
    "BINDING_CONTEXTS",
    "CONTEXT_ALLOCATION_GENERATED",
    "CONTEXT_RISK_ASSESSMENT_SAVED",
    "RECHECK_CODE",
    "RECHECK_LABEL",
    "bound_evaluation_status",
    "compute_snapshot_hash",
    "inputs_payload",
    "list_snapshots",
    "live_evaluation",
    "record_snapshot",
    "replay_snapshot",
    "structured_result",
    "verify_integrity",
]
