"""SLSQP-Solver mit Multi-Start fuer den Stochastic Optimizer.

Master-Spec: docs/planning/2026-05-05-stochastic-optimizer-spec.md (Sec 8)

Workflow:
1. Compute deterministic seed aus (mandate, cma, goals, score) - reproduzierbar
2. Build scenario paths (NumPy vektorisiert, Cornish-Fisher fat-tails)
3. Convert goals -> liabilities + aggregate liability path
4. Setup constraints aus House-Matrix + globale Caps
5. Multi-Start: 3-5 Initial-Allocations (House-Matrix-Mid, Conservative,
   Aggressive, Risky-Fraction-Edge, gleichverteilt) + optional PAR-5:
   ein zusaetzlicher Markowitz-Min-Varianz-Kandidat aus der CMA (additiv,
   siehe build_initial_guesses/_markowitz_min_variance_candidate)
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
import json
import math
import time
from collections.abc import Mapping
from datetime import date
from copy import deepcopy
from dataclasses import dataclass, field, replace
from numbers import Integral
from typing import Iterable

import numpy as np
from scipy.optimize import OptimizeResult, differential_evolution, minimize

from services.return_moments import ReturnMomentError

from .allocation_intent import (
    SOFT_PREFERENCE_PENALTY_LAMBDA_DEFAULT,
    SOFT_PREFERENCE_POLICY_VERSION,
    preference_deviation_bps,
    preference_loss_from_array,
)
from .constraints import (
    DEFAULT_BUCKET_RISKY_FRACTION,
    HouseMatrixBands,
    OptimizerInputError,
    bands_from_effective_bounds_bps,
    bands_from_house_matrix_row,
    bounds_collapse_warnings,
    build_bounds,
    build_constraint_set,
    is_feasible,
    validate_risky_fraction_per_bucket,
)
from .goal_liabilities import (
    GoalLiability,
    aggregate_liability_path,
    goals_to_liabilities,
)
from .drawdown_certification import (
    certify_drawdown_candidates,
    certify_resampled_candidates,
    drawdown_certification_reasoning,
    refined_primary_per_path,
)
from .goal_attribution import publish_goal_achievability
from .house_prior import (
    DECISION_HOUSE_PRIOR,
    DECISION_HOUSE_PRIOR_FAIL_CLOSED,
    DECISION_HOUSE_PRIOR_GUARD,
    HOUSE_ANCHOR_NUMERICAL_TOLERANCE_BPS,
    HOUSE_PRIOR_KAPPA,
    HOUSE_PRIOR_VERSION,
    REASON_GUARD,
    REASON_IDENTICAL,
    REASON_WITHIN_TOLERANCE,
    REASON_NO_VALIDATION,
    REASON_NOT_WORSE,
    REASON_TEST_DISABLED,
    goal_probability_rows,
    house_prior_penalty,
    house_prior_sentence,
    paired_bootstrap_disclosure,
    prior_metric_audit,
    tracking_error_bps,
)
from .objective import (
    GOAL_EROSION_NUMERIC_TOL,
    GOAL_EROSION_Z,
    GOAL_HIERARCHY_POLICY_VERSION,
    chance_constraint_penalty,
    _goal_hardness_weight,
    is_protected_goal,
    monte_carlo_standard_error,
    protected_goal_level,
    protected_goal_level_surrogate,
    combined_objective_two_phase,
    portfolio_variance_one_year,
    two_phase_objective_parts,
)
from .objective_contract import (
    ObjectiveContractV1,
    objective_contract_of,
    resolve_objective_contract,
)
from .objective_variants import (
    OBJECTIVE_GOAL_SHORTFALL,
    OBJECTIVE_MAX_DRAWDOWN,
    ObjectiveDomainError,
    primary_objective,
    refined_drawdown_check_for_winner,
)
from .resampling import (
    COMPARISON_GOAL_LEVEL,
    COMPARISON_RISK_MEASURE,
    DEFAULT_RESAMPLING,
    RISK_MEASURE_MATERIALITY,
    MIN_SUCCESSFUL_BAG_SHARE,
    MISSINGNESS_STRESS_SIGMAS,
    RESAMPLING_SCHEME_VERSION,
    ResamplingConfig,
    _domain_seed,
    bag_seeds,
    bootstrap_seed,
    build_bag_paths,
    paired_bootstrap_improvement,
)
from .scenario_engine import (
    SAMPLING_UNIT_ANTITHETIC_PAIR,
    SAMPLING_UNIT_PATH,
    sampling_unit_ids as scenario_sampling_unit_ids,
)
from .scenario_cache import (
    build_scenario_paths_cached,
    build_scenario_paths_with_weights_cached,
    scenario_inputs_digest,
    scenario_inputs_seed_digest,
)
from .goal_reachability import (
    annotate_rows as annotate_reachability_rows,
    goal_reachability_screen,
    reachability_reasoning,
)
from .importance_sampling import (
    IS_DEFENSIVE_MIXTURE_ALPHA,
    IS_ESS_FALLBACK_FRACTION,
    IS_SCHEME_VERSION,
    IS_TOTAL_SHIFT_SIGMA,
    build_shift_vector,
    decide_is_for_context,
    ess_requires_fallback,
    importance_sampling_diagnostics,
    make_default_weights,
)
from .scenario_engine import (
    BUCKET_ORDER,
    N_BUCKETS,
    ScenarioInputs,
    build_scenario_paths,
    scenario_inputs_from_cma,
    simulate_wealth_paths,
)


_ROBUSTIFIED_OBJECTIVE_TIE_REL_TOL = 0.05
_ROBUSTIFIED_DERISK_REL_TOL = 0.10

# SOLVER-CANDIDATE-ACCEPTANCE-001 (Kontrollrunde 2026-09-28): wie eng ein roher
# Non-success-SciPy-Kandidat schon VOR jeder Reparatur an sum=1/Bounds liegen
# muss, damit er als legitimer "SLSQP meldet faelschlich success=False"-
# Grenzfall gilt. 1e-3 deckt echtes numerisches Rauschen (SLSQP-ftol-Bereich)
# ab, verwirft aber grob infeasible Rohausgaben (z.B. x=[2,2,2,2,2]), die erst
# durch Clip+Renormierung zufaellig "feasible" wuerden.
_RAW_CANDIDATE_REPAIR_TOL = 1e-3


class SolverTechnicalError(RuntimeError):
    """Explicitly classified technical failure of the numerical solver.

    Only this exception (plus narrowly defined NumPy/floating-point errors)
    may activate the audited House-Matrix safety net at the production
    boundary. Domain/input errors and ordinary programming exceptions must
    remain visible and fail closed.
    """


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
    status: str  # "converged" | "converged_robustified" | "diverged" | "diverged_infeasible" | "fallback_house_matrix"
    method: str  # "stochastic" | "fallback_house_matrix"
    constraint_violations: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    n_paths: int = 0
    n_starts_attempted: int = 0
    stress_evaluations: dict[str, dict] | None = None
    goal_achievability: tuple[dict, ...] = ()
    robustification: dict[str, object] | None = None
    restart_results: tuple[dict, ...] = ()
    # CERT-ALLOCATION-INTENT-001: per-bucket (effective - preferred) deviation
    # in bps, populated only when the run had an explicit Soft-Preference
    # Target Intent (see OptimizerContext.preferred_target_bps). None means
    # "no Target Intent was given", not "0 deviation".
    preference_deviation_bps: dict[str, int] | None = None
    # OPTIMIZER-POST-SELECTION-CERTIFICATION-001 (2026-10-10): Anker der
    # unabhaengigen Validierungsstichprobe, auf der `goal_achievability`
    # nachzertifiziert wurde. None bedeutet "nicht unabhaengig validiert"
    # (z.B. weil keine ScenarioInputs im Context vorlagen) -- dann bleibt das
    # reliability_verdict der Rows bei `unvalidated_single_cube`.
    validation_seed: int | None = None
    validation_cube_hash: str | None = None
    validation_n_paths: int | None = None
    # SAA-RESAMPLED-STABILITY-001: Audit des Resamplings (Bags, Streuung je
    # Bucket, Projektion, Signifikanztest gegen die Hausmatrix, Entscheid).
    # None nur im Einzelwuerfel-Altpfad (ResamplingConfig mit n_bags <= 1).
    resampling: dict | None = None
    # OPTIMIZER-DRAWDOWN-CERTIFICATION-001 (2026-10-14): Audit des
    # Drawdown-Reranks ALLER zulaessigen Finalisten auf dem Validierungs-Cube
    # (nur Modus max_drawdown; sonst None). Siehe
    # services/optimizer/drawdown_certification.py.
    drawdown_certification: dict | None = None
    # IMPORTANCE-SAMPLING-ESS-001: Audit des Importance Samplings des
    # Hauptwuerfels (siehe OptimizerContext.importance_sampling_audit).
    importance_sampling: dict | None = None
    # GOAL-REACHABILITY-SCREEN-001: Pruefung, ob jedes Ziel auf IRGENDEINER
    # zulaessigen Allokation erreichbar ist (siehe
    # OptimizerContext.goal_reachability).
    goal_reachability: dict | None = None
    # Exact owned run-context snapshot used by the solver. compare=False is
    # essential because OptimizerContext contains NumPy arrays whose equality
    # is not scalar-valued. The context is intentionally not persisted as JSON;
    # callers reuse it in-process for congruent metrics/explainability.
    context: OptimizerContext | None = field(default=None, repr=False, compare=False)


# ============================================================================
# V3 Sprint 1b (2026-05-08): OptimizerContext + Evaluation
#
# Plan §5.2: Wiederverwendbare Evaluation beliebiger Gewichtungen unter
# denselben Szenarien, damit House-Matrix und Solver-Vorschlag Apples-to-
# Apples bewertet werden koennen.
# ============================================================================


# OPTIMIZER-POST-SELECTION-CERTIFICATION-001 (2026-10-10)
#
# Grosse Primzahl als Seed-Offset fuer den Validierungs-Cube. Eine Primzahl
# weit weg von kleinen Vielfachen haelt den PCG64-Stream des
# Validierungs-Cubes unabhaengig vom Trainings-Stream; ein Offset von z.B. 1
# oder 2 wuerde bei benachbarten Mandats-Seeds Ueberlappungen riskieren.
VALIDATION_SEED_OFFSET = 1_000_003

# DRAWDOWN-HOLDOUT-REUSE-001 (Engine saa_resampled_v7): Drei-Rollen-Architektur.
#
#   Training/Bag-Wuerfel  -> Kandidatenerzeugung
#   Auswahl-Wuerfel       -> genau einen Challenger einfrieren (nur Rerank)
#   finaler Holdout       -> Challenger vs. Anker + Zielerreichung, KEINE
#                            weitere Auswahl
#
# Der finale Holdout behaelt den bisherigen Seed (Inhalts-Seed +
# VALIDATION_SEED_OFFSET); der Auswahl-Wuerfel ist domaenensepariert aus dem
# Inhalts-Seed abgeleitet (SHA-256, wie die Bag-Seeds) -- er kann weder mit
# dem Holdout noch mit einem Bag zusammenfallen. Weitere Konsumenten (z.B.
# ein Screen vor der Optimierung) bekommen eine EIGENE Rolle statt einen der
# beiden Wuerfel mitzubenutzen.
CUBE_ROLE_FINAL = "final_certification"
CUBE_ROLE_SELECTION = "selection"
CUBE_ROLE_REACHABILITY_SCREEN = "reachability_screen"
_CUBE_ROLE_SEED_DOMAINS = {
    CUBE_ROLE_SELECTION: "saa-validation-selection-v1",
    CUBE_ROLE_REACHABILITY_SCREEN: "saa-validation-reachability-screen-v1",
}
# Validierungswuerfel sind immer antithetisch (kein Importance Sampling).
# Einzige Quelle fuer Bau UND Stichprobeneinheit des Bootstraps
# (RESAMPLING-ANTITHETIC-BOOTSTRAP-001).
VALIDATION_CUBE_ANTITHETIC = True


def _validation_seed_for_role(content_seed: int, role: str) -> int:
    if role == CUBE_ROLE_FINAL:
        return int(content_seed) + VALIDATION_SEED_OFFSET
    try:
        domain = _CUBE_ROLE_SEED_DOMAINS[role]
    except KeyError as exc:
        raise ValueError(f"Unbekannte Wuerfel-Rolle: {role!r}") from exc
    return _domain_seed(domain, int(content_seed))


def _build_validation_context(
    context: "OptimizerContext",
    *,
    role: str = CUBE_ROLE_FINAL,
) -> tuple["OptimizerContext", int, str] | None:
    """Unabhaengiger Validierungs-Cube (gleiche Verteilung, anderer Seed).

    ``role=CUBE_ROLE_FINAL`` (Default) ist der finale Holdout: auf ihm
    laufen NUR noch der Test des eingefrorenen Challengers gegen den Anker
    und die Zielerreichungs-Nachzertifizierung -- keine Auswahl.
    ``role=CUBE_ROLE_SELECTION`` ist der getrennte Auswahl-Wuerfel des
    Drawdown-Reranks. Seeds und Hashes der Rollen sind verschieden.
    None, wenn keine ScenarioInputs vorliegen oder der Cube nicht gebaut
    werden kann.
    """
    inputs = getattr(context, "scenario_inputs", None)
    if inputs is None:
        return None
    validation_seed = _validation_seed_for_role(int(context.seed), role)
    scenario_horizon = int(
        getattr(context, "scenario_horizon_years", None) or context.horizon_years
    )
    try:
        validation_paths = build_scenario_paths(
            inputs,
            horizon_years=scenario_horizon,
            n_paths=int(context.n_paths),
            seed=validation_seed,
            antithetic=VALIDATION_CUBE_ANTITHETIC,
        )
    except (ReturnMomentError, ValueError):
        return None
    # Wie der Hauptwuerfel auf dem gemeinsamen Szenario-Horizont gezogen und
    # auf den Optimierungshorizont gekuerzt (sonst passt die Jahresachse
    # nicht zu Cashflows/Liabilities des Contexts).
    validation_paths = validation_paths[:, : int(context.horizon_years), :]
    validation_context = replace(
        context, return_paths=validation_paths, scenario_weights=None,
    )
    # Der Hash identifiziert den CUBE, nicht nur die Verteilung: derselbe
    # Inputs-Digest mit anderem Seed ist ein anderer Cube. Wuerde hier nur
    # der Inputs-Digest stehen, waeren Trainings- und Validierungs-Cube
    # nicht unterscheidbar -- genau die Verwechslung, die dieser Anker
    # ausschliessen soll. Rolle und Stichprobeneinheit sind mitgebunden.
    cube_hash = hashlib.sha256(
        "|".join([
            scenario_inputs_digest(inputs),
            str(scenario_horizon),
            str(int(context.n_paths)),
            str(validation_seed),
            f"antithetic={VALIDATION_CUBE_ANTITHETIC}",
            f"role={role}",
            f"sampling_unit={SAMPLING_UNIT_ANTITHETIC_PAIR}",
        ]).encode("utf-8")
    ).hexdigest()
    return validation_context, validation_seed, cube_hash


def _build_selection_validation_context(
    context: "OptimizerContext",
) -> tuple["OptimizerContext", int, str] | None:
    """Auswahl-Wuerfel (DRAWDOWN-HOLDOUT-REUSE-001), getrennt vom Holdout."""
    return _build_validation_context(context, role=CUBE_ROLE_SELECTION)


def _validation_sampling_units(
    validation_context: "OptimizerContext",
) -> tuple[np.ndarray, str]:
    """Stichprobeneinheiten eines Validierungswuerfels fuer den Bootstrap.

    RESAMPLING-ANTITHETIC-BOOTSTRAP-001: Partnerpfade (i, i + ceil(n/2))
    bilden EINE unabhaengige Einheit (Layout-Vertrag
    ``scenario_engine.sampling_unit_ids``).
    """
    n_paths = int(validation_context.n_paths)
    ids = scenario_sampling_unit_ids(
        n_paths, antithetic=VALIDATION_CUBE_ANTITHETIC,
    )
    name = (
        SAMPLING_UNIT_ANTITHETIC_PAIR
        if VALIDATION_CUBE_ANTITHETIC
        else SAMPLING_UNIT_PATH
    )
    return ids, name


def _certify_on_independent_validation_cube(
    context: "OptimizerContext",
    weights_array: np.ndarray,
    train_achievability: list[dict],
) -> tuple[list[dict], int | None, str | None, int | None]:
    """Zertifiziert den GEWINNER auf einem unabhaengigen Validierungs-Cube.

    Der Solver waehlt den besten Kandidaten auf `context.return_paths` --
    demselben Cube, auf dem die Zielerreichung danach bewertet wurde. Das
    Maximum ueber mehrere rauschbehaftete Schaetzer ist systematisch zu
    optimistisch (Winner's Curse): bei einem Ziel, dessen WAHRE
    Wahrscheinlichkeit exakt auf der Schwelle liegt, zertifizierte die alte
    Regel in ~97 Prozent der Faelle "erreichbar", wo ~50 Prozent korrekt
    gewesen waeren.

    Dieser Schritt baut einen zweiten Cube mit identischer Verteilung aber
    anderem Seed und bewertet NUR den bereits gewaehlten Gewinner darauf
    neu. Weil die Auswahl nicht von diesem Cube abhing, ist die Schaetzung
    darauf selektionsfrei -- vorausgesetzt, kein vorgelagerter Schritt hat
    auf diesem Cube ausgewaehlt: der Drawdown-Rerank nutzt deshalb den
    getrennten Auswahl-Wuerfel (``CUBE_ROLE_SELECTION``).

    Returns ``(achievability, validation_seed, validation_cube_hash,
    validation_n_paths)``. Ohne verwertbare ScenarioInputs im Context wird
    das Trainings-Ergebnis unveraendert zurueckgegeben und der Anker bleibt
    None -- die fehlende Validierung ist dann am
    ``reliability_verdict`` der Rows sichtbar, statt stillschweigend als
    validiert zu gelten.
    """
    validation = _build_validation_context(context)
    if validation is None:
        # Ohne Inputs bzw. bei fehlgeschlagenem Validierungs-Cube: der Lauf
        # wird NICHT abgebrochen -- aber er gilt auch nicht als validiert.
        return train_achievability, None, None, None
    validation_context, validation_seed, cube_hash = validation
    validation_wealth = _simulate_context_wealth(validation_context, weights_array)
    # GOAL-ACHIEVABILITY-ATTRIBUTION-001: publiziert wird der typisierte
    # Vertrag (Zielzeilen nach Prioritaet + genau eine Plan-Solvenz-Zeile),
    # nicht die interne Joint-Sicht der Chance-Penalty.
    validation_achievability = publish_goal_achievability(
        validation_wealth,
        validation_context.liabilities,
        validation_context.advisory_wealth_rappen,
        weights=None,
        annualized_return_bps_per_path=_annualized_twr_bps_per_path(
            validation_context, weights_array
        ),
        validation_seed=validation_seed,
    )
    return (
        validation_achievability,
        validation_seed,
        cube_hash,
        int(context.n_paths),
    )


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
    external_wealth_rappen: int = 0
    risky_fraction_per_bucket: dict[str, float] | None = None
    max_risky_fraction_bps: int | None = None
    # Canonical snapshot of the exact Sub-Allocation rows used to derive CMA
    # bucket metrics and scenario paths. Tuple ownership prevents later caller
    # list mutations from changing the meaning of an already-built context.
    sub_allocations: tuple[dict, ...] = ()
    # OPTIMIZER-POST-SELECTION-CERTIFICATION-001 (2026-10-10): die
    # ScenarioInputs, aus denen `return_paths` gebaut wurde. Noetig, damit
    # nach der Selektion ein UNABHAENGIGER Validierungs-Cube mit anderem
    # Seed (aber identischer Verteilung) gebaut werden kann -- ohne diese
    # Inputs liesse sich der Gewinner nur auf dem Trainings-Cube
    # nachzertifizieren, auf dem er gerade ausgewaehlt wurde.
    scenario_inputs: ScenarioInputs | None = None
    # Phase 5c: optional Likelihood-Weights aus Importance Sampling.
    # Wenn None: trivialer sample-mean (Backwards-Compat). Wenn gesetzt:
    # shortfall_objective + volatility_objective berechnen weighted Estimator.
    # Aktivierung: Caller (build_optimizer_context oder ext. Pfad) liefert
    # weights vom build_scenario_paths_with_weights-Wrapper.
    scenario_weights: np.ndarray | None = None
    # Sprint 4 Phase 3 (2026-05-17), deterministisch seit Kontrollrunde
    # 2026-09-19: Optionaler Mortalitaets-Cutoff. Wenn None: keine Mortality
    # (Backwards-Compat). Wenn gesetzt: shape (n_paths,) integer-Array, pro
    # Pfad year_index ab dem cashflow=0 -- seit dem Fix fuer ALLE Pfade
    # identisch (services.mortality.horizon.expected_death_year_offset_from_mandate),
    # nicht mehr pro Pfad stochastisch gesampelt (siehe build_optimizer_context).
    mortality_death_year_index_per_path: np.ndarray | None = None
    # Sprint U-P2 Fix C9 (2026-05-19): tax-aware Solver-Pfad. Vorher liefen
    # MC + Objective im Solver tax-naiv — Schweizer Vermoegenssteuer-Drag
    # blieb unsichtbar. Wenn tax_regime gesetzt ist, wendet simulate_wealth_paths
    # pro Jahr die TaxRegime-Logik an (Dividenden-, Kapitalgewinn-, Vermoegens-,
    # Erbschaftssteuer je nach Plugin).
    tax_regime: object | None = None
    dividend_yield_bps_per_bucket: np.ndarray | None = None
    base_calendar_year: int = 2026
    mandate_age_at_start: int | None = None
    is_retired: bool = False
    # Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): siehe constraints.bounds_collapse_warnings
    # -- nicht-leer, wenn eine House-Matrix-Bandbreite durch einen globalen
    # Cap/Floor stillschweigend auf einen Punkt kollabiert wurde.
    bounds_collapse_warnings: tuple[str, ...] = ()
    # Exact Markowitz inputs owned by the same context as the scenario paths.
    # Appended (rather than inserted among older optional fields) to preserve
    # the positional layout for legacy manual context construction.  The
    # canonical builder always populates both arrays.
    scenario_mu_bps: np.ndarray | None = None
    scenario_cov_bps2: np.ndarray | None = None
    # Canonical deterministic external net-funding path for total-scope goals.
    # Index 0 is today; subsequent entries align with simulated goal years.
    external_wealth_series_rappen: tuple[int, ...] = ()
    # Longest scenario cube used to draw this context. Paired horizon
    # sensitivities set the same value and retain only their own prefix in
    # ``return_paths``.
    scenario_horizon_years: int | None = None
    # CERT-ALLOCATION-INTENT-001: optional, PARTIAL Soft-Preference Target
    # Intent -- orthogonal to the hard `bounds` above. None/empty means no
    # Target Intent at all, never "treat the baseline/seed target as
    # binding" (that conflation was MANUAL-TARGET-SEMANTICS-001). A bucket
    # absent from the mapping carries zero preference penalty. Applied
    # identically in `_objective_from_array` (solver optimization) and
    # `evaluate_weights` (congruent post-round/external scoring) via
    # `services.optimizer.allocation_intent.preference_loss_from_array`.
    preferred_target_bps: dict[str, int] | None = None
    preference_penalty_lambda: float = SOFT_PREFERENCE_PENALTY_LAMBDA_DEFAULT
    soft_preference_policy_version: str = SOFT_PREFERENCE_POLICY_VERSION
    # OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001 (2026-10-13): die Mathematik
    # dieses Laufs, EINMAL beim Context-Bau aus der Umgebung aufgeloest und
    # danach unveraenderlich. Vorher las `combined_objective_two_phase()` den
    # Primaermodus bei jeder Auswertung neu (gemessen: 205 Mal pro Lauf) und
    # `_effective_hardness_weight()` den Goal-Weighting-Modus pro Ziel pro
    # Auswertung -- ein Umgebungswechsel mitten im Lauf liess SLSQP Kandidaten
    # nach UNTERSCHIEDLICHEN Groessen vergleichen, ohne dass es auffiel.
    #
    # Default None nur, um das positionale Layout fuer manuell gebaute
    # Contexts zu erhalten (siehe Kommentar bei scenario_mu_bps). Konsumenten
    # lesen den Vertrag ausschliesslich ueber `objective_contract_of()`, das
    # bei None fail-closed abbricht statt still auf die Umgebung
    # zurueckzufallen -- ein Lauf ohne eingefrorene Mathematik hat keinen
    # Nachweis darueber, was er gerechnet hat.
    objective_contract: "ObjectiveContractV1 | None" = None
    # IMPORTANCE-SAMPLING-ESS-001 (2026-10-18): Audit des Importance
    # Samplings dieses Wuerfels (Entscheid, Proposal-Parameter, Kish-ESS,
    # Gewichtskonzentration, ggf. Fallback-Grund). None nur bei manuell
    # gebauten Contexts.
    importance_sampling_audit: dict | None = None
    # HOUSE-PRIOR-001 (Engine saa_resampled_v6): zulaessig projizierte
    # Hausmatrix-Zielquote als Prior des Optimierers (read-only, wie
    # scenario_cov_bps2). Gesetzt nur im Resampling-Pfad des Default-Modus
    # ``goal_shortfall`` mit projizierbarem Anker; dann ersetzt
    # ``house_prior_kappa * (w - w_H)' Sigma (w - w_H)`` den Tiebreak
    # ``w' Sigma w`` (siehe ``_tiebreak_portfolio_variance``). Bags,
    # Validierungswuerfel und ``evaluate_weights(result.context, ...)`` erben
    # ihn ueber ``replace`` -- eine Zielfunktion fuer alle Konsumenten.
    house_prior_weights: np.ndarray | None = None
    house_prior_kappa: float = HOUSE_PRIOR_KAPPA
    # GOAL-REACHABILITY-SCREEN-001 (2026-10-18): je Ziel mit Ziel-Untergrenze
    # die hoechste beobachtete Erfolgswahrscheinlichkeit ueber eine
    # Pruefmenge zulaessiger Allokationen. Seit Engine v7
    # (GOAL-SCREEN-OBJECTIVE-ERASURE-001) REINE OFFENLEGUNG auf einem eigenen
    # Screening-Wuerfel: kein Ziel wird mehr aus Zielfunktion oder
    # Chance-Strafe genommen (das fruehere Feld ``penalty_exempt_goal_ids``
    # ist entfallen). None, wenn nicht geprueft (keine ScenarioInputs).
    goal_reachability: dict | None = None


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
    # CERT-ALLOCATION-INTENT-001: see OptimizerResult.preference_deviation_bps.
    preference_deviation_bps: dict[str, int] | None = None


def _trusted_weights_bps_to_array(weights_bps: Mapping[str, int]) -> np.ndarray:
    """Internal exact conversion for already-validated/generated bps weights."""
    return np.array(
        [int(weights_bps[bucket]) / 10000.0 for bucket in BUCKET_ORDER],
        dtype=np.float64,
    )


def _weights_bps_to_array(weights_bps: Mapping[str, int]) -> np.ndarray:
    """Strict external conversion from exact integer bps to fractions.

    External evaluations are audit operations, not allocation repair.  Missing
    buckets, unknown keys, non-integer/out-of-range values, or a sum other than
    exactly 10'000 bps are therefore hard input errors and are never silently
    normalised.
    """
    if not isinstance(weights_bps, Mapping):
        raise OptimizerInputError(
            "weights_bps must be a mapping of optimizer bucket -> integer bps."
        )
    expected = set(BUCKET_ORDER)
    actual = set(weights_bps.keys())
    missing = sorted(expected - actual)
    extra = sorted(actual - expected, key=str)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing={missing}")
        if extra:
            details.append(f"unknown={extra}")
        raise OptimizerInputError(
            "weights_bps must contain exactly the optimizer buckets ("
            + ", ".join(details)
            + ")."
        )

    parsed: dict[str, int] = {}
    for bucket in BUCKET_ORDER:
        raw = weights_bps[bucket]
        if isinstance(raw, bool) or not isinstance(raw, Integral):
            raise OptimizerInputError(
                f"weights_bps[{bucket!r}] must be integer basis points."
            )
        value = int(raw)
        if not 0 <= value <= 10000:
            raise OptimizerInputError(
                f"weights_bps[{bucket!r}] must stay within 0..10000 bps."
            )
        parsed[bucket] = value
    total = sum(parsed.values())
    if total != 10000:
        raise OptimizerInputError(
            f"weights_bps must sum exactly to 10000 bps (got {total})."
        )
    return _trusted_weights_bps_to_array(parsed)


def _simulate_context_wealth(
    context: OptimizerContext,
    w: np.ndarray,
    *,
    portfolio_factors: np.ndarray | None = None,
) -> np.ndarray:
    return simulate_wealth_paths(
        portfolio_factors=portfolio_factors,
        initial_wealth_rappen=context.advisory_wealth_rappen,
        weights=w,
        return_paths=context.return_paths,
        cashflow_series_rappen=context.cashflow_series_rappen,
        liability_path_rappen=context.aggregated_liability_path,
        death_year_index_per_path=context.mortality_death_year_index_per_path,
        tax_regime=context.tax_regime,
        dividend_yield_bps_per_bucket=context.dividend_yield_bps_per_bucket,
        base_calendar_year=context.base_calendar_year,
        mandate_age_at_start=context.mandate_age_at_start,
        is_retired=context.is_retired,
    )


def _portfolio_return_factors(
    context: OptimizerContext,
    w: np.ndarray,
) -> np.ndarray:
    """Cashflow-neutrale Jahres-Wachstumsfaktoren des Portfolios, (pfade, jahre).

    Einzige Ableitung dieser Groesse. Sowohl die annualisierte Rendite als
    auch die Risikomass-Varianten der Zielfunktion (siehe
    objective_variants.py) haengen daran; zwei getrennte einsum-Ableitungen
    waeren genau die Divergenzklasse, die die MC-Paritaetsbefunde ausgeloest
    hat (ein Kanal rechnet etwas anderes als der andere, ohne dass es
    auffaellt).
    """
    return np.einsum(
        "phb,b->ph", context.return_paths, np.asarray(w, dtype=np.float64)
    )


def _annualized_twr_bps_per_path(
    context: OptimizerContext,
    w: np.ndarray,
    *,
    portfolio_factors: np.ndarray | None = None,
) -> np.ndarray:
    """Cashflow-neutral annualized portfolio return for every scenario path."""
    if portfolio_factors is None:
        portfolio_factors = _portfolio_return_factors(context, w)
    safe_factors = np.maximum(portfolio_factors, 1e-12)
    # In-place: gleiche Werte, ein Zwischen-Array weniger je Auswertung.
    np.log(safe_factors, out=safe_factors)
    annualized = np.exp(np.mean(safe_factors, axis=1)) - 1.0
    return annualized * 10000.0


def _canonicalize_sub_allocations(
    sub_allocations: list[dict] | tuple[dict, ...] | None,
) -> tuple[dict, ...]:
    """Take an owned, stable snapshot of the exact Sub-Allocation input.

    The row order and all row fields are preserved deliberately: this is a
    context snapshot, not a second source of allocation logic. Deep-copying
    prevents a later post-solver cap/materialisation step from mutating the
    scenario assumptions of a context that has already been evaluated.
    """
    if sub_allocations is None:
        return ()
    canonical: list[dict] = []
    for index, row in enumerate(sub_allocations):
        if not isinstance(row, Mapping):
            raise OptimizerInputError(
                f"sub_allocations[{index}] must be a mapping, got {type(row).__name__}."
            )
        canonical.append(deepcopy(dict(row)))
    return tuple(canonical)


def build_optimizer_context(
    *,
    cma,
    goals: list,
    house_matrix_row,
    score_x10: int,
    advisory_wealth_rappen: int,
    cashflow_series_rappen: Iterable[int],
    external_wealth_rappen: int = 0,
    external_wealth_series_rappen: Iterable[int] | None = None,
    sub_allocations: list[dict] | None = None,  # Sprint B1 (2026-06-07)
    effective_bounds_bps: Mapping[str, tuple[int, int]] | None = None,
    horizon_years: int = 10,
    scenario_horizon_years: int | None = None,
    n_paths: int = 2000,
    seed: int | None = None,
    inflation_series_bps: list[int] | None = None,
    risky_fraction_per_bucket: dict[str, float] | None = None,
    max_risky_fraction_bps: int | None = None,
    client_birth_year: int | None = None,
    client_sex: str | None = None,
    use_mortality_simulation: bool = False,
    mortality_fixed_offset_years: int | None = None,
    # Sprint U-P2 Fix C9: tax-aware Solver-Optionen
    tax_regime: object | None = None,
    dividend_yield_bps_per_bucket: np.ndarray | None = None,
    base_calendar_year: int = 2026,
    mandate_age_at_start: int | None = None,
    is_retired: bool = False,
    # CERT-ALLOCATION-INTENT-001: optional, partial Soft-Preference Target
    # Intent -- see OptimizerContext.preferred_target_bps.
    preferred_target_bps: Mapping[str, int] | None = None,
    preference_penalty_lambda: float | None = None,
    # OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001: vorgegebener Lauf-Vertrag.
    # None = hier aufloesen (der Normalfall, genau eine Umgebungslesung pro
    # Lauf). Gesetzt = ein Aufrufer, der mehrere Laeufe unter DERSELBEN
    # Mathematik vergleichen muss, hat ihn schon aufgeloest.
    objective_contract: ObjectiveContractV1 | None = None,
) -> OptimizerContext:
    """Baut den Solver-Context (Scenarios, Liabilities, Bounds, Constraints).

    Identische Inputs liefern identische Contexts. Wenn `seed=None`, wird der
    deterministische Inhalts-Seed aus dem wirtschaftlichen Inhalt abgeleitet
    (siehe `optimizer_content_seed`) -- nie aus Datenbank-IDs.
    """
    validated_preferred_target_bps: dict[str, int] | None = None
    if preferred_target_bps is not None:
        if not isinstance(preferred_target_bps, Mapping):
            raise OptimizerInputError(
                "preferred_target_bps must be a mapping of optimizer bucket -> integer bps."
            )
        unknown_buckets = sorted(set(preferred_target_bps) - set(BUCKET_ORDER))
        if unknown_buckets:
            raise OptimizerInputError(
                f"preferred_target_bps contains unknown buckets: {unknown_buckets}."
            )
        validated_preferred_target_bps = {}
        for bucket, value in preferred_target_bps.items():
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise OptimizerInputError(
                    f"preferred_target_bps[{bucket!r}] must be an integer bps value."
                )
            if not 0 <= int(value) <= 10000:
                raise OptimizerInputError(
                    f"preferred_target_bps[{bucket!r}] must stay within 0..10000 bps."
                )
            validated_preferred_target_bps[bucket] = int(value)
    horizon_years = int(max(1, horizon_years))
    if scenario_horizon_years is not None and (
        isinstance(scenario_horizon_years, bool)
        or not isinstance(scenario_horizon_years, Integral)
    ):
        raise OptimizerInputError(
            "scenario_horizon_years must be an exact integer."
        )
    common_scenario_horizon = (
        horizon_years
        if scenario_horizon_years is None
        else int(scenario_horizon_years)
    )
    if common_scenario_horizon < horizon_years:
        raise OptimizerInputError(
            "scenario_horizon_years must be >= horizon_years."
        )

    canonical_sub_allocations = _canonicalize_sub_allocations(sub_allocations)
    exact_risky_fractions = (
        validate_risky_fraction_per_bucket(risky_fraction_per_bucket)
        if risky_fraction_per_bucket is not None
        else None
    )

    if effective_bounds_bps is None:
        bands = bands_from_house_matrix_row(house_matrix_row)
        collapse_warnings = bounds_collapse_warnings(bands)
    else:
        # Explicit effective mandate bands are a hard domain contract. Validate
        # them before building expensive scenarios and reject contradictions
        # instead of inheriting legacy House-Matrix clamp-and-warn behaviour.
        bands = bands_from_effective_bounds_bps(effective_bounds_bps)
        collapse_warnings = []
    bounds, scipy_constraints = build_constraint_set(
        bands,
        score_x10,
        risky_fraction_per_bucket=exact_risky_fractions,
        max_risky_fraction_bps=max_risky_fraction_bps,
    )
    inputs = scenario_inputs_from_cma(
        cma,
        sub_allocations=list(canonical_sub_allocations) or None,
    )
    if seed is None:
        # SAA-RESAMPLED-STABILITY-001: Inhalts-Seed statt ID-Seed. Vorher
        # gingen `cma.id` und die Goal-IDs in den Seed -- ein geloeschtes und
        # identisch neu erfasstes Ziel aenderte damit den Monte-Carlo-Wuerfel
        # und (bei einem flachen Optimum) die Strategie. Jetzt bestimmt
        # ausschliesslich der wirtschaftliche Inhalt den Seed.
        seed = optimizer_content_seed(
            scenario_inputs=inputs,
            goals=goals,
            score_x10=score_x10,
            horizon_years=horizon_years,
            scenario_horizon_years=common_scenario_horizon,
            n_paths=n_paths,
        )
    scenario_mu_bps = np.array(inputs.mu_bps, dtype=np.float64, copy=True)
    scenario_cov_bps2 = np.array(
        _covariance_bps_from_scenario_inputs(inputs.sigma_bps, inputs.cholesky),
        dtype=np.float64,
        copy=True,
    )
    if (
        scenario_mu_bps.shape != (N_BUCKETS,)
        or scenario_cov_bps2.shape != (N_BUCKETS, N_BUCKETS)
        or not np.all(np.isfinite(scenario_mu_bps))
        or not np.all(np.isfinite(scenario_cov_bps2))
    ):
        raise OptimizerInputError(
            "CMA scenario inputs must be finite and match the optimizer bucket shape."
        )
    # Frozen dataclass alone does not freeze ndarray contents.  Read-only owned
    # copies keep the retained context stable for solver, fallback and audit.
    scenario_mu_bps.setflags(write=False)
    scenario_cov_bps2.setflags(write=False)
    # Sprint B1 (2026-06-07): Cache-Key muss Sub-Allocation enthalten,
    # sonst liefert Cache stale Pfade wenn dieselbe cma_id mit anderem
    # Sub-Mix aufgerufen wird.
    cma_id_for_cache = str(getattr(cma, "id", "no-cma"))
    if canonical_sub_allocations:
        try:
            import hashlib
            import json as _json
            sub_repr = _json.dumps(
                canonical_sub_allocations,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            sub_hash = hashlib.sha256(sub_repr.encode("utf-8")).hexdigest()[:12]
            cma_id_for_cache = f"{cma_id_for_cache}::sub::{sub_hash}"
        except (TypeError, ValueError) as exc:
            raise OptimizerInputError(
                "Canonical sub-allocations must be strictly JSON serializable "
                "for an unambiguous scenario-cache identity."
            ) from exc

    # Sprint P1 (2026-06-06): IS-Auto-Decision
    # ---------------------------------------
    # Wir muessen liabilities zuerst bauen, weil hardness fuer die Decision
    # benoetigt wird. ABER goals_to_liabilities ist deterministisch, also
    # safe vor der Scenario-Generierung aufzurufen.
    canonical_external_wealth_series: tuple[int, ...] = ()
    if external_wealth_series_rappen is not None:
        try:
            raw_external_series = list(external_wealth_series_rappen)
        except TypeError as exc:
            raise OptimizerInputError(
                "external_wealth_series_rappen must be an iterable of integers."
            ) from exc
        if len(raw_external_series) < int(horizon_years) + 1:
            raise OptimizerInputError(
                "external_wealth_series_rappen must cover today and every "
                "optimizer horizon year."
            )
        if any(
            isinstance(value, bool) or not isinstance(value, Integral)
            for value in raw_external_series
        ):
            raise OptimizerInputError(
                "external_wealth_series_rappen must contain exact integer Rappen."
            )
        canonical_external_wealth_series = tuple(
            int(value) for value in raw_external_series[: int(horizon_years) + 1]
        )

    liabilities = goals_to_liabilities(
        goals,
        horizon_years=horizon_years,
        inflation_series_bps=inflation_series_bps,
        external_wealth_rappen=external_wealth_rappen,
        external_wealth_series_rappen=(
            canonical_external_wealth_series or None
        ),
    )
    has_hart_goal = any(
        str(getattr(liab, "hardness_key", "") or "").lower() == "hart"
        for liab in liabilities
    )
    is_active, is_reason = decide_is_for_context(
        score_x10=int(score_x10),
        has_hart_goal=has_hart_goal,
        is_retired=bool(is_retired),
    )
    is_audit: dict = {
        "decision_active": bool(is_active),
        "decision_reason": str(is_reason),
        "scheme": IS_SCHEME_VERSION,
    }
    try:
        if is_active:
            # IMPORTANCE-SAMPLING-ESS-001: Gesamt-Shift-Budget c (auf die
            # Jahre des gezogenen Horizonts verteilt), defensive Mischung,
            # Gewichte auf dem Optimierungshorizont.
            shift_vec = build_shift_vector(
                N_BUCKETS,
                strength=IS_TOTAL_SHIFT_SIGMA,
            )
            return_paths, scenario_weights = build_scenario_paths_with_weights_cached(
                inputs,
                cma_id=cma_id_for_cache,
                horizon_years=common_scenario_horizon,
                n_paths=n_paths,
                seed=seed,
                shift_vector=shift_vec,
                mixture_alpha=IS_DEFENSIVE_MIXTURE_ALPHA,
                weight_horizon_years=int(horizon_years),
            )
            diagnostics = importance_sampling_diagnostics(scenario_weights)
            is_audit.update({
                "total_shift_sigma": IS_TOTAL_SHIFT_SIGMA,
                "per_year_shift_sigma": IS_TOTAL_SHIFT_SIGMA / float(
                    np.sqrt(float(common_scenario_horizon))
                ),
                "mixture_alpha": IS_DEFENSIVE_MIXTURE_ALPHA,
                "max_weight_bound": 1.0 / IS_DEFENSIVE_MIXTURE_ALPHA,
                "weight_horizon_years": int(horizon_years),
                "ess_fallback_fraction": IS_ESS_FALLBACK_FRACTION,
                **diagnostics,
            })
            if ess_requires_fallback(scenario_weights):
                # Unter der ESS-Schwelle traegt die Gewichtung keine
                # belastbare Aussage mehr: Standard-MC statt eines Schaetzers,
                # der auf wenigen Pfaden ruht. Grund im Audit.
                is_audit["fallback"] = "ess_below_threshold"
                scenario_weights = None
                return_paths = build_scenario_paths_cached(
                    inputs,
                    cma_id=cma_id_for_cache,
                    horizon_years=common_scenario_horizon,
                    n_paths=n_paths,
                    seed=seed,
                )
        else:
            return_paths = build_scenario_paths_cached(
                inputs,
                cma_id=cma_id_for_cache,
                horizon_years=common_scenario_horizon,
                n_paths=n_paths,
                seed=seed,
            )
            scenario_weights = None  # uniform sample-mean
    except ReturnMomentError as exc:
        raise OptimizerInputError(str(exc)) from exc
    is_audit["active"] = scenario_weights is not None
    # Same seed is not enough when NumPy draws arrays with different horizon
    # shapes: later paths get a different flattened RNG offset. Drawing both
    # paired runs at the common max horizon and slicing here makes every path's
    # overlapping years byte-identical.
    return_paths = return_paths[:, :horizon_years, :]
    aggregated_liability = aggregate_liability_path(liabilities, horizon_years)

    # Sprint 4 Phase 3 / Kontrollrunde 2026-09-19: Mortalitaets-Cutoff wenn
    # aktiviert. DETERMINISTISCH (identisch fuer alle Pfade), nicht mehr
    # pro-Pfad stochastisch gesampelt: mortality_fixed_offset_years kommt aus
    # services.mortality.horizon.expected_death_year_offset_from_mandate
    # (services/mandate_model_inputs.py::mortality_solver_kwargs_from_mandate)
    # -- derselben Quelle, die auch der Report als Sterbe-Marker anzeigt.
    #
    # Vorherige Version sampelte ein zufaelliges Sterbealter PRO PFAD; nach
    # dem simulierten Tod wurde Cashflow=0 gesetzt, Vermoegen wuchs aber
    # unveraendert weiter (Erbschafts-Fiktion). Damit genuegte jeder fruehe
    # simulierte Tod automatisch als Zielerreichung fuer outflow_stream/
    # cashflow_in_year-Ziele, unabhaengig davon ob der Entnahmeplan
    # tatsaechlich getragen haette -- ohne dass der Report dies offenlegte.
    # Ein fuer alle Pfade IDENTISCHER Horizont (Berater-Override oder
    # BFS-Median) hat diese Pfad-individuelle Zufallsstreuung nicht mehr:
    # Zielerreichung reagiert jetzt sauber darauf, WELCHEN Horizont der
    # Berater waehlt (bis 70 vs. bis 100), nicht darauf, welcher einzelne
    # Pfad zufaellig "glueck" mit einem fruehen simulierten Tod hatte.
    death_indices = None
    if use_mortality_simulation:
        if not client_birth_year or client_sex not in ("M", "F"):
            raise OptimizerInputError(
                "Activated mortality simulation requires client_birth_year "
                "and client_sex M/F."
            )
        if mortality_fixed_offset_years is not None:
            fixed_index = int(
                np.clip(int(mortality_fixed_offset_years), 1, int(horizon_years))
            )
            death_indices = np.full(int(n_paths), fixed_index, dtype=np.int32)

    context = OptimizerContext(
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
        scenario_mu_bps=scenario_mu_bps,
        scenario_cov_bps2=scenario_cov_bps2,
        external_wealth_rappen=max(0, int(external_wealth_rappen or 0)),
        external_wealth_series_rappen=canonical_external_wealth_series,
        scenario_horizon_years=common_scenario_horizon,
        risky_fraction_per_bucket=exact_risky_fractions,
        max_risky_fraction_bps=max_risky_fraction_bps,
        sub_allocations=canonical_sub_allocations,
        # OPTIMIZER-POST-SELECTION-CERTIFICATION-001: Basis fuer den
        # unabhaengigen Validierungs-Cube nach der Selektion.
        scenario_inputs=inputs,
        # Sprint P1 (2026-06-06): IS-Likelihood-Weights
        scenario_weights=scenario_weights,
        importance_sampling_audit=is_audit,
        mortality_death_year_index_per_path=death_indices,
        # Sprint U-P2 Fix C9: tax-aware Felder
        tax_regime=tax_regime,
        dividend_yield_bps_per_bucket=dividend_yield_bps_per_bucket,
        base_calendar_year=int(base_calendar_year),
        mandate_age_at_start=mandate_age_at_start,
        is_retired=bool(is_retired),
        bounds_collapse_warnings=tuple(collapse_warnings),
        preferred_target_bps=validated_preferred_target_bps,
        preference_penalty_lambda=(
            float(preference_penalty_lambda)
            if preference_penalty_lambda is not None
            else SOFT_PREFERENCE_PENALTY_LAMBDA_DEFAULT
        ),
        # OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001: DIE eine Aufloesung der
        # Umgebung fuer diesen Lauf. Ab hier liest kein Konsument mehr
        # `OPTIMIZER_OBJECTIVE` oder `OPTIMIZER_GOAL_WEIGHTING`; der Live-Read
        # bleibt damit wirksam (eine Konfigurationsaenderung greift beim
        # naechsten Lauf, ohne Prozessneustart), aber INNERHALB eines Laufs
        # ist die Mathematik per Konstruktion konstant.
        objective_contract=(
            objective_contract
            if objective_contract is not None
            else resolve_objective_contract()
        ),
    )
    # GOAL-REACHABILITY-SCREEN-001: einmal je Context, seit Engine v7 nur
    # Offenlegung auf einem eigenen Screening-Wuerfel (nie der Holdout, der
    # spaeter zertifiziert; GOAL-SCREEN-HOLDOUT-LEAKAGE-001) und ohne
    # Wirkung auf die Zielfunktion (GOAL-SCREEN-OBJECTIVE-ERASURE-001).
    screen = goal_reachability_screen(context)
    if screen is None:
        return context
    # GOAL-HIERARCHY-002 / DEMOTED-GOAL-WEIGHT-001: herabgestufte Ziele auf
    # der Liability markieren (Wunschziel-Gewicht in jedem Modus, nicht
    # Stufe 1). Bags/Validierung erben die Markierung ueber ``replace``.
    demoted = frozenset(
        str(g) for g in (screen.get("not_found_reachable_goal_ids") or ())
    )
    liabilities = [
        replace(liab, demoted=True) if str(liab.goal_id) in demoted else liab
        for liab in context.liabilities
    ]
    return replace(context, goal_reachability=screen, liabilities=liabilities)


def _tiebreak_portfolio_variance(
    context: OptimizerContext, w: np.ndarray,
) -> float | None:
    """TIEBREAK-PORTFOLIO-VARIANCE-001: ``w' Sigma w`` aus der CMA-Kovarianz
    des Contexts (None, falls ein manuell gebauter Context keine hat).

    HOUSE-PRIOR-001 (Engine v6): traegt der Context einen Hausmatrix-Prior,
    ist der Term ``kappa_H * (w - w_H)' Sigma (w - w_H)`` (Tracking-Error-
    Varianz zur Hausquote) statt ``w' Sigma w``. Ohne Anker bleibt v5."""
    cov = context.scenario_cov_bps2
    if cov is None:
        return None
    house = context.house_prior_weights
    if house is not None:
        return house_prior_penalty(
            w, house, cov, kappa=float(context.house_prior_kappa),
        )
    return portfolio_variance_one_year(w, cov)


