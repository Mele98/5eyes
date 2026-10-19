"""IMPORTANCE-SAMPLING-ESS-001 + GOAL-REACHABILITY-SCREEN-001 (2026-10-18).

Defekt (verifiziert): ``compute_likelihood_weights`` gewichtete mit
``exp(-mu' sum_t Z_t + T |mu|^2 / 2)`` bei ``mu = -0.5`` auf dem Aktienfaktor
in JEDEM Jahr. ``E_q[w^2] = exp(T |mu|^2)``, also ``ESS/N ~ exp(-T/4)``: bei
T = 31 rund 10 effektive von 2'000 Pfaden, Einzelpfade mit bis zu 33 % der
Gewichtsmasse. Die Chance-Constraint (Wilson-Grenze mit n = ESS) und alle
Zielwahrscheinlichkeiten der IS-Mandate (konservativ, Rentner, harte Ziele)
ruhten auf ~10 Pfaden.

Fix: horizont-skalierter Shift (Gesamtbudget c = 1 sigma des kumulierten
Faktors), defensive Mischung (alpha = 0.5, Gewichte <= 2), selbstnormierte
Schaetzer, ESS im Audit, Rueckfall auf Standard-MC unter 30 % ESS.
Herleitung: docs/planning/2026-10-18-importance-sampling-ess.md.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import norm

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for root in (BACKEND_ROOT, TESTS_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from services.optimizer import importance_sampling as IS  # noqa: E402
from services.optimizer.certification import effective_sample_size  # noqa: E402
from services.optimizer.scenario_engine import (  # noqa: E402
    ScenarioInputs,
    _log_parameters_for_inputs,
    build_scenario_paths,
    build_scenario_paths_with_weights,
)


def _inputs() -> ScenarioInputs:
    """Unkorreliert, ohne Schiefe/Kurtosis: der Aktien-Bucket ist exakt
    lognormal, ``E[W_T]`` und ``P(W_T < K)`` sind analytisch bekannt."""
    return ScenarioInputs(
        mu_bps=np.array([650.0, 150.0, 450.0, 400.0, 50.0]),
        sigma_bps=np.array([1600.0, 450.0, 1200.0, 1500.0, 50.0]),
        skew_bps=np.zeros(5),
        excess_kurt_bps=np.zeros(5),
        cholesky=np.eye(5),
    )


def _self_normalized(f: np.ndarray, w: np.ndarray) -> tuple[float, float]:
    """Selbstnormierter Schaetzer und sein Delta-Methoden-Standardfehler."""
    estimate = float(np.sum(f * w) / np.sum(w))
    se = float(np.sqrt(np.sum((w * (f - estimate)) ** 2)) / np.sum(w))
    return estimate, se


# ---------------------------------------------------------------------------
# e) Unverzerrtheit gegen analytische Lognormal-Werte
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("horizon", [5, 20, 40])
def test_is_estimators_are_unbiased_against_lognormal_closed_form(horizon):
    inputs = _inputs()
    location, scale = _log_parameters_for_inputs(inputs)
    paths, weights = build_scenario_paths_with_weights(
        inputs, horizon_years=horizon, n_paths=20_000, seed=20261018 + horizon,
        use_importance_sampling=True,
    )
    terminal = np.prod(paths[:, :, 0], axis=1)

    mean, se = _self_normalized(terminal, weights)
    exact_mean = (1.0 + 0.065) ** horizon
    assert abs(mean - exact_mean) <= 4.0 * se, (mean, exact_mean, se)

    for quantile in (0.05, 0.20):
        threshold = np.exp(
            horizon * location[0] + norm.ppf(quantile) * np.sqrt(horizon) * scale[0]
        )
        probability, se = _self_normalized((terminal < threshold).astype(float), weights)
        assert abs(probability - quantile) <= 4.0 * se, (horizon, quantile, probability, se)


# ---------------------------------------------------------------------------
# a)/b) ESS horizontunabhaengig, Gewichte beschraenkt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("horizon", [5, 10, 20, 31, 40])
def test_ess_fraction_is_horizon_independent(horizon):
    """Analytisch ESS/N = 1 / E_p[1/(alpha + (1-alpha) q/p)] = 0.83 (c = 1,
    alpha = 0.5), fuer JEDEN Horizont. Schwelle 0.5 laut CIO-Vorgabe."""
    for seed in (1, 2, 3):
        _paths, weights = build_scenario_paths_with_weights(
            _inputs(), horizon_years=horizon, n_paths=2_000, seed=seed,
            use_importance_sampling=True,
        )
        assert effective_sample_size(weights) / 2_000 >= 0.75


def test_legacy_per_year_shift_collapses_the_ess():
    """Gegenprobe zum Defekt: derselbe Shift von -0.5 in JEDEM der 31 Jahre
    (alter Vertrag, reiner Mean-Shift) -- ESS/N ~ exp(-31/4) = 4e-4."""
    rng = np.random.default_rng(31)
    legacy_shift = np.array([-0.5, 0.0, 0.0, 0.0, 0.0])
    x = rng.standard_normal(size=(2_000, 31, 5)) + legacy_shift
    legacy = IS.compute_likelihood_weights(x, legacy_shift)
    assert effective_sample_size(legacy) / 2_000 < 0.05


def test_weights_are_bounded_by_inverse_alpha_pathwise():
    _paths, weights = build_scenario_paths_with_weights(
        _inputs(), horizon_years=40, n_paths=5_000, seed=9,
        use_importance_sampling=True,
    )
    assert np.all(weights > 0.0)
    assert float(np.max(weights)) <= 1.0 / IS.IS_DEFENSIVE_MIXTURE_ALPHA + 1e-12
    # Kish: ESS >= alpha * sum(w) folgt deterministisch aus w <= 1/alpha.
    assert effective_sample_size(weights) >= (
        IS.IS_DEFENSIVE_MIXTURE_ALPHA * float(np.sum(weights)) - 1e-9
    )


def test_mixture_components_are_spread_over_every_prefix():
    mask = IS.mixture_shifted_mask(1_001, 0.5)
    assert int(mask.sum()) == 500
    for prefix in (10, 100, 500, 1_001):
        assert abs(float(mask[:prefix].mean()) - 0.5) <= 1.0 / prefix


# ---------------------------------------------------------------------------
# Tail-Abdeckung und Varianzgewinn
# ---------------------------------------------------------------------------


def test_tail_coverage_rises_against_nominal():
    """Anteil Pfade unter dem nominalen 5 %-Quantil des Aktien-Endwerts:
    nominal 5 %, defensive Mischung analytisch
    0.5 * 5 % + 0.5 * Phi(-1.645 + 1) = 15.5 %."""
    inputs = _inputs()
    location, scale = _log_parameters_for_inputs(inputs)
    horizon = 20
    threshold = np.exp(horizon * location[0] + norm.ppf(0.05) * np.sqrt(horizon) * scale[0])
    is_paths, _w = build_scenario_paths_with_weights(
        inputs, horizon_years=horizon, n_paths=10_000, seed=5,
        use_importance_sampling=True,
    )
    nominal = build_scenario_paths(inputs, horizon_years=horizon, n_paths=10_000, seed=5)
    is_share = float(np.mean(np.prod(is_paths[:, :, 0], axis=1) < threshold))
    nominal_share = float(np.mean(np.prod(nominal[:, :, 0], axis=1) < threshold))
    assert nominal_share == pytest.approx(0.05, abs=0.01)
    assert is_share == pytest.approx(0.155, abs=0.015)


def test_tail_probability_variance_is_reduced():
    """Analytischer Varianzgewinn fuer P(Aktien-Endwert < 5 %-Quantil): 2.4x.
    Gemessen ueber 60 unabhaengige Wuerfel zu je 2'000 Pfaden."""
    inputs = _inputs()
    location, scale = _log_parameters_for_inputs(inputs)
    horizon = 20
    threshold = np.exp(horizon * location[0] + norm.ppf(0.05) * np.sqrt(horizon) * scale[0])
    is_estimates, nominal_estimates = [], []
    for seed in range(60):
        paths, weights = build_scenario_paths_with_weights(
            inputs, horizon_years=horizon, n_paths=2_000, seed=1_000 + seed,
            use_importance_sampling=True,
        )
        tail = (np.prod(paths[:, :, 0], axis=1) < threshold).astype(float)
        is_estimates.append(_self_normalized(tail, weights)[0])
        nominal = build_scenario_paths(
            inputs, horizon_years=horizon, n_paths=2_000, seed=5_000 + seed,
            antithetic=False,
        )
        nominal_estimates.append(float(np.mean(np.prod(nominal[:, :, 0], axis=1) < threshold)))
    assert np.var(is_estimates) < np.var(nominal_estimates) / 1.4


