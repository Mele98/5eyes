"""Exception-Hierarchie fuer Market-Data-Provider.

Alle Provider-Fehler erben von MarketDataError. Spezifische Exceptions
erlauben dem Aggregator zwischen "weiter zum naechsten Provider" und
"harter Abbruch" zu unterscheiden.
"""
from __future__ import annotations


class MarketDataError(Exception):
    """Basisklasse fuer alle Market-Data-Probleme."""


class ProviderError(MarketDataError):
    """Genereller Provider-Fehler (Netzwerk, 5xx, Parsing).

    Aggregator soll bei diesem Fehler den naechsten Provider in der Chain
    versuchen.
    """


class RateLimitError(ProviderError):
    """Provider hat das Rate-Limit erreicht.

    Aggregator soll den naechsten Provider versuchen UND den aktuellen
    Provider fuer eine Weile als unhealthy markieren (Backoff).
    """


class SymbolNotFound(MarketDataError):
    """Das angefragte Symbol existiert beim Provider nicht.

    Bei diesem Fehler ist Provider-Fallback meist sinnlos: der Symbol-Code
    war wahrscheinlich falsch. Aggregator soll dennoch einen Fallback
    versuchen, weil verschiedene Provider unterschiedliche Symbol-Maps
    haben.
    """


class ProviderUnavailableError(ProviderError):
    """Die Quelle ist gar nicht erreichbar bzw. nicht betriebsbereit.

    BBG-1 (Audit 2026-11/06, B2/B3): z. B. Bloomberg ohne installiertes
    ``blpapi``, ohne laufendes Terminal/Session oder ohne Refdata-Service.
    Das ist ausdruecklich KEIN ``SymbolNotFound`` ("Symbol unbekannt"):
    der Aufrufer muss "Quelle nicht verfuegbar" sehen. ``code`` traegt einen
    maschinenlesbaren Grund (z. B. ``BLOOMBERG_SESSION_UNAVAILABLE``).

    Fuer massgebliche Provider (``MarketDataProvider.authoritative``) bricht
    der Aggregator bei diesem Fehler ab, statt still auf Gratisquellen
    zurueckzufallen.
    """

    def __init__(self, message: str, *, code: str = "PROVIDER_UNAVAILABLE", provider: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.provider = provider