def _objective_from_array(context: OptimizerContext, w: np.ndarray) -> float:
    """Internes Objective fuer einen w-Array unter dem Context.

    Wird vom Solver-Closure genutzt, damit der Optimierungslauf exakt die
    gleichen Scenarios sieht wie evaluate_weights spaeter.

    Phase 5c: respektiert context.scenario_weights (IS-Likelihood-Ratios)
    wenn gesetzt. Bei scenario_weights=None: trivialer sample-mean wie zuvor.
    """
    return _objective_from_inputs(context, w, _evaluation_inputs(context, w))


def _evaluation_inputs(
    context: OptimizerContext, w: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(portfolio_factors, wealth, annualized_twr)`` EINER Allokation.

    SAA-RESAMPLED-RUNTIME-001: Faktoren einmal ableiten und fuer Wealth-
    Simulation UND annualisierte Rendite verwenden (bitidentisch).
    GOAL-HIERARCHY-001: Zielfunktion und Stufe-1-Nebenbedingung teilen sich
    dieselbe Simulation je Punkt.
    """
    portfolio_factors = _portfolio_return_factors(context, w)
    wealth = _simulate_context_wealth(
        context, w, portfolio_factors=portfolio_factors
    )
    annualized_twr = _annualized_twr_bps_per_path(
        context, w, portfolio_factors=portfolio_factors
    )
    return portfolio_factors, wealth, annualized_twr


def _protected_level_from_inputs(
    context: OptimizerContext,
    inputs: tuple[np.ndarray, np.ndarray, np.ndarray],
    *,
    with_per_path: bool = False,
) -> tuple[float, np.ndarray | None]:
    """GOAL-HIERARCHY-001: Stufe-1-Zielniveau G1 (erreichbare harte/primaere Ziele)."""
    _factors, wealth, annualized_twr = inputs
    return protected_goal_level(
        _stage1_liabilities(context),
        wealth,
        initial_wealth_rappen=context.advisory_wealth_rappen,
        horizon_years=context.horizon_years,
        weights=context.scenario_weights,
        annualized_return_bps_per_path=annualized_twr,
        goal_weighting_mode=objective_contract_of(context).goal_weighting_mode,
        with_per_path=with_per_path,
    )


def _demoted_goal_ids(context: OptimizerContext) -> frozenset:
    """GOAL-HIERARCHY-002 (CIO-Review #650): Ziele, die der Screen auf seiner
    Pruefmenge nicht mit der Mindestsicherheit erreichbar fand (Default:
    obere 95-%-Grenze < tau/2). Sie bleiben mit vollem Fehlbetrag in der
    Zielfunktion (kein Ausnehmen, Codex "CHF 0 != CHF 900"), werden aber
    unabhaengig vom Haertegrad in Stufe 2 herabgestuft -- ein aussichtsloses
    Ziel darf erreichbare Stufe-1-Ziele nicht verdraengen."""
    screen = getattr(context, "goal_reachability", None) or {}
    return frozenset(str(g) for g in (screen.get("not_found_reachable_goal_ids") or ()))


def _stage1_liabilities(context: OptimizerContext) -> list:
    """Stufe-1-Ziele: hart/primaer, im Horizont, vom Screen erreichbar gefunden."""
    demoted = _demoted_goal_ids(context)
    n_cols = int(context.horizon_years) + 1
    return [
        liab for liab in context.liabilities
        if is_protected_goal(liab, n_wealth_columns=n_cols)
        and str(liab.goal_id) not in demoted
    ]


def _objective_from_inputs(
    context: OptimizerContext,
    w: np.ndarray,
    inputs: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> float:
    """Zielfunktion aus bereits simulierten Inputs (siehe ``_objective_from_array``)."""
    contract = objective_contract_of(context)
    portfolio_factors, wealth, annualized_twr = inputs
    objective = float(combined_objective_two_phase(
        context.liabilities,
        wealth,
        initial_wealth_rappen=context.advisory_wealth_rappen,
        horizon_years=context.horizon_years,
        weights=context.scenario_weights,
        annualized_return_bps_per_path=annualized_twr,
        # OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001: beide Modi aus dem
        # eingefrorenen Vertrag, nicht aus der Umgebung. Das ist der Kern des
        # Fixes: diese Funktion ist der SLSQP-Closure und laeuft hunderte Male
        # pro Lauf -- hier entstand die Mischung zweier Zielfunktionen.
        objective_mode=contract.objective_mode,
        goal_weighting_mode=contract.goal_weighting_mode,
        # OPTIMIZER-OBJECTIVE-VARIANTS-001: die Risikomass-Varianten rechnen
        # auf den cashflow-neutralen Faktoren, nicht auf `wealth` -- sonst
        # wuerde geplanter Verzehr als Marktrisiko bewertet.
        portfolio_return_factors=portfolio_factors,
        portfolio_variance=_tiebreak_portfolio_variance(context, w),
    ))
    # CERT-ALLOCATION-INTENT-001 (MANUAL-TARGET-SEMANTICS-001): an explicit
    # Soft-Preference Target Intent must actually influence the optimization,
    # not just the derived bounds. Additive penalty computed entirely in this
    # solver layer -- services/optimizer/objective.py stays untouched.
    if context.preferred_target_bps:
        objective += preference_loss_from_array(
            w, context.preferred_target_bps, lam=context.preference_penalty_lambda,
        )
    return objective


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
    contract = objective_contract_of(context)
    w = _weights_bps_to_array(weights_bps)
    # Sprint U-P2 Fix C9: tax-aware Evaluation
    # SAA-RESAMPLED-RUNTIME-001: Faktoren einmal ableiten und fuer Wealth-
    # Simulation UND annualisierte Rendite verwenden (bitidentisch).
    portfolio_factors = _portfolio_return_factors(context, w)
    wealth = _simulate_context_wealth(
        context, w, portfolio_factors=portfolio_factors
    )
    annualized_twr = _annualized_twr_bps_per_path(
        context, w, portfolio_factors=portfolio_factors
    )
    objective = combined_objective_two_phase(
        context.liabilities,
        wealth,
        initial_wealth_rappen=context.advisory_wealth_rappen,
        horizon_years=context.horizon_years,
        weights=context.scenario_weights,
        # OPTIMIZER-OBJECTIVE-VARIANTS-001: siehe _objective_from_array --
        # beide Pfade muessen denselben Primaerterm sehen, sonst weicht
        # `evaluate_weights(...).objective_value` von dem ab, was der Solver
        # tatsaechlich optimiert hat.
        #
        # OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001: "denselben Primaerterm
        # sehen" war vorher nur dadurch erfuellt, dass beide Pfade dieselbe
        # Umgebung lasen -- bei einer Aenderung zwischen Optimierung und
        # Nachbewertung also gerade NICHT. Jetzt beide aus demselben
        # eingefrorenen Vertrag.
        objective_mode=contract.objective_mode,
        goal_weighting_mode=contract.goal_weighting_mode,
        portfolio_return_factors=portfolio_factors,
        annualized_return_bps_per_path=annualized_twr,
        portfolio_variance=_tiebreak_portfolio_variance(context, w),
    )
    # CERT-ALLOCATION-INTENT-001: same additive Soft-Preference penalty as
    # `_objective_from_array`, so `evaluate_weights(ctx, result.weights_bps)
    # .objective_value` stays congruent with what the solver itself optimized
    # (same contract the pre-existing post-round re-evaluation in
    # `run_solver` already relies on for the base objective).
    weights_bps_out = _weights_to_bps_dict(w, bounds=context.bounds)
    preference_deviation: dict[str, int] | None = None
    if context.preferred_target_bps:
        objective = float(objective) + preference_loss_from_array(
            w, context.preferred_target_bps, lam=context.preference_penalty_lambda,
        )
        preference_deviation = preference_deviation_bps(
            weights_bps_out, context.preferred_target_bps,
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
        weights_bps=weights_bps_out,
        objective_value=float(objective),
        feasible=bool(feasible),
        constraint_violations=list(violations),
        terminal_wealth_p10_rappen=p10_i,
        terminal_wealth_p50_rappen=p50_i,
        terminal_wealth_p90_rappen=p90_i,
        preference_deviation_bps=preference_deviation,
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


# SAA-RESAMPLED-STABILITY-001 (2026-10-14): Inhalts-Seed.
#
# Version der Seed-Konstruktion UND der Entscheidungslogik, die auf dem Seed
# aufsetzt. Geht in den Seed ein: eine neue Engine-Version zieht bewusst
# neue Wuerfel, statt alte Wuerfel unter neuer Mathematik wiederzuverwenden.
#
# v2 (2026-10-17): Seed float-robust (scenario_inputs_seed_digest) und
# Goal-Daten relativ zum Bewertungsjahr (SAA-SEED-FLOAT-ROBUST-001);
# Signifikanzentscheid lexikographisch (SAA-SIGNIFICANCE-LEXICOGRAPHIC-001).
#
# Engine v3 (2026-10-18, OBJECTIVE-NORMALIZATION-001): stetige, Pareto-
# monotone Zielfunktion (Tiebreak immer aktiv, kein Stufen-Schalter) und
# volumen-normierte, lineare Chance-Strafe statt 1e6 * Defizit^2. Der
# Seed-Aufbau ist unveraendert (content_seed_v2); die Engine-Version geht
# aber in den Seed ein -- neue Mathematik zieht bewusst neue Wuerfel.
#
# Engine v4 (2026-10-18, IMPORTANCE-SAMPLING-ESS-001 +
# TIEBREAK-PORTFOLIO-VARIANCE-001 + GOAL-REACHABILITY-SCREEN-001): Importance
# Sampling als defensive Mischung mit horizont-skaliertem Shift (ESS/N ~0.83
# statt ~exp(-T/4)), Tiebreak kappa * w' Sigma w statt Var(W_T)/W0^2, und
# in den Risikomass-Varianten keine Chance-Strafe fuer Ziele, die auf keiner
# zulaessigen Allokation erreichbar sind.
#
# Engine v5 (2026-10-18, HOUSE-FIRST-SIGNIFICANCE-001, CIO-Entscheid
# "Hausmatrix, solange die Ziele mit ihr gleich sicher erreicht sind"): der
# Signifikanztest gegen die Hausmatrix entscheidet auf der Zielebene
# (Ziel-Fehlbetrag + Chance-Strafe), nicht mehr ueber den deterministischen
# Volatilitaets-Tiebreak; Risikomass-Varianten zusaetzlich nur mit
# Materialitaetsschwelle (50 bps). Neue Wuerfel, weil die Version in den
# Seed eingeht.
#
# Engine v6 (2026-10-18, HOUSE-PRIOR-001, CIO-Entscheid): die Hausmatrix ist
# ein Prior IM Optimierer statt eines binaeren Schalters dahinter. Je Bag
# ``argmin G(w) + P_pref(w) + kappa_H (w - w_H)' Sigma (w - w_H)`` mit
# kappa_H = 300 (services/optimizer/house_prior.py); der Tiebreak
# ``w' Sigma w`` entfaellt im Default, wenn ein Anker vorliegt. Der
# gepaarte Bootstrap bleibt nur zur Offenlegung plus Sicherheitsnetz (Final
# signifikant SCHLECHTER als die Hausquote -> Hausquote). v5 sprang bei +1 %
# Zielbetrag um bis zu 20.9 pp Turnover; v6 <= 4 pp. Risikomass-Varianten
# und Laeufe ohne Anker unveraendert v5-Regel. Bewusst neue Wuerfel (die
# Version geht in den Seed).
OPTIMIZER_SEED_SCHEME = "content_seed_v2"
# v7 (2026-10-18, Statistik-Vertraege): Einheiten-Bootstrap ueber
# antithetische Paare, nullzentrierte p-Werte, getrennte Auswahl-/Final-
# Wuerfel (max_drawdown), Survivor-Schwelle 90 %, Ridge-Prior-Metrik,
# fail-closed ohne Validierungswuerfel, Prior-Context im Ergebnis.
#
# v8 (2026-10-19, MAXIMIZE-GOAL-001 + GOAL-HARDNESS-DEFAULT-001 +
# GOAL-HIERARCHY-001/-002 + DEMOTED-GOAL-WEIGHT-001, CIO-Entscheide): Ziel
# "Maximierung" als Log-Wachstumsterm; Haertegrad standardmaessig;
# erreichbare harte/primaere Ziele als Stufe 1 (Schranke G1* + eps);
# auf der Pruefmenge unerreichbare Ziele als Wunschziel (0.2, Volumen auf W0
# gedeckelt); ObjectiveContractV2. Doku: docs/planning/2026-10-18-maximize-
# goal-and-hardness.md. Bewusst neue Wuerfel (die Version geht in den Seed).
OPTIMIZER_ENGINE_VERSION = "saa_resampled_v8"

# Wirtschaftliche Goal-Felder. Bewusst NICHT enthalten: id, mandate_id,
# client_id, label, notes, linked_position_id (eine ID), Zeitstempel und
# Scoring-Cache-Felder. Ein identisch neu erfasstes Ziel hat damit denselben
# Fingerabdruck -- und dieselbe Strategie.
GOAL_ECONOMIC_FIELDS = (
    "goal_family",
    "goal_type",
    "goal_scope",
    "rank",
    "weight_bps",
    "hardness",
    "value_mode",
    "target_amount_rappen",
    "target_wealth_rappen",
    "target_return_bps",
    "success_probability_min_x100",
    "probability_pct",
    "start_date",
    "target_date",
    "horizon_years",
    "is_ongoing",
    "frequency",
    "pension_pillar",
    "is_active",
    "is_included",
    "lifecycle_decision",
)


# Goal-Datumsfelder gehen RELATIV zum Bewertungsjahr in den Fingerabdruck
# ein (SAA-SEED-FLOAT-ROBUST-001): die Engine modelliert Ziele auf
# Kalenderjahr-Achsen relativ zu ``date.today().year`` (ADR-2,
# goal_liabilities). Wirtschaftlich identische Laeufe (gleiche Jahres-Offsets)
# ziehen damit denselben Wuerfel -- auch ueber Kalenderjahre hinweg --,
# waehrend ein Jahreswechsel, der die effektiven Liabilities verschiebt,
# bewusst einen neuen Wuerfel zieht.
_GOAL_DATE_FIELDS = frozenset({"start_date", "target_date"})


def _seed_goal_date(value, valuation_year: int):
    if value is None:
        return None
    text = str(value)[:10]
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return _seed_scalar(value)
    return f"Y{parsed.year - int(valuation_year):+d}-{parsed.month:02d}-{parsed.day:02d}"


def _seed_scalar(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, float):
        return repr(value)
    return str(value)


def goal_economic_fingerprint(
    goals: Iterable,
    *,
    valuation_year: int | None = None,
) -> list[str]:
    """Kanonische, ID-freie Darstellung der Ziele (sortiert).

    Datumsfelder relativ zu ``valuation_year`` (Default: laufendes
    Kalenderjahr, wie die Liability-Achse der Engine).
    """
    year = int(valuation_year) if valuation_year is not None else date.today().year
    rows = []
    for goal in goals or ():
        if isinstance(goal, Mapping):
            raw = {name: goal.get(name) for name in GOAL_ECONOMIC_FIELDS}
        else:
            raw = {name: getattr(goal, name, None) for name in GOAL_ECONOMIC_FIELDS}
        row = {
            name: (
                _seed_goal_date(value, year)
                if name in _GOAL_DATE_FIELDS
                else _seed_scalar(value)
            )
            for name, value in raw.items()
        }
        rows.append(json.dumps(row, sort_keys=True, separators=(",", ":")))
    return sorted(rows)


def optimizer_content_seed(
    *,
    scenario_inputs: ScenarioInputs,
    goals: Iterable,
    score_x10: int,
    horizon_years: int,
    scenario_horizon_years: int,
    n_paths: int,
    salt: tuple = (),
) -> int:
    """Seed aus dem WIRTSCHAFTLICHEN Inhalt eines Optimierungslaufs.

    Eingehen: der Digest der effektiven ScenarioInputs (mu, sigma, Schiefe,
    Kurtosis, Cholesky der Korrelation -- also CMA-Werte inklusive
    Sub-Klassen-Annahmen und Korrelationsstruktur), die kanonisch sortierten
    wirtschaftlichen Goal-Felder, Score, Horizonte, Pfadzahl und die
    Engine-Version. Nie Datenbank-IDs.

    Laeuft ueber ``deterministic_seed`` (SHA-256), damit es genau EINE
    Hash-Konstruktion fuer Seeds gibt.
    """
    return deterministic_seed(
        OPTIMIZER_SEED_SCHEME,
        OPTIMIZER_ENGINE_VERSION,
        scenario_inputs_seed_digest(scenario_inputs),
        json.dumps(goal_economic_fingerprint(goals), separators=(",", ":")),
        int(score_x10),
        int(horizon_years),
        int(scenario_horizon_years),
        int(n_paths),
        *salt,
    )


def sensitivity_content_seed(
    *,
    cma,
    sub_allocations: list[dict] | None,
    goals: Iterable,
    target_goal,
    score_x10: int,
    horizon_years: int,
    scenario_horizon_years: int,
    n_paths: int,
) -> int:
    """Gepinnter Inhalts-Seed der Goal-Sensitivity.

    Baseline und Variante teilen ihn (Common Random Numbers, siehe
    GOAL-SENSITIVITY-COMMON-BASELINE-001). Er unterscheidet sich vom
    Generierungs-Seed durch das Salz ``("sensitivity", <Fingerabdruck des
    variierten Ziels>)`` -- verschiedene ZIELE bleiben getrennt, aber wie beim
    Generierungs-Seed ohne jede Datenbank-ID.
    """
    canonical_sub_allocations = _canonicalize_sub_allocations(sub_allocations)
    inputs = scenario_inputs_from_cma(
        cma, sub_allocations=list(canonical_sub_allocations) or None,
    )
    return optimizer_content_seed(
        scenario_inputs=inputs,
        goals=goals,
        score_x10=score_x10,
        horizon_years=horizon_years,
        scenario_horizon_years=scenario_horizon_years,
        n_paths=n_paths,
        salt=("sensitivity", *goal_economic_fingerprint([target_goal])),
    )


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


def _minimum_risk_allocation(
    bounds: list[tuple[float, float]],
    risky_fraction_per_bucket: dict[str, float] | None = None,
) -> np.ndarray:
    """Construct the lowest-risk feasible point inside the allocation bounds."""
    lo = np.array([b[0] for b in bounds], dtype=np.float64)
    hi = np.array([b[1] for b in bounds], dtype=np.float64)
    weights = lo.copy()
    remaining = 1.0 - float(weights.sum())
    if remaining <= 1e-12:
        return _normalize_to_bounds(weights, bounds)

    rf_map = (
        DEFAULT_BUCKET_RISKY_FRACTION
        if risky_fraction_per_bucket is None
        else risky_fraction_per_bucket
    )
    bucket_order = sorted(
        range(len(bounds)),
        key=lambda i: (
            float(rf_map.get(BUCKET_ORDER[i], 0.0)),
            0 if BUCKET_ORDER[i] == "liquidity" else 1,
            i,
        ),
    )
    for idx in bucket_order:
        capacity = max(0.0, float(hi[idx] - weights[idx]))
        add = min(remaining, capacity)
        weights[idx] += add
        remaining -= add
        if remaining <= 1e-12:
            break
    return _normalize_to_bounds(weights, bounds)


def _covariance_bps_from_scenario_inputs(
    sigma_bps: np.ndarray,
    cholesky: np.ndarray,
) -> np.ndarray | None:
    """Baut die Kovarianzmatrix (bps^2-Einheiten) aus Vol-Vektor + Cholesky.

    `cholesky` ist die Cholesky-Zerlegung der (dimensionslosen) Korrelations-
    matrix (siehe scenario_engine.scenario_inputs_from_cma / _safe_cholesky).
    Es gilt L @ L.T = Korrelation, also:

        Cov = D @ Korrelation @ D = (D @ L) @ (D @ L).T,  D = diag(sigma_bps)

    Diese Konstruktion ist per Definition PSD (kein Risiko einer nicht-
    positiv-definiten Matrix durch Rundungsfehler in einer separat
    gespeicherten Korrelationsmatrix). Bei Shape-Mismatch oder NaN/Inf wird
    None zurueckgegeben (Caller behandelt das als "Markowitz-Kandidat
    nicht verfuegbar", kein Crash).
    """
    try:
        sigma = np.asarray(sigma_bps, dtype=np.float64)
        chol = np.asarray(cholesky, dtype=np.float64)
        n = sigma.shape[0]
        if chol.shape != (n, n):
            return None
        d_chol = np.diag(sigma) @ chol
        cov = d_chol @ d_chol.T
        if not np.all(np.isfinite(cov)):
            return None
        return cov
    except Exception:  # noqa: BLE001 - defensive, darf Solver nie crashen
        return None


def _markowitz_min_variance_candidate(
    bounds: list[tuple[float, float]],
    mu_bps: np.ndarray | None,
    cov_bps: np.ndarray | None,
) -> np.ndarray | None:
    """PAR-5 (3eyes-Parity): Markowitz-informierter Multi-Start-Kandidat.

    Loest ein kleines quadratisches Programm auf der Effizienzgrenze:

        minimiere   w^T * Cov * w                 (Portfolio-Varianz)
        unter       sum(w) == 1
                    w^T * mu >= target_return      (Mindest-Rendite)
                    lo_i <= w_i <= hi_i             (dieselben Bucket-Bands)

    `target_return` ist die erwartete Rendite des bereits vorhandenen
    Mid-of-Bounds-Kandidaten - so bleibt der Markowitz-Punkt konsistent zum
    House-Matrix-Risikoniveau statt einen willkuerlichen neuen Rendite-
    Zielwert einzufuehren. Das Ergebnis liegt (naeherungsweise, siehe unten)
    auf der Markowitz-Effizienzgrenze innerhalb der Bucket-Bands - analog zu
    3eyes, das ebenfalls von der Effizienzgrenze aus startet.

    Dies ist ein echtes QP via scipy.optimize.minimize(method="SLSQP"),
    nicht nur eine Naeherung - scipy ist bereits Kern-Dependency des Solvers
    (siehe _solve_single_start weiter unten im selben Modul).

    Guard (Punkt 5 des Auftrags): bei jedem Fehler (Shape-Mismatch, NaN/Inf,
    SLSQP-Exception, degenerierte/nicht handhabbare Kovarianz) wird None
    zurueckgegeben. Der Aufrufer laesst den Kandidaten dann einfach weg -
    kein Crash des gesamten Solver-Laufs.
    """
    if mu_bps is None or cov_bps is None:
        return None
    n = len(bounds)
    try:
        mu = np.asarray(mu_bps, dtype=np.float64)
        cov = np.asarray(cov_bps, dtype=np.float64)
        if mu.shape != (n,) or cov.shape != (n, n):
            return None
        if not np.all(np.isfinite(mu)) or not np.all(np.isfinite(cov)):
            return None

        mid = np.array([(lo + hi) / 2.0 for lo, hi in bounds], dtype=np.float64)
        x0 = _normalize_to_bounds(mid, bounds)
        target_return = float(x0 @ mu)

        def _variance(w: np.ndarray) -> float:
            return float(w @ cov @ w)

        def _variance_grad(w: np.ndarray) -> np.ndarray:
            return 2.0 * (cov @ w)

        cons = [
            {
                "type": "eq",
                "fun": lambda w: float(np.sum(w) - 1.0),
                "jac": lambda w: np.ones_like(w),
            },
            {
                "type": "ineq",
                "fun": lambda w: float(w @ mu - target_return),
                "jac": lambda w: mu,
            },
        ]
        result = minimize(
            _variance,
            x0=x0,
            jac=_variance_grad,
            method="SLSQP",
            bounds=bounds,
            constraints=cons,
            options={"maxiter": 100, "ftol": 1e-9, "disp": False},
        )
        raw_x = getattr(result, "x", None)
        if raw_x is None:
            return None
        candidate = np.asarray(raw_x, dtype=np.float64)
        if candidate.shape != (n,) or not np.all(np.isfinite(candidate)):
            return None
        return _normalize_to_bounds(np.clip(candidate, 0.0, 1.0), bounds)
    except Exception:  # noqa: BLE001 - defensive, darf Solver nie crashen
        return None


def build_initial_guesses(
    bounds: list[tuple[float, float]],
    score_x10: int,
    mu_bps: np.ndarray | None = None,
    cov_bps: np.ndarray | None = None,
    risky_fraction_per_bucket: dict[str, float] | None = None,
) -> list[np.ndarray]:
    """Liefert Multi-Start-Initials, alle innerhalb der Bounds und summe~1.

    OWNER-DECISION OD-5: Multi-Start verbessert SLSQP-Robustheit gegen
    Lokal-Minima. Erzeugte Kandidaten:
    1. Mid-of-bounds (zentral)
    2. Conservative: max Liquiditaet, min Risiko
    3. Aggressive: max Equities, in Bounds
    4. Risk-cap-edge: Risky-Fraction-Limit voll ausnutzen
    5. Equal: 1/n pro Bucket (Default-Diversifikation)
    6. PAR-5 (optional, additiv): Markowitz-Min-Varianz-Punkt aus CMA
       (expected returns `mu_bps` + Kovarianz `cov_bps`), nur wenn beide
       Parameter uebergeben werden und das QP loesbar ist. Backwards-Compat:
       ohne mu_bps/cov_bps (Default None) bleibt das Verhalten exakt wie
       zuvor (Kandidaten 1-5, unveraendert).

    Infeasible-Kandidaten (z.B. wegen pathologischer Bounds) werden gefiltert.
    Mindestens 1 Kandidat (Mid-of-Bounds) wird auch dann zurueckgegeben wenn
    er nicht 100% feasible ist - damit der Solver nie ohne Start dasteht.
    """
    n = len(bounds)
    candidates: list[np.ndarray] = []

    # 1. Mid-of-bounds
    mid = np.array([(lo + hi) / 2.0 for lo, hi in bounds])
    candidates.append(_normalize_to_bounds(mid, bounds))

    # 2. Conservative: minimum risky fraction inside the hard bounds
    cons = _minimum_risk_allocation(
        bounds,
        risky_fraction_per_bucket=risky_fraction_per_bucket,
    )
    liq_idx = BUCKET_ORDER.index("liquidity")
    candidates.append(cons)

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

    # 6. PAR-5 (additiv, optional): Markowitz-Min-Varianz-Punkt aus der CMA.
    # Nur hinzugefuegt wenn mu_bps/cov_bps uebergeben wurden UND das QP
    # ein brauchbares Ergebnis liefert - sonst bleibt das Set bei 5
    # Kandidaten (identisch zum bisherigen Verhalten).
    markowitz = _markowitz_min_variance_candidate(bounds, mu_bps, cov_bps)
    if markowitz is not None:
        candidates.append(markowitz)

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
    """Run one SLSQP start without reclassifying exceptions as divergence.

    A returned ``OptimizeResult(success=False)`` is an expected numerical
    non-convergence and the multi-start caller can continue.  An exception is
    different: it may be a domain/programming defect and must reach the strict
    production boundary, which alone owns the explicit technical-error
    allowlist for the audited House fallback.
    """
    return minimize(
        objective_fn,
        x0=x0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": max_iter, "ftol": ftol, "disp": False},
    )


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

    # As with SLSQP, only a returned non-success result is convergence state.
    # Exceptions must retain their type so domain/programming errors cannot be
    # laundered into a normal House fallback by the caller.
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


def _finite_feasible_candidate(
    result: OptimizeResult,
    objective_fn,
    bounds: list[tuple[float, float]],
    constraints: list[dict],
) -> tuple[np.ndarray, float] | None:
    """Return a normalized candidate when SciPy reports non-success but gave one.

    Stage 9 hardens the optimizer against SLSQP status false-positives such as
    "Inequality constraints incompatible" on non-smooth chance-constraint
    objectives. A candidate is accepted only after an independent strict
    feasibility check against bounds, sum-to-one and risk-cap constraints.

    SOLVER-CANDIDATE-ACCEPTANCE-001 (Kontrollrunde 2026-09-28): die Reparatur
    (Clip auf [0,1] + Renormierung auf sum=1) darf nur an einem Rohkandidaten
    ansetzen, der VOR der Reparatur schon nahe an sum=1/Bounds liegt -- sonst
    kann ein grob infeasibler Rohvektor (z.B. ein abgebrochener Solver-Versuch
    mit x=[2,2,2,2,2]) durch die Reparatur zufaellig "feasible" werden und
    faelschlich als `converged_robustified` aktivierbar sein, obwohl weder ein
    erfolgreicher Solver noch ein von ihm gelieferter zulaessiger Kandidat
    vorlag.
    """
    raw_x = getattr(result, "x", None)
    if raw_x is None:
        return None
    try:
        x = np.asarray(raw_x, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if x.shape != (len(bounds),) or not np.all(np.isfinite(x)):
        return None
    if not _is_within_bounds(x, bounds, tol=_RAW_CANDIDATE_REPAIR_TOL):
        return None
    candidate = _normalize_to_bounds(np.clip(x, 0.0, 1.0), bounds)
    feasible, _violations = is_feasible(
        candidate,
        bounds=bounds,
        constraints=constraints,
    )
    if not feasible:
        return None
    # A non-finite value is a rejected candidate.  An exception is not a
    # candidate property and therefore must not be hidden as non-convergence.
    objective = float(objective_fn(candidate))
    if not np.isfinite(objective):
        return None
    return candidate, objective


def _candidate_risky_fraction(
    weights: np.ndarray,
    risky_fraction_per_bucket: dict[str, float] | None,
) -> float:
    """Compute realized risky fraction for robustified candidate tie-breaks."""
    rf_map = (
        DEFAULT_BUCKET_RISKY_FRACTION
        if risky_fraction_per_bucket is None
        else risky_fraction_per_bucket
    )
    risky_vector = np.array(
        [float(rf_map.get(bucket, 0.0)) for bucket in BUCKET_ORDER],
        dtype=np.float64,
    )
    return float(np.dot(weights, risky_vector))


def _derisk_candidate_near_best(
    selected_weights: np.ndarray,
    *,
    objective_fn,
    objective_value: float,
    bounds: list[tuple[float, float]],
    constraints: list[dict],
    risky_fraction_per_bucket: dict[str, float] | None,
) -> tuple[np.ndarray, float] | None:
    """Move robustified candidates toward the lowest-risk feasible start.

    This is used only after SciPy reported non-success. At that point the
    objective is already numerically fragile, so 3eyes' "so viel Risiko wie
    noetig" rule is a better deterministic tie-break than accepting a
    platform-specific high-risk candidate by a tiny objective edge.
    """
    conservative_anchor = _minimum_risk_allocation(
        bounds,
        risky_fraction_per_bucket,
    )
    objective_limit = objective_value + max(
        abs(objective_value) * _ROBUSTIFIED_DERISK_REL_TOL,
        1e-9,
    )
    best_weights = selected_weights
    best_objective = float(objective_value)
    best_key = (
        _candidate_risky_fraction(best_weights, risky_fraction_per_bucket),
        float(best_weights[BUCKET_ORDER.index("equities")]),
        best_objective,
    )
    for alpha in np.linspace(0.05, 1.0, 20):
        trial = _normalize_to_bounds(
            ((1.0 - float(alpha)) * selected_weights) + (float(alpha) * conservative_anchor),
            bounds,
        )
        feasible, _violations = is_feasible(
            trial,
            bounds=bounds,
            constraints=constraints,
        )
        if not feasible:
            continue
        trial_objective = float(objective_fn(trial))
        if not np.isfinite(trial_objective) or trial_objective > objective_limit:
            continue
        trial_key = (
            _candidate_risky_fraction(trial, risky_fraction_per_bucket),
            float(trial[BUCKET_ORDER.index("equities")]),
            trial_objective,
        )
        if trial_key < best_key:
            best_weights = trial
            best_objective = trial_objective
            best_key = trial_key
    if np.allclose(best_weights, selected_weights, atol=1e-9, rtol=0.0):
        return None
    return best_weights, best_objective


def run_solver(
    *,
    cma,
    goals: list,
    house_matrix_row,
    score_x10: int,
    advisory_wealth_rappen: int,
    cashflow_series_rappen: Iterable[int],
    external_wealth_rappen: int = 0,
    external_wealth_series_rappen: Iterable[int] | None = None,
    horizon_years: int = 10,
    scenario_horizon_years: int | None = None,
    n_paths: int = 2000,
    seed: int | None = None,
    inflation_series_bps: list[int] | None = None,
    risky_fraction_per_bucket: dict[str, float] | None = None,
    max_risky_fraction_bps: int | None = None,
    max_iter: int = 50,
    ftol: float = 1e-6,
    client_birth_year: int | None = None,
    client_sex: str | None = None,
    use_mortality_simulation: bool = False,
    mortality_fixed_offset_years: int | None = None,
    # Sprint U-P2 Fix C9: tax-aware Solver-Optionen (Backwards-Compat: alle None)
    tax_regime: object | None = None,
    dividend_yield_bps_per_bucket: np.ndarray | None = None,
    base_calendar_year: int = 2026,
    mandate_age_at_start: int | None = None,
    is_retired: bool = False,
    # Sprint B1 (2026-06-07): Sub-Allocation-Aware Bucket-Returns
    sub_allocations: list[dict] | None = None,
    # Strict mandate-specific solver bounds. None keeps the legacy
    # House-Matrix extraction path byte-for-byte compatible.
    effective_bounds_bps: Mapping[str, tuple[int, int]] | None = None,
    # CERT-ALLOCATION-INTENT-001: optional, partial Soft-Preference Target
    # Intent -- forwarded into build_optimizer_context() when this call
    # builds its own context (optimizer_context=None). When a pre-built
    # context is supplied, that context's own preferred_target_bps is the
    # single source of truth and these are accepted-but-unused, consistent
    # with every other context-input kwarg in this signature.
    preferred_target_bps: Mapping[str, int] | None = None,
    preference_penalty_lambda: float | None = None,
    # Optional already-built source-of-truth context. Productive callers use
    # this to retain the exact context for validation/audited fallback and to
    # prevent any downstream rebuild with lost inputs.
    optimizer_context: OptimizerContext | None = None,
    # OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001: ein bereits aufgeloester
    # Lauf-Vertrag. Noetig fuer Aufrufer, die MEHRERE Laeufe vergleichen
    # muessen (die Goal-Sensitivity faehrt Baseline und Modified): loest jeder
    # Lauf seinen Vertrag selbst auf, kann das Delta zwei verschiedene
    # Mathematiken vergleichen. None heisst "eigenen aufloesen" -- der
    # Normalfall fuer einen einzelnen Lauf.
    objective_contract: ObjectiveContractV1 | None = None,
    # SAA-RESAMPLED-STABILITY-001: Hausmatrix-Zielquote als Anker des
    # Signifikanztests. None = aus `house_matrix_row` (target-Spalten)
    # ableiten; fehlen auch die, entfaellt der Test (im Audit ausgewiesen).
    house_anchor_bps: Mapping[str, int] | None = None,
    # SAA-RESAMPLED-STABILITY-001: None = Produktions-Resampling
    # (DEFAULT_RESAMPLING). Nur Vergleichsmessungen setzen SINGLE_CUBE.
    resampling: ResamplingConfig | None = None,
) -> OptimizerResult:
    """Mulvey-Light SLSQP Optimizer mit Resampled Efficiency.

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
    context = optimizer_context
    if context is None:
        context = build_optimizer_context(
            cma=cma,
            goals=list(goals),
            house_matrix_row=house_matrix_row,
            score_x10=score_x10,
            advisory_wealth_rappen=advisory_wealth_rappen,
            cashflow_series_rappen=cashflow_series_rappen,
            external_wealth_rappen=external_wealth_rappen,
            external_wealth_series_rappen=external_wealth_series_rappen,
            horizon_years=horizon_years,
            scenario_horizon_years=scenario_horizon_years,
            n_paths=n_paths,
            seed=seed,
            inflation_series_bps=inflation_series_bps,
            risky_fraction_per_bucket=risky_fraction_per_bucket,
            max_risky_fraction_bps=max_risky_fraction_bps,
            client_birth_year=client_birth_year,
            client_sex=client_sex,
            use_mortality_simulation=use_mortality_simulation,
            mortality_fixed_offset_years=mortality_fixed_offset_years,
            # Sprint U-P2 Fix C9
            tax_regime=tax_regime,
            dividend_yield_bps_per_bucket=dividend_yield_bps_per_bucket,
            base_calendar_year=base_calendar_year,
            mandate_age_at_start=mandate_age_at_start,
            is_retired=is_retired,
            # Sprint B1 (2026-06-07): Sub-Allocation
            sub_allocations=sub_allocations,
            effective_bounds_bps=effective_bounds_bps,
            preferred_target_bps=preferred_target_bps,
            preference_penalty_lambda=preference_penalty_lambda,
            objective_contract=objective_contract,
        )
    elif not isinstance(context, OptimizerContext):
        raise OptimizerInputError(
            "optimizer_context must be an OptimizerContext instance."
        )
    config = DEFAULT_RESAMPLING if resampling is None else resampling
    if not isinstance(config, ResamplingConfig):
        raise OptimizerInputError("resampling must be a ResamplingConfig instance.")

    if not config.enabled:
        # Einzelwuerfel-Altpfad: nur noch fuer gezielte Vergleichsmessungen
        # (z.B. "vorher"-Messung im Stabilitaetsnachweis). Kein produktiver
        # Aufrufer setzt ihn.
        selection = _select_cube_candidate(context, max_iter=max_iter, ftol=ftol)
        if selection.weights is None:
            return _house_midpoint_fallback_result(context, selection)
        weights = selection.weights
        # ---- 6c. OPTIMIZER-DRAWDOWN-CERTIFICATION-001: Drawdown-Rerank ----
        # Modus max_drawdown: alle zulaessigen Multi-Start-Finalisten auf dem
        # Validierungs-Cube mit dem verfeinerten Drawdown neu bewerten; die
        # Auswahl folgt dem validierten Objective.
        drawdown_certification: dict | None = None
        if objective_contract_of(context).objective_mode == OBJECTIVE_MAX_DRAWDOWN:
            # DRAWDOWN-HOLDOUT-REUSE-001: gerankt wird auf dem Auswahl-
            # Wuerfel; die Zielerreichung des Gewinners zertifiziert danach
            # der getrennte finale Holdout (_finalize_solver_result).
            certified_w, drawdown_certification = certify_drawdown_candidates(
                context,
                winner_weights=np.asarray(weights, dtype=np.float64),
                candidates=selection.finalists,
                validation=_build_selection_validation_context(context),
            )
            if certified_w is not None:
                weights = certified_w
        return _finalize_solver_result(
            context,
            selection=selection,
            weights=weights,
            advisory_wealth_rappen=advisory_wealth_rappen,
            cashflow_series_rappen=cashflow_series_rappen,
            drawdown_certification=drawdown_certification,
        )

    return _run_resampled_solver(
        context,
        config=config,
        house_anchor_bps=_resolve_house_anchor_bps(
            house_anchor_bps, house_matrix_row
        ),
        max_iter=max_iter,
        ftol=ftol,
        advisory_wealth_rappen=advisory_wealth_rappen,
        cashflow_series_rappen=cashflow_series_rappen,
    )


@dataclass
class _CubeSelection:
    """Ergebnis der Kandidatenauswahl auf EINEM Szenario-Wuerfel."""

    weights: np.ndarray | None
    objective: float
    total_iters: int
    n_starts: int
    attempt_summaries: list[dict]
    used_ga_fallback: bool
    accepted_feasible_non_success: bool
    robustification_derisked: bool
    # OPTIMIZER-DRAWDOWN-CERTIFICATION-001: zulaessige Multi-Start-Finalisten
    # (sauber konvergierter Lauf: nur konvergierte Starts) fuer den
    # Drawdown-Rerank des Einzelwuerfel-Pfads. Im Resampling-Pfad ungenutzt:
    # dort rankt der Rerank {Bag-Mittel, projiziertes Mittel, Hausmatrix-Anker}.
    finalists: list[dict] = field(default_factory=list)
    # GOAL-HIERARCHY-001: Audit der Stufe 1 (None ohne geschuetzte Ziele bzw.
    # in den Risikomass-Varianten).
    goal_protection: dict | None = None


# GOAL-HIERARCHY-001: Anzahl SLSQP-Starts der Stufe 1 (die besten Punkte
# nach exaktem G1; optimiert wird die glatte Naeherung von G1). Ist G1 an
# einem Punkt schon 0, entfaellt Stufe 1 (G1 >= 0).
GOAL_STAGE1_STARTS = 1
# Iterationsgrenze der Stufe-1-Suche (Laufzeitbudget Stage-8 <= 15 s): die
# Suche muss G1* nur nach unten verbessern; jede gefundene Verbesserung macht
# die Schranke strenger, ein vorzeitiger Abbruch macht sie hoechstens weiter.
GOAL_STAGE1_MAX_ITER = 25
# Punkte der Streckensuche, wenn die Stufe-1-Schranke bindet (t = 0, 0.1, ..1).
GOAL_SEGMENT_POINTS = 11
# Stufe-2-Multi-Starts, wenn herabgestufte Ziele vorliegen (siehe
# ``_select_cube_candidate_core``); sonst alle Startpunkte (bitidentisch).
GOAL_DEMOTED_STAGE2_STARTS = 2


class _EvaluationMemo:
    """Teilt die Simulation je Punkt zwischen Zielfunktion und Stufe-1-
    Nebenbedingung (SLSQP ruft beide am selben x auf)."""

    def __init__(self, context: OptimizerContext, capacity: int = 8):
        self._context = context
        self._capacity = int(capacity)
        self._store: dict[bytes, tuple] = {}

    def inputs(self, w: np.ndarray):
        w = np.asarray(w, dtype=np.float64)
        key = w.tobytes()
        hit = self._store.get(key)
        if hit is None:
            if len(self._store) >= self._capacity:
                self._store.pop(next(iter(self._store)))
            hit = _evaluation_inputs(self._context, w)
            self._store[key] = hit
        return hit


def _goal_protection_stage(
    context: OptimizerContext,
    initials: list[np.ndarray],
    memo: _EvaluationMemo,
    *,
    max_iter: int,
    ftol: float,
) -> dict | None:
    """GOAL-HIERARCHY-001, Stufe 1: ``G1* = min_w G1(w)`` auf diesem Wuerfel.

    Liefert die Schranke ``G1* + eps`` fuer Stufe 2 und den Stufe-1-
    Minimierer ``w1*`` (zulaessig fuer die Schranke per Konstruktion).
    None im Risikomass-Modus (Phase 2, eigener Auftrag), ohne geschuetzte
    Ziele oder ohne zulaessigen Startpunkt.

    Suche: exaktes G1 an allen zulaessigen Multi-Start-Punkten und an der
    Hausquote; von den besten Punkten aus SLSQP auf einer glatten Naeherung
    von G1 (``protected_goal_level_surrogate``: die Chance-Strafe ist mit dem
    harten Erfolgsindikator stueckweise konstant und fuer Gradienten
    unsichtbar), das Ergebnis wieder EXAKT bewertet. ``G1*`` ist das
    beste GEFUNDENE Minimum, kein globaler Beweis -- die Schranke ist damit
    eher zu weit als zu eng.
    """
    if objective_contract_of(context).objective_mode != OBJECTIVE_GOAL_SHORTFALL:
        return None
    n_cols = int(context.horizon_years) + 1
    protected = _stage1_liabilities(context)
    if not protected:
        return None
    goal_weighting_mode = objective_contract_of(context).goal_weighting_mode

    def level(w: np.ndarray) -> float:
        return _protected_level_from_inputs(context, memo.inputs(w))[0]

    house = context.house_prior_weights
    points = [np.asarray(x0, dtype=np.float64) for x0 in initials]
    if house is not None:
        points.append(np.asarray(house, dtype=np.float64))
    scored: list[tuple[float, int, np.ndarray]] = []
    for index, x0 in enumerate(points):
        ok, _violations = is_feasible(
            x0, bounds=context.bounds, constraints=context.scipy_constraints,
        )
        if not ok:
            continue
        value = level(x0)
        if np.isfinite(value):
            scored.append((float(value), index, x0))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]))
    best_level, _index, best_w = scored[0]
    n_solves = 0
    if best_level > 0.0:

        def smooth_part(w: np.ndarray) -> float:
            # Glatte Naeherung von G1 (Fehlbetrag exakt, Erfolgsindikator
            # logistisch geglaettet) -- nur fuer die Suche; entschieden wird
            # mit dem exakten G1 (``_finite_feasible_candidate(..., level)``).
            _factors, wealth, annualized_twr = memo.inputs(w)
            return protected_goal_level_surrogate(
                protected, wealth,
                initial_wealth_rappen=context.advisory_wealth_rappen,
                horizon_years=context.horizon_years,
                weights=context.scenario_weights,
                annualized_return_bps_per_path=annualized_twr,
                goal_weighting_mode=goal_weighting_mode,
            )

        # Numerik: SLSQP-ftol ist absolut -> relativ zum Startwert skaliert.
        unit = max(smooth_part(best_w), 1e-300)
        for _level, _i, x0 in scored[:GOAL_STAGE1_STARTS]:
            result = _solve_single_start(
                lambda w: smooth_part(w) / unit, x0,
                context.bounds, context.scipy_constraints,
                max_iter=min(int(max_iter), GOAL_STAGE1_MAX_ITER), ftol=ftol,
            )
            n_solves += 1
            candidate = _finite_feasible_candidate(
                result, level, context.bounds, context.scipy_constraints,
            )
            if candidate is not None and candidate[1] < best_level:
                best_w, best_level = candidate
    level_star, star_per_path = _protected_level_from_inputs(
        context, memo.inputs(best_w), with_per_path=True,
    )
    if house is not None:
        _house_level, house_per_path = _protected_level_from_inputs(
            context, memo.inputs(np.asarray(house, dtype=np.float64)),
            with_per_path=True,
        )
        standard_error = monte_carlo_standard_error(
            house_per_path - star_per_path, context.scenario_weights,
        )
        tolerance_basis = "paired_house_vs_stage1"
    else:
        standard_error = monte_carlo_standard_error(
            star_per_path, context.scenario_weights,
        )
        tolerance_basis = "stage1_point"
    # Haertegrad (GOAL-HARDNESS-DEFAULT-001): die statistische Toleranz wird
    # durch das hoechste Haertegrad-Gewicht der geschuetzten Ziele geteilt --
    # primaer (h = 1) darf innerhalb des Rauschens erodieren, sobald ein
    # hartes Ziel (h = 10) dabei ist nur um ein Zehntel davon.
    hardness_divisor = max(
        1.0, max(_goal_hardness_weight(liab, goal_weighting_mode) for liab in protected),
    )
    eps = (
        GOAL_EROSION_Z * float(standard_error) / hardness_divisor
        + GOAL_EROSION_NUMERIC_TOL
    )
    bound = float(level_star) + eps
    # Skala der Nebenbedingung: relativ zur Schranke, damit die absolute
    # Toleranz von is_feasible (1e-6) eine relative wird.
    constraint_unit = max(bound, 1e-12)

    def protection_slack(w: np.ndarray) -> float:
        return (bound - level(w)) / constraint_unit

    return {
        "policy": GOAL_HIERARCHY_POLICY_VERSION,
        "protected_goal_ids": [str(liab.goal_id) for liab in protected],
        "demoted_goal_ids": sorted(_demoted_goal_ids(context)),
        "level_star": float(level_star),
        "standard_error": float(standard_error),
        "tolerance_basis": tolerance_basis,
        "erosion_z": float(GOAL_EROSION_Z),
        "hardness_divisor": float(hardness_divisor),
        "erosion_tolerance": float(eps),
        "bound": bound,
        "stage1_solves": int(n_solves),
        "w_star": np.asarray(best_w, dtype=np.float64).copy(),
        "level": level,
        "constraint": {"type": "ineq", "fun": protection_slack},
    }


