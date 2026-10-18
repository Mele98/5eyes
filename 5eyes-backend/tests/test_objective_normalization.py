"""OBJECTIVE-NORMALIZATION-001 (2026-10-18): stetige, Pareto-monotone
Zielfunktion und volumen-normierte Chance-Constraint-Strafe.

Befund A (Skala): ``LAMBDA_CHANCE_DEFAULT = 1e6`` auf das Quadrat des
Wahrscheinlichkeitsdefizits. Gemessen auf dem Fundament-Mandat: Strafe
1.1e6 gegen Drawdown-Term 0.26 bzw. Volatilitaetsterm 0.11 -- die Varianten
``max_drawdown``/``min_volatility`` lieferten 67.9 % / 70.3 % Aktien, MEHR
als der Default (67.3 %), weil allein die Strafe entschied.

Befund B (Stufen-Schalter): der Volatilitaets-Tiebreak wurde pro Allokation
erst zugeschaltet, wenn deren Ziel-Stufe < 1e-12 war. In den Bags der
CH-Golden-Mandate (Score 5, drei Praeferenz-Varianten) gewann in 44 von 49
Bags, in denen der Solver ueberhaupt einen Punkt mit Ziel-Stufe 0
ausgewertet hatte, trotzdem eine Allokation mit Restfehlbetrag (~1e-9) --
weil die Ziel-erfuellende Allokation ihren Volatilitaetsterm (~1.5e3)
"bezahlen" musste. Messung: docs/planning/2026-10-18-objective-normalization.md.

TIEBREAK-PORTFOLIO-VARIANCE-001 (2026-10-18): der Tiebreak ist jetzt
``kappa * w' Sigma w`` (einjaehrige Portfolio-Varianz aus der CMA-Kovarianz,
vom Aufrufer mit der Allokation uebergeben) statt ``Var(W_T)/W0^2``. Die
Monotonie- und Stetigkeitseigenschaften gelten unveraendert; die Tests
uebergeben die Portfolio-Varianz explizit.
"""
from __future__ import annotations

import numpy as np
import pytest

from services.optimizer.certification import wilson_lower_bound
from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.objective import (
    CHANCE_PENALTY_WEIGHT,
    TIEBREAK_VARIANCE_WEIGHT,
    chance_constraint_penalty,
    combined_objective_two_phase,
    goal_volume_rappen,
    portfolio_variance_one_year,
    two_phase_objective_parts,
)


def _goal(
    *,
    goal_id: str = "g",
    target_kind: str = "wealth_at_t",
    target_amount_rappen: int = 100,
    target_year_index: int = 1,
    liability_path_rappen: list[int] | None = None,
    hardness_key: str = "hart",
    tau_x100: int = 8_000,
) -> GoalLiability:
    return GoalLiability(
        goal_id=goal_id,
        label=goal_id,
        goal_type="test",
        target_kind=target_kind,
        target_amount_rappen=target_amount_rappen,
        target_year_index=target_year_index,
        liability_path_rappen=list(liability_path_rappen or []),
        hardness_key=hardness_key,
        weight_bps=10_000,
        success_probability_min_x100=tau_x100,
    )


def _objective(goals, paths, *, w0: float = 100.0, **kwargs) -> float:
    return combined_objective_two_phase(
        goals, paths, initial_wealth_rappen=w0, horizon_years=paths.shape[1] - 1,
        objective_mode="goal_shortfall", goal_weighting_mode="equal", **kwargs,
    )


# ---------------------------------------------------------------------------
# B: Stufen-Schalter
# ---------------------------------------------------------------------------


# Realistische Rappen-Skala (CHF 500'000 wie die CH-Golden-Mandate): der
# alte Defekt hing an der Einheit -- der Tiebreak war 1e-12 * Var in Rappen^2.
W0 = 50_000_000.0


# Einjaehrige Portfolio-Varianzen (Dezimal^2) der beiden Allokationen des
# nachgebauten Falls: ``meets`` schwankt weniger (Vola 9.0 % gegen 9.5 %).
VAR_MEETS = 0.090 ** 2
VAR_MISSES = 0.095 ** 2


