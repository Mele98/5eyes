"""Red-test matrix for GOAL-CALENDAR-HORIZON-PARITY-001.

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md,
finding GOAL-CALENDAR-HORIZON-PARITY-001 ("Repro 4").

Four independent horizon resolvers exist in this codebase and are supposed to agree
on "how many annual buckets lie between as_of and target_date":

- services.calendar_horizon.calendar_years_until  (canonical, calendar-anniversary based)
- services.optimizer.goal_liabilities._resolve_target_year_index (optimizer path;
  internally delegates to calendar_years_until)
- routers.wealth._goal_horizon_from_date (day-count based: (delta_days + 364) // 365)
- services.portfolio_engine_payload._goal_projection_years (same day-count formula)

The day-count formula used by the router and the reporting layer silently adds one
extra bucket whenever at least one leap day (Feb 29) falls inside the elapsed span,
even though the span is an *exact* calendar-year anniversary. The audit's canonical
repro ("Repro 4"): as_of=2026-10-03, target_date=2038-10-03 (delta_days=4383, spanning
the leap days 2028-02-29, 2032-02-29 and 2036-02-29) -> router/reporting say 13,
calendar_years_until/optimizer say 12.

This test file pins "today" to each case's as_of date (via monkeypatching the `date`
name each resolver module calls `.today()` on) and asserts all four resolvers agree.
The divergent cases are wrapped in xfail(strict=True) so the suite stays green while
documenting the exact shape of the bug for the eventual fix.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

import routers.wealth as wealth_router
import services.calendar_horizon as calendar_horizon
import services.portfolio_engine_payload as portfolio_engine_payload
from services.calendar_horizon import calendar_years_until
from services.optimizer.goal_liabilities import _resolve_target_year_index


class _FrozenDate(date):
    """A `datetime.date` subclass whose `.today()` returns a fixed value.

    Installed in place of the `date` name inside each resolver's own module so that
    every resolver that calls `date.today()` internally observes the same "today" as
    the resolver that takes an explicit `as_of` argument.
    """

    _frozen: "date | None" = None

    @classmethod
    def today(cls):  # type: ignore[override]
        return cls._frozen


@pytest.fixture
def freeze_today(monkeypatch):
    def _freeze(as_of: date):
        frozen = type("_Frozen", (_FrozenDate,), {"_frozen": as_of})
        monkeypatch.setattr(wealth_router, "date", frozen)
        monkeypatch.setattr(portfolio_engine_payload, "date", frozen)
        monkeypatch.setattr(calendar_horizon, "date", frozen)

    return _freeze


def _make_goal(target_date: date, *, start_date: date | None = None, goal_type: str = "Vermoegensziel"):
    return SimpleNamespace(
        target_date=target_date.isoformat(),
        start_date=start_date.isoformat() if start_date else None,
        goal_type=goal_type,
        horizon_years=999,
        target_amount_rappen=0,
        frequency=None,
        is_ongoing=0,
    )


def _resolve_all(as_of: date, target: date) -> dict[str, int]:
    """Run all four resolvers for the same (as_of, target) pair and return their results.

    Assumes `date.today()` inside the router/reporting/calendar_horizon modules has
    already been frozen to `as_of` via the `freeze_today` fixture.
    """

    goal = _make_goal(target)
    return {
        "calendar_years_until": calendar_years_until(target, as_of=as_of),
        "optimizer": _resolve_target_year_index(goal, horizon_years=999, clamp_to_horizon=False),
        "router": wealth_router._goal_horizon_from_date(target),
        "reporting": portfolio_engine_payload._goal_projection_years(goal),
    }


def _assert_all_agree(results: dict[str, int], expected: int) -> None:
    assert results == {
        "calendar_years_until": expected,
        "optimizer": expected,
        "router": expected,
        "reporting": expected,
    }, results


# ---------------------------------------------------------------------------
# Pflichttest 1: exact anniversaries over 1/4/12/20/40 years crossing leap years
# ---------------------------------------------------------------------------


def test_one_year_exact_anniversary_no_leap_crossed_agrees(freeze_today):
    as_of = date(2026, 10, 3)
    target = date(2027, 10, 3)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 1)


@pytest.mark.xfail(
    strict=True,
    reason="GOAL-CALENDAR-HORIZON-PARITY-001 — round 38 red test, see "
    "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md",
)
def test_four_year_exact_anniversary_crossing_one_leap_day_diverges(freeze_today):
    as_of = date(2026, 10, 3)
    target = date(2030, 10, 3)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 4)


@pytest.mark.xfail(
    strict=True,
    reason="GOAL-CALENDAR-HORIZON-PARITY-001 — round 38 red test, see "
    "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md",
)
def test_twelve_year_exact_anniversary_crossing_three_leap_days_diverges(freeze_today):
    """Audit's canonical repro ("Repro 4"), restated as a 12-year anniversary case."""

    as_of = date(2026, 10, 3)
    target = date(2038, 10, 3)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 12)


