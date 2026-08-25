"""Provider-Interface fuer Macro-Time-Series.

MacroPoint = (date, value, series_code, source) — frozen.
MacroProvider liefert eine sortierte Liste solcher Punkte pro
get_series-Aufruf.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date as Date
from decimal import Decimal


@dataclass(frozen=True)
class MacroPoint:
    """Ein Zeitreihen-Punkt."""
    date: Date
    value: Decimal
    series_code: str
    source: str = "unknown"


class MacroProvider(ABC):
    """Abstract-Class fuer Macro-Time-Series-Provider.

    Provider-Beispiele: FRED, ECB SDW, SNB Daten-Portal, OECD Stats.
    Series-Codes sind provider-spezifisch — wir mappen sie nicht.
    """

    name: str = "abstract"

    @abstractmethod
    def get_series(
        self,
        series_code: str,
        start: Date,
        end: Date,
    ) -> list[MacroPoint]:
        """Time-Series fuer einen Code im Datumsbereich [start, end].

        Liefert sortierte Liste (aufsteigend nach date).
        Leere Liste wenn keine Daten verfuegbar (statt Exception).
        Raises:
            ProviderError: Netzwerk / 5xx / Parsing
            RateLimitError: Provider-Limit erreicht
        """

    def is_healthy(self) -> bool:
        """Default True; Provider koennen override."""
        return True
