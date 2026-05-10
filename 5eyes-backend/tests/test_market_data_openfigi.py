"""Phase 8 Tests: OpenFIGIProvider."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.market_data import (
    OpenFIGIProvider,
    ProductInfo,
    ProviderError,
    RateLimitError,
    SymbolNotFound,
)


def _mock_response(payload, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.json = lambda: payload
    return resp


def _mock_session(payload, status: int = 200):
    session = MagicMock()
    session.post.return_value = _mock_response(payload, status)
    return session


_UBSG_HIT = [
    {
        "data": [
            {
                "figi": "BBG00ABCDEFG",
                "ticker": "UBSG SW",
                "name": "UBS GROUP AG",
                "exchCode": "SW",
                "securityType": "Common Stock",
                "compositeFIGI": "BBG00COMP",
            }
        ]
    }
]

_NO_DATA_WARNING = [{"warning": "No identifier found."}]


# ============================================================================
# Headers (mit/ohne Key)
# ============================================================================


def test_headers_without_key():
    provider = OpenFIGIProvider()
    headers = provider._headers()
    assert "Content-Type" in headers
    assert "X-OPENFIGI-APIKEY" not in headers


def test_headers_with_key():
    provider = OpenFIGIProvider(api_key="MYKEY")
    headers = provider._headers()
    assert headers["X-OPENFIGI-APIKEY"] == "MYKEY"


# ============================================================================
# lookup_isin (Single)
# ============================================================================


def test_lookup_isin_returns_product_info():
    session = _mock_session(_UBSG_HIT)
    provider = OpenFIGIProvider(session=session)
    info = provider.lookup_isin("CH0244767585")
    assert isinstance(info, ProductInfo)
    assert info.isin == "CH0244767585"
    assert info.ticker == "UBSG.SW"  # Yahoo-Style-Konvertierung
    assert info.name == "UBS GROUP AG"
    assert info.exchange == "SW"
    assert info.figi == "BBG00ABCDEFG"
    assert info.asset_class == "Common Stock"
    assert info.source == "openfigi"


def test_lookup_isin_warning_raises_symbol_not_found():
    session = _mock_session(_NO_DATA_WARNING)
    provider = OpenFIGIProvider(session=session)
    with pytest.raises(SymbolNotFound):
        provider.lookup_isin("XX0000000000")


def test_lookup_isin_empty_isin_raises_symbol_not_found():
    provider = OpenFIGIProvider(session=MagicMock())
    with pytest.raises(SymbolNotFound):
        provider.lookup_isin("")


def test_lookup_isin_429_raises_rate_limit():
    session = _mock_session([], status=429)
    provider = OpenFIGIProvider(session=session)
    with pytest.raises(RateLimitError):
        provider.lookup_isin("CH0244767585")


def test_lookup_isin_500_raises_provider_error():
    session = _mock_session([], status=500)
    provider = OpenFIGIProvider(session=session)
    with pytest.raises(ProviderError):
        provider.lookup_isin("CH0244767585")


def test_lookup_isin_network_exception_raises_provider_error():
    session = MagicMock()
    session.post.side_effect = requests.RequestException("timeout")
    provider = OpenFIGIProvider(session=session)
    with pytest.raises(ProviderError):
        provider.lookup_isin("CH0244767585")


# ============================================================================
# lookup_isins (Batch)
# ============================================================================


def test_lookup_isins_batch_two_results():
    payload = [
        {"data": [{"figi": "F1", "ticker": "AAPL", "name": "Apple", "exchCode": "US", "securityType": "Common Stock"}]},
        {"data": [{"figi": "F2", "ticker": "UBSG SW", "name": "UBS", "exchCode": "SW", "securityType": "Common Stock"}]},
    ]
    session = _mock_session(payload)
    provider = OpenFIGIProvider(session=session)
    out = provider.lookup_isins(["US0378331005", "CH0244767585"])
    assert set(out.keys()) == {"US0378331005", "CH0244767585"}
    assert out["US0378331005"].ticker == "AAPL"
    assert out["CH0244767585"].ticker == "UBSG.SW"


def test_lookup_isins_skips_warning_entries():
    payload = [
        {"data": [{"figi": "F1", "ticker": "AAPL", "name": "Apple", "exchCode": "US", "securityType": "Common Stock"}]},
        {"warning": "No identifier found."},
    ]
    session = _mock_session(payload)
    provider = OpenFIGIProvider(session=session)
    out = provider.lookup_isins(["US0378331005", "XX0000000000"])
    assert "US0378331005" in out
    assert "XX0000000000" not in out


def test_lookup_isins_empty_list():
    provider = OpenFIGIProvider(session=MagicMock())
    assert provider.lookup_isins([]) == {}


def test_lookup_isins_prefers_common_stock_over_other_types():
    payload = [
        {
            "data": [
                {"figi": "F-OPT", "ticker": "X", "name": "Option", "exchCode": "Z", "securityType": "Option"},
                {"figi": "F-EQ", "ticker": "X", "name": "Stock", "exchCode": "Z", "securityType": "Common Stock"},
            ]
        }
    ]
    session = _mock_session(payload)
    provider = OpenFIGIProvider(session=session)
    out = provider.lookup_isins(["XX"])
    assert out["XX"].figi == "F-EQ"


# ============================================================================
# get_eod / get_history Methoden
# ============================================================================


def test_get_eod_raises_symbol_not_found():
    """OpenFIGI liefert keine Preisdaten — Provider muss klar abbruechen."""
    provider = OpenFIGIProvider()
    with pytest.raises(SymbolNotFound):
        provider.get_eod("CH0244767585", date(2026, 5, 8))


def test_get_history_returns_empty():
    provider = OpenFIGIProvider()
    assert provider.get_history("CH0244767585", date(2026, 1, 1), date(2026, 5, 8)) == []


def test_is_healthy_default_true():
    assert OpenFIGIProvider().is_healthy() is True
