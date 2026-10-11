"""OPTIMIZER-OBJECTIVE-VARIANTS-001 -- die Variante wirkt im echten Solver.

Die Modul-Suiten pruefen die Primaerterme isoliert und die Ziel-Untergrenze an
der kombinierten Zielfunktion. Beides kann korrekt sein und das Feature
trotzdem wirkungslos lassen -- wenn der Solver den Modus nicht sieht oder die
cashflow-neutralen Faktoren nicht durchgereicht bekommt, waehlt er in jedem
Modus dieselbe Allokation.

Diese Suite faehrt deshalb ``run_solver()`` unter verschiedenen Modi mit
identischem Seed und identischen Inputs und verlangt, dass sich die GEWAEHLTE
Allokation unterscheidet, und zwar in der fachlich erwarteten Richtung:
Rendite-Maximierung riskanter, Risikomass-Minimierung defensiver.

Entscheidend fuer die Eignung: gefahren wird mit den PRODUKTIONS-Bandbreiten
der Hausmatrix-Zeile, nicht mit kuenstlich geoeffneten. Die Risikoprofil-Band
ist der eigentliche Boden unter den Varianten -- ein Modus waehlt INNERHALB
des Bandes, er kann es nicht verlassen. Ohne diesen Boden entartet
``min_volatility`` zu 100 % Liquiditaet, auch fuer einen Kunden mit
Risikoscore 70; das ist unten ausdruecklich festgehalten
(``test_without_a_risk_profile_band_min_volatility_degenerates``), damit die
Rolle des Bandes nicht fuer Zufall gehalten wird. Die Referenzmethodik notiert
denselben Punkt fuer ihre eigene Vol-Minimierung ("meist mit Mindest-Return").
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _path in (BACKEND_ROOT, TESTS_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest

from services.optimizer.objective_variants import (
    OBJECTIVE_GOAL_SHORTFALL,
    OBJECTIVE_MAX_DRAWDOWN,
    OBJECTIVE_MAX_RETURN,
    OBJECTIVE_MIN_VOLATILITY,
)
from services.optimizer.solver import evaluate_weights, run_solver

# Wiederverwendete Solver-Fixtures (CMA, Hausmatrix-Zeile, Ziel).
from test_optimizer_context import (  # noqa: F401
    _cma,
    _house_matrix,
    _pension_goal,
)

SEED = 20261011
N_PATHS = 600
HORIZON = 10
WEALTH = 500_000_00

# Bandbreiten ohne Risikoprofil-Boden -- NUR fuer den Entartungs-Nachweis
# unten, nie fuer die Richtungstests. Die Liquiditaets-Untergrenze bleibt beim
# globalen Floor (200 bps), der ist eine Policy-Vorgabe.
UNBOUNDED_BY_RISK_PROFILE = {
    "equities": (0, 10000),
    "bonds": (0, 10000),
    "real_estate": (0, 2000),
    "alternatives": (0, 1000),
    "liquidity": (200, 10000),
}


def _solver_kwargs(**overrides) -> dict:
    base = dict(
        cma=_cma(),
        goals=[_pension_goal()],
        house_matrix_row=_house_matrix(),
        score_x10=70,
        advisory_wealth_rappen=WEALTH,
        cashflow_series_rappen=[20_000_00] * HORIZON,
        horizon_years=HORIZON,
        n_paths=N_PATHS,
        seed=SEED,
    )
    base.update(overrides)
    return base


def _solve(mode: str, monkeypatch, **overrides):
    """Loest unter den Produktions-Bandbreiten der Hausmatrix-Zeile."""
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", mode)
    return run_solver(**_solver_kwargs(**overrides))


def _risky_share_bps(weights_bps: dict[str, int]) -> int:
    """Aktien + Alternative als grobes Risikomass der gewaehlten Allokation."""
    return int(weights_bps.get("equities", 0)) + int(
        weights_bps.get("alternatives", 0)
    )


def test_max_return_chooses_a_riskier_allocation_than_min_volatility(
    monkeypatch,
) -> None:
    """Der Modus bewegt die gewaehlte Allokation, nicht nur die Zielfunktion."""
    aggressive = _solve(OBJECTIVE_MAX_RETURN, monkeypatch)
    defensive = _solve(OBJECTIVE_MIN_VOLATILITY, monkeypatch)
    for result, name in ((aggressive, "max_return"), (defensive, "min_volatility")):
        if result.status == "fallback_house_matrix":
            pytest.skip(f"Solver-Fallback bei {name}; Richtung nicht messbar.")

    assert _risky_share_bps(aggressive.weights_bps) > _risky_share_bps(
        defensive.weights_bps
    ), (
        "Rendite-Maximierung muss riskanter ausfallen als "
        f"Volatilitaets-Minimierung: {aggressive.weights_bps} vs "
        f"{defensive.weights_bps}"
    )


def test_max_drawdown_chooses_a_defensive_allocation(monkeypatch) -> None:
    """Drawdown-Minimierung landet nicht bei der Rendite-Allokation."""
    drawdown = _solve(OBJECTIVE_MAX_DRAWDOWN, monkeypatch)
    aggressive = _solve(OBJECTIVE_MAX_RETURN, monkeypatch)
    for result, name in ((drawdown, "max_drawdown"), (aggressive, "max_return")):
        if result.status == "fallback_house_matrix":
            pytest.skip(f"Solver-Fallback bei {name}; Richtung nicht messbar.")

    assert _risky_share_bps(drawdown.weights_bps) < _risky_share_bps(
        aggressive.weights_bps
    ), (
        f"Drawdown-Minimierung ({drawdown.weights_bps}) ist nicht defensiver "
        f"als Rendite-Maximierung ({aggressive.weights_bps})"
    )


def test_default_mode_is_unaffected_by_the_variant_plumbing(monkeypatch) -> None:
    """Der Default-Lauf liefert dasselbe wie ohne gesetzte Variable.

    Haette das Durchreichen der Faktoren den Default-Pfad veraendert, waere
    jede bestehende Allokation verschoben.
    """
    monkeypatch.delenv("OPTIMIZER_OBJECTIVE", raising=False)
    unset = run_solver(**_solver_kwargs())
    explicit = _solve(OBJECTIVE_GOAL_SHORTFALL, monkeypatch)
    assert unset.weights_bps == explicit.weights_bps
    assert unset.objective_value == pytest.approx(explicit.objective_value, rel=1e-12)


def test_no_variant_can_leave_the_risk_profile_band(monkeypatch) -> None:
    """Die Eignungs-Garantie: jeder Modus waehlt INNERHALB des Bandes.

    Das ist der Grund, warum die Varianten ueberhaupt gefahrlos angeboten
    werden koennen. Ein Modus verschiebt die Wahl innerhalb der
    Risikoprofil-Bandbreiten; er kann sie nicht aufheben -- und er kann wegen
    der immer aktiven Chance-Penalty auch die Ziele nicht aufgeben.
    """
    house = _house_matrix()
    band = {
        "equities": (house.equity_min_bps, house.equity_max_bps),
        "bonds": (house.bonds_min_bps, house.bonds_max_bps),
        "real_estate": (house.real_estate_min_bps, house.real_estate_max_bps),
        "alternatives": (house.alt_min_bps, house.alt_max_bps),
        "liquidity": (house.liq_min_bps, house.liq_max_bps),
    }
    for mode in (
        OBJECTIVE_GOAL_SHORTFALL,
        OBJECTIVE_MAX_RETURN,
        OBJECTIVE_MIN_VOLATILITY,
        OBJECTIVE_MAX_DRAWDOWN,
    ):
        result = _solve(mode, monkeypatch)
        if result.status == "fallback_house_matrix":
            continue
        for bucket, (lower, upper) in band.items():
            value = int(result.weights_bps[bucket])
            assert lower <= value <= upper, (
                f"{mode}: {bucket}={value} bps liegt ausserhalb des "
                f"Risikoprofil-Bandes [{lower}, {upper}]"
            )


def test_without_a_risk_profile_band_min_volatility_degenerates(
    monkeypatch,
) -> None:
    """Ohne Risikoprofil-Boden faehrt Vol-Minimierung alles in Liquiditaet.

    Festgehalten, weil es die Rolle des Bandes erklaert: eine reine
    Volatilitaets-Minimierung hat ihr Optimum im risikolosen Asset, voellig
    unabhaengig vom Risikoprofil des Kunden. Die Goal-Chance-Penalty faengt
    das NICHT auf -- sie verlangt nur, dass die Ziele erreichbar bleiben, und
    bescheidene Ziele sind auch mit Cash erreichbar.

    Der Boden ist also das Hausmatrix-Band, nicht die Zielfunktion. Wer die
    Bandbreiten manuell weit oeffnet, hebt diesen Schutz auf -- das ist der
    bestehende Restriktionen-Mechanismus und keine Eigenheit der Varianten,
    aber es gehoert dokumentiert.
    """
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", OBJECTIVE_MIN_VOLATILITY)
    result = run_solver(
        **_solver_kwargs(effective_bounds_bps=UNBOUNDED_BY_RISK_PROFILE)
    )
    if result.status == "fallback_house_matrix":
        pytest.skip("Solver-Fallback; Entartung nicht messbar.")
    assert result.weights_bps["liquidity"] > 9000, (
        "Ohne Risikoprofil-Boden muesste die Vol-Minimierung praktisch alles "
        f"in Liquiditaet legen, gewaehlt wurde: {result.weights_bps}"
    )


def test_evaluate_weights_agrees_with_the_solver_in_a_variant(monkeypatch) -> None:
    """Apples-to-Apples auch in einer Variante.

    ``evaluate_weights()`` und der Solver-Closure muessen denselben
    Primaerterm sehen -- sonst weicht der persistierte objective_value von dem
    ab, was tatsaechlich optimiert wurde. Genau diese Kongruenz haengt daran,
    dass beide Aufrufstellen die cashflow-neutralen Faktoren mitgeben.
    """
    from services.optimizer.solver import build_optimizer_context

    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", OBJECTIVE_MIN_VOLATILITY)
    context_kwargs = _solver_kwargs()
    result = run_solver(**context_kwargs)
    if result.status == "fallback_house_matrix":
        pytest.skip("Solver-Fallback; Apples-to-Apples nicht messbar.")
    context = build_optimizer_context(**context_kwargs)
    evaluation = evaluate_weights(context, result.weights_bps)
    assert evaluation.objective_value == pytest.approx(
        result.objective_value, rel=1e-8
    )
