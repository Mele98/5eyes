"""Sprint U-P15 (2026-05-21): A/B-HouseMatrix-Backtest.

Zwei OptimizerPolicy-Versionen (A und B) werden auf das Risikoprofil eines
Mandates angewandt und auf identische CMA/Stress-Szenarien gerechnet.
Liefert pro Policy: Bucket-Gewichtung, Risk-Metriken (Return/Vol/Sharpe/TER)
und alle 5 historischen Stress-Replays — plus die Diff-Strukturen.

Strikt READ-ONLY: keine DB-Mutation, kein Audit-Log, kein Optimizer-Lauf.
Wir nutzen den reinen House-Matrix-Pfad (`_baseline_target_bands`) — Tilts,
Goals, Reserve-Logik etc. werden bewusst NICHT angewandt, weil sie
mandant-/situations-spezifisch sind und den Policy-Diff verwässern würden.

Wechselwirkungen:
- U-P7 OptimizerPolicy-Versionierung (Snapshot via policy_id)
- U-P13 Stress-Replays (Wiederverwendung von compute_stress_for_weights)
- Reiner Read-Pfad (analog Sprint U-P12/U-P13).
"""
from __future__ import annotations

from typing import Mapping

from sqlalchemy.orm import Session

from models.allocation import (
    CapitalMarketAssumption,
    HouseMatrix,
    OptimizerPolicy,
)
from models.mandates import Mandate
from services.backtest_stress import compute_stress_for_weights
from services.portfolio_engine import (
    _baseline_target_bands,
    _expected_metrics,
    _house_matrix_or_default,
    _risk_score_bucket,
    require_strategy_ready_assessment,
)


BUCKET_LABELS = {
    "equities": "Aktien",
    "bonds": "Obligationen",
    "real_estate": "Immobilien",
    "alternatives": "Alternative Anlagen",
    "liquidity": "Liquidität",
}
BUCKETS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")


def _policy_or_404(db: Session, policy_id: str) -> OptimizerPolicy:
    policy = (
        db.query(OptimizerPolicy)
        .filter(OptimizerPolicy.id == policy_id)
        .first()
    )
    if policy is None:
        raise ValueError(f"OptimizerPolicy {policy_id} nicht gefunden")
    return policy


def _evaluate_policy(
    db: Session,
    policy: OptimizerPolicy,
    score_bucket: int,
    cma: CapitalMarketAssumption,
) -> dict:
    """Reiner House-Matrix-Pfad für eine einzelne Policy.

    Liefert Bucket-Gewichtung, House-Matrix-Bands, Risk-Metriken und
    Stress-Replays. Keine Side-Effects.
    """
    hm: HouseMatrix = _house_matrix_or_default(db, policy, score_bucket)
    targets, minimums, maximums = _baseline_target_bands(hm, policy)
    metrics = _expected_metrics(targets, cma, sub_allocations=None, products=None)
    return {
        "policy_id": str(policy.id),
        "policy_name": str(policy.policy_name),
        "version": int(policy.version),
        "is_current": bool(policy.is_current),
        "profile_name": str(hm.profile_name),
        "max_risky_fraction_bps": int(hm.max_risky_fraction_bps),
        "weights_bps": dict(targets),
        "bands": {
            bucket: {"min_bps": int(minimums[bucket]), "max_bps": int(maximums[bucket])}
            for bucket in BUCKETS
        },
        "expected_return_bps": int(metrics.get("expected_return_bps", 0) or 0),
        "expected_return_gross_bps": int(metrics.get("expected_return_gross_bps", 0) or 0),
        "expected_volatility_bps": int(metrics.get("expected_volatility_bps", 0) or 0),
        "expected_ter_bps": int(metrics.get("expected_ter_bps", 0) or 0),
        "sharpe_ratio_x100": int(metrics.get("sharpe_ratio_x100", 0) or 0),
        "risk_free_bps": int(metrics.get("risk_free_bps", 0) or 0),
        "stress_scenarios": compute_stress_for_weights(targets),
    }


def _buckets_diff(
    weights_a: Mapping[str, int], weights_b: Mapping[str, int]
) -> dict[str, dict[str, int]]:
    diff: dict[str, dict[str, int]] = {}
    for bucket in BUCKETS:
        a = int(weights_a.get(bucket, 0) or 0)
        b = int(weights_b.get(bucket, 0) or 0)
        diff[bucket] = {
            "label": BUCKET_LABELS[bucket],
            "a_bps": a,
            "b_bps": b,
            "delta_bps": b - a,
        }
    return diff


