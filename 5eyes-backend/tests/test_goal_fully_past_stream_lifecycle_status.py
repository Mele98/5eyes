"""Red test for GOAL-PAST-DATE-LIFECYCLE-001 (round 38).

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md,
finding GOAL-PAST-DATE-LIFECYCLE-001, "Repro 3": a recurring-expense goal
whose entire window (start_date..target_date) lies fully in the past relative
to ``as_of`` must contribute ZERO future liability. Today (as_of) is
2026-10-03 in this environment, and the goal window below (2020-01-01 ..
2022-12-31) is fully elapsed.

Current bug: ``_resolve_target_year_index`` clamps the calendar-year
calculation with ``max(1, calendar_years_until(anchor))``. For a past anchor,
``calendar_years_until`` correctly returns 0, but the ``max(1, ...)`` floor
silently reinterprets "this already ended" as "this starts next year",
reactivating a dead recurring-expense stream as if it starts now. Combined
with the goal's own 3-year span (2020..2022), this re-materializes as
3 brand-new full-year outflows of CHF 1'200 each in liability_path_rappen
years 1-3 (``[120000, 120000, 120000, 0, ...]`` in Rappen), instead of the
correct all-zero path.
"""
from __future__ import annotations

import sys
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


def _make_goal(
    *,
    goal_id: str = "g-fully-past",
    label: str = "Fully past recurring expense",
    goal_type: str = "Wiederkehrende_Ausgabe",
    target_amount_rappen: int = 100_00,  # CHF 100 monthly
    frequency: str = "monatlich",
    start_date: str = "2020-01-01",
    target_date: str = "2022-12-31",
    is_ongoing: int = 0,
    horizon_years: int | None = None,
    hardness: str = "Primaer",
    rank: int = 2,
    weight_bps: int | None = None,
    value_mode: str = "nominal",
    goal_scope: str = "Beratungsvermoegen",
):
    """Mock Goal as SimpleNamespace, mirroring the shape used by the
    production service (no DB object needed)."""
    return SimpleNamespace(
        id=goal_id,
        label=label,
        goal_type=goal_type,
        target_amount_rappen=target_amount_rappen,
        target_wealth_rappen=None,
        target_return_bps=None,
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
        pension_pillar=None,
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-PAST-DATE-LIFECYCLE-001 — round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_fully_past_recurring_stream_contributes_zero_future_liability():
    """Repro 3 (Pflichttest 2): monthly CHF100 stream 2020-01-01..2022-12-31,
    fully in the past as of 2026-10-03, must NOT reactivate as 3 new
    full-year future payments of CHF 1'200 each.
    """
    goal = _make_goal()

    liability = goal_to_liability(goal, horizon_years=10)

    # A fully-expired stream must not reappear as future outflows.
    assert liability.liability_path_rappen == [0] * 10, (
        "Fully past stream must contribute zero future liability, got "
        f"{liability.liability_path_rappen!r} (bug reactivates it as "
        "[120000, 120000, 120000, 0, ...])"
    )
    assert liability.target_amount_rappen == 0
