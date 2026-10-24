"""Sprint U-P11a (2026-05-22): Unit-Tests für Annual-Returns-Backfill.

Verifiziert mit Mock-Aggregator (kein Netz):
- _compute_annual_return_bps: korrekte bps-Berechnung, Edge-Cases
- _year_end_prices: nimmt letzte Bar pro Jahr, prefer adjusted_close
- _upsert_annual_return: create + update + skip-on-existing
- backfill_annual_returns: happy-path, errors für SymbolNotFound,
  fehlende Year-Bars, overwrite=False, summary-Counts
- Idempotenz: zweimal aufgerufen ergibt gleiche Werte
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

from models.snapshots import AssetClassAnnualReturn
from services.market_data.annual_returns_backfill import (
    DEFAULT_SYMBOL_MAP,
    _compute_annual_return_bps,
    _upsert_annual_return,
    _year_end_prices,
    backfill_annual_returns,
)
from services.market_data.base import Bar
from services.market_data.exceptions import MarketDataError, SymbolNotFound


# ============================================================================
# Helpers
# ============================================================================


def _bar(symbol: str, year: int, month: int, day: int, close: float, adj: float | None = None) -> Bar:
    return Bar(
        symbol=symbol,
        date=Date(year, month, day),
        open=Decimal(str(close)),
        high=Decimal(str(close)),
        low=Decimal(str(close)),
        close=Decimal(str(close)),
        currency="USD",
        volume=None,
        adjusted_close=Decimal(str(adj)) if adj is not None else None,
        source="mock",
    )


class MockAggregator:
    """Minimaler Stub des MarketDataAggregator für Tests."""
    def __init__(self, history_map: dict[str, list[Bar]] | None = None,
                 raises: dict[str, Exception] | None = None):
        self._history_map = history_map or {}
        self._raises = raises or {}

    def get_history(self, symbol: str, start: Date, end: Date) -> list[Bar]:
        if symbol in self._raises:
            raise self._raises[symbol]
        bars = self._history_map.get(symbol, [])
        return [b for b in bars if start <= b.date <= end]


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ar_backfill.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# ============================================================================
# _compute_annual_return_bps
# ============================================================================


def test_compute_return_bps_positive():
    assert _compute_annual_return_bps(Decimal("110"), Decimal("100")) == 1000


def test_compute_return_bps_negative():
    assert _compute_annual_return_bps(Decimal("80"), Decimal("100")) == -2000


def test_compute_return_bps_returns_none_when_prev_zero():
    assert _compute_annual_return_bps(Decimal("100"), Decimal("0")) is None


def test_compute_return_bps_zero_change():
    assert _compute_annual_return_bps(Decimal("100"), Decimal("100")) == 0


# ============================================================================
# _year_end_prices
# ============================================================================


def test_year_end_prices_takes_last_bar_per_year():
    bars = [
        _bar("X", 2019, 1, 15, 100),
        _bar("X", 2019, 6, 30, 105),
        _bar("X", 2019, 12, 30, 110),  # last in 2019
        _bar("X", 2020, 3, 10, 90),
        _bar("X", 2020, 12, 31, 130),  # last in 2020
    ]
    prices = _year_end_prices(bars, [2019, 2020])
    assert prices[2019] == Decimal("110")
    assert prices[2020] == Decimal("130")


def test_year_end_prices_prefers_adjusted_close():
    bars = [
        _bar("X", 2019, 12, 30, 100, adj=98),
        _bar("X", 2020, 12, 30, 110, adj=108),
    ]
    prices = _year_end_prices(bars, [2019, 2020])
    assert prices[2019] == Decimal("98")
    assert prices[2020] == Decimal("108")


def test_year_end_prices_skips_years_without_bars():
    bars = [_bar("X", 2019, 12, 30, 100)]
    prices = _year_end_prices(bars, [2019, 2020, 2021])
    assert 2019 in prices
    assert 2020 not in prices
    assert 2021 not in prices


# ============================================================================
# _upsert_annual_return
# ============================================================================


def test_upsert_creates_new_row(session_factory):
    with session_factory() as s:
        written, action = _upsert_annual_return(
            s, year=2020, asset_class="Aktien", return_bps=1500,
            source="t", overwrite=True,
        )
        s.commit()
        row = s.query(AssetClassAnnualReturn).filter_by(year=2020, asset_class="Aktien").first()
    assert written is True
    assert action == "created"
    assert row is not None
    assert row.return_bps == 1500


def test_upsert_updates_existing_when_overwrite(session_factory):
    with session_factory() as s:
        _upsert_annual_return(s, year=2020, asset_class="Aktien", return_bps=1000, source="t", overwrite=True)
        s.commit()
        written, action = _upsert_annual_return(s, year=2020, asset_class="Aktien", return_bps=1500, source="t2", overwrite=True)
        s.commit()
        row = s.query(AssetClassAnnualReturn).filter_by(year=2020, asset_class="Aktien").first()
    assert written is True
    assert action == "updated"
    assert row.return_bps == 1500
    assert row.source == "t2"


def test_upsert_skips_existing_when_not_overwrite(session_factory):
    with session_factory() as s:
        _upsert_annual_return(s, year=2020, asset_class="Aktien", return_bps=1000, source="t", overwrite=True)
        s.commit()
        written, action = _upsert_annual_return(s, year=2020, asset_class="Aktien", return_bps=9999, source="t2", overwrite=False)
        s.commit()
        row = s.query(AssetClassAnnualReturn).filter_by(year=2020, asset_class="Aktien").first()
    assert written is False
    assert action == "skipped_exists"
    assert row.return_bps == 1000  # unverändert


# ============================================================================
# backfill_annual_returns — End-to-End mit Mock-Aggregator
# ============================================================================


def _build_aktien_history():
    """5 Jahre Aktien-Index mit bekannten Year-End-Preisen."""
    return [
        _bar("URTH", 2018, 12, 28, 100, adj=100),
        _bar("URTH", 2019, 12, 30, 120, adj=120),  # +20%
        _bar("URTH", 2020, 12, 31, 138, adj=138),  # +15%
        _bar("URTH", 2021, 12, 30, 165.6, adj=165.6),  # +20%
        _bar("URTH", 2022, 12, 30, 140.76, adj=140.76),  # -15%
    ]


def test_backfill_happy_path_writes_correct_returns(session_factory):
    mock = MockAggregator(history_map={"URTH": _build_aktien_history()})
    with session_factory() as s:
        result = backfill_annual_returns(
            s, mock,
            from_year=2019, to_year=2022,
            symbol_map={"Aktien": "URTH"},
            overwrite=True,
        )
        s.commit()
        rows = s.query(AssetClassAnnualReturn).filter_by(asset_class="Aktien").order_by(AssetClassAnnualReturn.year).all()
    assert result["summary"]["error_count"] == 0
    assert result["summary"]["rows_written"] == 4
    assert len(rows) == 4
    by_year = {r.year: r.return_bps for r in rows}
    # 2019: 120/100 - 1 = 20% = 2000
    # 2020: 138/120 - 1 = 15% = 1500
    # 2021: 165.6/138 - 1 = 20% = 2000
    # 2022: 140.76/165.6 - 1 ≈ -15% = -1500
    assert by_year[2019] == 2000
    assert by_year[2020] == 1500
    assert by_year[2021] == 2000
    assert abs(by_year[2022] - (-1500)) <= 1  # Rundungsdrift


def test_backfill_idempotent_when_called_twice(session_factory):
    mock = MockAggregator(history_map={"URTH": _build_aktien_history()})
    with session_factory() as s:
        backfill_annual_returns(s, mock, from_year=2019, to_year=2022,
                                symbol_map={"Aktien": "URTH"}, overwrite=True)
        s.commit()
        result2 = backfill_annual_returns(s, mock, from_year=2019, to_year=2022,
                                          symbol_map={"Aktien": "URTH"}, overwrite=True)
        s.commit()
        rows = s.query(AssetClassAnnualReturn).filter_by(asset_class="Aktien").all()
    # Beim 2. Call werden bestehende Rows nur aktualisiert (gleiche Werte) -> "updated"
    assert len(rows) == 4
    assert all(p["action"] == "updated" for p in result2["processed"])


def test_backfill_records_errors_for_symbol_not_found(session_factory):
    mock = MockAggregator(raises={"BAD_TICKER": SymbolNotFound("nope")})
    with session_factory() as s:
        result = backfill_annual_returns(
            s, mock,
            from_year=2019, to_year=2020,
            symbol_map={"Aktien": "BAD_TICKER"},
            overwrite=True,
        )
        s.commit()
        rows = s.query(AssetClassAnnualReturn).all()
    assert result["summary"]["rows_written"] == 0
    assert result["summary"]["error_count"] >= 1
    assert any("BAD_TICKER" in (e.get("symbol") or "") for e in result["errors"])
    assert rows == []


def test_backfill_records_errors_for_missing_year_bars(session_factory):
    """Bars decken 2019+2020+2022 ab, 2021 fehlt -> Error für 2021."""
    bars = [
        _bar("X", 2018, 12, 30, 100),
        _bar("X", 2019, 12, 30, 110),
        _bar("X", 2020, 12, 30, 120),
        # 2021 fehlt
        _bar("X", 2022, 12, 30, 130),
    ]
    mock = MockAggregator(history_map={"X": bars})
    with session_factory() as s:
        result = backfill_annual_returns(
            s, mock, from_year=2019, to_year=2022,
            symbol_map={"Aktien": "X"}, overwrite=True,
        )
        s.commit()
    # 2019, 2020 ok; 2021 fehlt -> Error; 2022 fehlt Anchor 2021 -> Error
    written_years = sorted(p["year"] for p in result["processed"])
    error_years = sorted(e.get("year") for e in result["errors"] if e.get("year"))
    assert 2019 in written_years
    assert 2020 in written_years
    assert 2021 in error_years
    assert 2022 in error_years


def test_backfill_overwrite_false_keeps_existing(session_factory):
    mock = MockAggregator(history_map={"URTH": _build_aktien_history()})
    with session_factory() as s:
        # Vorbelegen mit anderem Wert
        _upsert_annual_return(s, year=2020, asset_class="Aktien", return_bps=9999,
                              source="manual", overwrite=True)
        s.commit()
        result = backfill_annual_returns(s, mock, from_year=2019, to_year=2020,
                                          symbol_map={"Aktien": "URTH"}, overwrite=False)
        s.commit()
        row_2019 = s.query(AssetClassAnnualReturn).filter_by(year=2019, asset_class="Aktien").first()
        row_2020 = s.query(AssetClassAnnualReturn).filter_by(year=2020, asset_class="Aktien").first()
    # 2019: kein Vorbelegt -> wurde geschrieben (action=created)
    actions_by_year = {p["year"]: p["action"] for p in result["processed"]}
    assert actions_by_year[2019] == "created"
    assert actions_by_year[2020] == "skipped_exists"
    assert row_2020.return_bps == 9999  # unverändert
    assert row_2019.return_bps == 2000  # frisch geschrieben


def test_backfill_raises_on_inverted_range(session_factory):
    mock = MockAggregator()
    with session_factory() as s:
        with pytest.raises(ValueError, match="from_year"):
            backfill_annual_returns(s, mock, from_year=2025, to_year=2020,
                                    symbol_map={"Aktien": "X"})


def test_backfill_handles_market_data_error_per_asset_class(session_factory):
    """Ein Provider-Crash bei einem Symbol darf andere Asset-Klassen nicht killen."""
    mock = MockAggregator(
        history_map={"URTH": _build_aktien_history()},
        raises={"AGG": MarketDataError("Provider chain failed")},
    )
    with session_factory() as s:
        result = backfill_annual_returns(
            s, mock, from_year=2019, to_year=2020,
            symbol_map={"Aktien": "URTH", "Obligationen": "AGG"},
            overwrite=True,
        )
        s.commit()
    # Aktien: 2 Rows geschrieben; Obligationen: 1 Error
    written_classes = {p["asset_class"] for p in result["processed"]}
    error_classes = {e["asset_class"] for e in result["errors"]}
    assert "Aktien" in written_classes
    assert "Obligationen" in error_classes
    assert "Obligationen" not in written_classes


def test_default_symbol_map_covers_all_asset_classes():
    """DEFAULT_SYMBOL_MAP muss exakt die 5 Asset-Klassen abdecken,
    die in routers/system.py _VALID_ASSET_CLASSES definiert sind."""
    expected = {"Aktien", "Obligationen", "Immobilien", "Liquiditaet", "Alternative"}
    assert set(DEFAULT_SYMBOL_MAP.keys()) == expected
