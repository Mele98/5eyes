from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from models.allocation import TargetAllocation


BUCKETS: tuple[str, ...] = ("equities", "bonds", "real_estate", "alternatives", "liquidity")


class ShadowComparisonNotFound(ValueError):
    pass


class ShadowComparisonMissing(ValueError):
    pass


def build_shadow_comparison_payload(db: Session, mandate_id: str) -> dict[str, Any]:
    """Serialize Methodology section 3 metrics for the current target allocation."""
    ta = (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.mandate_id == mandate_id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        )
        .order_by(TargetAllocation.version.desc(), TargetAllocation.created_at.desc())
        .first()
    )
    if ta is None:
        raise ShadowComparisonNotFound(f"Keine aktuelle TargetAllocation fuer Mandat {mandate_id}.")
    if not ta.shadow_optimization_json:
        raise ShadowComparisonMissing(
            f"Keine Shadow-Optimierung fuer Mandat {mandate_id} persistiert."
        )
    try:
        shadow = json.loads(ta.shadow_optimization_json)
    except (TypeError, ValueError) as exc:
        raise ShadowComparisonMissing("Shadow-Optimierung ist kein valides JSON.") from exc
    if not isinstance(shadow, dict):
        raise ShadowComparisonMissing("Shadow-Optimierung muss ein JSON-Objekt sein.")

    active = _dict_bps(shadow.get("active_allocation_bps") or _active_weights_from_ta(ta))
    stochastic = _dict_bps(shadow.get("allocation_bps") or shadow.get("shadow_weights_bps") or {})
    deltas = _dict_bps(shadow.get("weight_deltas_bps") or {
        bucket: stochastic[bucket] - active[bucket]
        for bucket in BUCKETS
    })
    total_drift_bps = max((abs(int(deltas[bucket])) for bucket in BUCKETS), default=0)

    active_risky = _int_or_none(shadow.get("active_risky_fraction_bps"))
    if active_risky is None:
        active_risky = _int_or_none(ta.risky_fraction_bps_at_generation)
    if active_risky is None:
        active_risky = _int_or_none(ta.risky_fraction_bps) or 0
    stochastic_risky = _int_or_none(shadow.get("risky_fraction_bps")) or 0
    risk_budget = _int_or_none(shadow.get("risk_budget_bps"))
    if risk_budget is None:
        risk_budget = _int_or_none(ta.risk_budget_bps_at_generation) or 0
    risky_drift_bps = abs(int(stochastic_risky) - int(active_risky))

    budget_compliance_hm = bool(int(active_risky) <= int(risk_budget)) if risk_budget else False
    budget_compliance_st = bool(shadow.get("budget_compliance"))
    if "budget_compliance" not in shadow and risk_budget:
        budget_compliance_st = bool(int(stochastic_risky) <= int(risk_budget))

    achievability = list(shadow.get("achievability") or [])
    goal_counts = _goal_counts(achievability)
    elapsed_ms = _int_or_none(shadow.get("elapsed_ms")) or 0
    optimization_status = str(shadow.get("optimization_status") or "")
    limiting_factor = str(shadow.get("limiting_factor") or "")

    verdict_detail = classify_shadow_verdict(
        total_drift_bps=total_drift_bps,
        risky_drift_bps=risky_drift_bps,
        budget_compliance_st=budget_compliance_st,
        n_hard_unreachable_st=goal_counts["n_hard_unreachable_st"],
        elapsed_ms=elapsed_ms,
        limiting_factor=limiting_factor,
        optimization_status=optimization_status,
    )
    verdict = str(verdict_detail.get("status") or "n/a").lower()
    verdict_notes = [str(note) for note in list(verdict_detail.get("reasons") or [])]

    return {
        "mandate_id": mandate_id,
        "target_allocation_id": ta.id,
        "active_engine": "house_matrix",
        "shadow_engine": str(shadow.get("engine") or "stochastic"),
        "active_allocation_bps": active,
        "shadow_allocation_bps": stochastic,
        "per_bucket_bps": {
            bucket: {
                "house_matrix": int(active[bucket]),
                "stochastic": int(stochastic[bucket]),
                "drift": abs(int(deltas[bucket])),
            }
            for bucket in BUCKETS
        },
        "weight_deltas_bps": deltas,
        "total_drift_bps": total_drift_bps,
        "risky_fraction_bps": {
            "house_matrix": int(active_risky),
            "stochastic": int(stochastic_risky),
            "drift": int(risky_drift_bps),
            "max_risky_fraction_bps": int(risk_budget),
        },
        "risky_drift_bps": int(risky_drift_bps),
        "risk_budget_bps": int(risk_budget),
        "budget_compliance": {
            "house_matrix": budget_compliance_hm,
            "stochastic": budget_compliance_st,
        },
        "goal_achievability": achievability,
        "goal_counts": goal_counts,
        "expected_volatility_bps": shadow.get("expected_volatility_bps"),
        "expected_terminal_p50_rappen": shadow.get("expected_terminal_p50_rappen"),
        "elapsed_ms": {
            "stochastic": int(elapsed_ms),
            "budget_ms": 8000,
        },
        "optimization_status": optimization_status,
        "limiting_factor": limiting_factor,
        "reasoning_complete": _reasoning_complete(shadow),
        "messages": list(shadow.get("messages") or []),
        "verdict": verdict,
        "verdict_notes": verdict_notes,
        "verdict_detail": verdict_detail,
        "raw_shadow_payload": shadow,
    }


