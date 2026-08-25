"""Legacy-Compat Layer fuer den Multi-Source-Aggregator.

Zweck: Drop-In-Replacement fuer services.twelvedata_client.
fetch_twelvedata_latest_prices(). Gleiche Signatur, gleiche Output-
Struktur, aber unter der Haube laeuft der MarketDataAggregator (P5) +
Cache (P6) statt direkt TwelveData.

Bestehende Aufrufer in price_updater.py koennen schrittweise migriert
werden via:

    # Alte Variante (bleibt funktional):
    from services.twelvedata_client import fetch_twelvedata_latest_prices
    resolved, failures = fetch_twelvedata_latest_prices(symbols)

    # Neue Variante (Multi-Source):
    from services.market_data.legacy_compat import fetch_latest_prices_via_aggregator
    resolved, failures = fetch_latest_prices_via_aggregator(symbols)

Output-Format:
    resolved = {
        "UBSG.SW": {
            "price_date": "2026-05-08",       # ISO
            "price_rappen": 2875,             # Close * 100 als int
            "source": "yfinance|stooq|...",
        },
        ...
    }
    failures = {"XX0000": "Provider error message"}
"""
from __future__ import annotations

import logging
from datetime import date as Date
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .aggregator import MarketDataAggregator
from .exceptions import ProviderError, RateLimitError, SymbolNotFound

logger = logging.getLogger(__name__)


def _to_rappen(amount: Decimal) -> int:
    """Decimal-Close zu int-rappen (Close * 100, gerundet)."""
    return int((amount * Decimal(100)).quantize(Decimal("1")))


def fetch_latest_prices_via_aggregator(
    symbols: list[str],
    on_date: Date | None = None,
    aggregator: MarketDataAggregator | None = None,
    cached: Any | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Drop-in Replacement fuer fetch_twelvedata_latest_prices.

    Args:
        symbols: Liste der Symbol-Strings (z.B. ['UBSG.SW', 'AAPL']).
        on_date: optional Datum (default heute UTC).
        aggregator: optional vorgebauter Aggregator (sonst build_default).
        cached: optional CachedAggregator (sonst direkt Aggregator).

    Returns:
        (resolved, failures) wie bei twelvedata_client.

    Notiz: aggregator hat eingebauten Fallback (yfinance -> stooq -> ...)
    inklusive Cache, daher pro Symbol nur 1 Aufruf.
    """
    cleaned = [s.strip() for s in (symbols or []) if s and s.strip()]
    if not cleaned:
        return {}, {}

    target_date = on_date or datetime.now(timezone.utc).date()
    fetcher = cached if cached is not None else aggregator
    if fetcher is None:
        # Lazy default-Aggregator (ohne Cache; Cache braucht DB-Session-Factory)
        from .factory import build_default_aggregator
        fetcher = build_default_aggregator()

    resolved: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}

    for symbol in cleaned:
        try:
            bar = fetcher.get_eod(symbol, target_date)
        except SymbolNotFound as exc:
            failures[symbol] = f"symbol-not-found: {exc}"
            continue
        except RateLimitError as exc:
            failures[symbol] = f"rate-limited: {exc}"
            continue
        except ProviderError as exc:
            failures[symbol] = f"provider-error: {exc}"
            continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("aggregator unexpected error for %s: %s", symbol, exc)
            failures[symbol] = f"unexpected: {exc}"
            continue
        try:
            price_rappen = _to_rappen(Decimal(bar.close))
        except Exception as exc:  # noqa: BLE001
            failures[symbol] = f"price-conversion: {exc}"
            continue
        resolved[symbol] = {
            "price_date": bar.date.isoformat(),
            "price_rappen": price_rappen,
            "source": bar.source or "aggregator",
        }
    return resolved, failures
