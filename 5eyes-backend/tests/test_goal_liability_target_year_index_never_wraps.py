"""target_year_index darf NIE kleiner als 1 sein.

Sicherheits-Invariante, nicht Fachlogik: Konsumenten lesen den Index als
Spalte in die Wealth-Pfade (``wealth_paths[:, target_year_index]``, siehe
services/optimizer/objective.py). NumPy zaehlt negative Indizes VON HINTEN,
ein negativer Wert wuerde also still auf ein falsches Jahr zeigen statt
einen Fehler zu erzeugen.

Konkret eingefangen: mit der Umstellung auf Kalenderjahr-Buckets (ADR-2,
2026-10-11) verlor ``_build_einmalige_ausgabe`` seine ``max(1, ...)``-
Klammer. Ein Ziel mit Zieldatum 2020 lieferte bei Basisjahr 2026 den Index
-5, und ``wealth[:, -5]`` loest bei Horizont 10 auf Spalte 6 auf -- das
ueberfaellige Ziel waere im Jahr 6 "bewertet" worden, ohne Hinweis.

Kodiert wird stattdessen die etablierte Ausserhalb-Konvention
(``target_year_index > horizon_years``), die Konsumenten schon pruefen; die
RICHTUNG (vergangen statt zukuenftig) steht im evaluation_note.

Das ist die Notbremse, nicht die Loesung: ADR-3 (Goal-Lifecycle, Owner-
Entscheid Variante 3 = fail-closed bei ueberfaellig) ist weiterhin offen.
Ein Hinweistext ist kein Zustand.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import configure_mappers
from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.optimizer.goal_liabilities import goal_to_liability

HORIZON_YEARS = 10


def _goal(
    *,
    goal_type: str,
    target_date: date | None,
    start_date: date | None = None,
    frequency: str | None = None,
    is_ongoing: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="wrap-goal",
        label="Wrap",
        goal_type=goal_type,
        target_amount_rappen=100_000,
        target_wealth_rappen=1_000_000,
        target_return_bps=500,
        horizon_years=HORIZON_YEARS,
        target_date=target_date.isoformat() if target_date else None,
        start_date=start_date.isoformat() if start_date else None,
        is_ongoing=is_ongoing,
        frequency=frequency,
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=None,
    )


_PAST_OFFSETS_YEARS = [1, 3, 6, 20]


@pytest.mark.parametrize("years_ago", _PAST_OFFSETS_YEARS)
@pytest.mark.parametrize(
    "goal_type,frequency,is_ongoing",
    [
        ("Einmalige_Ausgabe", None, 0),
        ("Wiederkehrende_Ausgabe", "monatlich", 0),
        ("Pensionsausgabe", "jaehrlich", 0),
        ("Vermoegensziel", None, 0),
        ("Kapitalerhalt", None, 0),
    ],
)
def test_past_dated_goal_never_yields_an_index_below_one(
    years_ago, goal_type, frequency, is_ongoing
):
    today = date.today()
    target = date(today.year - years_ago, 6, 15)
    start = date(target.year - 2, 6, 15) if frequency else None

    liability = goal_to_liability(
        _goal(
            goal_type=goal_type,
            target_date=target,
            start_date=start,
            frequency=frequency,
            is_ongoing=is_ongoing,
        ),
        horizon_years=HORIZON_YEARS,
    )

    assert liability.target_year_index >= 1, (
        f"{goal_type} mit Zieldatum {target.isoformat()} lieferte Index "
        f"{liability.target_year_index}; negativ indiziert numpy von hinten "
        "und bewertet still ein falsches Jahr"
    )


def test_overdue_one_off_is_flagged_outside_the_horizon_with_a_reason():
    """Die Kodierung muss fuer Konsumenten erkennbar sein, nicht nur safe."""
    today = date.today()
    target = date(today.year - 6, 1, 1)

    liability = goal_to_liability(
        _goal(goal_type="Einmalige_Ausgabe", target_date=target),
        horizon_years=HORIZON_YEARS,
    )

    # Ausserhalb-Konvention: die bestehende Pruefung der Konsumenten greift.
    assert liability.target_year_index > HORIZON_YEARS
    assert liability.liability_path_rappen == [0] * HORIZON_YEARS
    note = liability.evaluation_note or ""
    assert "UEBERFAELLIG" in note, note
    # Die Richtung muss im Text stehen -- "ausserhalb des Horizonts" allein
    # wuerde ein vergangenes Ziel wie ein zukuenftiges aussehen lassen.
    assert target.isoformat() in note, note
    assert "Lifecycle-Status" in note, note


def test_future_goals_keep_their_ordinary_index():
    """Gegenprobe: die Notbremse darf gueltige Zukunftsziele nicht anfassen."""
    today = date.today()
    target = today + timedelta(days=365 * 4)

    liability = goal_to_liability(
        _goal(goal_type="Einmalige_Ausgabe", target_date=target),
        horizon_years=HORIZON_YEARS,
    )

    expected = target.year - today.year + 1
    assert liability.target_year_index == expected
    assert 1 <= liability.target_year_index <= HORIZON_YEARS
    assert sum(liability.liability_path_rappen) == 100_000
    assert liability.evaluation_note is None