# ---------------------------------------------------------------------------
# Gekuerzte Pfade: Gewichte der Marginale, gemeinsame Zufallszahlen
# ---------------------------------------------------------------------------


def test_weights_belong_to_the_used_year_prefix_and_paths_keep_crn():
    inputs = _inputs()
    full_paths, full_w = build_scenario_paths_with_weights(
        inputs, horizon_years=30, n_paths=500, seed=77, use_importance_sampling=True,
    )
    short_paths, short_w = build_scenario_paths_with_weights(
        inputs, horizon_years=30, n_paths=500, seed=77, use_importance_sampling=True,
        weight_horizon_years=12,
    )
    # Pfade identisch (Sensitivitaeten mit kuerzerem Horizont teilen den Wuerfel).
    assert np.array_equal(full_paths, short_paths)
    # Gewichte = Likelihood-Ratio der ersten 12 Jahre.
    rng = np.random.default_rng(np.uint64(77))
    z = rng.standard_normal(size=(500, 30, 5))
    profile = IS.per_year_shift_profile(IS.build_shift_vector(5), 30)
    x = z + IS.mixture_shifted_mask(500, IS.IS_DEFENSIVE_MIXTURE_ALPHA)[:, None, None] * profile
    expected = IS.compute_likelihood_weights(
        x[:, :12], profile[:12], mixture_alpha=IS.IS_DEFENSIVE_MIXTURE_ALPHA,
    )
    assert np.allclose(short_w, expected)
    assert not np.allclose(short_w, full_w)