def _select_cube_candidate(
    context: OptimizerContext,
    *,
    max_iter: int,
    ftol: float,
) -> _CubeSelection:
    """Multi-Start-SLSQP + DE-Fallback + Stage-9-Robustifizierung auf einem Wuerfel.

    Unveraenderte Auswahl-Logik des bisherigen ``run_solver`` (Schritte 5-6);
    SAA-RESAMPLED-STABILITY-001 hat sie nur aus ``run_solver`` herausgeloest,
    damit dieselbe Logik auf jedem Bag-Wuerfel laeuft.

    GOAL-HIERARCHY-001: zuerst Stufe 1 (``_goal_protection_stage``), dann
    Stufe 2 als "lazy constraint": erfuellt das Optimum der vollen
    Zielfunktion die Schranke ``G1 <= G1* + eps`` bereits, ist es auch das
    Optimum unter der Schranke (gleiche Zielfunktion, kleinere zulaessige
    Menge, die es enthaelt). Nur sonst wird auf der Strecke zum
    Stufe-1-Minimierer der beste Punkt gewaehlt, der die Schranke exakt
    einhaelt. Gemessen: die Schranke als Dauer-Nebenbedingung kostete auf
    dem Fundament-Mandat x3.4 Laufzeit, sie band aber nur in 1-3 von 40
    Bags.
    """
    memo = _EvaluationMemo(context)
    initials = _cube_initial_guesses(context)
    protection = _goal_protection_stage(
        context, list(initials), memo, max_iter=max_iter, ftol=ftol,
    )
    selection = _select_cube_candidate_core(
        context, initials, memo, None, max_iter=max_iter, ftol=ftol,
        demoted_starts=(
            GOAL_DEMOTED_STAGE2_STARTS
            if protection is not None and protection["demoted_goal_ids"]
            else None
        ),
    )
    if protection is None:
        return selection
    level = protection["level"]
    bound = protection["bound"]
    tolerance = 1e-9 * max(1.0, abs(bound))
    if selection.weights is not None and level(selection.weights) <= bound + tolerance:
        selection.goal_protection = _goal_protection_audit(
            protection, selection.weights, constraint_pass=False,
        )
        return selection
    # Die Schranke bindet: zulaessige Punkte auf der Strecke vom Stufe-1-
    # Minimierer w1* (erfuellt sie per Konstruktion) zum Stufe-2-Optimum w2.
    # Die zulaessige Menge der linearen Nebenbedingungen ist konvex, jeder
    # Streckenpunkt also zulaessig; gewaehlt wird unter den Punkten, die die
    # Schranke EXAKT einhalten, der mit der kleinsten vollen Zielfunktion.
    # (Ein zweiter SLSQP-Lauf mit G1 als Nebenbedingung scheiterte gemessen an
    # der stueckweise konstanten Chance-Strafe und fiel in die DE-Suche:
    # +5 s je bindendem Bag.)
    w_star = np.asarray(protection["w_star"], dtype=np.float64)
    w_two = (
        w_star if selection.weights is None
        else np.asarray(selection.weights, dtype=np.float64)
    )
    best_w, best_value = w_star, float(_objective_from_inputs(
        context, w_star, memo.inputs(w_star),
    ))
    for t in np.linspace(0.0, 1.0, GOAL_SEGMENT_POINTS)[1:]:
        trial = _normalize_to_bounds((1.0 - t) * w_star + t * w_two, context.bounds)
        if level(trial) > bound + tolerance:
            continue
        ok, _violations = is_feasible(
            trial, bounds=context.bounds, constraints=context.scipy_constraints,
        )
        if not ok:
            continue
        value = float(_objective_from_inputs(context, trial, memo.inputs(trial)))
        if np.isfinite(value) and value < best_value:
            best_w, best_value = trial, value
    selection.weights = np.asarray(best_w, dtype=np.float64).copy()
    selection.objective = best_value
    selection.goal_protection = _goal_protection_audit(
        protection, selection.weights, constraint_pass=True,
    )
    return selection


