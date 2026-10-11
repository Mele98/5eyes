"""OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001 -- der Modus ist pro Lauf nicht eingefroren.

Befund
------
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

import services.optimizer.objective_variants as objective_variants
from services.optimizer.objective_variants import (
    OBJECTIVE_GOAL_SHORTFALL,
    OBJECTIVE_MIN_VOLATILITY,
)
from services.optimizer.solver import run_solver

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


def test_objective_mode_is_read_many_times_per_run(monkeypatch) -> None:
    """Belegt die Voraussetzung des Befundes: viele Reads pro Lauf.

    Dieser Test ist GRUEN -- er dokumentiert den Ist-Zustand, der den
    Reproducer darunter ueberhaupt moeglich macht. Faellt die Zahl eines Tages
    auf 1, ist der Befund gefixt und der strict-xfail darunter wird gruen.
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

    assert len(calls) > 1, (
        "Erwartet wurden mehrere Live-Reads pro Lauf; gemessen: "
        f"{len(calls)}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OPTIMIZER-OBJECTIVE-CONTRACT-FREEZE-001 (offen): der Objective-Modus "
        "ist pro Solver-Lauf nicht eingefroren. resolve_objective_mode() ist "
        "ein Live-Read der Umgebung und wird pro Lauf ~205 Mal aufgerufen; "
        "aendert sich OPTIMIZER_OBJECTIVE mittendrin, vergleicht der Solver "
        "Kandidaten nach UNTERSCHIEDLICHEN Groessen (ein Drawdown-Anteil gegen "
        "eine Renditestandardabweichung) und das Ergebnis loest kein "
        "wohldefiniertes Optimierungsproblem mehr -- ohne dass es irgendwo "
        "auffaellt. Derselbe strukturelle Befund wie bei "
        "resolve_goal_weighting_mode() (dort als offene Arbeit vermerkt, "
        "Zertifizierungs-Spez. 6.2-6.3), aber mit schwererer Folge. Fix: den "
        "Modus einmal beim OptimizerContext-Bau aufloesen, als Feld fuehren "
        "und ueber das bereits vorhandene objective_mode-Argument "
        "durchreichen."
    ),
)
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
