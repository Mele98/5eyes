"""Red test for GOAL-RECURRENCE-SCHEDULE-001 (round 38).

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md,
finding GOAL-RECURRENCE-SCHEDULE-001, "Repro 2".

Bug: ``_outflow_duration_years()`` in services/optimizer/goal_liabilities.py
computes the number of annual outflow buckets for a recurring
(Wiederkehrende_Ausgabe/Pensionsausgabe) goal as::

    full_years = target_date.year - start_date.year + 1

That is a *calendar-label* count, not an elapsed-time count. A goal that
starts on 2026-12-31 and ends on 2027-01-01 -- one calendar day later --
touches two calendar-year labels (2026 and 2027), so ``full_years`` is 2
even though only a single annual occurrence has actually elapsed.
``_build_recurring_outflow()`` then writes the full annualized amount into
*each* touched calendar-year bucket, so the liability is double-counted:
one CHF100/year goal spanning the Dec-31/Jan-1 boundary is booked as
CHF200 (two occurrences) instead of CHF100 (one occurrence). The same
calendar-label arithmetic also corrupts frequencies other than "annual":
a CHF100/month goal spanning the same boundary should book one year's
worth of monthly contributions (CHF1'200), but the bug doubles it to
CHF2'400.

Both tests below assert the economically correct, single-occurrence total.
They are expected to fail against the current implementation and are
therefore wrapped in ``xfail(strict=True)`` so the suite stays green while
the bug remains open. Once GOAL-RECURRENCE-SCHEDULE-001 is fixed, these
tests will start passing (xfail-strict turns that into a hard failure),
which is the intended signal to remove the xfail marker.
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


def _make_goal(
    *,
    goal_id: str = "g1",
    label: str = "Test",
    goal_type: str = "Wiederkehrende_Ausgabe",
    target_amount_rappen: int | None = None,
    start_date: str | None = None,
    target_date: str | None = None,
    frequency: str | None = None,
    is_ongoing: int = 0,
    hardness: str = "Primaer",
    rank: int = 2,
    weight_bps: int | None = None,
    value_mode: str = "nominal",
    goal_scope: str = "Beratungsvermoegen",
    pension_pillar: str | None = None,
    horizon_years: int | None = None,
    target_wealth_rappen: int | None = None,
    target_return_bps: int | None = None,
):
    """Mock-Goal als SimpleNamespace (kein DB-Objekt noetig) -- gleiches
    Muster wie tests/test_optimizer_goal_liabilities.py::_make_goal."""
    return SimpleNamespace(
        id=goal_id,
        label=label,
        goal_type=goal_type,
        target_amount_rappen=target_amount_rappen,
        target_wealth_rappen=target_wealth_rappen,
        target_return_bps=target_return_bps,
        horizon_years=horizon_years,
        target_date=target_date,
        start_date=start_date,
        is_ongoing=is_ongoing,
        frequency=frequency,
        hardness=hardness,
        rank=rank,
        weight_bps=weight_bps,
        value_mode=value_mode,
        goal_scope=goal_scope,
        pension_pillar=pension_pillar,
    )


CHF = 100  # 1 CHF == 100 Rappen (integer sub-unit convention of this codebase)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RECURRENCE-SCHEDULE-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_annual_goal_dec31_to_jan1_books_single_occurrence_not_two():
    """Audit Repro 2: annual CHF100 goal, start=2026-12-31, end=2027-01-01.

    One calendar day elapses between start and end, so exactly one annual
    occurrence of CHF100 should be booked. The current implementation
    treats the Dec-31 -> Jan-1 rollover as spanning two distinct calendar
    years (2026 and 2027) and books CHF100 into *each* of them, totalling
    CHF200.
    """
    goal = _make_goal(
        goal_type="Wiederkehrende_Ausgabe",
        target_amount_rappen=100 * CHF,  # CHF100/year
        frequency="jaehrlich",
        start_date="2026-12-31",
        target_date="2027-01-01",
    )

    liab = goal_to_liability(goal, horizon_years=10)

    total_booked = sum(liab.liability_path_rappen)

    assert total_booked == 100 * CHF, (
        f"expected a single CHF100 occurrence (10000 Rappen), got "
        f"{total_booked} Rappen -- Dec31/Jan1 boundary is being double-booked"
    )
    assert liab.target_amount_rappen == 100 * CHF


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RECURRENCE-SCHEDULE-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_monthly_goal_dec30_to_jan1_does_not_double_annualized_total():
    """Audit Repro 2 (monthly variant): CHF100/month goal, start=2026-12-30,
    end=2027-01-01 -- same Dec/Jan calendar-year boundary as the annual case.

    One year's worth of monthly contributions (12 x CHF100 = CHF1'200)
    should be booked once. The calendar-label duration bug instead spans
    the Dec-30/Jan-1 rollover as two calendar years and books the full
    annualized CHF1'200 into each of them, totalling CHF2'400.
    """
    goal = _make_goal(
        goal_type="Wiederkehrende_Ausgabe",
        target_amount_rappen=100 * CHF,  # CHF100/month
        frequency="monatlich",
        start_date="2026-12-30",
        target_date="2027-01-01",
    )

    liab = goal_to_liability(goal, horizon_years=10)

    total_booked = sum(liab.liability_path_rappen)

    assert total_booked == 1200 * CHF, (
        f"expected one year of monthly contributions (CHF1'200 == "
        f"120000 Rappen), got {total_booked} Rappen"
    )
    assert total_booked != 2400 * CHF, (
        "liability must not double-book the Dec/Jan calendar-year boundary "
        "to CHF2'400"
    )