def _cube_initial_guesses(context: OptimizerContext) -> list[np.ndarray]:
    """Multi-Start-Punkte eines Wuerfels (aus dem Context, nie aus der CMA)."""
    # PAR-5: zusaetzlicher Markowitz-Min-Varianz-Kandidat.  The retained
    # OptimizerContext is the sole source of truth: re-reading the separately
    # passed CMA here would allow the same context to produce different starts
    # (and potentially a different local optimum) after a CMA mutation.
    mu_bps_for_markowitz: np.ndarray | None = None
    cov_bps_for_markowitz: np.ndarray | None = None
    if context.scenario_mu_bps is not None and context.scenario_cov_bps2 is not None:
        candidate_mu = np.asarray(context.scenario_mu_bps, dtype=np.float64)
        candidate_cov = np.asarray(context.scenario_cov_bps2, dtype=np.float64)
        if (
            candidate_mu.shape == (N_BUCKETS,)
            and candidate_cov.shape == (N_BUCKETS, N_BUCKETS)
            and np.all(np.isfinite(candidate_mu))
            and np.all(np.isfinite(candidate_cov))
        ):
            mu_bps_for_markowitz = candidate_mu.copy()
            cov_bps_for_markowitz = candidate_cov.copy()
    return list(build_initial_guesses(
        context.bounds, context.score_x10,
        mu_bps=mu_bps_for_markowitz,
        cov_bps=cov_bps_for_markowitz,
        risky_fraction_per_bucket=context.risky_fraction_per_bucket,
    ))


