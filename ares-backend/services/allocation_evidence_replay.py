"""Persistierte Optimizer-Evidenz: erzeugen, binden und beim Reload abspielen.

OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001
---------------------------------------
Der eingefrorene Objective-Vertrag eines Laufs verliess den Prozess nicht:
``as_evidence()`` erreichte weder die OptimizerRun-Zeile noch die Modellbasis
der Allokation. Jetzt traegt die Run-Zeile Version, Hash und Nachweisblock,
die Modellbasis denselben Block (und damit der allocation_context_hash). Beim
Reload wird der Block versionsgenau nachgerechnet
(``objective_contract.verify_objective_contract_evidence``) und gegen die
verknuepfte Run-Zeile gebunden.

Statuswerte: ``verified``, ``unverifiable`` (Bestand ohne Nachweis),
``unknown_version``, ``corrupt``, ``not_applicable`` (kein Solver-Lauf).

OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001
------------------------------------------
Die verlustfreien Goal-Driver kamen nur im unmittelbaren Generate-Response an;
der Reload las den persistierten Container nicht und lieferte still ``[]``.
Jetzt haelt ``target_allocations.goal_driver_evidence_json`` einen
versionierten Snapshot (``optimizer-goal-driver-evidence-v1``): kanonische
Driver (Decimal/Hex als atomares, gegengeprueftes Paar), Rangsemantik, Modus
und der Objective-Vertrag des Laufs, mit SHA-256 ueber alles. Generate und
Reload liefern ihn ueber dieselbe Funktion; beim Reload werden Hash, Schema,
Rangfolge und die Bindung an den Vertrag der Modellbasis geprueft.

Schema v2 (2026-10-28, Rest von OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001):
Der Zielfunktionswert des Laufs war nur als ``*_milli``-Integer persistiert
(``_objective_to_milli``, ``int(round(value * 1000))``): 0.0006 und 0.0014
landen beide auf 1, 0.0001 und 0.0002 auf 0. Der v2-Snapshot traegt den Wert
zusaetzlich verlustfrei (``solver_objective_value``: kuerzester
round-trip-Dezimalstring + binary64-Hex, kanonisch und gegengeprueft; nicht
endlich -> ``null``, nie 0). Der Replay vergleicht exakt und bindet die
Legacy-Spalten (``target_allocations.optimization_objective_value_milli``,
``optimizer_runs.objective_value_milli``) an den verlustfreien Wert. Die
milli-Skala selbst bleibt unveraendert (bestehende Konsumenten). v1-Snapshots
verifizieren weiter, ohne verlustfreien Wert (``solver_objective_value: null``).

Zustaende: ``verified``; ``unverifiable`` (Bestand: Driver nur im alten
Shadow-Container, ungebunden); ``unavailable`` (Solver lief laut Basis, aber
kein Snapshot); ``not_applicable`` (kein Solver-Lauf); ``corrupt``
(Hash, Schema, Rang oder Vertragsbindung verletzt) -- dann keine Driver.

Reine Evidenz: nichts hier aendert eine Rechnung oder einen Optimizer-Entscheid.
"""
from __future__ import annotations

import hashlib
import json
import math

from services.optimizer.objective_contract import (
    CONTRACT_EVIDENCE_CORRUPT,
    CONTRACT_EVIDENCE_UNVERIFIABLE,
    CONTRACT_EVIDENCE_VERIFIED,
    verify_objective_contract_evidence,
)

EVIDENCE_NOT_APPLICABLE = "not_applicable"


def run_objective_contract_evidence(optimizer_result) -> dict | None:
    """Nachweisblock des eingefrorenen Lauf-Vertrags oder None (kein Context)."""
    context = getattr(optimizer_result, "context", None)
    contract = getattr(context, "objective_contract", None)
    as_evidence = getattr(contract, "as_evidence", None)
    return as_evidence() if callable(as_evidence) else None


def _basis_contract_evidence(model_basis: dict | None):
    """(Nachweisblock, Quelle) aus einer persistierten Modellbasis.

    Seit 2026-10-24 liegt der Block direkt in ``optimization``; aeltere
    stochastische Basen tragen ihn nur im Resampling-Audit (V2). Beide sind
    echte, mitgehashte Persistenz und werden als das verifiziert, was sie sind.
    """
    optimization = (model_basis or {}).get("optimization")
    if not isinstance(optimization, dict):
        return None, None
    if "objective_contract" in optimization:
        return optimization.get("objective_contract"), "model_basis"
    resampling = optimization.get("resampling")
    if isinstance(resampling, dict) and resampling.get("objective_contract") is not None:
        return resampling.get("objective_contract"), "model_basis_resampling"
    return None, None


