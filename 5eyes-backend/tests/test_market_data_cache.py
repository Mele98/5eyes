"""Phase 6 Tests: CachedAggregator + JSON-Roundtrip + TTL.

Nutzt eigene SQLite-DB pro Test (tmp_path), echte Cache-Tabelle.
Aggregator wird mit FakeProvider gemockt (kein Netzwerk).
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models.market_data_cache import MarketDataCacheEntry  # noqa: F401 (registers table)

# alle anderen Models importieren damit configure_mappers nicht meckert
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, users, wealth,
)

configure_mappers()

from services.market_data import (
    Bar,
    CachedAggregator,
    DEFAULT_TTL_SECONDS,
    MarketDataAggregator,
    MarketDataProvider,
    ProductInfo,
    SymbolNotFound,
)
from services.market_data.cache import (
    _bar_to_dict,
    _dict_to_bar,
    _dict_to_product,
    _hash_args,
    _is_expired,
    _product_to_dict,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cache.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class _CountingProvider(MarketDataProvider):
    name = "counter"

    def __init__(self, eod=None, history=None, isin=None):
        self._eod = eod
        self._history = history if history is not None else []
        self._isin = isin
        self.eod_calls = 0
        self.history_calls = 0
        self.isin_calls = 0

    def get_eod(self, symbol, on_date):
        self.eod_calls += 1
        if self._eod is None:
            raise SymbolNotFound(symbol)
        return self._eod

    def get_history(self, symbol, start, end):
        self.history_calls += 1
        return list(self._history)

    def lookup_isin(self, isin):
        self.isin_calls += 1
        if self._isin is None:
            raise SymbolNotFound(isin)
        return self._isin


def _bar(d=date(2026, 5, 8), source="counter") -> Bar:
    return Bar(
        symbol="UBSG.SW", date=d,
        open=Decimal("28.50"), high=Decimal("28.90"),
        low=Decimal("28.30"), close=Decimal("28.75"),
        currency="CHF", volume=1_500_000,
        adjusted_close=Decimal("28.75"), source=source,
    )


def _info() -> ProductInfo:
    return ProductInfo(
        isin="CH0244767585", ticker="UBSG.SW", name="UBS Group AG",
        exchange="VTX", currency="CHF", asset_class="EQUITY",
        country="CH", figi="BBG00ABCDEFG", source="counter",
    )


# ============================================================================
# Roundtrip: Bar / ProductInfo
# ============================================================================


def test_bar_roundtrip_preserves_all_fields():
    original = _bar()
    restored = _dict_to_bar(_bar_to_dict(original))
    assert restored == original


def test_bar_roundtrip_handles_none_volume_and_adj():
    original = Bar(
        symbol="X", date=date(2026, 5, 8),
        open=Decimal("1.1"), high=Decimal("1.2"),
        low=Decimal("1.0"), close=Decimal("1.15"),
        currency="USD",
    )
    restored = _dict_to_bar(_bar_to_dict(original))
    assert restored.volume is None
    assert restored.adjusted_close is None
    assert restored == original


def test_product_info_roundtrip():
    original = _info()
    restored = _dict_to_product(_product_to_dict(original))
    assert restored == original


# ============================================================================
# Hash + Expiry-Helpers
# ============================================================================


def test_hash_args_stable_for_same_input():
    a = _hash_args({"a": 1, "b": "x"})
    b = _hash_args({"b": "x", "a": 1})
    assert a == b  # sortierte Keys


def test_hash_args_differs_for_different_input():
    a = _hash_args({"x": 1})
    b = _hash_args({"x": 2})
    assert a != b


def test_is_expired_in_past():
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    assert _is_expired(past) is True


def test_is_expired_in_future():
    fut = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    assert _is_expired(fut) is False


def test_is_expired_invalid_iso_treated_as_expired():
    assert _is_expired("not-a-date") is True


# ============================================================================
# Cache-Hit / Miss
# ============================================================================


def test_get_eod_caches_after_first_call(session_factory):
    counter = _CountingProvider(eod=_bar())
    base = MarketDataAggregator(providers=[counter])
    cached = CachedAggregator(base, session_factory=session_factory)
    bar1 = cached.get_eod("UBSG.SW", date(2026, 5, 8))
    bar2 = cached.get_eod("UBSG.SW", date(2026, 5, 8))
    assert bar1 == bar2
    assert counter.eod_calls == 1  # Cache-Hit beim 2. Call


def test_get_eod_different_symbols_two_provider_calls(session_factory):
    counter = _CountingProvider(eod=_bar())
    base = MarketDataAggregator(providers=[counter])
    cached = CachedAggregator(base, session_factory=session_factory)
    cached.get_eod("UBSG.SW", date(2026, 5, 8))
    cached.get_eod("ROG.SW", date(2026, 5, 8))
    assert counter.eod_calls == 2


def test_get_history_caches_list(session_factory):
    bars = [_bar(d=date(2026, 5, 6)), _bar(d=date(2026, 5, 7)), _bar(d=date(2026, 5, 8))]
    counter = _CountingProvider(history=bars)
    base = MarketDataAggregator(providers=[counter])
    cached = CachedAggregator(base, session_factory=session_factory)
    a = cached.get_history("UBSG.SW", date(2026, 5, 6), date(2026, 5, 8))
    b = cached.get_history("UBSG.SW", date(2026, 5, 6), date(2026, 5, 8))
    assert a == b
    assert counter.history_calls == 1


def test_lookup_isin_caches(session_factory):
    counter = _CountingProvider(isin=_info())
    base = MarketDataAggregator(providers=[counter])
    cached = CachedAggregator(base, session_factory=session_factory)
    a = cached.lookup_isin("CH0244767585")
    b = cached.lookup_isin("CH0244767585")
    assert a == b
    assert counter.isin_calls == 1


# ============================================================================
# Expiry & Invalidation
# ============================================================================


def test_expired_entry_triggers_provider_recall(session_factory):
    """Cache-TTL=0 -> kein Cache-Hit, jeder Call geht zum Provider."""
    counter = _CountingProvider(eod=_bar())
    base = MarketDataAggregator(providers=[counter])
    # eod-TTL auf 0: nie cachen
    cached = CachedAggregator(base, session_factory=session_factory, ttl_seconds={"eod": 0})
    cached.get_eod("UBSG.SW", date(2026, 5, 8))
    cached.get_eod("UBSG.SW", date(2026, 5, 8))
    assert counter.eod_calls == 2


def test_invalidate_removes_entries(session_factory):
    counter = _CountingProvider(eod=_bar())
    base = MarketDataAggregator(providers=[counter])
    cached = CachedAggregator(base, session_factory=session_factory)
    cached.get_eod("UBSG.SW", date(2026, 5, 8))
    deleted = cached.invalidate("eod")
    assert deleted == 1
    cached.get_eod("UBSG.SW", date(2026, 5, 8))
    assert counter.eod_calls == 2  # 2. Call wieder Provider


def test_invalidate_all(session_factory):
    counter = _CountingProvider(eod=_bar(), isin=_info())
    base = MarketDataAggregator(providers=[counter])
    cached = CachedAggregator(base, session_factory=session_factory)
    cached.get_eod("UBSG.SW", date(2026, 5, 8))
    cached.lookup_isin("CH0244767585")
    deleted = cached.invalidate(kind=None)
    assert deleted == 2


def test_purge_expired_removes_old_entries(session_factory):
    """Mit TTL=1s und 1.5s Wartezeit ist der Eintrag expired und wird gepurged."""
    import time as _time
    counter = _CountingProvider(eod=_bar())
    base = MarketDataAggregator(providers=[counter])
    cached = CachedAggregator(base, session_factory=session_factory, ttl_seconds={"eod": 1})
    cached.get_eod("UBSG.SW", date(2026, 5, 8))
    _time.sleep(1.2)
    purged = cached.purge_expired()
    assert purged == 1


# ============================================================================
# Default-TTL
# ============================================================================


def test_default_ttl_values():
    # 24h EOD, 7d History, 180d ISIN — Plan §6
    assert DEFAULT_TTL_SECONDS["eod"] == 24 * 3600
    assert DEFAULT_TTL_SECONDS["history"] == 7 * 24 * 3600
    assert DEFAULT_TTL_SECONDS["isin"] == 180 * 24 * 3600


# ============================================================================
# Defensive: corrupt JSON skips cache silently
# ============================================================================


def test_corrupt_cache_entry_falls_through_to_provider(session_factory):
    counter = _CountingProvider(eod=_bar())
    base = MarketDataAggregator(providers=[counter])
    cached = CachedAggregator(base, session_factory=session_factory)
    # Direkt in DB einen Eintrag mit kaputtem JSON schreiben
    key = _hash_args({"op": "eod", "symbol": "UBSG.SW", "date": "2026-05-08"})
    session = session_factory()
    try:
        session.add(MarketDataCacheEntry(
            cache_kind="eod", cache_key=key,
            value_json="{not valid json}",
            fetched_at=datetime.now(timezone.utc).isoformat(),
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        ))
        session.commit()
    finally:
        session.close()
    # Aufruf: corrupt JSON -> log warning, fall through zum Provider
    bar = cached.get_eod("UBSG.SW", date(2026, 5, 8))
    assert isinstance(bar, Bar)
    assert counter.eod_calls == 1
