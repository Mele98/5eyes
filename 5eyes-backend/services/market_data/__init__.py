"""Multi-Source Market Data Aggregator (Phase 1).

Plan: docs/planning/2026-05-09-multi-source-data-aggregator-spec.md (folgt).
Memory: project_5eyes_data_pipeline.md.

Phase 1: Provider-Adapter-Pattern (Interface + Dataclasses + Exceptions).
Spaetere Phasen fuegen konkrete Provider hinzu (yfinance, stooq, alphavantage,
twelvedata, openfigi, fred, ecb, snb).
"""
from __future__ import annotations

from .base import (
    Bar,
    MarketDataProvider,
    ProductInfo,
)
from .exceptions import (
    MarketDataError,
    ProviderError,
    RateLimitError,
    SymbolNotFound,
)
from .providers import StooqProvider, YFinanceProvider

__all__ = [
    "Bar",
    "MarketDataProvider",
    "ProductInfo",
    "MarketDataError",
    "ProviderError",
    "RateLimitError",
    "SymbolNotFound",
    "StooqProvider",
    "YFinanceProvider",
]
