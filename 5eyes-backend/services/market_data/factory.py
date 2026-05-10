"""Factory zum Bauen eines MarketDataAggregators aus den Settings.

Liest `MARKET_DATA_PROVIDERS` aus config.settings (komma-separierte
Reihenfolge), instanziiert die entsprechenden Provider und liefert einen
fertig konfigurierten Aggregator.

Provider-Map:
- 'yfinance'      -> YFinanceProvider()
- 'stooq'         -> StooqProvider()
- 'alphavantage'  -> AlphaVantageProvider(api_key=settings.alphavantage_api_key)
- (spaeter) 'twelvedata' -> TwelveDataProvider(api_key=settings.twelvedata_api_key)
"""
from __future__ import annotations

import logging

from .aggregator import MarketDataAggregator
from .base import MarketDataProvider
from .providers import (
    AlphaVantageProvider,
    StooqProvider,
    TwelveDataProvider,
    YFinanceProvider,
)

logger = logging.getLogger(__name__)


def _provider_by_name(name: str, settings: object) -> MarketDataProvider | None:
    name = (name or "").strip().lower()
    if not name:
        return None
    if name == "yfinance":
        return YFinanceProvider()
    if name == "stooq":
        return StooqProvider()
    if name == "alphavantage":
        return AlphaVantageProvider(
            api_key=getattr(settings, "alphavantage_api_key", None),
        )
    if name == "twelvedata":
        return TwelveDataProvider(
            api_key=getattr(settings, "twelvedata_api_key", None),
        )
    logger.warning("Unbekannter Provider in MARKET_DATA_PROVIDERS: %s", name)
    return None


def build_default_aggregator(settings: object | None = None) -> MarketDataAggregator:
    """Baut den Aggregator anhand der Settings (oder importierter Default).

    Wenn keine Provider konfiguriert sind, wird `yfinance,stooq` als
    konservativer Fallback genutzt.
    """
    if settings is None:
        from config import settings as _global_settings  # type: ignore[import-not-found]
        settings = _global_settings
    raw = getattr(settings, "market_data_providers", "") or ""
    parts = [p for p in (s.strip() for s in raw.split(",")) if p]
    if not parts:
        parts = ["yfinance", "stooq"]
    providers: list[MarketDataProvider] = []
    for part in parts:
        provider = _provider_by_name(part, settings)
        if provider is not None:
            providers.append(provider)
    if not providers:
        # Letzter Strohhalm: yfinance + stooq direkt instanziieren
        providers = [YFinanceProvider(), StooqProvider()]
    ttl = int(getattr(settings, "market_data_unhealthy_ttl_seconds", 300) or 300)
    return MarketDataAggregator(providers=providers, unhealthy_ttl_seconds=ttl)
