from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.market_data.aggregator import MarketDataAggregator  # noqa: E402
from services.market_data.base import Bar, MarketDataProvider, ProductInfo  # noqa: E402
from services.market_data.exceptions import ProviderError  # noqa: E402
from services.market_data.provider_health_registry import (  # noqa: E402
    ProviderHealthRegistry,
    ensure_provider_health_table,
    latest_provider_health_by_name,
    list_provider_health,
    reset_provider_health,
)


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'provider_health.db'}")
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    ensure_provider_health_table(engine)
    try:
        yield factory
    finally:
        engine.dispose()


class FakeProvider(MarketDataProvider):
    def __init__(self, name: str, *, fail: bool = False, close: str = "100.00"):
        self.name = name
        self.fail = fail
        self.close = Decimal(close)
        self.calls = 0

    def get_eod(self, symbol: str, on_date: date) -> Bar:
        self.calls += 1
        if self.fail:
            raise ProviderError(f"{self.name} unavailable")
        return Bar(
            symbol=symbol,
            date=on_date,
            open=self.close,
            high=self.close,
            low=self.close,
            close=self.close,
            adjusted_close=self.close,
            currency="CHF",
            source=self.name,
        )

    def get_history(self, symbol: str, start: date, end: date) -> list[Bar]:
        return [self.get_eod(symbol, end)]

    def lookup_isin(self, isin: str) -> ProductInfo:
        raise ProviderError("not implemented")


def test_registry_records_unhealthy_event(session_factory):
    registry = ProviderHealthRegistry(session_factory=session_factory, ttl_seconds=60)

    registry.mark_unhealthy(
        "yfinance",
        reason="rate limited",
        operation="get_eod(TEST)",
        error_type="RateLimitError",
        consecutive_errors=2,
    )

    with session_factory() as db:
        events = list_provider_health(db)
    assert len(events) == 1
    assert events[0]["provider_name"] == "yfinance"
    assert events[0]["status"] == "unhealthy"
    assert events[0]["reason"] == "rate limited"
    assert events[0]["consecutive_errors"] == 2
    assert events[0]["recovered_at"] is None


def test_registry_marks_open_events_recovered(session_factory):
    registry = ProviderHealthRegistry(session_factory=session_factory, ttl_seconds=60)
    registry.mark_unhealthy("stooq", reason="network", operation="get_eod")

    registry.mark_healthy("stooq", operation="get_eod")

    with session_factory() as db:
        event = list_provider_health(db)[0]
    assert event["status"] == "recovered"
    assert event["recovered_at"]


def test_reset_provider_health_deletes_all_or_one_provider(session_factory):
    registry = ProviderHealthRegistry(session_factory=session_factory, ttl_seconds=60)
    registry.mark_unhealthy("yfinance", reason="down")
    registry.mark_unhealthy("stooq", reason="down")

    with session_factory() as db:
        deleted_one = reset_provider_health(db, provider_name="yfinance")
        db.commit()
        remaining = list_provider_health(db)
        deleted_rest = reset_provider_health(db)
        db.commit()
        empty = list_provider_health(db)

    assert deleted_one == 1
    assert [event["provider_name"] for event in remaining] == ["stooq"]
    assert deleted_rest == 1
    assert empty == []


def test_list_provider_health_filters_provider_names(session_factory):
    registry = ProviderHealthRegistry(session_factory=session_factory, ttl_seconds=60)
    registry.mark_unhealthy("yfinance", reason="down")
    registry.mark_unhealthy("stooq", reason="down")

    with session_factory() as db:
        filtered = list_provider_health(db, provider_names=["stooq"])

    assert len(filtered) == 1
    assert filtered[0]["provider_name"] == "stooq"


def test_latest_provider_health_by_name_returns_newest_event(session_factory):
    registry = ProviderHealthRegistry(session_factory=session_factory, ttl_seconds=60)
    registry.mark_unhealthy("yfinance", reason="first")
    registry.mark_unhealthy("yfinance", reason="second")

    with session_factory() as db:
        latest = latest_provider_health_by_name(db, ["yfinance"])

    assert latest["yfinance"]["reason"] == "second"


def test_aggregator_records_unhealthy_and_uses_fallback(session_factory):
    registry = ProviderHealthRegistry(session_factory=session_factory, ttl_seconds=60)
    yfinance = FakeProvider("yfinance", fail=True)
    stooq = FakeProvider("stooq", close="99.00")
    aggregator = MarketDataAggregator(
        providers=[yfinance, stooq],
        unhealthy_ttl_seconds=60,
        health_registry=registry,
    )

    bar = aggregator.get_eod("TEST", date(2026, 6, 4))

    assert bar.source == "stooq"
    assert yfinance.calls == 1
    assert stooq.calls == 1
    with session_factory() as db:
        latest = latest_provider_health_by_name(db)
    assert latest["yfinance"]["status"] == "unhealthy"
    assert "unavailable" in latest["yfinance"]["reason"]


def test_aggregator_marks_provider_recovered_after_success(session_factory):
    registry = ProviderHealthRegistry(session_factory=session_factory, ttl_seconds=60)
    yfinance = FakeProvider("yfinance", fail=True)
    stooq = FakeProvider("stooq")
    aggregator = MarketDataAggregator(
        providers=[yfinance, stooq],
        unhealthy_ttl_seconds=60,
        health_registry=registry,
    )
    aggregator.get_eod("TEST", date(2026, 6, 4))

    yfinance.fail = False
    aggregator.health.reset("yfinance")
    aggregator.get_eod("TEST", date(2026, 6, 4))

    with session_factory() as db:
        latest = latest_provider_health_by_name(db)
    assert latest["yfinance"]["status"] == "recovered"
    assert latest["yfinance"]["recovered_at"]


def test_registry_write_failures_do_not_break_aggregator(session_factory):
    class BrokenRegistry:
        def mark_unhealthy(self, *args, **kwargs):
            raise RuntimeError("db down")

        def mark_healthy(self, *args, **kwargs):
            return None

    registry = BrokenRegistry()
    yfinance = FakeProvider("yfinance", fail=True)
    stooq = FakeProvider("stooq")
    aggregator = MarketDataAggregator(
        providers=[yfinance, stooq],
        unhealthy_ttl_seconds=60,
        health_registry=registry,
    )

    bar = aggregator.get_eod("TEST", date(2026, 6, 4))

    assert bar.source == "stooq"
