"""Tests fuer Phase 5.4 Scenario-Cache.

Verifiziert:
- Cache miss: erste Aufruf, baut Pfade
- Cache hit: zweite Aufruf gleicher Inputs, gleiche Pfade ohne neuen Build
- LRU-Eviction wenn max_size erreicht
- invalidate_cma entfernt nur diese cma's Eintraege
- Determinismus: Cached und nicht-cached Output sind identisch
- Stats-Counter: hits, misses, evictions
- Cache hit ist >5x schneller als build
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.scenario_cache import (
    ScenarioCache,
    build_scenario_paths_cached,
    get_default_cache,
)
from services.optimizer.scenario_engine import (
    BUCKET_ORDER,
    N_BUCKETS,
    ScenarioInputs,
    build_scenario_paths,
)


def _make_inputs(mu_bps: int = 500, sigma_bps: int = 1000) -> ScenarioInputs:
    return ScenarioInputs(
        mu_bps=np.full(N_BUCKETS, mu_bps, dtype=np.float64),
        sigma_bps=np.full(N_BUCKETS, sigma_bps, dtype=np.float64),
        skew_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        excess_kurt_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        cholesky=np.eye(N_BUCKETS),
    )


# ============================================================================
# Cache miss/hit basics
# ============================================================================


def test_cache_miss_then_hit():
    cache = ScenarioCache(max_size=4)
    inputs = _make_inputs()
    # First call: miss
    a = build_scenario_paths_cached(
        inputs, cma_id="cma-1", horizon_years=5, n_paths=100, seed=42, cache=cache,
    )
    assert cache.stats.misses == 1
    assert cache.stats.hits == 0
    # Second call same params: hit
    b = build_scenario_paths_cached(
        inputs, cma_id="cma-1", horizon_years=5, n_paths=100, seed=42, cache=cache,
    )
    assert cache.stats.hits == 1
    assert cache.stats.misses == 1
    # Output identisch (selbe ndarray reference oder gleiche Werte)
    assert np.array_equal(a, b)


def test_cache_different_cma_id_is_miss():
    cache = ScenarioCache(max_size=4)
    inputs = _make_inputs()
    build_scenario_paths_cached(inputs, cma_id="cma-A", horizon_years=5, n_paths=50, seed=42, cache=cache)
    build_scenario_paths_cached(inputs, cma_id="cma-B", horizon_years=5, n_paths=50, seed=42, cache=cache)
    assert cache.stats.misses == 2
    assert cache.stats.hits == 0


def test_cache_different_seed_is_miss():
    cache = ScenarioCache(max_size=4)
    inputs = _make_inputs()
    build_scenario_paths_cached(inputs, cma_id="cma-1", horizon_years=5, n_paths=50, seed=42, cache=cache)
    build_scenario_paths_cached(inputs, cma_id="cma-1", horizon_years=5, n_paths=50, seed=43, cache=cache)
    assert cache.stats.misses == 2


def test_cache_consistency_with_uncached_output():
    """Cached output muss exakt identisch zu direktem build_scenario_paths sein."""
    cache = ScenarioCache(max_size=4)
    inputs = _make_inputs()
    cached = build_scenario_paths_cached(
        inputs, cma_id="cma-1", horizon_years=5, n_paths=100, seed=42, cache=cache,
    )
    direct = build_scenario_paths(inputs, horizon_years=5, n_paths=100, seed=42)
    assert np.array_equal(cached, direct)


# ============================================================================
# LRU eviction
# ============================================================================


def test_cache_lru_evicts_oldest_at_max_size():
    cache = ScenarioCache(max_size=2)
    inputs = _make_inputs()
    # Fill to max
    build_scenario_paths_cached(inputs, cma_id="cma-1", horizon_years=5, n_paths=50, seed=1, cache=cache)
    build_scenario_paths_cached(inputs, cma_id="cma-2", horizon_years=5, n_paths=50, seed=2, cache=cache)
    assert len(cache) == 2
    # New entry -> evict oldest (cma-1)
    build_scenario_paths_cached(inputs, cma_id="cma-3", horizon_years=5, n_paths=50, seed=3, cache=cache)
    assert len(cache) == 2
    assert cache.stats.evictions == 1
    # cma-1 should be gone -> miss again
    build_scenario_paths_cached(inputs, cma_id="cma-1", horizon_years=5, n_paths=50, seed=1, cache=cache)
    assert cache.stats.misses == 4  # 3 fills + 1 re-build


def test_cache_lru_touch_moves_to_end():
    """Access auf existierenden Key bewegt ihn ans Ende -> nicht evicted."""
    cache = ScenarioCache(max_size=2)
    inputs = _make_inputs()
    build_scenario_paths_cached(inputs, cma_id="cma-1", horizon_years=5, n_paths=50, seed=1, cache=cache)
    build_scenario_paths_cached(inputs, cma_id="cma-2", horizon_years=5, n_paths=50, seed=2, cache=cache)
    # Touch cma-1 again -> moves to end
    build_scenario_paths_cached(inputs, cma_id="cma-1", horizon_years=5, n_paths=50, seed=1, cache=cache)
    # Now add cma-3 -> should evict cma-2 (oldest), not cma-1
    build_scenario_paths_cached(inputs, cma_id="cma-3", horizon_years=5, n_paths=50, seed=3, cache=cache)
    # cma-1 should still be a hit
    pre_hits = cache.stats.hits
    build_scenario_paths_cached(inputs, cma_id="cma-1", horizon_years=5, n_paths=50, seed=1, cache=cache)
    assert cache.stats.hits == pre_hits + 1, "cma-1 should still be cached after LRU touch"


# ============================================================================
# invalidate_cma
# ============================================================================


def test_invalidate_cma_removes_only_that_cma_entries():
    cache = ScenarioCache(max_size=10)
    inputs = _make_inputs()
    # Add 3 entries for cma-1 (different seeds), 2 for cma-2
    for seed in (1, 2, 3):
        build_scenario_paths_cached(inputs, cma_id="cma-1", horizon_years=5, n_paths=50, seed=seed, cache=cache)
    for seed in (10, 20):
        build_scenario_paths_cached(inputs, cma_id="cma-2", horizon_years=5, n_paths=50, seed=seed, cache=cache)
    assert len(cache) == 5
    removed = cache.invalidate_cma("cma-1")
    assert removed == 3
    assert len(cache) == 2  # nur cma-2 Eintraege uebrig
    # cma-2 sollte noch hits liefern
    pre_hits = cache.stats.hits
    build_scenario_paths_cached(inputs, cma_id="cma-2", horizon_years=5, n_paths=50, seed=10, cache=cache)
    assert cache.stats.hits == pre_hits + 1


# ============================================================================
# Performance
# ============================================================================


def test_cache_hit_at_least_5x_faster_than_build():
    """Cache-Hit sollte mind 5x schneller sein als ein full build."""
    cache = ScenarioCache(max_size=4)
    inputs = _make_inputs()

    # Build once to warm cache
    build_scenario_paths_cached(
        inputs, cma_id="cma-perf", horizon_years=10, n_paths=2000, seed=42, cache=cache,
    )

    # Time another miss (different seed)
    t0 = time.perf_counter()
    build_scenario_paths_cached(
        inputs, cma_id="cma-perf", horizon_years=10, n_paths=2000, seed=99, cache=cache,
    )
    miss_time = time.perf_counter() - t0

    # Time hit (same as warm)
    t0 = time.perf_counter()
    build_scenario_paths_cached(
        inputs, cma_id="cma-perf", horizon_years=10, n_paths=2000, seed=42, cache=cache,
    )
    hit_time = time.perf_counter() - t0

    assert hit_time < miss_time / 5, (
        f"Cache hit {hit_time*1000:.2f}ms not significantly faster than miss {miss_time*1000:.2f}ms"
    )


# ============================================================================
# Default cache singleton
# ============================================================================


def test_default_cache_is_singleton():
    a = get_default_cache()
    b = get_default_cache()
    assert a is b


def test_default_cache_has_reasonable_max_size():
    cache = get_default_cache()
    assert cache.stats.max_size >= 4
    assert cache.stats.max_size <= 64


# ============================================================================
# Clear
# ============================================================================


def test_clear_resets_cache_and_stats():
    cache = ScenarioCache(max_size=4)
    inputs = _make_inputs()
    build_scenario_paths_cached(inputs, cma_id="cma-1", horizon_years=5, n_paths=50, seed=1, cache=cache)
    assert len(cache) == 1
    cache.clear()
    assert len(cache) == 0
    assert cache.stats.hits == 0
    assert cache.stats.misses == 0
