"""Sprint U-19 (2026-05-31, Roadmap-Punkt 19): In-Memory-Cache fuer
den Advisory-Report-Aggregator.

Problem
-------
`compute_advisory_report()` macht 3+ separate DB-Queries pro Sektion
(siehe Aggregator-Modul) und laeuft beim aktuellen Stand bei JEDER
Sub-App-Sektion-Anzeige neu — der User klickt durch 17 Sidebar-Items
und triggert 17x den vollen 17-Sektionen-Aggregator.

Loesung
-------
Thin TTL+LRU-Cache zwischen HTTP-Endpoint und Aggregator. Cache-Key
ist `(mandate_id, advisor_id)` (verschiedene Berater koennten auf
demselben Mandat anders gerendert werden — Cover.advisor_name). Default
TTL 60s — auch ohne explizite Invalidation ist das Drift-Risiko klein.

Save-Endpoints (PUT report-notes, POST/PUT advisory-log, etc.) sollen
nach Commit `invalidate_mandate(mandate_id)` aufrufen, damit die naechste
GET-Anfrage frische Daten sieht. Wenn ein Endpoint das vergisst,
greift der TTL nach 60s.

Sicherheits-Hinweis
-------------------
* Cache ist NUR im Prozess (kein Redis), reicht fuer Single-Backend-
  Workflow.
* Bei Multi-Worker (uvicorn --workers > 1) hat jeder Worker seinen
  eigenen Cache. Invalidation ueber Workers folgt nicht; bei aktuell
  1-Worker-Default kein Problem.
* `clear_all()` ist fuer Tests und Hard-Reset.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from config import settings
from models.mandates import Mandate
from models.users import User
from services.advisory_report import compute_advisory_report

logger = logging.getLogger(__name__)


@dataclass
class _CacheStats:
    hits: int = 0
    misses: int = 0
    invalidations: int = 0
    evictions: int = 0
    last_invalidation_at: float | None = None


class _TTLCache:
    """Threadsafe TTL-Cache mit LRU-Eviction. Key -> (expiry_ts, value).

    Kein extra Dependency — nutzt OrderedDict + Lock.
    """

    def __init__(self, *, ttl_seconds: float, max_size: int) -> None:
        self._ttl = float(ttl_seconds)
        self._max = max(1, int(max_size))
        self._store: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.stats = _CacheStats()

    def get(self, key: Any) -> Any | None:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.stats.misses += 1
                return None
            expiry, value = entry
            if expiry < now:
                # TTL abgelaufen
                self._store.pop(key, None)
                self.stats.misses += 1
                return None
            # LRU-Touch
            self._store.move_to_end(key)
            self.stats.hits += 1
            return value

    def set(self, key: Any, value: Any) -> None:
        now = time.monotonic()
        expiry = now + self._ttl
        with self._lock:
            self._store[key] = (expiry, value)
            self._store.move_to_end(key)
            while len(self._store) > self._max:
                self._store.popitem(last=False)
                self.stats.evictions += 1

    def invalidate(self, key: Any) -> bool:
        with self._lock:
            removed = self._store.pop(key, None) is not None
            if removed:
                self.stats.invalidations += 1
                self.stats.last_invalidation_at = time.time()
            return removed

    def invalidate_prefix(self, prefix_predicate) -> int:
        """Loescht alle Eintraege, fuer die `prefix_predicate(key)` True ist."""
        with self._lock:
            to_remove = [k for k in self._store if prefix_predicate(k)]
            for k in to_remove:
                self._store.pop(k, None)
                self.stats.invalidations += 1
            if to_remove:
                self.stats.last_invalidation_at = time.time()
            return len(to_remove)

    def clear(self) -> int:
        with self._lock:
            n = len(self._store)
            self._store.clear()
            return n

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# Globale Instance — wird beim ersten Zugriff erzeugt, damit settings
# zum Zeitpunkt-T frisch gelesen werden.
_cache_instance: _TTLCache | None = None
_cache_lock = threading.Lock()


def _get_cache() -> _TTLCache:
    global _cache_instance
    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                _cache_instance = _TTLCache(
                    ttl_seconds=float(settings.aggregator_cache_ttl_seconds),
                    max_size=int(settings.aggregator_cache_max_size),
                )
    return _cache_instance


def _cache_key(mandate_id: str, advisor: User | None) -> tuple[str, str]:
    advisor_id = str(getattr(advisor, "id", "") or "anonymous")
    return (str(mandate_id), advisor_id)


def cached_compute_advisory_report(
    db: Session,
    mandate: Mandate,
    *,
    advisor: User | None = None,
) -> dict[str, Any]:
    """Wrapper um compute_advisory_report() mit TTL+LRU-Cache.

    Wenn `aggregator_cache_enabled=False`, faellt durch zum Original
    ohne Cache-Lookup.
    """
    if not settings.aggregator_cache_enabled:
        return compute_advisory_report(db, mandate, advisor=advisor)

    key = _cache_key(str(mandate.id), advisor)
    cache = _get_cache()
    cached = cache.get(key)
    if cached is not None:
        return cached

    fresh = compute_advisory_report(db, mandate, advisor=advisor)
    cache.set(key, fresh)
    return fresh


def invalidate_mandate(mandate_id: str) -> int:
    """Loescht ALLE Cache-Eintraege zu einem Mandat (alle Berater-Views).

    Aufzurufen direkt nach erfolgreichem Commit eines Save-Endpoints.
    Return: Anzahl entfernter Eintraege (0 wenn Mandat nicht im Cache).
    """
    if not settings.aggregator_cache_enabled:
        return 0
    cache = _get_cache()
    target = str(mandate_id)
    count = cache.invalidate_prefix(lambda key: key[0] == target)
    if count > 0:
        logger.debug(
            "Aggregator-Cache invalidiert | mandate_id=%s entries=%d", target, count
        )
    return count


def get_cache_stats() -> dict[str, Any]:
    """Diagnose-Endpoint-Helper: liefert Hits/Misses/Eviction-Counts."""
    cache = _get_cache()
    stats = cache.stats
    total = stats.hits + stats.misses
    return {
        "enabled": bool(settings.aggregator_cache_enabled),
        "ttl_seconds": int(settings.aggregator_cache_ttl_seconds),
        "max_size": int(settings.aggregator_cache_max_size),
        "current_size": len(cache),
        "hits": stats.hits,
        "misses": stats.misses,
        "hit_rate": (stats.hits / total) if total > 0 else 0.0,
        "invalidations": stats.invalidations,
        "evictions": stats.evictions,
        "last_invalidation_at": stats.last_invalidation_at,
    }


def clear_all() -> int:
    """Test-Helper: kompletter Reset."""
    cache = _get_cache()
    return cache.clear()


def reset_for_tests() -> None:
    """Test-Helper: Cache-Instance wegwerfen, damit der naechste Aufruf
    mit den AKTUELLEN Settings (z.B. test-spezifischer TTL) neu baut."""
    global _cache_instance
    with _cache_lock:
        if _cache_instance is not None:
            _cache_instance.clear()
        _cache_instance = None