def _select_cube_candidate_core(
    context: OptimizerContext,
    initials: list[np.ndarray],
    memo: _EvaluationMemo,
    protection: dict | None,
    *,
    max_iter: int,
    ftol: float,
    demoted_starts: int | None = None,
) -> _CubeSelection:
    """Auswahl auf einem Wuerfel; mit ``protection`` unter der Stufe-1-Schranke."""
    seed = context.seed
    n_paths = context.n_paths
    bounds = context.bounds
    scipy_constraints = context.scipy_constraints

    # ---- 5. Objective Closure ueber den Context ----
    def objective_fn(w: np.ndarray) -> float:
        return _objective_from_inputs(context, w, memo.inputs(w))

    # ---- 6. Multi-Start SLSQP ----
    # ---- 5b. GOAL-HIERARCHY-001: Stufe-2-Lauf unter der Stufe-1-Schranke ----
    # Der Stufe-1-Minimierer ist zulaessiger Rueckfall-Kandidat (erfuellt die
    # Schranke per Konstruktion).
    if protection is not None:
        scipy_constraints = list(scipy_constraints) + [protection["constraint"]]
    best_result: OptimizeResult | None = None
    best_obj = float("inf")
    best_feasible_result: OptimizeResult | None = None
    best_feasible_w: np.ndarray | None = None
    best_feasible_obj = float("inf")
    best_feasible_source = ""
    finite_feasible_candidates: list[dict[str, object]] = []
    attempt_summaries: list[dict[str, object]] = []
    total_iters = 0
    used_ga_fallback = False
    accepted_feasible_non_success = False
    robustification_derisked = False
    if protection is not None:
        # Der Stufe-1-Minimierer erfuellt die Schranke per Konstruktion: er
        # ist immer ein zulaessiger Rueckfall-Kandidat (nie Hausmitte-
        # Fallback nur wegen der Zielhierarchie).
        w_star = protection["w_star"]
        star_objective = float(objective_fn(w_star))
        if np.isfinite(star_objective):
            finite_feasible_candidates.append({
                "result": OptimizeResult(
                    x=w_star.copy(), success=False, status=-1, nit=0,
                    message="goal_hierarchy_stage1_minimizer",
                ),
                "weights": w_star.copy(),
                "objective": star_objective,
                "source": "goal_hierarchy_stage1",
                "risky_fraction": _candidate_risky_fraction(
                    w_star, context.risky_fraction_per_bucket,
                ),
            })
            best_feasible_obj = star_objective
            best_feasible_w = w_star.copy()
            best_feasible_result = finite_feasible_candidates[-1]["result"]
            best_feasible_source = "goal_hierarchy_stage1"

    # STAGE2-OBJECTIVE-SCALE-001 (Laufzeit, CIO-Review #650): SLSQP prueft
    # ``ftol`` ABSOLUT. Liegt die Zielfunktion weit ueber 1 (grosse
    # Fehlbetraege, z. B. ein herabgestuftes unerreichbares Ziel), verlangt
    # das eine relative Genauigkeit von 1e-7 und kostet Iterationen ohne
    # Allokationswirkung. Der Solver sieht darum f / s mit
    # s = max(1, |f| am besten Startpunkt): gleiches argmin, ftol relativ.
    # Fuer |f| <= 1 (alle Golden-Mandate) ist s = 1 -- bitidentisch.
    # Bewertet und verglichen wird weiterhin mit dem unskalierten f.
    start_values = [
        abs(float(objective_fn(np.asarray(x0, dtype=np.float64)))) for x0 in initials
    ]
    finite_starts = [v for v in start_values if np.isfinite(v)]
    objective_unit = max(1.0, min(finite_starts)) if finite_starts else 1.0
    if protection is None and demoted_starts is not None and len(initials) > demoted_starts:
        # GOAL-HIERARCHY-002 (Laufzeit): mit herabgestuften (auf der
        # Pruefmenge unerreichbaren) Zielen dominiert deren Fehlbetrag die
        # Stufe-2-Zielfunktion, und die Stufe-1-Schranke bestimmt das
        # Ergebnis (Streckensuche). Der Multi-Start sucht dann nur die
        # Richtung w2 -- die besten Startpunkte nach f genuegen.
        order = sorted(
            range(len(initials)),
            key=lambda i: (start_values[i] if np.isfinite(start_values[i]) else np.inf, i),
        )[:demoted_starts]
        initials = [initials[i] for i in sorted(order)]
    if objective_unit == 1.0:
        solver_objective_fn = objective_fn
    else:
        def solver_objective_fn(w: np.ndarray) -> float:
            return objective_fn(w) / objective_unit

    for x0 in initials:
        attempt_started = time.perf_counter()
        result = _solve_single_start(
            solver_objective_fn, x0, bounds, scipy_constraints,
            max_iter=max_iter, ftol=ftol,
        )
        elapsed_ms = int(round((time.perf_counter() - attempt_started) * 1000))
        total_iters += int(getattr(result, "nit", 0) or 0)
        candidate = _finite_feasible_candidate(
            result,
            objective_fn,
            bounds,
            scipy_constraints,
        )
        if candidate is not None:
            candidate_w, candidate_obj = candidate
            finite_feasible_candidates.append({
                "result": result,
                "weights": candidate_w,
                "objective": candidate_obj,
                "source": "slsqp",
                "risky_fraction": _candidate_risky_fraction(
                    candidate_w,
                    context.risky_fraction_per_bucket,
                ),
            })
            if candidate_obj < best_feasible_obj:
                best_feasible_obj = candidate_obj
                best_feasible_result = result
                best_feasible_w = candidate_w
                best_feasible_source = "slsqp"
            if bool(getattr(result, "success", False)) and candidate_obj < best_obj:
                result.x = candidate_w
                best_obj = candidate_obj
                best_result = result
        attempt_summaries.append({
            "attempt": len(attempt_summaries) + 1,
            "stage": "slsqp",
            "status": "converged" if bool(getattr(result, "success", False)) else "non_success",
            "solver_status": int(getattr(result, "status", 0) or 0),
            "message": str(getattr(result, "message", "") or "")[:240],
            "reason": (
                "solver_success"
                if bool(getattr(result, "success", False))
                else "solver_no_convergence"
            ),
            "objective_value": (
                float(candidate[1]) if candidate is not None else None
            ),
            "feasible_candidate": candidate is not None,
            "n_paths": int(n_paths),
            "n_starts": int(len(initials)),
            "seed": int(seed),
            "elapsed_ms": elapsed_ms,
        })

    # ---- 6b. Phase 5.3 GA-Fallback wenn alle SLSQP-Starts divergiert ----
    if best_result is None:
        attempt_started = time.perf_counter()
        ga_result = _solve_via_genetic_algorithm(
            objective_fn, bounds, scipy_constraints, seed=seed,
        )
        elapsed_ms = int(round((time.perf_counter() - attempt_started) * 1000))
        total_iters += int(getattr(ga_result, "nit", 0) or 0)
        candidate = _finite_feasible_candidate(
            ga_result,
            objective_fn,
            bounds,
            scipy_constraints,
        )
        if candidate is not None:
            candidate_w, candidate_obj = candidate
            finite_feasible_candidates.append({
                "result": ga_result,
                "weights": candidate_w,
                "objective": candidate_obj,
                "source": "differential_evolution",
                "risky_fraction": _candidate_risky_fraction(
                    candidate_w,
                    context.risky_fraction_per_bucket,
                ),
            })
            if candidate_obj < best_feasible_obj:
                best_feasible_obj = candidate_obj
                best_feasible_result = ga_result
                best_feasible_w = candidate_w
                best_feasible_source = "differential_evolution"
            if bool(getattr(ga_result, "success", False)) and candidate_obj < float("inf"):
                ga_result.x = candidate_w
                best_obj = candidate_obj
                best_result = ga_result
                used_ga_fallback = True
        attempt_summaries.append({
            "attempt": len(attempt_summaries) + 1,
            "stage": "differential_evolution",
            "status": "converged" if bool(getattr(ga_result, "success", False)) else "non_success",
            "solver_status": int(getattr(ga_result, "status", 0) or 0),
            "message": str(getattr(ga_result, "message", "") or "")[:240],
            "reason": (
                "ga_success"
                if bool(getattr(ga_result, "success", False))
                else "ga_no_convergence"
            ),
            "objective_value": (
                float(candidate[1]) if candidate is not None else None
            ),
            "feasible_candidate": candidate is not None,
            "n_paths": int(n_paths),
            "n_starts": int(len(initials)),
            "seed": int(seed),
            "elapsed_ms": elapsed_ms,
        })

    if best_result is None and finite_feasible_candidates:
        objective_floor = min(
            float(candidate["objective"])
            for candidate in finite_feasible_candidates
        )
        objective_limit = objective_floor + max(
            abs(objective_floor) * _ROBUSTIFIED_OBJECTIVE_TIE_REL_TOL,
            1e-9,
        )
        near_best_candidates = [
            candidate
            for candidate in finite_feasible_candidates
            if float(candidate["objective"]) <= objective_limit
        ]
        # 3eyes-Logik: so viel Risiko wie noetig, aber bei praktisch
        # gleichwertiger Zielerreichung die defensivere Allocation nehmen.
        chosen_candidate = min(
            near_best_candidates,
            key=lambda candidate: (
                float(candidate["risky_fraction"]),
                float(np.asarray(candidate["weights"])[BUCKET_ORDER.index("equities")]),
                float(candidate["objective"]),
            ),
        )
        best_feasible_result = chosen_candidate["result"]  # type: ignore[assignment]
        best_feasible_w = np.asarray(
            chosen_candidate["weights"],
            dtype=np.float64,
        )
        best_feasible_obj = float(chosen_candidate["objective"])
        best_feasible_source = str(chosen_candidate["source"])
        derisked = _derisk_candidate_near_best(
            best_feasible_w,
            objective_fn=objective_fn,
            objective_value=best_feasible_obj,
            bounds=bounds,
            constraints=scipy_constraints,
            risky_fraction_per_bucket=context.risky_fraction_per_bucket,
        )
        if derisked is not None:
            best_feasible_w, best_feasible_obj = derisked
            robustification_derisked = True

    if best_result is None and best_feasible_result is not None and best_feasible_w is not None:
        best_result = best_feasible_result
        best_result.x = best_feasible_w
        best_obj = best_feasible_obj
        accepted_feasible_non_success = True
        used_ga_fallback = best_feasible_source == "differential_evolution"

    return _CubeSelection(
        weights=(
            None
            if best_result is None
            else np.asarray(best_result.x, dtype=np.float64).copy()
        ),
        objective=float(best_obj),
        total_iters=int(total_iters),
        n_starts=int(len(initials)),
        attempt_summaries=attempt_summaries,
        used_ga_fallback=bool(used_ga_fallback),
        accepted_feasible_non_success=bool(accepted_feasible_non_success),
        robustification_derisked=bool(robustification_derisked),
        finalists=[
            candidate for candidate in finite_feasible_candidates
            if accepted_feasible_non_success
            or bool(getattr(candidate["result"], "success", False))
        ],
    )


def _contract_evidence(context: OptimizerContext) -> dict | None:
    """Nachweis-Block des Lauf-Vertrags (ObjectiveContractV2) fuer Audit und
    Modellbasis; None, wenn ein (Test-)Vertrag keinen Nachweis liefert."""
    as_evidence = getattr(objective_contract_of(context), "as_evidence", None)
    return as_evidence() if callable(as_evidence) else None


