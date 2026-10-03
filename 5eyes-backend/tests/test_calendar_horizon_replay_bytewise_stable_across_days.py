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
    monkeypatch.setattr(calendar_horizon, "date", _PinnedToday)
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-CALENDAR-HORIZON-PARITY-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_goal_to_liability_replay_is_not_stable_across_real_calendar_days(
    pinned_calendar_horizon_today,
):
    """Red: `goal_to_liability()` never threads an explicit `as_of` through
    to `calendar_years_until()`. Replaying the IDENTICAL stored goal record
    "as if run on" two consecutive real calendar days (nothing about the
    goal itself changes) currently produces two different resolved
    target-year indices and liability schedules.
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
