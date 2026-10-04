"""Property test for GOAL-RECURRENCE-SCHEDULE-001.

Core invariant under test: for a recurring (Wiederkehrende_Ausgabe /
Pensionsausgabe) goal, the TOTAL amount the optimizer charges to the
portfolio over the goal's lifetime (the sum of
``GoalLiability.liability_path_rappen``, produced by
``services/optimizer/goal_liabilities.py::_build_recurring_outflow``) must
equal the sum of the individual, calendar-accurate occurrence amounts a
human (or a billing system) would actually observe for that frequency
between ``start_date`` and ``target_date`` (inclusive), or up to the
simulation horizon for an ``is_ongoing`` goal with no end date.

``_build_recurring_outflow`` does NOT enumerate individual occurrences. It:
  1. annualizes the per-period amount (``target_amount_rappen`` * periods
     per year, e.g. monthly * 12),
  2. determines a 1-based bucket start index via
     ``calendar_years_until(start_date)`` -- an anchor relative to
     ``date.today()`` (the valuation date), NOT relative to ``start_date``
     itself,
  3. determines a bucket COUNT via whole calendar-year arithmetic
     (``target_date.year - start_date.year + 1``, or
     ``horizon_years - target_year_index + 1`` when ``is_ongoing``), and
  4. assigns the FULL annualized amount to every one of those buckets.

Because bucket boundaries are anchored at the valuation date while actual
occurrences are anchored at ``start_date``, and because partial first/last
calendar years are charged a FULL annual amount instead of a pro-rated
partial amount, the bucketed total systematically diverges from the true
occurrence total whenever ``start_date`` does not fall exactly on a
valuation-date anniversary and run for a whole number of years -- i.e.
almost always. This test materializes that divergence as a red test.

``hypothesis`` is not a project dependency (checked via
``requirements.txt``), so this uses a fixed-seed pseudo-random loop instead
of ``@given`` for reproducible property-style coverage.

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
(Finding GOAL-RECURRENCE-SCHEDULE-001) for full context, when available in
your checkout. This worktree did not have that file materialized at the
time this test was written; the invariant and reproduction below were
derived directly from reading
``services/optimizer/goal_liabilities.py::_build_recurring_outflow`` /
``_outflow_duration_years`` / ``_resolve_target_year_index`` and
``services/calendar_horizon.py::calendar_years_until``.
"""
from __future__ import annotations

import random
import sys
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.calendar_horizon import add_calendar_years
from services.optimizer.goal_liabilities import goal_to_liability


# ============================================================================
# Canonical occurrence oracle (independent of the production bucketing code)
# ============================================================================

# frequency label (as understood by services.cashflow_timeline.normalize_frequency)
# -> step size in months between successive occurrences.
_FREQUENCY_STEP_MONTHS = {
    "monatlich": 1,
    "quartalsweise": 3,
    "halbjaehrlich": 6,
    "jaehrlich": 12,
}

HORIZON_YEARS = 60  # generous -- no case below gets anywhere near this, so
# the production horizon-clamp (``if year_idx > horizon_years: break``)
# never fires and cannot be blamed for any mismatch this test finds.


def _add_months(anchor: date, months: int) -> date:
    """Step a date forward by whole months, clamping the day to month-end.

    Independent re-implementation of simple calendar-month arithmetic (not a
    call into the module under test) -- this is the textbook definition of
    "N months later" used to decide when a monthly/quarterly/etc. payment
    is actually due.
    """
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    day = min(anchor.day, monthrange(year, month)[1])
    return date(year, month, day)


def _canonical_occurrence_sum(
    *, start_date: date, end_date: date, step_months: int, amount_rappen: int
) -> int:
    """Sum of occurrence amounts, stepping from start_date, inclusive end."""
    total = 0
    current = start_date
    while current <= end_date:
        total += amount_rappen
        current = _add_months(current, step_months)
    return total


# ============================================================================
# Goal mock (mirrors the SimpleNamespace pattern used in
# tests/test_optimizer_goal_liabilities.py -- goal_liabilities.py only
# duck-types on attribute access, no DB object required).
# ============================================================================