def objective_contract_replay(model_basis: dict | None, optimizer_run=None) -> dict:
    """Verifizierter Vertragsstatus einer Allokation (Reload und Generate)."""
    evidence, source = _basis_contract_evidence(model_basis)
    optimization = (model_basis or {}).get("optimization") or {}
    if evidence is None:
        if source == "model_basis":
            # Moderne Basis, aber kein Solver-Context: es gibt keinen Vertrag.
            return {
                "status": EVIDENCE_NOT_APPLICABLE,
                "objective_contract_version": None,
                "objective_contract_hash": None,
                "schema": None,
                "source": source,
                "reason": "kein Solver-Lauf",
            }
        result = verify_objective_contract_evidence(None)
        result["source"] = None
        return result
    result = verify_objective_contract_evidence(evidence)
    result["source"] = source
    if result["status"] != CONTRACT_EVIDENCE_VERIFIED:
        return result
    flat_hash = optimization.get("objective_contract_hash", result["objective_contract_hash"])
    flat_version = optimization.get(
        "objective_contract_version", result["objective_contract_version"],
    )
    if (flat_hash, flat_version) != (
        result["objective_contract_hash"], result["objective_contract_version"],
    ):
        return {**result, "status": CONTRACT_EVIDENCE_CORRUPT,
                "reason": "Anker der Modellbasis weicht vom Nachweisblock ab"}
    run_hash = getattr(optimizer_run, "objective_contract_hash", None)
    if optimizer_run is not None and run_hash is not None:
        try:
            run_evidence = json.loads(getattr(optimizer_run, "objective_contract_json", None) or "null")
        except (TypeError, ValueError):
            run_evidence = "corrupt"
        run_check = verify_objective_contract_evidence(run_evidence)
        if (
            run_check["status"] != CONTRACT_EVIDENCE_VERIFIED
            or run_check["objective_contract_hash"] != run_hash
            or run_hash != result["objective_contract_hash"]
            or getattr(optimizer_run, "objective_contract_version", None)
            != result["objective_contract_version"]
        ):
            return {**result, "status": CONTRACT_EVIDENCE_CORRUPT,
                    "reason": "OptimizerRun und Modellbasis tragen verschiedene Vertraege"}
        result["optimizer_run_bound"] = True
    return result


GOAL_DRIVER_EVIDENCE_VERSION_V1 = "optimizer-goal-driver-evidence-v1"
GOAL_DRIVER_EVIDENCE_VERSION = "optimizer-goal-driver-evidence-v2"
GOAL_DRIVER_RANKING_SEMANTICS = "raw_weighted_loss_desc_v1"
EVIDENCE_UNAVAILABLE = "unavailable"
_SOLVER_MODES = ("shadow_stochastic", "stochastic")
_ENVELOPE_KEYS_V1 = frozenset({
    "schema_version", "optimizer_mode", "ranking_semantics",
    "objective_contract_version", "objective_contract_hash", "drivers",
})
_ENVELOPE_KEYS = {
    GOAL_DRIVER_EVIDENCE_VERSION_V1: _ENVELOPE_KEYS_V1,
    GOAL_DRIVER_EVIDENCE_VERSION: _ENVELOPE_KEYS_V1 | {"solver_objective_value"},
}


def lossless_objective_value(value) -> dict | None:
    """Verlustfreier Zielfunktionswert oder None (fehlt / nicht endlich)."""
    from services.portfolio_engine_optimizer_integration import _lossless_objective_evidence

    decimal_text, hex_text = _lossless_objective_evidence(value)
    if decimal_text is None:
        return None
    return {"decimal": decimal_text, "binary64_hex": hex_text}


def _checked_objective_value(block) -> dict | None:
    """Kanonisches, gegengeprueftes Decimal/Hex-Paar (sonst ValueError)."""
    if block is None:
        return None
    if not isinstance(block, dict) or set(block) != {"decimal", "binary64_hex"}:
        raise ValueError("Zielfunktionswert hat eine unbekannte Form")
    decimal_text, hex_text = block["decimal"], block["binary64_hex"]
    if not isinstance(decimal_text, str) or not isinstance(hex_text, str):
        raise ValueError("Zielfunktionswert ist kein Decimal/Hex-Paar")
    try:
        value = float(decimal_text)
        hex_value = float.fromhex(hex_text)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Zielfunktionswert nicht lesbar") from exc
    if (
        not math.isfinite(value)
        or hex_value != value
        or repr(value) != decimal_text
        or value.hex() != hex_text
    ):
        raise ValueError("Zielfunktionswert: Decimal und Hex nicht bitgleich/kanonisch")
    return {"decimal": decimal_text, "binary64_hex": hex_text}


