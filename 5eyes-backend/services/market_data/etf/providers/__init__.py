"""ETF-Scraper-Implementierungen.

Opt-in via env SCRAPE_ETF_DATA=true. Default off (TOS-Compliance).
"""
from __future__ import annotations

from .justetf import JustetfScraper
from .swissfunddata import SwissfunddataScraper

__all__ = [
    "JustetfScraper",
    "SwissfunddataScraper",
]
