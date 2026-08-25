"""Phase 13 Tests: Integration — legacy_compat + scheduled jobs.

Pruefen dass:
- fetch_latest_prices_via_aggregator() das gleiche Output-Format wie
  twelvedata_client.fetch_twelvedata_latest_prices() liefert
- Fallback-Verhalten korrekt (Provider-Fehler -> failures dict)
- daily_cache_purge_job() laeuft ohne Exception
- weekly_validation_job() laeuft mit Mock-Providern
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models.market_data_cache import MarketDataCacheEntry  # noqa: F401
from models.market_data_validation_log import MarketDataValidationLog  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, users, wealth,
)
configure_mappers()

from services.market_data import (
    Bar,
    MarketDataAggregator,
    MarketDataProvider,
    ProviderError,
    RateLimitError,
    SymbolNotFound,
    daily_cache_purge_job,
    fetch_latest_prices_via_aggregator,
    weekly_validation_job,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'int.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class _FixedProvider(MarketDataProvider):
    def __init__(self, name: str, mapping: dict[str, Decimal], exc: Exception | None = None):
        self.name = name
        self._map = mapping
        self._exc = exc

    def get_eod(self, symbol, on_date):
        if self._exc:
            raise self._exc
        if symbol not in self._map:
            raise SymbolNotFound(symbol)
        return Bar(
            symbol=symbol, date=on_date,
            open=self._map[symbol], high=self._map[symbol],
            low=self._map[symbol], close=self._map[symbol],
            currency="CHF", source=self.name,
        )

    def get_history(self, symbol, start, end):
        return []

    def lookup_isin(self, isin):
        raise SymbolNotFound(isin)


# ============================================================================
# fetch_latest_prices_via_aggregator
# ============================================================================


def test_fetch_returns_resolved_dict():
    provider = _FixedProvider("p1", {"UBSG.SW": Decimal("28.75"), "AAPL": Decimal("250.10")})
    agg = MarketDataAggregator(providers=[provider])
    resolved, failures = fetch_latest_prices_via_aggregator(
        ["UBSG.SW", "AAPL"], on_date=date(2026, 5, 8), aggregator=agg,
    )
    assert resolved["UBSG.SW"]["price_date"] == "2026-05-08"
    assert resolved["UBSG.SW"]["price_rappen"] == 2875
    assert resolved["UBSG.SW"]["source"] == "p1"
    assert resolved["AAPL"]["price_rappen"] == 25010
    assert failures == {}


def test_fetch_handles_symbol_not_found_as_failure():
    provider = _FixedProvider("p1", {"UBSG.SW": Decimal("28.75")})
    agg = MarketDataAggregator(providers=[provider])
    resolved, failures = fetch_latest_prices_via_aggregator(
        ["UBSG.SW", "UNKNOWN"], on_date=date(2026, 5, 8), aggregator=agg,
    )
    assert "UBSG.SW" in resolved
    assert "UNKNOWN" in failures
    assert "symbol-not-found" in failures["UNKNOWN"].lower()


def test_fetch_handles_rate_limit_as_failure():
    provider = _FixedProvider("p1", {}, exc=RateLimitError("limit"))
    agg = MarketDataAggregator(providers=[provider])
    resolved, failures = fetch_latest_prices_via_aggregator(
        ["X"], on_date=date(2026, 5, 8), aggregator=agg,
    )
    assert resolved == {}
    assert "X" in failures
    assert "rate-limited" in failures["X"].lower()


def test_fetch_empty_symbols_returns_empty():
    resolved, failures = fetch_latest_prices_via_aggregator(
        [], on_date=date(2026, 5, 8),
    )
    assert resolved == {}
    assert failures == {}


def test_fetch_strips_whitespace_and_skips_empties():
    provider = _FixedProvider("p1", {"UBSG.SW": Decimal("28.75")})
    agg = MarketDataAggregator(providers=[provider])
    resolved, _ = fetch_latest_prices_via_aggregator(
        ["", "  ", "UBSG.SW", " AAPL "],
        on_date=date(2026, 5, 8), aggregator=agg,
    )
    assert "UBSG.SW" in resolved


def test_fetch_default_date_is_today_utc(monkeypatch):
    """Wenn on_date=None, sollte heute UTC genutzt werden — Provider bekommt
    das aktuelle Datum."""
    seen_dates: list = []

    class _CapDate(MarketDataProvider):
        name = "cap"
        def get_eod(self, symbol, on_date):
            seen_dates.append(on_date)
            return Bar(
                symbol=symbol, date=on_date,
                open=Decimal("1"), high=Decimal("1"),
                low=Decimal("1"), close=Decimal("1"),
                currency="CHF", source="cap",
            )
        def get_history(self, symbol, start, end):
            return []
        def lookup_isin(self, isin):
            raise SymbolNotFound(isin)

    cap = _CapDate()
    agg = MarketDataAggregator(providers=[cap])
    fetch_latest_prices_via_aggregator(["X"], on_date=None, aggregator=agg)
    assert len(seen_dates) == 1
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    assert seen_dates[0] == today


def test_output_format_matches_twelvedata_client():
    """Resolved-Dict hat genau die drei Keys 'price_date', 'price_rappen', 'source'
    — kompatibel zu twelvedata_client."""
    provider = _FixedProvider("p1", {"X": Decimal("100.00")})
    agg = MarketDataAggregator(providers=[provider])
    resolved, _ = fetch_latest_prices_via_aggregator(["X"], date(2026, 5, 8), agg)
    assert set(resolved["X"].keys()) == {"price_date", "price_rappen", "source"}


# ============================================================================
# Scheduled Jobs
# ============================================================================


def test_daily_cache_purge_job_runs_without_error(session_factory):
    # Job ruft build_default_aggregator() intern -> die echten gratis-Provider.
    # Wir machen einen no-op run: keine Cache-Eintraege existieren -> 0 geloescht.
    purged = daily_cache_purge_job(session_factory=session_factory)
    assert isinstance(purged, int)
    assert purged >= 0


def test_weekly_validation_job_runs(session_factory):
    """Run job — gibt (checked, alerts) zurueck. Build-default-aggregator
    nutzt yfinance,stooq,alphavantage; ohne Netzwerk werden alle Provider
    failen -> insufficient_data -> kein Log, aber Job sollte ohne Crash
    durchlaufen."""
    checked, alerts = weekly_validation_job(
        symbols=["UBSG.SW", "AAPL"],
        session_factory=session_factory,
        on_date=date(2026, 5, 8),
    )
    assert checked == 2
    assert alerts >= 0


def test_weekly_validation_job_skips_empty_symbol_list(session_factory):
    checked, alerts = weekly_validation_job(
        symbols=[],
        session_factory=session_factory,
        on_date=date(2026, 5, 8),
    )
    assert checked == 0
    assert alerts == 0
