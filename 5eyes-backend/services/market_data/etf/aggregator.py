"""ETFAggregator — Provider-Fallback-Chain fuer ETF-Master-Daten.

Analog zum MarketDataAggregator (siehe ../aggregator.py), aber fuer
ETFProvider (nur `lookup_isin`, kein get_eod/get_history). Bisher wurden
JustetfScraper/SwissfunddataScraper nur einzeln instanziiert -- es gab
KEINE Fallback-Kette: fiel der primaere Scraper aus (TOS-Block, HTTP-
Fehler, Parsing-Fehler durch HTML-Aenderung), kam kein Ergebnis und der
Aufrufer stand ohne ETF-Masterdaten da.

Dieser Aggregator schliesst die Luecke:
- ProviderError/RateLimitError -> naechster Provider in der Kette.
- SymbolNotFound -> ebenfalls naechster Provider (unterschiedliche
  Daten-Abdeckung je Scraper), Provider bleibt aber healthy.
- Jeder Fehler markiert den Provider im in-memory HealthState (TTL-
  Backoff) unhealthy UND wird -- sofern ein `health_registry` (siehe
  ../provider_health_registry.py) konfiguriert ist -- persistent
  geloggt. Kein stiller Null-Wert: entweder liefert die Kette ein
  ETFInfo-Ergebnis, oder die letzte Exception wird sichtbar re-raised.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from ..exceptions import MarketDataError, ProviderError, RateLimitError, SymbolNotFound
from ..health import HealthState
from .base import ETFInfo, ETFProvider

logger = logging.getLogger(__name__)


class ETFAggregator:
    """Sequentieller Fallback ueber eine Liste von ETFProvidern.

    Reihenfolge entscheidet Prioritaet (Index 0 = Primary).
    """

    def __init__(
        self,
        providers: Iterable[ETFProvider],
        unhealthy_ttl_seconds: int = 300,
        health_registry: Any | None = None,
    ) -> None:
        self._providers: list[ETFProvider] = list(providers)
        self._health = HealthState(unhealthy_ttl_seconds=unhealthy_ttl_seconds)
        self._health_registry = health_registry

    @property
    def providers(self) -> list[ETFProvider]:
        return list(self._providers)

    @property
    def health(self) -> HealthState:
        return self._health

    def _record_unhealthy(self, provider: ETFProvider, action_name: str, exc: BaseException) -> None:
        if self._health_registry is None:
            return
        try:
            self._health_registry.mark_unhealthy(
                provider.name,
                reason=str(exc),
                operation=action_name,
                error_type=exc.__class__.__name__,
                consecutive_errors=self._health.consecutive_errors(provider.name),
            )
        except Exception:  # noqa: BLE001 - observation must never affect ETF lookups
            logger.debug("etf provider-health registry unhealthy write failed", exc_info=True)

    def _record_healthy(self, provider: ETFProvider, action_name: str) -> None:
        if self._health_registry is None:
            return
        try:
            self._health_registry.mark_healthy(provider.name, operation=action_name)
        except Exception:  # noqa: BLE001
            logger.debug("etf provider-health registry healthy write failed", exc_info=True)

    def _candidates(self) -> list[ETFProvider]:
        """Provider in Reihenfolge, gefiltert auf currently-healthy."""
        result: list[ETFProvider] = []
        for p in self._providers:
            if not self._health.is_healthy(p.name):
                continue
            try:
                if not p.is_healthy():
                    continue
            except Exception:  # noqa: BLE001 - defensive
                continue
            result.append(p)
        return result

    def lookup_isin(self, isin: str) -> ETFInfo:
        action_name = f"lookup_isin({isin})"
        candidates = self._candidates()
        if not candidates:
            raise MarketDataError(
                f"{action_name}: kein gesunder ETF-Provider verfuegbar "
                f"(insgesamt {len(self._providers)} konfiguriert)"
            )
        last_exc: BaseException | None = None
        for provider in candidates:
            try:
                result = provider.lookup_isin(isin)
            except RateLimitError as exc:
                logger.warning("%s: %s rate-limited (%s)", action_name, provider.name, exc)
                self._health.mark_unhealthy(provider.name)
                self._record_unhealthy(provider, action_name, exc)
                last_exc = exc
                continue
            except SymbolNotFound as exc:
                # SymbolNotFound: weitermachen, Provider bleibt healthy
                last_exc = exc
                continue
            except ProviderError as exc:
                logger.warning("%s: %s provider error (%s)", action_name, provider.name, exc)
                self._health.mark_unhealthy(provider.name)
                self._record_unhealthy(provider, action_name, exc)
                last_exc = exc
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s: %s unexpected error (%s)", action_name, provider.name, exc)
                self._health.mark_unhealthy(provider.name)
                self._record_unhealthy(provider, action_name, exc)
                last_exc = exc
                continue
            # Erfolg: Provider bleibt/wird healthy
            self._health.mark_healthy(provider.name)
            self._record_healthy(provider, action_name)
            return result
        # Kein Provider erfolgreich -> letzte Exception werfen (kein stiller Ausfall)
        if isinstance(last_exc, BaseException):
            raise last_exc
        raise MarketDataError(f"{action_name}: alle ETF-Provider lieferten kein Resultat")
