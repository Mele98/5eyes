"""Red test for GOAL-CALENDAR-HORIZON-PARITY-001 (round 38).

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
(this path does not exist in this worktree's git history -- confirmed via
Glob/git log --all; derived directly from reading
services/calendar_horizon.py and services/optimizer/goal_liabilities.py, and
from empirically running both before writing assertions).

``calendar_horizon.calendar_years_until(target_date, as_of=...)`` itself
correctly accepts an explicit valuation date and is stable regardless of the
real wall clock when ``as_of`` is supplied -- that part is already correct
(audit Positivkontrolle #4) and is pinned below as a plain positive-control
test.

The production entry point actually used by the optimizer,
``goal_liabilities.goal_to_liability()`` (via its private
``_resolve_target_year_index()``, services/optimizer/goal_liabilities.py
line ~174), calls ``calendar_years_until(anchor)`` WITHOUT ever passing
``as_of`` -- it has no parameter for one at all. ``calendar_years_until``
then falls back to ``date.today()`` internally. Replaying the identical,
unchanged stored Goal record on two different real calendar days can
therefore silently change the resolved target-year index and liability
schedule, even though nothing about the goal's own data changed -- a run
is not byte-reproducible unless it happens to be replayed on the exact same
wall-clock day it was first computed.
"""
from __future__ import annotations

import sys
from datetime import date
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

import services.calendar_horizon as calendar_horizon  # noqa: E402
from services.optimizer.goal_liabilities import goal_to_liability  # noqa: E402

# target_date sits exactly one day past DAY_ONE's 1-year anniversary, and
# exactly ON DAY_TWO's 1-year anniversary -- verified empirically:
# calendar_years_until(TARGET_DATE, as_of=DAY_ONE) == 2
# calendar_years_until(TARGET_DATE, as_of=DAY_TWO) == 1
DAY_ONE = date(2026, 10, 4)
DAY_TWO = date(2026, 10, 5)  # DAY_ONE + 1 real calendar day, nothing else changes
TARGET_DATE = date(2027, 10, 5)


class _PinnedToday(date):
    """`date` subclass whose `.today()` returns whatever `pinned` is set to,
    so we can simulate "the real wall clock advanced by one day" without
    any actual waiting."""

    pinned: date = DAY_ONE

    @classmethod
    def today(cls):
        return cls.pinned


@pytest.fixture()
def pinned_calendar_horizon_today(monkeypatch):
    """Pinnt die Wanduhr in JEDEM Modul, das sie fuer Ziel-Buckets liest.

    NACHGEZOGEN am 2026-10-11 (ADR-2): vorher wurde nur
    ``calendar_horizon.date`` gepatcht. Seit die Bucket-Auflösung in
    ``services/optimizer/goal_liabilities.py`` selbst ``date.today()``
    aufruft (Kalenderjahr-Achse), griff der Pin dort nicht mehr -- beide
    Durchlaeufe sahen das ECHTE Heute, stimmten deshalb trivial ueberein,
    und der Reproducer wurde gruen, OHNE dass der Befund behoben ist.

    Der Befund ist unveraendert: ``goal_to_liability()`` nimmt keinen
    ``as_of``-Parameter, der Stichtag kommt aus der Wanduhr. Das ist genau
    ADR-1b (persistierter Bewertungsstichtag), noch offen. Mit korrektem
    Pin bleibt der Test rot, wie er soll.
    """
    import services.optimizer.goal_liabilities as goal_liabilities

    monkeypatch.setattr(calendar_horizon, "date", _PinnedToday)
    monkeypatch.setattr(goal_liabilities, "date", _PinnedToday)
    _PinnedToday.pinned = DAY_ONE
    yield _PinnedToday


def _make_wealth_goal() -> SimpleNamespace:
    return SimpleNamespace(
        id="g-replay-stability",
        label="Vermoegensziel Replay Stability",
        goal_type="Vermoegensziel",
        target_amount_rappen=None,
        target_wealth_rappen=100_00,
        target_return_bps=None,
        horizon_years=None,
        target_date=TARGET_DATE.isoformat(),
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=None,
        success_probability_min_x100=None,
    )


