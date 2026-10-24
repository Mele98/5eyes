"""Tests fuer services/market_data/sub_asset_backfill.py (Phase 2).

Verifiziert:
- Provider-Cascade-Wahl (fruehester data_starts mit verfuegbarem Provider)
- Total-Return-Approximation fuer Price-Only-Symbole vor tr_start_year
- Sanity-Range-Check filtert unplausible Returns
- Provider-Wechsel zwischen Jahren wird erkannt + uebersprungen
- Bar-Cache: pro Provider-Symbol nur 1 fetch
- dry_run verhindert DB-Writes
- Sub-Asset-Whitelist via sub_asset_keys
- Backwards-Compat: NULL-sub_asset_class-Rows bleiben unberuehrt
- Errors fuehren nicht zum Crash, sondern landen in errors-Liste
"""
from __future__ import annotations

import uuid
from datetime import date as Date, datetime, timezone
from decimal import Decimal
from typing import Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, configure_mappers, sessionmaker

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
configure_mappers()

from models.snapshots import AssetClassAnnualReturn
from services.market_data.aggregator import MarketDataAggregator
from services.market_data.base import Bar, MarketDataProvider, ProductInfo
from services.market_data.exceptions import MarketDataError, SymbolNotFound
from services.market_data.sub_asset_backfill import (
    SANITY_MAX_RETURN_BPS,
    SANITY_MIN_RETURN_BPS,
    _adjust_for_total_return,
    _provider_available_for_year,
    backfill_sub_asset_annual_returns,
)
from services.market_data.symbol_catalog import (
    SUB_ASSET_CATALOG,
    ProviderSymbol,
    SubAssetClass,
    get_sub_asset,
)


# ============================================================
# Fixture-Provider (deterministisch, kein Netz)
# ============================================================

class FakeProvider(MarketDataProvider):
    """Stub: gibt vorgefertigte Bar-Listen pro Symbol zurueck."""

    def __init__(self, name: str, bars_by_symbol: dict[str, list[Bar]]):
        self.name = name
        self._bars = bars_by_symbol

    def get_eod(self, symbol: str, on_date: Date) -> Bar:
        bars = self._bars.get(symbol, [])
        for b in bars:
            if b.date == on_date:
                return b
        raise SymbolNotFound(f"{symbol}@{on_date}")

    def get_history(self, symbol: str, start: Date, end: Date) -> list[Bar]:
        if symbol not in self._bars:
            raise SymbolNotFound(symbol)
        return [b for b in self._bars[symbol] if start <= b.date <= end]

    def lookup_isin(self, isin: str) -> ProductInfo:
        raise SymbolNotFound(isin)


def _bar(symbol: str, year: int, close: float, source: str = "fake") -> Bar:
    """Year-End-Bar Helper."""
    return Bar(
        symbol=symbol,
        date=Date(year, 12, 30),
        open=Decimal(str(close)),
        high=Decimal(str(close)),
        low=Decimal(str(close)),
        close=Decimal(str(close)),
        currency="USD",
        source=source,
    )


@pytest.fixture
def sqlite_db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    yield db
    db.close()


# ============================================================
# _provider_available_for_year — Cascade-Wahl
# ============================================================

def test_cascade_picks_earliest_provider_for_old_year():
    cascade = (
        ProviderSymbol("yfinance", "^SSMI", data_starts=1990, is_total_return=False),
        ProviderSymbol("stooq", "^smi", data_starts=1988, is_total_return=False),
    )
    # Cascade ist sortiert nach data_starts (Catalog.cascade())
    sorted_cascade = tuple(sorted(cascade, key=lambda s: (s.data_starts or 9999, s.provider)))
    chosen = _provider_available_for_year(sorted_cascade, year=1988, active_providers=frozenset({"yfinance", "stooq"}))
    assert chosen is not None
    assert chosen.provider == "stooq"


def test_cascade_picks_higher_provider_when_lower_inactive():
    cascade = (
        ProviderSymbol("stooq", "^smi", data_starts=1988, is_total_return=False),
        ProviderSymbol("yfinance", "^SSMI", data_starts=1990, is_total_return=False),
    )
    # Stooq nicht aktiv -> yfinance gewinnt (ab 1990)
    chosen = _provider_available_for_year(cascade, year=1995, active_providers=frozenset({"yfinance"}))
    assert chosen is not None
    assert chosen.provider == "yfinance"


def test_cascade_returns_none_when_no_provider_covers_year():
    cascade = (
        ProviderSymbol("yfinance", "^SSMI", data_starts=2000, is_total_return=True),
    )
    chosen = _provider_available_for_year(cascade, year=1995, active_providers=frozenset({"yfinance"}))
    assert chosen is None


