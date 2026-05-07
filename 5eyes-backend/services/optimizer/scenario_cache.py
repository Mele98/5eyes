"""LRU-Cache fuer scenario_paths (Phase 5.4).

Master-Spec: docs/planning/2026-05-05-stochastic-optimizer-spec.md (Sec I #43)

Wenn der Optimizer mehrfach fuer denselben Mandanten innerhalb kurzer Zeit
laeuft (z.B. iterative Sensitivity-Analyse, Sub-Allocation-Tweaks, Re-Computes
nach Goal-Edits), wuerde jedes Mal eine 2'000-Pfade × horizon × 5-Bucket
ndarray neu erzeugt. Das ist mit ~0.5s pro Build der dominierende Cost.

Diese Cache-Schicht erkennt Wiederholungen: gleiche cma_id + gleiche
Parameter -> Returns identisches ndarray (gleicher Seed, gleiche Numpy-
Generator, deterministisch).

Annahme: cma-Werte sind unter einer cma_id IMMUTABLE. 5eyes versioniert CMA
durch neue UUID pro Update -> Annahme haelt. Bei Aenderung der CMA-Inhalte
ohne ID-Aenderung wird der Cache stale; daher cmainvalidate() exposed.

Cache-Size: 16 Eintraege Default. Bei n_paths=2000, horizon=30: ~2.4 MB
pro Eintrag * 16 = ~38 MB Memory-Footprint. Vertraeglich fuer Desktop-App.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

from .scenario_engine import ScenarioInputs, build_scenario_paths


# ============================================================================
# Cache-Klasse
# ============================================================================


@dataclass
class CacheStats:
    """Diagnostik-Counter (fuer Tests + ggf. Admin-Endpoint)."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    max_size: int = 0


class ScenarioCache:
    """LRU-Cache fuer (n_paths, horizon, n_buckets) ndarrays.

    Key-Convention: (cma_id, horizon_years, n_paths, seed, antithetic).
    Value: numpy ndarray (n_paths, horizon_years, 5).

    Thread-safety: nicht-threadsafe by design. Backend ist sync per request,
    bei async/multi-process muss separater Cache pro Worker. Fuer Phase 5.4
    reicht single-process.
    """

    def __init__(self, max_size: int = 16) -> None:
        self._max_size = max(1, int(max_size))
        self._cache: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._stats = CacheStats(max_size=self._max_size)

    @property
    def stats(self) -> CacheStats:
        return self._stats

    def __len__(self) -> int:
        return len(self._cache)

    def get(self, key: tuple) -> np.ndarray | None:
        if key in self._cache:
            value = self._cache.pop(key)
            self._cache[key] = value  # move to end (LRU touch)
            self._stats.hits += 1
            return value
        self._stats.misses += 1
        return None

    def put(self, key: tuple, value: np.ndarray) -> None:
        if key in self._cache:
            self._cache.pop(key)
        elif len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)  # remove oldest
            self._stats.evictions += 1
        self._cache[key] = value

    def clear(self) -> None:
        self._cache.clear()
        self._stats = CacheStats(max_size=self._max_size)

    def invalidate_cma(self, cma_id: str) -> int:
        """Entfernt alle Eintraege fuer eine bestimmte cma_id. Returns count."""
        keys_to_remove = [k for k in self._cache if k[0] == cma_id]
        for k in keys_to_remove:
            self._cache.pop(k)
        return len(keys_to_remove)


# Module-level singleton fuer den Default-Use-Case
_GLOBAL_CACHE = ScenarioCache(max_size=16)


def get_default_cache() -> ScenarioCache:
    """Gibt den globalen Module-Cache zurueck."""
    return _GLOBAL_CACHE


# ============================================================================
# Public API: Cached scenario path build
# ============================================================================


def build_scenario_paths_cached(
    inputs: ScenarioInputs,
    *,
    cma_id: str,
    horizon_years: int,
    n_paths: int,
    seed: int,
    antithetic: bool = True,
    cache: ScenarioCache | None = None,
) -> np.ndarray:
    """Cache-aware Wrapper um build_scenario_paths.

    Cache-Key umfasst alle Parameter die das Output beeinflussen:
    cma_id (= proxy fuer mu/sigma/skew/kurt/cholesky), horizon, n_paths,
    seed, antithetic.

    Wenn cache=None: nutze Module-Default-Cache. Caller kann eigenen
    ScenarioCache uebergeben (z.B. fuer Tests-Isolation).

    Returns: identisch zu build_scenario_paths Output (n_paths, horizon, 5).
    """
    if cache is None:
        cache = _GLOBAL_CACHE
    key = (str(cma_id), int(horizon_years), int(n_paths), int(seed), bool(antithetic))
    cached = cache.get(key)
    if cached is not None:
        return cached
    paths = build_scenario_paths(
        inputs,
        horizon_years=horizon_years,
        n_paths=n_paths,
        seed=seed,
        antithetic=antithetic,
    )
    cache.put(key, paths)
    return paths
