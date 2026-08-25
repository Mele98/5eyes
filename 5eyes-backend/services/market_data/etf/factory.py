"""Factory zum Bauen eines ETFAggregators aus den Settings.

Analog zu ../factory.py (MarketDataAggregator), aber fuer ETF-Master-
Daten (TER, AUM, Replication -- siehe ETFInfo).

Liest (sofern vorhanden) folgende optionale Settings:
- `scrape_etf_data` (bool): globaler TOS-Opt-in-Schalter fuer beide
  Scraper. Default False (kein Netzwerkverkehr, wie bisher).
- `market_data_etf_providers` (str, komma-separiert): Reihenfolge der
  ETF-Provider. Gueltige Werte: 'justetf', 'swissfunddata'.
  Default: 'justetf,swissfunddata' (justetf primary).
- `etf_scraper_rate_delay_seconds` (int): Mindestpause zwischen Requests
  je Scraper. Default 5s (konservativ, wie bisheriger Scraper-Default).
- `market_data_unhealthy_ttl_seconds` (int): geteilt mit dem
  Equity-Aggregator, Default 300s.

Alle Settings sind optional (via getattr mit Default) -- config.py muss
dafuer nicht angepasst werden.
"""
from __future__ import annotations

import logging

from .aggregator import ETFAggregator
from .base import ETFProvider
from .providers import JustetfScraper, SwissfunddataScraper

logger = logging.getLogger(__name__)


def _etf_provider_by_name(name: str, *, enabled: bool, rate_delay: int) -> ETFProvider | None:
    key = (name or "").strip().lower()
    if not key:
        return None
    if key == "justetf":
        return JustetfScraper(enabled=enabled, rate_delay_seconds=rate_delay)
    if key == "swissfunddata":
        return SwissfunddataScraper(enabled=enabled, rate_delay_seconds=rate_delay)
    logger.warning("Unbekannter ETF-Provider in market_data_etf_providers: %s", name)
    return None


def build_default_etf_aggregator(settings: object | None = None) -> ETFAggregator:
    """Baut den ETF-Aggregator anhand der Settings (oder importierter Default).

    Wenn keine ETF-Provider konfiguriert sind, wird `justetf,swissfunddata`
    als konservativer Fallback genutzt (gleiche Reihenfolge wie bisher
    dokumentiert in etf/__init__.py).
    """
    if settings is None:
        from config import settings as _global_settings  # type: ignore[import-not-found]
        settings = _global_settings
    enabled = bool(getattr(settings, "scrape_etf_data", False))
    rate_delay = int(getattr(settings, "etf_scraper_rate_delay_seconds", 5) or 5)
    raw = getattr(settings, "market_data_etf_providers", "") or ""
    parts = [p for p in (s.strip() for s in raw.split(",")) if p]
    if not parts:
        parts = ["justetf", "swissfunddata"]
    providers: list[ETFProvider] = []
    for part in parts:
        provider = _etf_provider_by_name(part, enabled=enabled, rate_delay=rate_delay)
        if provider is not None:
            providers.append(provider)
    if not providers:
        # Letzter Strohhalm: beide Scraper direkt instanziieren
        providers = [
            JustetfScraper(enabled=enabled, rate_delay_seconds=rate_delay),
            SwissfunddataScraper(enabled=enabled, rate_delay_seconds=rate_delay),
        ]
    ttl = int(getattr(settings, "market_data_unhealthy_ttl_seconds", 300) or 300)
    try:
        from ..provider_health_registry import build_default_registry
        health_registry = build_default_registry()
    except Exception:  # noqa: BLE001 - registry is observational only
        health_registry = None
    return ETFAggregator(
        providers=providers,
        unhealthy_ttl_seconds=ttl,
        health_registry=health_registry,
    )
