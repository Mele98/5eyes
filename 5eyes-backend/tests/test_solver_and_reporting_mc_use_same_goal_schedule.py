"""Round 38 red test for finding GOAL-RECURRENCE-SCHEDULE-001.

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
(finding GOAL-RECURRENCE-SCHEDULE-001): the optimizer-consumer path
(services/optimizer/goal_liabilities.py, `_build_recurring_outflow` /
`_outflow_duration_years`) and the reporting-MC path
(services/portfolio_engine_mc_simulation.py, `_monte_carlo_goal_summary`
~L972-1005, via `_year_index_for_goal` / `_goal_duration_years`) each
independently re-derive "how many years does this recurring goal span, and
which calendar years does the outflow fall in" for the exact same
`Wiederkehrende_Ausgabe` / `Pensionsausgabe` goal. Both apply the same
"annual_amount * inclusive_year_count" shape, but:

- the optimizer anchors its window on `start_date` via
  `calendar_years_until` (anniversary-based, relative to *today*);
- the reporting-MC path anchors its evaluation index on `target_date` via
  `_goal_projection_years` (day-count-based, also relative to *today*,
  but rounded differently).

Because the two anchors (start vs. target) and the two rounding
conventions (anniversary comparison vs. day-count ceiling) are not the
same formula, the optimizer's liability schedule and the schedule implied
by the reporting-MC path's own (index, duration) pair can -- and, for an
ordinary multi-year recurring goal, DO -- disagree about which calendar
years carry the outflow, even when the aggregate total happens to agree.
Solver and reporting must treat the same goal identically; this test pins
that contract down year-by-year, not just on the aggregate total.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from services.optimizer.goal_liabilities import goal_to_liability
from services.portfolio_engine import (
    _annualize_goal_amount,
    _goal_duration_years,
    _goal_probability_factor,
    _year_index_for_goal,
)

HORIZON_YEARS = 15


def _make_recurring_goal() -> SimpleNamespace:
    """A plain, non-conditional annual recurring expense goal.

    start_date is one year out, target_date nine years after that (Jan 1 /
    Dec 31 boundaries, chosen so the window never collides with a leap-day
    edge case). horizon_years=15 is generous on both sides so neither
    consumer's horizon-clamping branch fires -- any divergence we observe
    comes purely from the two independent schedule formulas, not from
    clamping.
    """
    today = date.today()
    start_date = date(today.year + 1, 1, 1)
    target_date = date(today.year + 9, 12, 31)
    return SimpleNamespace(
        id="goal-rec-001",
        label="Jaehrliche Zusatzausgabe",
        goal_type="Wiederkehrende_Ausgabe",
        goal_scope="Beratungsvermoegen",
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        success_probability_min_x100=None,
        probability_pct=100,
        value_mode="nominal",
        target_amount_rappen=1_000_000,
        target_wealth_rappen=0,
        target_return_bps=0,
        start_date=start_date.isoformat(),
        target_date=target_date.isoformat(),
        horizon_years=None,
        is_ongoing=0,
        frequency="jaehrlich",
    )


def _reporting_mc_schedule(
    goal: SimpleNamespace, *, start_year: int, horizon_years: int
) -> tuple[int, list[int]]:
    """Reconstruct the per-year liability schedule implied by the
    reporting-MC path's own building blocks.

    `_monte_carlo_goal_summary` (services/portfolio_engine_mc_simulation.py,
    ~L904 and ~L972-995) does not materialize a liability_path itself -- it
    only computes a cumulative `target` (annual_amount * duration) and
    compares it against the simulated portfolio at a single evaluation
    `index`. To compare it against the optimizer's explicit per-year
    liability_path_rappen, we rebuild the implied path from the EXACT same
    helpers `_monte_carlo_goal_summary` calls internally:
    `_year_index_for_goal` (evaluation index), `_goal_duration_years`
    (duration), `_annualize_goal_amount` and `_goal_probability_factor`
    (per-year amount) -- i.e. the duration years run backwards from the
    evaluation index, mirroring how the reporting path narrates "funded for
    N of M years" against that index.
    """
    index = _year_index_for_goal(goal, start_year, horizon_years)
    duration = _goal_duration_years(goal, start_year, horizon_years)
    annual = int(round(_annualize_goal_amount(goal) * _goal_probability_factor(goal)))
    total = annual * duration
    path = [0] * horizon_years
    window_start = index - duration + 1
    for offset in range(duration):
        year_idx = window_start + offset
        if 1 <= year_idx <= horizon_years:
            path[year_idx - 1] = annual
    return total, path


def test_solver_and_reporting_mc_agree_on_recurring_goal_schedule():
    goal = _make_recurring_goal()
    start_year = date.today().year

    optimizer_liability = goal_to_liability(
        goal, horizon_years=HORIZON_YEARS, inflation_series_bps=None,
    )
    mc_total, mc_path = _reporting_mc_schedule(
        goal, start_year=start_year, horizon_years=HORIZON_YEARS,
    )

    # Both consumers apply "annual_amount * inclusive_year_count" and, for
    # this clean multi-year window, happen to agree on the aggregate total
    # -- the bug is not that magnitudes always diverge, it is that the two
    # independently-derived schedules need not describe the SAME years.
    assert optimizer_liability.target_amount_rappen == mc_total

    # GOAL-RECURRENCE-SCHEDULE-001: solver and reporting-MC must charge the
    # recurring outflow to the identical set of calendar years. Currently
    # the optimizer's start_date-anchored window and the reporting-MC
    # path's target_date-anchored window disagree on placement.
    assert optimizer_liability.liability_path_rappen == mc_path
