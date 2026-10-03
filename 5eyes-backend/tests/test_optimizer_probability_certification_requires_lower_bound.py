"""Red test for OPTIMIZER-POST-SELECTION-CERTIFICATION-001 (round 38).

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
(this path does not exist in this worktree's git history -- confirmed via
Glob/git log --all; derived directly from reading
services/optimizer/objective.py::chance_constraint_penalty and the existing
harness in tests/test_chance_constraint.py, and from empirically running
both before writing assertions).

``chance_constraint_penalty()`` (services/optimizer/objective.py line
~386) certifies a goal "erreichbar" (achievable) the instant the raw
sample-mean success probability is `>= tau`, with NO confidence-interval or
sample-size adjustment at all:

    tau = _default_tau_x100(goal) / 10000.0
    if probability >= tau:
        status = "erreichbar"

At exactly `tau`, this is a point estimate with substantial finite-sample
uncertainty, not evidence that the TRUE success probability is actually
`>= tau`. A one-sided 95% Wilson-score lower confidence bound for
1600/2000 successes (phat=0.80, n=2000) is only ~0.785 -- below tau -- so a
proper estimator-aware decision rule would flag this as uncertain rather
than immediately certifying it green. This file does not implement or
require any particular interval estimator in production code (that is the
documented repair contract, out of scope for a red test); it defines a
standard Wilson-score lower bound locally, purely as a reference oracle to
demonstrate that today's code ignores sampling uncertainty entirely.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
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

from services.optimizer.goal_liabilities import GoalLiability  # noqa: E402
from services.optimizer.objective import chance_constraint_penalty  # noqa: E402

TAU = 0.80


def _wilson_lower_bound(successes: int, n: int, *, z: float = 1.645) -> float:
    """One-sided ~95% Wilson-score lower confidence bound. Reference oracle
    only -- not a claim about which estimator production code should use,
    just a standard, well-known bound that demonstrates the point estimate
    alone is not sufficient evidence."""
    phat = successes / n
    denom = 1 + z * z / n
    center = phat + z * z / (2 * n)
    adjustment = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return (center - adjustment) / denom


def _wealth_at_t_liability() -> GoalLiability:
    return GoalLiability(
        goal_id="g-tau-boundary",
        label="Wealth-at-T Tau-Boundary Goal",
        goal_type="Vermoegensziel",
        target_kind="wealth_at_t",
        target_amount_rappen=100,
        target_year_index=1,
        liability_path_rappen=[100, 0],
        hardness_key="primaer",
        weight_bps=312,
        success_probability_min_x100=8000,  # tau = 0.80
    )


def _wealth_paths(n_success: int, n_total: int) -> np.ndarray:
    """(n_total, 2) wealth-path array: n_success paths clear the target
    (150 >= 100), the rest fall short (50 < 100)."""
    paths = np.zeros((n_total, 2))
    paths[:n_success, 1] = 150.0
    paths[n_success:, 1] = 50.0
    return paths


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OPTIMIZER-POST-SELECTION-CERTIFICATION-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_exact_tau_boundary_is_not_certified_without_a_lower_bound():
    """Red: exactly 1600/2000 successes (phat == tau == 0.80) is currently
    certified "erreichbar" with zero penalty on the raw point estimate
    alone. A one-sided Wilson lower bound at this sample size (~0.785) is
    below tau, so the correct contract requires this NOT be certified
    achievable without further evidence.
    """
    liability = _wealth_at_t_liability()
    wealth_paths = _wealth_paths(1600, 2000)

    lower_bound = _wilson_lower_bound(1600, 2000)
    assert lower_bound < TAU, "test setup error: oracle lower bound should be below tau"

    penalty, achievability = chance_constraint_penalty(wealth_paths, [liability], initial_value_rappen=100)
    status = achievability[0]["status"]

    assert status != "erreichbar", (
        f"status was certified {status!r} at the exact tau boundary "
        f"(probability={achievability[0]['probability']}) even though the "
        f"estimator-aware lower bound ({lower_bound:.4f}) is below tau "
        f"({TAU})"
    )
    assert penalty > 0.0, (
        "an uncertain tau-boundary result must not be treated as a "
        "zero-penalty certified success"
    )


def test_below_tau_boundary_is_not_certified_achievable():
    """Positive control (already correct today): 1599/2000 (phat=0.7995,
    clearly below tau) is correctly NOT certified "erreichbar" and carries
    a nonzero penalty -- the bug above is specifically about the exact
    boundary being wrongly treated as sufficient evidence, not about the
    whole mechanism being broken.
    """
    liability = _wealth_at_t_liability()
    wealth_paths = _wealth_paths(1599, 2000)

    penalty, achievability = chance_constraint_penalty(wealth_paths, [liability], initial_value_rappen=100)

    assert achievability[0]["status"] != "erreichbar"
    assert penalty > 0.0


def test_candidate_path_order_does_not_change_the_verdict():
    """Positive control (already correct today): the sample-mean estimator
    is order-invariant, so permuting which specific paths succeed/fail
    (while keeping the same count) cannot change the certified verdict on
    its own -- the bug is about accepting an uncorrected point estimate at
    the boundary, not about path ordering.
    """
    liability = _wealth_at_t_liability()

    wealth_paths_a = _wealth_paths(1600, 2000)
    wealth_paths_b = np.roll(wealth_paths_a, shift=777, axis=0)

    _, achievability_a = chance_constraint_penalty(wealth_paths_a, [liability], initial_value_rappen=100)
    _, achievability_b = chance_constraint_penalty(wealth_paths_b, [liability], initial_value_rappen=100)

    assert achievability_a[0]["status"] == achievability_b[0]["status"]
    assert achievability_a[0]["probability"] == achievability_b[0]["probability"]
