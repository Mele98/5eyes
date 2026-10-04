"""Red test for GOAL-RECURRENCE-SCHEDULE-001 (round 38).

Audit: docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
Finding GOAL-RECURRENCE-SCHEDULE-001, "Repro 2": a recurring-expense goal
(CHF 100/Jahr) whose start_date/target_date straddle a calendar-year boundary
by a single real-world day (Dec 31 -> Jan 1) is miscounted by
``_outflow_duration_years()`` in services/optimizer/goal_liabilities.py as
spanning TWO outflow years (naive ``target_date.year - start_date.year + 1``),
instead of the single real payment the one-day span represents.

End-to-end through the real production entry points
(``goal_to_liability`` -> ``simulate_wealth_paths`` -> ``goal_probability_per_path``),
this phantom second-year outflow drives an otherwise fully funded wealth path
negative and collapses the goal's success probability from the canonical
P == 1 down to P == 0.

Canonical (bug-free) repro, CHF 150 initial wealth, zero returns, zero other
cashflow:
    liability path: [100, 0, 0]
    wealth path:     [150, 50, 50, 50]
    P == 1

Current (buggy) behaviour:
    liability path: [100, 100, 0]
    wealth path:     [150, 50, -50, -50]
    P == 0
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
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

from services.optimizer.goal_liabilities import goal_to_liability
from services.optimizer.objective import goal_probability_per_path
from services.optimizer.scenario_engine import (
    N_BUCKETS,
    ScenarioInputs,
    build_scenario_paths,
    simulate_wealth_paths,
)


def _make_recurring_goal(*, start_date: str, target_date: str) -> SimpleNamespace:
    """Minimal Wiederkehrende_Ausgabe-Goal-Mock (kein DB-Objekt noetig),
    konsistent zu ``_make_goal`` in tests/test_optimizer_goal_liabilities.py."""
    return SimpleNamespace(
        id="repro2",
        label="CHF150-Repro",
        goal_type="Wiederkehrende_Ausgabe",
        target_amount_rappen=100,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=None,
        target_date=target_date,
        start_date=start_date,
        is_ongoing=0,
        frequency=None,
        hardness="Primaer",
        rank=2,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=None,
        success_probability_min_x100=None,
    )


def _zero_return_paths(*, horizon_years: int, n_paths: int) -> np.ndarray:
    """return-factor == 1.0 ueberall (= 0% Rendite), identity-Korrelation."""
    inputs = ScenarioInputs(
        mu_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        sigma_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        skew_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        excess_kurt_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        cholesky=np.eye(N_BUCKETS),
    )
    return build_scenario_paths(
        inputs, horizon_years=horizon_years, n_paths=n_paths, seed=42,
    )


@pytest.mark.xfail(
    strict=True,
    reason="GOAL-RECURRENCE-SCHEDULE-001 — round 38 red test, see docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md",
)
def test_chf150_repro_matches_canonical_p_equals_one():
    """Audit Repro 2 (GOAL-RECURRENCE-SCHEDULE-001), end-to-end through the
    real production entry points: goal_to_liability -> simulate_wealth_paths
    -> goal_probability_per_path."""
    horizon_years = 3
    initial_wealth_rappen = 150

    # start_date = next upcoming Dec 31, target_date = the following Jan 1 —
    # one real elapsed day, deliberately straddling a calendar-year boundary.
    today = date.today()
    year_end_year = today.year if date(today.year, 12, 31) > today else today.year + 1
    start_date = date(year_end_year, 12, 31).isoformat()
    target_date = date(year_end_year + 1, 1, 1).isoformat()

    goal = _make_recurring_goal(start_date=start_date, target_date=target_date)
    liability = goal_to_liability(goal, horizon_years=horizon_years)

    # Canonical: a single real-world day of elapsed time is one payment, not two.
    assert liability.liability_path_rappen == [100, 0, 0]

    weights = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
    return_paths = _zero_return_paths(horizon_years=horizon_years, n_paths=1)
    wealth_paths = simulate_wealth_paths(
        initial_wealth_rappen=initial_wealth_rappen,
        weights=weights,
        return_paths=return_paths,
        cashflow_series_rappen=[0] * horizon_years,
        liability_path_rappen=liability.liability_path_rappen,
    )

    assert wealth_paths[0].tolist() == [150, 50, 50, 50]

    probability = goal_probability_per_path(
        wealth_paths, liability, initial_wealth_rappen,
    )
    assert int(probability[0]) == 1
