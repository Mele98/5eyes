"""ETF-Master-Daten-Interface.

ETFInfo erweitert ProductInfo um ETF-spezifische Felder (TER, AUM,
Replication-Method, Domicile, Distribution-Policy).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ETFInfo:
    """ETF/Fonds Master-Daten."""
    isin: str | None
    ticker: str | None
    name: str | None
    ter_bps: int | None = None        # Total Expense Ratio in bps (z.B. 7 = 0.07%)
    aum_chf: Decimal | None = None    # Assets under Management in CHF
    domicile: str | None = None       # 'IE', 'LU', 'CH', etc.
    replication: str | None = None    # 'physical' | 'synthetic' | 'sampling'
    distribution: str | None = None   # 'accumulating' | 'distributing'
    fund_currency: str | None = None  # CHF/EUR/USD
    asset_class: str | None = None    # 'Aktien' | 'Obligationen' | ...
    region: str | None = None         # 'Schweiz' | 'Welt' | 'EM' | ...
    source: str = "unknown"


class ETFProvider(ABC):
    """Abstract-Class fuer ETF-Master-Daten-Provider."""

    name: str = "abstract"

    @abstractmethod
    def lookup_isin(self, isin: str) -> ETFInfo:
        """Liefert ETFInfo fuer eine ISIN.

        Raises:
            SymbolNotFound: ETF unbekannt
            ProviderError: andere Fehler
        """

    def is_healthy(self) -> bool:
        return True
