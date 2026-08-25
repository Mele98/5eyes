"""Mega-Audit (2026-08-04): services/eodhd_client.py wrappte HTTP 429 bisher
wie jeden anderen Netzwerkfehler generisch in RuntimeError -- keine
Rate-Limit-Erkennung im Gegensatz zu den modernen Providern in
services/market_data/ (RateLimitError-Vertrag).
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.eodhd_client import _request_json
from services.market_data.exceptions import RateLimitError


def test_request_json_raises_rate_limit_error_on_http_429(monkeypatch):
    from services import eodhd_client as ec

    def _fake_urlopen(request, timeout=15):
        raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(ec, "urlopen", _fake_urlopen)
    with pytest.raises(RateLimitError, match="429"):
        _request_json("https://eodhd.com/api/search/AAPL")


def test_request_json_non_429_http_error_stays_runtime_error(monkeypatch):
    from services import eodhd_client as ec

    def _fake_urlopen(request, timeout=15):
        raise HTTPError(request.full_url, 500, "Internal Server Error", {}, None)

    monkeypatch.setattr(ec, "urlopen", _fake_urlopen)
    with pytest.raises(RuntimeError) as exc_info:
        _request_json("https://eodhd.com/api/search/AAPL")
    assert not isinstance(exc_info.value, RateLimitError)


def test_request_json_generic_network_error_stays_runtime_error(monkeypatch):
    from services import eodhd_client as ec

    def _fake_urlopen(request, timeout=15):
        raise OSError("connection reset")

    monkeypatch.setattr(ec, "urlopen", _fake_urlopen)
    with pytest.raises(RuntimeError) as exc_info:
        _request_json("https://eodhd.com/api/search/AAPL")
    assert not isinstance(exc_info.value, RateLimitError)
