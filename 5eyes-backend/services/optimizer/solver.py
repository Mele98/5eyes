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
from scipy.optimize import OptimizeResult, differential_evolution, minimize

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
from .scenario_cache import build_scenario_paths_cached
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
    stress_evaluations: optional dict[scenario_name, StressResult-dict] aus
        Phase 5.2 Stress-Audit. None bei fallback-Modus.
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
    stress_evaluations: dict[str, dict] | None = None


# ============================================================================
# V3 Sprint 1b (2026-05-08): OptimizerContext + Evaluation
#
# Plan §5.2: Wiederverwendbare Evaluation beliebiger Gewichtungen unter
# denselben Szenarien, damit House-Matrix und Solver-Vorschlag Apples-to-
# Apples bewertet werden koennen.
# ============================================================================


@dataclass(frozen=True)
class OptimizerContext:
    """Gemeinsame Inputs fuer Solver und externe Evaluation.

    Wenn zwei Aufrufer mit identischem Context arbeiten (gleiche cma_id,
    gleicher seed, gleiche n_paths), erhalten sie identische Szenarien und
    Liability-Pfade. Damit ist `evaluate_weights(ctx, w_a)` vergleichbar mit
    `evaluate_weights(ctx, w_b)`.
    """
    cma_id: str
    seed: int
    horizon_years: int
    n_paths: int
    advisory_wealth_rappen: int
    cashflow_series_rappen: list[int]
    return_paths: np.ndarray
    liabilities: list[GoalLiability]
    aggregated_liability_path: np.ndarray
    bounds: list[tuple[float, float]]
    scipy_constraints: list[dict]
    score_x10: int
    risky_fraction_per_bucket: dict[str, float] | None = None
    # Phase 5c: optional Likelihood-Weights aus Importance Sampling.
    # Wenn None: trivialer sample-mean (Backwards-Compat). Wenn gesetzt:
    # shortfall_objective + volatility_objective berechnen weighted Estimator.
    # Aktivierung: Caller (build_optimizer_context oder ext. Pfad) liefert
    # weights vom build_scenario_paths_with_weights-Wrapper.
    scenario_weights: np.ndarray | None = None
    # Sprint 4 Phase 3 (2026-05-17): Optional mortalitaets-Sampling.
    # Wenn None: keine Mortality (Backwards-Compat). Wenn gesetzt: shape
    # (n_paths,) integer-Array, pro Pfad year_index ab dem cashflow=0.
    # Aktivierung: Caller liefert den Array aus
    # services.mortality.sample_age_at_death + death_year_index_from_age.
    mortality_death_year_index_per_path: np.ndarray | None = None


@dataclass(frozen=True)
class OptimizerEvaluation:
    """Bewertung einer konkreten Allocation unter einem OptimizerContext."""
    weights_bps: dict[str, int]
    objective_value: float
    feasible: bool
    constraint_violations: list[str] = field(default_factory=list)
    terminal_wealth_p10_rappen: int | None = None
    terminal_wealth_p50_rappen: int | None = None
    terminal_wealth_p90_rappen: int | None = None


def _weights_bps_to_array(weights_bps: dict[str, int]) -> np.ndarray:
    """Konvertiert {bucket: bps} -> np.ndarray (5 Buckets, summe = 1).

    Wird genutzt damit evaluate_weights deterministisch denselben Float-Vektor
    erhaelt wie der Solver intern (ueber denselben Rounding-Pfad).
    """
    raw = np.array(
        [int((weights_bps or {}).get(bucket, 0) or 0) / 10000.0 for bucket in BUCKET_ORDER],
        dtype=np.float64,
    )
    s = float(raw.sum())
    if s > 1e-12:
        raw = raw / s
    return raw


