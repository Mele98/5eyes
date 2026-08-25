"""Macro-Pipeline (P9): Zeitreihen aus FRED, ECB, SNB.

Eigenes Interface neben MarketDataProvider, weil Macro-Daten andere
Semantik haben (Time-Series mit beliebigem Intervall, nicht OHLCV-Bars).
"""
from __future__ import annotations

from .base import MacroPoint, MacroProvider
from .providers import (
    ECBMacroProvider,
    FREDMacroProvider,
    SNBMacroProvider,
)

__all__ = [
    "MacroPoint",
    "MacroProvider",
    "ECBMacroProvider",
    "FREDMacroProvider",
    "SNBMacroProvider",
]
