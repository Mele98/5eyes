"""Red test for GOAL-CALENDAR-HORIZON-PARITY-001 (round 38).

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
(this path does not exist in this worktree's git history -- confirmed via
Glob/git log --all; derived directly from reading
services/portfolio_engine.py::_compute_input_snapshot_hash and
services/optimizer/goal_liabilities.py, and from empirically running both
before writing assertions; sibling to
test_calendar_horizon_replay_bytewise_stable_across_days.py, which
demonstrates the same underlying as_of gap from the liability side).

``_compute_input_snapshot_hash()`` (services/portfolio_engine.py, used to
detect "does this allocation need recomputing") hashes every raw Goal field
that participates in the strategy's economics -- including `target_date`
and `start_date` -- but has NO parameter for a valuation date / as_of at
all. Its result is therefore a pure function of the stored raw fields,
independent of which real calendar day it was computed on.

`goal_liabilities.goal_to_liability()`, however, silently resolves a goal's
target-year index relative to `date.today()` (see the replay-stability
sibling test). For a goal sitting exactly on a calendar-anniversary
boundary, that means two runs computed on two different real days can
resolve DIFFERENT economic liabilities for IDENTICAL raw goal data --
while `_compute_input_snapshot_hash()` returns the exact same hash both
times, because it never saw a valuation date to begin with. The hash
therefore cannot be trusted as a "nothing economically relevant changed"
signal; a stale-allocation detector keyed on this hash would wrongly skip
recomputation after the valuation date advances past a goal's anniversary.
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
from services.portfolio_engine import _compute_input_snapshot_hash  # noqa: E402

# Same boundary dates as the replay-stability sibling test: target_date sits
# exactly one day past DAY_ONE's 1-year anniversary, and exactly ON
# DAY_TWO's 1-year anniversary -- verified empirically to flip
# goal_to_liability()'s resolved target_year_index from 2 to 1.
DAY_ONE = date(2026, 10, 4)
DAY_TWO = date(2026, 10, 5)
TARGET_DATE = date(2027, 10, 5)


class _PinnedToday(date):
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
        id="g-valuation-date-hash",
        mandate_id="mandate-1",
        client_id="client-1",
        goal_family="Vermoegen",
        goal_type="Vermoegensziel",
        label="Vermoegensziel Valuation-Date Hash",
        rank=1,
        weight_bps=None,
        goal_scope="Beratungsvermoegen",
        value_mode="nominal",
        target_amount_rappen=None,
        target_wealth_rappen=100_00,
        target_return_bps=None,
        success_probability_min_x100=None,
        start_date=None,
        horizon_years=None,
        target_date=TARGET_DATE.isoformat(),
        is_ongoing=0,
        frequency=None,
        hardness="Primaer",
        probability_pct=None,
        pension_pillar=None,
        linked_position_id=None,
        is_active=1,
    )


def _snapshot_hash_for(goal: SimpleNamespace) -> str:
    return _compute_input_snapshot_hash(
        advisory_positions=[],
        cashflows=[],
        goals=[goal],
        advisory_wealth_rappen=0,
        total_wealth_rappen=0,
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-CALENDAR-HORIZON-PARITY-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_valuation_date_change_that_flips_the_liability_also_changes_the_hash(
    pinned_calendar_horizon_today,
):
    """Red: for the IDENTICAL stored goal, moving the valuation date from
    DAY_ONE to DAY_TWO flips the resolved target_year_index (2 -> 1) and
    therefore the economic liability -- this must be visible in
    _compute_input_snapshot_hash()'s result, but it is not: the hash has no
    as_of input at all and stays byte-identical.
    """
    goal = _make_wealth_goal()

    _PinnedToday.pinned = DAY_ONE
    liability_day_one = goal_to_liability(goal, horizon_years=10)
    hash_day_one = _snapshot_hash_for(goal)

    _PinnedToday.pinned = DAY_TWO
    liability_day_two = goal_to_liability(goal, horizon_years=10)
    hash_day_two = _snapshot_hash_for(goal)

    # Precondition: the economic liability genuinely did change between the
    # two valuation dates (otherwise this test would prove nothing).
    assert liability_day_one.target_year_index != liability_day_two.target_year_index

    assert hash_day_one != hash_day_two, (
        "the input snapshot hash stayed identical "
        f"({hash_day_one[:16]}...) across two valuation dates that resolve "
        f"different economic liabilities (target_year_index "
        f"{liability_day_one.target_year_index} vs "
        f"{liability_day_two.target_year_index}) for the same stored goal"
    )


def test_snapshot_hash_is_a_pure_function_of_raw_fields_today(pinned_calendar_horizon_today):
    """Positive control / explicit documentation of the mechanism: calling
    the hash function twice for the identical raw goal, with nothing else
    changed, is already (trivially) deterministic -- the bug is not that
    the hash is flaky, it is that it is blind to valuation date entirely.
    """
    goal = _make_wealth_goal()
    assert _snapshot_hash_for(goal) == _snapshot_hash_for(goal)