def classify_shadow_verdict(
    *,
    total_drift_bps: int,
    risky_drift_bps: int,
    budget_compliance_st: bool,
    n_hard_unreachable_st: int,
    elapsed_ms: int,
    limiting_factor: str | None,
    optimization_status: str,
) -> dict[str, Any]:
    red_reasons: list[str] = []
    if int(total_drift_bps) > 2000:
        red_reasons.append("total_drift_bps > 2000")
    if int(risky_drift_bps) > 1000:
        red_reasons.append("risky_drift_bps > 1000")
    if not bool(budget_compliance_st):
        red_reasons.append("budget_compliance_ST == False")
    optimization_status_norm = str(optimization_status or "").strip()
    converged_statuses = {
        "converged",
        "converged_robustified",
        "converged_with_soft_tau",
    }
    if optimization_status_norm not in converged_statuses:
        red_reasons.append("optimization_status != converged")
    if int(n_hard_unreachable_st) > 0:
        red_reasons.append("n_hard_unreachable_st > 0")
    if int(elapsed_ms) > 15000:
        red_reasons.append("elapsed_ms > 15000")
    if red_reasons:
        return {"status": "RED", "reasons": red_reasons}

    yellow_reasons: list[str] = []
    if optimization_status_norm == "converged_robustified":
        yellow_reasons.append("optimization_status=converged_robustified")
    if optimization_status_norm == "converged_with_soft_tau":
        yellow_reasons.append("optimization_status=converged_with_soft_tau")
    if int(total_drift_bps) > 1000:
        yellow_reasons.append("1000 < total_drift_bps <= 2000")
    if int(risky_drift_bps) > 500:
        yellow_reasons.append("500 < risky_drift_bps <= 1000")
    if int(elapsed_ms) > 8000:
        yellow_reasons.append("8000 < elapsed_ms <= 15000")
    if not str(limiting_factor or "").strip():
        yellow_reasons.append("limiting_factor fehlt")
    if yellow_reasons:
        return {"status": "YELLOW", "reasons": yellow_reasons}

    return {"status": "GREEN", "reasons": ["Methodology-Schwellen erfuellt"]}


def _active_weights_from_ta(ta: TargetAllocation) -> dict[str, int]:
    return {
        "equities": int(ta.target_equities_bps or 0),
        "bonds": int(ta.target_bonds_bps or 0),
        "real_estate": int(ta.target_real_estate_bps or 0),
        "alternatives": int(ta.target_alternatives_bps or 0),
        "liquidity": int(ta.target_liquidity_bps or 0),
    }