def _goal_protection_audit(
    protection: dict | None,
    weights: np.ndarray | None,
    *,
    constraint_pass: bool,
) -> dict | None:
    """Serialisierbarer Audit der Stufe 1 (GOAL-HIERARCHY-001)."""
    if protection is None:
        return None
    final_level = (
        None if weights is None else float(protection["level"](weights))
    )
    return {
        "policy": protection["policy"],
        "protected_goal_ids": list(protection["protected_goal_ids"]),
        "demoted_goal_ids": list(protection["demoted_goal_ids"]),
        "level_star": protection["level_star"],
        "standard_error": protection["standard_error"],
        "tolerance_basis": protection["tolerance_basis"],
        "erosion_z": protection["erosion_z"],
        "hardness_divisor": protection["hardness_divisor"],
        "erosion_tolerance": protection["erosion_tolerance"],
        "bound": protection["bound"],
        "final_level": final_level,
        "binding": (
            None if final_level is None
            else bool(final_level >= protection["bound"] - 1e-12 * max(1.0, abs(protection["bound"])))
        ),
        "stage1_solves": protection["stage1_solves"],
        # True: das Optimum der vollen Zielfunktion verletzte die Schranke,
        # die Auswahl lief ein zweites Mal mit ihr als Nebenbedingung.
        "constraint_pass": bool(constraint_pass),
        "w_star_bps": [int(round(x * 10000.0)) for x in protection["w_star"]],
    }


def _house_midpoint_fallback_result(
    context: OptimizerContext,
    selection: _CubeSelection,
    *,
    extra_reasoning: list[str] | None = None,
    resampling_payload: dict | None = None,
) -> OptimizerResult:
    """Schritt 7, Fallback-Zweig: kein zulaessiger Kandidat (OD-5)."""
    seed = context.seed
    n_paths = context.n_paths
    bounds = context.bounds
    total_iters = selection.total_iters
    attempt_summaries = selection.attempt_summaries
    n_starts = selection.n_starts
    # ---- 7. Status & Output ----
    # Auch GA divergiert -> Fallback House-Matrix
    mid = _normalize_to_bounds(
        np.array([(lo + hi) / 2.0 for lo, hi in bounds]),
        bounds,
    )
    weights_bps = _weights_to_bps_dict(mid, bounds=bounds)
    midpoint_w = _trusted_weights_bps_to_array(weights_bps)
    mid_wealth = _simulate_context_wealth(context, midpoint_w)
    # GOAL-ACHIEVABILITY-ATTRIBUTION-001: auch der House-Fallback publiziert
    # den typisierten Vertrag (Zielzeilen nach Prioritaet + Plan-Solvenz).
    goal_achievability = publish_goal_achievability(
        mid_wealth,
        context.liabilities,
        context.advisory_wealth_rappen,
        weights=context.scenario_weights,
        annualized_return_bps_per_path=_annualized_twr_bps_per_path(
            context, midpoint_w
        ),
    )
    fallback_preference_deviation = (
        preference_deviation_bps(weights_bps, context.preferred_target_bps)
        if context.preferred_target_bps
        else None
    )
    fallback_reasoning = [
        "Alle Solver-Multi-Starts divergierten und GA-Fallback ebenso. "
        "Fallback auf House-Matrix-Mittelwert (siehe OWNER-DECISION OD-5)."
    ] + list(context.bounds_collapse_warnings) + list(extra_reasoning or [])
    fallback_reasoning.extend(reachability_reasoning(context.goal_reachability))
    goal_achievability = annotate_reachability_rows(
        goal_achievability, context.goal_reachability,
    )
    if fallback_preference_deviation is not None:
        # CERT-ALLOCATION-INTENT-001 (spec Sec. 8): a Soft Preference is
        # never silently promoted to an exactly-active value just because
        # the solver fell back -- the fallback candidate is evaluated
        # under the same preference, deviation is disclosed, nothing is
        # published as if it matched the preference.
        fallback_reasoning.append(
            "Soft-Preference-Praeferenz (Policy "
            f"{context.soft_preference_policy_version}) war aktiv; "
            "der House-Matrix-Fallback wurde dagegen bewertet, nicht "
            f"exakt uebernommen. Abweichung Effektiv-vs-Praeferenz (bps): "
            f"{fallback_preference_deviation}."
        )
    return OptimizerResult(
        weights_bps=weights_bps,
        objective_value=float("inf"),
        iterations=total_iters,
        seed=seed,
        status="fallback_house_matrix",
        method="fallback_house_matrix",
        reasoning=fallback_reasoning,
        n_paths=n_paths,
        n_starts_attempted=n_starts,
        goal_achievability=tuple(goal_achievability),
        robustification={
            "enabled": True,
            "stage": "fallback_house_matrix",
            "attempts": attempt_summaries,
            "final_reason": "no_finite_feasible_candidate",
        },
        restart_results=tuple(attempt_summaries),
        preference_deviation_bps=fallback_preference_deviation,
        resampling=resampling_payload,
        importance_sampling=context.importance_sampling_audit,
        goal_reachability=context.goal_reachability,
        context=context,
    )


def _constraint_violation(
    w: np.ndarray, constraints: list[dict],
) -> float:
    return float(sum(
        max(0.0, -float(cons["fun"](w)))
        for cons in constraints
        if cons.get("type") == "ineq"
    ))


def _repair_rounded_bps(
    weights_bps: dict[str, int],
    bounds: list[tuple[float, float]],
    constraints: list[dict],
    *,
    max_steps: int = 20,
) -> dict[str, int] | None:
    """BPS-ROUNDING-ON-ACTIVE-CONSTRAINT-001 (2026-10-18).

    Liegt ein kontinuierlich zulaessiger Punkt GENAU auf einer linearen
    Nebenbedingung (Risikobudget mit nicht-ganzzahligen Risikoanteilen), kann
    die bps-Rundung sie um Bruchteile eines bps verletzen (gemessen: -5e-6
    am Referenzmandat M1). Mit dem Varianz-Tiebreak (w' Sigma w) landen
    ziel-sichere Mandate systematisch auf solchen Flaechen. Reparatur:
    greedy je 1 bps zwischen zwei Buckets verschieben (Bandbreiten
    eingehalten, Summe bleibt 10'000), jeweils die Verschiebung mit der
    kleinsten Restverletzung, bis zulaessig. None, wenn das nicht in
    ``max_steps`` Schritten gelingt (dann bleibt der Status
    ``diverged_infeasible``).
    """
    current = [int(weights_bps[bucket]) for bucket in BUCKET_ORDER]
    lo = [int(round(b[0] * 10000.0)) for b in bounds]
    hi = [int(round(b[1] * 10000.0)) for b in bounds]
    n = len(current)
    if any(not lo[k] <= current[k] <= hi[k] for k in range(n)) or sum(current) != 10000:
        # Nur fuer Verletzungen linearer Ungleichungen gedacht: eine
        # Bandbreiten- oder Summenverletzung der Rundung ist ein anderer
        # Defekt und bleibt sichtbar (Status diverged_infeasible).
        return None
    for _step in range(int(max_steps)):
        best: tuple[float, list[int]] | None = None
        for i in range(n):
            if current[i] - 1 < lo[i]:
                continue
            for j in range(n):
                if i == j or current[j] + 1 > hi[j]:
                    continue
                trial = list(current)
                trial[i] -= 1
                trial[j] += 1
                violation = _constraint_violation(
                    np.array(trial, dtype=np.float64) / 10000.0, constraints,
                )
                if best is None or violation < best[0]:
                    best = (violation, trial)
        if best is None:
            return None
        current = best[1]
        candidate = np.array(current, dtype=np.float64) / 10000.0
        ok, _reasons = is_feasible(candidate, bounds=bounds, constraints=constraints)
        if ok:
            return {bucket: current[k] for k, bucket in enumerate(BUCKET_ORDER)}
    return None


def _importance_sampling_reasoning(context: OptimizerContext) -> str:
    """Audit-Zeile zum Importance Sampling (IMPORTANCE-SAMPLING-ESS-001).

    Die Praefixe "Importance Sampling AKTIV/INAKTIV" sind Vertrag
    (advisory_report._detect_is_status_from_reasoning).
    """
    audit = context.importance_sampling_audit or {}
    if context.scenario_weights is not None:
        ess = audit.get("ess")
        ess_text = (
            f" Kish-ESS {float(ess):.0f} von {int(context.n_paths)} Pfaden "
            f"({100.0 * float(audit.get('ess_fraction') or 0.0):.0f} %), "
            f"Gewichte <= {float(audit.get('max_weight_bound') or 0.0):.1f}."
            if ess is not None
            else ""
        )
        return (
            "Importance Sampling AKTIV (Tail-Schutz fuer Shortfall-Berechnung; "
            "defensive Mischung, horizont-skalierter Aktien-Shift). "
            "Achievability-Wahrscheinlichkeiten sind likelihood-ratio-gewichtet "
            "und selbstnormiert." + ess_text
        )
    if audit.get("fallback"):
        return (
            "Importance Sampling INAKTIV (Standard-MC, uniformer Sample-Mean): "
            f"Kish-ESS {float(audit.get('ess') or 0.0):.0f} unter der Schwelle "
            f"{100.0 * float(audit.get('ess_fallback_fraction') or 0.0):.0f} % "
            "der Pfade -- Rueckfall auf Standard-MC."
        )
    return "Importance Sampling INAKTIV (Standard-MC, uniformer Sample-Mean)."


def _finalize_solver_result(
    context: OptimizerContext,
    *,
    selection: _CubeSelection,
    weights: np.ndarray,
    advisory_wealth_rappen: int,
    cashflow_series_rappen: Iterable[int],
    extra_reasoning: list[str] | None = None,
    resampling_payload: dict | None = None,
    drawdown_certification: dict | None = None,
) -> OptimizerResult:
    """Schritt 7-8: Rundung, Status, Nachzertifizierung, Audit-Trail, Stress.

    Unveraenderte Abschluss-Logik des bisherigen ``run_solver``. Seit
    SAA-RESAMPLED-STABILITY-001 bekommt sie die finale Gewichtung explizit
    (Bag-Mittel bzw. Hausmatrix-Anker) und bewertet sie auf dem
    HAUPT-Wuerfel ``context`` -- derselbe Wuerfel, den alle nachgelagerten
    Konsumenten ueber ``result.context`` sehen.
    """
    seed = context.seed
    horizon_years = context.horizon_years
    n_paths = context.n_paths
    aggregated_liability = context.aggregated_liability_path
    bounds = context.bounds
    scipy_constraints = context.scipy_constraints
    total_iters = selection.total_iters
    attempt_summaries = selection.attempt_summaries
    used_ga_fallback = selection.used_ga_fallback
    accepted_feasible_non_success = selection.accepted_feasible_non_success
    robustification_derisked = selection.robustification_derisked
    n_starts = selection.n_starts

    # Final clip + renorm + feasibility check
    final_w = _normalize_to_bounds(np.clip(weights, 0.0, 1.0), bounds)
    continuous_feasible, continuous_violation_reasons = is_feasible(
        final_w, bounds=bounds, constraints=scipy_constraints,
    )

    weights_bps = _weights_to_bps_dict(final_w, bounds=bounds)
    rounded_w = _trusted_weights_bps_to_array(weights_bps)
    rounded_feasible, rounded_violation_reasons = is_feasible(
        rounded_w,
        bounds=bounds,
        constraints=scipy_constraints,
    )
    if continuous_feasible and not rounded_feasible:
        repaired = _repair_rounded_bps(weights_bps, bounds, scipy_constraints)
        if repaired is not None:
            weights_bps = repaired
            rounded_w = _trusted_weights_bps_to_array(weights_bps)
            rounded_feasible, rounded_violation_reasons = True, []

    # The integer-bps allocation is the product returned to the engine. A
    # continuous SLSQP point is therefore not allowed to retain a converged
    # status if its deterministic rounding/correction violates any constraint.
    if not continuous_feasible:
        status = "diverged_infeasible"
        violation_reasons = list(continuous_violation_reasons)
    elif not rounded_feasible:
        status = "diverged_infeasible"
        violation_reasons = list(rounded_violation_reasons)
    elif accepted_feasible_non_success:
        status = "converged_robustified"
        violation_reasons = []
    else:
        status = "converged"
        violation_reasons = []

    # V3 Sprint 1b: objective_value via Context-Path neu bestimmen, damit
    # `evaluate_weights(ctx, result.weights_bps).objective_value` exakt
    # `result.objective_value` matcht (post-rounding kongruent).
    post_round_objective = _objective_from_array(
        context, rounded_w
    )
    # OPTIMIZER-OBJECTIVE-DOMAIN-FAIL-CLOSED-001: ein nicht endlicher
    # Zielfunktionswert darf nicht als `converged` klassifiziert, nicht
    # publiziert und nicht persistiert werden. Vorher wurde er genau das: der
    # Status steht oben schon, und `objective_value=post_round_objective`
    # ging ungeprueft in das Ergebnis. Bei `-inf` schrieben zwei der drei
    # Milli-Konverter daraus sogar eine konkrete Zahl
    # (-9'000'000'000'000'000'000, der negative Cap) -- ein nicht
    # existierender Wert wurde zu einem scheinbar gemessenen.
    #
    # Nach der Domaenenpruefung der Faktoren und Gewichte kann das hier nur
    # noch ein Defekt weiter innen sein. Deshalb ein Domaenenfehler und kein
    # `SolverTechnicalError`: er liegt ausserhalb der Fallback-Allowlist und
    # laesst den Lauf scheitern, statt still eine House-Matrix-Empfehlung
    # auszugeben, die wie ein regulaeres Ergebnis aussieht.
    if not math.isfinite(float(post_round_objective)):
        raise ObjectiveDomainError(
            "objective_value_not_finite",
            "Der Zielfunktionswert nach dem Rounding ist nicht endlich "
            f"({post_round_objective!r}); ein solcher Lauf ist nicht "
            "bewertbar und darf nicht als konvergiert gelten.",
        )
    final_wealth = _simulate_context_wealth(context, rounded_w)
    train_achievability = publish_goal_achievability(
        final_wealth,
        context.liabilities,
        context.advisory_wealth_rappen,
        weights=context.scenario_weights,
        annualized_return_bps_per_path=_annualized_twr_bps_per_path(
            context, rounded_w
        ),
    )
    # OPTIMIZER-POST-SELECTION-CERTIFICATION-001: der Gewinner wird auf einem
    # UNABHAENGIGEN Cube nachzertifiziert. Was publiziert wird, ist die
    # selektionsfreie Schaetzung -- nicht die des Cubes, auf dem gerade
    # ausgewaehlt wurde.
    (
        goal_achievability,
        validation_seed_used,
        validation_cube_hash_used,
        validation_n_paths_used,
    ) = _certify_on_independent_validation_cube(
        context, rounded_w, list(train_achievability),
    )
    reasoning: list[str] = list(context.bounds_collapse_warnings)
    method_used = "SLSQP+DE-Fallback" if used_ga_fallback else "SLSQP"
    if resampling_payload is not None and resampling_payload.get("enabled"):
        reasoning.append(
            f"Stochastic Solver ({method_used}, Resampled Efficiency): "
            f"{total_iters} iterations across "
            f"{int(resampling_payload.get('n_bags_succeeded') or 0)} bags x "
            f"{n_starts} multi-starts."
        )
    else:
        reasoning.append(f"Stochastic Solver ({method_used}): {total_iters} iterations across "
                          f"{n_starts} multi-starts.")
    reasoning.extend(extra_reasoning or [])
    # Sprint P1 (2026-06-06): IS-Status im Audit-Trail
    reasoning.append(_importance_sampling_reasoning(context))
    reasoning.extend(reachability_reasoning(context.goal_reachability))
    goal_achievability = annotate_reachability_rows(
        goal_achievability, context.goal_reachability,
    )
    # OPTIMIZER-OBJECTIVE-VARIANTS-001: der Modus `max_drawdown` optimiert auf
    # dem JAHRESGITTER -- die Bruecken-Verfeinerung aus DRAWDOWN-TIME-GRID-001
    # in jeder SLSQP-Iteration waere unbezahlbar. Das Jahresgitter
    # unterschaetzt den Drawdown volatilitaetsabhaengig und bevorzugt als
    # Zielfunktion damit leicht riskantere Allokationen.
    #
    # Fuer den GEWINNER wird das genaue Mass nachgerechnet und die
    # Proxy-Verzerrung in den Audit-Trail geschrieben -- dieselbe Trennung von
    # "worauf optimiert wurde" und "was ausgewiesen wird" wie beim
    # unabhaengigen Validierungs-Cube direkt oben. Ohne diesen Aufruf waere
    # die Nachrechnung eine ungenutzte Funktion und die Verzerrung
    # unausgewiesen.
    # OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001: der Modus kommt aus dem
    # eingefrorenen Vertrag des Laufs. Vorher wurde hier -- NACH der Selektion
    # -- die Umgebung erneut gelesen: ein Wechsel mittendrin konnte die
    # Nachrechnung fuer einen Lauf ausloesen, der gar nicht auf max_drawdown
    # optimiert hatte, oder sie fuer einen unterdruecken, der es tat.
    #
    # OPTIMIZER-DRAWDOWN-CERTIFICATION-001 (2026-10-14): statt nur den
    # Gewinner auf dem Trainings-Cube nachzurechnen, werden alle Finalisten
    # auf dem Validierungs-Cube gerankt (Schritt 6c). Nur wenn das nicht
    # moeglich war, bleibt die alte Trainings-Cube-Nachrechnung als
    # (gekennzeichnete) Offenlegung.
    if drawdown_certification is not None:
        reasoning.extend(drawdown_certification_reasoning(
            drawdown_certification,
            training_cube_check=(
                None
                if drawdown_certification.get("certified")
                else refined_drawdown_check_for_winner(
                    _portfolio_return_factors(context, rounded_w),
                    seed=int(context.seed),
                    weights=context.scenario_weights,
                )
            ),
        ))
    robustification_payload: dict[str, object] | None = None
    if accepted_feasible_non_success:
        robustification_payload = {
            "enabled": True,
            "stage": "finite_feasible_candidate",
            "attempts": attempt_summaries,
            "final_reason": (
                "strict_feasibility_check_passed_risk_tiebreak_derisked"
                if robustification_derisked
                else "strict_feasibility_check_passed_risk_tiebreak"
            ),
        }
        reasoning.append(
            "Stage-9 Robustifizierung: SciPy meldete keinen stabilen Erfolg, "
            "lieferte aber eine finite Allokation, die Risk-Cap, Bandbreiten "
            "und Sum-to-one strikt erfuellt. Ergebnis als robustifizierter "
            "Solver-Run akzeptiert."
        )
    reasoning.append(f"Best objective L(w*) = {post_round_objective:.6e}")
    final_preference_deviation = (
        preference_deviation_bps(weights_bps, context.preferred_target_bps)
        if context.preferred_target_bps
        else None
    )
    if final_preference_deviation is not None:
        reasoning.append(
            "Soft-Preference-Praeferenz (Policy "
            f"{context.soft_preference_policy_version}) im Objective "
            "beruecksichtigt (CERT-ALLOCATION-INTENT-001). Abweichung "
            f"Effektiv-vs-Praeferenz (bps): {final_preference_deviation}."
        )
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
        # STRESS-SEMANTICS-001: Drawdown/kumulierte Rendite sind flussfreie
        # Portfolio-Kennzahlen; der Vermoegens-Effekt wird als Differenz zur
        # No-Crisis-Baseline (gleiche Flows, gleiches 0%-Padding) ausgewiesen,
        # nicht als absolutes End-Vermoegen (das vom Padding dominiert ist).
        for name, r in stress_results.items():
            # AA-UX-FORMAT-001: Tausendertrennung gerades Apostroph (wie PDFs).
            impact_chf = f"{r.crisis_impact_end_wealth_rappen / 100:+,.0f}".replace(",", "'")
            reasoning.append(
                f"Stress '{name}': Portfolio kumuliert "
                f"{r.cumulative_return_bps / 100:+.1f}%, "
                f"Max. Drawdown (Portfolio) {r.max_drawdown_bps / 100:.1f}%, "
                "Krisen-Effekt auf End-Vermoegen "
                f"{impact_chf} CHF "
                "(vs. gleicher Verlauf ohne Krise)."
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
        n_starts_attempted=n_starts,
        stress_evaluations=stress_evals,
        goal_achievability=tuple(goal_achievability),
        robustification=robustification_payload,
        restart_results=tuple(attempt_summaries),
        preference_deviation_bps=final_preference_deviation,
        validation_seed=validation_seed_used,
        validation_cube_hash=validation_cube_hash_used,
        validation_n_paths=validation_n_paths_used,
        resampling=resampling_payload,
        drawdown_certification=drawdown_certification,
        importance_sampling=context.importance_sampling_audit,
        goal_reachability=context.goal_reachability,
        context=context,
    )


# ============================================================================
# SAA-RESAMPLED-STABILITY-001: Resampled Efficiency + Hausmatrix-Signifikanz
# ============================================================================

_HOUSE_ANCHOR_ROW_FIELDS = {
    "equities": "equity_target_bps",
    "bonds": "bonds_target_bps",
    "real_estate": "real_estate_target_bps",
    "alternatives": "alt_target_bps",
    "liquidity": "liq_target_bps",
}


def _resolve_house_anchor_bps(
    house_anchor_bps: Mapping[str, int] | None,
    house_matrix_row,
) -> dict[str, int] | None:
    """Hausmatrix-Zielquote fuer den Signifikanztest.

    Vorrang hat der explizit uebergebene Anker (Produktion: die bereits um
    Reserve-Untergrenze und Praeferenzen bereinigte Hausmatrix-Zielquote des
    Generierungspfads). Sonst die target-Spalten der Hausmatrix-Zeile. Fehlt
    beides oder ist es unvollstaendig, gibt es keinen Anker (None) -- der
    Test entfaellt dann sichtbar, statt einen erfundenen Anker zu nehmen.
    """
    if house_anchor_bps is not None:
        if not isinstance(house_anchor_bps, Mapping):
            raise OptimizerInputError(
                "house_anchor_bps must be a mapping of optimizer bucket -> integer bps."
            )
        anchor: dict[str, int] = {}
        for bucket in BUCKET_ORDER:
            value = house_anchor_bps.get(bucket)
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise OptimizerInputError(
                    f"house_anchor_bps[{bucket!r}] must be integer basis points."
                )
            anchor[bucket] = int(value)
        return anchor
    if house_matrix_row is None:
        return None
    anchor = {}
    for bucket, attribute in _HOUSE_ANCHOR_ROW_FIELDS.items():
        value = getattr(house_matrix_row, attribute, None)
        if isinstance(value, bool) or not isinstance(value, Integral):
            return None
        anchor[bucket] = int(value)
    return anchor


