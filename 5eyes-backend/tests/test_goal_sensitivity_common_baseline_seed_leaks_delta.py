"""GOAL-SENSITIVITY-COMMON-BASELINE-001 — round 48 red test.

See docs/audits/2026-10-04-goal-sensitivity-common-baseline-and-publication-integrity-audit.md

The production seed for goal-sensitivity analyses is built as:

    pinned_seed = deterministic_seed(
        cma_id, goal_ids, score_x10, horizon, _OPTIMIZER_N_PATHS_DEFAULT,
        "sensitivity", target_goal.id, target_delta_pct, horizon_delta_years,
    )

(services/portfolio_engine.py, inside the sensitivity code path — confirmed by
direct reading, ~line 5403 at the time of writing).

`deterministic_seed` (services/optimizer/solver.py:672) is a pure SHA-256 hash
over every positional part, so including `target_delta_pct` and
`horizon_delta_years` in its arguments means every distinct slider step gets a
genuinely different seed and therefore a different Monte-Carlo scenario cube
for its BASELINE run, even though the underlying economic baseline (CMA,
goals, score, horizon) is byte-identical across all five slider steps. The
audit's own reproduction obtained five distinct seeds for deltas
-20/-10/0/+10/+20 and confirmed the first equity return factor of the first
path of the first year differs across all five.

This file proves the same defect in two independent, complementary ways:

1. A pure unit-level reproduction of the seed function itself (no DB/solver
   needed) — this is the root cause, confirmed deterministically.
2. An integration-level reproduction through the real
   `evaluate_goal_sensitivity()` service function, capturing the actual
   `return_paths` numpy array handed to the (stubbed) solver for the BASELINE
   run under two different `target_delta_pct` values — proving the defect
   reaches all the way to the actual scenario cube consumed by the solver,
   not just the seed integer.
"""
from __future__ import annotations

import numpy as np
import pytest

from services.optimizer.solver import deterministic_seed
from tests.test_optimizer_phase6 import (  # noqa: F401 -- re-exported as fixture
    session_factory,
    _seed_mandate,
    _capture_sensitivity_solver_calls,
)


# ---------------------------------------------------------------------------
# Part 1: unit-level reproduction of the seed function itself
# ---------------------------------------------------------------------------


def _production_sensitivity_seed(target_delta_pct: int, horizon_delta_years: int) -> int:
    """Mirrors the exact production call shape in portfolio_engine.py's
    sensitivity path, with fixed baseline economic inputs and only the
    counterfactual deltas varying — exactly what a user does by moving the
    slider while nothing else about their mandate changes."""
    return deterministic_seed(
        "cma-fixed-123",       # cma_id — identical baseline CMA
        "goal-fixed-abc",      # goal_ids — identical goal set
        9000,                  # score_x10 — identical score
        10,                    # horizon — identical horizon
        2000,                  # _OPTIMIZER_N_PATHS_DEFAULT — identical path count
        "sensitivity",
        "goal-fixed-abc",      # target_goal.id — identical target goal
        target_delta_pct,
        horizon_delta_years,
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-SENSITIVITY-COMMON-BASELINE-001 — round 48 red test (seed "
        "derivation includes target_delta_pct/horizon_delta_years, so every "
        "slider step gets a different baseline Monte-Carlo cube despite "
        "identical underlying economic inputs), see audit "
        "docs/audits/2026-10-04-goal-sensitivity-common-baseline-and-publication-integrity-audit.md"
    ),
)
def test_sensitivity_seed_should_be_stable_across_target_delta_steps():
    """All five visible slider steps share the same baseline economic
    inputs, so a correct common-baseline contract must derive the SAME
    seed for the baseline run regardless of which delta the user is
    currently comparing against. Today's production seed function does
    not hold this invariant."""
    deltas = [-20, -10, 0, 10, 20]
    seeds = {_production_sensitivity_seed(d, 0) for d in deltas}
    # Correct behavior: one shared baseline seed for all five steps.
    assert len(seeds) == 1, (
        f"expected a single shared baseline seed across all slider deltas, "
        f"got {len(seeds)} distinct seeds: {seeds}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-SENSITIVITY-COMMON-BASELINE-001 — round 48 red test (seed "
        "derivation includes horizon_delta_years as well, so a pure "
        "horizon-only slider step also silently reseeds the baseline), "
        "see audit docs/audits/2026-10-04-goal-sensitivity-common-baseline-and-publication-integrity-audit.md"
    ),
)
def test_sensitivity_seed_should_be_stable_across_horizon_delta_steps():
    horizon_deltas = [-3, 0, 3]
    seeds = {_production_sensitivity_seed(0, d) for d in horizon_deltas}
    assert len(seeds) == 1, (
        f"expected a single shared baseline seed across all horizon deltas, "
        f"got {len(seeds)} distinct seeds: {seeds}"
    )


def test_positive_control_seed_function_is_itself_deterministic_and_sensitive():
    """Sanity/positive control: deterministic_seed() is pure and
    content-sensitive (this is correct and must be preserved) — it is the
    *inclusion* of counterfactual deltas as inputs that is the bug, not the
    hash function's determinism itself."""
    a = _production_sensitivity_seed(10, 0)
    b = _production_sensitivity_seed(10, 0)
    assert a == b, "same inputs must give the same seed (determinism)"

    c = _production_sensitivity_seed(10, 0)
    d = _production_sensitivity_seed(20, 0)
    assert c != d, (
        "sanity check: today's function DOES vary with target_delta_pct "
        "(this is the documented bug, not a flaky test)"
    )


# ---------------------------------------------------------------------------
# Part 2: integration-level reproduction via the real production service
# ---------------------------------------------------------------------------


def test_sensitivity_baseline_scenario_cube_differs_across_target_delta_steps(
    session_factory, monkeypatch,
):
    """Integration-level reproduction: two sensitivity calls against the
    SAME mandate/goal/economic baseline, differing only in
    target_delta_pct, must use the SAME baseline scenario cube
    (return_paths) for their first (baseline) solver invocation. Today they
    do not, because the seed depends on target_delta_pct."""
    import services.portfolio_engine as pe
    from services.portfolio_engine import evaluate_goal_sensitivity
    from models.mandates import Mandate

    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)

    calls_a = _capture_sensitivity_solver_calls(monkeypatch)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        evaluate_goal_sensitivity(
            db=s,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=gid,
            target_delta_pct=-20,
            horizon_delta_years=0,
        )
    assert len(calls_a) == 2
    baseline_cube_a = calls_a[0]["return_paths"]

    calls_b = _capture_sensitivity_solver_calls(monkeypatch)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        evaluate_goal_sensitivity(
            db=s,
            mandate=mandate,
            user_id=advisor_id,
            goal_id=gid,
            target_delta_pct=20,
            horizon_delta_years=0,
        )
    assert len(calls_b) == 2
    baseline_cube_b = calls_b[0]["return_paths"]

    if baseline_cube_a is None or baseline_cube_b is None:
        pytest.skip(
            "solver context did not expose return_paths in this build; "
            "see test_sensitivity_seed_should_be_stable_across_target_delta_steps "
            "for the unambiguous unit-level reproduction of the same defect"
        )

    assert np.array_equal(baseline_cube_a, baseline_cube_b), (
        "the baseline run's scenario cube must be identical across slider "
        "steps that only change target_delta_pct, since the underlying "
        "economic baseline (CMA, goals, score, horizon) is unchanged"
    )
