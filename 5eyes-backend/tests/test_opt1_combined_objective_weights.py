"""OPT-1: combined_objective_two_phase muss `weights` auch in die
chance_constraint_penalty durchreichen (nicht nur in shortfall_/volatility_objective).

Reiner Test ohne DB. Mit primary_weight=0 und volatility_weight=0 reduziert sich
der Rückgabewert auf den Chance-Penalty-Term — so lässt sich isoliert nachweisen,
dass die Importance-Sampling-Gewichte den Strafterm verändern. Vor dem Fix war der
Term gewichtsunabhängig (uniformes Sample-Mean) -> dieser Test schlüge fehl.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.objective import combined_objective_two_phase


def _hard_goal() -> GoalLiability:
    return GoalLiability(
        goal_id="g1",
        label="Vermögensziel",
        goal_type="Vermoegensziel",
        target_kind="wealth_at_t",
        target_amount_rappen=100_000_00,
        target_year_index=5,
        liability_path_rappen=[0] * 11,
        hardness_key="hart",          # bindend -> Penalty greift
        weight_bps=10000,
        success_probability_min_x100=8000,  # tau = 0.80
    )


def _paths() -> np.ndarray:
    # 2 Pfade, 11 Spalten. Bei idx5: Pfad0 erreicht Ziel (150k), Pfad1 nicht (50k).
    p = np.full((2, 11), 100_000_00, dtype=np.float64)
    p[0, 5] = 150_000_00
    p[1, 5] = 50_000_00
    return p


def _chance_only(weights):
    return combined_objective_two_phase(
        [_hard_goal()],
        _paths(),
        initial_wealth_rappen=100_000_00,
        horizon_years=10,
        primary_weight=0.0,      # Primary ausblenden
        volatility_weight=0.0,   # Vol ausblenden -> Rückgabe == Chance-Penalty
        lambda_chance=1.0,
        weights=weights,
    )


def test_opt1_weights_change_chance_penalty():
    uniform = _chance_only(None)                      # P=0.5 -> shortfall 0.30
    mass_on_pass = _chance_only(np.array([0.99, 0.01]))   # P~0.99 -> shortfall 0
    mass_on_fail = _chance_only(np.array([0.01, 0.99]))   # P~0.01 -> shortfall ~0.79

    # Gewichte müssen den Strafterm bewegen — und zwar in die richtige Richtung.
    assert mass_on_pass < uniform < mass_on_fail
    # Konkret: Masse auf dem erfolgreichen Pfad -> (nahezu) keine Strafe.
    assert mass_on_pass == 0.0 or mass_on_pass < 1e-6
    # Masse auf dem Fehlpfad -> deutlich höhere Strafe als uniform.
    assert mass_on_fail > uniform * 2


def test_opt1_uniform_matches_unweighted_mean():
    # Ohne Gewichte: P = 0.5, shortfall = 0.8 - 0.5 = 0.3, penalty = 1.0 * 0.3^2 = 0.09
    assert abs(_chance_only(None) - 0.09) < 1e-9
