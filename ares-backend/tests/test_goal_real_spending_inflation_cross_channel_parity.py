"""Red test: GOAL-REAL-SPENDING-INFLATION-PARITY-001.

Round 40 audit finding (doc not committed in this worktree):
``services/optimizer/goal_liabilities.py`` (``_is_real_value_mode`` +
``_inflate_at_year``) inflates a ``value_mode='real'`` EXPENSE goal
(Einmalige_Ausgabe / Wiederkehrende_Ausgabe / Pensionsausgabe) per year with
the CMA inflation series before handing it to the optimizer as a Liability.

Other, independent consumers of the SAME goal data do NOT apply this
inflation to expense-type goals -- they only inflate wealth-type goals
(Vermoegensziel / Kapitalerhalt via ``_goal_target_wealth_rappen`` in
``services/portfolio_engine_payload.py``). One such consumer is the Reserve
calculation, ``_goal_reserve_for_goal`` in
``services/portfolio_engine_reserve.py`` (re-exported from
``services.portfolio_engine``): it reads ``goal.target_amount_rappen``
verbatim with no ``value_mode`` check at all.

This test constructs ONE real one-off expense goal (10'000 Rappen, due in
exactly 2 calendar years) with a 10%/10% CMA inflation series and 11'000
Rappen of available wealth -- the exact repro numbers from the audit -- and
runs it through BOTH real production functions (no mocking):

  1. Optimizer path:  goal_to_liability()  ->  goal_probability_per_path()
     Inflates 10'000 -> 12'100 Rappen. 11'000 available < 12'100 needed:
     NOT achievable (probability 0).

  2. Reserve path:    _goal_reserve_for_goal()
     Uses the raw 10'000 Rappen (no inflation applied). 11'000 available >=
     10'000 needed: achievable.

Same goal, same inflation assumptions, same available wealth -- opposite
achievability verdicts. The final parity assertion captures this and is
expected to fail until the two channels are reconciled.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Mapper-Init: alle Models laden damit relationships sich gegenseitig finden
# (gleiche Reihenfolge wie tests/test_audit_z2_goal_reserve.py).
from database import Base  # noqa: F401
from models import allocation as _alloc_models  # noqa: F401
from models import clients as _client_models  # noqa: F401
from models import mandates as _mandate_models  # noqa: F401
from models import profiling as _prof_models  # noqa: F401
from models import review as _review_models  # noqa: F401
from models import snapshots as _snap_models  # noqa: F401
from models import users as _user_models  # noqa: F401
from models import wealth as _wealth_models  # noqa: F401
from sqlalchemy.orm import configure_mappers

configure_mappers()

from models.wealth import Goal
from services.optimizer.goal_liabilities import goal_to_liability
from services.optimizer.objective import goal_probability_per_path
from services.portfolio_engine import _goal_reserve_for_goal


# Audit repro numbers: 10% p.a. CMA inflation for both years, 2-year horizon,
# 11'000 Rappen of wealth available to fund this single goal.
_INFLATION_SERIES_BPS = [1000, 1000]
_AVAILABLE_WEALTH_RAPPEN = 11_000
_HORIZON_YEARS = 2
_RAW_TARGET_RAPPEN = 10_000


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _make_real_expense_goal() -> Goal:
    """Real one-off expense goal, 10'000 Rappen due in exactly 2 calendar years."""
    today = datetime.date.today()
    target_date = today.replace(year=today.year + 2)
    return Goal(
        id="g-real-expense-1",
        mandate_id="m-1",
        client_id="c-1",
        goal_family="Konsum",
        goal_type="Einmalige_Ausgabe",
        label="Reale Einmalausgabe (Kueche)",
        rank=1,
        weight_bps=10_000,
        goal_scope="Beratungsvermoegen",
        value_mode="real",
        target_amount_rappen=_RAW_TARGET_RAPPEN,
        target_date=target_date.isoformat(),
        is_ongoing=0,
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-REAL-SPENDING-INFLATION-PARITY-001 — round 40 red test, see audit "
        "2026-10-04-goal-value-mode-inflation-and-publication-parity-audit.md "
        "(not committed in this repo)"
    ),
)
def test_optimizer_and_reserve_consumers_disagree_on_real_expense_goal_achievability():
    """Same real-mode expense goal + same inflation + same wealth must agree
    on achievability across independent consumers. Currently they do not."""
    goal = _make_real_expense_goal()

    # --- Consumer 1: Optimizer path (services/optimizer/goal_liabilities.py
    # dispatches to _build_einmalige_ausgabe, which inflates for
    # value_mode='real'; services/optimizer/objective.py evaluates the
    # resulting Liability against a wealth path).
    liability = goal_to_liability(
        goal,
        horizon_years=_HORIZON_YEARS,
        inflation_series_bps=_INFLATION_SERIES_BPS,
    )
    assert liability.target_amount_rappen == 12_100, (
        "optimizer path should inflate 10000 * 1.10 * 1.10 = 12100 Rappen, "
        f"got {liability.target_amount_rappen}"
    )

    # Deterministic single-path wealth: starts at available wealth, 0% growth,
    # minus the (inflated) liability outflow due in year 2.
    wealth_year0 = float(_AVAILABLE_WEALTH_RAPPEN)
    wealth_year1 = wealth_year0 - liability.liability_path_rappen[0]
    wealth_year2 = wealth_year1 - liability.liability_path_rappen[1]
    wealth_paths = np.array([[wealth_year0, wealth_year1, wealth_year2]])

    optimizer_probability = goal_probability_per_path(
        wealth_paths, liability, _AVAILABLE_WEALTH_RAPPEN,
    )
    optimizer_achievable = bool(optimizer_probability[0])
    assert optimizer_achievable is False, (
        "optimizer path should report the goal as NOT achievable once "
        f"inflated to {liability.target_amount_rappen} against "
        f"{_AVAILABLE_WEALTH_RAPPEN} available wealth"
    )

    # --- Consumer 2: Reserve path (services/portfolio_engine_reserve.py,
    # re-exported from services.portfolio_engine). Reads
    # goal.target_amount_rappen RAW -- no value_mode check at all.
    reserve_needed_rappen = _goal_reserve_for_goal(goal)
    assert reserve_needed_rappen == _RAW_TARGET_RAPPEN, (
        "Reserve path is documented to ignore value_mode='real' for expense "
        f"goals (raw amount expected); got {reserve_needed_rappen}"
    )
    reserve_achievable = _AVAILABLE_WEALTH_RAPPEN >= reserve_needed_rappen
    assert reserve_achievable is True, (
        "Reserve path should consider the goal funded against its "
        f"un-inflated {reserve_needed_rappen}-Rappen requirement"
    )

    # --- Parity assertion: both independent consumers evaluate the IDENTICAL
    # economic input (same goal, same CMA inflation series, same available
    # wealth) and must reach the same achievability verdict.
    assert optimizer_achievable == reserve_achievable, (
        "Cross-channel parity violated for real-mode expense goal: optimizer "
        f"(inflation-adjusted, needs {liability.target_amount_rappen} Rappen) "
        f"says achievable={optimizer_achievable}, but Reserve path (raw, "
        f"needs {reserve_needed_rappen} Rappen) says "
        f"achievable={reserve_achievable} for the identical "
        f"{_AVAILABLE_WEALTH_RAPPEN}-Rappen available wealth."
    )
