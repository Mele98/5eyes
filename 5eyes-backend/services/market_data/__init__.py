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
from .aggregator import MarketDataAggregator
from .cache import CachedAggregator, DEFAULT_TTL_SECONDS
from .factory import build_default_aggregator
from .health import HealthState
from .macro import (
    ECBMacroProvider,
    FREDMacroProvider,
    MacroPoint,
    MacroProvider,
    SNBMacroProvider,
)
from .providers import (
    AlphaVantageProvider,
    OpenFIGIProvider,
    StooqProvider,
    YFinanceProvider,
)
from .validation import (
    DEFAULT_THRESHOLD_BPS,
    ProviderQuote,
    ValidationResult,
    validate_batch,
    validate_symbol,
)

__all__ = [
    "Bar",
    "MarketDataProvider",
    "ProductInfo",
    "MarketDataError",
    "ProviderError",
    "RateLimitError",
    "SymbolNotFound",
    "AlphaVantageProvider",
    "OpenFIGIProvider",
    "StooqProvider",
    "YFinanceProvider",
    "MarketDataAggregator",
    "CachedAggregator",
    "DEFAULT_TTL_SECONDS",
    "HealthState",
    "build_default_aggregator",
    "DEFAULT_THRESHOLD_BPS",
    "ProviderQuote",
    "ValidationResult",
    "validate_batch",
    "validate_symbol",
    "MacroPoint",
    "MacroProvider",
    "FREDMacroProvider",
    "ECBMacroProvider",
    "SNBMacroProvider",
]
