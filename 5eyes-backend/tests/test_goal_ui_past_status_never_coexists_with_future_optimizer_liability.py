"""Red test for GOAL-PAST-DATE-LIFECYCLE-001 (round 38).

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md,
finding GOAL-PAST-DATE-LIFECYCLE-001.

Two independent code paths decide what "this goal's date is in the past"
means for the SAME goal/date input, and they disagree:

- services/pdf/components/goal_classification.py (mirrors the React
  reporting/src/lib/goalClassification.ts logic) classifies a goal as
  GOAL_STATUS_PAST whenever its target_date's year is before the Monte-
  Carlo time_axis' first year. A "past" goal is meant to be excluded from
  forward-looking planning -- the UI renders it as a historical goal, not
  as something the optimizer should still be funding.

- services/optimizer/goal_liabilities.py resolves the goal's evaluation
  year via _resolve_target_year_index(), which anchors on
  calendar_years_until(). calendar_years_until() returns 0 for any date
  on or before today, and _resolve_target_year_index() then clamps that
  with max(1, ...) -- silently promoting a goal whose real-world date has
  already passed into "evaluate/pay out in year 1" (i.e. next year, a
  FUTURE optimizer year), instead of excluding it the way the
  classification helper does.

Net effect: for one and the same goal (identical target_date, identical
target_amount_rappen), the PDF/report UI tells the advisor "this goal is
in the past, ignore it" while the optimizer still carries a nonzero
future liability for exactly that goal. This test encodes the invariant
that must hold: a goal classified as "past" must never simultaneously
produce a nonzero liability in a future optimizer year.
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

from database import Base  # noqa: E402, F401
from models import (  # noqa: E402, F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)

configure_mappers()

from services.pdf.components.goal_classification import (  # noqa: E402
    GOAL_STATUS_PAST,
    classify_goals,
)
from services.optimizer.goal_liabilities import goal_to_liability  # noqa: E402


HORIZON_YEARS = 10


def _make_liability_goal(*, goal_type: str, target_date: str, target_amount_rappen: int):
    """Mock-Goal as SimpleNamespace, mirroring test_optimizer_goal_liabilities.py."""
    return SimpleNamespace(
        id="g1",
        label="Past-dated goal",
        goal_type=goal_type,
        target_amount_rappen=target_amount_rappen,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=HORIZON_YEARS,
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


def _classification_status_for(*, target_date: str, target_amount_rappen: int) -> str:
    """Run the SAME goal/date input through the PDF classification helper."""
    today = date.today()
    time_axis = [str(today.year + offset) for offset in range(HORIZON_YEARS)]
    flat_path = [1_000_000.0] * HORIZON_YEARS
    mc = {
        "time_axis": time_axis,
        "p5": flat_path,
        "p50": flat_path,
        "p75": flat_path,
    }
    goals = [{
        "goal_id": "g1",
        "target_date": target_date,
        "target_amount_rappen": target_amount_rappen,
    }]
    [result] = classify_goals(goals, mc)
    return result["status"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-PAST-DATE-LIFECYCLE-001 — round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
@pytest.mark.parametrize(
    "goal_type",
    ["Einmalige_Ausgabe", "Wiederkehrende_Ausgabe"],
)
def test_past_classified_goal_never_has_future_optimizer_liability(goal_type):
    # Clearly past relative to "today" in any plausible environment clock,
    # yet well within the classification's MC time_axis horizon so the
    # "past" branch (target_year < start_year) is exercised, not "unknown".
    past_target_date = (date.today() - timedelta(days=800)).isoformat()
    target_amount_rappen = 500_000

    status = _classification_status_for(
        target_date=past_target_date,
        target_amount_rappen=target_amount_rappen,
    )
    assert status == GOAL_STATUS_PAST, (
        "Precondition failed: expected the classification helper to mark "
        f"this goal as past-dated, got {status!r} instead."
    )

    goal = _make_liability_goal(
        goal_type=goal_type,
        target_date=past_target_date,
        target_amount_rappen=target_amount_rappen,
    )
    liability = goal_to_liability(goal, horizon_years=HORIZON_YEARS)
    has_future_liability = sum(liability.liability_path_rappen) > 0

    assert not (status == GOAL_STATUS_PAST and has_future_liability), (
        "Cross-channel contradiction: goal_classification.py reports "
        f"status={status!r} (past, excluded from forward planning) for this "
        "goal/date input, but goal_liabilities.py still produced a nonzero "
        f"future liability path ({liability.liability_path_rappen!r}) for the "
        "identical goal -- GOAL-PAST-DATE-LIFECYCLE-001."
    )
