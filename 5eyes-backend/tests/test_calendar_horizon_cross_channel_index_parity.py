"""Red test for GOAL-CALENDAR-HORIZON-PARITY-001 (round 38).

Fixed cross-channel harness: as_of=2024-01-01 (a leap year), target_date=
2025-01-01 -- an EXACT 1-calendar-year gap. Four independent channels
resolve this goal's target-year index differently, because two of them
derive the index from raw day counts instead of calendar-year arithmetic:

  - Router (routers/wealth.py::_goal_horizon_from_date) and
  - Main-MC (services/portfolio_engine_mc_simulation.py::_year_index_for_goal,
    via services/portfolio_engine_payload.py::_goal_projection_years)

both compute `max(1, (delta_days + 364) // 365)`. 2024 is a leap year, so
the exact 1-year gap spans 366 days: `(366 + 364) // 365 == 2`. The
day-count formula rounds an exact calendar anniversary UP to 2 years.

  - Optimizer (services/optimizer/goal_liabilities.py::goal_to_liability,
    via services/calendar_horizon.py::calendar_years_until) and
  - PDF/React (services/pdf/components/goal_classification.py::classify_
    goals, plain `target_year - start_year`)

both correctly resolve the gap to 1 year.

Fixed wealth path (rappen-scaled for readability): t0=100, t1=50, t2=150,
target=100.
  - index 1 (optimizer, PDF/React) -> wealth=50  < target  -> FAILURE
  - index 2 (router, main-MC)      -> wealth=150 >= target -> SUCCESS

All four channels describe the SAME goal for the SAME client and MUST
agree on both the resolved target-year index and the resulting
success/failure verdict. They currently split into two incompatible
camps. This is GOAL-CALENDAR-HORIZON-PARITY-001; see
docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
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

from sqlalchemy.orm import configure_mappers
from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from routers import wealth as wealth_router
import services.calendar_horizon as calendar_horizon
import services.portfolio_engine_payload as portfolio_engine_payload
from services.optimizer.goal_liabilities import goal_to_liability
from services.portfolio_engine_mc_simulation import _year_index_for_goal
from services.pdf.components.goal_classification import (
    GOAL_STATUS_NICHT_ERREICHBAR,
    classify_goals,
)


AS_OF = date(2024, 1, 1)  # leap year -- a true 1-year gap spans 366 days
TARGET_DATE = date(2025, 1, 1)  # exact calendar anniversary of AS_OF
WEALTH_PATH = [100, 50, 150]  # index 0 (as_of) .. index 2
TARGET_AMOUNT_RAPPEN = 100


class _FixedToday(date):
    """`date` subclass whose `.today()` is pinned to AS_OF.

    All three Python channels resolve "now" internally via `date.today()`
    rather than threading an explicit as_of through from the caller -- this
    pins them to the audit harness's fixed valuation date.
    """

    @classmethod
    def today(cls):
        return AS_OF


@pytest.fixture
def pinned_today(monkeypatch):
    monkeypatch.setattr(wealth_router, "date", _FixedToday)
    monkeypatch.setattr(portfolio_engine_payload, "date", _FixedToday)
    monkeypatch.setattr(calendar_horizon, "date", _FixedToday)


def _make_goal() -> SimpleNamespace:
    """Mock-Goal als SimpleNamespace (kein DB-Objekt noetig), analog zu
    tests/test_optimizer_goal_liabilities.py::_make_goal."""
    return SimpleNamespace(
        id="goal-parity-1",
        label="Vermoegensziel Parity",
        goal_type="Vermoegensziel",
        target_amount_rappen=None,
        target_wealth_rappen=TARGET_AMOUNT_RAPPEN,
        target_return_bps=None,
        horizon_years=None,
        target_date=TARGET_DATE.isoformat(),
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=None,
        success_probability_min_x100=None,
    )


def _router_index(goal: SimpleNamespace) -> int:
    """Router channel: routers/wealth.py derives the goal horizon (and thus
    its target-year index) from the raw calendar-day distance."""
    target = date.fromisoformat(goal.target_date)
    return wealth_router._goal_horizon_from_date(target)


def _optimizer_index(goal: SimpleNamespace, horizon_years: int) -> int:
    """Optimizer channel: services/optimizer/goal_liabilities.py, via the
    calendar-aware services.calendar_horizon.calendar_years_until."""
    liability = goal_to_liability(goal, horizon_years=horizon_years)
    return liability.target_year_index


def _main_mc_index(goal: SimpleNamespace, *, start_year: int, horizon_years: int) -> int:
    """Main-MC channel: services/portfolio_engine_mc_simulation.py's
    goal-year resolver used to slice the simulated wealth paths."""
    return _year_index_for_goal(goal, start_year, horizon_years)


def _pdf_react_index_and_status(goal: SimpleNamespace) -> tuple[int, str]:
    """PDF/React channel: services/pdf/components/goal_classification.py
    mirrors the frontend's goalClassification.ts -- plain
    `target_year - start_year`, no day-count arithmetic at all."""
    time_axis = [AS_OF.year + offset for offset in range(len(WEALTH_PATH))]
    mc_payload = {
        "time_axis": time_axis,
        "p5": list(WEALTH_PATH),
        "p50": list(WEALTH_PATH),
        "p75": list(WEALTH_PATH),
    }
    goal_dict = {
        "goal_id": goal.id,
        "target_date": goal.target_date,
        "target_amount_rappen": TARGET_AMOUNT_RAPPEN,
    }
    [result] = classify_goals([goal_dict], mc_payload)
    return result["t_index"], result["status"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-CALENDAR-HORIZON-PARITY-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_cross_channel_target_year_index_and_verdict_parity(pinned_today):
    goal = _make_goal()
    horizon_years = 5
    start_year = AS_OF.year

    router_index = _router_index(goal)
    optimizer_index = _optimizer_index(goal, horizon_years)
    main_mc_index = _main_mc_index(goal, start_year=start_year, horizon_years=horizon_years)
    pdf_index, pdf_status = _pdf_react_index_and_status(goal)

    # Documented status quo (audit harness): router/main-MC overcount the
    # exact 1-calendar-year gap as 2 (leap-year day-count bug); optimizer
    # and PDF/React correctly resolve it to 1.
    assert router_index == 2
    assert main_mc_index == 2
    assert optimizer_index == 1
    assert pdf_index == 1

    def verdict(index: int) -> bool:
        return WEALTH_PATH[index] >= TARGET_AMOUNT_RAPPEN

    router_success = verdict(router_index)
    main_mc_success = verdict(main_mc_index)
    optimizer_success = verdict(optimizer_index)
    pdf_success = pdf_status != GOAL_STATUS_NICHT_ERREICHBAR

    assert router_success is True
    assert main_mc_success is True
    assert optimizer_success is False
    assert pdf_success is False

    # The actual parity requirement that must hold once
    # GOAL-CALENDAR-HORIZON-PARITY-001 is fixed: every channel agrees on
    # both the resolved index and the resulting verdict for the same goal.
    all_indexes = {router_index, optimizer_index, main_mc_index, pdf_index}
    all_verdicts = {router_success, main_mc_success, optimizer_success, pdf_success}
    assert len(all_indexes) == 1, f"Index-Divergenz zwischen Kanaelen: {all_indexes}"
    assert len(all_verdicts) == 1, f"Verdict-Divergenz zwischen Kanaelen: {all_verdicts}"
