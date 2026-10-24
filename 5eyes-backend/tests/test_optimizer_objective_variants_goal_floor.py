"""OPTIMIZER-OBJECTIVE-VARIANTS-001 -- die Ziel-Untergrenze gilt in jeder Variante.

Dies ist die Eignungs-Eigenschaft der ganzen Variantenfaehigkeit, und sie ist
der Grund, warum hier kein freies Menue von Zielfunktionen gebaut wurde.

Ein Berater, der "minimiere den maximalen Drawdown" oder "maximiere die
Rendite" waehlt, darf keine Allokation bekommen, die die Ziele des Mandats
aufgibt. Die Zielfunktion ist deshalb immer

    primaerterm(modus) + chance_penalty(ziele)

und die Chance-Penalty ist so gewichtet, dass ein MATERIELLES Zieldefizit
mehr kostet als der ganze Wertebereich jedes Primaerterms. Eine Variante
verschiebt also, welche Allokation unter den ziel-zulaessigen die beste ist,
nicht ob die Ziele ueberhaupt zaehlen.

OBJECTIVE-NORMALIZATION-001 (2026-10-18): bis dahin stand hier
``LAMBDA_CHANCE_DEFAULT = 1e6`` auf das Defizit-QUADRAT -- "um
Groessenordnungen dominanter als jeder Primaerterm". Das war zu viel: auch
ein statistisch bedeutungsloses Defizit von wenigen Pfaden ueberstimmte den
ganzen Primaerterm (Fundament-Mandat: Strafe 1.1e6 gegen Drawdown 0.26; die
Varianten Drawdown/Volatilitaet lieferten MEHR Aktien als der Default).
Jetzt: Defizit linear mal (Zielvolumen / W0)^2, in der Einheit des
Primaerterms (siehe tests/test_objective_normalization.py).

Zusaetzlich geprueft: der Default-Modus rechnet bit-identisch wie vor der
Variantenfaehigkeit.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import numpy as np
import pytest

from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.objective import (
    LAMBDA_CHANCE_DEFAULT,
    RISK_TERM_VARIANCE_WEIGHT,
    chance_constraint_penalty,
    combined_objective_two_phase,
    shortfall_objective,
    volatility_objective,
)
from services.optimizer.objective_variants import (
    OBJECTIVE_CVAR_RETURN,
    OBJECTIVE_GOAL_SHORTFALL,
    OBJECTIVE_MAX_DRAWDOWN,
    OBJECTIVE_MAX_RETURN,
    OBJECTIVE_MIN_VOLATILITY,
)

VARIANTS = [
    OBJECTIVE_CVAR_RETURN,
    OBJECTIVE_MAX_DRAWDOWN,
    OBJECTIVE_MIN_VOLATILITY,
    OBJECTIVE_MAX_RETURN,
]

INITIAL_WEALTH = 100_000_00
HORIZON = 10
N_PATHS = 200


def _hard_goal() -> GoalLiability:
    """Bindendes Ziel mit tau = 0.80."""
    return GoalLiability(
        goal_id="g1",
        label="Vermoegensziel",
        goal_type="Vermoegensziel",
        target_kind="wealth_at_t",
        target_amount_rappen=200_000_00,
        target_year_index=5,
        liability_path_rappen=[0] * (HORIZON + 1),
        hardness_key="hart",
        weight_bps=10000,
        success_probability_min_x100=8000,
    )


def _wealth_paths(*, success_fraction: float) -> np.ndarray:
    """Vermoegenspfade, bei denen ein Anteil der Pfade das Ziel erreicht."""
    paths = np.full((N_PATHS, HORIZON + 1), float(INITIAL_WEALTH))
    n_success = int(round(success_fraction * N_PATHS))
    paths[:n_success, 5] = 300_000_00
    paths[n_success:, 5] = 50_000_00
    return paths


def _factors(*, mean: float, vol: float, seed: int = 5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 1.0 + rng.normal(mean, vol, size=(N_PATHS, HORIZON))


# ── Die Ziel-Untergrenze ─────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", VARIANTS)
def test_material_goal_deficit_outweighs_every_variant(mode: str) -> None:
    """Ein materiell verfehltes Ziel kostet in JEDER Variante mehr als der
    ganze Wertebereich ihres Primaerterms.

    Ohne diese Eigenschaft waere "maximiere die Rendite" eine Lizenz, die
    Ziele des Mandats zu ignorieren. (Hiess bis OBJECTIVE-NORMALIZATION-001
    ``test_unreachable_goal_dominates_every_variant`` und verlangte eine
    Strafe > 1000 -- die Groessenordnung der alten 1e6-Skala.)
    """
    goal = _hard_goal()
    missed = _wealth_paths(success_fraction=0.10)  # weit unter tau = 0.80
    reached = _wealth_paths(success_fraction=1.0)
    factors = _factors(mean=0.05, vol=0.10)

    def value(paths):
        return combined_objective_two_phase(
            [goal],
            paths,
            initial_wealth_rappen=INITIAL_WEALTH,
            horizon_years=HORIZON,
            objective_mode=mode,
            portfolio_return_factors=factors,
        )

    # Jeder Primaerterm liegt in (-1, 1), sein ganzer Wertebereich also
    # unter 2; die Differenz stammt allein aus der Chance-Penalty.
    assert value(missed) - value(reached) > 2.0, (
        f"{mode}: Zielverfehlung kostet nur {value(missed) - value(reached):.4f} "
        "-- die Ziel-Untergrenze wirkt in dieser Variante nicht"
    )


@pytest.mark.parametrize("mode", VARIANTS)
def test_variant_decides_only_among_goal_compliant_allocations(mode: str) -> None:
    """Sind die Ziele erfuellt, entscheidet allein der Primaerterm.

    Gegenstueck zum Test oben: die Penalty darf nicht dauerhaft dominieren,
    sonst waere die Variante wirkungslos. Bei erfuellten Zielen ist die
    Penalty 0 und zwei Portfolios unterscheiden sich genau um ihren
    Primaerterm.
    """
    goal = _hard_goal()
    reached = _wealth_paths(success_fraction=1.0)

    calm = combined_objective_two_phase(
        [goal],
        reached,
        initial_wealth_rappen=INITIAL_WEALTH,
        horizon_years=HORIZON,
        objective_mode=mode,
        portfolio_return_factors=_factors(mean=0.05, vol=0.04, seed=11),
    )
    rough = combined_objective_two_phase(
        [goal],
        reached,
        initial_wealth_rappen=INITIAL_WEALTH,
        horizon_years=HORIZON,
        objective_mode=mode,
        portfolio_return_factors=_factors(mean=0.05, vol=0.20, seed=11),
    )
    assert calm != pytest.approx(rough), (
        f"{mode}: Primaerterm hat keinen Einfluss, obwohl die Ziele erfuellt sind"
    )
    assert abs(calm) < 1.0 and abs(rough) < 1.0, (
        f"{mode}: bei erfuellten Zielen darf keine Strafe uebrig bleiben "
        f"(calm={calm}, rough={rough})"
    )
    if mode != OBJECTIVE_MAX_RETURN:
        # Bei gleicher Durchschnittsrendite muss jedes Risikomass das ruhige
        # Portfolio vorziehen; die Rendite-Variante ist hier bewusst indifferent.
        assert calm < rough


@pytest.mark.parametrize("mode", VARIANTS)
def test_penalty_component_is_identical_across_variants(mode: str) -> None:
    """Die Chance-Penalty haengt nicht am gewaehlten Primaerterm.

    Sie wird aus den Vermoegenspfaden und den Zielen berechnet, also muss sie
    fuer identische Pfade in jeder Variante dieselbe sein -- sonst waere die
    Ziel-Untergrenze modusabhaengig weich.
    """
    goal = _hard_goal()
    missed = _wealth_paths(success_fraction=0.40)
    penalty, _achievability = chance_constraint_penalty(
        missed, [goal], INITIAL_WEALTH, lambda_chance=LAMBDA_CHANCE_DEFAULT
    )
    factors = _factors(mean=0.05, vol=0.10)
    total = combined_objective_two_phase(
        [goal],
        missed,
        initial_wealth_rappen=INITIAL_WEALTH,
        horizon_years=HORIZON,
        objective_mode=mode,
        portfolio_return_factors=factors,
    )
    # total = primaerterm + penalty, und |primaerterm| < 1
    assert abs(total - penalty) < 1.0, (
        f"{mode}: total={total}, erwartete Penalty={penalty} -- die Differenz "
        "ist groesser als ein Primaerterm sein kann"
    )


# ── Der Default bleibt bit-identisch ────────────────────────────────────────


def test_default_mode_is_bit_identical_to_the_explicit_composition() -> None:
    """``goal_shortfall`` == L(w) + Chance-Penalty + normierter Vol-Tiebreak.

    Der Default-Pfad darf sich durch die Variantenfaehigkeit um kein Bit
    veraendert haben, sonst verschiebt sich jede bestehende Zahl und jeder
    Golden-Snapshot.
    """
    goal = _hard_goal()
    for fraction in (0.0, 0.25, 0.85, 1.0):
        paths = _wealth_paths(success_fraction=fraction)
        expected_primary = shortfall_objective(
            [goal],
            paths,
            initial_wealth_rappen=INITIAL_WEALTH,
            horizon_years=HORIZON,
        )
        expected_penalty, _ = chance_constraint_penalty(
            paths, [goal], INITIAL_WEALTH, lambda_chance=LAMBDA_CHANCE_DEFAULT
        )
        # OBJECTIVE-NORMALIZATION-001: Tiebreak immer aktiv, normiert auf W0^2.
        expected_vol = volatility_objective(paths) / float(INITIAL_WEALTH) ** 2
        expected = (
            expected_primary + expected_penalty
            + RISK_TERM_VARIANCE_WEIGHT * expected_vol
        )

        actual = combined_objective_two_phase(
            [goal],
            paths,
            initial_wealth_rappen=INITIAL_WEALTH,
            horizon_years=HORIZON,
            objective_mode=OBJECTIVE_GOAL_SHORTFALL,
        )
        assert actual == expected, f"Anteil {fraction}: {actual} != {expected}"


def test_default_mode_needs_no_return_factors_in_the_combined_objective() -> None:
    """Der Default-Aufruf darf ohne das neue Argument auskommen."""
    goal = _hard_goal()
    paths = _wealth_paths(success_fraction=0.9)
    value = combined_objective_two_phase(
        [goal],
        paths,
        initial_wealth_rappen=INITIAL_WEALTH,
        horizon_years=HORIZON,
        objective_mode=OBJECTIVE_GOAL_SHORTFALL,
    )
    assert np.isfinite(value)


def test_variant_without_factors_raises_in_the_combined_objective() -> None:
    """Und eine Variante ohne Faktoren bricht ab, statt still zurueckzufallen."""
    from services.optimizer.objective_variants import ObjectiveModeError

    goal = _hard_goal()
    paths = _wealth_paths(success_fraction=0.9)
    with pytest.raises(ObjectiveModeError):
        combined_objective_two_phase(
            [goal],
            paths,
            initial_wealth_rappen=INITIAL_WEALTH,
            horizon_years=HORIZON,
            objective_mode=OBJECTIVE_MAX_DRAWDOWN,
        )


def test_mode_comes_from_the_environment_when_not_passed(monkeypatch) -> None:
    """Ohne explizites Argument entscheidet die zentral validierte Umgebung.

    So sieht der Solver-Pfad denselben Modus wie jede andere Aufrufstelle,
    ohne ihn durchreichen zu muessen.
    """
    goal = _hard_goal()
    paths = _wealth_paths(success_fraction=1.0)
    factors = _factors(mean=0.05, vol=0.10)

    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", "min_volatility")
    from_env = combined_objective_two_phase(
        [goal],
        paths,
        initial_wealth_rappen=INITIAL_WEALTH,
        horizon_years=HORIZON,
        portfolio_return_factors=factors,
    )
    explicit = combined_objective_two_phase(
        [goal],
        paths,
        initial_wealth_rappen=INITIAL_WEALTH,
        horizon_years=HORIZON,
        objective_mode=OBJECTIVE_MIN_VOLATILITY,
        portfolio_return_factors=factors,
    )
    assert from_env == explicit

    monkeypatch.delenv("OPTIMIZER_OBJECTIVE", raising=False)
    default = combined_objective_two_phase(
        [goal],
        paths,
        initial_wealth_rappen=INITIAL_WEALTH,
        horizon_years=HORIZON,
        portfolio_return_factors=factors,
    )
    assert default != pytest.approx(explicit)
