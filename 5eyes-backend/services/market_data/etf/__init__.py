"""ETF/Fonds-Master-Daten (P11): Scraper fuer Justetf + Swissfunddata.

WICHTIG — TOS-Hinweis:
- justetf.com Terms of Service verbieten automatisiertes Crawling
- swissfunddata.ch TOS-Status unklar
- Diese Scraper sind opt-in (env SCRAPE_ETF_DATA=true), default off
- Bei produktivem Einsatz: rate-limit sehr konservativ (5s/req)
- Bei FINIG-Lizenz spaeter: migration auf SIX Financial Information
  oder Morningstar Direct (cost ~CHF 8'000-15'000/Jahr)

Wofuer das hier gut ist: Inhouse-Berater braucht TER, AUM, Replication
fuer Sub-Allocation. Mit yfinance allein kriegst du diese Daten nicht.
"""
from __future__ import annotations

from .base import ETFInfo, ETFProvider
from .providers import (
    JustetfScraper,
    SwissfunddataScraper,
)

__all__ = [
    "ETFInfo",
    "ETFProvider",
    "JustetfScraper",
    "SwissfunddataScraper",
]
