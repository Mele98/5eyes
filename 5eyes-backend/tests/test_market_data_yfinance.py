"""Phase 2 Tests: YFinanceProvider.

Mocked yfinance.Ticker (kein Netzwerk). Network-Tests sind separat
markiert und skipped by default (laufen nur via -m network).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pandas as pd

from services.market_data import (
    Bar,
    ProductInfo,
    ProviderError,
    RateLimitError,
    SymbolNotFound,
    YFinanceProvider,
)
from services.market_data.providers._ticker_suffix import yahoo_ticker


# ============================================================================
# Ticker-Suffix
# ============================================================================


@pytest.mark.parametrize("ticker,exchange,expected", [
    ("UBSG", "SIX", "UBSG.SW"),
    ("UBSG", "CH", "UBSG.SW"),
    ("UBSG.SW", "SIX", "UBSG.SW"),  # bereits suffixiert
    ("AAPL", "NYSE", "AAPL"),       # US: kein Suffix
    ("AAPL", "US", "AAPL"),
    ("VOW3", "DE", "VOW3.DE"),
    ("BMW", "FRA", "BMW.F"),
    ("VOD", "LON", "VOD.L"),
    ("VOD", None, "VOD"),           # kein Exchange -> unveraendert
    ("VOD", "ZZZ", "VOD"),          # unbekannter Exchange -> unveraendert
])
def test_yahoo_ticker_suffix(ticker, exchange, expected):
    assert yahoo_ticker(ticker, exchange) == expected


def test_yahoo_ticker_empty():
    assert yahoo_ticker("") == ""


# ============================================================================
# Helpers fuer Mock
# ============================================================================


def _mock_history_df(rows: list[tuple]) -> pd.DataFrame:
    """Baut ein yfinance-typisches DataFrame.
    rows: list von (date, open, high, low, close, adj_close, volume)
    """
    if not rows:
        return pd.DataFrame()
    dates = [pd.Timestamp(r[0]) for r in rows]
    df = pd.DataFrame(
        {
            "Open": [r[1] for r in rows],
            "High": [r[2] for r in rows],
            "Low": [r[3] for r in rows],
            "Close": [r[4] for r in rows],
            "Adj Close": [r[5] for r in rows],
            "Volume": [r[6] for r in rows],
        },
        index=pd.DatetimeIndex(dates, name="Date"),
    )
    return df


def _make_mock_ticker(history_df, info=None, fast_currency=None):
    """Erstellt ein Mock-Objekt das wie yfinance.Ticker aussieht."""
    fast = SimpleNamespace(currency=fast_currency) if fast_currency else None
    obj = SimpleNamespace(
        history=lambda **kwargs: history_df,
        info=info or {},
        fast_info=fast,
    )
    return obj


# ============================================================================
# get_eod
# ============================================================================


def test_get_eod_returns_bar_for_ubs():
    df = _mock_history_df([
        (date(2026, 5, 8), 28.50, 28.90, 28.30, 28.75, 28.75, 1_500_000),
    ])
    mock_ticker = _make_mock_ticker(df, fast_currency="CHF")
    provider = YFinanceProvider()
    with patch.object(provider, "_ticker_obj", return_value=mock_ticker):
        bar = provider.get_eod("UBSG.SW", date(2026, 5, 8))
    assert isinstance(bar, Bar)
    assert bar.symbol == "UBSG.SW"
    assert bar.date == date(2026, 5, 8)
    assert bar.close == Decimal("28.75")
    assert bar.currency == "CHF"
    assert bar.volume == 1_500_000
    assert bar.source == "yfinance"


def test_get_eod_falls_back_to_last_trading_day_on_weekend():
    """Wenn on_date Sonntag ist, liefert yfinance den letzten Handelstag."""
    # Sonntag 2026-05-10 -> letzter Handelstag Freitag 2026-05-08
    df = _mock_history_df([
        (date(2026, 5, 6), 28.10, 28.40, 28.00, 28.20, 28.20, 1_200_000),
        (date(2026, 5, 7), 28.20, 28.60, 28.15, 28.55, 28.55, 1_400_000),
        (date(2026, 5, 8), 28.50, 28.90, 28.30, 28.75, 28.75, 1_500_000),
    ])
    mock_ticker = _make_mock_ticker(df, fast_currency="CHF")
    provider = YFinanceProvider()
    with patch.object(provider, "_ticker_obj", return_value=mock_ticker):
        bar = provider.get_eod("UBSG.SW", date(2026, 5, 10))  # Sonntag
    # letzte Zeile == Freitag
    assert bar.date == date(2026, 5, 8)
    assert bar.close == Decimal("28.75")


def test_get_eod_empty_df_raises_symbol_not_found():
    df = _mock_history_df([])
    mock_ticker = _make_mock_ticker(df)
    provider = YFinanceProvider()
    with patch.object(provider, "_ticker_obj", return_value=mock_ticker):
        with pytest.raises(SymbolNotFound):
            provider.get_eod("UNKNOWN", date(2026, 5, 8))


def test_get_eod_provider_error_on_http_failure():
    def raise_http(**kwargs):
        raise RuntimeError("network down")
    mock_ticker = SimpleNamespace(history=raise_http, info={}, fast_info=None)
    provider = YFinanceProvider()
    with patch.object(provider, "_ticker_obj", return_value=mock_ticker):
        with pytest.raises(ProviderError):
            provider.get_eod("UBSG.SW", date(2026, 5, 8))


def test_get_eod_rate_limit_error_classified():
    def raise_rate_limit(**kwargs):
        raise RuntimeError("Too Many Requests: rate limit exceeded")
    mock_ticker = SimpleNamespace(history=raise_rate_limit, info={}, fast_info=None)
    provider = YFinanceProvider()
    with patch.object(provider, "_ticker_obj", return_value=mock_ticker):
        with pytest.raises(RateLimitError):
            provider.get_eod("UBSG.SW", date(2026, 5, 8))


# ============================================================================
# get_history
# ============================================================================


def test_get_history_returns_list_of_bars():
    df = _mock_history_df([
        (date(2026, 5, 6), 28.10, 28.40, 28.00, 28.20, 28.20, 1_200_000),
        (date(2026, 5, 7), 28.20, 28.60, 28.15, 28.55, 28.55, 1_400_000),
        (date(2026, 5, 8), 28.50, 28.90, 28.30, 28.75, 28.75, 1_500_000),
    ])
    mock_ticker = _make_mock_ticker(df, fast_currency="CHF")
    provider = YFinanceProvider()
    with patch.object(provider, "_ticker_obj", return_value=mock_ticker):
        bars = provider.get_history("UBSG.SW", date(2026, 5, 6), date(2026, 5, 8))
    assert len(bars) == 3
    assert all(isinstance(b, Bar) for b in bars)
    assert [b.date for b in bars] == [date(2026, 5, 6), date(2026, 5, 7), date(2026, 5, 8)]


def test_get_history_empty_when_end_before_start():
    provider = YFinanceProvider()
    bars = provider.get_history("UBSG.SW", date(2026, 5, 8), date(2026, 5, 1))
    assert bars == []


def test_get_history_returns_empty_list_when_no_data():
    df = _mock_history_df([])
    mock_ticker = _make_mock_ticker(df)
    provider = YFinanceProvider()
    with patch.object(provider, "_ticker_obj", return_value=mock_ticker):
        bars = provider.get_history("UNKNOWN", date(2026, 5, 1), date(2026, 5, 8))
    assert bars == []


# ============================================================================
# lookup_isin
# ============================================================================


def test_lookup_isin_raises_symbol_not_found():
    """yfinance unterstuetzt keine Reverse-ISIN-Suche; Phase 8 (OpenFIGI)
    liefert das. Provider muss klar SymbolNotFound werfen."""
    provider = YFinanceProvider()
    with pytest.raises(SymbolNotFound):
        provider.lookup_isin("CH0244767585")


# ============================================================================
# is_healthy
# ============================================================================


def test_is_healthy_default_true():
    assert YFinanceProvider().is_healthy() is True


# ============================================================================
# Network-Integration (skipped by default)
# ============================================================================


@pytest.mark.network
@pytest.mark.skip(reason="network-test, manuell mit -m network ausfuehren")
def test_real_yfinance_call_for_ubsg():
    """Echter Aufruf gegen Yahoo. Nur fuer manuelle Verifikation."""
    provider = YFinanceProvider()
    bar = provider.get_eod("UBSG.SW", date.today() - timedelta(days=5))
    assert bar.currency == "CHF"
    assert bar.close > 0
