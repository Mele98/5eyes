"""CCX P5 / M-3: eine kanonische Zielkennzahl (Vertrag 2026-11-13 §8.2).

Stdlib-Blatt (architecture ratchets): keine Projekt-Importe; die Ziele liest
der Aufrufer.

Primaere Kennzahl je Ziel ist die auf der unabhaengigen Validierungs-
stichprobe gemessene Zielerreichungswahrscheinlichkeit des Optimierers samt
einseitiger Wilson-Untergrenze (``services/optimizer/certification.py``).
Der Status kommt ausschliesslich aus diesem Payload: ``erreichbar`` nur, wenn
die effektive Stichprobe genuegt UND die Untergrenze die Schwelle ``tau``
erreicht -- ein guter Punktschaetzer mit unzureichender Untergrenze ist nie
gruen. Median, pessimistischer Fehlbetrag und Faecherquantile bleiben
Sekundaerwerte und erzeugen keinen eigenen Status.

Quelle ist die integritaetsgebundene Zielanalyse der Soll-Allokation
(``target_allocations.goal_achievability_json``; ihr Hash steht im
``allocation_context_hash``). Hat ein Ziel mit Betrag keine Optimierer-
Evidenz, gilt ``CCX_GOAL_METRIC_UNCERTIFIED`` (kein Ersatz aus der
Haupt-Simulation).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

GOAL_METRIC_CONTRACT_VERSION = "ares-goal-metric/1"
GOAL_STATUS_POLICY_VERSION = "ares-goal-status/1"
GOAL_METRIC_ID = "validation_success_probability_wilson_lb"
GOAL_METRIC_HASH_DOMAIN = b"Ares\x00ares/goal-metric/1\x00"


class GoalMetricUncertified(ValueError):
    reason_code = "CCX_GOAL_METRIC_UNCERTIFIED"


def _ppm(value: Any) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(round(min(1.0, max(0.0, number)) * 1_000_000))


def _nfc(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _nfc(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_nfc(v) for v in value]
    return value


def goal_metric_hash(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "goal_metric_payload_hash"}
    canonical = json.dumps(_nfc(body), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(GOAL_METRIC_HASH_DOMAIN + canonical.encode("utf-8")).hexdigest()


# Zielindividuelle Evidenz (services/optimizer/goal_attribution.py:
# EVALUATION_SCOPE_PRIORITY_FUNDED); Plan-Solvenz und Altzeilen ohne Scope zaehlen nicht.
INDIVIDUAL_SCOPE = "priority_funded"


def _individual_rows(achievability: Any) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in achievability or []:
        if not isinstance(row, Mapping):
            continue
        scope = str(row.get("evaluation_scope") or "").strip()
        if scope == INDIVIDUAL_SCOPE and row.get("goal_id") and str(row["goal_id"]) not in out:
            out[str(row["goal_id"])] = dict(row)
    return out


def _requires_metric(goal: Any) -> bool:
    return bool(int(getattr(goal, "target_amount_rappen", 0) or 0) > 0
                or int(getattr(goal, "target_wealth_rappen", 0) or 0) > 0)


def build_goal_metric_payload(goals: Iterable[Any], *, mandate: Any, target_allocation: Any) -> dict[str, Any]:
    """Kanonischer Zielkennzahl-Payload einer Soll-Allokation (mit Hash).
    ``goals``: aktive Ziele des Mandats (Aufrufer liest sie aus der DB)."""
    raw = getattr(target_allocation, "goal_achievability_json", None)
    try:
        achievability = json.loads(raw) if raw else []
    except (TypeError, ValueError) as exc:
        raise GoalMetricUncertified("Die Zielanalyse der Soll-Allokation ist nicht lesbar.") from exc
    by_goal = _individual_rows(achievability)
    goals = [g for g in goals if int(getattr(g, "is_active", 1) or 0) == 1
             and int(getattr(g, "is_included", 1) or 0) == 1]
    currency = str(getattr(mandate, "base_currency", None) or "").strip().upper()
    if not currency:  # N-925-08: kein stiller CHF-Default
        raise GoalMetricUncertified("Die Referenzwährung des Mandats fehlt; die Zielkennzahl wird nicht gebildet.")
    entries: list[dict[str, Any]] = []
    uncertified: list[str] = []
    for goal in goals:
        row = by_goal.get(str(goal.id))
        if row is None:
            if _requires_metric(goal):
                uncertified.append(str(getattr(goal, "label", "") or goal.id))
            continue
        ess = row.get("effective_sample_size")
        try:
            ess_x100 = int(round(float(ess) * 100)) if ess is not None else None
        except (TypeError, ValueError):
            ess_x100 = None
        probability = _ppm(row.get("probability"))
        lower = _ppm(row.get("lower_confidence_bound"))
        tau = _ppm(row.get("tau"))
        if probability is None or lower is None or tau is None or ess_x100 is None:
            uncertified.append(str(getattr(goal, "label", "") or goal.id))
            continue
        seed = row.get("validation_seed")
        entries.append({
            "goal_id": str(goal.id),
            "goal_revision": str(getattr(goal, "updated_at", "") or ""),
            "rank": int(getattr(goal, "rank", 0) or 0),
            "hardness": str(getattr(goal, "hardness", "") or ""),
            "target_amount_minor": int(getattr(goal, "target_amount_rappen", 0) or 0)
            or int(getattr(goal, "target_wealth_rappen", 0) or 0),
            "currency": currency,
            "target_date": str(getattr(goal, "target_date", "") or ""),
            "metric_id": GOAL_METRIC_ID,
            "validation_seed": int(seed) if isinstance(seed, int) and not isinstance(seed, bool) else None,
            "effective_sample_size_x100": ess_x100,
            "probability_ppm": probability,
            "lower_bound_ppm": lower,
            "tau_ppm": tau,
            "status": str(row.get("status") or ""),
            "outside_horizon": bool(row.get("outside_simulation_horizon")),
        })
    if uncertified:
        raise GoalMetricUncertified(
            "Für folgende Ziele liegt keine zertifizierte Erfolgswahrscheinlichkeit vor: "
            + ", ".join(sorted(uncertified)) + ". Bitte die Strategie neu berechnen."
        )
    entries.sort(key=lambda item: (item["rank"], item["target_date"], item["goal_id"]))
    payload: dict[str, Any] = {
        "contract_version": GOAL_METRIC_CONTRACT_VERSION,
        "status_policy_version": GOAL_STATUS_POLICY_VERSION,
        "target_allocation_id": str(getattr(target_allocation, "id", "") or ""),
        # = services.goal_analysis_snapshot.goal_analysis_hash (sha256 der gespeicherten Bytes)
        "goal_analysis_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else None,
        "goals": entries,
    }
    payload["goal_metric_payload_hash"] = goal_metric_hash(payload)
    return payload


__all__ = [
    "GOAL_METRIC_CONTRACT_VERSION",
    "GOAL_METRIC_ID",
    "GOAL_STATUS_POLICY_VERSION",
    "GoalMetricUncertified",
    "build_goal_metric_payload",
    "goal_metric_hash",
]
