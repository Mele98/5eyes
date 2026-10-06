"""Red test for GOAL-FUNDING-PRIORITY-001 (Kontrollrunde 37).

Audit finding: the optimizer has no goal-funding priority mechanism — every
spending goal's outflow is subtracted unconditionally from the shared wealth
path (services.optimizer.goal_liabilities.aggregate_liability_path) before
any goal's achievability is evaluated. The opt-in hardness-weighting mode
(OPTIMIZER_GOAL_WEIGHTING=hardness) does NOT repair this: it only rescales
the shortfall contribution inside the primary MSE objective
(services.optimizer.objective.shortfall_objective via
_effective_hardness_weight), while the chance-constraint penalty
(services.optimizer.objective.chance_constraint_penalty) never reads
OPTIMIZER_GOAL_WEIGHTING at all and operates on the exact same wealth path
in both modes. So a hard goal that is starved by an opportunistic goal's
outflow stays at 0% achievability, with the identical chance-penalty value,
in both equal and hardness weighting modes.

Scenario (same two-goal setup as the sibling repro task
round47-funding-priority-repro1, built independently from scratch here):
  initial wealth CHF 100, return factor 1.0 (no growth)
  Goal A: Vermoegensziel, Hart, rank 1, target CHF 90, due year 2
  Goal B: Einmalige_Ausgabe, Opportunistisch, rank 5, amount CHF 20, due year 1

See docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md.
"""
from __future__ import annotations

import sys
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
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)

configure_mappers()

from services.optimizer.goal_liabilities import (
    GoalLiability,
    aggregate_liability_path,
    goal_to_liability,
)
from services.optimizer.objective import chance_constraint_penalty
from services.optimizer.scenario_engine import simulate_wealth_paths

HORIZON_YEARS = 2
INITIAL_WEALTH_RAPPEN = 100_00  # CHF 100
N_PATHS = 50


def _goal_a_vermoegensziel_hart() -> SimpleNamespace:
    """Hard wealth goal, rank 1, target CHF 90 due year 2."""
    return SimpleNamespace(
        id="goal-a-hart",
        label="Vermoegensziel Hart",
        goal_type="Vermoegensziel",
        target_wealth_rappen=90_00,  # CHF 90
        target_amount_rappen=None,
        target_return_bps=None,
        horizon_years=HORIZON_YEARS,
        target_date=None,
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Hart",
        rank=1,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=None,
        success_probability_min_x100=None,
    )


def _goal_b_einmalige_ausgabe_opportunistisch() -> SimpleNamespace:
    """Opportunistic one-off spending goal, rank 5, amount CHF 20 due year 1."""
    return SimpleNamespace(
        id="goal-b-opportunistisch",
        label="Einmalige Ausgabe Opportunistisch",
        goal_type="Einmalige_Ausgabe",
        target_wealth_rappen=None,
        target_amount_rappen=20_00,  # CHF 20
        target_return_bps=None,
        horizon_years=1,
        target_date=None,
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Opportunistisch",
        rank=5,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=None,
        success_probability_min_x100=None,
    )


def _build_liabilities() -> tuple[GoalLiability, GoalLiability]:
    goal_a = goal_to_liability(_goal_a_vermoegensziel_hart(), horizon_years=HORIZON_YEARS)
    goal_b = goal_to_liability(
        _goal_b_einmalige_ausgabe_opportunistisch(), horizon_years=HORIZON_YEARS
    )
    assert goal_a.target_kind == "wealth_at_t"
    assert goal_a.target_year_index == 2
    assert goal_a.target_amount_rappen == 90_00
    assert goal_b.target_kind == "cashflow_in_year"
    assert goal_b.liability_path_rappen == [20_00, 0]
    return goal_a, goal_b


def _run_scenario() -> tuple[float, float, list[dict]]:
    """Builds the shared wealth path via real production functions and
    returns (goal_a_probability, goal_a_chance_penalty, achievability_rows).

    Uses the exact same unconditional-subtraction call path the audit
    describes: aggregate_liability_path() sums ALL goal outflows (hard and
    opportunistic alike) BEFORE any per-goal evaluation happens, and that
    aggregate is what simulate_wealth_paths() subtracts from the shared
    wealth path.
    """
    goal_a, goal_b = _build_liabilities()
    liabilities = [goal_a, goal_b]

    liability_path = aggregate_liability_path(liabilities, horizon_years=HORIZON_YEARS)
    assert liability_path == [20_00, 0]

    # return factor 1.0 == no growth, no volatility: weight everything on a
    # single bucket so the dot-product is exactly 1.0 every year/path.
    weights = np.array([0.0, 0.0, 0.0, 0.0, 1.0])
    return_paths = np.ones((N_PATHS, HORIZON_YEARS, 5), dtype=np.float64)

    wealth_paths = simulate_wealth_paths(
        initial_wealth_rappen=INITIAL_WEALTH_RAPPEN,
        weights=weights,
        return_paths=return_paths,
        cashflow_series_rappen=[0, 0],
        liability_path_rappen=liability_path,
    )
    # Sanity: deterministic path, opportunistic Goal B's outflow is taken
    # unconditionally before Goal A (due a year later) is ever evaluated.
    assert np.all(wealth_paths[:, 1] == 80_00)  # 100 - 20 (Goal B outflow)
    assert np.all(wealth_paths[:, 2] == 80_00)  # no growth, no further outflow

    penalty, rows = chance_constraint_penalty(
        wealth_paths,
        liabilities,
        initial_value_rappen=INITIAL_WEALTH_RAPPEN,
    )
    goal_a_row = next(row for row in rows if row["goal_id"] == "goal-a-hart")
    return float(goal_a_row["probability"]), float(penalty), rows


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-FUNDING-PRIORITY-001 -- round 47 red test (hardness mode does "
        "not repair funding order), see audit "
        "docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md"
    ),
)
def test_hardness_mode_does_not_protect_hard_goal_from_opportunistic_outflow(monkeypatch):
    # --- Mode 1: equal weighting (default, OPTIMIZER_GOAL_WEIGHTING unset) ---
    monkeypatch.delenv("OPTIMIZER_GOAL_WEIGHTING", raising=False)
    probability_equal, penalty_equal, _rows_equal = _run_scenario()

    assert probability_equal == pytest.approx(0.0)
    assert penalty_equal == pytest.approx(640_000.0)

    # --- Mode 2: opt-in hardness weighting ---
    monkeypatch.setenv("OPTIMIZER_GOAL_WEIGHTING", "hardness")
    probability_hardness, penalty_hardness, _rows_hardness = _run_scenario()

    assert probability_hardness == pytest.approx(0.0)
    assert penalty_hardness == pytest.approx(640_000.0)

    # THE RED ASSERTION: hardness mode is supposed to protect the hard Goal A
    # by giving it funding priority over the opportunistic Goal B. Instead
    # the wealth path (and therefore Goal A's achievability and chance
    # penalty) is bit-for-bit identical in both modes -- hardness weighting
    # provides zero protection against the underlying funding-order bug.
    assert probability_hardness > probability_equal, (
        "Expected hardness mode to raise Goal A's achievability above the "
        "equal-weighting baseline (funding priority for the hard goal), but "
        f"both modes yield the identical probability={probability_equal!r} "
        f"and chance penalty={penalty_equal!r} -- hardness weighting does "
        "not change the funding order at all."
    )