def _project_onto_feasible_set(
    target: np.ndarray,
    context: OptimizerContext,
) -> np.ndarray | None:
    """Euklidische Projektion auf {Bandbreiten, Risikobudget, Summe = 1, ...}.

    Alle harten Constraints des Contexts (Bandbreiten inkl. Reserve-
    Untergrenze und Illiquiditaets-Caps als Box-Bounds, Risikobudget als
    lineare Ungleichung, Summe = 1) bilden eine konvexe Menge -- die
    Projektion ist eindeutig. Ist der Punkt schon zulaessig, wird er
    unveraendert zurueckgegeben (Normalfall fuer das Bag-Mittel). None, wenn
    keine zulaessige Projektion gefunden wird.
    """
    bounds = context.bounds
    constraints = context.scipy_constraints
    target = np.asarray(target, dtype=np.float64)
    feasible, _violations = is_feasible(target, bounds=bounds, constraints=constraints)
    if feasible:
        return target.copy()
    starts = [
        _normalize_to_bounds(np.clip(target, 0.0, 1.0), bounds),
        _minimum_risk_allocation(bounds, context.risky_fraction_per_bucket),
    ]
    best: np.ndarray | None = None
    best_distance = float("inf")
    for x0 in starts:
        result = minimize(
            lambda w: float(np.sum((w - target) ** 2)),
            x0=x0,
            jac=lambda w: 2.0 * (w - target),
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 200, "ftol": 1e-12, "disp": False},
        )
        raw = getattr(result, "x", None)
        if raw is None:
            continue
        candidate = np.asarray(raw, dtype=np.float64)
        if candidate.shape != target.shape or not np.all(np.isfinite(candidate)):
            continue
        candidate = _normalize_to_bounds(np.clip(candidate, 0.0, 1.0), bounds)
        ok, _violations = is_feasible(candidate, bounds=bounds, constraints=constraints)
        if not ok:
            continue
        distance = float(np.sum((candidate - target) ** 2))
        if distance < best_distance:
            best, best_distance = candidate, distance
    return best


def _bag_context(
    context: OptimizerContext,
    *,
    seed: int,
    n_paths: int,
) -> OptimizerContext:
    """Bag-Wuerfel: identische Inputs/Constraints/Vertrag, eigener Pfadsatz.

    Wird ausschliesslich aus dem Haupt-Context abgeleitet -- nicht aus den
    Aufrufer-kwargs. So sehen Generierung, Sensitivity und jede
    Nachzertifizierung per Konstruktion dieselben Bags, sobald sie denselben
    Haupt-Context (Inhalts-Seed) haben.
    """
    paths, scenario_weights = build_bag_paths(
        context.scenario_inputs,
        scenario_horizon_years=int(
            context.scenario_horizon_years or context.horizon_years
        ),
        horizon_years=int(context.horizon_years),
        n_paths=int(n_paths),
        seed=int(seed),
        importance_sampling=context.scenario_weights is not None,
    )
    death_indices = context.mortality_death_year_index_per_path
    if death_indices is not None:
        # Deterministischer Mortalitaets-Cutoff: fuer alle Pfade identisch
        # (siehe build_optimizer_context), also einfach auf n_paths ausrollen.
        death_indices = np.full(
            int(n_paths), int(np.asarray(death_indices)[0]), dtype=np.int32
        )
    return replace(
        context,
        seed=int(seed),
        n_paths=int(n_paths),
        return_paths=paths,
        scenario_weights=scenario_weights,
        mortality_death_year_index_per_path=death_indices,
    )


def _context_loss_components_on_validation(
    validation_context: OptimizerContext,
    anchor_w: np.ndarray,
    candidate_w: np.ndarray,
    *,
    validation_seed: int | None = None,
):
    """Liefert ``component_pair(idx)`` fuer den gepaarten Bootstrap.

    Je Allokation das Paar ``(zielebene, risikoebene)`` auf der Pfadauswahl
    ``idx`` (None = alle Pfade); ihre Summe ist exakt die Skalar-Zielfunktion
    der Bags (Vertrag des Laufs, Soft-Preference inklusive):

    * ``zielebene`` -- die ZIELERREICHUNG: im Default Ziel-Fehlbetrag L(w) +
      Chance-Strafe, in den Varianten die Chance-Strafe; jeweils plus
      Soft-Preference-Strafe (explizite Berater-Vorgabe, keine
      Schaetzgroesse).
    * ``risikoebene`` -- im Default der Tiebreak ``kappa * w' Sigma w``, in
      den Varianten das Risikomass selbst (Primaerterm).

    HOUSE-FIRST-SIGNIFICANCE-001 (CIO-Entscheid 2026-10-18): der
    Signifikanztest gegen die Hausmatrix entscheidet auf der Zielebene; die
    Risikoebene zaehlt nur in den Varianten und nur mit Materialitaet
    (``_significance_vs_house_anchor``). Vermoegenspfade, Faktoren und
    Jahresrenditen werden EINMAL je Allokation simuliert.
    """
    contract = objective_contract_of(validation_context)
    is_default = contract.objective_mode == OBJECTIVE_GOAL_SHORTFALL
    # OPTIMIZER-DRAWDOWN-CERTIFICATION-001 (CIO-Entscheid 2026-10-18): im
    # Modus max_drawdown vergleicht der Signifikanztest mit dem VERFEINERTEN
    # Drawdown (Brownsche Bruecke, Bruecken-Seed = Validierungs-Seed) statt
    # des Jahresgitter-Proxy -- dasselbe Mass wie der Drawdown-Rerank. Der
    # Proxy unterschaetzt volatilitaetsabhaengig und wuerde den Test
    # systematisch zugunsten der riskanteren Allokation verschieben.
    refined_drawdown = (
        contract.objective_mode == OBJECTIVE_MAX_DRAWDOWN
        and validation_seed is not None
    )

    def _prepare(w: np.ndarray):
        wealth = _simulate_context_wealth(validation_context, w)
        factors = _portfolio_return_factors(validation_context, w)
        annualized = _annualized_twr_bps_per_path(
            validation_context, w, portfolio_factors=factors
        )
        preference = (
            preference_loss_from_array(
                w,
                validation_context.preferred_target_bps,
                lam=validation_context.preference_penalty_lambda,
            )
            if validation_context.preferred_target_bps
            else 0.0
        )
        drawdowns = (
            refined_primary_per_path(
                validation_context, w, validation_seed=int(validation_seed),
            )
            if refined_drawdown
            else None
        )
        variance = _tiebreak_portfolio_variance(validation_context, w)
        return wealth, factors, annualized, float(preference), drawdowns, variance

    prepared = (_prepare(anchor_w), _prepare(candidate_w))

    def _components(bundle, idx) -> tuple[float, float]:
        wealth, factors, annualized, preference, drawdowns, variance = bundle
        if idx is not None:
            wealth, factors, annualized = wealth[idx], factors[idx], annualized[idx]
            if drawdowns is not None:
                drawdowns = drawdowns[idx]
        primary_override, primary_weight = None, 1.0
        if not is_default:
            # Varianten: das Risikomass einmal rechnen und als Override mit
            # Gewicht 0 durchreichen -> die Zielebene ist exakt die
            # Chance-Strafe, ohne den Primaerterm doppelt zu berechnen.
            primary_override = (
                float(np.mean(drawdowns))
                if drawdowns is not None
                else primary_objective(
                    contract.objective_mode,
                    goal_shortfall_value=0.0,
                    portfolio_return_factors=factors,
                    weights=None,
                )
            )
            primary_weight = 0.0
        goal_level, tiebreak = two_phase_objective_parts(
            validation_context.liabilities,
            wealth,
            initial_wealth_rappen=validation_context.advisory_wealth_rappen,
            horizon_years=validation_context.horizon_years,
            primary_weight=primary_weight,
            weights=None,
            annualized_return_bps_per_path=annualized,
            objective_mode=contract.objective_mode,
            goal_weighting_mode=contract.goal_weighting_mode,
            portfolio_return_factors=factors,
            primary_value_override=primary_override,
            portfolio_variance=variance,
        )
        risk_level = float(tiebreak) if is_default else float(primary_override)
        return float(goal_level) + float(preference), risk_level

    def component_pair(idx):
        return _components(prepared[0], idx), _components(prepared[1], idx)

    return component_pair


def _rounded_bps_with_repair(
    w: np.ndarray,
    context: OptimizerContext,
) -> dict[str, int]:
    """bps-Rundung; verletzt sie eine aktive lineare Nebenbedingung, die
    1-bps-Reparatur (``_repair_rounded_bps``). Gelingt die nicht, bleibt die
    einfache Rundung (der Aufrufer prueft die Zulaessigkeit selbst)."""
    weights_bps = _weights_to_bps_dict(w, bounds=context.bounds)
    ok, _violations = is_feasible(
        _trusted_weights_bps_to_array(weights_bps),
        bounds=context.bounds,
        constraints=context.scipy_constraints,
    )
    if ok:
        return weights_bps
    repaired = _repair_rounded_bps(
        weights_bps, context.bounds, context.scipy_constraints,
    )
    return repaired if repaired is not None else weights_bps


def _bps_dict_for_feasible_point(
    w: np.ndarray,
    context: OptimizerContext,
) -> dict[str, int] | None:
    weights_bps = _rounded_bps_with_repair(w, context)
    ok, _violations = is_feasible(
        _trusted_weights_bps_to_array(weights_bps),
        bounds=context.bounds,
        constraints=context.scipy_constraints,
    )
    return weights_bps if ok else None


def _project_house_anchor(
    context: OptimizerContext,
    house_anchor_bps: dict[str, int] | None,
) -> tuple[dict[str, int] | None, str | None]:
    """Hausmatrix-Zielquote zulaessig projiziert, als bps -- oder (None, Grund).

    Herausgeloest aus ``_significance_vs_house_anchor``, damit der
    Drawdown-Rerank (OPTIMIZER-DRAWDOWN-CERTIFICATION-001) exakt denselben
    projizierten Anker bewertet wie der Signifikanztest.
    """
    if not house_anchor_bps:
        return None, "no_house_anchor"
    anchor_raw = np.array(
        [int(house_anchor_bps[bucket]) / 10000.0 for bucket in BUCKET_ORDER],
        dtype=np.float64,
    )
    anchor_total = float(np.sum(anchor_raw))
    if anchor_total <= 0:
        return None, "invalid_house_anchor"
    projected = _project_onto_feasible_set(anchor_raw / anchor_total, context)
    anchor_bps = (
        _bps_dict_for_feasible_point(projected, context)
        if projected is not None
        else None
    )
    if anchor_bps is None:
        return None, "house_anchor_not_projectable"
    return anchor_bps, None


def _significance_vs_house_anchor(
    context: OptimizerContext,
    *,
    candidate_bps: dict[str, int],
    house_anchor_bps: dict[str, int] | None,
    config: ResamplingConfig,
    validation: tuple[OptimizerContext, int, str] | None = None,
) -> dict:
    """Test: ist die resampelte Allokation der (zulaessig projizierten)
    Hausmatrix-Zielquote signifikant UEBERLEGEN?

    HOUSE-FIRST-SIGNIFICANCE-001 (CIO-Entscheid 2026-10-18): "Hausmatrix,
    solange die Ziele mit ihr gleich sicher erreicht sind."

    1. Zielebene (alle Modi): gepaarter Bootstrap der Verbesserung von
       Ziel-Fehlbetrag + Chance-Strafe (+ Soft-Preference). Signifikant ->
       Optimierer. Der Volatilitaets-Tiebreak zaehlt hier NICHT: er ist
       deterministisch (``kappa * w' Sigma w``), jede noch so kleine
       Differenz waere "signifikant" (p = 1/(B+1)) -- so entstanden
       Eckloesungen auf Schaetzfehlern der Korrelation. Im Solver bleibt er
       (Stetigkeit/Monotonie), er entscheidet nur nicht ueber Anker vs.
       Kandidat.
    2. Nur in den Varianten (Risikomass = Zweck): Skalar-Zielfunktion
       (Risikomass + Chance-Strafe + Preference) signifikant UND
       Risikomass-Verbesserung auf dem Validierungs-Cube
       >= ``RISK_MEASURE_MATERIALITY`` -> Optimierer.

    Entscheid ``decision``:
    * ``optimizer``  -- (1) oder (2) erfuellt, Optimierer-Allokation gilt.
    * ``house_matrix`` -- weder noch, Hausmatrix-Zielquote gilt.
    * ``optimizer_untested`` -- kein Test moeglich, weil es keinen
      zulaessigen Anker gibt (kein Anker, keine zulaessige Projektion) oder
      der Test abgeschaltet ist; die Optimierer-Allokation gilt, der Grund
      steht in ``reason``.
    * ``house_matrix`` mit ``reason="no_validation_cube"`` -- Anker vorhanden,
      aber kein finaler Validierungswuerfel: fail-closed auf die Hausquote
      (OPTIMIZER-POST-SELECTION-CERTIFICATION-001, v7).

    ``validation`` ist der FINALE Holdout (``CUBE_ROLE_FINAL``); gezogen wird
    ueber antithetische Paare (``_validation_sampling_units``).

    Die Top-Level-Statistik (``p_value``, ``improvement`` ...) ist immer die
    der Zielebene; die Varianten-Statistik steht in ``risk_measure_test``.
    """
    block: dict = {
        "test": None,
        "alpha": float(config.significance_alpha),
        "house_anchor_bps": dict(house_anchor_bps) if house_anchor_bps else None,
        "house_anchor_projected_bps": None,
        "candidate_bps": dict(candidate_bps),
    }
    if not config.significance_test:
        return {**block, "decision": "optimizer_untested", "reason": "test_disabled"}
    anchor_bps, anchor_reason = _project_house_anchor(context, house_anchor_bps)
    if anchor_bps is None:
        return {**block, "decision": "optimizer_untested", "reason": anchor_reason}
    block["house_anchor_projected_bps"] = dict(anchor_bps)
    if anchor_bps == candidate_bps:
        return {
            **block,
            "decision": "house_matrix",
            "reason": "identical_to_house_anchor",
            "significant": False,
        }
    if validation is None:
        validation = _build_validation_context(context)
    if validation is None:
        # Fail-closed: ohne Holdout ist die Abweichung unzertifiziert.
        return {
            **block,
            "decision": "house_matrix",
            "reason": "no_validation_cube",
            "significant": False,
        }
    validation_context, validation_seed, cube_hash = validation
    unit_ids, unit_name = _validation_sampling_units(validation_context)
    objective_mode = objective_contract_of(context).objective_mode
    if objective_mode == OBJECTIVE_MAX_DRAWDOWN:
        # Nur in diesem Modus gesetzt: Default-Laeufe behalten ihre
        # Modellbasis (und damit ihren allocation_context_hash) bit-gleich.
        block["drawdown_measure"] = "refined_brownian_bridge"
    component_pair = _context_loss_components_on_validation(
        validation_context,
        _trusted_weights_bps_to_array(anchor_bps),
        _trusted_weights_bps_to_array(candidate_bps),
        validation_seed=int(validation_seed),
    )
    bootstrap_kwargs = dict(
        n_paths=int(validation_context.n_paths),
        n_bootstrap=int(config.n_bootstrap),
        alpha=float(config.significance_alpha),
        seed=bootstrap_seed(validation_seed),
        sampling_unit_ids=unit_ids,
        sampling_unit=unit_name,
    )
    goal_stats = paired_bootstrap_improvement(
        lambda idx: tuple(parts[0] for parts in component_pair(idx)),
        **bootstrap_kwargs,
    )
    result = {
        **block,
        **goal_stats,
        "comparison": COMPARISON_GOAL_LEVEL,
        "decision_level": COMPARISON_GOAL_LEVEL,
        "cube_role": CUBE_ROLE_FINAL,
        "validation_seed": int(validation_seed),
        "validation_cube_hash": cube_hash,
        "validation_n_paths": int(validation_context.n_paths),
    }
    if goal_stats["significant"]:
        return {**result, "decision": "optimizer",
                "reason": "significant_goal_improvement"}
    if objective_mode == OBJECTIVE_GOAL_SHORTFALL:
        return {**result, "decision": "house_matrix",
                "reason": "goal_improvement_not_significant"}

    (_anchor_goal, anchor_risk), (_cand_goal, candidate_risk) = component_pair(None)
    risk_improvement = float(anchor_risk) - float(candidate_risk)
    material = bool(risk_improvement >= RISK_MEASURE_MATERIALITY)
    risk_stats = paired_bootstrap_improvement(
        lambda idx: tuple(sum(parts) for parts in component_pair(idx)),
        **bootstrap_kwargs,
    )
    result["risk_measure_test"] = {
        **{
            key: risk_stats.get(key)
            for key in ("improvement", "improvement_lower_bound", "p_value",
                        "bootstrap_tail_fraction", "null_hypothesis",
                        "p_value_calibration", "anchor_objective",
                        "candidate_objective")
        },
        "comparison": COMPARISON_RISK_MEASURE,
        "anchor_risk_measure": float(anchor_risk),
        "candidate_risk_measure": float(candidate_risk),
        "risk_improvement": risk_improvement,
        "materiality_threshold": float(RISK_MEASURE_MATERIALITY),
        "material": material,
        "significant": bool(risk_stats["significant"]),
    }
    if risk_stats["significant"] and material:
        return {**result, "decision": "optimizer", "significant": True,
                "decision_level": COMPARISON_RISK_MEASURE,
                "reason": "significant_material_risk_improvement"}
    return {
        **result,
        "decision": "house_matrix",
        "reason": (
            "risk_improvement_not_material"
            if risk_stats["significant"]
            else "risk_improvement_not_significant"
        ),
    }