def build_optimizer_context(
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
    client_birth_year: int | None = None,
    client_sex: str | None = None,
    use_mortality_simulation: bool = False,
) -> OptimizerContext:
    """Baut den Solver-Context (Scenarios, Liabilities, Bounds, Constraints).

    Identische Inputs liefern identische Contexts. Wenn `seed=None`, wird der
    deterministische Seed aus `(cma_id, goal_ids, score_x10, horizon, n_paths)`
    abgeleitet — gleicher Pfad wie bisher in `run_solver`.
    """
    if seed is None:
        cma_id = getattr(cma, "id", "no-cma")
        goal_ids = "|".join(str(getattr(g, "id", "?")) for g in goals)
        seed = deterministic_seed(cma_id, goal_ids, score_x10, horizon_years, n_paths)

    inputs = scenario_inputs_from_cma(cma)
    cma_id_for_cache = str(getattr(cma, "id", "no-cma"))
    return_paths = build_scenario_paths_cached(
        inputs,
        cma_id=cma_id_for_cache,
        horizon_years=horizon_years,
        n_paths=n_paths,
        seed=seed,
    )

    liabilities = goals_to_liabilities(
        goals,
        horizon_years=horizon_years,
        inflation_series_bps=inflation_series_bps,
    )
    aggregated_liability = aggregate_liability_path(liabilities, horizon_years)
    bands = bands_from_house_matrix_row(house_matrix_row)
    bounds, scipy_constraints = build_constraint_set(
        bands,
        score_x10,
        risky_fraction_per_bucket=risky_fraction_per_bucket,
    )

    # Sprint 4 Phase 3: Mortalitaets-Sampling wenn aktiviert
    death_indices = None
    if use_mortality_simulation and client_birth_year and client_sex in ("M", "F"):
        try:
            from datetime import date as _date
            from services.mortality.bfs import BFS_2020_2022
            from services.mortality.sampler import (
                death_year_index_from_age,
                sample_age_at_death,
            )
            current_age = max(0, int(_date.today().year - int(client_birth_year)))
            death_ages = sample_age_at_death(
                n_paths=int(n_paths),
                current_age=current_age,
                sex=client_sex,
                table=BFS_2020_2022,
                seed=int(seed),
            )
            death_indices = death_year_index_from_age(
                death_ages,
                current_age=current_age,
                horizon_years=int(horizon_years),
            )
        except Exception:
            # Defensive: keine Mortality bei Fehler — Backwards-Compat
            death_indices = None

    return OptimizerContext(
        cma_id=cma_id_for_cache,
        seed=int(seed),
        horizon_years=int(horizon_years),
        n_paths=int(n_paths),
        advisory_wealth_rappen=int(advisory_wealth_rappen or 0),
        cashflow_series_rappen=list(cashflow_series_rappen),
        return_paths=return_paths,
        liabilities=list(liabilities),
        aggregated_liability_path=aggregated_liability,
        bounds=list(bounds),
        scipy_constraints=list(scipy_constraints),
        score_x10=int(score_x10),
        risky_fraction_per_bucket=risky_fraction_per_bucket,
        mortality_death_year_index_per_path=death_indices,
    )


def _objective_from_array(context: OptimizerContext, w: np.ndarray) -> float:
    """Internes Objective fuer einen w-Array unter dem Context.

    Wird vom Solver-Closure genutzt, damit der Optimierungslauf exakt die
    gleichen Scenarios sieht wie evaluate_weights spaeter.

    Phase 5c: respektiert context.scenario_weights (IS-Likelihood-Ratios)
    wenn gesetzt. Bei scenario_weights=None: trivialer sample-mean wie zuvor.
    """
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=context.advisory_wealth_rappen,
        weights=w,
        return_paths=context.return_paths,
        cashflow_series_rappen=context.cashflow_series_rappen,
        liability_path_rappen=context.aggregated_liability_path,
        death_year_index_per_path=context.mortality_death_year_index_per_path,
    )
    return float(shortfall_objective(
        context.liabilities,
        wealth,
        initial_wealth_rappen=context.advisory_wealth_rappen,
        horizon_years=context.horizon_years,
        weights=context.scenario_weights,
    ))


def evaluate_weights(
    context: OptimizerContext,
    weights_bps: dict[str, int],
) -> OptimizerEvaluation:
    """Bewertet eine konkrete bps-Allocation unter dem Context.

    Liefert:
    - objective_value: shortfall_objective unter den Scenarios des Context
    - feasible / constraint_violations: gegen bounds + scipy_constraints
    - terminal_wealth_p10/p50/p90: Endvermoegen-Quantile in Rappen
    """
    w = _weights_bps_to_array(weights_bps)
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=context.advisory_wealth_rappen,
        weights=w,
        return_paths=context.return_paths,
        cashflow_series_rappen=context.cashflow_series_rappen,
        liability_path_rappen=context.aggregated_liability_path,
        death_year_index_per_path=context.mortality_death_year_index_per_path,
    )
    objective = shortfall_objective(
        context.liabilities,
        wealth,
        initial_wealth_rappen=context.advisory_wealth_rappen,
        horizon_years=context.horizon_years,
        weights=context.scenario_weights,
    )
    feasible, violations = is_feasible(
        w, bounds=context.bounds, constraints=context.scipy_constraints,
    )
    terminal = wealth[:, -1] if wealth.size else np.array([], dtype=np.float64)
    if terminal.size:
        p10, p50, p90 = np.percentile(terminal, [10, 50, 90])
        p10_i = int(round(float(p10)))
        p50_i = int(round(float(p50)))
        p90_i = int(round(float(p90)))
    else:
        p10_i = p50_i = p90_i = None

    return OptimizerEvaluation(
        weights_bps=_weights_to_bps_dict(w),
        objective_value=float(objective),
        feasible=bool(feasible),
        constraint_violations=list(violations),
        terminal_wealth_p10_rappen=p10_i,
        terminal_wealth_p50_rappen=p50_i,
        terminal_wealth_p90_rappen=p90_i,
    )


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