def _dict_bps(raw: Any) -> dict[str, int]:
    source = raw if isinstance(raw, dict) else {}
    return {bucket: int(source.get(bucket, 0) or 0) for bucket in BUCKETS}


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _goal_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    achievable = 0
    tight = 0
    unreachable = 0
    hard_unreachable = 0
    for row in rows:
        status = str(row.get("status") or "")
        hardness = _hardness_key(row.get("hardness"))
        if status == "erreichbar":
            achievable += 1
        elif status == "knapp":
            tight += 1
        elif status == "nicht_erreichbar":
            unreachable += 1
            if hardness == "hart":
                hard_unreachable += 1
    return {
        "n_goals_achievable_st": achievable,
        "n_goals_tight_st": tight,
        "n_goals_unreachable_st": unreachable,
        "n_hard_unreachable_st": hard_unreachable,
    }


def _hardness_key(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("hart", "hard"):
        return "hart"
    if raw in ("primaer", "prim\u00e4r", "primary"):
        return "primaer"
    if raw in ("opportunistisch", "opportunistic"):
        return "opportunistisch"
    return raw


def _reasoning_complete(shadow: dict[str, Any]) -> bool:
    if not str(shadow.get("limiting_factor") or "").strip():
        return False
    if not isinstance(shadow.get("constraints"), list):
        return False
    achievability = shadow.get("achievability")
    if achievability is None:
        return False
    return isinstance(achievability, list)


# --- Stage 8 Foundation: Aggregation für Owner-Verifikation ---------------
# Methodology §4 Gesamt-Verdikt definiert den Default-Wechsel-Entscheid auf
# Basis von n GREEN/YELLOW/RED Mandaten. Diese Funktion fasst die einzelnen
# Per-Mandate-Verdicts zusammen, damit der Owner Stage 8 nicht händisch pro
# Mandat laufen lassen muss.

def aggregate_shadow_comparisons(
    db: Session,
    *,
    examples_per_verdict: int = 2,
    example_red_limit: int = 1,
) -> dict[str, Any]:
    """Aggregate shadow-comparison verdicts across all mandates with shadow data.

    Iteriert über alle aktuellen ``TargetAllocation``-Zeilen mit persistierter
    Shadow-Optimization, baut pro Mandat das Vergleichs-Payload via
    :func:`build_shadow_comparison_payload`, und liefert Methodology §4
    GREEN/YELLOW/RED Counts plus repräsentative Beispiele.

    Verwendet vom Admin-Endpoint ``/admin/system/shadow-comparison-aggregate``
    als Datenquelle für die Stage-8-Owner-Verifikation und das
    Compliance-Template ``docs/compliance/shadow-vergleich-template.md``.

    Parameter
    ---------
    examples_per_verdict
        Maximale Anzahl Beispiel-Mandate pro Verdict (GREEN/YELLOW). Default 2.
    example_red_limit
        Maximale Anzahl RED-Beispiele. Default 1 (RED ist Stop-Bedingung —
        eines reicht zur Diagnose, mehr macht den Report unleserlich).

    Returns
    -------
    dict mit Keys:
        ``counts``: ``{green, yellow, red, total}`` (int).
        ``percentages``: dieselben Keys als float (0-100).
        ``examples``: ``{green, yellow, red}`` als Listen kompakter Per-Mandat-
            Zusammenfassungen (mandate_id, target_allocation_id, total_drift_bps,
            risky_drift_bps, limiting_factor, verdict, verdict_notes).
        ``default_switch_ready``: bool — True nur wenn Methodology §4
            Gesamt-Verdikt erfüllt (≥ 2/3 realer Mandate GREEN, 0 RED).
        ``default_switch_reason``: str (mensch-lesbare Begründung).
        ``errors``: ``[{mandate_id, error}]`` für Mandate, deren Payload-Bau
            fehlschlug (kein Stop — der Aggregator liefert weiter, was geht).
    """
    counts = {"green": 0, "yellow": 0, "red": 0}
    examples: dict[str, list[dict[str, Any]]] = {"green": [], "yellow": [], "red": []}
    errors: list[dict[str, str]] = []

    rows = (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
            TargetAllocation.shadow_optimization_json.isnot(None),
        )
        .order_by(TargetAllocation.created_at.desc())
        .all()
    )

    for ta in rows:
        try:
            payload = build_shadow_comparison_payload(db, ta.mandate_id)
        except (ShadowComparisonNotFound, ShadowComparisonMissing) as exc:
            errors.append({"mandate_id": str(ta.mandate_id), "error": str(exc)})
            continue
        verdict = str(payload.get("verdict") or "").lower()
        if verdict not in counts:
            errors.append({
                "mandate_id": str(ta.mandate_id),
                "error": f"Unbekanntes verdict '{verdict}'",
            })
            continue
        counts[verdict] += 1
        limit = example_red_limit if verdict == "red" else examples_per_verdict
        if len(examples[verdict]) < limit:
            examples[verdict].append(_summarize_mandate_for_aggregate(payload))

    total = counts["green"] + counts["yellow"] + counts["red"]
    percentages = {
        key: (round(100.0 * value / total, 1) if total else 0.0)
        for key, value in counts.items()
    }
    percentages["total"] = total

    ready, reason = _gesamt_verdikt(counts)

    return {
        "counts": {**counts, "total": total},
        "percentages": percentages,
        "examples": examples,
        "default_switch_ready": ready,
        "default_switch_reason": reason,
        "errors": errors,
    }


