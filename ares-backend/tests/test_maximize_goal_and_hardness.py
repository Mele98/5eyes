"""MAXIMIZE-GOAL-001 + GOAL-HARDNESS-DEFAULT-001 (CIO-Entscheid 2026-10-18,
Engine ``saa_resampled_v7``).

Befund A (v6): das Ziel "Maximierung" hatte im Optimierer den Fehlbetrag 0
(``objective.shortfall_squared_per_path``) und keine Chance-Strafe. Ein
Kunde, der "Vermoegen maximieren" waehlt, bekam exakt die Hausquote --
dieselbe Allokation wie ganz ohne Ziel (Reproducer unten:
``test_maximize_goal_tilts_toward_growth_within_eligibility``).

Befund B (v6): der Haertegrad war im Default ``OPTIMIZER_GOAL_WEIGHTING=equal``
wirkungslos -- Fehlbetrag (h_g = 1) und Chance-Strafe (gleiches tau, gleiches
Gewicht) waren fuer "hart" und "primaer" identisch.

Neu: Maximierung = Log-Wachstumsterm ``-T * E[log(1 + r_TWR)]`` in G;
Haertegrad standardmaessig auf den Fehlbetrag (OD-1-Gewichte 10 / 1 / 0.2,
fuer Maximierung auf "primaer" gedeckelt) UND als Zielhierarchie
(GOAL-HIERARCHY-001): harte/primaere Ziele sind Stufe 1; der Rest der
Zielfunktion (inkl. Haus-Prior) wird nur unter G1 <= G1* + eps minimiert.
Dazu die Codex-Reproducer zur Reachability-Ausnahme (Abschnitt 6).
Doku: docs/planning/2026-10-18-maximize-goal-and-hardness.md.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import services.optimizer.objective as objective_module  # noqa: E402
import services.optimizer.solver as solver_module  # noqa: E402
from services.optimizer.goal_liabilities import GoalLiability  # noqa: E402
from services.optimizer.scenario_engine import BUCKET_ORDER  # noqa: E402
from test_engine_input_sensitivity import _cma, _hm_wachstum  # noqa: E402
from test_engine_reference_mandates import _make_goal  # noqa: E402


@pytest.fixture(autouse=True)
def _default_goal_weighting(monkeypatch):
    """Alle Tests gegen den DOKUMENTIERTEN Default (Variable nicht gesetzt)."""
    monkeypatch.delenv("OPTIMIZER_GOAL_WEIGHTING", raising=False)


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

HOUSE_ANCHOR = {
    "equities": 6000, "bonds": 3000, "real_estate": 500,
    "alternatives": 300, "liquidity": 200,
}


def _max_goal(horizon_years: int, hardness: str = "Primär"):
    today = date.today()
    return SimpleNamespace(
        id="mx", label="Vermoegen maximieren", goal_type="Maximierung",
        goal_family="Maximierung", target_amount_rappen=None,
        target_wealth_rappen=None, target_return_bps=None,
        horizon_years=horizon_years, start_date=today.isoformat(),
        target_date=(today + timedelta(days=365 * horizon_years)).isoformat(),
        is_ongoing=0, frequency=None, hardness=hardness, rank=1,
        weight_bps=None, value_mode="nominal",
    )


def _wealth_goal(amount_rappen: int, hardness: str):
    return _make_goal(
        goal_id="vz", label="VZ", hardness=hardness, goal_type="Vermoegensziel",
        target_rappen=amount_rappen, target_date_offset_days=365 * 25,
    )


def _inputs(goals, horizon: int) -> dict:
    return dict(
        cma=_cma(), goals=goals, house_matrix_row=_hm_wachstum(), score_x10=75,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[0] * horizon,
        horizon_years=horizon, n_paths=500,
    )


_RUNS: dict = {}


def _run(goals, horizon: int, *, seed: int | None = None, key=None):
    cache_key = (key, horizon, seed)
    if key is None or cache_key not in _RUNS:
        inputs = _inputs(goals, horizon)
        context = solver_module.build_optimizer_context(seed=seed, **inputs)
        result = solver_module.run_solver(
            **inputs, optimizer_context=context, house_anchor_bps=HOUSE_ANCHOR,
        )
        if key is None:
            return result, context
        _RUNS[cache_key] = (result, context)
    return _RUNS[cache_key]


def _w(weights_bps) -> np.ndarray:
    return np.array([int(weights_bps[b]) for b in BUCKET_ORDER], dtype=float) / 1e4


def _liability(kind: str, *, hardness: str = "primaer", target: int = 0,
               horizon: int = 10, goal_id: str = "g", weight_bps: int = 10000):
    return GoalLiability(
        goal_id=goal_id, label=goal_id, goal_type=kind, target_kind=kind,
        target_amount_rappen=target, target_year_index=horizon,
        liability_path_rappen=[0] * horizon, hardness_key=hardness,
        weight_bps=weight_bps, success_probability_min_x100=8000,
    )


# ---------------------------------------------------------------------------
# 1. Versionierung + ObjectiveContractV2
# ---------------------------------------------------------------------------


def test_engine_version_is_v7_and_objective_contract_v2_is_disclosed():
    result, context = _run([], 10, key="no_goals_10")
    resampling = result.resampling
    assert resampling["engine_version"] == "saa_resampled_v12"
    contract = resampling["objective_contract"]
    assert contract["objective_contract_version"] == "objective-contract-v2"
    assert contract["goal_weighting_mode"] == "hardness"
    assert contract["goal_hardness_policy"] == (
        "hardness_scales_shortfall_and_protection_v1")
    assert contract["goal_hierarchy_policy"] == "protected_goals_lexicographic_v2_reachable_only"
    assert contract["maximize_goal_policy"] == "maximize_log_growth_v1"
    assert contract["hardness_weights"] == {
        "hart": 10.0, "opportunistisch": 0.2, "primaer": 1.0}
    assert contract["goal_erosion_z"] == pytest.approx(1.6448536269514722)
    assert contract["objective_contract_hash"] == (
        context.objective_contract.contract_hash)
    from services.optimizer.resampling import resampling_model_basis

    assert resampling_model_basis(resampling)["objective_contract"] == contract


def test_objective_contract_v2_binds_every_coefficient_and_fails_closed():
    """OBJECTIVE-CROSS-TERM-GOVERNANCE-001: jeder Koeffizient/jede Policy
    geht in den Hash; ein Vertrag mit einer Mathematik, die der Code nicht
    rechnet, kann nicht gebaut werden (kein stiller Replay)."""
    from services.optimizer.objective_contract import (
        ObjectiveContractError,
        ObjectiveContractV1,
        ObjectiveContractV2,
        implemented_objective_policy,
        resolve_objective_contract,
    )

    contract = resolve_objective_contract()
    assert isinstance(contract, ObjectiveContractV2)
    assert isinstance(contract, ObjectiveContractV1)  # alle V1-Konsumenten
    v1 = ObjectiveContractV1(
        objective_mode=contract.objective_mode,
        goal_weighting_mode=contract.goal_weighting_mode,
    )
    assert contract.contract_hash != v1.contract_hash
    for name, value in implemented_objective_policy().items():
        assert getattr(contract, name) == value, name
    with pytest.raises(ObjectiveContractError):
        ObjectiveContractV2(
            objective_mode="goal_shortfall", goal_weighting_mode="hardness",
            house_prior_kappa=30.0,
        )
    with pytest.raises(ObjectiveContractError):
        ObjectiveContractV2(
            objective_mode="goal_shortfall", goal_weighting_mode="hardness",
            goal_erosion_z=0.0,
        )
    equal = ObjectiveContractV2(
        objective_mode="goal_shortfall", goal_weighting_mode="equal")
    assert equal.contract_hash != contract.contract_hash


# ---------------------------------------------------------------------------
# 2. A -- Maximierung: Formel
# ---------------------------------------------------------------------------


def test_maximize_term_is_minus_expected_log_growth_over_the_horizon():
    """L(w) fuer ein Maximierungsziel = -T * mean_n log(1 + r_n) (Gewicht 1,
    primaer). v6: 0 fuer jede Allokation."""
    rng = np.random.default_rng(7)
    n, horizon = 400, 12
    twr_bps = rng.normal(450.0, 900.0, size=n)
    wealth = np.full((n, horizon + 1), 1e8)
    liab = _liability("maximize", horizon=horizon)
    value = objective_module.shortfall_objective(
        [liab], wealth, initial_wealth_rappen=1e8, horizon_years=horizon,
        annualized_return_bps_per_path=twr_bps,
    )
    expected = -horizon * float(np.mean(np.log1p(twr_bps / 1e4)))
    assert value == pytest.approx(expected, rel=1e-12)
    assert value < 0.0


def test_maximize_term_is_scale_free_in_initial_wealth():
    rng = np.random.default_rng(3)
    twr_bps = rng.normal(400.0, 800.0, size=300)
    liab = _liability("maximize", horizon=8)
    values = [
        objective_module.shortfall_objective(
            [liab], np.full((300, 9), w0), initial_wealth_rappen=w0,
            horizon_years=8, annualized_return_bps_per_path=twr_bps,
        )
        for w0 in (5_000_00, 500_000_00, 50_000_000_00)
    ]
    assert values[0] < 0.0
    assert values[0] == pytest.approx(values[1], rel=1e-12)
    assert values[1] == pytest.approx(values[2], rel=1e-12)


def test_maximize_term_is_risk_averse_for_equal_arithmetic_mean():
    """Jensen: gleiche mittlere Rendite, mehr Streuung -> schlechter (der Term
    maximiert das Median-/Log-Wachstum, nicht den arithmetischen Mittelwert)."""
    liab = _liability("maximize", horizon=10)
    wealth = np.full((2, 11), 1e8)
    calm = np.array([500.0, 500.0])
    volatile = np.array([-1500.0, 2500.0])
    kwargs = dict(initial_wealth_rappen=1e8, horizon_years=10)
    calm_value = objective_module.shortfall_objective(
        [liab], wealth, annualized_return_bps_per_path=calm, **kwargs)
    volatile_value = objective_module.shortfall_objective(
        [liab], wealth, annualized_return_bps_per_path=volatile, **kwargs)
    assert calm_value < volatile_value


def test_maximize_goal_weight_and_hardness_cap():
    """Rang-Gewicht wirkt (g_g = weight_bps/1e4); "hart" zaehlt fuer eine
    Maximierung nur wie "primaer" (kein Zielwert, keine Zielsicherheit)."""
    twr = np.array([300.0, 700.0])
    wealth = np.full((2, 11), 1e8)
    kwargs = dict(initial_wealth_rappen=1e8, horizon_years=10,
                  annualized_return_bps_per_path=twr)
    primary = objective_module.shortfall_objective(
        [_liability("maximize", hardness="primaer")], wealth, **kwargs)
    hard = objective_module.shortfall_objective(
        [_liability("maximize", hardness="hart")], wealth, **kwargs)
    opportunistic = objective_module.shortfall_objective(
        [_liability("maximize", hardness="opportunistisch")], wealth, **kwargs)
    half_weight = objective_module.shortfall_objective(
        [_liability("maximize", weight_bps=5000)], wealth, **kwargs)
    assert primary < 0.0
    assert hard == pytest.approx(primary, rel=1e-12)
    assert opportunistic == pytest.approx(0.2 * primary, rel=1e-12)
    assert half_weight == pytest.approx(0.5 * primary, rel=1e-12)


def test_goal_driver_contributions_still_sum_to_the_objective_with_maximize():
    rng = np.random.default_rng(11)
    n, horizon = 200, 10
    wealth = rng.normal(1.3e8, 4e7, size=(n, horizon + 1))
    twr = rng.normal(400.0, 700.0, size=n)
    liabs = [
        _liability("maximize", goal_id="mx", horizon=horizon),
        _liability("wealth_at_t", goal_id="vz", target=int(1.5e8),
                   horizon=horizon, hardness="hart"),
    ]
    kwargs = dict(initial_wealth_rappen=1e8, horizon_years=horizon,
                  annualized_return_bps_per_path=twr)
    total = objective_module.shortfall_objective(liabs, wealth, **kwargs)
    rows = objective_module.shortfall_contributions(liabs, wealth, **kwargs)
    assert sum(r.weighted_objective_contribution for r in rows) == pytest.approx(
        total, rel=1e-12)


# ---------------------------------------------------------------------------
# 3. A -- Maximierung im Solver (Reproducer)
# ---------------------------------------------------------------------------


def _expected_return(context, weights_bps) -> float:
    mu = np.asarray(context.scenario_mu_bps, dtype=float) / 1e4
    return float(mu @ _w(weights_bps))


def test_maximize_goal_tilts_toward_growth_within_eligibility():
    """Reproducer A. v6: Maximierung == keine Ziele == Hausquote (identisch).
    v7: Abweichung Richtung Wachstum, innerhalb Bandbreiten und Risikobudget,
    und nur so weit, wie der Haus-Prior sie bezahlt (TE klein)."""
    no_goal, _ = _run([], 25, key="no_goals_25")
    result, context = _run([_max_goal(25)], 25, key="max_25")
    assert no_goal.weights_bps == HOUSE_ANCHOR
    assert result.weights_bps != no_goal.weights_bps
    gain_bps = (_expected_return(context, result.weights_bps)
                - _expected_return(context, HOUSE_ANCHOR)) * 1e4
    assert gain_bps >= 10.0, (gain_bps, result.weights_bps)

    block = result.resampling["house_prior"]
    assert 20.0 <= block["tracking_error_vs_house_bps"] <= 300.0, block[
        "tracking_error_vs_house_bps"]
    # Eignung bleibt harte Restriktion.
    hm = _hm_wachstum()
    bands = {
        "equities": (hm.equity_min_bps, hm.equity_max_bps),
        "bonds": (hm.bonds_min_bps, hm.bonds_max_bps),
        "real_estate": (hm.real_estate_min_bps, hm.real_estate_max_bps),
        "alternatives": (hm.alt_min_bps, hm.alt_max_bps),
        "liquidity": (hm.liq_min_bps, hm.liq_max_bps),
    }
    for bucket, (low, high) in bands.items():
        assert low <= result.weights_bps[bucket] <= high, bucket
    assert sum(result.weights_bps.values()) == 10000
    from services.optimizer.constraints import is_feasible

    feasible, violations = is_feasible(
        _w(result.weights_bps), bounds=context.bounds,
        constraints=context.scipy_constraints,
    )
    assert feasible, violations  # inkl. Risikobudget (max_risky_fraction)


def test_maximize_tilt_grows_with_the_horizon():
    """Laengerer Horizont -> groesserer Wachstumsnutzen je Abweichung ->
    groessere (aber weiterhin begrenzte) Abweichung von der Hausquote."""
    long_result, _ = _run([_max_goal(25)], 25, key="max_25")
    short_result, _ = _run([_max_goal(10)], 10, key="max_10")
    long_te = long_result.resampling["house_prior"]["tracking_error_vs_house_bps"]
    short_te = short_result.resampling["house_prior"]["tracking_error_vs_house_bps"]
    assert short_te > 0.0
    assert long_te > short_te


# ---------------------------------------------------------------------------
# 4. B -- Haertegrad wirkt standardmaessig
# ---------------------------------------------------------------------------


def test_default_goal_weighting_mode_is_hardness():
    from config import DEFAULT_GOAL_WEIGHTING_MODE, Settings, validate_goal_weighting_mode

    assert DEFAULT_GOAL_WEIGHTING_MODE == "hardness"
    assert validate_goal_weighting_mode(None) == "hardness"
    assert objective_module.resolve_goal_weighting_mode() == "hardness"
    assert Settings.model_fields["optimizer_goal_weighting"].default == "hardness"
    assert validate_goal_weighting_mode("equal") == "equal"


def _deficit_paths(n: int = 400, achieved: int = 200, target: float = 1.5e8):
    wealth = np.full((n, 11), 1e8)
    wealth[:achieved, 10] = target * 1.1
    return wealth


def test_chance_penalty_stays_an_unweighted_soft_regret():
    """Der Haertegrad wirkt ueber Fehlbetrag und Zielhierarchie, nicht ueber
    die (weiche) Chance-Strafe: gleiches Defizit, gleiche Strafe."""
    wealth = _deficit_paths()
    penalties = [
        objective_module.chance_constraint_penalty(
            wealth,
            [_liability("wealth_at_t", target=int(1.5e8), hardness=hardness)],
            int(1e8),
        )[0]
        for hardness in ("hart", "primaer")
    ]
    assert penalties[0] > 0.0
    assert penalties[0] == pytest.approx(penalties[1], rel=1e-12)


def test_default_goal_level_orders_hard_above_primary_above_opportunistic():
    wealth = _deficit_paths()
    levels = {}
    for hardness in ("hart", "primaer", "opportunistisch"):
        goal_level, _tiebreak = objective_module.two_phase_objective_parts(
            [_liability("wealth_at_t", target=int(1.5e8), hardness=hardness)],
            wealth, initial_wealth_rappen=1e8, horizon_years=10,
        )
        levels[hardness] = goal_level
    assert levels["hart"] > levels["primaer"] > levels["opportunistisch"] > 0.0


def test_equal_opt_out_restores_hardness_neutral_goal_level(monkeypatch):
    monkeypatch.setenv("OPTIMIZER_GOAL_WEIGHTING", "equal")
    wealth = _deficit_paths()
    levels = [
        objective_module.two_phase_objective_parts(
            [_liability("wealth_at_t", target=int(1.5e8), hardness=hardness)],
            wealth, initial_wealth_rappen=1e8, horizon_years=10,
        )[0]
        for hardness in ("hart", "primaer")
    ]
    assert levels[0] == pytest.approx(levels[1], rel=1e-12)


# ---------------------------------------------------------------------------
# 5. GOAL-HIERARCHY-001 -- harte/primaere Ziele als Stufe 1
# ---------------------------------------------------------------------------


def test_protected_goal_level_contains_exactly_the_protected_goal_terms():
    """G1 = sum ueber harte/primaere Ziele von (h * g * L + C) -- dieselben
    Terme wie in der Zielfunktion; opportunistische Ziele und Maximierung
    gehoeren nicht dazu."""
    rng = np.random.default_rng(5)
    wealth = rng.normal(1.2e8, 4e7, size=(300, 11))
    goals = {
        hardness: _liability("wealth_at_t", target=int(1.5e8), hardness=hardness,
                             goal_id=hardness)
        for hardness in ("hart", "primaer", "opportunistisch")
    }
    maximize = _liability("maximize", goal_id="mx")
    kwargs = dict(initial_wealth_rappen=1e8, horizon_years=10)
    level, per_path = objective_module.protected_goal_level(
        [*goals.values(), maximize], wealth, with_per_path=True, **kwargs)
    protected = [goals["hart"], goals["primaer"]]
    expected = objective_module.shortfall_objective(protected, wealth, **kwargs) + (
        objective_module.chance_constraint_penalty(wealth, protected, int(1e8))[0])
    assert level == pytest.approx(expected, rel=1e-12)
    assert per_path.shape == (300,)
    assert objective_module.monte_carlo_standard_error(per_path) > 0.0


def _goal_context(hardness: str = "Hart", seed: int = 11, amount: int = 1_200_000_00):
    inputs = _inputs([_wealth_goal(amount, hardness)], 25)
    return solver_module.build_optimizer_context(seed=seed, **inputs)


@pytest.mark.parametrize("hardness", ["Hart", "Primär"])
def test_house_prior_cannot_buy_erosion_of_a_protected_goal(hardness):
    """Lexikographisch statt verrechenbar: auch ein (absichtlich) extremer
    Haus-Prior (kappa = 1e6, waere ohne Hierarchie praktisch die Hausquote)
    darf das Stufe-1-Niveau nicht ueber ``G1* + eps`` hinaus erodieren."""
    from dataclasses import replace

    context = _goal_context(hardness)
    house = _w(HOUSE_ANCHOR)
    strong_prior = replace(context, house_prior_weights=house, house_prior_kappa=1e6)
    selection = solver_module._select_cube_candidate(
        strong_prior, max_iter=50, ftol=1e-6)
    audit = selection.goal_protection
    assert audit is not None and audit["protected_goal_ids"] == ["vz"]

    def level(w):
        return solver_module._protected_level_from_inputs(
            strong_prior, solver_module._evaluation_inputs(strong_prior, w))[0]

    assert level(house) > audit["bound"]  # die Hausquote wuerde erodieren
    assert level(selection.weights) <= audit["bound"] * (1.0 + 1e-6)
    assert audit["final_level"] == pytest.approx(level(selection.weights), rel=1e-9)


def test_erosion_tolerance_is_z_times_paired_standard_error_divided_by_hardness():
    """eps = z * SE(G1(w_H) - G1(w1*)) / h_max + numerische Toleranz; h_max =
    10 sobald ein hartes Ziel geschuetzt ist, sonst 1."""
    from dataclasses import replace

    from services.optimizer.objective import GOAL_EROSION_NUMERIC_TOL, GOAL_EROSION_Z

    audits = {}
    for hardness in ("Hart", "Primär"):
        context = replace(
            _goal_context(hardness, amount=700_000_00), house_prior_weights=_w(HOUSE_ANCHOR))
        audits[hardness] = solver_module._select_cube_candidate(
            context, max_iter=50, ftol=1e-6).goal_protection
    assert audits["Hart"]["hardness_divisor"] == 10.0
    assert audits["Primär"]["hardness_divisor"] == 1.0
    for audit in audits.values():
        assert audit["tolerance_basis"] == "paired_house_vs_stage1"
        assert audit["erosion_tolerance"] == pytest.approx(
            GOAL_EROSION_Z * audit["standard_error"] / audit["hardness_divisor"]
            + GOAL_EROSION_NUMERIC_TOL, rel=1e-12)


def test_certain_goals_skip_stage_one_and_keep_the_house_quota():
    """Ziele mit der Hausquote sicher erreicht (G1 = 0 an einem Startpunkt):
    keine Stufe-1-Loesung, Hausquote unveraendert (wie die Golden-Mandate)."""
    result, _ = _run([_wealth_goal(100_000_00, "Hart")], 25, key="certain_hard")
    audits = [b["goal_protection"] for b in result.resampling["bags"]]
    assert audits and all(a is not None for a in audits)
    assert all(a["stage1_solves"] == 0 and a["level_star"] == 0.0 for a in audits)
    assert result.weights_bps == HOUSE_ANCHOR


def test_risk_measure_variants_have_no_goal_hierarchy_yet(monkeypatch):
    """Phase 1: die Hierarchie gilt im Default ``goal_shortfall``; das
    Goal-Preservation-Gate der Varianten (Codex-Befund 4) ist Phase 2."""
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", "min_volatility")
    selection = solver_module._select_cube_candidate(
        _goal_context("Hart"), max_iter=50, ftol=1e-6)
    assert selection.goal_protection is None


def test_hardness_orders_the_deviation_from_the_house_quota():
    """Reproducer B. Vermoegensziel CHF 0.7 Mio (Hausquote erreicht es mit
    ~96 %). v6: hart == primaer (gleiche Zielfunktion). v7: opportunistisch
    und primaer bleiben bei der Hausquote (Restfehlbetrag im Rauschen), ein
    HARTES Ziel duldet nur ein Zehntel dieses Rauschens -- die Allokation
    wird defensiver und das Ziel sicherer."""
    results = {
        hardness: _run([_wealth_goal(700_000_00, hardness)], 25, seed=11,
                       key=f"vz07_{hardness}")
        for hardness in ("Opportunistisch", "Primär", "Hart")
    }

    def te(hardness):
        return float(results[hardness][0].resampling["house_prior"][
            "tracking_error_vs_house_bps"])

    def probability(hardness):
        # Publizierte Zielwahrscheinlichkeit (Validierungswuerfel); die
        # Haus-vs-Final-Offenlegung fehlt seit Engine v7 (#649), wenn das
        # Ergebnis die Hausquote ist.
        rows = results[hardness][0].goal_achievability
        return float(next(r for r in rows if r.get("goal_id") == "vz")["probability"])

    def vol(hardness):
        result, context = results[hardness]
        cov = np.asarray(context.scenario_cov_bps2, dtype=float) / 1e8
        w = _w(result.weights_bps)
        return float(np.sqrt(w @ cov @ w))

    assert te("Opportunistisch") <= 5.0 and te("Primär") <= 5.0
    assert te("Hart") >= 50.0, te("Hart")
    assert probability("Hart") > probability("Primär") >= probability("Opportunistisch") - 1e-9
    assert vol("Hart") < vol("Primär")
    hard_eq = results["Hart"][0].weights_bps["equities"]
    assert hard_eq < results["Primär"][0].weights_bps["equities"]


# ---------------------------------------------------------------------------
# 6. Codex-Reproducer (docs/audits/reproducers/
#    test_2026_10_18_pr631_goal_reachability_adversarial.py), uebernommen als
#    regulaere Tests; Aufruf nur dort angepasst, wo die Schnittstelle
#    absichtlich entfallen ist (siehe jeweiliger Docstring).
# ---------------------------------------------------------------------------


def _codex_hard_wealth_goal():
    return GoalLiability(
        goal_id="hard-goal", label="Hard goal", goal_type="Vermoegensziel",
        target_kind="wealth_at_t", target_amount_rappen=1_000, target_year_index=1,
        liability_path_rappen=[0], hardness_key="hart", weight_bps=10_000,
        success_probability_min_x100=8_000,
    )


def test_codex_unreachable_label_must_not_erase_shortfall_ranking():
    """Codex GOAL-SCREEN-OBJECTIVE-ERASURE-001. Original-Aufruf mit
    ``excluded_goal_ids={"hard-goal"}``: der Parameter existiert nicht mehr
    (es gibt keinen Weg, ein Ziel auszunehmen) -- geprueft wird zuerst genau
    das, danach die Rangfolge CHF 900 besser als CHF 0."""
    import inspect

    assert "excluded_goal_ids" not in inspect.signature(
        objective_module.shortfall_objective).parameters
    goal = _codex_hard_wealth_goal()
    worse = np.column_stack([np.full(400, 100.0), np.full(400, 0.0)])
    better = np.column_stack([np.full(400, 100.0), np.full(400, 900.0)])
    kwargs = {"initial_wealth_rappen": 100, "horizon_years": 1,
              "goal_weighting_mode": "equal"}
    assert objective_module.shortfall_objective([goal], better, **kwargs) < (
        objective_module.shortfall_objective([goal], worse, **kwargs))
    # Auch die Stufe-1-Groesse (Zielhierarchie) unterscheidet beide.
    assert objective_module.protected_goal_level([goal], better, **{
        k: v for k, v in kwargs.items() if k != "goal_weighting_mode"})[0] < (
        objective_module.protected_goal_level([goal], worse, **{
            k: v for k, v in kwargs.items() if k != "goal_weighting_mode"})[0])


def test_codex_finite_candidate_screen_must_not_claim_full_feasible_set(monkeypatch):
    """Codex GOAL-SCREEN-FEASIBLE-SET-PROOF-001. Angepasst: der Screen baut
    seinen eigenen Screening-Wuerfel (``_build_screening_context``) statt des
    Validierungswuerfels; derselbe Gegenbeweis (Innenpunkt erfolgreich, beide
    geprueften Endpunkte nicht) wird dort eingespeist."""
    from services.optimizer import goal_reachability as reachability
    from services.optimizer.objective_contract import ObjectiveContractV1

    goal = _codex_hard_wealth_goal()
    context = SimpleNamespace(
        liabilities=[goal], horizon_years=1, n_paths=200, advisory_wealth_rappen=100,
        objective_contract=ObjectiveContractV1(
            objective_mode="goal_shortfall", goal_weighting_mode="equal"),
    )
    monkeypatch.setattr(
        reachability, "candidate_allocations",
        lambda _context: [np.array([0.0, 1.0]), np.array([1.0, 0.0])],
    )
    monkeypatch.setattr(
        reachability, "_build_screening_context",
        lambda _context: (context, 123, "screen-cube"),
    )
    monkeypatch.setattr(
        solver_module, "_simulate_context_wealth",
        lambda _context, w: np.full((200, 2), float(w[0])),
    )
    monkeypatch.setattr(
        solver_module, "_annualized_twr_bps_per_path",
        lambda _context, _w: np.zeros(200),
    )

    def success_only_at_diversified_interior(wealth, *_args, **_kwargs):
        succeeds = abs(float(wealth[0, 0]) - 0.5) < 1e-12
        return np.full(wealth.shape[0], succeeds, dtype=bool)

    monkeypatch.setattr(
        objective_module, "_goal_probability_core", success_only_at_diversified_interior)
    interior_wealth = solver_module._simulate_context_wealth(context, np.array([0.5, 0.5]))
    assert np.all(objective_module._goal_probability_core(interior_wealth, goal, 100))

    screen = reachability.goal_reachability_screen(context)
    assert screen["penalty_exempt_goal_ids"] == []
    row = screen["goals"][0]
    assert row["status"] == "not_found_reachable_in_screen_set"  # kein Beweis
    assert row["penalty_exempt"] is False


def test_codex_final_certification_holdout_must_not_select_the_objective():
    """Codex GOAL-SCREEN-HOLDOUT-LEAKAGE-001 (unveraendert) + Seed-Nachweis."""
    import inspect

    from services.optimizer.goal_reachability import (
        SCREENING_SEED_OFFSET,
        goal_reachability_screen,
    )

    source = inspect.getsource(goal_reachability_screen)
    assert "_build_validation_context(context)" not in source
    assert SCREENING_SEED_OFFSET != solver_module.VALIDATION_SEED_OFFSET


def test_unreachable_hard_goal_is_not_exempted_in_production():
    """Produktionspfad: ein auf der Pruefmenge unerreichbares hartes Ziel
    bleibt mit vollem Fehlbetrag in der Zielfunktion (v6: ``penalty_exempt``).
    Engine v11 (GOAL-REVISION-DECISION-001): ohne Berater-Entscheidung bleibt
    es auch Stufe 1 (bis v10 automatisch herabgestuft) -- die lokale Suche
    beweist keine Unerreichbarkeit; sie schlaegt die Einstufung nur vor."""
    context = _goal_context("Hart", amount=50_000_000_00)
    screen = context.goal_reachability
    assert screen["not_found_reachable_goal_ids"] == ["vz"]
    assert screen["penalty_exempt_goal_ids"] == []
    assert screen["revision_suggested_goal_ids"] == ["vz"]
    assert screen["demoted_goal_ids"] == []
    assert not hasattr(context, "penalty_exempt_goal_ids")
    assert [str(l.goal_id) for l in solver_module._stage1_liabilities(context)] == ["vz"]
    low = _w({"equities": 4500, "bonds": 4500, "real_estate": 500,
              "alternatives": 300, "liquidity": 200})
    high = _w({"equities": 7000, "bonds": 2000, "real_estate": 500,
               "alternatives": 300, "liquidity": 200})
    shortfall = {}
    for name, w in (("low", low), ("high", high)):
        _f, wealth, twr, scopes = solver_module._evaluation_inputs(context, w)
        shortfall[name] = objective_module.shortfall_objective(
            context.liabilities, wealth,
            initial_wealth_rappen=context.advisory_wealth_rappen,
            horizon_years=context.horizon_years, weights=context.scenario_weights,
            annualized_return_bps_per_path=twr, scope_wealth=scopes,
        )
    assert shortfall["low"] != shortfall["high"]  # das Ziel unterscheidet weiter


def _with_revision_decision(goal):
    """GOAL-REVISION-DECISION-001: gueltige Berater-Entscheidung am Ziel."""
    from test_goal_revision_decision import _decision_for

    goal.goal_revision_decision = _decision_for(goal)
    return goal


def _two_goal_context(seed: int = 11, *, decided: bool = False):
    far = _make_goal(goal_id="far", label="Aussichtslos", hardness="Hart",
                     goal_type="Vermoegensziel", target_rappen=50_000_000_00,
                     target_date_offset_days=365 * 25)
    goals = [
        _make_goal(goal_id="reach", label="Erreichbar", hardness="Primär",
                   goal_type="Vermoegensziel", target_rappen=700_000_00,
                   target_date_offset_days=365 * 25),
        _with_revision_decision(far) if decided else far,
    ]
    return solver_module.build_optimizer_context(seed=seed, **_inputs(goals, 25))


def test_unreachable_goal_is_demoted_and_cannot_displace_a_reachable_goal():
    """GOAL-HIERARCHY-002 (CIO-Review #650): das aussichtslose Ziel (auch
    wenn HART) ist -- seit Engine v11 NUR mit Berater-Entscheidung
    GoalRevisionDecisionV1 -- nicht Stufe 1; Stufe 1 schuetzt das erreichbare
    Ziel. Mit der Hausquote als Prior bleibt das Stufe-1-Niveau des
    erreichbaren Ziels innerhalb seiner Schranke, obwohl der Fehlbetrag des
    aussichtslosen Ziels die Zielfunktion dominiert."""
    from dataclasses import replace

    context = replace(_two_goal_context(decided=True), house_prior_weights=_w(HOUSE_ANCHOR))
    assert context.goal_reachability["not_found_reachable_goal_ids"] == ["far"]
    assert [str(l.goal_id) for l in solver_module._stage1_liabilities(context)] == ["reach"]
    selection = solver_module._select_cube_candidate(context, max_iter=50, ftol=1e-6)
    audit = selection.goal_protection
    assert audit["protected_goal_ids"] == ["reach"]
    assert audit["demoted_goal_ids"] == ["far"]
    level_final = solver_module._protected_level_from_inputs(
        context, solver_module._evaluation_inputs(context, selection.weights))[0]
    assert level_final <= audit["bound"] * (1.0 + 1e-6)


def test_demoted_goal_reasoning_says_subordinate_not_excluded():
    """Engine v11: ohne Decision ein VORSCHLAG (keine Unmoeglichkeits-/
    Garantieaussage), mit Decision der Hinweis auf den Beraterentscheid."""
    from services.optimizer.goal_reachability import reachability_reasoning

    lines = reachability_reasoning(_two_goal_context().goal_reachability)
    assert len(lines) == 1 and "'Aussichtslos'" in lines[0]
    assert "nicht mit ausreichender Sicherheit erreicht" in lines[0]
    assert "als nachrangiges Wunschziel einstufen" in lines[0]
    assert "unerreichbar" not in lines[0].lower()
    decided = reachability_reasoning(_two_goal_context(decided=True).goal_reachability)
    assert len(decided) == 1 and "'Aussichtslos'" in decided[0]
    assert "als nachrangiges Wunschziel eingestuft" in decided[0]
    assert "verdraengt keine erreichbaren Ziele" in decided[0]


# ---------------------------------------------------------------------------
# 7. DEMOTED-GOAL-WEIGHT-001 (CIO-Entscheid 2026-10-19)
# ---------------------------------------------------------------------------


def test_demoted_goal_counts_like_a_wish_goal_with_volume_capped_at_w0():
    """Herabgestuft: Gewicht 0.2 (unabhaengig vom Haertegrad) und Volumen
    auf W0 gedeckelt -- auf Fehlbetrag UND Chance-Strafe; CHF 0 bleibt
    schlechter als CHF 900 (Codex)."""
    from dataclasses import replace

    big = _liability("wealth_at_t", target=int(10e8), hardness="hart", horizon=1)
    demoted = replace(big, demoted=True)
    worse = np.column_stack([np.full(400, 1e8), np.full(400, 0.0)])
    better = np.column_stack([np.full(400, 1e8), np.full(400, 9e8)])
    kwargs = dict(initial_wealth_rappen=1e8, horizon_years=1)
    full = objective_module.shortfall_objective([big], worse, **kwargs)
    reduced = objective_module.shortfall_objective([demoted], worse, **kwargs)
    # h: 10 -> 0.2, Volumen (Z/W0 = 10) auf 1 gedeckelt: Faktor 0.02 / 100.
    assert reduced == pytest.approx(full * (0.2 / 10.0) / 100.0, rel=1e-12)
    assert objective_module.shortfall_objective([demoted], better, **kwargs) < reduced
    chance_full, _ = objective_module.chance_constraint_penalty(worse, [big], int(1e8))
    chance_reduced, _ = objective_module.chance_constraint_penalty(worse, [demoted], int(1e8))
    assert chance_reduced == pytest.approx(chance_full * 0.2 / 100.0, rel=1e-12)
    assert not objective_module.is_protected_goal(demoted, n_wealth_columns=2)


def test_unreachable_goal_alone_stays_near_the_house_quota():
    """CIO: ein vom Berater als nachrangig eingestuftes, aussichtsloses Ziel
    darf die Allokation nicht an die Bandobergrenze treiben (erste Fassung:
    7000/2000/800/0/200). Engine v11: die Herabstufung kommt aus der
    GoalRevisionDecisionV1, nicht mehr automatisch aus der Suche."""
    result, context = _run([_with_revision_decision(_wealth_goal(5_000_000_00, "Hart"))],
                           25, seed=11, key="unreachable_alone")
    assert all(l.demoted for l in context.liabilities)
    assert result.resampling["house_prior"]["tracking_error_vs_house_bps"] <= 25.0
    assert result.weights_bps["equities"] <= 6100


def test_unreachable_goal_without_decision_stays_stage1_and_is_disclosed():
    """Engine v11 (GOAL-REVISION-DECISION-001, CIO-Entscheid 2026-10-21):
    OHNE Berater-Entscheidung bleibt das harte CHF-5-Mio-Ziel Stufe 1 --
    bewusst, denn die lokale Suche kann "aussichtslos" nicht von einer
    verfehlten Erfolgsinsel unterscheiden. Der Optimierer verfolgt das Ziel
    dann innerhalb der Bandbreiten maximal (gemessen 7000/2000/800/0/200,
    TE 170 bps zur Hausquote; mit Decision 6014/2958/534/294/200, TE 4 bps,
    identisch zu v10). Das Reasoning schlaegt die Einstufung vor."""
    result, context = _run([_wealth_goal(5_000_000_00, "Hart")], 25, seed=11,
                           key="unreachable_alone_no_decision")
    assert not any(l.demoted for l in context.liabilities)
    assert [str(l.goal_id) for l in solver_module._stage1_liabilities(context)] == ["vz"]
    assert context.goal_reachability["revision_suggested_goal_ids"] == ["vz"]
    assert result.status == "converged"
    assert result.weights_bps["equities"] <= 7000  # Bandobergrenze Wachstum
    assert any("als nachrangiges Wunschziel einstufen" in line for line in result.reasoning)
