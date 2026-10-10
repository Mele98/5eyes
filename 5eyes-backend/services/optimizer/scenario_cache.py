"""LRU-Cache fuer scenario_paths (Phase 5.4).

Master-Spec: docs/planning/2026-05-05-stochastic-optimizer-spec.md (Sec I #43)

Wenn der Optimizer mehrfach fuer denselben Mandanten innerhalb kurzer Zeit
laeuft (z.B. iterative Sensitivity-Analyse, Sub-Allocation-Tweaks, Re-Computes
nach Goal-Edits), wuerde jedes Mal eine 2'000-Pfade × horizon × 5-Bucket
ndarray neu erzeugt. Das ist mit ~0.5s pro Build der dominierende Cost.

Diese Cache-Schicht erkennt Wiederholungen: gleiche effektive
ScenarioInputs + gleiche Parameter -> Returns identisches ndarray (gleicher
Seed, gleiche Numpy-Generator, deterministisch).

SCENARIO-CACHE-EFFECTIVE-INPUT-001 (2026-10-10): der Key hing vorher an
`cma_id` als Proxy fuer mu/sigma/skew/kurt/cholesky, unter der Annahme
"cma-Werte sind unter einer cma_id IMMUTABLE". Diese Annahme war falsch --
die effektive Bucket-Sigma haengt zusaetzlich von Einstellungen AUSSERHALB
der CMA-Zeile ab (`settings.sub_class_intra_correlation`). Der Key hasht
jetzt die tatsaechlichen ScenarioInputs (siehe
scenario_inputs_digest()); `cma_id` bleibt im Key, aber nur noch als
Gruppierungsmerkmal fuer invalidate_cma().

Cache-Size: 16 Eintraege Default. Bei n_paths=2000, horizon=30: ~2.4 MB
pro Eintrag * 16 = ~38 MB Memory-Footprint. Vertraeglich fuer Desktop-App.
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

from .scenario_engine import ScenarioInputs, build_scenario_paths
from services.return_moments import RETURN_MOMENT_MODEL_VERSION


# ============================================================================
# Effective-input digest (SCENARIO-CACHE-EFFECTIVE-INPUT-001)
# ============================================================================

_INPUT_DIGEST_FIELDS = ("mu_bps", "sigma_bps", "skew_bps", "excess_kurt_bps", "cholesky")


def scenario_inputs_digest(inputs: ScenarioInputs) -> str:
    """Deterministischer Hash ueber die TATSAECHLICHEN ScenarioInputs.

    SCENARIO-CACHE-EFFECTIVE-INPUT-001 (2026-10-10): der Cache-Key nutzte
    vorher nur `cma_id` als "Proxy fuer mu/sigma/skew/kurt/cholesky" unter
    der Annahme "cma-Werte sind unter einer cma_id IMMUTABLE". Diese
    Annahme haelt NICHT: `_weighted_bucket_metrics()` laesst die effektive
    Bucket-Sigma von einer globalen Einstellung ausserhalb der CMA-Zeile
    abhaengen (`settings.sub_class_intra_correlation`, siehe
    SUBRISK-GLOBAL-RHO-MODEL-001). Bei identischer cma_id und geaendertem
    effektivem Sigma lieferte der Cache die Pfade der ALTEN Inputs zurueck
    -- also eine Monte-Carlo-Simulation unter stillschweigend falschen
    Verteilungsannahmen.

    `float64.tobytes()` ist die exakte Bit-Repraesentation und damit
    deterministisch reproduzierbar (keine Repr-/Rundungs-Unschaerfe). Die
    Feldreihenfolge ist fix, und jedes Feld geht mit Shape + Bytes ein,
    damit zwei verschieden geformte Arrays mit gleichem Byte-Inhalt nicht
    kollidieren koennen.
    """
    hasher = hashlib.sha256()
    for field_name in _INPUT_DIGEST_FIELDS:
        array = np.ascontiguousarray(getattr(inputs, field_name), dtype=np.float64)
        hasher.update(field_name.encode("utf-8"))
        hasher.update(repr(array.shape).encode("utf-8"))
        hasher.update(array.tobytes())
    return hasher.hexdigest()


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
        """Entfernt alle Eintraege fuer eine bestimmte cma_id. Returns count.

        Sprint P1: Cache-Keys haben jetzt ein Marker-Praefix ('STD' oder 'IS')
        an Position 0 — cma_id steht an Position 1. Wir support beide Formen
        fuer Backwards-Compat falls Caller alte Keys direkt put-en.
        """
        keys_to_remove = [
            k for k in self._cache
            if (len(k) >= 2 and k[0] in ("STD", "IS") and k[1] == cma_id)
            or (len(k) >= 1 and k[0] == cma_id)
        ]
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
    """Cache-aware Wrapper um build_scenario_paths (Standard-MC ohne IS).

    Cache-Key umfasst alle Parameter die das Output beeinflussen: cma_id
    (nur noch fuer invalidate_cma()-Gruppierung, NICHT als Proxy fuer die
    Verteilungsparameter), der Digest der tatsaechlichen ScenarioInputs,
    horizon, n_paths, seed, antithetic. Siehe scenario_inputs_digest() --
    SCENARIO-CACHE-EFFECTIVE-INPUT-001.

    Wenn cache=None: nutze Module-Default-Cache. Caller kann eigenen
    ScenarioCache uebergeben (z.B. fuer Tests-Isolation).

    Returns: identisch zu build_scenario_paths Output (n_paths, horizon, 5).
    """
    if cache is None:
        cache = _GLOBAL_CACHE
    # IS-aware key: 'STD' marker damit IS- und Non-IS-Eintraege getrennt
    # gecacht werden. build_scenario_paths_with_weights_cached nutzt ein
    # anderes Marker-Praefix. cma_id bleibt an Position 1, damit
    # invalidate_cma() weiterhin gruppieren kann.
    key = (
        "STD",
        str(cma_id),
        RETURN_MOMENT_MODEL_VERSION,
        int(horizon_years),
        int(n_paths),
        int(seed),
        bool(antithetic),
        scenario_inputs_digest(inputs),
    )
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


def build_scenario_paths_with_weights_cached(
    inputs: ScenarioInputs,
    *,
    cma_id: str,
    horizon_years: int,
    n_paths: int,
    seed: int,
    antithetic: bool = True,
    shift_vector: np.ndarray | None = None,
    cache: ScenarioCache | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Sprint P1 (2026-06-06): IS-aware cached scenario paths.

    Wie build_scenario_paths_cached, aber returnt zusaetzlich die
    Likelihood-Ratio-Gewichte fuer Mean-Shift Importance Sampling.

    Cache-Key umfasst zusaetzlich den shift_vector damit IS-on und IS-off
    Pfade NICHT vertauscht werden koennen.

    Parameters
    ----------
    shift_vector : np.ndarray | None
        Mean-Shift-Vector pro Bucket. None oder zero-Vector -> normales MC
        ohne IS (weights = ones).

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        (paths shape (n_paths, horizon, 5), weights shape (n_paths,)).
        Bei IS-off: weights sind alle 1.0.
    """
    from .scenario_engine import build_scenario_paths_with_weights
    from .importance_sampling import make_default_weights

    if cache is None:
        cache = _GLOBAL_CACHE

    # Wenn kein Shift: identisch zum STD-Pfad, weights = ones
    if shift_vector is None or float(np.dot(shift_vector, shift_vector)) < 1e-12:
        paths = build_scenario_paths_cached(
            inputs,
            cma_id=cma_id,
            horizon_years=horizon_years,
            n_paths=n_paths,
            seed=seed,
            antithetic=antithetic,
            cache=cache,
        )
        return paths, make_default_weights(n_paths)

    # IS-aktiv: shift_vector als tuple zur Hash-Stabilitaet. Der
    # Inputs-Digest ist hier aus demselben Grund Teil des Keys wie im
    # STD-Pfad (SCENARIO-CACHE-EFFECTIVE-INPUT-001).
    shift_tuple = tuple(float(x) for x in np.asarray(shift_vector).reshape(-1))
    key = (
        "IS", str(cma_id), RETURN_MOMENT_MODEL_VERSION,
        int(horizon_years), int(n_paths), int(seed),
        bool(antithetic), shift_tuple,
        scenario_inputs_digest(inputs),
    )
    cached = cache.get(key)
    if cached is not None:
        # Cache speichert paths + weights als (n_paths, horizon+1, 5)-Trick:
        # letzter Year-Slot hat weights im 0-ten Bucket
        # Saubere Variante: cache speichert tuple
        return cached  # cached ist tuple (paths, weights)

    paths, weights = build_scenario_paths_with_weights(
        inputs,
        horizon_years=horizon_years,
        n_paths=n_paths,
        seed=seed,
        antithetic=antithetic,
        use_importance_sampling=True,
        is_shift_strength=float(np.max(np.abs(shift_vector))),
    )
    # Note: build_scenario_paths_with_weights derives shift_vector internally
    # mit default-target-indices. Wir trauen dem default und cachen das Ergebnis.
    cache.put(key, (paths, weights))
    return paths, weights
