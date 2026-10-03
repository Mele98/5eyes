"""Red test for GOAL-RECURRENCE-SCHEDULE-001 (round 38), Pflichttest 2.

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
(this path does not exist in this worktree's git history -- confirmed via
Glob/git log --all; derived directly from reading
services/optimizer/goal_liabilities.py and from empirically running
goal_to_liability() for every combination below before writing assertions).

``_build_recurring_outflow()`` books one YEAR-sized bucket per element of
``_outflow_duration_years()``, and that duration is computed as the plain
calendar-year LABEL difference ``target_date.year - start_date.year + 1``
(``goal_liabilities.py::_outflow_duration_years``), not the number of
calendar years the stream actually, elapsed-time-wise, overlaps. Frequency
(monatlich/quartalsweise/halbjaehrlich/jaehrlich) only scales the per-year
annualized amount (``_annualize_amount_rappen``); it does not change the
duration-counting bug, so the same bucket-count defect appears identically
-- just scaled -- at every frequency.

This matrix pins down, for each of the four supported frequencies, both:

- two window shapes where the calendar-label formula is CORRECT today
  (same-year window; an exact N-year span landing on Dec 31) -- plain
  passing positive-control tests, not xfail;
- two window shapes where it overcounts by exactly one bucket (a 1-day
  cross-year straddle; an exact N-year span landing on Jan 1 of year N+1)
  -- xfail(strict) red tests.

Every expected total/bucket-count below was verified by directly executing
``goal_to_liability()`` against current `develop` before writing the
assertions (not hand-derived in the abstract).
"""
from __future__ import annotations

import sys
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

from services.optimizer.goal_liabilities import goal_to_liability  # noqa: E402

CHF = 100  # 1 CHF == 100 Rappen
ANNUAL_AMOUNT_RAPPEN = 100 * CHF  # CHF100 (per-frequency-period amount)

FREQUENCIES = ["jaehrlich", "monatlich", "quartalsweise", "halbjaehrlich"]
_ANNUALIZATION_MULTIPLIER = {
    "jaehrlich": 1,
    "monatlich": 12,
    "quartalsweise": 4,
    "halbjaehrlich": 2,
}


def _make_goal(*, frequency: str, start_date: str, target_date: str) -> SimpleNamespace:
    """Mock-Goal as SimpleNamespace -- same pattern as
    tests/test_optimizer_goal_liabilities.py::_make_goal and the sibling
    round-38 test_goal_liability_dec31_jan1_single_occurrence.py."""
    return SimpleNamespace(
        id="g-freq-window",
        label="Frequency/Window Matrix Goal",
        goal_type="Wiederkehrende_Ausgabe",
        target_amount_rappen=ANNUAL_AMOUNT_RAPPEN,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=None,
        target_date=target_date,
        start_date=start_date,
        is_ongoing=0,
        frequency=frequency,
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
    )


def _annual_total(frequency: str) -> int:
    return ANNUAL_AMOUNT_RAPPEN * _ANNUALIZATION_MULTIPLIER[frequency]


@pytest.mark.parametrize("frequency", FREQUENCIES)
def test_same_year_window_books_exactly_one_bucket(frequency):
    """Positive control (already correct today): start and target both fall
    within the same calendar year -- the calendar-label formula
    (target.year - start.year + 1 == 1) happens to match the genuinely
    correct one-year duration here, regardless of frequency."""
    goal = _make_goal(frequency=frequency, start_date="2027-03-01", target_date="2027-09-01")
    liab = goal_to_liability(goal, horizon_years=10)

    nonzero_buckets = [amount for amount in liab.liability_path_rappen if amount]
    assert len(nonzero_buckets) == 1
    assert liab.target_amount_rappen == _annual_total(frequency)


@pytest.mark.parametrize("frequency", FREQUENCIES)
def test_exact_two_year_span_ending_dec31_books_exactly_two_buckets(frequency):
    """Positive control (already correct today): start=2027-01-01,
    target=2028-12-31 -- an exact two-year span that ends on Dec 31 without
    crossing into a third calendar-year label. target.year - start.year + 1
    == 2, which matches the genuinely correct two-year duration."""
    goal = _make_goal(frequency=frequency, start_date="2027-01-01", target_date="2028-12-31")
    liab = goal_to_liability(goal, horizon_years=10)

    nonzero_buckets = [amount for amount in liab.liability_path_rappen if amount]
    assert len(nonzero_buckets) == 2
    assert liab.target_amount_rappen == 2 * _annual_total(frequency)


@pytest.mark.parametrize("frequency", FREQUENCIES)
@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RECURRENCE-SCHEDULE-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_one_day_cross_year_straddle_books_one_bucket_not_two(frequency):
    """Red: start=2027-12-31, target=2028-01-01 -- one calendar day elapses,
    but the calendar-label formula counts two distinct year labels (2027,
    2028) and books the full annualized amount into each, doubling the
    economically correct single-occurrence total."""
    goal = _make_goal(frequency=frequency, start_date="2027-12-31", target_date="2028-01-01")
    liab = goal_to_liability(goal, horizon_years=10)

    nonzero_buckets = [amount for amount in liab.liability_path_rappen if amount]
    assert len(nonzero_buckets) == 1, (
        f"expected a single occurrence bucket, got {len(nonzero_buckets)} "
        f"({nonzero_buckets}) -- Dec31/Jan1 boundary double-booked at {frequency}"
    )
    assert liab.target_amount_rappen == _annual_total(frequency)


@pytest.mark.parametrize("frequency", FREQUENCIES)
@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RECURRENCE-SCHEDULE-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_exact_two_year_span_landing_on_jan1_books_two_buckets_not_three(frequency):
    """Red: start=2027-01-01, target=2029-01-01 -- an exact two-year span
    (the stream ends exactly as year 3 begins). target.year - start.year + 1
    == 3, overcounting by one whole bucket versus the genuinely correct
    two-year duration (contrast with the Dec-31-ending positive control
    above, which lands one day earlier and is counted correctly)."""
    goal = _make_goal(frequency=frequency, start_date="2027-01-01", target_date="2029-01-01")
    liab = goal_to_liability(goal, horizon_years=10)

    nonzero_buckets = [amount for amount in liab.liability_path_rappen if amount]
    assert len(nonzero_buckets) == 2, (
        f"expected exactly two occurrence buckets, got {len(nonzero_buckets)} "
        f"({nonzero_buckets}) -- exact Jan-1 landing overcounted at {frequency}"
    )
    assert liab.target_amount_rappen == 2 * _annual_total(frequency)
