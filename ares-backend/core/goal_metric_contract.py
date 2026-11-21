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
# P5b / N-925-03: Rundung der Wahrscheinlichkeiten (float -> ganze ppm,
# Python ``round`` = halb-gerade) -- Anzeige und Hash lesen dieselben Zahlen.
PPM_ROUNDING_POLICY = "ares-ppm-round-half-even/1"

# Statuskette (= services/optimizer/objective.py ``certify_success_indicator``
# mit ``certification.ESS_ABSOLUTE_FLOOR``/``ESS_FRACTION_FLOOR`` und
# ``objective.TAU_UNREACHABLE``; Gleichheit per Test gepinnt), hier auf den
# kanonischen Ganzzahlen des Payloads.
ESS_ABSOLUTE_FLOOR_X100 = 3_000
ESS_FRACTION_FLOOR_PPM = 100_000
TAU_UNREACHABLE_PPM = 500_000


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


# N-925-08: Revision = Fingerabdruck der fachlichen Zielfelder (nicht der
# Zeitstempel) -- eine reine Beruehrung (updated_at) aendert sie nicht.
GOAL_REVISION_FIELDS = (
    "id", "goal_family", "goal_type", "rank", "weight_bps", "goal_scope", "value_mode",
    "target_amount_rappen", "target_wealth_rappen", "target_return_bps", "success_probability_min_x100",
    "start_date", "horizon_years", "target_date", "is_ongoing", "frequency", "hardness",
    "probability_pct", "is_active", "is_included",
)


def goal_revision(goal: Any) -> str:
    material = {
        "id": getattr(goal, "id", None),
        "goal_family": getattr(goal, "goal_family", None),
        "goal_type": getattr(goal, "goal_type", None),
        "rank": getattr(goal, "rank", None),
        "weight_bps": getattr(goal, "weight_bps", None),
        "goal_scope": getattr(goal, "goal_scope", None),
        "value_mode": getattr(goal, "value_mode", None),
        "target_amount_rappen": getattr(goal, "target_amount_rappen", None),
        "target_wealth_rappen": getattr(goal, "target_wealth_rappen", None),
        "target_return_bps": getattr(goal, "target_return_bps", None),
        "success_probability_min_x100": getattr(goal, "success_probability_min_x100", None),
        "start_date": getattr(goal, "start_date", None),
        "horizon_years": getattr(goal, "horizon_years", None),
        "target_date": getattr(goal, "target_date", None),
        "is_ongoing": getattr(goal, "is_ongoing", None),
        "frequency": getattr(goal, "frequency", None),
        "hardness": getattr(goal, "hardness", None),
        "probability_pct": getattr(goal, "probability_pct", None),
        "is_active": getattr(goal, "is_active", None),
        "is_included": getattr(goal, "is_included", None),
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return "goal-rev/1:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def goal_status_from_metric(*, probability_ppm: int, lower_bound_ppm: int, tau_ppm: int,
                            ess_x100: int, n_paths: int, outside_horizon: bool) -> str:
    """N-925-03: Status ausschliesslich aus Untergrenze, tau und Stichprobe
    (nie aus der gespeicherten Zeile uebernommen)."""
    if outside_horizon:
        return "ausserhalb_horizont"
    ess_sufficient = ess_x100 >= ESS_ABSOLUTE_FLOOR_X100 and not (
        n_paths > 0 and ess_x100 * 10_000 < ESS_FRACTION_FLOOR_PPM * n_paths)
    if ess_sufficient and lower_bound_ppm >= tau_ppm:
        return "erreichbar"
    if not ess_sufficient and probability_ppm >= TAU_UNREACHABLE_PPM:
        return "unreliable"
    if probability_ppm >= TAU_UNREACHABLE_PPM:
        return "knapp"
    return "nicht_erreichbar"