def _stress_diff(
    scenarios_a: list[dict], scenarios_b: list[dict]
) -> list[dict]:
    """Diff zwischen den zwei Stress-Replay-Listen. Match per scenario-id."""
    by_id_b = {s.get("id"): s for s in scenarios_b}
    result: list[dict] = []
    for sa in scenarios_a:
        sid = sa.get("id")
        sb = by_id_b.get(sid, {})
        a_cum = int(sa.get("cumulative_return_bps", 0) or 0)
        b_cum = int(sb.get("cumulative_return_bps", 0) or 0)
        a_dd = int(sa.get("max_drawdown_bps", 0) or 0)
        b_dd = int(sb.get("max_drawdown_bps", 0) or 0)
        result.append({
            "id": sid,
            "label": str(sa.get("label", "") or ""),
            "period": str(sa.get("period", "") or ""),
            "a_cumulative_return_bps": a_cum,
            "b_cumulative_return_bps": b_cum,
            "delta_cumulative_return_bps": b_cum - a_cum,
            "a_max_drawdown_bps": a_dd,
            "b_max_drawdown_bps": b_dd,
            "delta_max_drawdown_bps": b_dd - a_dd,
            "a_recovery_months": int(sa.get("recovery_months", 0) or 0),
            "b_recovery_months": int(sb.get("recovery_months", 0) or 0),
        })
    return result


def _risk_metrics_diff(a: dict, b: dict) -> dict[str, int]:
    return {
        "delta_expected_return_bps": int(b["expected_return_bps"]) - int(a["expected_return_bps"]),
        "delta_expected_volatility_bps": int(b["expected_volatility_bps"]) - int(a["expected_volatility_bps"]),
        "delta_expected_ter_bps": int(b["expected_ter_bps"]) - int(a["expected_ter_bps"]),
        "delta_sharpe_ratio_x100": int(b["sharpe_ratio_x100"]) - int(a["sharpe_ratio_x100"]),
    }


def run_ab_backtest(
    db: Session,
    mandate: Mandate,
    policy_a_id: str,
    policy_b_id: str,
) -> dict:
    """A/B-HouseMatrix-Backtest für ein Mandat.

    Wendet beide Policies (A und B) auf das Risikoprofil des Mandates an,
    rechnet pro Policy:
      - Bucket-Gewichtung aus HouseMatrix-Row
      - Expected-Return / Vol / Sharpe / TER (aus aktueller CMA)
      - Stress-Replays über alle 5 historischen Szenarien
    Liefert beide Snapshots + Diff-Strukturen.

    Raises:
        ValueError: wenn Policy nicht gefunden, Assessment fehlt, oder
            keine aktive CMA hinterlegt ist.
    """
    if policy_a_id == policy_b_id:
        raise ValueError("policy_a und policy_b müssen unterschiedlich sein.")

    policy_a = _policy_or_404(db, policy_a_id)
    policy_b = _policy_or_404(db, policy_b_id)

    assessment = require_strategy_ready_assessment(db, mandate.id)
    score_bucket = _risk_score_bucket(assessment)

    cma = (
        db.query(CapitalMarketAssumption)
        .filter(
            CapitalMarketAssumption.is_current == 1,
            CapitalMarketAssumption.deleted_at.is_(None),
        )
        .first()
    )
    if cma is None:
        raise ValueError(
            "Keine aktive Capital-Market-Assumption gefunden — A/B-Backtest "
            "benötigt eine CMA für die Risk-Metriken."
        )

    view_a = _evaluate_policy(db, policy_a, score_bucket, cma)
    view_b = _evaluate_policy(db, policy_b, score_bucket, cma)

    warnings: list[str] = []
    if view_a["profile_name"] != view_b["profile_name"]:
        warnings.append(
            f"Unterschiedliche House-Matrix-Profile (A: {view_a['profile_name']}, "
            f"B: {view_b['profile_name']}) — Score-Bucket {score_bucket} wird "
            f"in beiden Policies abgedeckt, aber das Profil-Konzept ist nicht "
            f"identisch."
        )

    return {
        "mandate_id": str(mandate.id),
        "score_bucket": score_bucket,
        "cma_id": str(cma.id),
        "cma_version": int(getattr(cma, "version", 0) or 0),
        "policy_a": view_a,
        "policy_b": view_b,
        "buckets_diff": _buckets_diff(view_a["weights_bps"], view_b["weights_bps"]),
        "risk_metrics_diff": _risk_metrics_diff(view_a, view_b),
        "stress_diff": _stress_diff(view_a["stress_scenarios"], view_b["stress_scenarios"]),
        "warnings": warnings,
        "note": (
            "Reiner House-Matrix-Pfad — Tilts, Goals und Reserve-Logik werden "
            "bewusst nicht angewandt, damit der Diff den Policy-Effekt isoliert. "
            "Beide Policies werden gegen die aktuelle CMA gemessen."
        ),
    }
