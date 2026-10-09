"""Objective Functions + Goal-Drivers (V3 Sprint 1d).

Master-Spec: docs/planning/2026-05-05-stochastic-optimizer-spec.md (Sec 6)

All Rappen shortfalls entering the optimizer objective are divided by the
single context scale ``max(1, initial_wealth_rappen)`` before squaring. This
makes the primary term dimensionless while retaining absolute goal priority.

Primary Objective (Advisory-Methodik Slide 18, Priorität 1):
    L(w) = Σ_g h_g · w_g · (1/N) · Σ_n max(0, target_g - wealth_g(w, n))^2

Sekundaer (Priorität 2, wenn L ≈ 0):
    Var(w) = Var_n(W_T(w))

Hardness-Weights (OWNER-DECISION OD-1, vom User bestaetigt):
    hart: 10.0    primaer: 1.0    opportunistisch: 0.2

Pro Goal-Typ wird Shortfall anders berechnet:
- "wealth_at_t":      max(0, target - wealth[t])^2
- "cashflow_in_year": max(0, -wealth[t])^2 (Outflow ist bereits abgezogen)
- "outflow_stream":   max(0, -min_t wealth[t])^2 (jeder Outflow muss finanzierbar sein)
- "return_rate":      max(0, target_bps - annualized_return_bps)^2
- "maximize":         0  (kein Shortfall, nur in Vol-Min relevant)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from config import validate_goal_weighting_mode

from .goal_liabilities import GoalLiability


LAMBDA_CHANCE_DEFAULT = 1_000_000.0
TAU_UNREACHABLE = 0.50

# OWNER-DECISION OD-1 (bestaetigt 2026-05-05): 50x zwischen hart/opportunistisch.
# Im Optimizer brauchen wir staerkere Hardness-Trennung als in der reinen Score-
# Aggregation (_GOAL_HARDNESS_MULTIPLIER_BPS in portfolio_engine, Faktor 5x).
HARDNESS_WEIGHT = {
    "hart": 10.0,
    "primaer": 1.0,
    "opportunistisch": 0.2,
}

_PRIMARY_HARDNESS_KEYS = {"hart", "primaer", "primär"}


def resolve_goal_weighting_mode() -> str:
    """3eyes-Methodik (Q&A iSAA): 'Alle Ziele sind gleich wichtig (Mittelung)'.

    Default = 'equal' -> jedes Ziel geht mit Gewicht 1.0 in die Zielfunktion
    ein. Die Haertegrad-Gewichtung (hart 10x / primaer 1x / opportunistisch
    0.2x) bleibt als optionales Feature erhalten: OPTIMIZER_GOAL_WEIGHTING=hardness.

    CERT-OPTIMIZER-OBJECTIVE-001 / OPTIMIZER-GOAL-WEIGHTING-EVIDENCE-001: this
    used to normalize ANY unrecognized value (a typo, an empty string, ...)
    silently to "equal" -- indistinguishable from an unset variable, with no
    error and no evidence of the misconfiguration. It now delegates to the
    single centrally validated definition in config.validate_goal_weighting_mode,
    which raises ValueError fail-closed for anything other than "equal" or
    "hardness" (unset -> documented default "equal"). This is the one call
    site this module uses to resolve the mode; every objective/driver
    function below calls this function (directly or via
    _effective_hardness_weight), never os.environ, so there is a single
    source of truth for "which mathematics produced this run".

    This is intentionally still a live env read rather than a value frozen
    once at process start: a config change must take effect on the very
    next optimizer run without requiring a process restart. The remaining
    architectural gap -- binding the resolved mode into one immutable
    per-run ObjectiveContract so solver/reevaluation/driver/sensitivity/
    replay are provably congruent even if the environment changes mid-run
    -- is tracked as further work (see certification spec Sec. 6.2-6.3);
    this fix closes the "silent fallback" and "not hashed" gaps, not that
    larger contract-freeze gap.
    """
    return validate_goal_weighting_mode(os.environ.get("OPTIMIZER_GOAL_WEIGHTING"))


def _goal_weighting_mode() -> str:
    """Backwards-compatible internal alias for resolve_goal_weighting_mode()."""
    return resolve_goal_weighting_mode()


def _effective_hardness_weight(hardness_key: str | None) -> float:
    """Gibt den Haertegrad-Multiplikator nur im opt-in-Modus zurueck, sonst 1.0.

    So mittelt der Optimizer per Default alle Ziele gleich (Methodik-konform),
    ohne die Haertegrad-Logik zu verlieren.
    """
    if _goal_weighting_mode() == "hardness":
        return HARDNESS_WEIGHT.get(_hardness_key(hardness_key), 1.0)
    return 1.0


def _hardness_key(value: str | None) -> str:
    raw = str(value or "primaer").strip().lower()
    if raw in ("hart", "hard"):
        return "hart"
    if raw in ("primaer", "primär", "primary"):
        return "primaer"
    if raw in ("opportunistisch", "opportunistic", "opp"):
        return "opportunistisch"
    return raw or "primaer"


def _display_hardness(value: str | None) -> str:
    key = _hardness_key(value)
    if key == "primaer":
        return "primär"
    return key


def _default_tau_x100(liability: GoalLiability) -> int:
    raw = getattr(liability, "success_probability_min_x100", None)
    if raw is not None:
        try:
            return max(0, min(10000, int(raw)))
        except (TypeError, ValueError):
            pass
    if liability.target_kind == "return_rate":
        return 5000
    if liability.target_kind == "maximize":
        return 10000
    return 8000


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


def _context_scale_rappen(value: float) -> float:
    """Return the finite, positive common normalization scale."""
    raw = float(value)
    if not np.isfinite(raw):
        raise ValueError("initial_wealth_rappen must be finite")
    return max(1.0, raw)


def _squared_rappen_shortfall(
    shortfall_rappen: np.ndarray,
    *,
    normalization_scale_rappen: float | None,
) -> np.ndarray:
    """Square a Rappen shortfall after optional context normalization.

    ``None`` intentionally preserves the historic raw-rappen helper contract
    for direct callers. The optimizer objective and explainability path always
    pass the common context scale ``max(1, initial_wealth_rappen)``.
    """
    scale = (
        1.0
        if normalization_scale_rappen is None
        else _context_scale_rappen(normalization_scale_rappen)
    )
    relative_shortfall = np.asarray(shortfall_rappen, dtype=np.float64) / scale
    return relative_shortfall * relative_shortfall


def _positive_due_wealth_indices(
    liability: GoalLiability,
    *,
    n_wealth_columns: int,
) -> np.ndarray:
    """Map this goal's positive liability entries to wealth-path columns.

    ``liability_path_rappen[0]`` is paid in year one and is observed in
    ``wealth_paths[:, 1]``. Unrelated negative wealth before or after this
    goal's payment window must not make this goal fail.

    The supplied wealth path is aggregate across all goals. Exact causal
    attribution between simultaneous liabilities would require per-goal
    counterfactual wealth paths; this helper intentionally does not invent an
    ordering or allocation rule from the aggregate series.
    """
    indices = [
        path_index + 1
        for path_index, amount in enumerate(liability.liability_path_rappen or ())
        if float(amount or 0) > 0.0 and path_index + 1 < int(n_wealth_columns)
    ]
    return np.asarray(indices, dtype=np.intp)


def shortfall_squared_per_path(
    liability: GoalLiability,
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    horizon_years: int,
    annualized_return_bps_per_path: np.ndarray | None = None,
    normalization_scale_rappen: float | None = None,
) -> np.ndarray:
    """Liefert shortfall^2 pro Szenario-Pfad fuer ein Goal, shape (n_paths,).

    Wealth-Pfade kommen aus simulate_wealth_paths mit Liability bereits
    subtrahiert.

    Mit ``normalization_scale_rappen`` wird der Rappen-Fehlbetrag vor dem
    Quadrieren durch diese gemeinsame Context-Skala geteilt. ``None`` behaelt
    fuer direkte Diagnose-Caller den historischen Roh-Rappen-Wert bei.
    """
    n_paths = wealth_paths.shape[0]

    if liability.target_kind == "maximize":
        return np.zeros(n_paths, dtype=np.float64)

    if liability.target_kind == "return_rate":
        # #2 (2026-06-12): einheitenkonsistenter Shortfall in Rappen statt bps².
        # Vorher: max(0, target_bps - annualized_bps)² in bps² (~1e4-1e8) — ging
        # in gemischten Goal-Sets gegen Wealth-Ziele (Rappen²~1e16) unter, das
        # Renditeziel war im primaeren SLSQP-Objective faktisch unsichtbar.
        # Fix: impliziertes Wealth-Target = initial·(1+r)^h (Spec §4.1: annualized
        # >= target  <=>  end_wealth >= initial·(1+target)^h). IDENTISCH zu
        # goal_probability_per_path -> primaeres Objective & Chance-Constraint
        # (P-Ampel) nutzen jetzt dieselbe Renditeziel-Definition.
        horizon = max(1, min(
            int(liability.target_year_index or (wealth_paths.shape[1] - 1)),
            wealth_paths.shape[1] - 1,
        ))
        target_return = float(liability.target_amount_rappen) / 10000.0
        target_wealth = max(1.0, float(initial_wealth_rappen)) * ((1.0 + target_return) ** horizon)
        if annualized_return_bps_per_path is None:
            comparison_wealth = wealth_paths[:, horizon]
        else:
            twr = np.asarray(
                annualized_return_bps_per_path, dtype=np.float64
            ).reshape(-1)
            if twr.shape != (n_paths,):
                raise ValueError(
                    "annualized_return_bps_per_path must match n_paths "
                    f"({twr.shape} != {(n_paths,)})"
                )
            comparison_wealth = max(1.0, float(initial_wealth_rappen)) * np.power(
                np.maximum(0.0, 1.0 + twr / 10000.0), horizon
            )
        shortfall = np.maximum(0.0, target_wealth - comparison_wealth)
        return _squared_rappen_shortfall(
            shortfall,
            normalization_scale_rappen=normalization_scale_rappen,
        )

    if liability.target_kind == "wealth_at_t":
        target = float(liability.target_amount_rappen)
        idx = max(1, min(int(liability.target_year_index), wealth_paths.shape[1] - 1))
        wealth_at_t = wealth_paths[:, idx]
        shortfall = np.maximum(0.0, target - wealth_at_t)
        return _squared_rappen_shortfall(
            shortfall,
            normalization_scale_rappen=normalization_scale_rappen,
        )

    if liability.target_kind == "cashflow_in_year":
        # The one-off expense is already part of liability_path and therefore
        # already subtracted in the simulated wealth at T. Requiring the same
        # amount again here would double-count the goal.
        due_indices = _positive_due_wealth_indices(
            liability,
            n_wealth_columns=wealth_paths.shape[1],
        )
        if due_indices.size == 0:
            return np.zeros(n_paths, dtype=np.float64)
        minimum_due_wealth = np.min(wealth_paths[:, due_indices], axis=1)
        shortfall = np.maximum(0.0, -minimum_due_wealth)
        return _squared_rappen_shortfall(
            shortfall,
            normalization_scale_rappen=normalization_scale_rappen,
        )

    if liability.target_kind == "outflow_stream":
        # Every scheduled payment must be fundable when due. Looking only at
        # terminal wealth can hide an interim funding gap that a later inflow
        # happens to repair.
        due_indices = _positive_due_wealth_indices(
            liability,
            n_wealth_columns=wealth_paths.shape[1],
        )
        if due_indices.size == 0:
            return np.zeros(n_paths, dtype=np.float64)
        minimum_due_wealth = np.min(wealth_paths[:, due_indices], axis=1)
        shortfall = np.maximum(0.0, -minimum_due_wealth)
        return _squared_rappen_shortfall(
            shortfall,
            normalization_scale_rappen=normalization_scale_rappen,
        )

    return np.zeros(n_paths, dtype=np.float64)


def _priority_protected_wealth_paths(
    wealth_paths: np.ndarray,
    goal: GoalLiability,
) -> tuple[np.ndarray, bool]:
    """Reconstruct `goal`'s priority-protected wealth trajectory.

    GOAL-FUNDING-PRIORITY-001 (CERT-GOAL-FUNDING-001), Spec Sec. 4.2: a goal
    with rank ``r`` must be evaluated on the cumulative scope
    ``S_r = {h | rank(h) <= r}``, not on the unprotected joint aggregate of
    every requested goal. ``goals_to_liabilities()`` precomputes, for every
    goal in a batch, ``priority_scope_liability_path_rappen`` (the scope-r
    cumulative outflow) and ``joint_liability_path_rappen`` (the full
    unprotected aggregate -- what actually produced the given
    ``wealth_paths``).

    When both are present and differ, this derives the per-path, per-year
    growth factor directly from the already-realized joint trajectory
    (``simulate_wealth_paths`` applies growth before subtracting the
    liability for that year) and re-applies that SAME realized growth to the
    scope-protected liability path instead. This is mathematically identical
    to re-running ``simulate_wealth_paths`` on the same scenario cube with a
    different liability path (common random numbers, Hard Invariant #3) as
    long as liability subtraction does not itself feed back into growth
    (true when ``tax_regime`` is inactive; a known approximation otherwise,
    see PR description). It is NOT path-wise lookahead: every return used
    here already happened in the given ``wealth_paths``; no later year's
    return is consulted to decide an earlier year's funding order.

    Returns (wealth_paths_or_reconstruction, was_reconstructed).
    """
    scope_path = goal.priority_scope_liability_path_rappen
    joint_path = goal.joint_liability_path_rappen
    if not scope_path or not joint_path or list(scope_path) == list(joint_path):
        return wealth_paths, False

    n_cols = wealth_paths.shape[1]
    horizon = n_cols - 1
    protected = np.array(wealth_paths, dtype=np.float64, copy=True)
    prev_joint = wealth_paths[:, 0]
    prev_protected = protected[:, 0]
    for t in range(horizon):
        joint_next = wealth_paths[:, t + 1]
        joint_liab_t = float(joint_path[t]) if t < len(joint_path) else 0.0
        scope_liab_t = float(scope_path[t]) if t < len(scope_path) else 0.0
        pre_liability_joint = joint_next + joint_liab_t
        with np.errstate(divide="ignore", invalid="ignore"):
            growth_factor = np.where(
                prev_joint != 0.0, pre_liability_joint / prev_joint, 1.0
            )
        protected_next = prev_protected * growth_factor - scope_liab_t
        protected[:, t + 1] = protected_next
        prev_joint = joint_next
        prev_protected = protected_next
    return protected, True


def _goal_probability_core(
    wealth_paths: np.ndarray,
    goal: GoalLiability,
    initial_value_rappen: int,
    annualized_return_bps_per_path: np.ndarray | None = None,
) -> np.ndarray:
    """Returns an int array with 1 where the goal is achieved, else 0.

    Pure function of the GIVEN wealth_paths (no priority-scope
    reconstruction) -- used internally wherever the deliberately unprotected
    joint-requested-plan view is required (``chance_constraint_penalty``).
    """
    n_paths = wealth_paths.shape[0]
    if n_paths <= 0:
        return np.zeros(0, dtype=np.int8)
    if goal.target_kind == "maximize":
        return np.ones(n_paths, dtype=np.int8)
    if goal.target_kind == "wealth_at_t":
        idx = max(1, min(int(goal.target_year_index), wealth_paths.shape[1] - 1))
        target = float(goal.target_amount_rappen or 0)
        return (wealth_paths[:, idx] >= target).astype(np.int8)
    if goal.target_kind == "cashflow_in_year":
        due_indices = _positive_due_wealth_indices(
            goal,
            n_wealth_columns=wealth_paths.shape[1],
        )
        if due_indices.size == 0:
            return np.ones(n_paths, dtype=np.int8)
        return np.all(wealth_paths[:, due_indices] >= 0, axis=1).astype(np.int8)
    if goal.target_kind == "outflow_stream":
        due_indices = _positive_due_wealth_indices(
            goal,
            n_wealth_columns=wealth_paths.shape[1],
        )
        if due_indices.size == 0:
            return np.ones(n_paths, dtype=np.int8)
        return np.all(wealth_paths[:, due_indices] >= 0, axis=1).astype(np.int8)
    if goal.target_kind == "return_rate":
        if annualized_return_bps_per_path is not None:
            twr = np.asarray(
                annualized_return_bps_per_path, dtype=np.float64
            ).reshape(-1)
            if twr.shape != (n_paths,):
                raise ValueError(
                    "annualized_return_bps_per_path must match n_paths "
                    f"({twr.shape} != {(n_paths,)})"
                )
            return (
                twr >= float(goal.target_amount_rappen or 0)
            ).astype(np.int8)
        horizon = max(1, min(int(goal.target_year_index or (wealth_paths.shape[1] - 1)), wealth_paths.shape[1] - 1))
        target_return = float(goal.target_amount_rappen or 0) / 10000.0
        target_wealth = float(max(1, int(initial_value_rappen or 0))) * ((1.0 + target_return) ** horizon)
        return (wealth_paths[:, horizon] >= target_wealth).astype(np.int8)
    return np.ones(n_paths, dtype=np.int8)


def goal_probability_per_path(
    wealth_paths: np.ndarray,
    goal: GoalLiability,
    initial_value_rappen: int,
    annualized_return_bps_per_path: np.ndarray | None = None,
) -> np.ndarray:
    """Returns an int array with 1 where the goal is achieved, else 0.

    GOAL-FUNDING-PRIORITY-001: when `goal` carries priority-scope evidence
    (built via ``goals_to_liabilities()``), the goal is evaluated on its own
    priority-protected wealth trajectory (Spec Sec. 4.2 ``P_protected(g)``),
    not on the raw ``wealth_paths`` the caller supplies -- a lower-priority
    (higher-rank) goal's outflow must not be able to drag a higher-priority
    goal's achievability below what it would have been without it. Callers
    that deliberately want the unprotected joint-requested-plan view (e.g.
    ``chance_constraint_penalty`` below) use ``_goal_probability_core``
    directly instead of this public wrapper.
    """
    protected_wealth_paths, reconstructed = _priority_protected_wealth_paths(
        wealth_paths, goal
    )
    effective_twr = None if reconstructed else annualized_return_bps_per_path
    return _goal_probability_core(
        protected_wealth_paths,
        goal,
        initial_value_rappen,
        annualized_return_bps_per_path=effective_twr,
    )


def chance_constraint_penalty(
    wealth_paths: np.ndarray,
    goal_liabilities: list[GoalLiability],
    initial_value_rappen: int,
    lambda_chance: float = LAMBDA_CHANCE_DEFAULT,
    *,
    weights: np.ndarray | None = None,
    annualized_return_bps_per_path: np.ndarray | None = None,
) -> tuple[float, list[dict]]:
    """Return chance-constraint penalty and per-goal achievability rows.

    Parameters
    ----------
    weights : np.ndarray | None
        Sprint P1 (2026-06-06): Optional Likelihood-Ratio-Weights aus
        Importance Sampling. Wenn None: uniform sample-mean P(success).
        Wenn gesetzt: weighted estimator
        P_weighted = Sum(per_path * w) / Sum(w).

        WICHTIG: ohne diesen Parameter wuerde IS einen verzerrten
        Probability-Estimator liefern (alle Pfade aus shifted distribution
        gleich gewichtet) — die PDF-Achievability-Rows waeren falsch.
    """
    penalty = 0.0
    achievability: list[dict] = []
    if weights is not None:
        weights_arr = np.asarray(weights, dtype=np.float64).reshape(-1)
        if weights_arr.shape[0] != wealth_paths.shape[0]:
            raise ValueError(
                f"weights.shape[0]={weights_arr.shape[0]} != n_paths={wealth_paths.shape[0]}"
            )
        weight_sum = float(np.sum(weights_arr))
        if weight_sum <= 0:
            raise ValueError("Sum-of-weights must be > 0")
    else:
        weights_arr = None
        weight_sum = None
    for goal in goal_liabilities:
        # Deliberately the UNPROTECTED joint-requested-plan view (Spec Sec.
        # 4.2 `W_joint_requested`/`P_joint_requested`): this aggregator must
        # keep publishing today's shared-aggregate achievability so existing
        # callers (and the chance-constraint term feeding the SLSQP
        # objective) are unaffected by GOAL-FUNDING-PRIORITY-001's fix. The
        # priority-protected per-goal view lives in the public
        # `goal_probability_per_path()` above; a future solver-level Scope
        # evaluator (Spec Phase B/C) is expected to call that directly per
        # rank-ordered scope rather than through this joint aggregator.
        per_path = _goal_probability_core(
            wealth_paths,
            goal,
            initial_value_rappen,
            annualized_return_bps_per_path=annualized_return_bps_per_path,
        )
        if per_path.size == 0:
            probability = 0.0
        elif weights_arr is None:
            probability = float(np.mean(per_path))
        else:
            probability = float(np.sum(per_path.astype(np.float64) * weights_arr) / weight_sum)
        tau = _default_tau_x100(goal) / 10000.0
        if probability >= tau:
            status = "erreichbar"
        elif probability >= TAU_UNREACHABLE:
            status = "knapp"
        else:
            status = "nicht_erreichbar"
        hardness = _hardness_key(getattr(goal, "hardness_key", None))
        applies_penalty = hardness in _PRIMARY_HARDNESS_KEYS and goal.target_kind != "maximize"
        if applies_penalty:
            shortfall = max(0.0, tau - probability)
            penalty += float(lambda_chance) * shortfall * shortfall
        achievability.append({
            "goal_id": str(goal.goal_id),
            "label": str(goal.label),
            "target_kind": str(goal.target_kind),
            "probability": probability,
            "tau": tau,
            "status": status,
            "hardness": _display_hardness(hardness),
        })
    return float(penalty), achievability


def shortfall_objective(
    liabilities: Iterable[GoalLiability],
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    horizon_years: int,
    weights: np.ndarray | None = None,
    annualized_return_bps_per_path: np.ndarray | None = None,
) -> float:
    """Primaere Objective L(w): gewichteter dimensionsloser MSE-Shortfall.

    Jeder Rappen-Fehlbetrag wird vor dem Quadrieren durch die gemeinsame
    Context-Skala ``max(1, initial_wealth_rappen)`` geteilt. Damit bleibt die
    absolute Rangfolge der Fehlbetraege sowie die Hardness-/Goal-Gewichtung
    erhalten, waehrend Primary- und Chance-Terme einheitenfrei sind.

    L(w) = Σ_g h_g · g_g · mean_n(shortfall(g, n)^2)

    h_g = _effective_hardness_weight(hardness_key)
          → Default 1.0 (alle Ziele gleich, Methodik-konform);
            HARDNESS_WEIGHT nur bei OPTIMIZER_GOAL_WEIGHTING=hardness.
    g_g = liability.weight_bps / 10000

    Skalar-Output, von scipy.optimize.minimize konsumierbar.

    Parameters
    ----------
    weights : np.ndarray | None
        Optional. Shape (n_paths,). Likelihood-Ratio-Weights aus
        Importance Sampling (services/optimizer/importance_sampling.py).
        Wenn None: trivialer sample-mean (alle Pfade gleich gewichtet).
        Wenn gesetzt: weighted mean = Σ (per_path · w) / Σ w.

        Phase 5c — Mathematik-Backbone fuer IS-faehigen Solver-Pfad.
        Backwards-Compat: bei weights=None identisch zu vorher.
    """
    total = 0.0
    n_paths = wealth_paths.shape[0]
    if n_paths <= 0:
        return 0.0
    context_scale_rappen = _context_scale_rappen(initial_wealth_rappen)
    # Normalisierung: bei weights=None → uniform; sonst weighted (NOT mean von w,
    # sondern Sum(per_path · w) / Sum(w) als unverzerrter Estimator).
    if weights is None:
        inv_n = 1.0 / n_paths
        weight_sum = None
    else:
        weights_arr = np.asarray(weights, dtype=np.float64).reshape(-1)
        if weights_arr.shape[0] != n_paths:
            raise ValueError(
                f"weights.shape[0]={weights_arr.shape[0]} != n_paths={n_paths}"
            )
        weight_sum = float(np.sum(weights_arr))
        if weight_sum <= 0:
            raise ValueError("Sum-of-weights must be > 0")
    for liab in liabilities:
        h_weight = _effective_hardness_weight(liab.hardness_key)
        g_weight = max(1, int(liab.weight_bps)) / 10000.0
        per_path = shortfall_squared_per_path(
            liab, wealth_paths,
            initial_wealth_rappen=initial_wealth_rappen,
            horizon_years=horizon_years,
            annualized_return_bps_per_path=annualized_return_bps_per_path,
            normalization_scale_rappen=context_scale_rappen,
        )
        if weights is None:
            mean_sq = float(np.sum(per_path) * inv_n)
        else:
            mean_sq = float(np.sum(per_path * weights_arr) / weight_sum)
        total += h_weight * g_weight * mean_sq
    return total


def volatility_objective(
    wealth_paths: np.ndarray,
    *,
    weights: np.ndarray | None = None,
) -> float:
    """Sekundaere Objective: Varianz des End-Wealth ueber Pfade.

    Wird genutzt wenn die primary objective bereits ~0 ist und wir auf
    minimale Volatilitaet optimieren wollen (Slide 18 Priorität 2).

    Parameters
    ----------
    weights : np.ndarray | None
        Optional Likelihood-Ratios (Phase 5c). Bei None: trivial np.var.
        Bei gesetzt: weighted variance = Σ w·(x-E_w[x])² / Σ w
        (Estimator fuer Var unter Ziel-Verteilung wenn weights die
        Likelihood-Ratios sind).
    """
    end_wealth = wealth_paths[:, -1]
    if weights is None:
        return float(np.var(end_wealth))
    weights_arr = np.asarray(weights, dtype=np.float64).reshape(-1)
    if weights_arr.shape[0] != end_wealth.shape[0]:
        raise ValueError(
            f"weights.shape[0]={weights_arr.shape[0]} != n_paths={end_wealth.shape[0]}"
        )
    weight_sum = float(np.sum(weights_arr))
    if weight_sum <= 0:
        raise ValueError("Sum-of-weights must be > 0")
    weighted_mean = float(np.sum(end_wealth * weights_arr) / weight_sum)
    deviations = end_wealth - weighted_mean
    return float(np.sum(weights_arr * deviations * deviations) / weight_sum)


# ============================================================================
# V3 Sprint 1d (Plan §5.4): Goal-Driver Erklaerbarkeit
# ============================================================================


@dataclass(frozen=True)
class GoalShortfallContribution:
    """Beitrag eines einzelnen Goals zum Gesamt-Shortfall-Objective.

    Objective-Beitraege sind dimensionslos: jeder Rappen-Fehlbetrag wird vor
    dem Quadrieren mit derselben Initialvermoegens-Skala normalisiert.

    'Contribution under aggregate wealth path' (Plan §5.4):
        contribution = h_g · g_g · mean_n(shortfall(g, n)^2)
    Das ist NICHT eine teure marginale Counterfactual-Berechnung
    ('Objective ohne dieses Goal') — sondern der direkte Beitrag, den dieses
    Goal in der gemeinsam evaluierten Summe ausmacht. Sortierung absteigend
    macht 'welches Ziel dominiert den Shortfall' fuer den Berater sichtbar.

    weighted_objective_contribution: float
        Direkt vergleichbar mit dem Output von shortfall_objective() — die
        Summe aller GoalShortfallContribution.weighted_objective_contribution
        ergibt L(w).
    """
    goal_id: str
    label: str
    target_kind: str
    hardness_key: str
    weight_bps: int
    mean_shortfall_squared: float
    weighted_objective_contribution: float


def shortfall_contributions(
    liabilities: Iterable[GoalLiability],
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    horizon_years: int,
    annualized_return_bps_per_path: np.ndarray | None = None,
) -> list[GoalShortfallContribution]:
    """Pro Goal: Mean-Shortfall² und gewichteter Beitrag zum Objective.

    Sortiert absteigend nach weighted_objective_contribution: das groesste
    Risiko zuerst. Wenn n_paths == 0, leere Liste.
    """
    rows: list[GoalShortfallContribution] = []
    if wealth_paths.size == 0:
        return rows
    n_paths = wealth_paths.shape[0]
    if n_paths <= 0:
        return rows
    context_scale_rappen = _context_scale_rappen(initial_wealth_rappen)
    inv_n = 1.0 / n_paths
    for liab in liabilities:
        per_path = shortfall_squared_per_path(
            liab,
            wealth_paths,
            initial_wealth_rappen=initial_wealth_rappen,
            horizon_years=horizon_years,
            annualized_return_bps_per_path=annualized_return_bps_per_path,
            normalization_scale_rappen=context_scale_rappen,
        )
        mean_sq = float(np.sum(per_path) * inv_n)
        h_weight = _effective_hardness_weight(liab.hardness_key)
        g_weight = max(1, int(liab.weight_bps)) / 10000.0
        rows.append(GoalShortfallContribution(
            goal_id=str(liab.goal_id),
            label=str(liab.label),
            target_kind=str(liab.target_kind),
            hardness_key=str(liab.hardness_key),
            weight_bps=int(liab.weight_bps),
            mean_shortfall_squared=mean_sq,
            weighted_objective_contribution=float(h_weight * g_weight * mean_sq),
        ))
    return sorted(rows, key=lambda row: row.weighted_objective_contribution, reverse=True)


def combined_objective_two_phase(
    liabilities: Iterable[GoalLiability],
    wealth_paths: np.ndarray,
    *,
    initial_wealth_rappen: float,
    horizon_years: int,
    primary_weight: float = 1.0,
    volatility_weight: float = 1e-12,
    lambda_chance: float = LAMBDA_CHANCE_DEFAULT,
    epsilon: float = 1e-12,
    weights: np.ndarray | None = None,
    annualized_return_bps_per_path: np.ndarray | None = None,
) -> float:
    """Kombination Primary + tiny Volatility-Term.

    Nuetzlich als single-phase Approximation: L(w) + ε · Var(w). Wenn
    Goals erfuellt sind oder keine Goals existieren, dominiert der vol-Term
    und der Solver minimiert die Varianz des terminalen Vermoegens. Sonst
    dominiert Primary. Vorteil: nur ein Solve-Run, kein 2-Phase Switch.

    primary_weight: skaliert das dimensionslose L(w)
    volatility_weight: typischerweise 1e-12 weil Var(wealth) in rappen^2 sehr gross ist
    epsilon: numerische Nulltoleranz fuer den Phase-2-Switch; 1e-12 verhindert
             nach der Dimensionsnormalisierung ein vorzeitiges Umschalten.
    """
    liability_list = list(liabilities)
    primary = shortfall_objective(
        liability_list, wealth_paths,
        initial_wealth_rappen=initial_wealth_rappen,
        horizon_years=horizon_years,
        weights=weights,
        annualized_return_bps_per_path=annualized_return_bps_per_path,
    )
    chance, _achievability = chance_constraint_penalty(
        wealth_paths,
        liability_list,
        int(initial_wealth_rappen),
        lambda_chance=lambda_chance,
        # OPT-1: weights MUSS auch in die Chance-Penalty fliessen. shortfall_ und
        # volatility_objective bekommen sie bereits; ohne sie schätzt die Penalty
        # P(success) als uniformes Sample-Mean über IS-geshiftete Pfade -> verzerrt
        # -> falsche Strafterme -> falsch gewichtete Optimierung. Konsistent mit
        # _objective_from_array/evaluate_weights (solver.py), die weights setzen.
        weights=weights,
        annualized_return_bps_per_path=annualized_return_bps_per_path,
    )
    vol = volatility_objective(wealth_paths, weights=weights) if primary + chance < float(epsilon) else 0.0
    return primary_weight * primary + chance + volatility_weight * vol