# ---------------------------------------------------------------------------
# c)/d) Solver: ESS im Audit, Wilson mit n = ESS, Rueckfall
# ---------------------------------------------------------------------------


def _conservative_context(**overrides):
    from test_optimizer_context import _cma, _house_matrix, _pension_goal

    from services.optimizer.solver import build_optimizer_context

    house = _house_matrix()
    house.equity_min_bps = 0
    house.bonds_min_bps = 0
    house.real_estate_min_bps = 0
    house.alt_min_bps = 0
    house.liq_max_bps = 8000
    base = dict(
        cma=_cma(id="cma-is-ess"),
        goals=[_pension_goal()],
        house_matrix_row=house,
        score_x10=20,  # konservativ -> Auto-IS
        advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[20_000_00] * 25,
        horizon_years=25,
        n_paths=1_000,
        seed=4711,
    )
    base.update(overrides)
    return build_optimizer_context(**base)


def test_context_reports_ess_and_wilson_uses_it(monkeypatch):
    from config import settings

    from services.optimizer.objective import chance_constraint_penalty
    from services.optimizer.solver import _simulate_context_wealth

    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    ctx = _conservative_context()
    audit = ctx.importance_sampling_audit
    assert ctx.scenario_weights is not None and audit["active"] is True
    assert audit["scheme"] == IS.IS_SCHEME_VERSION
    assert audit["ess_fraction"] >= 0.75
    assert audit["ess"] == pytest.approx(effective_sample_size(ctx.scenario_weights))
    assert audit["max_weight_normalized"] <= 2.0 + 1e-9
    w = np.array([0.2, 0.5, 0.1, 0.1, 0.1])
    _penalty, rows = chance_constraint_penalty(
        _simulate_context_wealth(ctx, w), ctx.liabilities, ctx.advisory_wealth_rappen,
        weights=ctx.scenario_weights,
    )
    for row in rows:
        assert row["effective_sample_size"] == pytest.approx(audit["ess"])


