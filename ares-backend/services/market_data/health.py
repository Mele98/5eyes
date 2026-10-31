"""Provider-Health-State mit TTL-basiertem Backoff.

Wenn ein Provider einen RateLimitError oder mehrfachen ProviderError wirft,
markieren wir ihn fuer einige Minuten als unhealthy. Aggregator (siehe
aggregator.py) prueft den State vor jedem Aufruf und skipped unhealthy
Provider.

Healthy/Unhealthy-Entscheidung:
- Zwei Inputs: explicit-mark via `mark_unhealthy(...)` oder Provider-eigene
  is_healthy() == False
- TTL: nach `unhealthy_ttl_seconds` (default 300s = 5min) wird der Provider
  wieder als healthy betrachtet

In-memory only — bei App-Restart ist der State weg, das ist OK
(Provider werden ohnehin frisch geprueft).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class _ProviderHealthEntry:
    until_epoch: float = 0.0  # unhealthy bis epoch-time; 0 = healthy
    consecutive_errors: int = 0


class HealthState:
    """In-memory Tracker fuer Provider-Gesundheit."""

    def __init__(self, unhealthy_ttl_seconds: int = 300) -> None:
        self._ttl = max(10, int(unhealthy_ttl_seconds))
        self._entries: dict[str, _ProviderHealthEntry] = {}

    def _now(self) -> float:
        return time.monotonic()

    def _entry(self, name: str) -> _ProviderHealthEntry:
        return self._entries.setdefault(name, _ProviderHealthEntry())

    def is_healthy(self, name: str) -> bool:
        entry = self._entry(name)
        return entry.until_epoch <= self._now()

    def mark_healthy(self, name: str) -> None:
        entry = self._entry(name)
        entry.until_epoch = 0.0
        entry.consecutive_errors = 0

    def mark_unhealthy(self, name: str, ttl_seconds: int | None = None) -> None:
        ttl = max(10, int(ttl_seconds)) if ttl_seconds is not None else self._ttl
        entry = self._entry(name)
        entry.until_epoch = self._now() + ttl
        entry.consecutive_errors += 1

    def consecutive_errors(self, name: str) -> int:
        return self._entry(name).consecutive_errors

    def reset(self, name: str | None = None) -> None:
        if name is None:
            self._entries.clear()
        else:
            self._entries.pop(name, None)