def _validation_anchor(target_allocation: Any) -> dict[str, Any] | None:
    """Seed, Wuerfel-Hash und Pfadzahl der unabhaengigen Validierung (der mit
    der Soll-Allokation verknuepfte Optimierer-Lauf); unvollstaendig -> None."""
    run = getattr(target_allocation, "optimization_run", None)
    seed = getattr(run, "validation_seed", None)
    cube_hash = str(getattr(run, "validation_cube_hash", None) or "")
    n_paths = getattr(run, "validation_n_paths", None)
    if not isinstance(seed, int) or isinstance(seed, bool) or len(cube_hash) != 64:
        return None
    if not isinstance(n_paths, int) or isinstance(n_paths, bool) or n_paths <= 0:
        return None
    return {"seed": seed, "cube_hash": cube_hash, "n_paths": n_paths}


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
             and int(getattr(g, "is_included", 1) or 0) == 1 and getattr(g, "deleted_at", None) is None]
    currency = str(getattr(mandate, "base_currency", None) or "").strip().upper()
    if not currency:  # N-925-08: kein stiller CHF-Default
        raise GoalMetricUncertified("Die Referenzwährung des Mandats fehlt; die Zielkennzahl wird nicht gebildet.")
    entries: list[dict[str, Any]] = []
    uncertified: list[str] = []
    anchor = _validation_anchor(target_allocation) if any(str(g.id) in by_goal for g in goals) else None
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
        seed = row.get("validation_seed")
        # N-925-03: Seed ist Pflicht und muss der Validierung des Laufs entsprechen.
        seed_ok = isinstance(seed, int) and not isinstance(seed, bool) and anchor is not None \
            and seed == anchor["seed"]
        if probability is None or lower is None or tau is None or ess_x100 is None or not seed_ok:
            uncertified.append(str(getattr(goal, "label", "") or goal.id))
            continue
        outside = bool(row.get("outside_simulation_horizon"))
        entries.append({
            "goal_id": str(goal.id),
            "goal_revision": goal_revision(goal),
            "rank": int(getattr(goal, "rank", 0) or 0),
            "hardness": str(getattr(goal, "hardness", "") or ""),
            "target_amount_minor": int(getattr(goal, "target_amount_rappen", 0) or 0)
            or int(getattr(goal, "target_wealth_rappen", 0) or 0),
            "currency": currency,
            "target_date": str(getattr(goal, "target_date", "") or ""),
            "metric_id": GOAL_METRIC_ID,
            "validation_seed": int(seed),
            "effective_sample_size_x100": ess_x100,
            "probability_ppm": probability,
            "lower_bound_ppm": lower,
            "tau_ppm": tau,
            "status": goal_status_from_metric(
                probability_ppm=probability, lower_bound_ppm=lower, tau_ppm=tau, ess_x100=ess_x100,
                n_paths=int(anchor["n_paths"]), outside_horizon=outside),
            "outside_horizon": outside,
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
        "rounding_policy": PPM_ROUNDING_POLICY,
        # N-925-03: Anker der unabhaengigen Validierungsstichprobe.
        "validation": dict(anchor) if entries and anchor is not None else None,
        "goals": entries,
    }
    payload["goal_metric_payload_hash"] = goal_metric_hash(payload)
    return payload


def canonical_goal_rows(rows: list[dict], target_allocation: Any) -> list[dict]:
    """N-925-03: Anzeige (App, PDF) aus dem kanonischen Payload -- je Zielzeile
    Wahrscheinlichkeit, Untergrenze, tau und Status aus dem Payload (gleiche
    Rundung, neu berechneter Status) samt Payload-Hash. Ist keine Kennzahl
    bildbar (unzertifiziert), bleiben die Zeilen unveraendert: ein solcher
    Entscheid ist nicht versiegelbar und jedes Dokument traegt den Entwurfs-
    hinweis."""
    mandate = getattr(target_allocation, "mandate", None)
    if mandate is None or not rows:
        return rows
    try:
        payload = build_goal_metric_payload(
            list(getattr(mandate, "goals", None) or []), mandate=mandate, target_allocation=target_allocation)
    except GoalMetricUncertified:
        return rows
    by_goal = {entry["goal_id"]: entry for entry in payload["goals"]}
    out: list[dict] = []
    for row in rows:
        entry = by_goal.get(str(row.get("goal_id") or "")) \
            if str(row.get("evaluation_scope") or "") == INDIVIDUAL_SCOPE else None
        if entry is None:
            out.append(row)
            continue
        out.append({
            **row,
            "probability": entry["probability_ppm"] / 1_000_000,
            "lower_confidence_bound": entry["lower_bound_ppm"] / 1_000_000,
            "tau": entry["tau_ppm"] / 1_000_000,
            "status": entry["status"],
            "metric_id": entry["metric_id"],
            "goal_metric_payload_hash": payload["goal_metric_payload_hash"],
        })
    return out


__all__ = [
    "canonical_goal_rows",
    "goal_status_from_metric",
    "GOAL_METRIC_CONTRACT_VERSION",
    "GOAL_METRIC_ID",
    "GOAL_STATUS_POLICY_VERSION",
    "GoalMetricUncertified",
    "build_goal_metric_payload",
    "goal_metric_hash",
]