def _golden_like_pair(n_paths: int = 2000, seed: int = 3):
    """Nachbau des gemessenen Falls (CH-Golden Score 7, Validierungs-Cube).

    ``meets``: erfuellt das Ziel (= W0) auf jedem Pfad, schwankt weniger
    (``VAR_MEETS``). ``misses``: CHF 100 Fehlbetrag auf genau EINEM von
    2'000 Pfaden, schwankt mehr (``VAR_MISSES``). ``meets`` ist auf beiden
    Stufen besser.
    """
    rng = np.random.default_rng(seed)
    terminal = W0 * (2.0 + rng.normal(0.0, 0.3, size=n_paths))
    terminal = np.maximum(terminal, 1.4 * W0)
    meets = np.column_stack([np.full(n_paths, W0), terminal])
    misses = np.column_stack([np.full(n_paths, W0), 2.0 * W0 + 1.5 * (terminal - 2.0 * W0)])
    misses[0, 1] = W0 - 10_000.0  # CHF 100 unter dem Ziel, ein Pfad
    goal = _goal(target_amount_rappen=int(W0), hardness_key="opportunistisch")
    return goal, meets, misses


def test_reproducer_tiny_one_path_shortfall_no_longer_beats_full_goal_attainment():
    """Rot vor dem Fix: f(misses) = 2e-11 (nur Ziel-Stufe, Tiebreak nicht
    zugeschaltet) < f(meets) = 1e-12 * Var = ~2e2.

    Der Stufen-Schalter schaltete den Tiebreak nur fuer ``meets`` zu; jede
    Allokation, die ein Ziel auf einem Pfad um ein paar Franken verfehlte,
    war damit "besser" als eine, die alle Ziele erfuellt UND weniger
    schwankt -- der Solver hatte einen Anreiz, Ziele knapp zu verfehlen.
    """
    goal, meets, misses = _golden_like_pair()
    assert np.all(meets[:, 1] >= W0) and int(np.sum(misses[:, 1] < W0)) == 1
    assert (
        _objective([goal], meets, w0=W0, portfolio_variance=VAR_MEETS)
        < _objective([goal], misses, w0=W0, portfolio_variance=VAR_MISSES)
    )


def test_tiebreak_is_always_active_not_switched_by_goal_level():
    goal, meets, misses = _golden_like_pair()
    for paths, variance in ((meets, VAR_MEETS), (misses, VAR_MISSES)):
        goal_level, tiebreak = two_phase_objective_parts(
            [goal], paths, initial_wealth_rappen=W0, horizon_years=1,
            objective_mode="goal_shortfall", goal_weighting_mode="equal",
            portfolio_variance=variance,
        )
        assert tiebreak == pytest.approx(TIEBREAK_VARIANCE_WEIGHT * variance)
        assert tiebreak > 0.0
        assert _objective(
            [goal], paths, w0=W0, portfolio_variance=variance
        ) == pytest.approx(goal_level + tiebreak)


def test_tiebreak_is_the_one_year_portfolio_variance_and_mean_independent():
    """TIEBREAK-PORTFOLIO-VARIANCE-001: ``w' Sigma w`` haengt weder von den
    erwarteten Renditen ab (das alte ``Var(W_T)`` wuchs ueber 31 Jahre mit
    dem Mittelwert und bevorzugte rendite-schwaechere Mischungen) noch von
    den Szenariopfaden."""
    sigma_bps = np.array([1600.0, 450.0, 1200.0, 1500.0, 50.0])
    corr = np.full((5, 5), 0.2) + 0.8 * np.eye(5)
    cov_bps2 = corr * np.outer(sigma_bps, sigma_bps)
    w = np.array([0.4, 0.45, 0.05, 0.07, 0.03])
    expected = float(w @ (cov_bps2 / 1e8) @ w)
    assert portfolio_variance_one_year(w, cov_bps2) == pytest.approx(expected)
    goal, meets, _ = _golden_like_pair()
    shifted = meets * 1.7  # anderer Mittelwert, andere Endvermoegens-Streuung
    tiebreaks = [
        two_phase_objective_parts(
            [goal], paths, initial_wealth_rappen=W0, horizon_years=1,
            objective_mode="goal_shortfall", goal_weighting_mode="equal",
            portfolio_variance=expected,
        )[1]
        for paths in (meets, shifted)
    ]
    assert tiebreaks[0] == tiebreaks[1] == pytest.approx(TIEBREAK_VARIANCE_WEIGHT * expected)


