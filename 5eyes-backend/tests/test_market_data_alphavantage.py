"""Phase 4 Tests: AlphaVantageProvider.

Mock-Session, kein echter HTTP-Call. Testet auch Rate-Limit-Tracker und
fehlenden API-Key.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
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
    AlphaVantageProvider,
    Bar,
    ProviderError,
    RateLimitError,
    SymbolNotFound,
)


# ============================================================================
# Mock Helpers
# ============================================================================


def _mock_response(payload, status: int = 200):
    """Erstellt ein response-aehnliches Objekt."""
    resp = MagicMock()
    resp.status_code = status
    resp.json = lambda: payload
    resp.text = str(payload)
    return resp


def _mock_session(payload, status: int = 200):
    session = MagicMock()
    session.get.return_value = _mock_response(payload, status)
    return session


_VALID_PAYLOAD = {
    "Meta Data": {"1. Information": "Daily Prices"},
    "Time Series (Daily)": {
        "2026-05-08": {
            "1. open": "28.50", "2. high": "28.90", "3. low": "28.30",
            "4. close": "28.75", "5. volume": "1500000",
        },
        "2026-05-07": {
            "1. open": "28.20", "2. high": "28.60", "3. low": "28.15",
            "4. close": "28.55", "5. volume": "1400000",
        },
        "2026-05-06": {
            "1. open": "28.10", "2. high": "28.40", "3. low": "28.00",
            "4. close": "28.20", "5. volume": "1200000",
        },
    },
}


# ============================================================================
# API-Key & Rate-Limit
# ============================================================================


def test_provider_without_key_is_unhealthy():
    provider = AlphaVantageProvider(api_key=None)
    assert provider.has_key is False
    assert provider.is_healthy() is False


def test_provider_with_empty_key_is_unhealthy():
    provider = AlphaVantageProvider(api_key="   ")
    assert provider.has_key is False


def test_provider_with_key_is_healthy_initially():
    provider = AlphaVantageProvider(api_key="TESTKEY")
    assert provider.has_key is True
    assert provider.is_healthy() is True


def test_get_eod_without_key_raises_provider_error():
    provider = AlphaVantageProvider(api_key=None)
    with pytest.raises(ProviderError):
        provider.get_eod("UBSG.SW", date(2026, 5, 8))


def test_rate_limit_tracker_blocks_after_daily_limit():
    """Mit daily_limit=2 sollten der dritte Aufruf RateLimitError werfen."""
    session = _mock_session(_VALID_PAYLOAD)
    provider = AlphaVantageProvider(api_key="TESTKEY", session=session, daily_limit=2)
    provider.get_eod("AAPL", date(2026, 5, 8))
    provider.get_eod("AAPL", date(2026, 5, 8))
    with pytest.raises(RateLimitError):
        provider.get_eod("AAPL", date(2026, 5, 8))


def test_is_healthy_false_when_limit_reached():
    session = _mock_session(_VALID_PAYLOAD)
    provider = AlphaVantageProvider(api_key="K", session=session, daily_limit=1)
    provider.get_eod("AAPL", date(2026, 5, 8))
    assert provider.is_healthy() is False


# ============================================================================
# get_eod
# ============================================================================


def test_get_eod_returns_bar():
    session = _mock_session(_VALID_PAYLOAD)
    provider = AlphaVantageProvider(api_key="K", session=session)
    bar = provider.get_eod("AAPL", date(2026, 5, 8))
    assert isinstance(bar, Bar)
    assert bar.symbol == "AAPL"
    assert bar.date == date(2026, 5, 8)
    assert bar.close == Decimal("28.75")
    assert bar.currency == "USD"
    assert bar.volume == 1_500_000
    assert bar.source == "alphavantage"


def test_get_eod_falls_back_to_last_trading_day():
    session = _mock_session(_VALID_PAYLOAD)
    provider = AlphaVantageProvider(api_key="K", session=session)
    # Sonntag 2026-05-10 -> letzter <= 2026-05-08
    bar = provider.get_eod("AAPL", date(2026, 5, 10))
    assert bar.date == date(2026, 5, 8)


def test_get_eod_no_match_in_range_raises_symbol_not_found():
    """Alle Zeilen sind nach on_date."""
    session = _mock_session(_VALID_PAYLOAD)
    provider = AlphaVantageProvider(api_key="K", session=session)
    with pytest.raises(SymbolNotFound):
        provider.get_eod("AAPL", date(2026, 5, 1))


def test_get_eod_error_message_payload_raises_symbol_not_found():
    session = _mock_session({"Error Message": "Invalid API call. Symbol XXX"})
    provider = AlphaVantageProvider(api_key="K", session=session)
    with pytest.raises(SymbolNotFound):
        provider.get_eod("XXX", date(2026, 5, 8))


def test_get_eod_information_with_limit_raises_rate_limit():
    payload = {"Information": "Thank you for using Alpha Vantage! Daily limit reached."}
    session = _mock_session(payload)
    provider = AlphaVantageProvider(api_key="K", session=session)
    with pytest.raises(RateLimitError):
        provider.get_eod("AAPL", date(2026, 5, 8))


def test_get_eod_note_with_limit_raises_rate_limit():
    payload = {"Note": "Our standard API call frequency is limit per minute."}
    session = _mock_session(payload)
    provider = AlphaVantageProvider(api_key="K", session=session)
    with pytest.raises(RateLimitError):
        provider.get_eod("AAPL", date(2026, 5, 8))


def test_get_eod_http_error_raises_provider_error():
    session = _mock_session({}, status=503)
    provider = AlphaVantageProvider(api_key="K", session=session)
    with pytest.raises(ProviderError):
        provider.get_eod("AAPL", date(2026, 5, 8))


def test_get_eod_network_exception_raises_provider_error():
    session = MagicMock()
    session.get.side_effect = requests.RequestException("connection refused")
    provider = AlphaVantageProvider(api_key="K", session=session)
    with pytest.raises(ProviderError):
        provider.get_eod("AAPL", date(2026, 5, 8))


def test_get_eod_non_json_raises_provider_error():
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.side_effect = ValueError("not json")
    session.get.return_value = resp
    provider = AlphaVantageProvider(api_key="K", session=session)
    with pytest.raises(ProviderError):
        provider.get_eod("AAPL", date(2026, 5, 8))


# ============================================================================
# get_history
# ============================================================================


def test_get_history_returns_filtered_range():
    session = _mock_session(_VALID_PAYLOAD)
    provider = AlphaVantageProvider(api_key="K", session=session)
    bars = provider.get_history("AAPL", date(2026, 5, 7), date(2026, 5, 8))
    assert len(bars) == 2
    assert [b.date for b in bars] == [date(2026, 5, 7), date(2026, 5, 8)]


def test_get_history_empty_when_end_before_start():
    provider = AlphaVantageProvider(api_key="K", session=MagicMock())
    bars = provider.get_history("AAPL", date(2026, 5, 8), date(2026, 5, 1))
    assert bars == []


def test_get_history_returns_empty_on_symbol_not_found():
    session = _mock_session({"Error Message": "Invalid"})
    provider = AlphaVantageProvider(api_key="K", session=session)
    bars = provider.get_history("XX", date(2026, 5, 1), date(2026, 5, 8))
    assert bars == []


# ============================================================================
# lookup_isin
# ============================================================================


def test_lookup_isin_raises_symbol_not_found():
    provider = AlphaVantageProvider(api_key="K", session=MagicMock())
    with pytest.raises(SymbolNotFound):
        provider.lookup_isin("CH0244767585")


# ============================================================================
# Network-Integration
# ============================================================================


@pytest.mark.network
@pytest.mark.skip(reason="network-test, manuell mit -m network + ALPHAVANTAGE_API_KEY")
def test_real_alphavantage_call_for_apple():
    import os
    key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key:
        pytest.skip("ALPHAVANTAGE_API_KEY nicht gesetzt")
    provider = AlphaVantageProvider(api_key=key)
    bar = provider.get_eod("AAPL", date.today() - timedelta(days=7))
    assert bar.currency == "USD"
    assert bar.close > 0