def test_calendar_years_until_is_stable_when_as_of_is_explicit(pinned_calendar_horizon_today):
    """Positive control (already correct): when the caller explicitly passes
    `as_of`, the result depends only on that explicit value, never on the
    real wall clock."""
    _PinnedToday.pinned = DAY_ONE
    result_pinned_to_day_one = calendar_horizon.calendar_years_until(TARGET_DATE, as_of=DAY_ONE)

    _PinnedToday.pinned = DAY_TWO  # wall clock "advances", but as_of is still explicit
    result_still_explicit_day_one = calendar_horizon.calendar_years_until(TARGET_DATE, as_of=DAY_ONE)

    assert result_pinned_to_day_one == result_still_explicit_day_one == 2


def test_goal_to_liability_replay_is_stable_within_a_calendar_year(
    pinned_calendar_horizon_today,
):
    """Zwei aufeinanderfolgende Kalendertage liefern denselben Bucket.

    GEFIXT am 2026-10-11 durch ADR-2 (Kalenderjahr-Buckets), aber nur
    TEILWEISE -- siehe den Jahresgrenz-Test darunter, der weiterhin rot ist.

    Vorher war der Index jahrestagsbasiert und sprang an JEDEM Tag:
    Stichtag 2026-10-04 -> Index 2, Stichtag 2026-10-05 -> Index 1, fuer
    dasselbe gespeicherte Ziel (Zieldatum 2027-10-05). Seit die Buckets
    Kalenderjahre sind, aendert sich der Bucket nur noch zum Jahreswechsel.

    Die Ursache ist damit NICHT behoben: ``goal_to_liability()`` nimmt
    weiterhin keinen ``as_of``-Parameter, der Stichtag kommt aus der
    Wanduhr. Das ist ADR-1b (persistierter Bewertungsstichtag), noch offen.
    Die Instabilitaet ist von "taeglich" auf "einmal im Jahr" geschrumpft --
    eine Verbesserung, keine Loesung.
    """
    goal = _make_wealth_goal()

    _PinnedToday.pinned = DAY_ONE
    liability_day_one = goal_to_liability(goal, horizon_years=10)

    _PinnedToday.pinned = DAY_TWO
    liability_day_two = goal_to_liability(goal, horizon_years=10)

    assert liability_day_one.target_year_index == liability_day_two.target_year_index, (
        f"replaying the same stored goal one real calendar day later changed "
        f"the resolved target-year index from {liability_day_one.target_year_index} "
        f"to {liability_day_two.target_year_index}"
    )
    assert liability_day_one.target_amount_rappen == liability_day_two.target_amount_rappen
    assert liability_day_one.liability_path_rappen == liability_day_two.liability_path_rappen


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-CALENDAR-HORIZON-PARITY-001 / ADR-1b -- der Bewertungsstichtag "
        "ist nicht gebunden: goal_to_liability() liest die Wanduhr. Seit "
        "ADR-2 (Kalenderjahr-Buckets) springt der Index nicht mehr taeglich, "
        "aber am Jahreswechsel weiterhin -- derselbe gespeicherte Datensatz "
        "liefert am 31.12. und am 1.1. verschiedene Buckets."
    ),
)
def test_goal_to_liability_replay_is_not_stable_across_the_year_boundary(
    pinned_calendar_horizon_today,
):
    """Der Restbefund: ein Replay ueber den Jahreswechsel verschiebt alles.

    Gemessen (Zieldatum 2027-10-05):
        Stichtag 2026-12-31 -> Bucket 2
        Stichtag 2027-01-01 -> Bucket 1

    Nichts am gespeicherten Ziel hat sich geaendert. Ein PDF-Reprint oder
    ein UI-Reload nach Neujahr zeigt damit eine andere wirtschaftliche
    Aussage als der Originallauf -- genau die Audit-Trail-Luecke, die
    ADR-1b schliesst (Stichtag beim Klick binden und persistieren, nie
    erneut date.today() lesen).
    """
    goal = _make_wealth_goal()

    _PinnedToday.pinned = date(2026, 12, 31)
    before = goal_to_liability(goal, horizon_years=10)

    _PinnedToday.pinned = date(2027, 1, 1)
    after = goal_to_liability(goal, horizon_years=10)

    assert before.target_year_index == after.target_year_index, (
        "Replay ueber den Jahreswechsel verschob den Bucket von "
        f"{before.target_year_index} auf {after.target_year_index}"
    )
    assert before.liability_path_rappen == after.liability_path_rappen
