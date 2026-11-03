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

Massgebliche Quellen (BBG-1, Audit 2026-11/06, B4): Ein Provider mit
``authoritative = True`` (z. B. Bloomberg) wird NIE still uebersprungen.
Ist er ungesund, im Backoff oder liefert er einen Fehler, bricht die Kette
mit ``ProviderUnavailableError`` (bzw. ``SymbolNotFound``) ab, und der
Provider wird als ungesund markiert. Nur mit dem expliziten Schalter
``allow_fallback_from_authoritative=True`` (Policy-Hook fuer die
Tenant-Konfiguration in BBG-2; Default aus) springen die folgenden Provider
ein, und jedes Ergebnis traegt dann ``source`` UND ``fallback_reason``.
"""
from __future__ import annotations

import dataclasses
import logging
from datetime import date as Date
from typing import Any, Iterable

from .base import Bar, MarketDataProvider, ProductInfo
from .exceptions import (
    MarketDataError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
    SymbolNotFound,
)
from .health import HealthState

logger = logging.getLogger(__name__)

AUTHORITATIVE_PROVIDER_UNAVAILABLE = "AUTHORITATIVE_PROVIDER_UNAVAILABLE"


def _is_authoritative(provider: MarketDataProvider) -> bool:
    return bool(getattr(provider, "authoritative", False))


class MarketDataAggregator:
    """Sequentieller Fallback ueber eine Liste von MarketDataProvidern.

    Reihenfolge entscheidet Prioritaet (Index 0 = Primary).
    """

    def __init__(
        self,
        providers: Iterable[MarketDataProvider],
        unhealthy_ttl_seconds: int = 300,
        health_registry: Any | None = None,
        allow_fallback_from_authoritative: bool = False,
    ) -> None:
        self._providers: list[MarketDataProvider] = list(providers)
        self._health = HealthState(unhealthy_ttl_seconds=unhealthy_ttl_seconds)
        self._health_registry = health_registry
        self._allow_fallback_from_authoritative = bool(allow_fallback_from_authoritative)

    @property
    def providers(self) -> list[MarketDataProvider]:
        return list(self._providers)

    @property
    def health(self) -> HealthState:
        return self._health

    @property
    def allow_fallback_from_authoritative(self) -> bool:
        return self._allow_fallback_from_authoritative

    def _record_unhealthy(self, provider: MarketDataProvider, action_name: str, exc: BaseException) -> None:
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
        except Exception:  # noqa: BLE001 - observation must never affect pricing
            logger.debug("provider-health registry unhealthy write failed", exc_info=True)

    def _record_healthy(self, provider: MarketDataProvider, action_name: str) -> None:
        if self._health_registry is None:
            return
        try:
            self._health_registry.mark_healthy(provider.name, operation=action_name)
        except Exception:  # noqa: BLE001
            logger.debug("provider-health registry healthy write failed", exc_info=True)

    # ------------------------------------------------------------------ #
    # Massgebliche Quellen (BBG-1)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _unavailable_from(provider: MarketDataProvider, exc: BaseException | None, detail: str) -> ProviderUnavailableError:
        if isinstance(exc, ProviderUnavailableError):
            return exc
        code = getattr(exc, "code", None) or AUTHORITATIVE_PROVIDER_UNAVAILABLE
        message = f"[{code}] Massgebliche Quelle {provider.name} nicht verfuegbar: {detail}"
        return ProviderUnavailableError(message, code=code, provider=provider.name)

    def _authoritative_failed(
        self,
        provider: MarketDataProvider,
        exc: BaseException | None,
        detail: str,
    ) -> str:
        """Massgebliche Quelle ausgefallen: ohne Policy hart abbrechen,
        mit Policy den sichtbaren Fallback-Grund zurueckgeben."""
        if isinstance(exc, SymbolNotFound):
            if not self._allow_fallback_from_authoritative:
                raise exc
            return f"{provider.name}: SYMBOL_NOT_FOUND: {exc}"
        unavailable = self._unavailable_from(provider, exc, detail)
        if not self._allow_fallback_from_authoritative:
            if unavailable is exc:
                raise unavailable
            raise unavailable from exc
        return f"{provider.name}: {unavailable.code}: {unavailable}"

    def _candidates(self, action_name: str) -> tuple[list[MarketDataProvider], list[str]]:
        """Provider in Reihenfolge, gefiltert auf currently-healthy.

        Liefert zusaetzlich die Fallback-Gruende fuer uebersprungene
        massgebliche Provider (nur bei aktiver Fallback-Policy, sonst
        wird hier bereits abgebrochen).
        """
        result: list[MarketDataProvider] = []
        reasons: list[str] = []
        for p in self._providers:
            authoritative = _is_authoritative(p)
            if not self._health.is_healthy(p.name):
                if authoritative:
                    last = getattr(p, "last_unavailable_error", None)
                    reasons.append(self._authoritative_failed(p, last, "Provider ist im Health-Backoff"))
                continue
            try:
                healthy = bool(p.is_healthy())
                health_exc: BaseException | None = None
            except Exception as exc:  # noqa: BLE001 - defensive
                healthy = False
                health_exc = exc
            if not healthy:
                if authoritative:
                    last = getattr(p, "last_unavailable_error", None) or health_exc
                    unavailable = self._unavailable_from(p, last, "Health-Check fehlgeschlagen")
                    self._health.mark_unhealthy(p.name)
                    self._record_unhealthy(p, action_name, unavailable)
                    reasons.append(self._authoritative_failed(p, unavailable, "Health-Check fehlgeschlagen"))
                continue
            result.append(p)
        return result, reasons

    @staticmethod
    def _mark_fallback(result: Any, reasons: list[str]) -> Any:
        if not reasons:
            return result
        reason = "; ".join(reasons)
        if isinstance(result, (Bar, ProductInfo)):
            return dataclasses.replace(result, fallback_reason=reason)
        if isinstance(result, list):
            return [
                dataclasses.replace(item, fallback_reason=reason) if isinstance(item, Bar) else item
                for item in result
            ]
        return result

    def _call_chain(self, action_name: str, action):
        """Generischer Fallback-Loop. action(provider) liefert Result oder
        wirft. Sammelt letzte Exception fuer Re-Raise.
        """
        candidates, reasons = self._candidates(action_name)
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
                self._record_unhealthy(provider, action_name, exc)
                last_exc = exc
                if _is_authoritative(provider):
                    reasons.append(self._authoritative_failed(provider, exc, str(exc)))
                continue
            except SymbolNotFound as exc:
                # SymbolNotFound: weitermachen, Provider bleibt healthy
                last_exc = exc
                if _is_authoritative(provider):
                    reasons.append(self._authoritative_failed(provider, exc, str(exc)))
                continue
            except ProviderError as exc:
                logger.warning(
                    "%s: %s provider error (%s)", action_name, provider.name, exc,
                )
                self._health.mark_unhealthy(provider.name)
                self._record_unhealthy(provider, action_name, exc)
                last_exc = exc
                if _is_authoritative(provider):
                    reasons.append(self._authoritative_failed(provider, exc, str(exc)))
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "%s: %s unexpected error (%s)", action_name, provider.name, exc,
                )
                self._health.mark_unhealthy(provider.name)
                self._record_unhealthy(provider, action_name, exc)
                last_exc = exc
                if _is_authoritative(provider):
                    reasons.append(self._authoritative_failed(provider, exc, str(exc)))
                continue
            # Erfolg: Provider bleibt/wird healthy
            self._health.mark_healthy(provider.name)
            self._record_healthy(provider, action_name)
            return self._mark_fallback(result, reasons)
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
        action_name = f"get_history({symbol})"
        candidates, reasons = self._candidates(action_name)
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
                self._record_unhealthy(provider, action_name, exc)
                last_exc = exc
                if _is_authoritative(provider):
                    reasons.append(self._authoritative_failed(provider, exc, str(exc)))
                continue
            except SymbolNotFound as exc:
                last_exc = exc
                if _is_authoritative(provider):
                    reasons.append(self._authoritative_failed(provider, exc, str(exc)))
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "get_history(%s): %s unexpected (%s)", symbol, provider.name, exc,
                )
                self._health.mark_unhealthy(provider.name)
                self._record_unhealthy(provider, action_name, exc)
                last_exc = exc
                if _is_authoritative(provider):
                    reasons.append(self._authoritative_failed(provider, exc, str(exc)))
                continue
            self._health.mark_healthy(provider.name)
            self._record_healthy(provider, action_name)
            if result:
                return self._mark_fallback(result, reasons)
            # leere Liste: weiter zum naechsten Provider, aber keinen Fehler werfen
            last_exc = SymbolNotFound(f"{provider.name}: leeres history fuer {symbol}")
            if _is_authoritative(provider):
                # Leere Antwort der massgeblichen Quelle ist ein legitimes
                # Ergebnis (leerer Bereich), kein Anlass fuer einen Fallback.
                return []
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
