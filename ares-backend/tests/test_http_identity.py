"""User-Agent ausgehender Requests: ``Ares/<version>`` an allen Aufrufstellen.

Die Requests werden abgefangen, bevor sie das Netz erreichen; geprueft wird
der tatsaechlich gesetzte Header, nicht nur die Konstante.
"""
from __future__ import annotations

import pytest

from config import settings
from services import eodhd_client, openfigi_client, twelvedata_client
from config import browser_compatible_user_agent, user_agent
from services.market_data import notifier
from services.market_data.etf.providers.justetf import JustetfScraper
from services.market_data.etf.providers.swissfunddata import SwissfunddataScraper


class _Captured(Exception):
    pass


def _capture_urlopen(monkeypatch, module, seen: list):
    def fake_urlopen(request, timeout=None):
        seen.append(request.get_header("User-agent"))
        raise _Captured()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)


def test_user_agent_format():
    assert user_agent() == f"Ares/{settings.app_version}"
    assert browser_compatible_user_agent() == f"Mozilla/5.0 (Ares/{settings.app_version})"


@pytest.mark.parametrize("module", [eodhd_client, twelvedata_client])
def test_api_clients_send_product_user_agent(monkeypatch, module):
    seen: list = []
    _capture_urlopen(monkeypatch, module, seen)
    with pytest.raises(Exception):
        module._request_json("https://provider.invalid/x")
    assert seen == [user_agent()]


def test_openfigi_sends_product_user_agent(monkeypatch):
    seen: list = []
    _capture_urlopen(monkeypatch, openfigi_client, seen)
    try:
        openfigi_client.preview_openfigi_mapping(isin="CH0000000000")
    except Exception:
        pass
    assert seen == [user_agent()]


def test_alert_webhook_sends_product_user_agent(monkeypatch):
    seen: list = []
    _capture_urlopen(monkeypatch, notifier, seen)
    try:
        notifier.post_alert("https://hook.invalid/x", {"k": "v"})
    except Exception:
        pass
    assert seen == [user_agent()]


@pytest.mark.parametrize("provider_cls", [JustetfScraper, SwissfunddataScraper])
def test_html_providers_send_browser_compatible_user_agent(provider_cls):
    seen: list = []

    class _Session:
        def get(self, url, params=None, headers=None, timeout=None):
            seen.append(headers["User-Agent"])
            raise _Captured()

    provider = provider_cls(enabled=True, rate_delay_seconds=0, session=_Session())
    with pytest.raises(_Captured):
        provider._http_get("CH0000000000")
    assert seen == [browser_compatible_user_agent()]
