"""Phase 12 Tests: TwelveDataProvider."""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.market_data import (
    Bar,
    ProviderError,
    RateLimitError,
    SymbolNotFound,
    TwelveDataProvider,
    build_default_aggregator,
)


def _mock_response(payload, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json = lambda: payload
    return resp


def _mock_session(payload, status: int = 200):
    session = MagicMock()
    session.get.return_value = _mock_response(payload, status)
    return session


_OK = {
    "meta": {"currency": "CHF", "symbol": "UBSG.SW"},
    "values": [
        {"datetime": "2026-05-08", "open": "28.50", "high": "28.90",
         "low": "28.30", "close": "28.75", "volume": "1500000"},
        {"datetime": "2026-05-07", "open": "28.20", "high": "28.60",
         "low": "28.15", "close": "28.55", "volume": "1400000"},
        {"datetime": "2026-05-06", "open": "28.10", "high": "28.40",
         "low": "28.00", "close": "28.20", "volume": "1200000"},
    ],
    "status": "ok",
}


# ============================================================================
# Key handling
# ============================================================================


def test_provider_without_key_unhealthy():
    p = TwelveDataProvider()
    assert p.has_key is False
    assert p.is_healthy() is False


def test_provider_with_key_healthy():
    p = TwelveDataProvider(api_key="K")
    assert p.has_key is True
    assert p.is_healthy() is True


def test_get_eod_without_key_raises_provider_error():
    p = TwelveDataProvider(api_key=None)
    with pytest.raises(ProviderError):
        p.get_eod("UBSG.SW", date(2026, 5, 8))


# ============================================================================
# get_eod
# ============================================================================


def test_get_eod_returns_bar():
    session = _mock_session(_OK)
    p = TwelveDataProvider(api_key="K", session=session)
    bar = p.get_eod("UBSG.SW", date(2026, 5, 8))
    assert isinstance(bar, Bar)
    assert bar.date == date(2026, 5, 8)
    assert bar.close == Decimal("28.75")
    assert bar.currency == "CHF"
    assert bar.volume == 1_500_000
    assert bar.source == "twelvedata"


def test_get_eod_weekend_fallback():
    """Sonntag -> letzter Handelstag (TwelveData liefert absteigend)."""
    session = _mock_session(_OK)
    p = TwelveDataProvider(api_key="K", session=session)
    bar = p.get_eod("UBSG.SW", date(2026, 5, 10))
    assert bar.date == date(2026, 5, 8)


def test_get_eod_status_error_404_raises_symbol_not_found():
    payload = {"status": "error", "message": "symbol not found", "code": 404}
    session = _mock_session(payload)
    p = TwelveDataProvider(api_key="K", session=session)
    with pytest.raises(SymbolNotFound):
        p.get_eod("XXX", date(2026, 5, 8))


def test_get_eod_status_error_rate_limit_raises_rate_limit():
    payload = {"status": "error", "message": "API credits limit exceeded", "code": 429}
    session = _mock_session(payload)
    p = TwelveDataProvider(api_key="K", session=session)
    with pytest.raises(RateLimitError):
        p.get_eod("UBSG.SW", date(2026, 5, 8))


def test_get_eod_http_429_raises_rate_limit():
    session = _mock_session({}, status=429)
    p = TwelveDataProvider(api_key="K", session=session)
    with pytest.raises(RateLimitError):
        p.get_eod("UBSG.SW", date(2026, 5, 8))


def test_get_eod_http_500_raises_provider_error():
    session = _mock_session({}, status=500)
    p = TwelveDataProvider(api_key="K", session=session)
    with pytest.raises(ProviderError):
        p.get_eod("UBSG.SW", date(2026, 5, 8))


def test_get_eod_no_values_raises_symbol_not_found():
    payload = {"meta": {"currency": "CHF"}, "values": [], "status": "ok"}
    session = _mock_session(payload)
    p = TwelveDataProvider(api_key="K", session=session)
    with pytest.raises(SymbolNotFound):
        p.get_eod("XXX", date(2026, 5, 8))


def test_get_eod_network_exception_raises_provider_error():
    session = MagicMock()
    session.get.side_effect = requests.RequestException("timeout")
    p = TwelveDataProvider(api_key="K", session=session)
    with pytest.raises(ProviderError):
        p.get_eod("UBSG.SW", date(2026, 5, 8))


# ============================================================================
# get_history
# ============================================================================


def test_get_history_returns_sorted_list():
    session = _mock_session(_OK)
    p = TwelveDataProvider(api_key="K", session=session)
    bars = p.get_history("UBSG.SW", date(2026, 5, 6), date(2026, 5, 8))
    assert len(bars) == 3
    # Aufsteigend sortiert (TwelveData liefert absteigend)
    assert [b.date for b in bars] == [date(2026, 5, 6), date(2026, 5, 7), date(2026, 5, 8)]


def test_get_history_empty_when_end_before_start():
    p = TwelveDataProvider(api_key="K", session=MagicMock())
    assert p.get_history("UBSG.SW", date(2026, 5, 8), date(2026, 5, 1)) == []


def test_get_history_returns_empty_on_symbol_not_found():
    payload = {"status": "error", "message": "symbol not found", "code": 404}
    session = _mock_session(payload)
    p = TwelveDataProvider(api_key="K", session=session)
    bars = p.get_history("XXX", date(2026, 5, 1), date(2026, 5, 8))
    assert bars == []


# ============================================================================
# lookup_isin
# ============================================================================


def test_lookup_isin_not_supported():
    p = TwelveDataProvider(api_key="K", session=MagicMock())
    with pytest.raises(SymbolNotFound):
        p.lookup_isin("CH0244767585")


# ============================================================================
# Factory-Integration
# ============================================================================


def test_factory_includes_twelvedata_with_key():
    fake_settings = SimpleNamespace(
        market_data_providers="twelvedata,yfinance",
        alphavantage_api_key=None,
        twelvedata_api_key="TD-KEY",
        market_data_unhealthy_ttl_seconds=300,
    )
    agg = build_default_aggregator(settings=fake_settings)
    names = [pr.name for pr in agg.providers]
    assert names == ["twelvedata", "yfinance"]


def test_factory_twelvedata_works_without_key_but_unhealthy():
    """Factory baut den Provider auch ohne Key (Aggregator skipped via
    is_healthy())."""
    fake_settings = SimpleNamespace(
        market_data_providers="twelvedata",
        alphavantage_api_key=None,
        twelvedata_api_key=None,
        market_data_unhealthy_ttl_seconds=300,
    )
    agg = build_default_aggregator(settings=fake_settings)
    assert len(agg.providers) == 1
    assert agg.providers[0].name == "twelvedata"
    assert agg.providers[0].is_healthy() is False
