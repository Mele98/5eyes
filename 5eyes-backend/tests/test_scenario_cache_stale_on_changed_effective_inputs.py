"""SCENARIO-CACHE-EFFECTIVE-INPUT-001 -- round 52 red test.

See docs/audits/2026-10-05-sub-asset-risk-aggregation-cache-and-replay-integrity-audit.md
(Kontrollrunde 51 per the audit's own numbering, auditing commit 3b9f17c).

Confirmed by direct reading of services/optimizer/scenario_cache.py::build_scenario_paths_cached:

    key = (
        "STD",
        str(cma_id),
        RETURN_MOMENT_MODEL_VERSION,
        int(horizon_years),
        int(n_paths),
        int(seed),
        bool(antithetic),
    )

The function's own docstring explicitly documents `cma_id` as "= proxy fuer
mu/sigma/skew/kurt/cholesky" -- i.e. the cache key never hashes the actual
`inputs: ScenarioInputs` argument (mu_bps/sigma_bps/skew_bps/
excess_kurt_bps/cholesky) that the function receives and that the cached
ndarray is actually built from. The module's own docstring states the
underlying assumption explicitly: "Annahme: cma-Werte sind unter einer
cma_id IMMUTABLE" -- but this assumption does not hold for inputs whose
values are influenced by settings OUTSIDE the CMA row itself (confirmed by
the sibling finding SUBRISK-GLOBAL-RHO-MODEL-001: `_weighted_bucket_metrics()`
reads a global `settings.sub_class_intra_correlation` value that changes
the effective bucket sigma for the identical cma_id/sub-allocation).

This test proves the resulting bug directly at the cache's own public
contract, without needing the full settings/CMA plumbing: build once with
one `ScenarioInputs` (sigma=1000) under a given cma_id/horizon/n_paths/seed,
then build again with the SAME cma_id/horizon/n_paths/seed but a genuinely
DIFFERENT `ScenarioInputs` (sigma=2000) -- today's cache returns the FIRST
call's stale paths instead of building new ones for the new inputs.
"""
from __future__ import annotations

import numpy as np
import pytest

from services.optimizer.scenario_cache import (
    ScenarioCache,
    build_scenario_paths_cached,
)
from services.optimizer.scenario_engine import (
    N_BUCKETS,
    ScenarioInputs,
    build_scenario_paths,
)


def _make_inputs(mu_bps: int = 500, sigma_bps: int = 1000) -> ScenarioInputs:
    """Mirrors tests/test_optimizer_scenario_cache.py::_make_inputs exactly."""
    return ScenarioInputs(
        mu_bps=np.full(N_BUCKETS, mu_bps, dtype=np.float64),
        sigma_bps=np.full(N_BUCKETS, sigma_bps, dtype=np.float64),
        skew_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        excess_kurt_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        cholesky=np.eye(N_BUCKETS),
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "SCENARIO-CACHE-EFFECTIVE-INPUT-001 -- round 52 red test "
        "(build_scenario_paths_cached's cache key hashes only cma_id as a "
        "'proxy' for the actual ScenarioInputs; changing the effective "
        "sigma/mu while keeping cma_id/horizon/n_paths/seed identical "
        "returns stale cached paths from the OLD inputs instead of "
        "building fresh ones), see audit "
        "docs/audits/2026-10-05-sub-asset-risk-aggregation-cache-and-replay-integrity-audit.md"
    ),
)
def test_cache_must_not_return_stale_paths_when_effective_inputs_change():
    """Same cma_id/horizon/n_paths/seed, but genuinely different
    ScenarioInputs (sigma changed from 1000 to 2000 bps, simulating e.g. a
    changed sub_class_intra_correlation under an unchanged CMA row) must
    produce DIFFERENT scenario paths matching the NEW inputs -- not a
    cache hit serving the old inputs' paths."""
    cache = ScenarioCache(max_size=4)
    cma_id, horizon, n_paths, seed = "cma-same-id", 5, 100, 42

    old_inputs = _make_inputs(sigma_bps=1000)
    paths_old = build_scenario_paths_cached(
        old_inputs, cma_id=cma_id, horizon_years=horizon,
        n_paths=n_paths, seed=seed, cache=cache,
    )

    new_inputs = _make_inputs(sigma_bps=2000)
    paths_new_cached = build_scenario_paths_cached(
        new_inputs, cma_id=cma_id, horizon_years=horizon,
        n_paths=n_paths, seed=seed, cache=cache,
    )

    # Ground truth: what the SAME new_inputs produce when built directly,
    # bypassing the cache entirely.
    paths_new_direct = build_scenario_paths(
        new_inputs, horizon_years=horizon, n_paths=n_paths, seed=seed,
    )

    assert np.array_equal(paths_new_cached, paths_new_direct), (
        "build_scenario_paths_cached() returned paths that do not match a "
        "direct (uncached) build of the SAME new inputs -- it served a "
        "stale cache entry keyed only by cma_id instead of rebuilding for "
        "the changed effective ScenarioInputs"
    )
    assert not np.array_equal(paths_new_cached, paths_old), (
        "sanity check: the old and new inputs must produce genuinely "
        "different paths (different sigma), so a stale cache hit is "
        "actually observable and not masked by coincidental equality"
    )


def test_positive_control_cache_hit_for_truly_unchanged_inputs():
    """Positive control: calling with the identical cma_id AND identical
    ScenarioInputs twice must still be a correct, fast cache hit -- the
    fix for the red test above must not break this core cache purpose."""
    cache = ScenarioCache(max_size=4)
    inputs = _make_inputs(sigma_bps=1000)

    a = build_scenario_paths_cached(
        inputs, cma_id="cma-stable", horizon_years=5, n_paths=100, seed=42, cache=cache,
    )
    assert cache.stats.misses == 1
    b = build_scenario_paths_cached(
        inputs, cma_id="cma-stable", horizon_years=5, n_paths=100, seed=42, cache=cache,
    )
    assert cache.stats.hits == 1
    assert np.array_equal(a, b)
