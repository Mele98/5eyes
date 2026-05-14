"""V3 Sprint 1d Tests: Constraint Slacks + Goal Drivers.

Plan §5.3 (constraint_slacks) und §5.4 (shortfall_contributions): Macht fuer
den Berater sichtbar, welche Leitplanke wirklich begrenzt und welches Goal
den Solver-Shortfall dominiert.

Verifiziert:
- ConstraintSlack: Risky-Fraction-Cap exakt berechnet (Plan §8.3 Test).
- ConstraintSlack: per-Bucket Min/Max gegen bounds.
- is_binding nur wenn 0 <= slack <= threshold.
- is_violated nur wenn slack < 0.
- shortfall_contributions: Summe der weighted_objective_contribution
  matcht shortfall_objective Apples-to-Apples.
- shortfall_contributions: absteigend sortiert.
- Helper sind sicher gegen leere Eingaben.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.constraints import (
    ConstraintSlack,
    constraint_slacks,
)
from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.objective import (
    GoalShortfallContribution,
    shortfall_contributions,
    shortfall_objective,
)
from services.optimizer.scenario_engine import BUCKET_ORDER


# ============================================================================
# constraint_slacks
# ============================================================================


def test_constraint_slacks_marks_risky_fraction_binding():
    """Plan §8.3 Beispiel: Allocation reizt Risky-Fraction-Cap voll aus.

    equities 8750 bps * 0.8 + liquidity 1250 * 0.0 = 7000 bps. score_x10 = 70
    -> cap_bps = 7000. slack = 0 -> binding=True, violated=False.
    """
    rows = constraint_slacks(
        {"equities": 8750, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 1250},
        bounds=[(0, 1), (0, 1), (0, 1), (0, 1), (0, 1)],
        score_x10=70,
        risky_fraction_per_bucket={
            "equities": 0.8, "bonds": 0.25, "real_estate": 0.6,
            "alternatives": 0.6, "liquidity": 0.0,
        },
    )
    risk = next(r for r in rows if r.code == "risky_fraction_cap")
    assert risk.value_bps == 7000
    assert risk.limit_bps == 7000
    assert risk.slack_bps == 0
    assert risk.is_binding is True
    assert risk.is_violated is False


def test_constraint_slacks_violated_risky_fraction():
    """Risky-Anteil ueber Cap -> is_violated=True."""
    rows = constraint_slacks(
        {"equities": 9500, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 500},
        bounds=[(0, 1), (0, 1), (0, 1), (0, 1), (0, 1)],
        score_x10=70,
        risky_fraction_per_bucket={
            "equities": 0.8, "bonds": 0.25, "real_estate": 0.6,
            "alternatives": 0.6, "liquidity": 0.0,
        },
    )
    risk = next(r for r in rows if r.code == "risky_fraction_cap")
    # 9500 * 0.8 = 7600 bps > cap 7000 bps
    assert risk.value_bps == 7600
    assert risk.slack_bps == -600
    assert risk.is_violated is True
    assert risk.is_binding is False


def test_constraint_slacks_per_bucket_min_max():
    """Pro Bucket gibt es {bucket}_min und {bucket}_max Eintraege."""
    rows = constraint_slacks(
        {"equities": 5000, "bonds": 3000, "real_estate": 1000,
         "alternatives": 500, "liquidity": 500},
        bounds=[(0.4, 0.7), (0.2, 0.5), (0.0, 0.2), (0.0, 0.1), (0.02, 0.2)],
        score_x10=70,
    )
    codes = {r.code for r in rows}
    for bucket in BUCKET_ORDER:
        assert f"{bucket}_min" in codes
        assert f"{bucket}_max" in codes


def test_constraint_slacks_min_violated_when_below_floor():
    """Liquidity unter Min-Floor -> is_violated=True bei {bucket}_min."""
    rows = constraint_slacks(
        {"equities": 6000, "bonds": 3000, "real_estate": 500,
         "alternatives": 0, "liquidity": 500},
        bounds=[(0, 1), (0, 1), (0, 1), (0, 1), (0.02, 0.2)],  # liquidity-min 200 bps
        score_x10=100,
    )
    liq_min = next(r for r in rows if r.code == "liquidity_min")
    # value 500 - limit 200 = 300 -> nicht violated, nicht binding
    assert liq_min.is_violated is False
    # Test mit echter Verletzung
    rows2 = constraint_slacks(
        {"equities": 6000, "bonds": 3000, "real_estate": 500,
         "alternatives": 350, "liquidity": 150},
        bounds=[(0, 1), (0, 1), (0, 1), (0, 1), (0.02, 0.2)],
        score_x10=100,
    )
    liq_min2 = next(r for r in rows2 if r.code == "liquidity_min")
    assert liq_min2.value_bps == 150
    assert liq_min2.limit_bps == 200
    assert liq_min2.slack_bps == -50
    assert liq_min2.is_violated is True


def test_constraint_slacks_binding_threshold_default_25():
    """slack=20 -> is_binding=True; slack=30 -> is_binding=False."""
    # Equities exakt 25 bps unter dem max-cap 7000
    rows_binding = constraint_slacks(
        {"equities": 6975, "bonds": 2025, "real_estate": 500,
         "alternatives": 0, "liquidity": 500},
        bounds=[(0, 0.7), (0, 1), (0, 1), (0, 1), (0, 1)],
        score_x10=100,
    )
    eq_max = next(r for r in rows_binding if r.code == "equities_max")
    assert eq_max.slack_bps == 25
    assert eq_max.is_binding is True


def test_constraint_slacks_handles_empty_or_missing_keys():
    """Defensive: weights_bps mit fehlenden Keys -> 0 als Default."""
    rows = constraint_slacks(
        {"equities": 10000},  # nur ein Bucket gesetzt
        bounds=[(0, 1)] * 5,
        score_x10=70,
    )
    risk = next(r for r in rows if r.code == "risky_fraction_cap")
    # Default rf_map: equities=0.80; risk_used = 10000 * 0.80 = 8000
    assert risk.value_bps == 8000


def test_constraint_slacks_dataclass_is_frozen():
    cs = ConstraintSlack(
        code="x", label="X", value_bps=10, limit_bps=20,
        slack_bps=10, is_binding=False, is_violated=False,
    )
    with pytest.raises(Exception):
        cs.value_bps = 999  # type: ignore[misc]


# ============================================================================
# shortfall_contributions
# ============================================================================


def _wealth_at_t_liability(
    goal_id: str, target_amount: int, weight_bps: int = 5000,
    hardness: str = "primaer", target_year_index: int = 5,
) -> GoalLiability:
    return GoalLiability(
        goal_id=goal_id,
        label=f"goal-{goal_id}",
        goal_type="Vermoegensziel",
        target_kind="wealth_at_t",
        target_amount_rappen=target_amount,
        target_year_index=target_year_index,
        hardness_key=hardness,
        weight_bps=weight_bps,
    )


def test_shortfall_contributions_sum_matches_objective():
    """Summe der weighted_objective_contribution = shortfall_objective."""
    liabilities = [
        _wealth_at_t_liability("g1", 200_000_00, weight_bps=6000, hardness="hart"),
        _wealth_at_t_liability("g2", 100_000_00, weight_bps=3000, hardness="primaer"),
    ]
    # 50 Pfade, 6 Jahre (idx 0..5)
    rng = np.random.default_rng(42)
    wealth_paths = rng.uniform(50_000_00, 250_000_00, size=(50, 6))

    contributions = shortfall_contributions(
        liabilities, wealth_paths,
        initial_wealth_rappen=150_000_00, horizon_years=5,
    )
    total_via_contrib = sum(c.weighted_objective_contribution for c in contributions)
    total_via_objective = shortfall_objective(
        liabilities, wealth_paths,
        initial_wealth_rappen=150_000_00, horizon_years=5,
    )
    assert total_via_contrib == pytest.approx(total_via_objective, rel=1e-9)


def test_shortfall_contributions_sorted_descending():
    liabilities = [
        _wealth_at_t_liability("small", 50_000_00, weight_bps=1000, hardness="opportunistisch"),
        _wealth_at_t_liability("big", 500_000_00, weight_bps=8000, hardness="hart"),
        _wealth_at_t_liability("medium", 200_000_00, weight_bps=3000, hardness="primaer"),
    ]
    wealth_paths = np.full((100, 6), 100_000_00, dtype=np.float64)  # alle Pfade unter big-target

    contributions = shortfall_contributions(
        liabilities, wealth_paths,
        initial_wealth_rappen=100_000_00, horizon_years=5,
    )
    assert len(contributions) == 3
    contribs = [c.weighted_objective_contribution for c in contributions]
    assert contribs == sorted(contribs, reverse=True)
    # 'big' sollte ganz oben sein (groesster shortfall * groesster weight * 10x hardness)
    assert contributions[0].goal_id == "big"


def test_shortfall_contributions_empty_paths_returns_empty_list():
    liabilities = [_wealth_at_t_liability("g1", 100_000_00)]
    empty = np.zeros((0, 5))
    assert shortfall_contributions(
        liabilities, empty,
        initial_wealth_rappen=100_000_00, horizon_years=5,
    ) == []


def test_shortfall_contributions_dataclass_is_frozen():
    c = GoalShortfallContribution(
        goal_id="g1", label="G1", target_kind="wealth_at_t",
        hardness_key="hart", weight_bps=5000,
        mean_shortfall_squared=1.0, weighted_objective_contribution=1.0,
    )
    with pytest.raises(Exception):
        c.weight_bps = 999  # type: ignore[misc]


def test_shortfall_contributions_weighted_includes_hardness_and_weight():
    """Identische shortfalls + unterschiedliche Hardness -> gewichteter Beitrag
    skaliert mit HARDNESS_WEIGHT[hardness_key]."""
    hard = _wealth_at_t_liability("hart", 100_000_00, weight_bps=5000, hardness="hart")
    primaer = _wealth_at_t_liability("primaer", 100_000_00, weight_bps=5000, hardness="primaer")
    wealth_paths = np.full((10, 6), 50_000_00, dtype=np.float64)

    contribs = shortfall_contributions(
        [hard, primaer], wealth_paths,
        initial_wealth_rappen=100_000_00, horizon_years=5,
    )
    by_id = {c.goal_id: c for c in contribs}
    # Hartness-Verhaeltnis 10:1 (HARDNESS_WEIGHT)
    ratio = by_id["hart"].weighted_objective_contribution / by_id["primaer"].weighted_objective_contribution
    assert ratio == pytest.approx(10.0, rel=1e-9)