def test_objective_is_pareto_monotone_property():
    """Property: ist eine Allokation auf jedem Pfad mindestens so nah am Ziel
    und hat sie hoechstens dieselbe Portfolio-Varianz, darf ihr Wert
    nicht groesser sein -- fuer beliebige Skalen, Haertegrade, Schwellen.

    Konstruktion: ``better`` erfuellt das Ziel auf jedem Pfad; ``worse`` ist
    ``better`` mit gestreckter Streuung und (in der Haelfte der Faelle) einem
    einzelnen Pfad knapp unter dem Ziel -- genau das Regime, in dem der alte
    Stufen-Schalter versagte (Ziel-Stufe von ``worse`` winzig, aber > 1e-12).
    """
    rng = np.random.default_rng(20261018)
    failures = []
    for trial in range(400):
        n_paths = int(rng.integers(50, 2000))
        w0 = float(10 ** rng.uniform(6, 9))
        target = w0 * float(rng.uniform(0.3, 1.2))
        spread = w0 * float(rng.uniform(0.05, 0.6))
        terminal = target + spread + np.abs(rng.normal(0.0, spread, size=n_paths))
        better = np.column_stack([np.full(n_paths, w0), terminal])
        mean = float(np.mean(terminal))
        stretched = mean + float(rng.uniform(1.0, 2.0)) * (terminal - mean)
        stretched = np.maximum(stretched, target)
        if trial % 2:
            stretched[int(rng.integers(n_paths))] = target - w0 * float(10 ** rng.uniform(-7, -2))
        worse = np.column_stack([np.full(n_paths, w0), stretched])
        hardness = ["hart", "primaer", "opportunistisch"][trial % 3]
        goal = _goal(target_amount_rappen=int(np.floor(target)), hardness_key=hardness,
                     tau_x100=int(rng.integers(5_000, 9_900)))
        variance = float(rng.uniform(0.02, 0.2)) ** 2
        f_better = _objective([goal], better, w0=w0, portfolio_variance=variance)
        f_worse = _objective(
            [goal], worse, w0=w0,
            portfolio_variance=variance * float(rng.uniform(1.0, 2.0)),
        )
        if not f_better <= f_worse:
            failures.append((trial, f_better, f_worse))
    assert not failures, (len(failures), failures[:5])


def test_objective_is_continuous_at_goal_attainment():
    """Kein Sprung beim Uebergang "Ziel um CHF 1 verfehlt" -> "Ziel erreicht".

    Vorher sprang der Wert um den ganzen Volatilitaetsterm (hier ~2e2,
    gemessen in den Golden-Bags ~1.5e3), sobald der letzte Fehlbetrag
    verschwand.
    """
    goal, meets, _ = _golden_like_pair()
    at_target = meets.copy()
    at_target[0, 1] = W0
    just_below = at_target.copy()
    just_below[0, 1] = W0 - 100.0
    jump = abs(
        _objective([goal], just_below, w0=W0, portfolio_variance=VAR_MEETS)
        - _objective([goal], at_target, w0=W0, portfolio_variance=VAR_MEETS)
    )
    assert jump < 1e-9


# ---------------------------------------------------------------------------
# A: Skala der Chance-Constraint-Strafe
# ---------------------------------------------------------------------------


def test_chance_penalty_is_linear_deficit_times_relative_goal_volume():
    goal = _goal(target_amount_rappen=150)
    paths = np.array([[100.0, 150.0], [100.0, 100.0]])  # p_hat = 0.5
    penalty, rows = chance_constraint_penalty(paths, [goal], 100)
    deficit = 0.8 - wilson_lower_bound(0.5, 2)
    assert rows[0]["lower_confidence_bound"] == pytest.approx(wilson_lower_bound(0.5, 2))
    assert penalty == pytest.approx(CHANCE_PENALTY_WEIGHT * deficit * (150.0 / 100.0) ** 2)


