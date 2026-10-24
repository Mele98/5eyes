"""Red test for GOAL-RECURRENCE-SCHEDULE-001 (round 38), Pflichttest 5.

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
(this path does not exist in this worktree's git history -- confirmed via
Glob/git log --all; derived directly from reading
services/optimizer/goal_liabilities.py and services/calendar_horizon.py, and
from empirically running goal_to_liability() for every case below, including
a 2000-sample randomized sweep, before writing any assertion).

``_outflow_duration_years()`` computes how many yearly buckets a recurring
goal spans as the plain calendar-year LABEL difference
``target_date.year - start_date.year + 1``. ``_resolve_target_year_index()``
separately anchors the FIRST bucket via ``calendar_years_until(start_date)``
(leap-aware, relative to today). Because the label-difference formula and
the leap-aware anchor formula round differently, the last bucket written
(``target_year_index + duration - 1``) can land ONE YEAR PAST the index that
``calendar_years_until(target_date)`` itself would resolve to for the same
target_date -- i.e. the engine invents an outflow for a year that starts
only AFTER the goal's own target_date/end has already passed. This
reproduces for both a goal whose target_date falls mid-month (not on a
year/period boundary) and across different frequencies; a 2000-sample
random sweep of (start, target) pairs found this in ~18% of cases.

A case with no such divergence is included as a plain positive control to
show the duration formula is not uniformly wrong -- only direction- and
boundary-dependent, which is exactly why this is a release-blocking
correctness bug rather than a uniform, easily-noticed offset.

All start/target dates are expressed as explicit day-offsets from
``date.today()`` rather than hardcoded calendar dates, so the exact
divergence (found empirically for these specific offsets) remains
reproducible however much time passes between when this test was written
and when it runs.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers  # noqa: E402
from database import Base  # noqa: E402,F401
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.calendar_horizon import calendar_years_until  # noqa: E402
from services.optimizer.goal_liabilities import goal_to_liability  # noqa: E402

CHF = 100  # 1 CHF == 100 Rappen
HORIZON_YEARS = 25


def _make_goal(*, frequency: str, start_date: date, target_date: date) -> SimpleNamespace:
    """Mock-Goal as SimpleNamespace -- same pattern as
    tests/test_optimizer_goal_liabilities.py::_make_goal."""
    return SimpleNamespace(
        id="g-no-occurrence-after-target",
        label="No-Occurrence-After-Target Goal",
        goal_type="Wiederkehrende_Ausgabe",
        target_amount_rappen=100 * CHF,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=None,
        target_date=target_date.isoformat(),
        start_date=start_date.isoformat(),
        is_ongoing=0,
        frequency=frequency,
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
    )


def _last_nonzero_bucket_index(liability_path_rappen: list[int]) -> int | None:
    nonzero_positions = [i + 1 for i, amount in enumerate(liability_path_rappen) if amount]
    return max(nonzero_positions) if nonzero_positions else None


def _target_calendar_bucket(target_date: date) -> int:
    """1-based Bucket des Kalenderjahres, in dem target_date liegt.

    GEFIXT am 2026-10-11 (ADR-2): die Tests dieser Datei verglichen den
    gebuchten Bucket vorher mit ``calendar_years_until(target_date)``, also
    einen Kalenderjahr-Bucket mit einem JAHRESTAG-Index. Das sind zwei
    verschiedene Konventionen, und ihre Vermischung war genau der zweite
    Teil des Befunds. Die Invariante, die der Prosa-Text dieser Datei
    beschreibt -- "es wird kein Outflow nach dem Ende des Ziels gebucht" --
    ist auf der Kalenderjahr-Achse formuliert: das letzte belastete Bucket
    darf nicht nach dem Kalenderjahr von target_date liegen.
    """
    return int(target_date.year) - date.today().year + 1


def test_monthly_goal_ending_mid_month_does_not_book_a_year_past_target_date():
    """start = today+375d, target = start+200d (endet mitten im Monat, nicht
    an einer Jahres- oder Periodengrenze).

    Die alte Label-Rechnung buchte ein Bucket, das nach dem eigenen
    Enddatum des Ziels beginnt -- ein erfundenes Outflow-Jahr. Jetzt endet
    der Strom im Kalenderjahr von target_date.
    """
    today = date.today()
    start_date = today + timedelta(days=375)
    target_date = start_date + timedelta(days=200)

    goal = _make_goal(frequency="monatlich", start_date=start_date, target_date=target_date)
    liability = goal_to_liability(goal, horizon_years=HORIZON_YEARS)

    last_bucket = _last_nonzero_bucket_index(liability.liability_path_rappen)
    target_bucket = _target_calendar_bucket(target_date)

    assert last_bucket is not None
    assert last_bucket <= target_bucket, (
        f"booked a liability bucket at calendar-year bucket {last_bucket}, "
        f"but target_date {target_date.isoformat()} lies in bucket "
        f"{target_bucket} -- an outflow was invented for a year that starts "
        "after the goal's own target_date"
    )


def test_quarterly_goal_ending_mid_period_does_not_book_a_year_past_target_date():
    """Dieselbe Abweichung wie im monatlichen Fall oben, an einer anderen
    Frequenz (quartalsweise) und einem anderen Versatz (start=today+1840d,
    target=start+200d) -- der Fehler war nicht an eine Frequenz oder an ein
    einzelnes Datumspaar gebunden.
    """
    today = date.today()
    start_date = today + timedelta(days=1840)
    target_date = start_date + timedelta(days=200)

    goal = _make_goal(frequency="quartalsweise", start_date=start_date, target_date=target_date)
    liability = goal_to_liability(goal, horizon_years=HORIZON_YEARS)

    last_bucket = _last_nonzero_bucket_index(liability.liability_path_rappen)
    target_bucket = _target_calendar_bucket(target_date)

    assert last_bucket is not None
    assert last_bucket <= target_bucket, (
        f"booked a liability bucket at calendar-year bucket {last_bucket}, "
        f"but target_date {target_date.isoformat()} lies in bucket "
        f"{target_bucket} -- an outflow was invented for a year that starts "
        "after the goal's own target_date"
    )


def test_positive_control_matching_window_does_not_overshoot_target_date():
    """start=today+830d, target=start+395d -- der Strom endet genau im
    Kalenderjahr von target_date, also exakt dort, wo er enden muss.

    Dieser Test verglich vorher mit ``calendar_years_until(target_date)``
    und war damit an die Jahrestag-Konvention gebunden; er ging nur
    deshalb durch, weil der Defekt randabhaengig war. Jetzt prueft er
    Gleichheit auf der Kalenderjahr-Achse -- derselben Achse, auf der die
    Cashflow-Serie liegt.
    """
    today = date.today()
    start_date = today + timedelta(days=830)
    target_date = start_date + timedelta(days=395)

    goal = _make_goal(frequency="monatlich", start_date=start_date, target_date=target_date)
    liability = goal_to_liability(goal, horizon_years=HORIZON_YEARS)

    last_bucket = _last_nonzero_bucket_index(liability.liability_path_rappen)

    assert last_bucket == _target_calendar_bucket(target_date)