@pytest.mark.xfail(
    strict=True,
    reason="GOAL-CALENDAR-HORIZON-PARITY-001 — round 38 red test, see "
    "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md",
)
def test_twenty_year_exact_anniversary_crossing_five_leap_days_diverges(freeze_today):
    as_of = date(2026, 10, 3)
    target = date(2046, 10, 3)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 20)


@pytest.mark.xfail(
    strict=True,
    reason="GOAL-CALENDAR-HORIZON-PARITY-001 — round 38 red test, see "
    "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md",
)
def test_forty_year_exact_anniversary_crossing_ten_leap_days_diverges(freeze_today):
    as_of = date(2026, 10, 3)
    target = date(2066, 10, 3)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 40)


# ---------------------------------------------------------------------------
# Pflichttest 2: Feb 28 / Feb 29 boundary dates
# ---------------------------------------------------------------------------


def test_leap_day_as_of_to_feb28_next_year_is_exact_one_year(freeze_today):
    """as_of=2024-02-29 (leap day) -> target=2025-02-28 is the mapped anniversary."""

    as_of = date(2024, 2, 29)
    target = date(2025, 2, 28)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 1)


@pytest.mark.xfail(
    strict=True,
    reason="GOAL-CALENDAR-HORIZON-PARITY-001 — round 38 red test, see "
    "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md",
)
def test_leap_day_as_of_to_next_leap_day_four_years_diverges(freeze_today):
    """as_of=2024-02-29 -> target=2028-02-29, both leap days, exact 4-year anniversary."""

    as_of = date(2024, 2, 29)
    target = date(2028, 2, 29)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 4)


def test_feb28_as_of_non_leap_target_year_is_exact_one_year(freeze_today):
    as_of = date(2023, 2, 28)
    target = date(2024, 2, 28)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 1)


def test_feb28_as_of_to_feb29_one_day_past_anniversary_agrees_on_two(freeze_today):
    """target is one calendar day past the mapped Feb-28 anniversary -> correctly year 2.

    Not a divergence case: calendar_years_until's own Feb-29-maps-to-Feb-28 convention
    already bumps this to year 2, and the day-count formula happens to agree here.
    """

    as_of = date(2023, 2, 28)
    target = date(2024, 2, 29)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 2)


# ---------------------------------------------------------------------------
# Pflichttest 7: audit's exact Repro 4 (as_of=2026-10-03, target=2038-10-03, delta_days=4383)
# ---------------------------------------------------------------------------


def test_repro_4_exact_values_router_and_reporting_say_13_others_say_12(freeze_today):
    """Pin down the audit's literal Repro 4 numbers so a future fix can't silently drift.

    This is intentionally NOT wrapped in xfail: it documents today's actual (buggy)
    per-resolver outputs rather than the desired agreement, so it must stay green on
    its own and will fail loudly (not xfail-strict-pass) if any resolver's output for
    this exact input ever changes without the test being revisited.
    """

    as_of = date(2026, 10, 3)
    target = date(2038, 10, 3)
    assert (target - as_of).days == 4383

    freeze_today(as_of)
    goal = _make_goal(target)

    assert calendar_years_until(target, as_of=as_of) == 12
    assert _resolve_target_year_index(goal, horizon_years=999, clamp_to_horizon=False) == 12
    assert wealth_router._goal_horizon_from_date(target) == 13
    assert portfolio_engine_payload._goal_projection_years(goal) == 13


@pytest.mark.xfail(
    strict=True,
    reason="GOAL-CALENDAR-HORIZON-PARITY-001 — round 38 red test, see "
    "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md",
)
def test_repro_4_all_four_resolvers_should_agree_on_twelve(freeze_today):
    """The actual Pflichttest 7 assertion: all four resolvers should return 12."""

    as_of = date(2026, 10, 3)
    target = date(2038, 10, 3)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 12)
