"""BBG-1 (Audit 2026-11/06, B2/B3/B4): Fail-closed-Semantik des Bloomberg-Providers.

Befunde, die diese Tests vor dem Fix rot machen:

- B2/B3c: Ohne Terminal bzw. ohne ``blpapi`` meldeten ``get_eod``/
  ``get_history``/``lookup_isin`` ``SymbolNotFound`` ("Symbol unbekannt")
  statt "Bloomberg nicht verfuegbar". Eine Session wurde nie versucht.
- B3: ``is_healthy()`` war True, sobald ``blpapi`` importierbar war, auch
  wenn kein Terminal lief (``Session.start()`` wurde 0-mal aufgerufen).
- B4: Die Aggregator-Kaskade ``[bloomberg, yfinance]`` lieferte ohne
  Terminal still ``source='yfinance'``; Bloomberg wurde nie als ungesund
  markiert.

``blpapi`` wird ausschliesslich per ``sys.modules``-Stub simuliert. Es gibt
keine Netzwerkaufrufe und keinen echten Request-Aufbau (das ist BBG-3).
"""
from __future__ import annotations

import sys
import types
from datetime import date as Date
from decimal import Decimal

import pytest

from services.market_data.aggregator import MarketDataAggregator
from services.market_data.base import Bar, MarketDataProvider, ProductInfo
from services.market_data.exceptions import (
    ProviderError,
    ProviderUnavailableError,
    SymbolNotFound,
)
from services.market_data.providers.bloomberg_provider import (
    BLOOMBERG_NOT_INSTALLED,
    BLOOMBERG_REQUEST_NOT_IMPLEMENTED,
    BLOOMBERG_SESSION_UNAVAILABLE,
    BloombergProvider,
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


def _install_fake_blpapi(monkeypatch, *, start_ok: bool, service_ok: bool = True):
    calls: dict[str, list] = {"start": [], "options": [], "open_service": [], "stop": []}

    class _FakeSessionOptions:
        def setServerHost(self, host):
            calls["options"].append(("host", host))

        def setServerPort(self, port):
            calls["options"].append(("port", port))

        def setConnectTimeout(self, ms):
            calls["options"].append(("connect_timeout_ms", ms))

    class _FakeSession:
        def __init__(self, opts):
            self.opts = opts

        def start(self):
            calls["start"].append(True)
            return start_ok

        def openService(self, name):
            calls["open_service"].append(name)
            return service_ok

        def stop(self):
            calls["stop"].append(True)

    fake = types.ModuleType("blpapi")
    fake.SessionOptions = _FakeSessionOptions
    fake.Session = _FakeSession
    monkeypatch.setitem(sys.modules, "blpapi", fake)
    return calls


def _hide_blpapi(monkeypatch):
    # None in sys.modules -> "import blpapi" wirft ImportError.
    monkeypatch.setitem(sys.modules, "blpapi", None)


class _FreeProvider(MarketDataProvider):
    name = "yfinance"

    def __init__(self):
        self.calls = 0

    def get_eod(self, symbol, on_date):
        self.calls += 1
        return Bar(
            symbol=symbol, date=on_date, open=Decimal("1"), high=Decimal("1"),
            low=Decimal("1"), close=Decimal("1"), currency="CHF", source="yfinance",
        )

    def get_history(self, symbol, start, end):
        self.calls += 1
        return [self.get_eod(symbol, start)]

    def lookup_isin(self, isin):
        self.calls += 1
        return ProductInfo(isin=isin, ticker="X", name="X", source="yfinance")


class _Registry:
    def __init__(self):
        self.events: list[tuple] = []

    def mark_unhealthy(self, name, **kwargs):
        self.events.append(("unhealthy", name, kwargs.get("error_type")))

    def mark_healthy(self, name, **kwargs):
        self.events.append(("healthy", name))


# --------------------------------------------------------------------------- #
# Provider (B2/B3)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", ["get_eod", "get_history", "lookup_isin"])
def test_without_blpapi_data_methods_raise_provider_unavailable(monkeypatch, method):
    _hide_blpapi(monkeypatch)
    p = BloombergProvider()
    args = {
        "get_eod": ("SMI Index", Date(2026, 10, 30)),
        "get_history": ("SMI Index", Date(2026, 1, 1), Date(2026, 10, 30)),
        "lookup_isin": ("CH0012005267",),
    }[method]
    with pytest.raises(ProviderUnavailableError) as exc:
        getattr(p, method)(*args)
    assert not isinstance(exc.value, SymbolNotFound)
    assert exc.value.code == BLOOMBERG_NOT_INSTALLED


@pytest.mark.parametrize("method", ["get_eod", "get_history", "lookup_isin"])
def test_without_terminal_data_methods_try_session_and_raise_unavailable(monkeypatch, method):
    calls = _install_fake_blpapi(monkeypatch, start_ok=False)
    p = BloombergProvider()
    args = {
        "get_eod": ("SMI Index", Date(2026, 10, 30)),
        "get_history": ("SMI Index", Date(2026, 1, 1), Date(2026, 10, 30)),
        "lookup_isin": ("CH0012005267",),
    }[method]
    with pytest.raises(ProviderUnavailableError) as exc:
        getattr(p, method)(*args)
    assert exc.value.code == BLOOMBERG_SESSION_UNAVAILABLE
    assert len(calls["start"]) == 1


def test_is_healthy_false_when_blpapi_missing(monkeypatch):
    _hide_blpapi(monkeypatch)
    assert BloombergProvider().is_healthy() is False


def test_is_healthy_checks_real_session_with_short_timeout(monkeypatch):
    calls = _install_fake_blpapi(monkeypatch, start_ok=False)
    p = BloombergProvider()
    assert p.is_healthy() is False
    assert len(calls["start"]) == 1, "is_healthy muss einen echten Session-Start versuchen"
    timeouts = [v for k, v in calls["options"] if k == "connect_timeout_ms"]
    assert timeouts and 0 < timeouts[0] <= 5000


def test_is_healthy_caches_result_within_ttl(monkeypatch):
    calls = _install_fake_blpapi(monkeypatch, start_ok=False)
    p = BloombergProvider()
    assert p.is_healthy() is False
    assert p.is_healthy() is False
    assert len(calls["start"]) == 1


def test_is_healthy_true_only_with_session_and_refdata_service(monkeypatch):
    calls = _install_fake_blpapi(monkeypatch, start_ok=True, service_ok=True)
    p = BloombergProvider()
    assert p.is_healthy() is True
    assert calls["open_service"] == ["//blp/refdata"]


def test_is_healthy_false_when_refdata_service_missing(monkeypatch):
    calls = _install_fake_blpapi(monkeypatch, start_ok=True, service_ok=False)
    p = BloombergProvider()
    assert p.is_healthy() is False
    assert calls["stop"], "halb gestartete Session muss gestoppt werden"


def test_with_session_data_methods_still_fail_closed_not_symbol_not_found(monkeypatch):
    """Session steht, aber der Request-Aufbau (BBG-3) fehlt: eindeutiger
    Provider-Fehler, nie 'Symbol unbekannt'."""
    _install_fake_blpapi(monkeypatch, start_ok=True)
    p = BloombergProvider()
    with pytest.raises(ProviderUnavailableError) as exc:
        p.get_eod("SMI Index", Date(2026, 10, 30))
    assert exc.value.code == BLOOMBERG_REQUEST_NOT_IMPLEMENTED
    # Fehler -> Provider meldet sich bis zum TTL-Ablauf ungesund.
    assert p.is_healthy() is False


def test_bloomberg_is_authoritative_and_unavailable_error_is_provider_error():
    assert BloombergProvider.authoritative is True
    assert issubclass(ProviderUnavailableError, ProviderError)
    assert MarketDataProvider.authoritative is False


# --------------------------------------------------------------------------- #
# Aggregator-Kaskade (B4)
# --------------------------------------------------------------------------- #


def test_cascade_does_not_silently_fall_back_when_bloomberg_has_no_terminal(monkeypatch):
    _install_fake_blpapi(monkeypatch, start_ok=False)
    free = _FreeProvider()
    reg = _Registry()
    agg = MarketDataAggregator([BloombergProvider(), free], health_registry=reg)

    with pytest.raises(ProviderUnavailableError) as exc:
        agg.get_eod("SMI Index", Date(2026, 10, 30))
    assert exc.value.code == BLOOMBERG_SESSION_UNAVAILABLE
    with pytest.raises(ProviderUnavailableError):
        agg.lookup_isin("CH0012005267")
    with pytest.raises(ProviderUnavailableError):
        agg.get_history("SMI Index", Date(2026, 1, 1), Date(2026, 10, 30))

    assert free.calls == 0, "Gratisquelle darf nicht still einspringen"
    assert ("unhealthy", "bloomberg", "ProviderUnavailableError") in reg.events
    assert not any(e[0] == "healthy" for e in reg.events)
    assert agg.health.is_healthy("bloomberg") is False


def test_cascade_without_blpapi_also_fails_closed(monkeypatch):
    _hide_blpapi(monkeypatch)
    free = _FreeProvider()
    agg = MarketDataAggregator([BloombergProvider(), free])
    with pytest.raises(ProviderUnavailableError) as exc:
        agg.get_eod("SMI Index", Date(2026, 10, 30))
    assert exc.value.code == BLOOMBERG_NOT_INSTALLED
    assert free.calls == 0


def test_cascade_fails_closed_when_session_up_but_request_missing(monkeypatch):
    _install_fake_blpapi(monkeypatch, start_ok=True)
    free = _FreeProvider()
    reg = _Registry()
    agg = MarketDataAggregator([BloombergProvider(), free], health_registry=reg)
    with pytest.raises(ProviderUnavailableError):
        agg.get_eod("SMI Index", Date(2026, 10, 30))
    assert free.calls == 0
    assert ("unhealthy", "bloomberg", "ProviderUnavailableError") in reg.events


def test_explicit_fallback_is_visible_in_result(monkeypatch):
    """Expliziter Fallback (Policy-Schalter fuer BBG-2) ist nie still:
    Ergebnis traegt die tatsaechliche Quelle UND den Fallback-Grund."""
    _install_fake_blpapi(monkeypatch, start_ok=False)
    free = _FreeProvider()
    agg = MarketDataAggregator([BloombergProvider(), free], allow_fallback_from_authoritative=True)

    bar = agg.get_eod("SMI Index", Date(2026, 10, 30))
    assert bar.source == "yfinance"
    assert bar.fallback_reason and "bloomberg" in bar.fallback_reason
    assert BLOOMBERG_SESSION_UNAVAILABLE in bar.fallback_reason

    info = agg.lookup_isin("CH0012005267")
    assert info.source == "yfinance" and info.fallback_reason

    bars = agg.get_history("SMI Index", Date(2026, 1, 1), Date(2026, 10, 30))
    assert bars and all(b.fallback_reason for b in bars)


def test_free_cascade_positive_control_unchanged():
    """Positivkontrolle: Gratis-Kaskade ohne massgebliche Quelle faellt wie
    bisher weiter und markiert nichts als Fallback."""

    class _Down(_FreeProvider):
        name = "stooq"

        def get_eod(self, symbol, on_date):
            raise ProviderError("down")

    free = _FreeProvider()
    agg = MarketDataAggregator([_Down(), free])
    bar = agg.get_eod("UBSG.SW", Date(2026, 10, 30))
    assert bar.source == "yfinance"
    assert bar.fallback_reason is None


def test_fallback_reason_survives_cache_roundtrip():
    """Ein sichtbar markierter Fallback darf im Cache nicht zum stillen werden."""
    from services.market_data.cache import _bar_to_dict, _dict_to_bar, _dict_to_product, _product_to_dict

    bar = Bar(
        symbol="SMI Index", date=Date(2026, 10, 30), open=Decimal("1"), high=Decimal("1"),
        low=Decimal("1"), close=Decimal("1"), currency="CHF", source="yfinance",
        fallback_reason="bloomberg: BLOOMBERG_SESSION_UNAVAILABLE",
    )
    assert _dict_to_bar(_bar_to_dict(bar)).fallback_reason == bar.fallback_reason
    info = ProductInfo(isin="CH1", ticker="X", name="X", source="yfinance", fallback_reason="r")
    assert _dict_to_product(_product_to_dict(info)).fallback_reason == "r"
    # Ohne Fallback bleibt das Cache-Payload unveraendert (kein neues Feld).
    plain = dataclasses_replace(bar, fallback_reason=None)
    assert "fallback_reason" not in _bar_to_dict(plain)


def dataclasses_replace(obj, **kw):
    import dataclasses

    return dataclasses.replace(obj, **kw)
