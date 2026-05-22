"""Sprint U-P19 (2026-05-22): Unit-Tests für Daily-Price-Backfill.

Verifiziert mit Mock-Aggregator (kein Netz):
- backfill_asset_class_prices: happy-path, close_rappen = price*100,
  adjusted_close bevorzugt, coverage je Asset-Klasse
- Idempotenz: overwrite=False überspringt bestehende Rows
- Pro-Asset-Fehler werden gesammelt, nicht abgebrochen
- from_year > to_year -> ValueError
"""
from __future__ import annotations

import sys
import uuid
from datetime import date as Date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from models.snapshots import AssetClassPriceHistory
from services.market_data.asset_class_price_backfill import (
    DEFAULT_SYMBOL_MAP,
    backfill_asset_class_prices,
)
from services.market_data.base import Bar
from services.market_data.exceptions import SymbolNotFound


def _bar(symbol: str, year: int, month: int, day: int, close: float, adj: float | None = None) -> Bar:
    return Bar(
        symbol=symbol, date=Date(year, month, day),
        open=Decimal(str(close)), high=Decimal(str(close)),
        low=Decimal(str(close)), close=Decimal(str(close)),
        currency="USD", volume=None,
        adjusted_close=Decimal(str(adj)) if adj is not None else None,
        source="mock",
    )


class MockAggregator:
    def __init__(self, history_map=None, raises=None):
        self._history_map = history_map or {}
        self._raises = raises or {}

    def get_history(self, symbol, start, end):
        if symbol in self._raises:
            raise self._raises[symbol]
        bars = self._history_map.get(symbol, [])
        return [b for b in bars if start <= b.date <= end]


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'acp_backfill.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _history_for_all_classes():
    """3 Tage je Proxy-Symbol für alle 5 Asset-Klassen."""
    hist = {}
    for ac_de, symbol in DEFAULT_SYMBOL_MAP.items():
        hist[symbol] = [
            _bar(symbol, 2023, 1, 2, 100.0, adj=100.0),
            _bar(symbol, 2023, 1, 3, 101.0, adj=101.5),
            _bar(symbol, 2023, 1, 4, 102.0, adj=102.0),
        ]
    return hist


def test_backfill_writes_rows_and_coverage(session_factory):
    agg = MockAggregator(history_map=_history_for_all_classes())
    with session_factory() as s:
        result = backfill_asset_class_prices(s, agg, from_year=2023, to_year=2023)
        s.commit()
        total = s.query(AssetClassPriceHistory).count()
    # 5 Klassen * 3 Tage = 15 Rows
    assert total == 15
    assert result["summary"]["rows_written"] == 15
    assert result["summary"]["error_count"] == 0
    assert set(result["coverage"].keys()) == set(DEFAULT_SYMBOL_MAP.keys())
    for ac, cov in result["coverage"].items():
        assert cov["points"] == 3
        assert cov["first"] == "2023-01-02"
        assert cov["last"] == "2023-01-04"


def test_backfill_prefers_adjusted_close_and_scales_rappen(session_factory):
    agg = MockAggregator(history_map=_history_for_all_classes())
    with session_factory() as s:
        backfill_asset_class_prices(s, agg, from_year=2023, to_year=2023)
        s.commit()
        row = (
            s.query(AssetClassPriceHistory)
            .filter_by(asset_class="Aktien", price_date="2023-01-03")
            .first()
        )
    # adjusted_close 101.5 bevorzugt -> 101.5 * 100 = 10150 Rappen
    assert row.close_rappen == 10150


def test_backfill_idempotent_overwrite_false(session_factory):
    agg = MockAggregator(history_map=_history_for_all_classes())
    with session_factory() as s:
        backfill_asset_class_prices(s, agg, from_year=2023, to_year=2023)
        s.commit()
        result2 = backfill_asset_class_prices(s, agg, from_year=2023, to_year=2023, overwrite=False)
        s.commit()
        total = s.query(AssetClassPriceHistory).count()
    assert total == 15  # keine Duplikate
    assert result2["summary"]["rows_written"] == 0
    assert result2["summary"]["rows_skipped"] == 15


def test_backfill_collects_per_asset_errors(session_factory):
    hist = _history_for_all_classes()
    bad_symbol = DEFAULT_SYMBOL_MAP["Immobilien"]
    agg = MockAggregator(history_map=hist, raises={bad_symbol: SymbolNotFound(bad_symbol)})
    with session_factory() as s:
        result = backfill_asset_class_prices(s, agg, from_year=2023, to_year=2023)
        s.commit()
        total = s.query(AssetClassPriceHistory).count()
    # 4 Klassen erfolgreich, Immobilien fehlerhaft
    assert total == 12
    assert result["summary"]["error_count"] == 1
    assert result["errors"][0]["asset_class"] == "Immobilien"
    assert "Immobilien" not in result["coverage"]


def test_backfill_raises_on_inverted_range(session_factory):
    agg = MockAggregator()
    with session_factory() as s:
        with pytest.raises(ValueError, match="from_year > to_year"):
            backfill_asset_class_prices(s, agg, from_year=2024, to_year=2020)
