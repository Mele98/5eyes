"""Red test for CMA-INFLATION-PATH-DOMAIN-001.

Finding (verified against current develop code): a real-value-mode expense
goal (goal_type="Einmalige_Ausgabe") combined with an administratively
reachable, deeply negative CMA inflation series (-200%/year, i.e.
inflation_series_bps=[-20000, -20000]; see sibling domain-validation
finding for how such a value reaches the engine) causes
``services.optimizer.goal_liabilities.goal_to_liability`` to compute a
NEGATIVE liability for what must always be a non-negative expense:

    amount = max(0, int(goal.target_amount_rappen or 0))   # 10000, guarded
    amount = _inflate_at_year(amount, target_year, inflation_series_bps)
    # cumulative factor = 1 + (-20000/10000) = -1.0 -> amount = -10000
    # the max(0, ...) guard above only protected the PRE-inflation input;
    # the POST-inflation amount is never re-clamped.

That negative liability then poisons two independent downstream production
consumers in services/optimizer/:

1. ``scenario_engine.simulate_wealth_paths`` does
   ``wealth[:, t+1] = grown + cashflow[t] - liability[t]``. Subtracting a
   NEGATIVE liability ADDS money to wealth, i.e. a real spending need
   increases simulated wealth instead of decreasing it.

2. ``objective.goal_probability_per_path`` (via
   ``objective._positive_due_wealth_indices``, which only treats
   ``amount > 0`` entries as "due") never registers the negative outflow as
   a due payment at all, so the goal is trivially reported as achieved on
   every single path (probability=1.0) regardless of actual wealth, and
   ``objective.chance_constraint_penalty`` assigns it zero penalty and
   status "erreichbar" -- a real CHF 100 expense goal is reported as a
   costless, 100%-achievable non-event.

This test exercises the real production functions end-to-end (no mocks)
with a trivial zero-growth, zero-cashflow, zero-initial-wealth scenario and
asserts the behaviour that must hold for ANY expense goal: the liability
must never be negative, wealth must never be increased by paying an
expense, and the goal must not be reported as costlessly achievable.

Audit: 2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md
(not committed in this repo; round 40 red test).
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from services.optimizer.goal_liabilities import goal_to_liability
from services.optimizer.objective import chance_constraint_penalty, goal_probability_per_path
from services.optimizer.scenario_engine import simulate_wealth_paths


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CMA-INFLATION-PATH-DOMAIN-001 -- round 40 red test, see audit "
        "2026-10-04-cma-inflation-domain-and-effective-date-integrity-audit.md "
        "(not committed in this repo)"
    ),
)
def test_deeply_negative_real_inflation_must_not_flip_expense_liability_negative():
    goal = SimpleNamespace(
        id="g1",
        label="t",
        goal_type="Einmalige_Ausgabe",
        target_amount_rappen=10000,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=None,
        target_date=None,
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        value_mode="real",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
    )

    horizon_years = 5
    liab = goal_to_liability(
        goal, horizon_years=horizon_years, inflation_series_bps=[-20000, -20000],
    )

    # --- Drive the REAL production wealth-path simulation end-to-end -----
    # Zero growth, zero cashflow, zero initial wealth: any change in wealth
    # across t=0 -> t=1 must come purely from the goal's liability.
    n_paths = 3
    return_paths = np.ones((n_paths, horizon_years, 5), dtype=np.float64)
    weights = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
    cashflow_series_rappen = [0] * horizon_years

    wealth_paths = simulate_wealth_paths(
        initial_wealth_rappen=0,
        weights=weights,
        return_paths=return_paths,
        cashflow_series_rappen=cashflow_series_rappen,
        liability_path_rappen=liab.liability_path_rappen,
    )

    per_path = goal_probability_per_path(wealth_paths, liab, initial_value_rappen=0)
    penalty, achievability = chance_constraint_penalty(
        wealth_paths, [liab], initial_value_rappen=0,
    )
    row = achievability[0]

    # --- Observed (buggy) values, kept here for debugging visibility ----
    # liab.target_amount_rappen            == -10000
    # liab.liability_path_rappen           == [-10000, 0, 0, 0, 0]
    # wealth_paths[:, 1]                    == 10000 (wealth INCREASED by
    #                                          paying a CHF 100 expense)
    # per_path                              == [1, 1, 1]
    # row["probability"] / row["status"]    == 1.0 / "erreichbar"
    # penalty                               == 0.0

    negative_liability = liab.target_amount_rappen < 0 or any(
        v < 0 for v in liab.liability_path_rappen
    )
    wealth_increased_from_paying_expense = bool(
        np.any(wealth_paths[:, 1] > wealth_paths[:, 0])
    )
    false_positive_achievable = (
        row["probability"] >= 1.0
        and row["status"] == "erreichbar"
        and penalty == 0.0
    )

    assert not negative_liability, (
        "An expense goal's liability must never be negative; got "
        f"target_amount_rappen={liab.target_amount_rappen}, "
        f"liability_path_rappen={liab.liability_path_rappen}"
    )
    assert not wealth_increased_from_paying_expense, (
        "Paying a real expense must never increase simulated wealth; got "
        f"wealth_paths[:, 0]={wealth_paths[:, 0].tolist()} -> "
        f"wealth_paths[:, 1]={wealth_paths[:, 1].tolist()}"
    )
    assert not false_positive_achievable, (
        "An unfunded real expense goal must not be reported as costlessly "
        f"achievable; got probability={row['probability']}, "
        f"status={row['status']!r}, penalty={penalty}"
    )