def test_chance_penalty_is_currency_and_wealth_scale_invariant():
    """Gleiche wirtschaftliche Lage in anderer Einheit/Groesse -> gleiche Strafe."""
    goal_small = _goal(target_amount_rappen=150)
    goal_large = _goal(target_amount_rappen=150 * 10**7)
    paths = np.array([[100.0, 150.0], [100.0, 120.0], [100.0, 200.0]])
    small, _ = chance_constraint_penalty(paths, [goal_small], 100)
    large, _ = chance_constraint_penalty(paths * 10**7, [goal_large], 100 * 10**7)
    assert small > 0.0
    assert large == pytest.approx(small)


def test_chance_penalty_is_bounded_by_relative_goal_volume():
    """Auch ein unerreichbares Ziel kostet hoechstens ``tau * (Z/W0)^2`` --
    vorher 1e6 * tau^2 = 6.4e5, um 5-7 Groessenordnungen ueber jedem
    Primaerterm."""
    goal = _goal(target_amount_rappen=80)
    never = np.column_stack([np.full(500, 100.0), np.full(500, 10.0)])
    penalty, rows = chance_constraint_penalty(never, [goal], 100)
    assert rows[0]["probability"] == 0.0
    assert penalty == pytest.approx(0.8 * (80.0 / 100.0) ** 2)
    assert penalty <= 1.0


@pytest.mark.parametrize("target_kind,expected", [
    ("wealth_at_t", 300.0),
    ("cashflow_in_year", 40.0),
    ("outflow_stream", 40.0),
])
def test_goal_volume_matches_the_amount_that_a_full_miss_loses(target_kind, expected):
    goal = _goal(
        target_kind=target_kind,
        target_amount_rappen=300,
        liability_path_rappen=[0, 10, 30, 99],  # 99 liegt jenseits des Horizonts
    )
    assert goal_volume_rappen(goal, initial_value_rappen=100, n_wealth_columns=4) == expected


def test_return_goal_volume_is_the_implied_target_wealth():
    goal = _goal(target_kind="return_rate", target_amount_rappen=1_000, target_year_index=2)
    assert goal_volume_rappen(goal, initial_value_rappen=100, n_wealth_columns=3) == pytest.approx(121.0)


def _variant_pair(*, calm_successes: int, wild_successes: int, n_paths: int = 2000):
    """Zwei Allokationen fuer eine Risikomass-Variante: ``calm`` schwankt
    kaum, ``wild`` stark; das Ziel (Z = W0) trifft jede auf genau der
    angegebenen Pfadzahl. Ziel- und Risikoseite sind bewusst entkoppelt
    konstruiert, damit nur das Verhaeltnis der Terme geprueft wird."""
    rng = np.random.default_rng(7)
    years = 10
    calm = np.exp(rng.normal(0.01, 0.02, size=(n_paths, years)))
    wild = np.exp(rng.normal(0.01, 0.20, size=(n_paths, years)))

    def wealth(successes):
        end = np.where(np.arange(n_paths) < successes, 101.0, 99.0)
        return np.column_stack([np.full(n_paths, 100.0)] + [end] * years)

    goal = _goal(target_amount_rappen=100, target_year_index=years)

    def evaluate(paths, factors, mode="min_volatility"):
        return combined_objective_two_phase(
            [goal], paths, initial_wealth_rappen=100.0, horizon_years=years,
            objective_mode=mode, goal_weighting_mode="equal",
            portfolio_return_factors=factors,
        )

    return (
        evaluate(wealth(calm_successes), calm),
        evaluate(wealth(wild_successes), wild),
    )


def test_insignificant_probability_edge_does_not_override_the_variant():
    """Befund A: drei zusaetzliche Erfolgspfade von 2'000 (0.15 pp, weit
    unter dem Monte-Carlo-Standardfehler von ~1.1 pp) durften vorher den
    ganzen Risikomass-Unterschied ueberstimmen: 1e6 * (Defizit^2) aenderte
    sich um ~960, der Volatilitaetsunterschied der Variante betraegt ~0.18.
    Die Variante "min_volatility" waehlte die UNRUHIGERE Allokation."""
    calm, wild = _variant_pair(calm_successes=1000, wild_successes=1003)
    assert calm < wild


