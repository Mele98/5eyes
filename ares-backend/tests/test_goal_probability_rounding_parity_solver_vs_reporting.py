"""Solver und Reporting-MC runden bedingte Ziele identisch.

Befund aus dem Codex-Review vom 2026-10-11, selbst nachgemessen und
bestaetigt: nach ADR-2 wendeten beide Seiten ``probability_pct``
unabhaengig an, mit verschiedener Granularitaet UND verschiedenem
Rundungsmodus.

    Periodenbetrag 101 Rappen, jaehrlich, zwei Raten, probability_pct=50

    Solver:    int(round(101 * 0.5)) pro Bucket, dann summiert
               -> round(50.5) = 50  (Banker's Rounding)  -> 50 + 50 = 100
    Reporting: Summe 202, dann * 0.5, dann int() abgeschnitten
               -> 101.0 -> 101

Das ist dieselbe Solver/Reporting-Paritaetsklasse, die PR #576 geschlossen
hatte -- durch ADR-2 wieder aufgerissen, weil die Gewichtung an zwei
Stellen lag. Der Vertrag ist damit zum ZWEITEN Mal gebrochen worden; diese
Datei soll ein drittes Mal verhindern.

Fix: ``probability_factor`` ist ein Parameter von
``cashflow_timeline.recurring_occurrence_series()`` und wird dort PRO
BUCKET gerundet. Der Gesamtbetrag ist per Konstruktion die Summe des
Pfads, und Aufrufer duerfen den Faktor nicht erneut anwenden.

Warum pro Bucket und nicht auf der Summe: der Liability-Pfad wird pro Jahr
vom Vermoegen abgezogen (``wealth[:, t+1] = ... - liability[t]``), muss
also je Bucket eine ganze Rappenzahl sein. Rundet man stattdessen die
Summe, passt sie nicht mehr zur Summe ihrer eigenen Buckets.
"""
from __future__ import annotations

import sys
from datetime import date
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
from services.portfolio_engine_mc_simulation import (
    _recurring_outflow_total_rappen,
    _shared_recurring_series,
)

HORIZON_YEARS = 12


def _goal(
    *,
    amount_rappen: int,
    probability_pct: int | None,
    frequency: str = "jährlich",
    span_years: int = 2,
    goal_type: str = "Wiederkehrende_Ausgabe",
) -> SimpleNamespace:
    today = date.today()
    return SimpleNamespace(
        id="rounding-goal",
        label="Rounding",
        goal_type=goal_type,
        target_amount_rappen=amount_rappen,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=None,
        start_date=date(today.year + 1, 1, 1).isoformat(),
        target_date=date(today.year + span_years, 12, 31).isoformat(),
        is_ongoing=0,
        frequency=frequency,
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=probability_pct,
        success_probability_min_x100=None,
    )


def test_codex_repro_two_instalments_of_101_rappen_at_fifty_percent():
    """Der genaue Fall aus dem Codex-Review: 100 gegen 101 Rappen."""
    goal = _goal(amount_rappen=101, probability_pct=50)

    solver_total = sum(
        goal_to_liability(goal, horizon_years=HORIZON_YEARS).liability_path_rappen
    )
    reporting_total = _recurring_outflow_total_rappen(
        goal, date.today().year, HORIZON_YEARS
    )

    assert solver_total == reporting_total, (
        f"Solver {solver_total} != Reporting {reporting_total} Rappen -- die "
        "Wahrscheinlichkeitsgewichtung wird wieder an zwei Stellen "
        "angewandt"
    )
    # Pro-Bucket-Rundung ist der Vertrag: round(50.5) = 50, zweimal.
    assert solver_total == 100


@pytest.mark.parametrize("probability_pct", [None, 1, 17, 33, 50, 67, 99, 100])
@pytest.mark.parametrize(
    "amount_rappen", [1, 3, 101, 333, 7_777, 99_999, 24_000_00]
)
@pytest.mark.parametrize(
    "frequency", ["monatlich", "quartalsweise", "halbjährlich", "jährlich"]
)
def test_solver_and_reporting_totals_agree_exactly(
    probability_pct, amount_rappen, frequency
):
    """224 Kombinationen aus Betrag x Wahrscheinlichkeit x Frequenz.

    Rundungsdivergenzen zeigen sich nur bei bestimmten Restklassen, deshalb
    ein Sweep statt eines Einzelfalls -- der Codex-Fall war genau eine
    solche Restklasse (x.5 bei Banker's Rounding).
    """
    goal = _goal(
        amount_rappen=amount_rappen,
        probability_pct=probability_pct,
        frequency=frequency,
    )

    liability = goal_to_liability(goal, horizon_years=HORIZON_YEARS)
    series = _shared_recurring_series(goal, date.today().year, HORIZON_YEARS)

    # Bucket fuer Bucket, nicht nur die Summe: gleiche Summe aus
    # verschiedenen Buckets waere immer noch eine Paritaetsverletzung.
    assert liability.liability_path_rappen == series
    assert liability.target_amount_rappen == sum(series)
    assert _recurring_outflow_total_rappen(
        goal, date.today().year, HORIZON_YEARS
    ) == sum(series)


def test_total_equals_the_sum_of_its_own_buckets():
    """Der ausgewiesene Gesamtbetrag muss die Summe des Pfads sein.

    Die abgeloeste Reporting-Rechnung rundete die SUMME unabhaengig vom
    Pfad; damit konnte der ausgewiesene Bedarf von der Summe der jaehrlich
    abgezogenen Betraege abweichen -- eine Verbindlichkeit, die als Ganzes
    anders gross ist als ihre Teile.
    """
    for pct in (1, 7, 50, 83):
        goal = _goal(amount_rappen=1_234_57, probability_pct=pct, span_years=6)
        liability = goal_to_liability(goal, horizon_years=HORIZON_YEARS)
        assert liability.target_amount_rappen == sum(
            liability.liability_path_rappen
        ), pct


def test_conditional_goal_is_actually_weighted_down():
    """Gegenprobe: die gemeinsame Gewichtung darf sie nicht wegoptimieren."""
    unconditional = _goal(amount_rappen=10_000_00, probability_pct=100)
    half = _goal(amount_rappen=10_000_00, probability_pct=50)

    full_total = sum(
        goal_to_liability(unconditional, horizon_years=HORIZON_YEARS).liability_path_rappen
    )
    half_total = sum(
        goal_to_liability(half, horizon_years=HORIZON_YEARS).liability_path_rappen
    )

    assert full_total > 0
    assert half_total * 2 == full_total
