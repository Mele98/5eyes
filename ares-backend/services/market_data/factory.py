"""Factory zum Bauen eines MarketDataAggregators aus den Settings.

Liest `MARKET_DATA_PROVIDERS` aus config.settings (komma-separierte
Reihenfolge) und baut daraus einen fertig konfigurierten Aggregator.

Die Provider-Aufloesung liegt in ``provider_registry``: eingebaute Provider
(yfinance, stooq, alphavantage, twelvedata) und per Entry-Point entdeckte
externe Provider werden zu einer kollisionsgeprueften Map vereinigt. Ein
explizit konfigurierter, aber nicht verfuegbarer Provider ist ein harter
Fehler (``ProviderConfigurationError``) — kein stiller Rueckfall. Nur ohne
Konfiguration gelten die Defaults `yfinance,stooq` (W2-804-02).
"""
from __future__ import annotations

from .aggregator import MarketDataAggregator
from .provider_registry import ProviderConfigurationError, resolve_providers

__all__ = ["ProviderConfigurationError", "build_default_aggregator"]


def build_default_aggregator(settings: object | None = None) -> MarketDataAggregator:
    """Baut den Aggregator anhand der Settings (oder importierter Default).

    Wenn keine Provider konfiguriert sind, wird `yfinance,stooq` genutzt.
    Ist eine Konfiguration vorhanden, muss jeder genannte Provider eindeutig
    verfuegbar sein, sonst ``ProviderConfigurationError`` (fail-closed).
    """
    if settings is None:
        from config import settings as _global_settings  # type: ignore[import-not-found]
        settings = _global_settings
    providers = resolve_providers(settings)
    ttl = int(getattr(settings, "market_data_unhealthy_ttl_seconds", 300) or 300)
    try:
        from .provider_health_registry import build_default_registry
        health_registry = build_default_registry()
    except Exception:  # noqa: BLE001 - registry is observational only
        health_registry = None
    return MarketDataAggregator(
        providers=providers,
        unhealthy_ttl_seconds=ttl,
        health_registry=health_registry,
    )
