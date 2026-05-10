"""MarketDataAggregator — Provider-Fallback-Chain mit Health-Backoff.

Setzt das Multi-Source-Versprechen um: rufe Provider in Reihenfolge auf;
erster gibt Result -> done. RateLimit/Provider-Error -> nachster Versuch.
SymbolNotFound -> ebenfalls naechster Versuch (verschiedene Provider-
Symbol-Maps).

Provider werden mit ihrem .name identifiziert. Health-State (TTL-Backoff
nach Fehler) lebt im HealthState-Helper, in-memory pro Aggregator.

Exception-Strategie:
- Wenn ALLE Provider fehlgeschlagen sind: letzte Exception re-raise
- Wenn Liste leer ist (z.B. alle unhealthy): MarketDataError
"""
from __future__ import annotations

import logging
from datetime import date as Date
from typing import Iterable

from .base import Bar, MarketDataProvider, ProductInfo
from .exceptions import MarketDataError, ProviderError, RateLimitError, SymbolNotFound
from .health import HealthState

logger = logging.getLogger(__name__)


class MarketDataAggregator:
    """Sequentieller Fallback ueber eine Liste von MarketDataProvidern.

    Reihenfolge entscheidet Prioritaet (Index 0 = Primary).
    """

    def __init__(
        self,
        providers: Iterable[MarketDataProvider],
        unhealthy_ttl_seconds: int = 300,
    ) -> None:
        self._providers: list[MarketDataProvider] = list(providers)
        self._health = HealthState(unhealthy_ttl_seconds=unhealthy_ttl_seconds)

    @property
    def providers(self) -> list[MarketDataProvider]:
        return list(self._providers)

    @property
    def health(self) -> HealthState:
        return self._health

    def _candidates(self) -> list[MarketDataProvider]:
        """Provider in Reihenfolge, gefiltert auf currently-healthy."""
        result: list[MarketDataProvider] = []
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

    def _call_chain(self, action_name: str, action):
        """Generischer Fallback-Loop. action(provider) liefert Result oder
        wirft. Sammelt letzte Exception fuer Re-Raise.
        """
        candidates = self._candidates()
        if not candidates:
            raise MarketDataError(
                f"{action_name}: kein gesunder Provider verfuegbar "
                f"(insgesamt {len(self._providers)} konfiguriert)"
            )
        last_exc: BaseException | None = None
        for provider in candidates:
            try:
                result = action(provider)
            except RateLimitError as exc:
                logger.warning("%s: %s rate-limited (%s)", action_name, provider.name, exc)
                self._health.mark_unhealthy(provider.name)
                last_exc = exc
                continue
            except SymbolNotFound as exc:
                # SymbolNotFound: weitermachen, Provider bleibt healthy
                last_exc = exc
                continue
            except ProviderError as exc:
                logger.warning(
                    "%s: %s provider error (%s)", action_name, provider.name, exc,
                )
                self._health.mark_unhealthy(provider.name)
                last_exc = exc
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "%s: %s unexpected error (%s)", action_name, provider.name, exc,
                )
                self._health.mark_unhealthy(provider.name)
                last_exc = exc
                continue
            # Erfolg: Provider bleibt/wird healthy
            self._health.mark_healthy(provider.name)
            return result
        # Kein Provider erfolgreich -> letzte Exception werfen
        if isinstance(last_exc, BaseException):
            raise last_exc
        raise MarketDataError(f"{action_name}: alle Provider lieferten kein Resultat")

    # ------------------------------------------------------------------ #
    def get_eod(self, symbol: str, on_date: Date) -> Bar:
        return self._call_chain(
            f"get_eod({symbol}, {on_date})",
            lambda p: p.get_eod(symbol, on_date),
        )

    def get_history(self, symbol: str, start: Date, end: Date) -> list[Bar]:
        # get_history hat speziellere Semantik: leere Liste ist legitim,
        # nicht zwingend ein Fallback-Trigger. Aber wenn ein Provider [] gibt
        # und der naechste echte Daten haette, sollten wir diesen nutzen.
        # Pragmatisch: erste nicht-leere Antwort gewinnt.
        candidates = self._candidates()
        if not candidates:
            raise MarketDataError(
                f"get_history({symbol}): kein gesunder Provider verfuegbar"
            )
        last_exc: BaseException | None = None
        for provider in candidates:
            try:
                result = provider.get_history(symbol, start, end)
            except (RateLimitError, ProviderError) as exc:
                logger.warning(
                    "get_history(%s): %s error (%s)", symbol, provider.name, exc,
                )
                self._health.mark_unhealthy(provider.name)
                last_exc = exc
                continue
            except SymbolNotFound as exc:
                last_exc = exc
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "get_history(%s): %s unexpected (%s)", symbol, provider.name, exc,
                )
                self._health.mark_unhealthy(provider.name)
                last_exc = exc
                continue
            self._health.mark_healthy(provider.name)
            if result:
                return result
            # leere Liste: weiter zum naechsten Provider, aber keinen Fehler werfen
            last_exc = SymbolNotFound(f"{provider.name}: leeres history fuer {symbol}")
        # Wenn wir hier sind: kein Provider hatte Daten
        # Wenn der letzte Fehler ein "echter" Provider-Fehler war, raise.
        # Wenn nur leere Listen, leere Liste zurueck.
        if isinstance(last_exc, (RateLimitError, ProviderError)):
            raise last_exc
        return []

    def lookup_isin(self, isin: str) -> ProductInfo:
        return self._call_chain(
            f"lookup_isin({isin})",
            lambda p: p.lookup_isin(isin),
        )
