"""Round 38 red test for finding GOAL-RECURRENCE-SCHEDULE-001.

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
(finding GOAL-RECURRENCE-SCHEDULE-001): the optimizer-consumer path
(services/optimizer/goal_liabilities.py, `_build_recurring_outflow` /
`_outflow_duration_years`) and the reporting-MC path
(services/portfolio_engine_mc_simulation.py, `_monte_carlo_goal_summary`
~L972-1005, via `_year_index_for_goal` / `_goal_duration_years`) each
independently re-derive "how many years does this recurring goal span, and
which calendar years does the outflow fall in" for the exact same
`Wiederkehrende_Ausgabe` / `Pensionsausgabe` goal. Both apply the same
"annual_amount * inclusive_year_count" shape, but:

- the optimizer anchors its window on `start_date` via
  `calendar_years_until` (anniversary-based, relative to *today*);
- the reporting-MC path anchors its evaluation index on `target_date` via
  `_goal_projection_years` (day-count-based, also relative to *today*,
  but rounded differently).

Because the two anchors (start vs. target) and the two rounding
conventions (anniversary comparison vs. day-count ceiling) are not the
same formula, the optimizer's liability schedule and the schedule implied
by the reporting-MC path's own (index, duration) pair can -- and, for an
ordinary multi-year recurring goal, DO -- disagree about which calendar
years carry the outflow, even when the aggregate total happens to agree.
Solver and reporting must treat the same goal identically; this test pins
that contract down year-by-year, not just on the aggregate total.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from services.cashflow_timeline import contribution_for_year
from services.optimizer.goal_liabilities import goal_to_liability
from services.portfolio_engine import (
    _goal_probability_factor,
    _year_index_for_goal,
)
from services.portfolio_engine_mc_simulation import _shared_recurring_series

HORIZON_YEARS = 15


def _make_recurring_goal() -> SimpleNamespace:
    """A plain, non-conditional annual recurring expense goal.

    start_date is one year out, target_date nine years after that (Jan 1 /
    Dec 31 boundaries, chosen so the window never collides with a leap-day
    edge case). horizon_years=15 is generous on both sides so neither
    consumer's horizon-clamping branch fires -- any divergence we observe
    comes purely from the two independent schedule formulas, not from
    clamping.
    """
    today = date.today()
    start_date = date(today.year + 1, 1, 1)
    target_date = date(today.year + 9, 12, 31)
    return SimpleNamespace(
        id="goal-rec-001",
        label="Jaehrliche Zusatzausgabe",
        goal_type="Wiederkehrende_Ausgabe",
        goal_scope="Beratungsvermoegen",
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        success_probability_min_x100=None,
        probability_pct=100,
        value_mode="nominal",
        target_amount_rappen=1_000_000,
        target_wealth_rappen=0,
        target_return_bps=0,
        start_date=start_date.isoformat(),
        target_date=target_date.isoformat(),
        horizon_years=None,
        is_ongoing=0,
        frequency="jaehrlich",
    )


def _reporting_mc_schedule(
    goal: SimpleNamespace, *, start_year: int, horizon_years: int
) -> tuple[int, list[int]]:
    """Der Zahlungsplan, den der Reporting-MC-Pfad benutzt.

    UMGESTELLT am 2026-10-11 (ADR-2c): vorher musste dieser Helfer den Plan
    REKONSTRUIEREN, weil der Reporting-MC keinen Pfad materialisierte --
    er rechnete nur ``annualisierter Betrag x Dauer in Jahres-Labels`` und
    verglich das Ergebnis an einem einzigen Auswertungsindex. Genau diese
    zweite, unabhaengige Implementierung ist jetzt entfernt; der
    Reporting-MC liest den Plan aus derselben Funktion wie der Solver.
    """
    series = _shared_recurring_series(goal, start_year, horizon_years)
    probability = _goal_probability_factor(goal)
    path = [int(round(value * probability)) for value in series]
    return sum(path), path


def _independent_calendar_enumeration(
    goal: SimpleNamespace, *, start_year: int, horizon_years: int
) -> list[int]:
    """Unabhaengige Referenz: direkt aus contribution_for_year().

    Haette dieser Test nur die beiden Produktionsseiten gegeneinander
    gestellt, waere er nach der Konsolidierung tautologisch geworden --
    beide rufen jetzt dieselbe Funktion. Deshalb prueft er zusaetzlich
    gegen eine Enumeration, die ohne die neue gemeinsame Schicht auskommt.
    """
    probability = _goal_probability_factor(goal)
    return [
        int(round(
            contribution_for_year(
                amount_rappen=int(goal.target_amount_rappen or 0),
                frequency=goal.frequency,
                nature="wiederkehrend",
                valid_from=goal.start_date,
                valid_until=goal.target_date,
                year=start_year + offset,
            ) * probability
        ))
        for offset in range(horizon_years)
    ]


def test_solver_and_reporting_mc_agree_on_recurring_goal_schedule():
    goal = _make_recurring_goal()
    start_year = date.today().year

    optimizer_liability = goal_to_liability(
        goal, horizon_years=HORIZON_YEARS, inflation_series_bps=None,
    )
    mc_total, mc_path = _reporting_mc_schedule(
        goal, start_year=start_year, horizon_years=HORIZON_YEARS,
    )

    # GOAL-RECURRENCE-SCHEDULE-001 / ADR-2c: Solver und Reporting-MC
    # belasten dieselben Kalenderjahre mit denselben Betraegen. Vorher
    # ankerte der Solver auf start_date und der Reporting-MC auf
    # target_date, mit zusaetzlich unterschiedlicher Rundung -- die
    # Gesamtsummen hoben sich oft auf, die Jahre nie.
    assert optimizer_liability.liability_path_rappen == mc_path
    assert optimizer_liability.target_amount_rappen == mc_total

    # Und beide stimmen mit einer Enumeration ueberein, die die gemeinsame
    # Schicht nicht benutzt -- sonst wuerde dieser Test nur noch bestaetigen,
    # dass eine Funktion sich selbst gleicht.
    assert mc_path == _independent_calendar_enumeration(
        goal, start_year=start_year, horizon_years=HORIZON_YEARS,
    )


def test_reporting_mc_evaluates_at_the_last_paid_bucket():
    """Der Auswertungsindex ist das letzte Bucket mit einer Faelligkeit.

    Vorher war es das letzte beruehrte Kalenderjahr-LABEL, also auch dann
    ein Jahr spaeter, wenn dort gar keine Zahlung mehr anfiel -- der
    kumulierte Strom wurde gegen ein Vermoegen geprueft, das ein
    zusaetzliches Wachstumsjahr hinter sich hatte.
    """
    goal = _make_recurring_goal()
    start_year = date.today().year

    _total, path = _reporting_mc_schedule(
        goal, start_year=start_year, horizon_years=HORIZON_YEARS,
    )
    expected = max(i for i, amount in enumerate(path) if amount) + 1

    assert _year_index_for_goal(goal, start_year, HORIZON_YEARS) == expected