def test_context_falls_back_to_standard_mc_below_ess_threshold(monkeypatch):
    from config import settings

    from services.optimizer.solver import _importance_sampling_reasoning

    monkeypatch.setattr(settings, "mc_importance_sampling_enabled", False, raising=False)
    monkeypatch.setattr(settings, "mc_importance_sampling_auto_enable", True, raising=False)
    monkeypatch.setattr(IS, "IS_ESS_FALLBACK_FRACTION", 0.99)
    ctx = _conservative_context(seed=4712)
    audit = ctx.importance_sampling_audit
    assert ctx.scenario_weights is None
    assert audit["decision_active"] is True and audit["active"] is False
    assert audit["fallback"] == "ess_below_threshold"
    line = _importance_sampling_reasoning(ctx)
    assert line.startswith("Importance Sampling INAKTIV") and "Rueckfall" in line


# ---------------------------------------------------------------------------
# GOAL-REACHABILITY-SCREEN-001
# ---------------------------------------------------------------------------


def _unreachable_goal():
    from datetime import date, timedelta
    from types import SimpleNamespace

    today = date.today()
    return SimpleNamespace(
        id="goal-unreachable", label="Unerreichbar", goal_type="Vermögensziel",
        target_amount_rappen=50_000_000_00,
        target_wealth_rappen=50_000_000_00, target_return_bps=None,
        horizon_years=None,
        start_date=today.isoformat(),
        target_date=(today + timedelta(days=365 * 8)).isoformat(),
        is_ongoing=0, frequency="jährlich",
        hardness="Hart", rank=2, weight_bps=5000, value_mode="real",
    )


def _screen_context(mode: str):
    from test_optimizer_context import _cma, _house_matrix, _pension_goal

    from services.optimizer.objective_contract import ObjectiveContractV1
    from services.optimizer.solver import build_optimizer_context

    return build_optimizer_context(
        cma=_cma(id="cma-reach"),
        goals=[_pension_goal(), _unreachable_goal()],
        house_matrix_row=_house_matrix(),
        score_x10=70,
        advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[20_000_00] * 10,
        horizon_years=10,
        n_paths=600,
        seed=8080,
        objective_contract=ObjectiveContractV1(
            objective_mode=mode, goal_weighting_mode="equal",
        ),
    )


def _unreachable_id(ctx) -> str:
    return next(str(l.goal_id) for l in ctx.liabilities if l.label == "Unerreichbar")