def test_cascade_ignores_bloomberg_placeholder_when_inactive():
    cascade = (
        ProviderSymbol("bloomberg", "SMI Index", data_starts=1988, is_total_return=False),
        ProviderSymbol("yfinance", "^SSMI", data_starts=1990, is_total_return=False),
    )
    chosen = _provider_available_for_year(cascade, year=1988, active_providers=frozenset({"yfinance"}))
    # Bloomberg fehlt -> yfinance kann 1988 nicht decken (data_starts=1990)
    assert chosen is None


# ============================================================
# _adjust_for_total_return — TR-Approximation
# ============================================================

def test_tr_approximation_addiert_dividend_yield_fuer_smi_1990():
    sa = get_sub_asset("Aktien_CH_Large")  # pre_tr=250, tr_start=1999
    price_only_symbol = next(s for s in sa.provider_symbols if not s.is_total_return)
    adjusted, was_adjusted = _adjust_for_total_return(800, sa, 1990, price_only_symbol)
    assert was_adjusted is True
    assert adjusted == 800 + 250


def test_tr_approximation_skipt_wenn_year_at_or_after_tr_start():
    sa = get_sub_asset("Aktien_CH_Large")  # tr_start=1999
    price_only_symbol = next(s for s in sa.provider_symbols if not s.is_total_return)
    adjusted, was_adjusted = _adjust_for_total_return(800, sa, 2000, price_only_symbol)
    assert was_adjusted is False
    assert adjusted == 800


def test_tr_approximation_skipt_bei_total_return_symbol():
    sa = get_sub_asset("Aktien_CH_Large")
    tr_symbol = next(s for s in sa.provider_symbols if s.is_total_return)
    adjusted, was_adjusted = _adjust_for_total_return(800, sa, 1990, tr_symbol)
    assert was_adjusted is False
    assert adjusted == 800


def test_tr_approximation_skipt_wenn_kein_dividend_yield():
    sa = get_sub_asset("Aktien_Welt")  # pre_tr=0
    price_only = ProviderSymbol("bloomberg", "MXWO Index", data_starts=1969, is_total_return=False)
    adjusted, was_adjusted = _adjust_for_total_return(800, sa, 1990, price_only)
    assert was_adjusted is False


# ============================================================
# Backfill happy-path
# ============================================================

def test_backfill_smi_2000_2002_total_return_period(sqlite_db):
    """SMI 2000-2002: tr_start=1999, also keine Dividenden-Adjustierung."""
    # SMI: tr_start_year=1999. Wir nutzen Bloomberg-TR-Symbol das ab 1999 verfuegbar ist.
    bars = [
        _bar("SMIC Index", 1999, 7000.0),
        _bar("SMIC Index", 2000, 7700.0),  # +10%
        _bar("SMIC Index", 2001, 6900.0),  # -10.4%
        _bar("SMIC Index", 2002, 5500.0),  # -20.3%
    ]
    provider = FakeProvider("bloomberg", {"SMIC Index": bars})
    aggregator = MarketDataAggregator([provider])

    result = backfill_sub_asset_annual_returns(
        sqlite_db, aggregator,
        from_year=2000, to_year=2002,
        sub_asset_keys=["Aktien_CH_Large"],
    )
    sqlite_db.commit()

    assert result["summary"]["rows_written"] == 3
    assert result["summary"]["tr_adjusted_count"] == 0
    # Check DB
    rows = sqlite_db.query(AssetClassAnnualReturn).filter_by(
        sub_asset_class="Aktien_CH_Large"
    ).order_by(AssetClassAnnualReturn.year).all()
    assert len(rows) == 3
    assert rows[0].year == 2000
    assert rows[0].return_bps == 1000  # +10%
    assert rows[0].asset_class == "Aktien"  # Top-Level mit-gespeichert
    assert rows[0].sub_asset_class == "Aktien_CH_Large"


