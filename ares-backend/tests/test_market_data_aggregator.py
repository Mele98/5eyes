"""Phase 5 Tests: MarketDataAggregator + HealthState + Factory.

Reine Unit-Tests mit Fake-Providern (keine Netzwerk-Calls).
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.market_data import (
    Bar,
    HealthState,
    MarketDataAggregator,
    MarketDataError,
    MarketDataProvider,
    ProductInfo,
    ProviderError,
    RateLimitError,
    SymbolNotFound,
    build_default_aggregator,
)


# ============================================================================
# Fake-Provider Helper
# ============================================================================


class _FakeProvider(MarketDataProvider):
    """Konfigurierbarer Fake-Provider fuer Aggregator-Tests."""

    def __init__(
        self,
        name: str,
        eod_result=None,
        eod_exc=None,
        history_result=None,
        history_exc=None,
        isin_result=None,
        isin_exc=None,
        healthy: bool = True,
    ):
        self.name = name
        self._eod = eod_result
        self._eod_exc = eod_exc
        self._history = history_result if history_result is not None else []
        self._history_exc = history_exc
        self._isin = isin_result
        self._isin_exc = isin_exc
        self._healthy = healthy
        self.eod_calls = 0
        self.history_calls = 0
        self.isin_calls = 0

    def get_eod(self, symbol, on_date):
        self.eod_calls += 1
        if self._eod_exc:
            raise self._eod_exc
        if self._eod is not None:
            return self._eod
        raise SymbolNotFound(symbol)

    def get_history(self, symbol, start, end):
        self.history_calls += 1
        if self._history_exc:
            raise self._history_exc
        return list(self._history)

    def lookup_isin(self, isin):
        self.isin_calls += 1
        if self._isin_exc:
            raise self._isin_exc
        if self._isin is not None:
            return self._isin
        raise SymbolNotFound(isin)

    def is_healthy(self) -> bool:
        return self._healthy


def _bar(symbol="X", source="fake"):
    return Bar(
        symbol=symbol, date=date(2026, 5, 8),
        open=Decimal("1"), high=Decimal("1"),
        low=Decimal("1"), close=Decimal("1"),
        currency="USD", source=source,
    )


# ============================================================================
# HealthState
# ============================================================================


def test_health_state_default_healthy():
    h = HealthState()
    assert h.is_healthy("yfinance") is True


def test_health_state_mark_unhealthy_blocks():
    h = HealthState()
    h.mark_unhealthy("yfinance", ttl_seconds=60)
    assert h.is_healthy("yfinance") is False


def test_health_state_mark_healthy_unblocks():
    h = HealthState()
    h.mark_unhealthy("yfinance", ttl_seconds=60)
    h.mark_healthy("yfinance")
    assert h.is_healthy("yfinance") is True


def test_health_state_consecutive_errors_increment():
    h = HealthState()
    h.mark_unhealthy("yfinance")
    h.mark_unhealthy("yfinance")
    assert h.consecutive_errors("yfinance") == 2


def test_health_state_reset_clears_one_provider():
    h = HealthState()
    h.mark_unhealthy("yfinance")
    h.mark_unhealthy("stooq")
    h.reset("yfinance")
    assert h.is_healthy("yfinance") is True
    assert h.is_healthy("stooq") is False


def test_health_state_reset_all():
    h = HealthState()
    h.mark_unhealthy("yfinance")
    h.mark_unhealthy("stooq")
    h.reset()
    assert h.is_healthy("yfinance") is True
    assert h.is_healthy("stooq") is True


# ============================================================================
# Aggregator: get_eod Fallback
# ============================================================================


def test_get_eod_first_provider_wins():
    p1 = _FakeProvider("p1", eod_result=_bar(source="p1"))
    p2 = _FakeProvider("p2", eod_result=_bar(source="p2"))
    agg = MarketDataAggregator(providers=[p1, p2])
    bar = agg.get_eod("X", date(2026, 5, 8))
    assert bar.source == "p1"
    assert p1.eod_calls == 1
    assert p2.eod_calls == 0


def test_get_eod_falls_through_provider_error():
    p1 = _FakeProvider("p1", eod_exc=ProviderError("network down"))
    p2 = _FakeProvider("p2", eod_result=_bar(source="p2"))
    agg = MarketDataAggregator(providers=[p1, p2])
    bar = agg.get_eod("X", date(2026, 5, 8))
    assert bar.source == "p2"
    assert p1.eod_calls == 1
    assert p2.eod_calls == 1
    # p1 jetzt unhealthy
    assert agg.health.is_healthy("p1") is False


def test_get_eod_falls_through_rate_limit():
    p1 = _FakeProvider("p1", eod_exc=RateLimitError("limit"))
    p2 = _FakeProvider("p2", eod_result=_bar(source="p2"))
    agg = MarketDataAggregator(providers=[p1, p2])
    bar = agg.get_eod("X", date(2026, 5, 8))
    assert bar.source == "p2"
    assert agg.health.is_healthy("p1") is False


def test_get_eod_symbol_not_found_keeps_provider_healthy():
    p1 = _FakeProvider("p1", eod_exc=SymbolNotFound("X"))
    p2 = _FakeProvider("p2", eod_result=_bar(source="p2"))
    agg = MarketDataAggregator(providers=[p1, p2])
    bar = agg.get_eod("X", date(2026, 5, 8))
    assert bar.source == "p2"
    # SymbolNotFound != Provider-Krankheit
    assert agg.health.is_healthy("p1") is True


def test_get_eod_all_fail_raises_last_exception():
    p1 = _FakeProvider("p1", eod_exc=ProviderError("p1 down"))
    p2 = _FakeProvider("p2", eod_exc=SymbolNotFound("not at p2"))
    agg = MarketDataAggregator(providers=[p1, p2])
    with pytest.raises((ProviderError, SymbolNotFound)):
        agg.get_eod("X", date(2026, 5, 8))


def test_get_eod_no_providers_raises_market_data_error():
    agg = MarketDataAggregator(providers=[])
    with pytest.raises(MarketDataError):
        agg.get_eod("X", date(2026, 5, 8))


def test_get_eod_skips_unhealthy_provider_via_self_report():
    p1 = _FakeProvider("p1", eod_result=_bar(source="p1"), healthy=False)
    p2 = _FakeProvider("p2", eod_result=_bar(source="p2"))
    agg = MarketDataAggregator(providers=[p1, p2])
    bar = agg.get_eod("X", date(2026, 5, 8))
    assert bar.source == "p2"
    assert p1.eod_calls == 0


def test_get_eod_skips_provider_marked_unhealthy_in_aggregator():
    p1 = _FakeProvider("p1", eod_result=_bar(source="p1"))
    p2 = _FakeProvider("p2", eod_result=_bar(source="p2"))
    agg = MarketDataAggregator(providers=[p1, p2])
    agg.health.mark_unhealthy("p1", ttl_seconds=60)
    bar = agg.get_eod("X", date(2026, 5, 8))
    assert bar.source == "p2"
    assert p1.eod_calls == 0


# ============================================================================
# Aggregator: get_history mit speziellen Semantiken
# ============================================================================


def test_get_history_first_non_empty_wins():
    p1 = _FakeProvider("p1", history_result=[_bar(source="p1")])
    p2 = _FakeProvider("p2", history_result=[_bar(source="p2")])
    agg = MarketDataAggregator(providers=[p1, p2])
    bars = agg.get_history("X", date(2026, 5, 1), date(2026, 5, 8))
    assert [b.source for b in bars] == ["p1"]
    assert p2.history_calls == 0


def test_get_history_falls_through_empty_list():
    p1 = _FakeProvider("p1", history_result=[])
    p2 = _FakeProvider("p2", history_result=[_bar(source="p2")])
    agg = MarketDataAggregator(providers=[p1, p2])
    bars = agg.get_history("X", date(2026, 5, 1), date(2026, 5, 8))
    assert [b.source for b in bars] == ["p2"]
    # p1 bleibt healthy (leere Liste != Krankheit)
    assert agg.health.is_healthy("p1") is True


def test_get_history_returns_empty_when_all_empty():
    p1 = _FakeProvider("p1", history_result=[])
    p2 = _FakeProvider("p2", history_result=[])
    agg = MarketDataAggregator(providers=[p1, p2])
    bars = agg.get_history("X", date(2026, 5, 1), date(2026, 5, 8))
    assert bars == []


def test_get_history_provider_error_raises_when_all_fail():
    p1 = _FakeProvider("p1", history_exc=ProviderError("p1 down"))
    p2 = _FakeProvider("p2", history_exc=ProviderError("p2 down"))
    agg = MarketDataAggregator(providers=[p1, p2])
    with pytest.raises(ProviderError):
        agg.get_history("X", date(2026, 5, 1), date(2026, 5, 8))


# ============================================================================
# Aggregator: lookup_isin
# ============================================================================


def test_lookup_isin_first_provider_wins():
    info1 = ProductInfo(isin="X", ticker="t1", name="n1", source="p1")
    info2 = ProductInfo(isin="X", ticker="t2", name="n2", source="p2")
    p1 = _FakeProvider("p1", isin_result=info1)
    p2 = _FakeProvider("p2", isin_result=info2)
    agg = MarketDataAggregator(providers=[p1, p2])
    info = agg.lookup_isin("X")
    assert info.source == "p1"


def test_lookup_isin_falls_through_symbol_not_found():
    info2 = ProductInfo(isin="X", ticker="t", name="n", source="p2")
    p1 = _FakeProvider("p1", isin_exc=SymbolNotFound("X"))
    p2 = _FakeProvider("p2", isin_result=info2)
    agg = MarketDataAggregator(providers=[p1, p2])
    info = agg.lookup_isin("X")
    assert info.source == "p2"


# ============================================================================
# Factory
# ============================================================================


def test_factory_default_includes_yfinance_and_stooq():
    fake_settings = SimpleNamespace(
        market_data_providers="yfinance,stooq",
        alphavantage_api_key=None,
        market_data_unhealthy_ttl_seconds=300,
    )
    agg = build_default_aggregator(settings=fake_settings)
    names = [p.name for p in agg.providers]
    assert "yfinance" in names
    assert "stooq" in names


def test_factory_includes_alphavantage_with_key():
    fake_settings = SimpleNamespace(
        market_data_providers="yfinance,stooq,alphavantage",
        alphavantage_api_key="TESTKEY",
        market_data_unhealthy_ttl_seconds=300,
    )
    agg = build_default_aggregator(settings=fake_settings)
    names = [p.name for p in agg.providers]
    assert names == ["yfinance", "stooq", "alphavantage"]


def test_factory_skips_unknown_provider_name():
    fake_settings = SimpleNamespace(
        market_data_providers="yfinance,doesnotexist,stooq",
        alphavantage_api_key=None,
        market_data_unhealthy_ttl_seconds=300,
    )
    agg = build_default_aggregator(settings=fake_settings)
    names = [p.name for p in agg.providers]
    assert names == ["yfinance", "stooq"]


def test_factory_falls_back_when_no_providers_configured():
    fake_settings = SimpleNamespace(
        market_data_providers="",
        alphavantage_api_key=None,
        market_data_unhealthy_ttl_seconds=300,
    )
    agg = build_default_aggregator(settings=fake_settings)
    names = [p.name for p in agg.providers]
    assert names == ["yfinance", "stooq"]


def test_factory_respects_provider_order():
    fake_settings = SimpleNamespace(
        market_data_providers="stooq,yfinance",
        alphavantage_api_key=None,
        market_data_unhealthy_ttl_seconds=300,
    )
    agg = build_default_aggregator(settings=fake_settings)
    names = [p.name for p in agg.providers]
    assert names == ["stooq", "yfinance"]