def test_unreachable_goal_still_steers_the_default_mode():
    """GOAL-SCREEN-OBJECTIVE-ERASURE-001 (Engine v7, CIO-Entscheid nach
    Codex-Review): ein auf der Pruefmenge unerreichbares Ziel wird offengelegt,
    aber NICHT mehr aus Primaerterm und Chance-Strafe genommen (bis v6:
    ``penalty_exempt_goal_ids``). Sein Fehlbetrag unterscheidet weiter
    zwischen viel und wenig Verfehlen."""
    from services.optimizer.goal_reachability import UNREACHABLE_TAU_FRACTION
    from services.optimizer.objective import shortfall_objective
    from services.optimizer.scenario_engine import BUCKET_ORDER
    from services.optimizer.solver import (
        _objective_from_array,
        _simulate_context_wealth,
        _weights_to_bps_dict,
        evaluate_weights,
    )

    ctx = _screen_context("goal_shortfall")
    screen = ctx.goal_reachability
    gid = _unreachable_id(ctx)
    assert screen["unreachable_goal_ids"] == [gid]
    assert screen["not_found_reachable_goal_ids"] == [gid]
    assert screen["penalty_exempt_goal_ids"] == []
    assert screen["role"] == "advisory_disclosure_only"
    row = next(r for r in screen["goals"] if r["goal_id"] == gid)
    assert row["reachable"] is False
    assert row["status"] == "not_found_reachable_in_screen_set"
    assert row["penalty_exempt"] is False
    assert row["max_upper_bound"] < UNREACHABLE_TAU_FRACTION * row["tau"]
    assert screen["n_candidates_evaluated"] == screen["n_candidates"] >= 5
    assert not hasattr(ctx, "penalty_exempt_goal_ids")

    w = np.array([0.6, 0.3, 0.05, 0.03, 0.02])
    wealth = _simulate_context_wealth(ctx, w)
    kwargs = dict(
        initial_wealth_rappen=ctx.advisory_wealth_rappen,
        horizon_years=ctx.horizon_years, weights=ctx.scenario_weights,
    )
    reachable_only = [l for l in ctx.liabilities if str(l.goal_id) != gid]
    assert shortfall_objective(ctx.liabilities, wealth, **kwargs) > shortfall_objective(
        reachable_only, wealth, **kwargs
    )
    bps = _weights_to_bps_dict(w, bounds=ctx.bounds)
    w_rounded = np.array([bps[b] / 10000.0 for b in BUCKET_ORDER])
    assert evaluate_weights(ctx, bps).objective_value == pytest.approx(
        _objective_from_array(ctx, w_rounded), rel=1e-12
    )


@pytest.mark.parametrize("success_share,reachable", [(0.54, True), (0.05, False)])
def test_half_tau_threshold_keeps_decision_relevant_goals_steering(
    monkeypatch, success_share, reachable,
):
    """Schwelle tau/2 (Offenlegung): ein Ziel mit max. 54 % gegen tau = 80 %
    gilt als auf der Pruefmenge erreichbar, eines mit max. 5 % nicht. Seit
    Engine v7 steuern BEIDE (kein Ausnehmen)."""
    from services.optimizer import objective as objective_module
    from services.optimizer.goal_reachability import goal_reachability_screen

    ctx = _screen_context("goal_shortfall")
    n = int(ctx.n_paths)

    def _constant_success(wealth, goal, *_args, **_kwargs):
        return (np.arange(wealth.shape[0]) < int(round(success_share * n))).astype(np.int8)

    monkeypatch.setattr(objective_module, "_goal_probability_core", _constant_success)
    screen = goal_reachability_screen(ctx)
    assert all(row["reachable"] is reachable for row in screen["goals"])
    assert bool(screen["not_found_reachable_goal_ids"]) is (not reachable)
    assert screen["penalty_exempt_goal_ids"] == []


@pytest.mark.parametrize("mode", ["max_drawdown", "min_volatility"])
@pytest.mark.parametrize("success_share,steers", [(0.54, False), (0.90, True)])
def test_risk_variants_steer_only_goals_whose_tau_is_reachable(
    monkeypatch, mode, success_share, steers,
):
    """Risikomass-Varianten: ein Ziel, dessen tau (80 %) auf keiner gepruften
    Allokation erreicht wird, bekommt einen eigenen Beraterhinweis -- es
    steuert seit Engine v7 aber weiter (GOAL-SCREEN-OBJECTIVE-ERASURE-001)."""
    from services.optimizer import objective as objective_module
    from services.optimizer.goal_reachability import (
        goal_reachability_screen,
        reachability_reasoning,
    )

    ctx = _screen_context(mode)
    n = int(ctx.n_paths)

    def _constant_success(wealth, goal, *_args, **_kwargs):
        return (np.arange(wealth.shape[0]) < int(round(success_share * n))).astype(np.int8)

    monkeypatch.setattr(objective_module, "_goal_probability_core", _constant_success)
    screen = goal_reachability_screen(ctx)
    assert all(row["reachable"] is True for row in screen["goals"])
    assert all(row["tau_reachable"] is steers for row in screen["goals"])
    assert bool(screen["not_found_reachable_goal_ids"]) is (not steers)
    assert screen["penalty_exempt_goal_ids"] == []
    lines = reachability_reasoning(screen)
    if steers:
        assert lines == []
    else:
        assert len(lines) == len(screen["goals"])
        assert all(
            "erreichte in der Risikovariante (" + mode + ")" in line
            and "es bleibt Teil der Zielfunktion" in line
            for line in lines
        )