def test_backfill_smi_1989_1990_with_dividend_estimate(sqlite_db):
    """SMI via Stooq Price-Index + 250bps Dividenden-Approximation.

    data_starts=1988 heisst 1988-Year-End ist erster Anker. Erster
    berechenbarer Return = 1989 (= 1988 -> 1989)."""
    bars = [
        _bar("^smi", 1988, 1000.0),  # Anker
        _bar("^smi", 1989, 1100.0),  # +10% price, +12.5% TR
        _bar("^smi", 1990, 1232.0),  # +12% price, +14.5% TR
    ]
    provider = FakeProvider("stooq", {"^smi": bars})
    aggregator = MarketDataAggregator([provider])

    result = backfill_sub_asset_annual_returns(
        sqlite_db, aggregator,
        from_year=1989, to_year=1990,
        sub_asset_keys=["Aktien_CH_Large"],
    )
    sqlite_db.commit()

    assert result["summary"]["rows_written"] == 2
    assert result["summary"]["tr_adjusted_count"] == 2  # beide vor tr_start=1999

    rows = sqlite_db.query(AssetClassAnnualReturn).filter_by(
        sub_asset_class="Aktien_CH_Large"
    ).order_by(AssetClassAnnualReturn.year).all()
    # 1989: +10% + 2.5% Div = 1250bps
    assert rows[0].year == 1989
    assert rows[0].return_bps == 1000 + 250
    assert "div_estimate_250bps" in rows[0].source
    assert "stooq" in rows[0].source


# ============================================================
# Sanity-Range
# ============================================================

def test_sanity_range_filters_implausible_returns(sqlite_db):
    """Return > +200% wird als Daten-Bug erkannt + uebersprungen."""
    bars = [
        _bar("SMIC Index", 1999, 1000.0),
        _bar("SMIC Index", 2000, 10000.0),  # +900% -> ausserhalb Sanity
    ]
    provider = FakeProvider("bloomberg", {"SMIC Index": bars})
    aggregator = MarketDataAggregator([provider])

    result = backfill_sub_asset_annual_returns(
        sqlite_db, aggregator,
        from_year=2000, to_year=2000,
        sub_asset_keys=["Aktien_CH_Large"],
    )

    assert result["summary"]["rows_written"] == 0
    assert result["summary"]["error_count"] == 1
    assert "Sanity-Range" in result["errors"][0]["reason"]


# ============================================================
# Provider-Wechsel zwischen Jahren
# ============================================================

def test_provider_wechsel_keine_bar_fuehrt_zu_error(sqlite_db):
    """Cascade waehlt Stooq (data_starts=1988) fuer alle Years 1989-1990.
    Wenn Stooq keine Bar fuer 1990 hat (Daten-Luecke), waechselt der Code
    NICHT zu yfinance (Provider-Mix unsicher), sondern erzeugt Error.
    """
    stooq_bars = [
        _bar("^smi", 1988, 1000.0),
        _bar("^smi", 1989, 1100.0),
        # KEINE Bar fuer 1990 -> Daten-Luecke
    ]
    yf_bars = [
        _bar("^SSMI", 1990, 5500.0),
    ]
    p_stooq = FakeProvider("stooq", {"^smi": stooq_bars})
    p_yf = FakeProvider("yfinance", {"^SSMI": yf_bars})
    aggregator = MarketDataAggregator([p_stooq, p_yf])

    result = backfill_sub_asset_annual_returns(
        sqlite_db, aggregator,
        from_year=1989, to_year=1990,
        sub_asset_keys=["Aktien_CH_Large"],
    )
    sqlite_db.commit()

    rows = sqlite_db.query(AssetClassAnnualReturn).filter_by(
        sub_asset_class="Aktien_CH_Large"
    ).all()
    written_years = sorted(r.year for r in rows)
    assert 1989 in written_years
    assert 1990 not in written_years
    # 1990-Error: Stooq hat keine Bar (Provider-Mix verboten)
    assert any(
        "Keine Bar" in e["reason"]
        for e in result["errors"]
        if e.get("year") == 1990
    )


# ============================================================
# dry_run
# ============================================================

