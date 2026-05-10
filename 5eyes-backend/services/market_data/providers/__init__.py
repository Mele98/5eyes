"""Konkrete MarketDataProvider-Implementierungen."""
from __future__ import annotations

from .stooq_provider import StooqProvider
from .yfinance_provider import YFinanceProvider

__all__ = [
    "StooqProvider",
    "YFinanceProvider",
]