def test_material_goal_deficit_still_beats_the_variant():
    """Gegenprobe "die Chance-Constraint wirkt": erfuellt nur die unruhige
    Allokation das Ziel mit 95 % statt 50 % (tau = 80 %), muss sie
    gewinnen -- die Ziel-Untergrenze gilt in jeder Variante."""
    calm, wild = _variant_pair(calm_successes=1000, wild_successes=1900)
    assert wild < calm


# ---------------------------------------------------------------------------
# Signifikanztest (#619) und Drawdown-Rerank (#625): dieselbe Zielfunktion
# ---------------------------------------------------------------------------


def test_house_matrix_significance_compares_the_goal_level_not_the_tiebreak():
    """HOUSE-FIRST-SIGNIFICANCE-001 (CIO-Entscheid 2026-10-18): der gepaarte
    Test gegen die Hausmatrix vergleicht die ZIELEBENE der Bag-Zielfunktion
    (Ziel-Fehlbetrag + Chance-Strafe, + Soft-Preference) auf dem
    Validierungs-Cube -- ohne den Volatilitaets-Tiebreak. Der Tiebreak ist
    deterministisch; mit ihm war jede noch so kleine Varianzdifferenz
    "signifikant" (p = 1/(B+1)). Im Solver bleibt er (Stetigkeit), er
    entscheidet nur nicht mehr ueber Anker vs. Kandidat."""
    import sys
    from pathlib import Path

    tests_root = Path(__file__).resolve().parent
    if str(tests_root) not in sys.path:
        sys.path.insert(0, str(tests_root))
    from test_optimizer_context import _cma, _house_matrix, _pension_goal

    from services.optimizer import solver as solver_module
    from services.optimizer.scenario_engine import BUCKET_ORDER

    result = solver_module.run_solver(
        cma=_cma(), goals=[_pension_goal()], house_matrix_row=_house_matrix(),
        score_x10=70, advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[20_000_00] * 10, horizon_years=10,
        n_paths=400, seed=20261018,
    )
    significance = result.resampling["significance"]
    if significance.get("reason") == "identical_to_house_anchor":
        pytest.skip("Kandidat = Anker; kein Test gelaufen.")
    assert significance["test"] == "paired_bootstrap_one_sided_goal_level_v4"
    assert significance["comparison"] == "goal_level"
    assert significance["decision_level"] in {"goal_level"}
    # Default-Modus: keine Risikomass-Ebene im Entscheid.
    assert "risk_measure_test" not in significance

    validation_context, _seed, _hash = solver_module._build_validation_context(result.context)

    def levels(bps):
        w = np.array([bps[b] / 10000.0 for b in BUCKET_ORDER])
        factors = solver_module._portfolio_return_factors(validation_context, w)
        return two_phase_objective_parts(
            validation_context.liabilities,
            solver_module._simulate_context_wealth(validation_context, w),
            initial_wealth_rappen=validation_context.advisory_wealth_rappen,
            horizon_years=validation_context.horizon_years,
            weights=None,
            annualized_return_bps_per_path=solver_module._annualized_twr_bps_per_path(
                validation_context, w, portfolio_factors=factors,
            ),
            objective_mode="goal_shortfall",
            goal_weighting_mode=result.context.objective_contract.goal_weighting_mode,
            portfolio_return_factors=factors,
            portfolio_variance=portfolio_variance_one_year(
                w, validation_context.scenario_cov_bps2
            ),
            penalty_exempt_goal_ids=validation_context.penalty_exempt_goal_ids,
        )

    anchor_goal, anchor_tiebreak = levels(significance["house_anchor_projected_bps"])
    candidate_goal, candidate_tiebreak = levels(significance["candidate_bps"])
    assert significance["anchor_objective"] == pytest.approx(anchor_goal, rel=1e-12, abs=1e-15)
    assert significance["candidate_objective"] == pytest.approx(candidate_goal, rel=1e-12, abs=1e-15)
    assert significance["improvement"] == pytest.approx(
        significance["anchor_objective"] - significance["candidate_objective"],
        rel=1e-12, abs=1e-15,
    )
    # Der Tiebreak existiert weiterhin (Solver), steckt aber nicht im Vergleich.
    assert anchor_tiebreak > 0.0 and candidate_tiebreak > 0.0
