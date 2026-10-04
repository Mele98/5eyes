"""Red test for OPTIMIZER-POST-SELECTION-CERTIFICATION-001 (round 38).

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
(this path does not exist in this worktree's git history -- confirmed via
Glob/git log --all; derived directly from the audit's own documented repro
shape -- five marginally-identical candidates, true P(success)=tau=0.80,
2000 antithetic standard-MC train paths, select the best by the real
objective, validate on an independent cube, repeat over 100 seed pairs --
and independently re-derived here with fixed local seeds before writing
assertions, rather than taking the audit's numbers on faith).

Common Random Numbers across candidates are correct and intentional (see
services/portfolio_engine_optimizer_integration.py / solver.py -- a single
``OptimizerContext.return_paths`` is reused for all candidates in one
solver pass, which is the right way to compare candidates fairly). The bug
is what happens AFTER selection: the winning candidate's own
train-cube probability estimate is treated as final, with no independent
re-estimate. Because the winner is chosen BECAUSE it had a favourable
sample on this particular cube, its train-cube estimate is systematically
upward-biased relative to its true probability -- the classic
winner's-curse / post-selection-inference effect. This file demonstrates
that bias numerically, independent of any specific production function
(deliberately -- there is currently no independent-validation step
anywhere in the codebase to call into; that absence is exactly what this
test documents as the release-blocking gap, per Pflichttest 3 of this
finding).
"""
from __future__ import annotations

import numpy as np
import pytest

TRUE_SUCCESS_PROBABILITY = 0.80
TAU = 0.80
N_CANDIDATES = 5
N_PATHS = 2000
N_TRIALS = 100


def _antithetic_bernoulli_successes(rng: np.random.Generator, p: float, n: int) -> np.ndarray:
    """n antithetic-paired Bernoulli(p) draws: for each uniform draw u, both
    u and its antithetic partner (1-u) are compared against p. This mirrors
    the audit's "2000 antithetic Standard-MC-Pfade" train-cube shape."""
    half = n // 2
    u = rng.random(half)
    first_half = (u < p).astype(np.int8)
    second_half = ((1.0 - u) < p).astype(np.int8)
    return np.concatenate([first_half, second_half])


def _run_selection_and_validation_trial(trial_index: int) -> tuple[bool, bool]:
    """One trial: build 5 marginally-identical candidates on a train cube,
    select the one with the highest train estimate, then re-estimate ONLY
    that selected candidate on an independent validation cube. Returns
    (train_certified_green, validation_certified_green)."""
    train_rng = np.random.default_rng(1000 + trial_index)
    validation_rng = np.random.default_rng(50_000 + trial_index)

    train_rates = np.array([
        _antithetic_bernoulli_successes(train_rng, TRUE_SUCCESS_PROBABILITY, N_PATHS).mean()
        for _ in range(N_CANDIDATES)
    ])
    best_candidate_index = int(np.argmax(train_rates))
    train_certified_green = bool(train_rates[best_candidate_index] >= TAU)

    validation_rate = _antithetic_bernoulli_successes(
        validation_rng, TRUE_SUCCESS_PROBABILITY, N_PATHS
    ).mean()
    validation_certified_green = bool(validation_rate >= TAU)

    return train_certified_green, validation_certified_green


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OPTIMIZER-POST-SELECTION-CERTIFICATION-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_train_cube_certification_rate_matches_independent_validation_rate():
    """Red: the train-cube certification rate for the SELECTED (best-of-5)
    candidate must be statistically close to the independent validation
    rate for that same true-0.80-probability candidate -- today's codebase
    has no independent validation step at all, so the train-cube estimate
    (systematically inflated by selection) is published as final.

    Empirically reproduced with fixed seeds (deterministic): over 100
    seed-pairs, the train-certified-green rate runs dramatically higher
    than the independent-validation-certified-green rate for the identical
    underlying (true P=0.80) candidate, even though every individual
    candidate distribution is correctly calibrated at tau.
    """
    train_green_count = 0
    validation_green_count = 0
    for trial_index in range(N_TRIALS):
        train_green, validation_green = _run_selection_and_validation_trial(trial_index)
        train_green_count += int(train_green)
        validation_green_count += int(validation_green)

    # A generous tolerance for genuine sampling noise between two
    # independently-seeded rate estimates of the same underlying quantity --
    # anything beyond this is selection bias, not noise.
    noise_tolerance = 15

    assert abs(train_green_count - validation_green_count) <= noise_tolerance, (
        f"train-cube certified {train_green_count}/{N_TRIALS} trials green, "
        f"but independent validation only certified "
        f"{validation_green_count}/{N_TRIALS} green for the identical "
        f"true-{TRUE_SUCCESS_PROBABILITY}-probability selected candidate -- "
        f"a gap of {abs(train_green_count - validation_green_count)} is far "
        "beyond sampling noise and demonstrates post-selection/winner's-curse "
        "bias from certifying on the same cube used for selection"
    )


def test_each_individual_candidate_distribution_is_itself_correctly_calibrated():
    """Positive control: a single candidate's own Bernoulli(0.80) sampling
    mechanism, evaluated WITHOUT any selection step, is correctly calibrated
    around tau on average across many independent draws -- the bug is
    specifically about selecting the best of several before certifying,
    not about the underlying random-sampling mechanism being biased.
    """
    rng = np.random.default_rng(999)
    rates = [
        _antithetic_bernoulli_successes(rng, TRUE_SUCCESS_PROBABILITY, N_PATHS).mean()
        for _ in range(200)
    ]
    mean_rate = float(np.mean(rates))
    assert abs(mean_rate - TRUE_SUCCESS_PROBABILITY) < 0.01
