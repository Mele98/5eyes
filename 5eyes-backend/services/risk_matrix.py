from __future__ import annotations

from collections.abc import Iterable, Mapping

from sqlalchemy.orm import Session

from models.allocation import HouseMatrix, OptimizerPolicy
from services.optimizer.constraints import BUCKET_ORDER, bucket_risky_fractions_from_building_blocks


class RiskBudgetExceeded(ValueError):
    """Raised when a generated allocation exceeds the strict risk budget."""

    def __init__(self, realized_bps: int, max_bps: int) -> None:
        self.realized_bps = int(realized_bps)
        self.max_bps = int(max_bps)
        super().__init__(
            f"Risikobudget ueberschritten: Ist={self.realized_bps} bps, "
            f"Limit={self.max_bps} bps."
        )


def score_bucket_from_assessment(assessment) -> int:
    from services.risk_assessment_semantics import (
        risk_score_bucket_from_validated_score,
        validate_risk_assessment_model_input,
    )

    return risk_score_bucket_from_validated_score(
        validate_risk_assessment_model_input(assessment)
    )


def max_risky_fraction_for_mandate(
    db: Session,
    mandate,
    assessment,
    policy: OptimizerPolicy | None = None,
) -> int:
    """Return the strict suitability cap from HouseMatrix for the assessment bucket."""
    del mandate  # reserved for future mandate-specific policy selection
    active_policy = policy
    if active_policy is None:
        active_policy = db.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
    if active_policy is None:
        raise ValueError("Keine aktive Optimizer Policy gefunden.")
    score_bucket = score_bucket_from_assessment(assessment)
    house_matrix = db.query(HouseMatrix).filter(
        HouseMatrix.policy_id == active_policy.id,
        HouseMatrix.score_from <= score_bucket,
        HouseMatrix.score_to >= score_bucket,
        HouseMatrix.is_active == 1,
    ).first()
    if house_matrix is None:
        raise ValueError(f"HouseMatrix unvollstaendig fuer Score {score_bucket}")
    return int(house_matrix.max_risky_fraction_bps)


def compute_portfolio_risky_fraction_bps(
    allocation_bps: Mapping[str, int],
    building_blocks: Iterable,
) -> int:
    """Compute sum_b weight_b * risky_fraction_b in bps."""
    rf_by_bucket_bps = bucket_risky_fraction_bps_from_building_blocks(building_blocks)
    realized = 0.0
    for bucket in BUCKET_ORDER:
        weight_bps = int((allocation_bps or {}).get(bucket, 0) or 0)
        realized += float(weight_bps) * float(rf_by_bucket_bps.get(bucket, 0)) / 10000.0
    return max(0, min(10000, int(round(realized))))


def bucket_risky_fraction_bps_from_building_blocks(building_blocks: Iterable) -> dict[str, int]:
    rf_by_bucket = bucket_risky_fractions_from_building_blocks(list(building_blocks))
    return {
        bucket: max(0, min(10000, int(round(float(rf_by_bucket.get(bucket, 0.0)) * 10000))))
        for bucket in BUCKET_ORDER
    }


def assert_risk_budget_ok(
    realized_risky_bps: int,
    max_risky_bps: int,
    *,
    slack_bps: int = 0,
) -> None:
    if int(realized_risky_bps) > int(max_risky_bps) + int(slack_bps):
        raise RiskBudgetExceeded(int(realized_risky_bps), int(max_risky_bps))


def _hardness_key(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("hart", "hard"):
        return "hart"
    if raw in ("primär", "primaer", "primary"):
        return "primär"
    if raw in ("opportunistisch", "opportunistic", "opp"):
        return "opportunistisch"
    return raw


def classify_limiting_factor(
    allocation_bps: Mapping[str, int],
    risky_fraction: int,
    max_risky_fraction: int,
    min_liquidity_bps: int,
    bands: Mapping[str, tuple[int, int]],
    achievability: list[dict],
    optimization_status: str | None,
) -> str:
    del bands  # reserved for Stage-4 message classification refinements
    if optimization_status == "fallback_house_matrix":
        return "solver_konvergenz"
    nicht_erreicht = [
        row for row in (achievability or [])
        if row.get("status") == "nicht_erreichbar"
        and _hardness_key(row.get("hardness")) in ("hart", "primär")
    ]
    if len(nicht_erreicht) >= 2:
        return "zielkonflikt"
    if nicht_erreicht and int(risky_fraction) >= int(max_risky_fraction) - 50:
        return "risikoprofil"
    if int((allocation_bps or {}).get("liquidity", 0) or 0) <= int(min_liquidity_bps) + 1:
        return "liquiditaetsreserve"
    return "bandbreite"