@pytest.mark.parametrize("mode", ["max_drawdown", "min_volatility"])
def test_unreachable_goal_still_steers_risk_measure_variants(mode):
    """Engine v7: auch in den Varianten keine Ausnahme -- eine Zielfunktion
    (Hauptwuerfel, Bag, Nachbewertung, Validierung) mit dem Ziel."""
    from services.optimizer.drawdown_certification import validated_drawdown_evaluation
    from services.optimizer.objective import chance_constraint_penalty
    from services.optimizer.scenario_engine import BUCKET_ORDER
    from services.optimizer.solver import (
        _bag_context,
        _build_validation_context,
        _objective_from_array,
        _simulate_context_wealth,
        _weights_to_bps_dict,
        evaluate_weights,
    )

    ctx = _screen_context(mode)
    gid = _unreachable_id(ctx)
    assert gid in ctx.goal_reachability["not_found_reachable_goal_ids"]
    w = np.array([0.6, 0.3, 0.05, 0.03, 0.02])

    # Eine Zielfunktion: Hauptwuerfel, Bag, Nachbewertung, Validierung.
    penalty, rows = chance_constraint_penalty(
        _simulate_context_wealth(ctx, w), ctx.liabilities, ctx.advisory_wealth_rappen,
        weights=ctx.scenario_weights,
    )
    assert all("penalty_exempt" not in r for r in rows)
    without, _ = chance_constraint_penalty(
        _simulate_context_wealth(ctx, w),
        [l for l in ctx.liabilities if str(l.goal_id) != gid],
        ctx.advisory_wealth_rappen, weights=ctx.scenario_weights,
    )
    assert penalty > without  # das unerreichbare Ziel steuert
    bag = _bag_context(ctx, seed=123, n_paths=200)
    assert not hasattr(bag, "penalty_exempt_goal_ids")
    bps = _weights_to_bps_dict(w, bounds=ctx.bounds)
    w_rounded = np.array([bps[b] / 10000.0 for b in BUCKET_ORDER])
    assert evaluate_weights(ctx, bps).objective_value == pytest.approx(
        _objective_from_array(ctx, w_rounded), rel=1e-12
    )
    validation_context, validation_seed, _hash = _build_validation_context(ctx)
    if mode == "max_drawdown":
        evaluation = validated_drawdown_evaluation(
            validation_context, w_rounded, validation_seed=validation_seed,
        )
        expected, _ = chance_constraint_penalty(
            _simulate_context_wealth(validation_context, w_rounded),
            validation_context.liabilities,
            validation_context.advisory_wealth_rappen,
        )
        assert evaluation["chance_penalty"] == pytest.approx(expected)


