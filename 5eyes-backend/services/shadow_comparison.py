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
    if str(optimization_status or "") != "converged":
        red_reasons.append("optimization_status != converged")
    if int(n_hard_unreachable_st) > 0:
        red_reasons.append("n_hard_unreachable_st > 0")
    if int(elapsed_ms) > 15000:
        red_reasons.append("elapsed_ms > 15000")
    if red_reasons:
        return {"status": "RED", "reasons": red_reasons}

    yellow_reasons: list[str] = []
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