def _make_recurring_goal(
    *,
    goal_type: str,
    amount_rappen: int,
    frequency: str,
    start_date: date,
    target_date: date | None,
    is_ongoing: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="goal-under-test",
        label="Property-Test-Goal",
        goal_type=goal_type,
        target_amount_rappen=amount_rappen,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=HORIZON_YEARS,
        target_date=target_date.isoformat() if target_date else None,
        start_date=start_date.isoformat(),
        is_ongoing=is_ongoing,
        frequency=frequency,
        hardness="Primaer",
        rank=3,
        weight_bps=None,
        value_mode="nominal",  # no inflation -- isolates the pure scheduling bug
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=100,  # no pro-rata factor -- isolates the pure scheduling bug
        success_probability_min_x100=None,
    )


# ============================================================================
# Case generation: ~80 fixed-seed pseudo-random combinations of
# (frequency, start_date, end_date-or-ongoing, amount).
# ============================================================================


def _generate_cases() -> list[dict]:
    today = date.today()
    frequencies = list(_FREQUENCY_STEP_MONTHS.keys())
    goal_types = ["Wiederkehrende_Ausgabe", "Pensionsausgabe"]
    cases: list[dict] = []
    for seed in range(80):
        rng = random.Random(seed)
        frequency = rng.choice(frequencies)
        goal_type = rng.choice(goal_types)
        amount_rappen = rng.randint(1_000, 999_999)
        start_date = today + timedelta(days=rng.randint(1, 3650))
        is_ongoing = 1 if rng.random() < 0.3 else 0
        if is_ongoing:
            target_date = None
        else:
            target_date = start_date + timedelta(days=rng.randint(180, 3650))
        cases.append(
            dict(
                seed=seed,
                goal_type=goal_type,
                frequency=frequency,
                amount_rappen=amount_rappen,
                start_date=start_date,
                target_date=target_date,
                is_ongoing=is_ongoing,
            )
        )
    return cases


# ============================================================================
# The property test
# ============================================================================


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RECURRENCE-SCHEDULE-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_goal_liability_bucket_sum_equals_occurrence_sum() -> None:
    """Bucket-sum (production) must equal occurrence-sum (canonical oracle).

    For every generated (frequency, start_date, end/is_ongoing, amount)
    combination, the total rappen the optimizer liability path charges for
    a recurring goal must equal the total rappen a calendar-accurate
    enumeration of individual occurrences would produce. GOAL-RECURRENCE-
    SCHEDULE-001 documents that it currently does not, because bucketing
    anchors on whole valuation-date-relative calendar years instead of on
    the goal's own start_date / actual occurrence dates.
    """
    today = date.today()
    cases = _generate_cases()
    failures: list[str] = []

    for case in cases:
        goal = _make_recurring_goal(
            goal_type=case["goal_type"],
            amount_rappen=case["amount_rappen"],
            frequency=case["frequency"],
            start_date=case["start_date"],
            target_date=case["target_date"],
            is_ongoing=case["is_ongoing"],
        )

        liability = goal_to_liability(goal, horizon_years=HORIZON_YEARS)
        bucket_sum = sum(liability.liability_path_rappen)

        step_months = _FREQUENCY_STEP_MONTHS[case["frequency"]]
        if case["is_ongoing"]:
            # No explicit end date: the only cap production applies is the
            # simulation horizon itself, expressed as whole valuation-date
            # anniversaries (consistent with calendar_years_until's own
            # anchor). This is a shared calendar-arithmetic helper, not a
            # re-use of the buggy bucketing logic under test.
            enumeration_end = add_calendar_years(today, HORIZON_YEARS)
        else:
            enumeration_end = case["target_date"]

        occurrence_sum = _canonical_occurrence_sum(
            start_date=case["start_date"],
            end_date=enumeration_end,
            step_months=step_months,
            amount_rappen=case["amount_rappen"],
        )

        if bucket_sum != occurrence_sum:
            failures.append(
                f"seed={case['seed']} goal_type={case['goal_type']} "
                f"frequency={case['frequency']} start={case['start_date']} "
                f"target={case['target_date']} is_ongoing={case['is_ongoing']} "
                f"amount={case['amount_rappen']}: "
                f"bucket_sum={bucket_sum} occurrence_sum={occurrence_sum} "
                f"diff={bucket_sum - occurrence_sum}"
            )

    assert not failures, (
        f"{len(failures)}/{len(cases)} generated cases violated the "
        "bucket-sum == occurrence-sum invariant (GOAL-RECURRENCE-SCHEDULE-001):\n"
        + "\n".join(failures[:10])
    )