def _solve_via_genetic_algorithm(
    objective_fn,
    bounds: list[tuple[float, float]],
    constraints: list[dict],
    *,
    seed: int,
    max_iter: int = 60,
    popsize: int = 15,
) -> OptimizeResult:
    """Phase 5.3 GA-Fallback: scipy.optimize.differential_evolution.

    Robuster als SLSQP gegen lokal-Minima und Konvergenz-Probleme bei
    nicht-glatten Objectives. Nachteile: 5-10x langsamer, kein Gradient-Use.

    Wir nutzen DE mit Penalty fuer Constraint-Verletzung (DE selbst hat
    keine native ineq-constraints in alten scipy-Versionen). Equality-
    Constraint sum=1 wird durch Renormalisation enforciert.

    seed wird durchgereicht fuer Reproduzierbarkeit.
    """
    sum_to_one_cons = next(
        (c for c in constraints if c["type"] == "eq"),
        None,
    )
    ineq_constraints = [c for c in constraints if c["type"] == "ineq"]

    def penalized_objective(w: np.ndarray) -> float:
        # Renormalize zu sum=1 (Equality enforcement)
        s = float(np.sum(w))
        if s > 1e-12:
            w = w / s
        # Bound clamping (DE hat boundary handling, aber doppelt sicher)
        lo = np.array([b[0] for b in bounds])
        hi = np.array([b[1] for b in bounds])
        w = np.clip(w, lo, hi)
        s = float(np.sum(w))
        if s > 1e-12:
            w = w / s
        # Base objective
        base = float(objective_fn(w))
        # Penalty fuer Inequality-Verletzungen
        penalty = 0.0
        for cons in ineq_constraints:
            val = float(cons["fun"](w))
            if val < 0:
                penalty += 1e9 * abs(val) ** 2  # quadratisch, gross genug zu dominieren
        return base + penalty

    try:
        result = differential_evolution(
            penalized_objective,
            bounds=bounds,
            seed=int(seed) & 0x7FFFFFFF,  # DE seed ist int32
            maxiter=max_iter,
            popsize=popsize,
            tol=1e-6,
            polish=False,  # SLSQP-Polish skip (haben wir schon versucht)
            disp=False,
        )
        # Manuelle Renormalization auf result.x
        x = np.asarray(result.x, dtype=np.float64)
        s = float(np.sum(x))
        if s > 1e-12:
            x = x / s
        result.x = x
        result.message = f"DE: {result.message}"
        return result
    except Exception as e:  # noqa: BLE001
        return OptimizeResult(
            x=np.array([(lo + hi) / 2.0 for lo, hi in bounds]),
            fun=float("inf"),
            success=False,
            status=99,
            message=f"DE-crash: {type(e).__name__}: {e}",
            nit=0,
        )


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
    client_birth_year: int | None = None,
    client_sex: str | None = None,
    use_mortality_simulation: bool = False,
) -> OptimizerResult:
    """Mulvey-Light SLSQP Optimizer.

    Returns OptimizerResult mit weights_bps + Audit-Trace.

    Bei Solver-Divergenz aller Multi-Starts: status='fallback_house_matrix'
    mit House-Matrix-Mid als weights (OWNER-DECISION OD-5).

    V3 Sprint 1b: Solver baut intern einen OptimizerContext und nutzt
    `_objective_from_array` als Closure. Nach finalem Rounding wird
    `objective_value` ueber `evaluate_weights` neu bestimmt, damit ein
    externer Aufruf von `evaluate_weights(ctx, result.weights_bps)` exakt
    den gleichen Wert liefert.
    """
    # ---- 1.-4. Context (Seed, Scenarios, Liabilities, Constraints) ----
    context = build_optimizer_context(
        cma=cma,
        goals=list(goals),
        house_matrix_row=house_matrix_row,
        score_x10=score_x10,
        advisory_wealth_rappen=advisory_wealth_rappen,
        cashflow_series_rappen=cashflow_series_rappen,
        horizon_years=horizon_years,
        n_paths=n_paths,
        seed=seed,
        inflation_series_bps=inflation_series_bps,
        risky_fraction_per_bucket=risky_fraction_per_bucket,
        client_birth_year=client_birth_year,
        client_sex=client_sex,
        use_mortality_simulation=use_mortality_simulation,
    )
    # Lokale Aliase fuer Lesbarkeit der bestehenden Logik unten
    seed = context.seed
    return_paths = context.return_paths
    liabilities = context.liabilities
    aggregated_liability = context.aggregated_liability_path
    bounds = context.bounds
    scipy_constraints = context.scipy_constraints

    # ---- 5. Objective Closure ueber den Context ----
    def objective_fn(w: np.ndarray) -> float:
        return _objective_from_array(context, w)

    # ---- 6. Multi-Start SLSQP ----
    initials = build_initial_guesses(bounds, score_x10)
    best_result: OptimizeResult | None = None
    best_obj = float("inf")
    total_iters = 0
    used_ga_fallback = False

    for x0 in initials:
        result = _solve_single_start(
            objective_fn, x0, bounds, scipy_constraints,
            max_iter=max_iter, ftol=ftol,
        )
        total_iters += int(getattr(result, "nit", 0) or 0)
        if result.success and result.fun < best_obj:
            best_obj = float(result.fun)
            best_result = result

    # ---- 6b. Phase 5.3 GA-Fallback wenn alle SLSQP-Starts divergiert ----
    if best_result is None:
        ga_result = _solve_via_genetic_algorithm(
            objective_fn, bounds, scipy_constraints, seed=seed,
        )
        total_iters += int(getattr(ga_result, "nit", 0) or 0)
        if ga_result.success and ga_result.fun < float("inf"):
            best_obj = float(ga_result.fun)
            best_result = ga_result
            used_ga_fallback = True

    # ---- 7. Status & Output ----
    if best_result is None:
        # Auch GA divergiert -> Fallback House-Matrix
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
                "Alle Solver-Multi-Starts divergierten und GA-Fallback ebenso. "
                "Fallback auf House-Matrix-Mittelwert (siehe OWNER-DECISION OD-5)."
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
    # V3 Sprint 1b: objective_value via Context-Path neu bestimmen, damit
    # `evaluate_weights(ctx, result.weights_bps).objective_value` exakt
    # `result.objective_value` matcht (post-rounding kongruent).
    post_round_objective = _objective_from_array(
        context, _weights_bps_to_array(weights_bps)
    )
    reasoning: list[str] = []
    method_used = "SLSQP+DE-Fallback" if used_ga_fallback else "SLSQP"
    reasoning.append(f"Stochastic Solver ({method_used}): {total_iters} iterations across "
                      f"{len(initials)} multi-starts.")
    reasoning.append(f"Best objective L(w*) = {post_round_objective:.6e}")
    if violation_reasons:
        reasoning.append("Constraint-Verletzungen am Optimum:")
        reasoning.extend(f"  - {r}" for r in violation_reasons)

    # Phase 5.2: Stress-Szenarien als Audit-Erweiterung. Berechnet die End-
    # Wealth in 3 historischen Krisen-Pfaden, damit der Berater sehen kann
    # wie die Allocation in 1929/2008/2020 abgeschnitten haette.
    stress_evals: dict[str, dict] | None = None
    try:
        from .stress_scenarios import (
            evaluate_stress_scenarios,
            stress_results_to_dict,
        )
        stress_results = evaluate_stress_scenarios(
            weights=final_w,
            initial_wealth_rappen=advisory_wealth_rappen,
            cashflow_series_rappen=list(cashflow_series_rappen),
            liability_path_rappen=aggregated_liability,
            horizon_years=horizon_years,
        )
        stress_evals = stress_results_to_dict(stress_results)
        for name, r in stress_results.items():
            reasoning.append(
                f"Stress '{name}': End-Vermoegen {r.end_wealth_rappen // 100:,} CHF, "
                f"Max Drawdown {r.max_drawdown_bps / 100:.1f}%."
            )
    except Exception as exc:  # noqa: BLE001
        # Stress-Eval ist nice-to-have - kein Solver-Crash deswegen
        reasoning.append(f"Stress-Auswertung fehlgeschlagen: {type(exc).__name__}")

    return OptimizerResult(
        weights_bps=weights_bps,
        objective_value=post_round_objective,
        iterations=total_iters,
        seed=seed,
        status=status,
        method="stochastic",
        constraint_violations=violation_reasons,
        reasoning=reasoning,
        n_paths=n_paths,
        n_starts_attempted=len(initials),
        stress_evaluations=stress_evals,
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
