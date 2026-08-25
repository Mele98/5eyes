"""Sprint U-105 (2026-06-06): Coverage-Lifts fuer services/twelvedata_client.py.

Pure-Funktions-Tests + no-API-key-Error-Pfad. Echte Netzwerk-Calls
werden NICHT getestet (out-of-scope, brauchen Mock-Server).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.market_data.exceptions import RateLimitError
from services.twelvedata_client import (
    TWELVEDATA_TIME_SERIES_URL,
    _extract_series_payload,
    _request_json,
    _to_rappen,
    fetch_twelvedata_latest_prices,
)


# ---------------------------------------------------------------------------
# _to_rappen
# ---------------------------------------------------------------------------

def test_to_rappen_simple_float():
    assert _to_rappen(123.45) == 12345


def test_to_rappen_integer_input():
    assert _to_rappen(100) == 10000


def test_to_rappen_string_input():
    assert _to_rappen("123.45") == 12345


def test_to_rappen_zero():
    assert _to_rappen(0) == 0


def test_to_rappen_rounds_half_up():
    """0.005 rundet auf 0.01 (ROUND_HALF_UP)."""
    assert _to_rappen("0.005") == 1


def test_to_rappen_negative():
    assert _to_rappen(-123.45) == -12345


# ---------------------------------------------------------------------------
# _extract_series_payload
# ---------------------------------------------------------------------------

def test_extract_returns_subdict_for_symbol():
    decoded = {"AAPL": {"meta": "x", "values": []}}
    assert _extract_series_payload(decoded, "AAPL") == {"meta": "x", "values": []}


def test_extract_returns_root_if_meta_present():
    decoded = {"meta": "x", "values": []}
    assert _extract_series_payload(decoded, "AAPL") == decoded


def test_extract_returns_none_for_unknown_format():
    """Wenn weder symbol-Key noch meta-Key vorhanden -> None."""
    decoded = {"data": [1, 2, 3]}
    assert _extract_series_payload(decoded, "AAPL") is None


def test_extract_returns_none_for_non_dict_input():
    assert _extract_series_payload([1, 2, 3], "AAPL") is None
    assert _extract_series_payload("string", "AAPL") is None
    assert _extract_series_payload(None, "AAPL") is None


def test_extract_returns_none_when_symbol_value_is_not_dict():
    decoded = {"AAPL": "string-not-dict"}
    # Erste Pruefung schlaegt fehl (AAPL ist nicht dict), dann meta-Check
    # auch fail -> None
    assert _extract_series_payload(decoded, "AAPL") is None


# ---------------------------------------------------------------------------
# fetch_twelvedata_latest_prices: Error-Pfade ohne Netzwerk
# ---------------------------------------------------------------------------

def test_fetch_raises_without_api_key(monkeypatch):
    """Ohne API-Key -> RuntimeError."""
    from services import twelvedata_client as tdc

    monkeypatch.setattr(tdc.settings, "twelvedata_api_key", "", raising=False)
    with pytest.raises(RuntimeError, match="API Key"):
        fetch_twelvedata_latest_prices(["AAPL"])


def test_fetch_raises_with_none_api_key(monkeypatch):
    from services import twelvedata_client as tdc

    monkeypatch.setattr(tdc.settings, "twelvedata_api_key", None, raising=False)
    with pytest.raises(RuntimeError, match="API Key"):
        fetch_twelvedata_latest_prices(["AAPL"])


def test_fetch_returns_empty_for_no_symbols(monkeypatch):
    """Mit gueltigem API-Key aber leeren Symbolen -> ({}, {})."""
    from services import twelvedata_client as tdc

    monkeypatch.setattr(tdc.settings, "twelvedata_api_key", "test-key", raising=False)
    result = fetch_twelvedata_latest_prices([])
    assert result == ({}, {})


def test_fetch_returns_empty_for_whitespace_symbols(monkeypatch):
    """Symbole nur Whitespace werden gefiltert -> leerer Output."""
    from services import twelvedata_client as tdc

    monkeypatch.setattr(tdc.settings, "twelvedata_api_key", "test-key", raising=False)
    result = fetch_twelvedata_latest_prices(["  ", "", None])  # type: ignore[list-item]
    assert result == ({}, {})


# ---------------------------------------------------------------------------
# Mega-Audit (2026-08-04): HTTP 429 wurde bisher wie jeder andere
# Netzwerkfehler generisch in RuntimeError gewrappt -- keine Rate-Limit-
# Erkennung im Gegensatz zu den modernen Providern (services/market_data/).
# ---------------------------------------------------------------------------

def test_request_json_raises_rate_limit_error_on_http_429(monkeypatch):
    from urllib.error import HTTPError
    from services import twelvedata_client as tdc

    def _fake_urlopen(request, timeout=15):
        raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(tdc, "urlopen", _fake_urlopen)
    with pytest.raises(RateLimitError, match="429"):
        _request_json("https://api.twelvedata.com/time_series?symbol=AAPL")


def test_request_json_non_429_http_error_stays_runtime_error(monkeypatch):
    from urllib.error import HTTPError
    from services import twelvedata_client as tdc

    def _fake_urlopen(request, timeout=15):
        raise HTTPError(request.full_url, 503, "Service Unavailable", {}, None)

    monkeypatch.setattr(tdc, "urlopen", _fake_urlopen)
    with pytest.raises(RuntimeError) as exc_info:
        _request_json("https://api.twelvedata.com/time_series?symbol=AAPL")
    assert not isinstance(exc_info.value, RateLimitError)


def test_fetch_raises_rate_limit_error_on_json_embedded_code_429(monkeypatch):
    """Twelve Data meldet ein erreichtes Rate-Limit als HTTP 200 mit
    "status":"error"/"code":429 im JSON-Body -- kein echter HTTP-429."""
    from services import twelvedata_client as tdc

    monkeypatch.setattr(tdc.settings, "twelvedata_api_key", "test-key", raising=False)
    monkeypatch.setattr(
        tdc, "_request_json",
        lambda url: {"status": "error", "code": 429, "message": "You have run out of API credits."},
    )
    with pytest.raises(RateLimitError, match="Rate-Limit"):
        fetch_twelvedata_latest_prices(["AAPL"])


def test_fetch_non_429_json_error_stays_runtime_error(monkeypatch):
    from services import twelvedata_client as tdc

    monkeypatch.setattr(tdc.settings, "twelvedata_api_key", "test-key", raising=False)
    monkeypatch.setattr(
        tdc, "_request_json",
        lambda url: {"status": "error", "code": 400, "message": "Invalid symbol"},
    )
    with pytest.raises(RuntimeError) as exc_info:
        fetch_twelvedata_latest_prices(["AAPL"])
    assert not isinstance(exc_info.value, RateLimitError)


# ---------------------------------------------------------------------------
# URL-Constants
# ---------------------------------------------------------------------------

def test_twelvedata_time_series_url_https():
    assert TWELVEDATA_TIME_SERIES_URL.startswith("https://")
    assert "twelvedata.com" in TWELVEDATA_TIME_SERIES_URL
