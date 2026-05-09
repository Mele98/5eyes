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
