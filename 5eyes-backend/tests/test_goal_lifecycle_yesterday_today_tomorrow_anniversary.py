"""Red test for GOAL-PAST-DATE-LIFECYCLE-001 (round 38), Pflichttest 1.

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md.

`_resolve_target_year_index()` in services/optimizer/goal_liabilities.py does
`years = max(1, calendar_years_until(anchor))` and never threads an explicit
lifecycle decision. `calendar_years_until()` returns 0 for any target_date
on or before the valuation date (today, yesterday, an exact past anniversary),
so all of these collapse to `target_year_index == 1` -- byte-identical to a
goal that is genuinely due in exactly one year. There is no field on
`GoalLiability` (see its dataclass definition) that distinguishes a past/
overdue/due-today goal from a normal future one.

This test documents the required contract (`GOAL-PAST-DATE-LIFECYCLE-001`,
Reparaturvertrag item 1: "Ein Goal besitzt einen typisierten Lifecycle") by
asserting that genuinely past-dated and today-dated one-off/wealth goals are
NOT silently indistinguishable from a true "due in exactly one year" goal.
It currently fails because no such lifecycle marker exists.
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

from sqlalchemy.orm import configure_mappers
from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.optimizer.goal_liabilities import goal_to_liability


def _make_goal(*, goal_type: str, target_date: str, goal_id: str = "g1"):
    return SimpleNamespace(
        id=goal_id,
        label="Lifecycle-Boundary",
        goal_type=goal_type,
        target_amount_rappen=100_00 if goal_type == "Einmalige_Ausgabe" else None,
        target_wealth_rappen=500_000_00 if goal_type == "Vermoegensziel" else None,
        target_return_bps=None,
        horizon_years=10,
        target_date=target_date,
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Primaer",
        rank=2,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
    )


def _has_lifecycle_marker(liab) -> bool:
    """A genuine fix must expose SOME way to tell a past/overdue/today goal
    apart from a normal future-year-1 goal. Today, neither a typed lifecycle
    field nor a distinguishing evaluation_note exists."""
    lifecycle_status = getattr(liab, "lifecycle_status", None)
    if lifecycle_status is not None:
        return True
    note = (liab.evaluation_note or "") if hasattr(liab, "evaluation_note") else ""
    return any(
        marker in note.lower()
        for marker in ("past", "overdue", "ueberfaellig", "vergangen", "faellig heute")
    )


@pytest.mark.parametrize("goal_type", ["Einmalige_Ausgabe", "Vermoegensziel"])
@pytest.mark.parametrize(
    "label,offset_days",
    [
        pytest.param(
            "yesterday", -1,
            marks=pytest.mark.xfail(
                strict=True,
                reason="GOAL-PAST-DATE-LIFECYCLE-001 -- round 38 red test, see "
                "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md",
            ),
        ),
        pytest.param(
            "today", 0,
            marks=pytest.mark.xfail(
                strict=True,
                reason="GOAL-PAST-DATE-LIFECYCLE-001 -- round 38 red test, see "
                "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md",
            ),
        ),
        ("tomorrow", 1),
        pytest.param(
            "one_year_past_anniversary", -365,
            marks=pytest.mark.xfail(
                strict=True,
                reason="GOAL-PAST-DATE-LIFECYCLE-001 -- round 38 red test, see "
                "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md",
            ),
        ),
    ],
)
def test_past_present_future_boundary_needs_explicit_lifecycle(goal_type, label, offset_days):
    today = date.today()
    target = today + timedelta(days=offset_days)
    goal = _make_goal(goal_type=goal_type, target_date=target.isoformat())

    liab = goal_to_liability(goal, horizon_years=10)

    if offset_days > 0:
        # Genuinely future (tomorrow): a real "due in ~1 year" goal. Not the
        # focus of this test, but pinned so the matrix stays self-documenting.
        assert liab.target_year_index == 1
        return

    # yesterday / today / a full year in the past: all genuinely due now or
    # already overdue, not "due in exactly one year". The current clamp
    # `max(1, calendar_years_until(...))` makes them indistinguishable from
    # a true year-1 goal, and GoalLiability carries no lifecycle signal that
    # would let a caller tell the difference.
    assert liab.target_year_index == 1, (
        f"{label}: expected the documented max(1, calendar_years_until(..)) clamp "
        f"to still fire (target_year_index == 1); if this changed, re-check the "
        f"repro against current goal_liabilities.py behaviour."
    )
    assert _has_lifecycle_marker(liab), (
        f"{label}: GOAL-PAST-DATE-LIFECYCLE-001 — a past/overdue/due-today goal "
        f"must expose an explicit lifecycle marker distinguishing it from a goal "
        f"genuinely due in one year. No such marker exists today, so this goal "
        f"is silently reactivated as a normal future year-1 liability."
    )