def test_chance_penalty_has_no_exemption_any_more():
    """GOAL-SCREEN-OBJECTIVE-ERASURE-001: es gibt keinen Parameter mehr, mit
    dem ein Ziel aus der Strafe genommen werden kann."""
    import inspect

    from services.optimizer.goal_liabilities import GoalLiability
    from services.optimizer.objective import (
        chance_constraint_penalty,
        shortfall_objective,
    )

    assert "penalty_exempt_goal_ids" not in inspect.signature(
        chance_constraint_penalty).parameters
    assert "excluded_goal_ids" not in inspect.signature(
        shortfall_objective).parameters

    goal = GoalLiability(
        goal_id="g", label="g", goal_type="test", target_kind="wealth_at_t",
        target_amount_rappen=1_000, target_year_index=1, liability_path_rappen=[],
        hardness_key="hart", weight_bps=10_000, success_probability_min_x100=8_000,
    )
    never = np.column_stack([np.full(400, 100.0), np.full(400, 10.0)])
    steered, rows = chance_constraint_penalty(never, [goal], 100)
    assert steered > 0.0
    assert rows[0]["probability"] == 0.0 and "penalty_exempt" not in rows[0]


def test_bps_rounding_on_an_active_linear_constraint_is_repaired():
    """BPS-ROUNDING-ON-ACTIVE-CONSTRAINT-001: der Varianz-Tiebreak legt
    ziel-sichere Mandate auf aktive lineare Nebenbedingungen; die bps-Rundung
    verletzte sie dort um Bruchteile eines bps (Referenzmandat M1: -5e-6,
    Status ``diverged_infeasible``). Nachbau mit dem gemessenen Punkt."""
    from services.optimizer.constraints import is_feasible
    from services.optimizer.scenario_engine import BUCKET_ORDER
    from services.optimizer.solver import (
        _repair_rounded_bps,
        _trusted_weights_bps_to_array,
        _weights_to_bps_dict,
    )

    bounds = [(0.05, 0.25), (0.5, 0.8), (0.0, 0.15), (0.0, 0.05), (0.05, 0.2)]
    rf = np.array([1.0, 0.0, 1.0, 1.0, 0.0])
    cap = 0.05 + 0.037278 + 0.027007 + 5e-7
    constraints = [{"type": "ineq", "fun": lambda w: float(cap - float(np.dot(w, rf)))}]
    w = np.array([0.05, 0.685714, 0.037278, 0.027007, 0.2])
    w = w / w.sum()
    assert is_feasible(w, bounds=bounds, constraints=constraints)[0]
    rounded = _weights_to_bps_dict(w, bounds=bounds)
    assert not is_feasible(
        _trusted_weights_bps_to_array(rounded), bounds=bounds, constraints=constraints,
    )[0]
    repaired = _repair_rounded_bps(rounded, bounds, constraints)
    assert repaired is not None and sum(repaired.values()) == 10_000
    assert is_feasible(
        _trusted_weights_bps_to_array(repaired), bounds=bounds, constraints=constraints,
    )[0]
    assert sum(abs(repaired[b] - rounded[b]) for b in BUCKET_ORDER) <= 4


def test_reachability_is_published_on_goal_rows(monkeypatch):
    from services.optimizer.resampling import SINGLE_CUBE
    from services.optimizer.solver import run_solver
    from test_optimizer_context import _cma, _house_matrix, _pension_goal

    result = run_solver(
        cma=_cma(id="cma-reach-pub"),
        goals=[_pension_goal(), _unreachable_goal()],
        house_matrix_row=_house_matrix(),
        score_x10=70,
        advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[20_000_00] * 10,
        horizon_years=10,
        n_paths=400,
        seed=8081,
        resampling=SINGLE_CUBE,
    )
    assert result.goal_reachability is not None
    rows = {r["label"]: r for r in result.goal_achievability if r.get("goal_id")}
    assert rows["Unerreichbar"]["feasible_set_reachable"] is False
    hints = [line for line in result.reasoning if line.startswith("Beraterhinweis: Ziel 'Unerreichbar'")]
    assert len(hints) == 1
    assert "mit der Mindestsicherheit erreichbar" in hints[0]
    assert "Ziel mit dem Kunden ueberpruefen (Betrag, Termin, Prioritaet)" in hints[0]
    assert "nachrangig verfolgt und verdraengt keine erreichbaren Ziele" in hints[0]