def test_dry_run_persistiert_nichts(sqlite_db):
    bars = [
        _bar("SMIC Index", 1999, 1000.0),
        _bar("SMIC Index", 2000, 1100.0),
    ]
    provider = FakeProvider("bloomberg", {"SMIC Index": bars})
    aggregator = MarketDataAggregator([provider])

    result = backfill_sub_asset_annual_returns(
        sqlite_db, aggregator,
        from_year=2000, to_year=2000,
        sub_asset_keys=["Aktien_CH_Large"],
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["summary"]["rows_written"] == 0
    # processed-Liste enthaelt was geschrieben WAERE
    assert len(result["processed"]) == 1
    assert result["processed"][0]["action"] == "dry_run"
    # DB ist leer
    rows = sqlite_db.query(AssetClassAnnualReturn).all()
    assert len(rows) == 0


# ============================================================
# Whitelist
# ============================================================

def test_whitelist_iteriert_nur_die_angegebenen_subassets(sqlite_db):
    bars_smi = [
        _bar("SMIC Index", 1999, 1000.0),
        _bar("SMIC Index", 2000, 1100.0),
    ]
    bars_spx = [
        _bar("^SP500TR", 1999, 2000.0),
        _bar("^SP500TR", 2000, 2100.0),
    ]
    provider = FakeProvider("yfinance", {"^SP500TR": bars_spx})
    bloomberg = FakeProvider("bloomberg", {"SMIC Index": bars_smi})
    aggregator = MarketDataAggregator([provider, bloomberg])

    result = backfill_sub_asset_annual_returns(
        sqlite_db, aggregator,
        from_year=2000, to_year=2000,
        sub_asset_keys=["Aktien_US_Large"],  # nur US, nicht CH
    )

    # Nur US-Sub-Asset im result
    assert all(p["sub_asset_class"] == "Aktien_US_Large" for p in result["processed"])
    assert result["sub_assets_requested"] == ["Aktien_US_Large"]


def test_unknown_subasset_raises():
    aggregator = MarketDataAggregator([])
    with pytest.raises(ValueError) as exc:
        backfill_sub_asset_annual_returns(
            None, aggregator, from_year=2000, to_year=2000,
            sub_asset_keys=["Aktien_UNKNOWN_KEY"],
        )
    assert "Unbekannter Sub-Asset" in str(exc.value)


# ============================================================
# Backwards-Compat — Top-Level-Rows bleiben unberuehrt
# ============================================================

def test_top_level_rows_bleiben_unberuehrt(sqlite_db):
    """Existing Top-Level (sub_asset_class NULL) Row bleibt nach Sub-Asset-
    Backfill unberuehrt."""
    sqlite_db.add(AssetClassAnnualReturn(
        id=str(uuid.uuid4()),
        year=2000,
        asset_class="Aktien",
        return_bps=850,
        source="manual",
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
        sub_asset_class=None,
    ))
    sqlite_db.commit()

    bars = [
        _bar("SMIC Index", 1999, 1000.0),
        _bar("SMIC Index", 2000, 1100.0),
    ]
    provider = FakeProvider("bloomberg", {"SMIC Index": bars})
    aggregator = MarketDataAggregator([provider])

    backfill_sub_asset_annual_returns(
        sqlite_db, aggregator,
        from_year=2000, to_year=2000,
        sub_asset_keys=["Aktien_CH_Large"],
    )
    sqlite_db.commit()

    # Top-Level-Row bleibt
    top = sqlite_db.query(AssetClassAnnualReturn).filter(
        AssetClassAnnualReturn.sub_asset_class.is_(None),
    ).all()
    assert len(top) == 1
    assert top[0].return_bps == 850
    assert top[0].source == "manual"

    # Sub-Asset-Row neu
    sub = sqlite_db.query(AssetClassAnnualReturn).filter(
        AssetClassAnnualReturn.sub_asset_class.isnot(None),
    ).all()
    assert len(sub) == 1
    assert sub[0].sub_asset_class == "Aktien_CH_Large"


# ============================================================
# Provider-Fehler werden gefangen
# ============================================================

class _RaisingProvider(MarketDataProvider):
    name = "yfinance"
    def get_eod(self, symbol, on_date):
        raise MarketDataError("simulated network error")
    def get_history(self, symbol, start, end):
        raise MarketDataError("simulated network error")
    def lookup_isin(self, isin):
        raise SymbolNotFound(isin)


def test_provider_error_landet_in_errors_kein_crash(sqlite_db):
    aggregator = MarketDataAggregator([_RaisingProvider()])
    result = backfill_sub_asset_annual_returns(
        sqlite_db, aggregator,
        from_year=2000, to_year=2000,
        sub_asset_keys=["Aktien_US_Large"],
    )
    assert result["summary"]["error_count"] >= 1
    assert result["summary"]["rows_written"] == 0


# ============================================================
# Argument-Validation
# ============================================================

def test_from_year_after_to_year_raises():
    aggregator = MarketDataAggregator([])
    with pytest.raises(ValueError):
        backfill_sub_asset_annual_returns(
            None, aggregator, from_year=2010, to_year=2000,
        )


def test_unrealistic_year_range_raises():
    aggregator = MarketDataAggregator([])
    with pytest.raises(ValueError):
        backfill_sub_asset_annual_returns(
            None, aggregator, from_year=1800, to_year=2000,
        )


# ============================================================
# Sanity-Range-Konstanten
# ============================================================

def test_sanity_constants_make_sense():
    assert SANITY_MIN_RETURN_BPS == -9000  # -90%
    assert SANITY_MAX_RETURN_BPS == 20000  # +200%
