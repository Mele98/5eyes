"""Phase 3 Tests: StooqProvider.

Mock-Session statt echter HTTP-Calls. Network-Test skipped by default.
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
    Bar,
    ProviderError,
    StooqProvider,
    SymbolNotFound,
)
from services.market_data.providers._stooq_symbols import (
    stooq_currency,
    stooq_symbol,
)


# ============================================================================
# Symbol-Mapping
# ============================================================================


@pytest.mark.parametrize("ticker,exchange,expected", [
    ("UBSG", "SIX", "ubsg.ch"),
    ("UBSG", "CH", "ubsg.ch"),
    ("ubsg.ch", "SIX", "ubsg.ch"),  # bereits Stooq-suffixiert
    ("UBSG.SW", None, "ubsg.ch"),   # Yahoo-Suffix -> Stooq
    ("UBSG.SW", "SIX", "ubsg.ch"),  # Yahoo-Suffix gewinnt
    ("VOW3.DE", None, "vow3.de"),
    ("VOD.L", None, "vod.uk"),
    ("AAPL", "NYSE", "aapl.us"),
    ("AAPL", "US", "aapl.us"),
    ("VOW3", "DE", "vow3.de"),
    ("VOD", "LON", "vod.uk"),
    ("VOD", None, "vod"),
    ("VOD", "ZZZ", "vod"),
])
def test_stooq_symbol(ticker, exchange, expected):
    assert stooq_symbol(ticker, exchange) == expected


@pytest.mark.parametrize("symbol,expected", [
    ("ubsg.ch", "CHF"),
    ("aapl.us", "USD"),
    ("vow3.de", "EUR"),
    ("vod.uk", "GBP"),
    ("nokia.fi", "EUR"),
    ("xxx", "USD"),  # Default
])
def test_stooq_currency(symbol, expected):
    assert stooq_currency(symbol) == expected


# ============================================================================
# Mock-Session Helper
# ============================================================================


def _mock_response(text: str, status: int = 200, content_type: str = "application/octet-stream"):
    resp = SimpleNamespace(
        text=text,
        status_code=status,
        headers={"Content-Type": content_type},
    )
    return resp


def _mock_session(response):
    session = MagicMock()
    session.get.return_value = response
    return session


_VALID_CSV = (
    "Date,Open,High,Low,Close,Volume\n"
    "2026-05-06,28.10,28.40,28.00,28.20,1200000\n"
    "2026-05-07,28.20,28.60,28.15,28.55,1400000\n"
    "2026-05-08,28.50,28.90,28.30,28.75,1500000\n"
)


# ============================================================================
# get_eod
# ============================================================================


def test_get_eod_returns_last_row_as_bar():
    session = _mock_session(_mock_response(_VALID_CSV))
    provider = StooqProvider(session=session)
    bar = provider.get_eod("UBSG.SW", date(2026, 5, 8))
    assert isinstance(bar, Bar)
    assert bar.symbol == "UBSG.SW"
    assert bar.date == date(2026, 5, 8)
    assert bar.close == Decimal("28.75")
    assert bar.currency == "CHF"
    assert bar.volume == 1_500_000
    assert bar.source == "stooq"


def test_get_eod_html_response_raises_symbol_not_found():
    session = _mock_session(_mock_response("<html>not found</html>", content_type="text/html"))
    provider = StooqProvider(session=session)
    with pytest.raises(SymbolNotFound):
        provider.get_eod("UNKNOWN.XX", date(2026, 5, 8))


def test_get_eod_empty_response_raises_symbol_not_found():
    session = _mock_session(_mock_response(""))
    provider = StooqProvider(session=session)
    with pytest.raises(SymbolNotFound):
        provider.get_eod("UNKNOWN", date(2026, 5, 8))


def test_get_eod_invalid_csv_header_raises_symbol_not_found():
    session = _mock_session(_mock_response("Wrong,Header\nfoo,bar\n"))
    provider = StooqProvider(session=session)
    with pytest.raises(SymbolNotFound):
        provider.get_eod("UNKNOWN", date(2026, 5, 8))


def test_get_eod_http_500_raises_provider_error():
    session = _mock_session(_mock_response("server error", status=500))
    provider = StooqProvider(session=session)
    with pytest.raises(ProviderError):
        provider.get_eod("UBSG", date(2026, 5, 8))


def test_get_eod_network_exception_raises_provider_error():
    session = MagicMock()
    session.get.side_effect = requests.RequestException("connection refused")
    provider = StooqProvider(session=session)
    with pytest.raises(ProviderError):
        provider.get_eod("UBSG", date(2026, 5, 8))


def test_get_eod_skips_malformed_rows():
    """Eine kaputte Zeile in der Mitte darf nicht das ganze Result killen."""
    csv = (
        "Date,Open,High,Low,Close,Volume\n"
        "2026-05-06,28.10,28.40,28.00,28.20,1200000\n"
        "broken,row,here,wrong\n"
        "2026-05-08,28.50,28.90,28.30,28.75,1500000\n"
    )
    session = _mock_session(_mock_response(csv))
    provider = StooqProvider(session=session)
    bar = provider.get_eod("UBSG.SW", date(2026, 5, 8))
    assert bar.date == date(2026, 5, 8)


# ============================================================================
# get_history
# ============================================================================


def test_get_history_returns_all_rows():
    session = _mock_session(_mock_response(_VALID_CSV))
    provider = StooqProvider(session=session)
    bars = provider.get_history("UBSG.SW", date(2026, 5, 6), date(2026, 5, 8))
    assert len(bars) == 3
    assert all(isinstance(b, Bar) for b in bars)
    assert [b.date for b in bars] == [
        date(2026, 5, 6), date(2026, 5, 7), date(2026, 5, 8),
    ]


def test_get_history_empty_when_end_before_start():
    provider = StooqProvider(session=MagicMock())
    bars = provider.get_history("UBSG.SW", date(2026, 5, 8), date(2026, 5, 1))
    assert bars == []


def test_get_history_returns_empty_on_html_response():
    session = _mock_session(_mock_response("<html>not found</html>", content_type="text/html"))
    provider = StooqProvider(session=session)
    bars = provider.get_history("UNKNOWN", date(2026, 5, 1), date(2026, 5, 8))
    assert bars == []


# ============================================================================
# lookup_isin
# ============================================================================


def test_lookup_isin_raises_symbol_not_found():
    provider = StooqProvider(session=MagicMock())
    with pytest.raises(SymbolNotFound):
        provider.lookup_isin("CH0244767585")


# ============================================================================
# is_healthy
# ============================================================================


def test_is_healthy_returns_true_when_ping_ok():
    session = _mock_session(_mock_response("Date,Open,High,Low,Close,Volume\n"))
    provider = StooqProvider(session=session)
    assert provider.is_healthy() is True


def test_is_healthy_returns_true_on_network_error():
    """Bei Netz-Error nicht direkt unhealthy machen — Aggregator
    soll trotzdem versuchen."""
    session = MagicMock()
    session.get.side_effect = requests.RequestException("timeout")
    provider = StooqProvider(session=session)
    assert provider.is_healthy() is True


# ============================================================================
# Network-Integration
# ============================================================================


@pytest.mark.network
@pytest.mark.skip(reason="network-test, manuell mit -m network")
def test_real_stooq_call_for_apple():
    provider = StooqProvider()
    bar = provider.get_eod("AAPL.US", date.today() - timedelta(days=7))
    assert bar.currency == "USD"
    assert bar.close > 0