def _run_resampled_solver(
    context: OptimizerContext,
    *,
    config: ResamplingConfig,
    house_anchor_bps: dict[str, int] | None,
    max_iter: int,
    ftol: float,
    advisory_wealth_rappen: int,
    cashflow_series_rappen: Iterable[int],
) -> OptimizerResult:
    """Resampled Efficiency (Michaud-Bagging) mit Hausmatrix-Prior (Default)
    bzw. Signifikanztest gegen die Hausmatrix (Varianten, kein Anker).

    Siehe services/optimizer/resampling.py fuer Methode und Parameterwahl und
    services/optimizer/house_prior.py fuer den Prior (HOUSE-PRIOR-001).
    """
    started = time.perf_counter()
    if context.scenario_inputs is None:
        raise OptimizerInputError(
            "Resampling braucht die ScenarioInputs des Contexts, um Bag-Wuerfel "
            "derselben Verteilung zu ziehen."
        )
    # HOUSE-PRIOR-001: im Default-Modus mit projizierbarem Anker tragen ALLE
    # Bags und der Validierungswuerfel der Offenlegung den Prior (eine
    # Zielfunktion fuer Optimierung und Offenlegung).
    # HOUSE-PRIOR-DECISION-OBJECTIVE-IDENTITY-001 (Engine v7): auch der
    # Abschluss laeuft auf dem Prior-Context. ``result.context`` und
    # ``result.objective_value`` (= G + P_pref + kappa_H * TE_M^2) sind damit
    # dieselbe Zielfunktion, unter der die Bags selektiert wurden;
    # ``evaluate_weights(result.context, result.weights_bps).objective_value ==
    # result.objective_value``. Ein ohne Prior gebauter Context bewertet
    # bewusst eine ANDERE Zielfunktion (v5-Tiebreak w' Sigma w).
    house_prior_anchor_bps: dict[str, int] | None = None
    if objective_contract_of(context).objective_mode == OBJECTIVE_GOAL_SHORTFALL:
        house_prior_anchor_bps, _anchor_reason = _project_house_anchor(
            context, house_anchor_bps,
        )
        if house_prior_anchor_bps is not None:
            context = _with_house_prior(context, house_prior_anchor_bps)
    n_bags = int(config.n_bags)
    # Nie mehr Pfade je Bag als der Hauptwuerfel hat: der Hauptwuerfel ist die
    # Referenzgroesse des Laufs (Tests mit kleinen Wuerfeln bleiben klein).
    bag_n_paths = max(2, min(int(config.bag_n_paths), int(context.n_paths)))
    seeds = bag_seeds(int(context.seed), n_bags)

    bag_weights: list[np.ndarray] = []
    total_iters = 0
    n_starts = 0
    bag_summaries: list[dict] = []
    robustified_bags = 0
    ga_bags = 0
    bag_ess_fractions: list[float] = []
    bag_is_fallbacks = 0
    for index, bag_seed in enumerate(seeds):
        bag_started = time.perf_counter()
        bag_ctx = _bag_context(context, seed=bag_seed, n_paths=bag_n_paths)
        if context.scenario_weights is not None:
            if bag_ctx.scenario_weights is None:
                bag_is_fallbacks += 1
                bag_ess_fractions.append(1.0)
            else:
                bag_ess_fractions.append(float(
                    importance_sampling_diagnostics(bag_ctx.scenario_weights)[
                        "ess_fraction"
                    ]
                ))
        selection = _select_cube_candidate(
            bag_ctx,
            max_iter=max_iter,
            ftol=ftol,
        )
        total_iters += selection.total_iters
        n_starts = max(n_starts, selection.n_starts)
        succeeded = selection.weights is not None
        if succeeded:
            bag_weights.append(np.asarray(selection.weights, dtype=np.float64))
            robustified_bags += int(selection.accepted_feasible_non_success)
            ga_bags += int(selection.used_ga_fallback)
        # Gleiche Schluessel wie die Start-Diagnose eines Einzelwuerfels
        # (stage/status/reason/n_paths/n_starts/seed/elapsed_ms), damit
        # OptimizerRun.restart_results_json lesbar bleibt; je Bag eine Zeile.
        bag_summaries.append({
            "attempt": index + 1,
            "bag": index + 1,
            "stage": "resampling_bag",
            "seed": int(bag_seed),
            "n_paths": int(bag_n_paths),
            "n_starts": int(selection.n_starts),
            "status": (
                "no_feasible_candidate"
                if not succeeded
                else (
                    "converged_robustified"
                    if selection.accepted_feasible_non_success
                    else "converged"
                )
            ),
            "reason": (
                "bag_no_feasible_candidate"
                if not succeeded
                else (
                    "bag_de_fallback"
                    if selection.used_ga_fallback
                    else "bag_solver_success"
                )
            ),
            "objective_value": (
                float(selection.objective)
                if succeeded and math.isfinite(float(selection.objective))
                else None
            ),
            "feasible_candidate": bool(succeeded),
            "iterations": int(selection.total_iters),
            "weights_bps": (
                _weights_to_bps_dict(selection.weights, bounds=context.bounds)
                if succeeded
                else None
            ),
            "elapsed_ms": int(round((time.perf_counter() - bag_started) * 1000)),
            # GOAL-HIERARCHY-001: Stufe-1-Audit dieses Bags (Objective-
            # Schnittstelle; None ohne geschuetzte Ziele).
            "goal_protection": selection.goal_protection,
        })

    n_succeeded = len(bag_weights)
    payload: dict = {
        "enabled": True,
        "scheme": RESAMPLING_SCHEME_VERSION,
        "seed_scheme": OPTIMIZER_SEED_SCHEME,
        "engine_version": OPTIMIZER_ENGINE_VERSION,
        # ObjectiveContractV2 (Engine v7): alle Koeffizienten, Scopes und
        # Policy-Versionen dieses Laufs samt Hash (Audit und Modellbasis).
        "objective_contract": _contract_evidence(context),
        "content_seed": int(context.seed),
        "n_bags": n_bags,
        "n_bags_succeeded": n_succeeded,
        "n_bags_robustified": robustified_bags,
        "n_bags_de_fallback": ga_bags,
        "bag_n_paths": bag_n_paths,
        "bags": bag_summaries,
    }
    if bag_ess_fractions:
        # IMPORTANCE-SAMPLING-ESS-001: Kish-ESS-Quote der Bag-Wuerfel
        # (Standard-MC-Rueckfaelle zaehlen mit 1.0 und separat).
        payload["importance_sampling_bags"] = {
            "ess_fraction_min": round(float(np.min(bag_ess_fractions)), 4),
            "ess_fraction_median": round(float(np.median(bag_ess_fractions)), 4),
            "n_fallback_standard_mc": int(bag_is_fallbacks),
        }
    aggregate_selection = _CubeSelection(
        weights=None,
        objective=float("inf"),
        total_iters=total_iters,
        n_starts=n_starts,
        attempt_summaries=bag_summaries,
        used_ga_fallback=ga_bags > 0,
        # Ein robustifizierter Bag macht den ganzen Lauf "robustifiziert":
        # das Mittel enthaelt einen Kandidaten, den SciPy nicht als Erfolg
        # gemeldet hat -- das muss am Status sichtbar bleiben.
        accepted_feasible_non_success=robustified_bags > 0,
        robustification_derisked=False,
    )
    # RESAMPLING-SUCCESS-SURVIVOR-BIAS-001: Mindestquote (Herleitung bei
    # MIN_SUCCESSFUL_BAG_SHARE). Darunter fail-closed, KEIN Mittel publiziert.
    min_successful = max(1, int(np.ceil(MIN_SUCCESSFUL_BAG_SHARE * n_bags - 1e-9)))
    payload["min_successful_bag_share"] = float(MIN_SUCCESSFUL_BAG_SHARE)
    if n_succeeded < min_successful:
        payload["decision"] = "fallback_house_matrix"
        payload["reason"] = "insufficient_successful_bags"
        payload["elapsed_ms"] = int(round((time.perf_counter() - started) * 1000))
        return _house_midpoint_fallback_result(
            context,
            aggregate_selection,
            extra_reasoning=[
                f"Resampling: nur {n_succeeded} von {n_bags} Bags lieferten eine "
                f"zulaessige Allokation (Mindestquote "
                f"{MIN_SUCCESSFUL_BAG_SHARE:.0%} = {min_successful}) -- ein "
                "Mittel nur der erfolgreichen Bags waere bei nicht zufaelligem "
                "Ausfall verzerrt; kein Mittelwert publiziert."
            ],
            resampling_payload=payload,
        )

    stacked = np.vstack(bag_weights)
    mean_w = stacked.mean(axis=0)
    dispersion = (
        stacked.std(axis=0, ddof=1) if n_succeeded > 1 else np.zeros(N_BUCKETS)
    )
    payload["mean_weights_bps"] = {
        bucket: round(float(mean_w[i]) * 10000.0, 2)
        for i, bucket in enumerate(BUCKET_ORDER)
    }
    payload["dispersion_bps"] = {
        bucket: round(float(dispersion[i]) * 10000.0, 2)
        for i, bucket in enumerate(BUCKET_ORDER)
    }
    # Standardfehler des Bag-Mittels, BEDINGT auf die erfolgreichen Bags
    # (RESAMPLING-SUCCESS-SURVIVOR-BIAS-001): die Streuung der publizierten
    # Quote, wenn nur der Monte-Carlo-Zufall variiert. Er enthaelt weder die
    # Unsicherheit durch Bag-Ausfall noch Projektion oder Hausmatrix-Gate.
    payload["conditional_bag_mean_standard_error_bps"] = {
        bucket: round(float(dispersion[i]) * 10000.0 / float(np.sqrt(n_succeeded)), 2)
        for i, bucket in enumerate(BUCKET_ORDER)
    }
    # Sensitivitaetsschranke fuer nicht zufaelligen Ausfall: liegen die
    # fehlenden Bags bis zu MISSINGNESS_STRESS_SIGMAS Bag-Standardabweichungen
    # neben dem Mittel, verschiebt das die Quote um hoechstens
    # f * k * sigma_bag (f = Ausfallanteil). 0 bei vollstaendigem Lauf.
    missing_share = float(n_bags - n_succeeded) / float(n_bags)
    payload["missingness_sensitivity_bps"] = {
        bucket: round(
            missing_share * MISSINGNESS_STRESS_SIGMAS * float(dispersion[i]) * 10000.0,
            2,
        )
        for i, bucket in enumerate(BUCKET_ORDER)
    }

    projected = _project_onto_feasible_set(mean_w, context)
    if projected is None:
        payload["decision"] = "fallback_house_matrix"
        payload["elapsed_ms"] = int(round((time.perf_counter() - started) * 1000))
        return _house_midpoint_fallback_result(
            context,
            aggregate_selection,
            extra_reasoning=[
                "Resampling: das Bag-Mittel liess sich nicht auf die harten "
                "Constraints projizieren."
            ],
            resampling_payload=payload,
        )
    payload["projection_distance_bps"] = round(
        float(np.sqrt(np.sum((projected - mean_w) ** 2))) * 10000.0, 4
    )
    candidate_bps = _rounded_bps_with_repair(projected, context)
    payload["resampled_weights_bps"] = dict(candidate_bps)

    # OPTIMIZER-DRAWDOWN-CERTIFICATION-001 unter Resampling (CIO-Entscheid
    # 2026-10-18): Modus max_drawdown -> {projiziertes Bag-Mittel, rohes
    # Bag-Mittel, Hausmatrix-Anker} mit dem verfeinerten Drawdown ranken; der
    # beste Nicht-Anker-Kandidat geht in den Signifikanztest (der dasselbe
    # Mass verwendet).
    # DRAWDOWN-HOLDOUT-REUSE-001 (Engine v7): gerankt wird auf dem
    # AUSWAHL-Wuerfel. Danach ist der Challenger eingefroren; Test gegen die
    # Hausmatrix und Zielerreichung laufen auf dem getrennten FINALEN
    # Holdout, auf dem nichts mehr ausgewaehlt wird.
    drawdown_certification: dict | None = None
    final_validation = None
    if objective_contract_of(context).objective_mode == OBJECTIVE_MAX_DRAWDOWN:
        selection_validation = _build_selection_validation_context(context)
        certified_w, drawdown_certification = certify_resampled_candidates(
            context,
            projected_mean=projected,
            raw_mean=mean_w,
            house_anchor_bps=_project_house_anchor(context, house_anchor_bps)[0],
            validation=selection_validation,
        )
        if certified_w is not None:
            candidate_bps = _rounded_bps_with_repair(certified_w, context)
        final_validation = _build_validation_context(context)

    reasoning: list[str] = []
    max_dispersion_pp = float(np.max(dispersion)) * 100.0
    max_standard_error_pp = max_dispersion_pp / float(np.sqrt(n_succeeded))
    reasoning.append(
        f"Resampled Efficiency: {n_succeeded} von {n_bags} Bags a "
        f"{bag_n_paths} Pfaden (Inhalts-Seed, Common Random Numbers) gemittelt; "
        f"Streuung je Bucket ueber die Bags max. {max_dispersion_pp:.1f} pp, "
        f"Standardfehler der Quote (bedingt auf die erfolgreichen Bags) max. "
        f"{max_standard_error_pp:.2f} pp."
    )
    if house_prior_anchor_bps is not None:
        # HOUSE-PRIOR-001: kein Schalter -- das (projizierte) Bag-Mittel IST
        # das Ergebnis; der Bootstrap legt nur offen und faengt als
        # Sicherheitsnetz ein signifikant schlechteres Ergebnis ab.
        house_prior = _house_prior_disclosure(
            context,
            candidate_bps=candidate_bps,
            house_anchor_bps=house_anchor_bps,
            anchor_projected_bps=house_prior_anchor_bps,
            config=config,
        )
        payload["house_prior"] = house_prior
        payload["decision"] = house_prior["decision"]
        final_bps = dict(house_prior["final_bps"])
        reasoning.append(house_prior_sentence(house_prior))
        payload["final_weights_bps"] = dict(final_bps)
        payload["elapsed_ms"] = int(round((time.perf_counter() - started) * 1000))
        return _finalize_solver_result(
            context,
            selection=aggregate_selection,
            weights=_trusted_weights_bps_to_array(final_bps),
            advisory_wealth_rappen=advisory_wealth_rappen,
            cashflow_series_rappen=cashflow_series_rappen,
            extra_reasoning=reasoning,
            resampling_payload=payload,
            drawdown_certification=drawdown_certification,
        )

    significance = _significance_vs_house_anchor(
        context,
        candidate_bps=candidate_bps,
        house_anchor_bps=house_anchor_bps,
        config=config,
        validation=final_validation,
    )
    if drawdown_certification is not None and drawdown_certification.get("certified"):
        # Beide Rollen offenlegen: Auswahl-Wuerfel != finaler Holdout.
        significance["selection_seed"] = drawdown_certification.get("validation_seed")
        significance["selection_cube_hash"] = drawdown_certification.get(
            "validation_cube_hash"
        )
    payload["significance"] = significance
    decision = significance["decision"]
    payload["decision"] = decision
    if decision == "house_matrix":
        final_bps = dict(significance["house_anchor_projected_bps"])
        if significance.get("reason") == "identical_to_house_anchor":
            reasoning.append(
                "Optimierer-Allokation ist identisch mit der Hausmatrix-Zielquote; "
                "Hausmatrix-Zielquote beibehalten."
            )
        elif significance.get("reason") == "no_validation_cube":
            reasoning.append(
                "Finaler Validierungswuerfel nicht verfuegbar: die "
                "Optimierer-Abweichung ist nicht zertifiziert; "
                "Hausmatrix-Zielquote beibehalten (fail-closed)."
            )
        elif significance.get("reason") == "risk_improvement_not_material":
            reasoning.append(
                "Optimierer-Abweichung von der Hausmatrix ist nicht material "
                "(Risikomass-Verbesserung unter der Materialitaetsschwelle, Ziele "
                "nicht signifikant sicherer erreicht); Hausmatrix-Zielquote "
                "beibehalten. " + _significance_sentence(significance)
            )
        else:
            reasoning.append(
                "Optimierer-Abweichung von der Hausmatrix ist statistisch nicht "
                "signifikant; Hausmatrix-Zielquote beibehalten. "
                + _significance_sentence(significance)
            )
    elif decision == "optimizer":
        final_bps = dict(candidate_bps)
        reasoning.append(
            "Optimierer-Abweichung von der Hausmatrix ist statistisch "
            "signifikant; Optimierer-Allokation uebernommen. "
            + _significance_sentence(significance)
        )
    else:
        final_bps = dict(candidate_bps)
        reasoning.append(
            "Signifikanztest gegen die Hausmatrix nicht durchfuehrbar "
            f"({significance.get('reason')}); Optimierer-Allokation uebernommen."
        )
    payload["final_weights_bps"] = dict(final_bps)
    payload["elapsed_ms"] = int(round((time.perf_counter() - started) * 1000))
    return _finalize_solver_result(
        context,
        selection=aggregate_selection,
        weights=_trusted_weights_bps_to_array(final_bps),
        advisory_wealth_rappen=advisory_wealth_rappen,
        cashflow_series_rappen=cashflow_series_rappen,
        extra_reasoning=reasoning,
        resampling_payload=payload,
        drawdown_certification=drawdown_certification,
    )


def _with_house_prior(
    context: OptimizerContext,
    anchor_projected_bps: Mapping[str, int],
) -> OptimizerContext:
    """Context mit Hausmatrix-Prior (HOUSE-PRIOR-001); Anker read-only."""
    house = _trusted_weights_bps_to_array(dict(anchor_projected_bps)).copy()
    house.setflags(write=False)
    return replace(
        context, house_prior_weights=house, house_prior_kappa=HOUSE_PRIOR_KAPPA,
    )


def _validation_goal_rows(
    validation_context: OptimizerContext,
    w: np.ndarray,
    validation_seed: int,
) -> list[dict]:
    wealth = _simulate_context_wealth(validation_context, w)
    return publish_goal_achievability(
        wealth,
        validation_context.liabilities,
        validation_context.advisory_wealth_rappen,
        weights=None,
        annualized_return_bps_per_path=_annualized_twr_bps_per_path(
            validation_context, w
        ),
        validation_seed=int(validation_seed),
    )


def _house_prior_disclosure(
    context: OptimizerContext,
    *,
    candidate_bps: dict[str, int],
    house_anchor_bps: Mapping[str, int] | None,
    anchor_projected_bps: dict[str, int],
    config: ResamplingConfig,
) -> dict:
    """Offenlegung + Sicherheitsnetz des Hausmatrix-Priors (HOUSE-PRIOR-001).

    ``candidate_bps`` ist das projizierte, gerundete Bag-Mittel unter dem
    Prior. Ausgewiesen: kappa, Anker (roh/projiziert), Tracking Error zur
    Hausquote, Delta Zielebene Haus vs. Ergebnis mit gepaartem Bootstrap
    auf dem unabhaengigen Validierungswuerfel und die Zielwahrscheinlichkeit
    je Ziel fuer beide. Einziger Entscheid: ist das Ergebnis auf der
    Zielebene einseitig signifikant SCHLECHTER als die Hausquote, wird die
    Hausquote publiziert (``house_prior_guard``).
    """
    house_w = np.asarray(context.house_prior_weights, dtype=np.float64)
    candidate_w = _trusted_weights_bps_to_array(candidate_bps)
    cov = context.scenario_cov_bps2
    block: dict = {
        "version": HOUSE_PRIOR_VERSION,
        "kappa": float(context.house_prior_kappa),
        "prior_metric": prior_metric_audit(cov),
        "house_anchor_bps": dict(house_anchor_bps) if house_anchor_bps else None,
        "house_anchor_projected_bps": dict(anchor_projected_bps),
        "candidate_bps": dict(candidate_bps),
        "candidate_tracking_error_vs_house_bps": round(
            tracking_error_bps(candidate_w, house_w, cov), 4
        ),
        "disclosure": None,
        "goal_probabilities": None,
    }

    def _done(decision: str, reason: str, final_bps: dict[str, int]) -> dict:
        final_w = _trusted_weights_bps_to_array(final_bps)
        return {
            **block,
            "decision": decision,
            "reason": reason,
            "final_bps": dict(final_bps),
            "tracking_error_vs_house_bps": round(
                tracking_error_bps(final_w, house_w, cov), 4
            ),
            # Prior-Term des publizierten Ergebnisses (kappa_H * TE_M^2);
            # seit v7 Bestandteil von result.objective_value (der Abschluss
            # laeuft auf dem Prior-Context, siehe _run_resampled_solver).
            "final_prior_penalty": float(house_prior_penalty(
                final_w, house_w, cov, kappa=float(context.house_prior_kappa),
            )),
        }

    if candidate_bps == anchor_projected_bps:
        return _done(DECISION_HOUSE_PRIOR, REASON_IDENTICAL, candidate_bps)
    if max(
        abs(int(candidate_bps[bucket]) - int(anchor_projected_bps[bucket]))
        for bucket in BUCKET_ORDER
    ) <= HOUSE_ANCHOR_NUMERICAL_TOLERANCE_BPS:
        return _done(
            DECISION_HOUSE_PRIOR, REASON_WITHIN_TOLERANCE, dict(anchor_projected_bps),
        )
    if not config.significance_test:
        return _done(DECISION_HOUSE_PRIOR, REASON_TEST_DISABLED, candidate_bps)
    validation = _build_validation_context(context)
    if validation is None:
        # OPTIMIZER-POST-SELECTION-CERTIFICATION-001 (v7): ohne finalen
        # Holdout ist das Ergebnis nicht zertifiziert -> projizierte
        # Hausquote (fail-closed), nicht der Kandidat.
        return _done(
            DECISION_HOUSE_PRIOR_FAIL_CLOSED,
            REASON_NO_VALIDATION,
            dict(anchor_projected_bps),
        )
    validation_context, validation_seed, cube_hash = validation
    unit_ids, unit_name = _validation_sampling_units(validation_context)
    component_pair = _context_loss_components_on_validation(
        validation_context, house_w, candidate_w,
        validation_seed=int(validation_seed),
    )
    disclosure = paired_bootstrap_disclosure(
        lambda idx: tuple(parts[0] for parts in component_pair(idx)),
        n_paths=int(validation_context.n_paths),
        n_bootstrap=int(config.n_bootstrap),
        alpha=float(config.significance_alpha),
        seed=bootstrap_seed(validation_seed),
        sampling_unit_ids=unit_ids,
        sampling_unit=unit_name,
    )
    block.update({
        "disclosure": disclosure,
        "goal_probabilities": goal_probability_rows(
            _validation_goal_rows(validation_context, house_w, validation_seed),
            _validation_goal_rows(validation_context, candidate_w, validation_seed),
        ),
        "cube_role": CUBE_ROLE_FINAL,
        "validation_seed": int(validation_seed),
        "validation_cube_hash": cube_hash,
        "validation_n_paths": int(validation_context.n_paths),
    })
    if disclosure["significantly_worse"]:
        return _done(DECISION_HOUSE_PRIOR_GUARD, REASON_GUARD, anchor_projected_bps)
    return _done(DECISION_HOUSE_PRIOR, REASON_NOT_WORSE, candidate_bps)


def _significance_sentence(significance: Mapping) -> str:
    p_value = significance.get("p_value")
    lower = significance.get("improvement_lower_bound")
    improvement = significance.get("improvement")
    alpha = float(significance.get("alpha") or 0.05)
    units = significance.get("n_independent_units")
    unit_text = (
        f", {units} unabhaengige Einheiten ({significance.get('sampling_unit')})"
        if units is not None
        else ""
    )
    parts = [
        f"Gepaarter Bootstrap (B={significance.get('n_bootstrap')}, einseitig, "
        f"alpha={alpha:.0%}{unit_text}) auf dem finalen, unabhaengigen "
        f"Validierungs-Cube ({significance.get('validation_n_paths')} Pfade):"
    ]
    if significance.get("comparison") == "goal_level":
        parts.append(
            "Vergleich auf der Zielebene (Ziel-Fehlbetrag + Chance-Strafe); "
            "die Volatilitaet allein begruendet keine Abweichung"
        )
    if improvement is not None:
        parts.append(f"Verbesserung der Zielebene {float(improvement):.6e}")
    if lower is not None:
        parts.append(
            f"untere {1 - alpha:.0%}-Konfidenzgrenze {float(lower):.6e}"
        )
    if p_value is not None:
        parts.append(
            f"p = {float(p_value):.4f} (H0: keine Verbesserung, "
            "nullzentrierter Bootstrap)"
        )
    risk = significance.get("risk_measure_test")
    if isinstance(risk, Mapping):
        risk_p = risk.get("p_value")
        parts.append(
            "Risikomass "
            f"{float(risk.get('anchor_risk_measure') or 0.0) * 100:.2f} % "
            f"(Hausmatrix) vs {float(risk.get('candidate_risk_measure') or 0.0) * 100:.2f} % "
            f"(Optimierer), Verbesserung {float(risk.get('risk_improvement') or 0.0) * 10000:.1f} bps "
            f"gegen Materialitaetsschwelle {float(risk.get('materiality_threshold') or 0.0) * 10000:.0f} bps"
            + (f", p = {float(risk_p):.4f}" if risk_p is not None else "")
        )
    return " ".join(parts[:1]) + " " + ", ".join(parts[1:]) + "."


def _weights_to_bps_dict(
    weights: np.ndarray,
    bounds: list[tuple[float, float]] | None = None,
) -> dict[str, int]:
    """Konvertiert weight-array (0..1) in {bucket: bps}-dict.

    Stellt sicher dass Summe genau 10000 ist.

    SOLVER-BPS-APPORTIONMENT-001 (Kontrollrunde 2026-09-28): die alte
    Argmax-Korrektur gab den gesamten Rundungsrest immer dem groessten
    Gewicht, unabhaengig von dessen Bounds. Das konnte einen kontinuierlich
    zulaessigen Kandidaten an einer Cap-Grenze (z.B. 50% Aktien) kuenstlich
    ueber die Cap heben, obwohl eine andere 10.000-bps-Verteilung existiert,
    die alle Bounds einhaelt. Mit uebergebenen `bounds` wird der
    Rundungsrest stattdessen floor-basiert per groesstem Nachkommaanteil
    verteilt, wobei ein Bucket uebersprungen wird, sobald ihm der naechste
    bps-Schritt seine Obergrenze verletzen wuerde. Ohne `bounds`
    (Rueckwaertskompatibilitaet) bleibt die alte Argmax-Korrektur bestehen.
    """
    bps_floats = weights * 10000.0
    if bounds is None:
        bps_ints = [int(round(v)) for v in bps_floats]
        diff = 10000 - sum(bps_ints)
        if diff != 0:
            # Korrektur auf den groessten Bucket
            max_idx = int(np.argmax(weights))
            bps_ints[max_idx] += diff
        return {bucket: bps_ints[i] for i, bucket in enumerate(BUCKET_ORDER)}

    floor_bps = np.floor(bps_floats).astype(int)
    remainder = int(10000 - int(floor_bps.sum()))
    if remainder <= 0:
        # Floating-Point-Randfall (floor summiert bereits >= 10000): alte
        # Round+Argmax-Korrektur bleibt hier unveraendert das sicherste
        # bekannte Verhalten.
        bps_ints = [int(round(v)) for v in bps_floats]
        diff = 10000 - sum(bps_ints)
        if diff != 0:
            max_idx = int(np.argmax(weights))
            bps_ints[max_idx] += diff
        return {bucket: bps_ints[i] for i, bucket in enumerate(BUCKET_ORDER)}

    bps_ints = floor_bps.tolist()
    n = len(weights)
    upper_bps = [int(round(hi * 10000.0)) for _lo, hi in bounds]
    fractional = bps_floats - floor_bps
    # Groesster Nachkommaanteil zuerst (klassische Largest-Remainder-Methode),
    # aber ein Bucket an seiner Obergrenze wird uebersprungen statt verletzt.
    order = sorted(range(n), key=lambda i: fractional[i], reverse=True)
    assigned = 0
    attempts = 0
    max_attempts = remainder * n + n
    while assigned < remainder and attempts < max_attempts:
        i = order[attempts % n]
        if bps_ints[i] < upper_bps[i]:
            bps_ints[i] += 1
            assigned += 1
        attempts += 1
    if assigned < remainder:
        # Pathologische Bounds (kein Bucket hat mehr Platz): alte
        # Argmax-Korrektur als letzter Ausweg. Der nachgelagerte
        # is_feasible()-Post-Round-Check faengt eine dadurch entstehende
        # echte Constraint-Verletzung weiterhin korrekt als
        # diverged_infeasible ab.
        max_idx = int(np.argmax(weights))
        bps_ints[max_idx] += (remainder - assigned)
    return {bucket: int(bps_ints[i]) for i, bucket in enumerate(BUCKET_ORDER)}
