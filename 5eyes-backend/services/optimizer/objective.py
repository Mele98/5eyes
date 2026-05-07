"""Objective Functions fuer den Optimizer.

Master-Spec: docs/planning/2026-05-05-stochastic-optimizer-spec.md (Sec 6)

Primary Objective (3eyes Slide 18, Priorität 1):
    L(w) = Σ_g h_g · w_g · (1/N) · Σ_n max(0, target_g - wealth_g(w, n))^2

Sekundaer (Priorität 2, wenn L ≈ 0):
    Var(w) = Var_n(W_T(w))

Hardness-Weights (OWNER-DECISION OD-1, vom User bestaetigt):
    hart: 10.0    primaer: 1.0    opportunistisch: 0.2

Pro Goal-Typ wird Shortfall anders berechnet:
- "wealth_at_t":      max(0, target - wealth[t])^2
- "cashflow_in_year": max(0, target - wealth[t])^2  (selbe Logik)
- "outflow_stream":   max(0, -wealth[end])^2  (Lebensluecke nach allen Outflows)
- "return_rate":      max(0, target_bps - annualized_return_bps)^2
- "maximize":         0  (kein Shortfall, nur in Vol-Min relevant)
"""
from __future__ import annotations

from typing import Iterable

import numpy as np

from .goal_liabilities import GoalLiability


# OWNER-DECISION OD-1 (bestaetigt 2026-05-05): 50x zwischen hart/opportunistisch.
# Im Optimizer brauchen wir staerkere Hardness-Trennung als in der reinen Score-
# Aggregation (_GOAL_HARDNESS_MULTIPLIER_BPS in portfolio_engine, Faktor 5x).
HARDNESS_WEIGHT = {
    "hart": 10.0,
    "primaer": 1.0,
    "opportunistisch": 0.2,
}


def _annualized_return_bps_per_path(
    initial_wealth_rappen: float,
    end_wealth_per_path: np.ndarray,
    horizon_years: int,
) -> np.ndarray:
    """Annualisierte Rendite pro Pfad in bps.

    Wenn end_wealth <= 0 (Lebensluecke): Rendite konstanter Wert von -10000bps
    (= -100% effektiv). Verhindert log-of-non-positive Errors und ist
    konsistent zu portfolio_engine._annualized_return_bps clamp.
    """
    horizon = max(1, int(horizon_years))
    initial = max(1.0, float(initial_wealth_rappen))
    ratio = end_wealth_per_path / initial
    safe_ratio = np.where(ratio > 0, ratio, 1e-12)
    annualized = np.power(safe_ratio, 1.0 / horizon) - 1.0
    annualized_bps = annualized * 10000.0
    # Clamp wenn Pfad negativ wurde
    annualized_bps = np.where(end_wealth_per_path > 0, annualized_bps, -10000.0)
    return annualized_bps


def shortfall_squared_per_path(
    liability: GoalLiability,
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    horizon_years: int,
) -> np.ndarray:
    """Liefert shortfall^2 pro Szenario-Pfad fuer ein Goal, shape (n_paths,).

    Wealth-Pfade kommen aus simulate_wealth_paths mit Liability bereits
    subtrahiert.
    """
    n_paths = wealth_paths.shape[0]

    if liability.target_kind == "maximize":
        return np.zeros(n_paths, dtype=np.float64)

    if liability.target_kind == "return_rate":
        target_bps = float(liability.target_amount_rappen)  # ist bps in diesem Feld
        end_wealth = wealth_paths[:, -1]
        actual_bps = _annualized_return_bps_per_path(
            initial_wealth_rappen, end_wealth, horizon_years,
        )
        # Shortfall = wenn target > actual
        shortfall = np.maximum(0.0, target_bps - actual_bps)
        return shortfall * shortfall

    if liability.target_kind in ("wealth_at_t", "cashflow_in_year"):
        target = float(liability.target_amount_rappen)
        idx = max(1, min(int(liability.target_year_index), wealth_paths.shape[1] - 1))
        wealth_at_t = wealth_paths[:, idx]
        shortfall = np.maximum(0.0, target - wealth_at_t)
        return shortfall * shortfall

    if liability.target_kind == "outflow_stream":
        # Outflows sind im liability_path bereits aus dem Wealth abgezogen.
        # Wenn end_wealth negativ -> Lebensluecke = abs(end_wealth)
        end_wealth = wealth_paths[:, -1]
        shortfall = np.maximum(0.0, -end_wealth)
        return shortfall * shortfall

    return np.zeros(n_paths, dtype=np.float64)


def shortfall_objective(
    liabilities: Iterable[GoalLiability],
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    horizon_years: int,
) -> float:
    """Primaere Objective L(w): hardness- und weight-gewichteter MSE-Shortfall.

    L(w) = Σ_g h_g · g_g · mean_n(shortfall(g, n)^2)

    h_g = HARDNESS_WEIGHT[hardness_key]
    g_g = liability.weight_bps / 10000

    Skalar-Output, von scipy.optimize.minimize konsumierbar.
    """
    total = 0.0
    n_paths = wealth_paths.shape[0]
    if n_paths <= 0:
        return 0.0
    inv_n = 1.0 / n_paths
    for liab in liabilities:
        h_weight = HARDNESS_WEIGHT.get(liab.hardness_key, 1.0)
        g_weight = max(1, int(liab.weight_bps)) / 10000.0
        per_path = shortfall_squared_per_path(
            liab, wealth_paths,
            initial_wealth_rappen=initial_wealth_rappen,
            horizon_years=horizon_years,
        )
        mean_sq = float(np.sum(per_path) * inv_n)
        total += h_weight * g_weight * mean_sq
    return total


def volatility_objective(wealth_paths: np.ndarray) -> float:
    """Sekundaere Objective: Varianz des End-Wealth ueber Pfade.

    Wird genutzt wenn die primary objective bereits ~0 ist und wir auf
    minimale Volatilitaet optimieren wollen (Slide 18 Priorität 2).
    """
    end_wealth = wealth_paths[:, -1]
    return float(np.var(end_wealth))


def combined_objective_two_phase(
    liabilities: Iterable[GoalLiability],
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    horizon_years: int,
    primary_weight: float = 1.0,
    volatility_weight: float = 1e-12,
) -> float:
    """Kombination Primary + tiny Volatility-Term.

    Nuetzlich als single-phase Approximation: L(w) + ε · Var(w). Wenn
    Goals erfuellt sind, dominiert der vol-Term und Solver minimiert Vol.
    Sonst dominiert Primary. Vorteil: nur ein Solve-Run, kein 2-Phase Switch.

    primary_weight: skaliert L(w)
    volatility_weight: typischerweise 1e-12 weil Var(wealth) in rappen^2 sehr gross ist
    """
    primary = shortfall_objective(
        liabilities, wealth_paths,
        initial_wealth_rappen=initial_wealth_rappen,
        horizon_years=horizon_years,
    )
    vol = volatility_objective(wealth_paths)
    return primary_weight * primary + volatility_weight * vol
