"""OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001 -- Modus pro Lauf eingefroren.

BEHOBEN am 2026-10-13. Der Befund bleibt unten stehen, weil die Tests ihn
weiterhin als Eigenschaft festhalten: der Lauf darf nur EINEN Primaerterm
sehen, und die Zahl der Umgebungslesungen pro Lauf ist jetzt 1 (vorher 205).

Fix: ``services/optimizer/objective_contract.py`` -- ein unveraenderlicher
``ObjectiveContractV1`` (Primaermodus + Goal-Weighting-Modus + Hash), genau
einmal in ``build_optimizer_context()`` aufgeloest, als Feld am
``OptimizerContext`` gefuehrt und an Objective, Post-Round-Evaluation,
Gewinner-Nachrechnung, Goal-Driver, Modellbasis und Sensitivity
durchgereicht. ``objective_contract_of()`` bricht fail-closed ab, statt bei
fehlendem Vertrag still auf die Umgebung zurueckzufallen.

Befund (historisch)
-------------------
``resolve_objective_mode()`` ist ein **Live-Read** der Umgebungsvariable
``OPTIMIZER_OBJECTIVE``, und ``combined_objective_two_phase()`` ruft ihn bei
JEDER Auswertung auf. Gemessen: **205 Aufrufe in einem einzigen
Solver-Lauf** (SLSQP-Multi-Start, 600 Pfade).

Aendert sich die Umgebung waehrend eines Laufs, optimiert der Solver eine
MISCHUNG zweier Zielfunktionen: ein Teil der Iterationen bewertet Kandidaten
nach dem einen Primaerterm, der Rest nach einem anderen. Das Ergebnis ist
keine Loesung eines wohldefinierten Optimierungsproblems mehr -- und nichts
erkennt es. Der persistierte Nachweis nennt genau einen Modus, naemlich den,
der beim Bauen des Modell-Basis-Blocks gerade gilt.

Der Live-Read ist Absicht und hat einen guten Grund (eine
Konfigurationsaenderung muss beim naechsten Lauf wirken, ohne Prozessneustart,
siehe Docstring von ``resolve_objective_mode``). Der Fehler ist nicht das
Lesen, sondern dass der gelesene Wert nicht EINMAL PRO LAUF eingefroren und
dann durchgereicht wird.

Verhaeltnis zum bekannten Nachbar-Befund
----------------------------------------
``resolve_goal_weighting_mode()`` hat dieselbe Eigenschaft, und ihr Docstring
vermerkt sie ausdruecklich als offene Arbeit ("binding the resolved mode into
one immutable per-run ObjectiveContract ... is tracked as further work", siehe
Zertifizierungs-Spezifikation Abschnitt 6.2-6.3).

Fuer die Ziel-GEWICHTUNG ist die Folge eine falsch gewichtete Summe derselben
Zielfunktion. Fuer den PRIMAERTERM ist sie schwerer: die Kandidaten werden
nach unterschiedlichen GROESSEN verglichen -- ein Drawdown-Anteil gegen eine
Renditestandardabweichung. Deshalb ein eigener Reproducer statt einer
Fussnote.

Fix
---
Den Modus einmal beim Bauen des ``OptimizerContext`` aufloesen, dort als Feld
fuehren und an ``combined_objective_two_phase()`` durchreichen (das Argument
``objective_mode`` existiert schon). Dann ist der Lauf per Konstruktion
konsistent, der Live-Read bleibt beim Context-Bau erhalten, und der Nachweis
kann den Wert aus dem Context nehmen statt aus der Umgebung.
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

import services.optimizer.objective as objective_module
import services.optimizer.objective_variants as objective_variants
from services.optimizer.objective_contract import (
    ObjectiveContractError,
    ObjectiveContractV1,
    objective_contract_of,
)
from services.optimizer.objective_variants import (
    OBJECTIVE_GOAL_SHORTFALL,
    OBJECTIVE_MIN_VOLATILITY,
)
from services.optimizer.solver import (
    build_optimizer_context,
    evaluate_weights,
    run_solver,
)

from test_optimizer_context import _cma, _house_matrix, _pension_goal  # noqa: F401


def _solver_kwargs() -> dict:
    return dict(
        cma=_cma(),
        goals=[_pension_goal()],
        house_matrix_row=_house_matrix(),
        score_x10=70,
        advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[20_000_00] * 10,
        horizon_years=10,
        n_paths=400,
        seed=20261011,
    )


def test_objective_mode_is_resolved_exactly_once_per_run(monkeypatch) -> None:
    """Der Primaermodus wird pro Lauf GENAU EINMAL aus der Umgebung gelesen.

    Dieser Test hat bis zum Fix das Gegenteil verlangt (``len(calls) > 1``)
    und damit den DEFEKT als erwarteten Zustand festgehalten -- sein eigener
    Docstring sagte: "Faellt die Zahl eines Tages auf 1, ist der Befund
    gefixt". Gemessen wurde 205; jetzt 1. Die Assertion ist umgedreht, nicht
    entfernt: die Zahl ist die eigentliche Aussage des Fixes.

    Exakt 1 statt "<= 1": null Lesungen waeren kein Fortschritt, sondern ein
    Zeichen, dass der Lauf den Modus gar nicht mehr aufloest und irgendwo
    ein hartkodierter Default greift.
    """
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", OBJECTIVE_MIN_VOLATILITY)
    calls: list[str] = []
    real = objective_variants.resolve_objective_mode

    def _counting() -> str:
        value = real()
        calls.append(value)
        return value

    monkeypatch.setattr(objective_variants, "resolve_objective_mode", _counting)
    run_solver(**_solver_kwargs())

    assert len(calls) == 1, (
        "Der Primaermodus muss pro Lauf genau einmal aufgeloest werden; "
        f"gemessen: {len(calls)} ({calls[:5]}...)"
    )
    assert calls == [OBJECTIVE_MIN_VOLATILITY], calls


def test_goal_weighting_mode_is_resolved_exactly_once_per_run(monkeypatch) -> None:
    """Dasselbe fuer den Goal-Weighting-Modus.

    Er war der haeufiger gelesene der beiden: ``_effective_hardness_weight()``
    las ihn pro ZIEL pro Auswertung. Ohne diesen Test waere der halbe Fix
    (nur der Primaermodus eingefroren) nicht von dem ganzen zu
    unterscheiden -- und genau diese Haelfte-Verwechslung ist die
    Fehlerklasse, die in dieser Kontrollrunde mehrfach aufgetreten ist.
    """
    monkeypatch.setenv("OPTIMIZER_GOAL_WEIGHTING", "hardness")
    calls: list[str] = []
    real = objective_module.resolve_goal_weighting_mode

    def _counting() -> str:
        value = real()
        calls.append(value)
        return value

    monkeypatch.setattr(objective_module, "resolve_goal_weighting_mode", _counting)
    run_solver(**_solver_kwargs())

    assert len(calls) == 1, (
        "Der Goal-Weighting-Modus muss pro Lauf genau einmal aufgeloest "
        f"werden; gemessen: {len(calls)}"
    )
    assert calls == ["hardness"], calls


def test_objective_mode_is_frozen_for_the_duration_of_a_run(monkeypatch) -> None:
    """Reproducer: ein Lauf darf nur EINEN Primaerterm sehen.

    Die Umgebung wird nach dem ersten Read umgestellt. Ein Lauf, dessen
    Zielfunktion per Konstruktion konsistent ist, darf davon nichts merken --
    er hat den Modus einmal aufgeloest und reicht ihn durch.
    """
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", OBJECTIVE_GOAL_SHORTFALL)
    observed: list[str] = []
    real = objective_variants.resolve_objective_mode

    def _flipping() -> str:
        value = real()
        observed.append(value)
        # Nach dem ersten Read die Umgebung umstellen -- ein eingefrorener
        # Lauf darf das nicht mehr sehen.
        import os

        os.environ["OPTIMIZER_OBJECTIVE"] = OBJECTIVE_MIN_VOLATILITY
        return value

    monkeypatch.setattr(objective_variants, "resolve_objective_mode", _flipping)
    run_solver(**_solver_kwargs())

    assert len(set(observed)) == 1, (
        "Ein Solver-Lauf hat mehr als einen Primaerterm gesehen und damit "
        "eine Mischung zweier Zielfunktionen optimiert: "
        f"{sorted(set(observed))}"
    )


def test_run_result_context_carries_the_contract_that_produced_it() -> None:
    """Der Lauf traegt seinen Vertrag mit -- nachweisbar, nicht rekonstruiert.

    Ohne diesen Test waere ein Fix denkbar, der die Umgebung nur noch einmal
    liest, den Wert aber nirgends festhaelt. Dann waere die Zahl der Reads
    richtig und der Nachweis trotzdem nicht fuehrbar: "welche Mathematik hat
    diese Allokation erzeugt" liesse sich nur aus der AKTUELLEN Umgebung
    raten.
    """
    result = run_solver(**_solver_kwargs())
    context = getattr(result, "context", None)
    assert context is not None, "Lauf ohne Context -- kein Nachweis moeglich."

    contract = objective_contract_of(context)
    assert isinstance(contract, ObjectiveContractV1)
    assert contract.objective_mode
    assert contract.goal_weighting_mode
    assert len(contract.contract_hash) == 64
    evidence = contract.as_evidence()
    assert evidence["objective_contract_hash"] == contract.contract_hash
    assert evidence["objective_mode"] == contract.objective_mode


def test_a_context_without_a_contract_fails_closed() -> None:
    """Ein Context ohne Vertrag darf nicht rechnen -- kein stiller Rueckfall.

    Das ist die Kehrseite des Fixes. Faellt ``objective_contract_of()`` bei
    fehlendem Vertrag auf die Umgebung zurueck, ist der Befund nicht
    geschlossen, sondern nur schwerer zu sehen: ein manuell gebauter oder
    deserialisierter Context wuerde wieder live lesen, und niemand merkt es.
    """
    kwargs = _solver_kwargs()
    context = build_optimizer_context(
        cma=kwargs["cma"],
        goals=kwargs["goals"],
        house_matrix_row=kwargs["house_matrix_row"],
        score_x10=kwargs["score_x10"],
        advisory_wealth_rappen=kwargs["advisory_wealth_rappen"],
        cashflow_series_rappen=kwargs["cashflow_series_rappen"],
        horizon_years=kwargs["horizon_years"],
        n_paths=kwargs["n_paths"],
        seed=kwargs["seed"],
    )
    # Gegenprobe zuerst: der regulaer gebaute Context HAT einen Vertrag.
    assert objective_contract_of(context) is not None

    from dataclasses import replace

    contractless = replace(context, objective_contract=None)
    with pytest.raises(ObjectiveContractError):
        evaluate_weights(contractless, {"equities": 4000, "bonds": 6000})


def test_contract_rejects_an_invalid_mode() -> None:
    """Ein Vertrag mit unzulaessigem Modus darf nicht existieren koennen.

    Sonst waere der Hash stabil und identifizierte eine Mathematik, die es
    nicht gibt -- ein Nachweis, der auf nichts zeigt.
    """
    with pytest.raises(ValueError):
        ObjectiveContractV1(
            objective_mode="tippfehler_modus", goal_weighting_mode="equal",
        )
    with pytest.raises(ValueError):
        ObjectiveContractV1(
            objective_mode=OBJECTIVE_GOAL_SHORTFALL,
            goal_weighting_mode="gewichtung_die_es_nicht_gibt",
        )


def test_contract_hash_separates_different_mathematics() -> None:
    """Verschiedene Mathematik -> verschiedener Hash; gleiche -> gleicher.

    Beide Richtungen, weil nur die erste zu pruefen auch von einem Hash
    erfuellt waere, der bei jedem Aufruf etwas anderes liefert.
    """
    a = ObjectiveContractV1(
        objective_mode=OBJECTIVE_GOAL_SHORTFALL, goal_weighting_mode="equal",
    )
    b = ObjectiveContractV1(
        objective_mode=OBJECTIVE_MIN_VOLATILITY, goal_weighting_mode="equal",
    )
    c = ObjectiveContractV1(
        objective_mode=OBJECTIVE_GOAL_SHORTFALL, goal_weighting_mode="hardness",
    )
    again = ObjectiveContractV1(
        objective_mode=OBJECTIVE_GOAL_SHORTFALL, goal_weighting_mode="equal",
    )

    hashes = {a.contract_hash, b.contract_hash, c.contract_hash}
    assert len(hashes) == 3, (
        "Zwei verschiedene Zielfunktions-Vertraege tragen denselben Hash: "
        f"{hashes}"
    )
    assert a.contract_hash == again.contract_hash, (
        "Derselbe Vertrag liefert verschiedene Hashes -- damit waere kein "
        "Vergleich zwischen Lauf und Nachweis moeglich."
    )