def _canonical_json(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validated_drivers(drivers) -> list[dict]:
    """Driver durch das API-Schema (inkl. Decimal/Hex-Paarpruefung)."""
    from pydantic import ValidationError

    from schemas.allocation import OptimizerGoalDriverResponse

    if not isinstance(drivers, list) or not all(isinstance(row, dict) for row in drivers):
        raise ValueError("goal_drivers ist keine Liste von Objekten")
    try:
        return [OptimizerGoalDriverResponse(**row).model_dump() for row in drivers]
    except ValidationError as exc:
        raise ValueError(f"Driver verletzt das Schema: {exc.errors()[0].get('msg')}") from exc


def _check_ranking(drivers: list[dict]) -> None:
    ranks = [int(row["rank"]) for row in drivers]
    if ranks != list(range(1, len(drivers) + 1)):
        raise ValueError("Raenge nicht lueckenlos 1..n in Listenreihenfolge")
    values = [
        float(row["weighted_objective_contribution_decimal"])
        for row in drivers
        if row.get("weighted_objective_contribution_decimal") is not None
    ]
    if any(later > earlier for earlier, later in zip(values, values[1:])):
        raise ValueError("Rangfolge widerspricht den verlustfreien Rohwerten")


def build_goal_driver_evidence_json(
    drivers, *, optimizer_mode: str, optimizer_result, model_basis: dict | None,
) -> str | None:
    """Snapshot fuer ``target_allocations.goal_driver_evidence_json``.

    Nur wenn ein Solver lief (dieselbe Bedingung wie die Driver-Berechnung);
    sonst None. Gebunden an den Vertrag, den die Modellbasis ausweist.
    """
    if optimizer_mode not in _SOLVER_MODES or optimizer_result is None:
        return None
    optimization = (model_basis or {}).get("optimization") or {}
    canonical = _validated_drivers(list(drivers or []))
    _check_ranking(canonical)
    envelope = {
        "schema_version": GOAL_DRIVER_EVIDENCE_VERSION,
        "optimizer_mode": str(optimizer_mode),
        "ranking_semantics": GOAL_DRIVER_RANKING_SEMANTICS,
        "objective_contract_version": optimization.get("objective_contract_version"),
        "objective_contract_hash": optimization.get("objective_contract_hash"),
        "drivers": canonical,
        "solver_objective_value": lossless_objective_value(
            getattr(optimizer_result, "objective_value", None)
        ),
    }
    envelope["evidence_hash"] = hashlib.sha256(
        _canonical_json(envelope).encode("utf-8")
    ).hexdigest()
    return _canonical_json(envelope)


def _driver_state(status: str, *, drivers=None, reason=None, envelope=None, source=None) -> dict:
    envelope = envelope if isinstance(envelope, dict) else {}
    drivers = list(drivers or [])
    return {
        "drivers": drivers,
        "evidence": {
            "status": status,
            "schema_version": envelope.get("schema_version"),
            "evidence_hash": envelope.get("evidence_hash"),
            "objective_contract_hash": envelope.get("objective_contract_hash"),
            "ranking_semantics": envelope.get("ranking_semantics"),
            "solver_objective_value": envelope.get("solver_objective_value"),
            "driver_count": len(drivers),
            "source": source,
            "reason": reason,
        },
    }


def _verified_envelope(evidence_json: str, optimization: dict) -> tuple[dict, list[dict]]:
    envelope = json.loads(evidence_json)
    if not isinstance(envelope, dict):
        raise ValueError("Snapshot ist kein Objekt")
    expected_keys = _ENVELOPE_KEYS.get(envelope.get("schema_version"))
    if expected_keys is None:
        raise ValueError("unbekannte Snapshot-Version")
    body = {key: value for key, value in envelope.items() if key != "evidence_hash"}
    if set(body) != expected_keys:
        raise ValueError("Feldsatz des Snapshots")
    recomputed = hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()
    if recomputed != envelope.get("evidence_hash"):
        raise ValueError("Snapshot-Hash weicht ab")
    if envelope["ranking_semantics"] != GOAL_DRIVER_RANKING_SEMANTICS:
        raise ValueError("unbekannte Rangsemantik")
    drivers = _validated_drivers(envelope["drivers"])
    if drivers != envelope["drivers"]:
        raise ValueError("Driver nicht kanonisch")
    _checked_objective_value(envelope.get("solver_objective_value"))
    _check_ranking(drivers)
    if (
        envelope["objective_contract_hash"] != optimization.get("objective_contract_hash")
        or envelope["objective_contract_version"]
        != optimization.get("objective_contract_version")
    ):
        raise ValueError("Snapshot und Modellbasis tragen verschiedene Vertraege")
    return envelope, drivers


def replay_goal_drivers(
    evidence_json: str | None,
    *,
    legacy_shadow_json: str | None,
    model_basis: dict | None,
) -> dict:
    """Driver einer gespeicherten Allokation samt typisiertem Evidenzzustand."""
    optimization = (model_basis or {}).get("optimization") or {}
    if evidence_json is not None:
        try:
            envelope, drivers = _verified_envelope(evidence_json, optimization)
        except (TypeError, ValueError, KeyError) as exc:
            return _driver_state(
                CONTRACT_EVIDENCE_CORRUPT, source="goal_driver_evidence_json",
                reason=str(exc)[:200],
            )
        return _driver_state(
            CONTRACT_EVIDENCE_VERIFIED, drivers=drivers, envelope=envelope,
            source="goal_driver_evidence_json",
        )
    legacy = None
    if legacy_shadow_json:
        try:
            legacy = json.loads(legacy_shadow_json).get("goal_drivers")
        except (TypeError, ValueError, AttributeError):
            return _driver_state(
                CONTRACT_EVIDENCE_CORRUPT, source="shadow_optimization_json",
                reason="Shadow-Container nicht lesbar",
            )
    if legacy:
        try:
            drivers = _validated_drivers(legacy)
            _check_ranking(drivers)
        except (TypeError, ValueError, KeyError) as exc:
            return _driver_state(
                CONTRACT_EVIDENCE_CORRUPT, source="shadow_optimization_json",
                reason=str(exc)[:200],
            )
        return _driver_state(
            CONTRACT_EVIDENCE_UNVERIFIABLE, drivers=drivers, source="shadow_optimization_json",
            reason="Bestand: Driver ohne Snapshot-Hash und Vertragsbindung",
        )
    if str(optimization.get("basis_id") or "").startswith("stochastic"):
        return _driver_state(EVIDENCE_UNAVAILABLE, reason="Solver lief, Driver nicht persistiert")
    return _driver_state(EVIDENCE_NOT_APPLICABLE, reason="kein Solver-Lauf")


def _bind_legacy_objective_milli(replay: dict, allocation, run) -> dict:
    """Legacy-milli-Spalten muessen exakt aus dem verlustfreien Wert folgen.

    Nur fuer verifizierte v2-Snapshots mit Wert. Eine gesetzte milli-Spalte
    (Allokation bzw. verknuepfter Lauf), die nicht
    ``_objective_to_milli(<verlustfreier Wert>)`` ist, macht den Nachweis
    ``corrupt``. Leere Spalten (Shadow-Modus, kein verknuepfter Lauf) sind
    keine Aussage und werden nicht geprueft.
    """
    from services.portfolio_engine_optimizer_integration import _objective_to_milli

    evidence = replay["evidence"]
    block = evidence.get("solver_objective_value")
    if evidence.get("status") != CONTRACT_EVIDENCE_VERIFIED or block is None:
        return replay
    expected = _objective_to_milli(float(block["decimal"]))
    for source, holder, column in (
        ("target_allocations", allocation, "optimization_objective_value_milli"),
        ("optimizer_runs", run, "objective_value_milli"),
    ):
        stored = getattr(holder, column, None) if holder is not None else None
        if stored is not None and int(stored) != expected:
            return _driver_state(
                CONTRACT_EVIDENCE_CORRUPT, source="goal_driver_evidence_json",
                reason=f"{source}.{column} widerspricht dem verlustfreien Zielfunktionswert",
            )
    return replay


def allocation_evidence_payload(db, allocation, model_basis: dict | None, *, legacy_shadow_json=None) -> dict:
    """Ein Block fuer Generate und Reload: Vertrag + Driver aus der Persistenz."""
    from models.allocation import OptimizerRun

    run = None
    run_id = getattr(allocation, "optimization_run_id", None)
    if db is not None and run_id:
        run = db.query(OptimizerRun).filter(OptimizerRun.id == run_id).first()
    replay = replay_goal_drivers(
        getattr(allocation, "goal_driver_evidence_json", None),
        legacy_shadow_json=legacy_shadow_json,
        model_basis=model_basis,
    )
    replay = _bind_legacy_objective_milli(replay, allocation, run)
    return {
        "objective_contract_evidence": objective_contract_replay(model_basis, run),
        "optimizer_goal_drivers": replay["drivers"],
        "optimizer_goal_driver_evidence": replay["evidence"],
    }


__all__ = [
    "CONTRACT_EVIDENCE_UNVERIFIABLE",
    "EVIDENCE_NOT_APPLICABLE",
    "EVIDENCE_UNAVAILABLE",
    "GOAL_DRIVER_EVIDENCE_VERSION",
    "GOAL_DRIVER_EVIDENCE_VERSION_V1",
    "lossless_objective_value",
    "allocation_evidence_payload",
    "build_goal_driver_evidence_json",
    "replay_goal_drivers",
    "objective_contract_replay",
    "run_objective_contract_evidence",
]