def _summarize_mandate_for_aggregate(payload: dict[str, Any]) -> dict[str, Any]:
    """Compact per-mandate summary for the aggregation examples list.

    Kept narrow on purpose — der volle Payload bleibt im Per-Mandate-Endpoint
    zugänglich; hier reichen die Methodology §4-relevanten Felder.
    """
    return {
        "mandate_id": str(payload.get("mandate_id") or ""),
        "target_allocation_id": str(payload.get("target_allocation_id") or ""),
        "verdict": str(payload.get("verdict") or ""),
        "verdict_notes": list(payload.get("verdict_notes") or []),
        "total_drift_bps": int(payload.get("total_drift_bps") or 0),
        "risky_drift_bps": int(payload.get("risky_drift_bps") or 0),
        "limiting_factor": str(payload.get("limiting_factor") or ""),
        "optimization_status": str(payload.get("optimization_status") or ""),
        "elapsed_ms_stochastic": int(
            (payload.get("elapsed_ms") or {}).get("stochastic") or 0
        ),
        "goal_counts": dict(payload.get("goal_counts") or {}),
        "budget_compliance": dict(payload.get("budget_compliance") or {}),
    }


def _gesamt_verdikt(counts: dict[str, int]) -> tuple[bool, str]:
    """Methodology §4 Gesamt-Verdikt: Default-Wechsel ja/nein.

    Spec: "Default-Wechsel ist freigegeben, wenn ≥ 2 von 3 realen Mandaten
    = GREEN, 0 = RED". Ohne den fixen Foundation-Case (der separat geprüft
    wird) verlangen wir dasselbe Verhältnis auf der Gesamtstichprobe:
    keine RED, GREEN-Anteil ≥ 2/3, mindestens 3 Mandate insgesamt.
    """
    green = int(counts.get("green") or 0)
    yellow = int(counts.get("yellow") or 0)
    red = int(counts.get("red") or 0)
    total = green + yellow + red
    if total == 0:
        return False, "Keine Shadow-Vergleiche persistiert."
    if red > 0:
        return False, f"{red} Mandat(e) RED — Default-Wechsel hart blockiert (Methodology §4 RED)."
    if total < 3:
        return False, f"Nur {total} Mandat(e) im Shadow-Modus — Methodology §4 verlangt mindestens 3."
    if green / total < (2 / 3):
        return False, (
            f"GREEN-Anteil {green}/{total} unter 2/3 — Owner-Review für YELLOW-Mandate nötig."
        )
    return True, (
        f"{green}/{total} GREEN, {yellow} YELLOW, 0 RED — Methodology §4 Gesamt-Verdikt erfüllt."
    )
