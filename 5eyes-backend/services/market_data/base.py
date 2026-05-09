"""Provider-Interface fuer Market-Data-Quellen.

Ueberlegen: jeder Provider (yfinance, stooq, alphavantage, twelvedata, ...)
muss dieselben drei Operationen sauber liefern: EOD-Preis, History und
ID-Lookup. Mehr braucht der Aggregator vorerst nicht. FX-Spezifika kommen
ueber denselben get_eod-Pfad mit FX-Symbol-Konvention (z.B. 'EURCHF=X').

Die Datenklassen Bar/ProductInfo sind frozen (Wertobjekte). Preise sind
Decimal-basiert, damit kein Float-Drift in Audit-Pfaden entsteht.

Health-Check ist Default-True, jeder Provider kann das ueberschreiben.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date as Date
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class Bar:
    """Ein End-of-Day OHLC-Eintrag fuer ein Symbol.

    volume kann None sein, wenn der Provider kein Volumen liefert (z.B. FX).
    currency ist die Quotierungswaehrung (z.B. 'CHF' bei UBSG.SW).
    """
    symbol: str
    date: Date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    currency: str
    volume: Optional[int] = None
    adjusted_close: Optional[Decimal] = None
    source: str = "unknown"


@dataclass(frozen=True)
class ProductInfo:
    """Master-Daten zu einem Wertpapier.

    Mindestens isin oder ticker muss gesetzt sein. name ist meist gesetzt.
    Andere Felder sind Best-Effort, je nach Provider-Coverage.
    """
    isin: Optional[str]
    ticker: Optional[str]
    name: Optional[str]
    exchange: Optional[str] = None
    currency: Optional[str] = None
    asset_class: Optional[str] = None
    country: Optional[str] = None
    figi: Optional[str] = None
    source: str = "unknown"


class MarketDataProvider(ABC):
    """Abstract-Class fuer alle Market-Data-Quellen.

    Konkrete Implementierungen liegen in services/market_data/providers/.
    Aggregator (Phase 5) instantiiert eine Liste von Providern und ruft
    diese Methoden in Reihenfolge.

    Eine konkrete Implementierung MUSS:
    - eindeutigen `name` haben (z.B. 'yfinance', 'stooq')
    - get_eod liefern oder SymbolNotFound werfen
    - Provider-Fehler in ProviderError/RateLimitError mappen
    - is_healthy() True liefern wenn nutzbar (kein Default-Override noetig)
    """

    name: str = "abstract"

    @abstractmethod
    def get_eod(self, symbol: str, on_date: Date) -> Bar:
        """End-of-Day Bar fuer ein Symbol an einem konkreten Datum.

        Wenn das Datum auf einem Wochenende/Feiertag liegt, soll der
        Provider den letzten verfuegbaren Handelstag <= on_date liefern.
        Raises:
            SymbolNotFound: Symbol unbekannt
            RateLimitError: Provider-Limit erreicht
            ProviderError: alle anderen Fehler (Netz, Parsing, 5xx)
        """

    @abstractmethod
    def get_history(self, symbol: str, start: Date, end: Date) -> list[Bar]:
        """Bars im Datumsbereich [start, end] (inklusive beider).

        Liefert leere Liste statt SymbolNotFound, wenn Bereich leer ist.
        """

    @abstractmethod
    def lookup_isin(self, isin: str) -> ProductInfo:
        """Master-Daten fuer eine ISIN.

        Raises:
            SymbolNotFound: ISIN beim Provider unbekannt
            ProviderError: andere Fehler
        """

    def is_healthy(self) -> bool:
        """Schneller Health-Check (default True).

        Konkrete Provider koennen z.B. einen leichten Ping-Call machen.
        Aggregator nutzt das fuer Fallback-Reihenfolge.
        """
        return True
