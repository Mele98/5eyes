"""SLSQP-Solver mit Multi-Start fuer den Stochastic Optimizer.

Master-Spec: docs/planning/2026-05-05-stochastic-optimizer-spec.md (Sec 8)

Workflow:
1. Compute deterministic seed aus (mandate, cma, goals, score) - reproduzierbar
2. Build scenario paths (NumPy vektorisiert, Cornish-Fisher fat-tails)
3. Convert goals -> liabilities + aggregate liability path
4. Setup constraints aus House-Matrix + globale Caps
5. Multi-Start: 3-5 Initial-Allocations (House-Matrix-Mid, Conservative,
   Aggressive, Risky-Fraction-Edge, gleichverteilt)
6. SLSQP pro Initial-Allocation
7. Pick best result (lowest objective)
8. Validate feasibility, return OptimizerResult mit Audit-Trace

Fallback-Strategie (OWNER-DECISION OD-5):
- Wenn alle Multi-Starts divergieren: status="fallback_house_matrix" mit
  reasoning. Caller kann dann House-Matrix-Default verwenden.
- Wenn Solver konvergiert aber Allocation infeasible: status="diverged_infeasible".
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from scipy.optimize import OptimizeResult, minimize

from .constraints import (
    HouseMatrixBands,
    bands_from_house_matrix_row,
    build_bounds,
    build_constraint_set,
    is_feasible,
)
from .goal_liabilities import (
    GoalLiability,
    aggregate_liability_path,
    goals_to_liabilities,
)
from .objective import shortfall_objective
from .scenario_engine import (
    BUCKET_ORDER,
    N_BUCKETS,
    build_scenario_paths,
    scenario_inputs_from_cma,
    simulate_wealth_paths,
)


# ============================================================================
# Result-Datenklasse
# ============================================================================


@dataclass(frozen=True)
class OptimizerResult:
    """Allocation + Audit-Trace aus dem Optimizer.

    weights_bps: Bucket-Gewichte in bps (summe ~ 10000), in BUCKET_ORDER-Reihenfolge.
    """
    weights_bps: dict[str, int]
    objective_value: float
    iterations: int
    seed: int
    status: str  # "converged" | "diverged" | "diverged_infeasible" | "fallback_house_matrix"
    method: str  # "stochastic" | "fallback_house_matrix"
    constraint_violations: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    n_paths: int = 0
    n_starts_attempted: int = 0


# ============================================================================
# Deterministic Seed
# ============================================================================


def deterministic_seed(*parts) -> int:
    """Reproduzierbarer 63-bit Seed aus String-Parts.

    Konsistent zu portfolio_engine._monte_carlo_seed-Idee, aber unabhaengig.
    SHA-256 verkleinert auf 63 bit (numpy default_rng nimmt unsigned 64-bit;
    63-bit reicht und vermeidet Vorzeichen-Verwirrung).
    """
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x00")
    return int.from_bytes(h.digest()[:8], "big") & 0x7FFFFFFFFFFFFFFF


# ============================================================================
# Initial Guesses fuer Multi-Start
# ============================================================================


def _normalize_to_bounds(w: np.ndarray, bounds: list[tuple[float, float]]) -> np.ndarray:
    """Projeziert w auf bounds und re-normalisiert zu sum=1.

    Best-effort: clipped auf bounds, dann skaliert zu sum=1, dann erneut
    geclipped. Bei pathologischen Bounds-Sets kann das nicht-feasible bleiben -
    der is_feasible-Check im Solver faengt das ab.
    """
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    w = np.clip(w, lo, hi)
    s = w.sum()
    if s > 0:
        w = w / s
        w = np.clip(w, lo, hi)
        s = w.sum()
        if s > 0:
            w = w / s
    return w


def _is_within_bounds(w: np.ndarray, bounds: list[tuple[float, float]], tol: float = 1e-6) -> bool:
    """Prueft Bounds-Compliance + sum=1 (gewuenscht fuer SLSQP-Initial)."""
    if abs(np.sum(w) - 1.0) > tol:
        return False
    for i, (lo, hi) in enumerate(bounds):
        if w[i] < lo - tol or w[i] > hi + tol:
            return False
    return True


def build_initial_guesses(
    bounds: list[tuple[float, float]],
    score_x10: int,
) -> list[np.ndarray]:
    """Liefert Multi-Start-Initials, alle innerhalb der Bounds und summe~1.

    OWNER-DECISION OD-5: Multi-Start verbessert SLSQP-Robustheit gegen
    Lokal-Minima. Erzeugte Kandidaten:
    1. Mid-of-bounds (zentral)
    2. Conservative: max Liquiditaet, min Risiko
    3. Aggressive: max Equities, in Bounds
    4. Risk-cap-edge: Risky-Fraction-Limit voll ausnutzen
    5. Equal: 1/n pro Bucket (Default-Diversifikation)

    Infeasible-Kandidaten (z.B. wegen pathologischer Bounds) werden gefiltert.
    Mindestens 1 Kandidat (Mid-of-Bounds) wird auch dann zurueckgegeben wenn
    er nicht 100% feasible ist - damit der Solver nie ohne Start dasteht.
    """
    n = len(bounds)
    candidates: list[np.ndarray] = []

    # 1. Mid-of-bounds
    mid = np.array([(lo + hi) / 2.0 for lo, hi in bounds])
    candidates.append(_normalize_to_bounds(mid, bounds))

    # 2. Conservative: maximize liquidity (last bucket), minimize others
    cons = np.array([lo for lo, _ in bounds])
    liq_idx = BUCKET_ORDER.index("liquidity")
    remaining = max(0.0, 1.0 - cons.sum() + cons[liq_idx])
    cons[liq_idx] = min(bounds[liq_idx][1], remaining)
    candidates.append(_normalize_to_bounds(cons, bounds))

    # 3. Aggressive: maximize equities first
    aggr = np.array([lo for lo, _ in bounds])
    eq_idx = BUCKET_ORDER.index("equities")
    aggr[eq_idx] = bounds[eq_idx][1]
    leftover = 1.0 - aggr.sum()
    if leftover > 0:
        bonds_idx = BUCKET_ORDER.index("bonds")
        addable_bonds = min(leftover, bounds[bonds_idx][1] - aggr[bonds_idx])
        aggr[bonds_idx] += addable_bonds
        leftover -= addable_bonds
        if leftover > 0:
            addable_liq = min(leftover, bounds[liq_idx][1] - aggr[liq_idx])
            aggr[liq_idx] += addable_liq
    candidates.append(_normalize_to_bounds(aggr, bounds))

    # 4. Risk-Cap-Edge: knapp unter Risky-Fraction-Cap
    risk_target = max(0.0, min(1.0, score_x10 / 100.0)) * 0.95
    edge = np.array([lo for lo, _ in bounds])
    bonds_idx = BUCKET_ORDER.index("bonds")
    edge[eq_idx] = min(bounds[eq_idx][1], risk_target)
    edge[bonds_idx] = max(bounds[bonds_idx][0], 1 - edge.sum() + edge[bonds_idx])
    candidates.append(_normalize_to_bounds(edge, bounds))

    # 5. Equal-weight - kann infeasible werden bei strikten Bounds
    eq = np.full(n, 1.0 / n)
    candidates.append(_normalize_to_bounds(eq, bounds))

    # Filter feasible Kandidaten; wenn alle infeasible: behalte mindestens
    # Mid-of-Bounds als Best-Effort-Start.
    feasible = [w for w in candidates if _is_within_bounds(w, bounds, tol=1e-3)]
    if not feasible:
        feasible = [candidates[0]]
    return feasible


# ============================================================================
# SLSQP Solver
# ============================================================================


def _solve_single_start(
    objective_fn,
    x0: np.ndarray,
    bounds: list[tuple[float, float]],
    constraints: list[dict],
    *,
    max_iter: int = 50,
    ftol: float = 1e-6,
) -> OptimizeResult:
    """Ein einzelner SLSQP-Solve. Konvertiert OptimizeResult-typ Errors zu
    diverged-OptimizeResult statt crash."""
    try:
        return minimize(
            objective_fn,
            x0=x0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": max_iter, "ftol": ftol, "disp": False},
        )
    except Exception as e:  # noqa: BLE001 - we want to handle solver crashes gracefully
        # Konstruiere Fake-OptimizeResult mit success=False
        result = OptimizeResult(
            x=x0,
            fun=float("inf"),
            success=False,
            status=99,
            message=f"solver-crash: {type(e).__name__}: {e}",
            nit=0,
        )
        return result


def run_solver(
    *,
    cma,
    goals: list,
    house_matrix_row,
    score_x10: int,
    advisory_wealth_rappen: int,
    cashflow_series_rappen: Iterable[int],
    horizon_years: int = 10,
    n_paths: int = 2000,
    seed: int | None = None,
    inflation_series_bps: list[int] | None = None,
    risky_fraction_per_bucket: dict[str, float] | None = None,
    max_iter: int = 50,
    ftol: float = 1e-6,
) -> OptimizerResult:
    """Mulvey-Light SLSQP Optimizer.

    Returns OptimizerResult mit weights_bps + Audit-Trace.

    Bei Solver-Divergenz aller Multi-Starts: status='fallback_house_matrix'
    mit House-Matrix-Mid als weights (OWNER-DECISION OD-5).
    """
    # ---- 1. Seed ----
    if seed is None:
        cma_id = getattr(cma, "id", "no-cma")
        goal_ids = "|".join(str(getattr(g, "id", "?")) for g in goals)
        seed = deterministic_seed(cma_id, goal_ids, score_x10, horizon_years, n_paths)

    # ---- 2. Scenario Paths ----
    inputs = scenario_inputs_from_cma(cma)
    return_paths = build_scenario_paths(
        inputs, horizon_years=horizon_years, n_paths=n_paths, seed=seed,
    )

    # ---- 3. Liabilities ----
    liabilities = goals_to_liabilities(
        goals, horizon_years=horizon_years, inflation_series_bps=inflation_series_bps,
    )
    aggregated_liability = aggregate_liability_path(liabilities, horizon_years)

    # ---- 4. Constraints ----
    bands = bands_from_house_matrix_row(house_matrix_row)
    bounds, scipy_constraints = build_constraint_set(
        bands, score_x10, risky_fraction_per_bucket=risky_fraction_per_bucket,
    )

    # ---- 5. Objective Closure ----
    def objective_fn(w: np.ndarray) -> float:
        wealth = simulate_wealth_paths(
            initial_wealth_rappen=advisory_wealth_rappen,
            weights=w,
            return_paths=return_paths,
            cashflow_series_rappen=cashflow_series_rappen,
            liability_path_rappen=aggregated_liability,
        )
        return shortfall_objective(
            liabilities, wealth,
            initial_wealth_rappen=advisory_wealth_rappen,
            horizon_years=horizon_years,
        )

    # ---- 6. Multi-Start ----
    initials = build_initial_guesses(bounds, score_x10)
    best_result: OptimizeResult | None = None
    best_obj = float("inf")
    total_iters = 0

    for x0 in initials:
        result = _solve_single_start(
            objective_fn, x0, bounds, scipy_constraints,
            max_iter=max_iter, ftol=ftol,
        )
        total_iters += int(getattr(result, "nit", 0) or 0)
        if result.success and result.fun < best_obj:
            best_obj = float(result.fun)
            best_result = result

    # ---- 7. Status & Output ----
    if best_result is None:
        # Alle Starts divergiert -> Fallback
        mid = _normalize_to_bounds(
            np.array([(lo + hi) / 2.0 for lo, hi in bounds]),
            bounds,
        )
        weights_bps = _weights_to_bps_dict(mid)
        return OptimizerResult(
            weights_bps=weights_bps,
            objective_value=float("inf"),
            iterations=total_iters,
            seed=seed,
            status="fallback_house_matrix",
            method="fallback_house_matrix",
            reasoning=[
                "Alle Solver-Multi-Starts divergierten. Fallback auf "
                "House-Matrix-Mittelwert (siehe OWNER-DECISION OD-5)."
            ],
            n_paths=n_paths,
            n_starts_attempted=len(initials),
        )

    # Final clip + renorm + feasibility check
    final_w = _normalize_to_bounds(np.clip(best_result.x, 0.0, 1.0), bounds)
    feasible, violation_reasons = is_feasible(
        final_w, bounds=bounds, constraints=scipy_constraints,
    )

    if not feasible:
        status = "diverged_infeasible"
    else:
        status = "converged"

    weights_bps = _weights_to_bps_dict(final_w)
    reasoning: list[str] = []
    reasoning.append(f"Stochastic Solver: {total_iters} iterations across "
                      f"{len(initials)} multi-starts.")
    reasoning.append(f"Best objective L(w*) = {best_obj:.6e}")
    if violation_reasons:
        reasoning.append("Constraint-Verletzungen am Optimum:")
        reasoning.extend(f"  - {r}" for r in violation_reasons)

    return OptimizerResult(
        weights_bps=weights_bps,
        objective_value=best_obj,
        iterations=total_iters,
        seed=seed,
        status=status,
        method="stochastic",
        constraint_violations=violation_reasons,
        reasoning=reasoning,
        n_paths=n_paths,
        n_starts_attempted=len(initials),
    )


def _weights_to_bps_dict(weights: np.ndarray) -> dict[str, int]:
    """Konvertiert weight-array (0..1) in {bucket: bps}-dict.

    Stellt sicher dass Summe genau 10000 ist (Rounding-Fix auf groesstes Bucket).
    """
    bps_floats = weights * 10000.0
    bps_ints = [int(round(v)) for v in bps_floats]
    diff = 10000 - sum(bps_ints)
    if diff != 0:
        # Korrektur auf den groessten Bucket
        max_idx = int(np.argmax(weights))
        bps_ints[max_idx] += diff
    return {bucket: bps_ints[i] for i, bucket in enumerate(BUCKET_ORDER)}
