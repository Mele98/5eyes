"""Red test for OPTIMIZER-POST-SELECTION-CERTIFICATION-001 (round 38).

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
(this path does not exist in this worktree's git history -- confirmed via
Glob/git log --all; derived directly from reading models/allocation.py's
``OptimizerRun``, services/optimizer/objective.py's
``chance_constraint_penalty``, and services/optimizer/solver.py, and by
grepping for "effective_sample"/"ess"/"ESS" across the optimizer package).

Documents four concrete, currently-missing pieces of the "independent
validation evidence" contract this finding requires. Each sub-test fails
for the specific documented reason (not a generic absence) and is
individually wrapped so the file states exactly which part of the contract
is missing, rather than a single opaque assertion.
"""
from __future__ import annotations

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
from models.allocation import OptimizerRun  # noqa: E402
configure_mappers()

from services.optimizer.goal_liabilities import GoalLiability  # noqa: E402
from services.optimizer.objective import chance_constraint_penalty  # noqa: E402


def _optimizer_run_column_names() -> set[str]:
    return {column.name for column in OptimizerRun.__table__.columns}


def test_optimizer_run_persists_a_distinct_validation_seed_and_cube_hash():
    """OptimizerRun has exactly one `seed` and one `n_paths` column -- there
    is no second, independent validation-cube seed/path-count/hash field at
    all. Asserts the columns the desired contract requires actually exist;
    currently fails because none of them do.
    """
    columns = _optimizer_run_column_names()
    required_validation_columns = {
        "validation_seed",
        "validation_n_paths",
        "validation_cube_hash",
    }
    missing = required_validation_columns - columns
    assert not missing, (
        f"OptimizerRun is missing validation-evidence columns {missing} -- "
        f"it only has {sorted(columns)}"
    )


def test_optimizer_run_with_missing_validation_anchor_cannot_even_be_represented():
    """A direct consequence of (a): since OptimizerRun has no
    validation-anchor column, a solver run that was never independently
    validated and one that was ARE THE SAME ROW SHAPE -- there is no field
    whose absence/NULL-ness a reload or publication gate could check.
    Asserts that at least one validation-anchor column exists and can be
    NULL to represent "not yet validated"; currently fails because the
    column referenced doesn't exist, so the distinction cannot even be
    expressed in the schema, let alone enforced.
    """
    columns = _optimizer_run_column_names()
    assert "validation_cube_hash" in columns, (
        "no column exists whose NULL-ness could represent "
        '"this run was never independently validated" -- the schema has '
        "no way to distinguish a validated run from an unvalidated one"
    )


def test_low_effective_sample_size_importance_sampling_yields_unreliable_not_green():
    """A heavily concentrated importance-sampling weight vector (99.9% of
    the total weight mass on a single path -- effective sample size close
    to 1 out of 2000) is statistically almost no evidence at all, yet
    chance_constraint_penalty() has no ESS computation anywhere (verified:
    no "effective_sample"/"ess"/"ESS" symbol exists in
    services/optimizer/objective.py or services/optimizer/solver.py) and
    certifies "erreichbar" purely because the weighted mean happens to
    clear tau. Asserts the desired "unreliable" verdict; currently fails
    because that status string is never produced by this function at all.
    """
    liability = GoalLiability(
        goal_id="g-low-ess",
        label="Low-ESS Goal",
        goal_type="Vermoegensziel",
        target_kind="wealth_at_t",
        target_amount_rappen=100,
        target_year_index=1,
        liability_path_rappen=[100, 0],
        hardness_key="primaer",
        weight_bps=312,
        success_probability_min_x100=8000,
    )
    n_paths = 2000
    wealth_paths = np.zeros((n_paths, 2))
    wealth_paths[:, 1] = 50.0  # every path fails on its own
    wealth_paths[0, 1] = 150.0  # except exactly one path, which succeeds

    # Concentrate almost all importance-sampling weight on that single
    # successful path -- effective sample size collapses to ~1.
    weights = np.full(n_paths, 1e-6)
    weights[0] = 1.0

    _, achievability = chance_constraint_penalty(
        wealth_paths, [liability], initial_value_rappen=100, weights=weights,
    )

    assert achievability[0]["status"] == "unreliable", (
        f"a goal whose certification rests on a single effective path "
        f"(ESS ~= 1 out of {n_paths}) was certified "
        f"{achievability[0]['status']!r} instead of flagged unreliable"
    )


def test_achievability_row_exposes_an_interval_and_reliability_verdict():
    """The per-goal achievability dict returned by chance_constraint_penalty()
    -- the structure that ultimately reaches API/UI/PDF -- only carries
    goal_id/label/target_kind/probability/tau/status/hardness. Asserts the
    desired evidence fields exist on that row; currently fails because none
    of them are present.
    """
    liability = GoalLiability(
        goal_id="g-interval-evidence",
        label="Interval Evidence Goal",
        goal_type="Vermoegensziel",
        target_kind="wealth_at_t",
        target_amount_rappen=100,
        target_year_index=1,
        liability_path_rappen=[100, 0],
        hardness_key="primaer",
        weight_bps=312,
        success_probability_min_x100=8000,
    )
    wealth_paths = np.zeros((2000, 2))
    wealth_paths[:1600, 1] = 150.0
    wealth_paths[1600:, 1] = 50.0

    _, achievability = chance_constraint_penalty(wealth_paths, [liability], initial_value_rappen=100)
    row = achievability[0]

    required_evidence_fields = {
        "lower_confidence_bound",
        "validation_seed",
        "reliability_verdict",
    }
    missing_fields = required_evidence_fields - set(row.keys())
    assert not missing_fields, (
        f"achievability row is missing evidence fields {missing_fields} -- "
        f"it only carries {sorted(row.keys())}"
    )
