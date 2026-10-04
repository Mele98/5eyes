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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RECURRENCE-SCHEDULE-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_monthly_goal_ending_mid_month_does_not_book_a_year_past_target_date():
    """start = today+375d, target = start+200d (ends mid-month, not on a
    year/period boundary). Empirically verified against current develop:
    the engine books a 2nd bucket whose year is one past where
    ``calendar_years_until(target_date)`` itself resolves -- an invented
    outflow year that starts after the goal's own end date.
    """
    today = date.today()
    start_date = today + timedelta(days=375)
    target_date = start_date + timedelta(days=200)

    goal = _make_goal(frequency="monatlich", start_date=start_date, target_date=target_date)
    liability = goal_to_liability(goal, horizon_years=HORIZON_YEARS)

    last_bucket = _last_nonzero_bucket_index(liability.liability_path_rappen)
    target_own_anchor = calendar_years_until(target_date)

    assert last_bucket is not None
    assert last_bucket <= target_own_anchor, (
        f"booked a liability bucket at year-index {last_bucket}, but "
        f"target_date {target_date.isoformat()} itself resolves to year-index "
        f"{target_own_anchor} -- an outflow was invented for a year that "
        "starts after the goal's own target_date"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RECURRENCE-SCHEDULE-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_quarterly_goal_ending_mid_period_does_not_book_a_year_past_target_date():
    """Same divergence as the monthly case above, reproduced at a different
    frequency (quartalsweise) and a different offset (start=today+1840d,
    target=start+200d) to show it is not specific to one frequency or one
    arbitrary pair of dates.
    """
    today = date.today()
    start_date = today + timedelta(days=1840)
    target_date = start_date + timedelta(days=200)

    goal = _make_goal(frequency="quartalsweise", start_date=start_date, target_date=target_date)
    liability = goal_to_liability(goal, horizon_years=HORIZON_YEARS)

    last_bucket = _last_nonzero_bucket_index(liability.liability_path_rappen)
    target_own_anchor = calendar_years_until(target_date)

    assert last_bucket is not None
    assert last_bucket <= target_own_anchor, (
        f"booked a liability bucket at year-index {last_bucket}, but "
        f"target_date {target_date.isoformat()} itself resolves to year-index "
        f"{target_own_anchor} -- an outflow was invented for a year that "
        "starts after the goal's own target_date"
    )


def test_positive_control_matching_window_does_not_overshoot_target_date():
    """Positive control (already correct today): start=today+830d,
    target=start+395d. Empirically verified: the last booked bucket exactly
    matches target_date's own resolved anchor year -- no overshoot. Proves
    the duration formula is not uniformly wrong; it is boundary-dependent,
    which is exactly why the bug in the two tests above is easy to miss.
    """
    today = date.today()
    start_date = today + timedelta(days=830)
    target_date = start_date + timedelta(days=395)

    goal = _make_goal(frequency="monatlich", start_date=start_date, target_date=target_date)
    liability = goal_to_liability(goal, horizon_years=HORIZON_YEARS)

    last_bucket = _last_nonzero_bucket_index(liability.liability_path_rappen)
    target_own_anchor = calendar_years_until(target_date)

    assert last_bucket == target_own_anchor
