"""Pruefrunde #862 (Audit 2026-11/06): Nachbesserungen N-862-2 bis N-862-6.

- N-862-2: Session.start()/openService() ohne Wanduhr-Grenze blockierten den
  Aufrufer beliebig lange (Probe: 4 s).
- N-862-3: Stand eine Gratisquelle VOR der massgeblichen Quelle, lieferte sie
  still (``fallback_reason=None``), obwohl Bloomberg gesund war.
- N-862-4: Preis-Updater mit Primaer ``aggregator`` (inkl. Bloomberg) fiel nach
  dem Abbruch der massgeblichen Quelle auf stooq zurueck.
- N-862-5: Ein einzelner OpenFIGI-Kandidat ohne exchCode wurde auto-applied
  (blankes Symbol = US-Listing); HK ohne fuehrende Nullen [pruefen].
- N-862-6: Abbruch bei ``SymbolNotFound`` der massgeblichen Quelle war durch
  keinen Test gepinnt; ein Rate-Limit verlor seinen Code.

``blpapi`` nur als ``sys.modules``-Stub, OpenFIGI/stooq gefaked, kein Netz.
"""
from __future__ import annotations

import sys
import time
import types
from datetime import date as Date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import price_updater
import routers.review as review_router
from database import Base
from models.review import Product
from models.users import User
from routers.review import auto_apply_product_id_mappings
from schemas.review import ProductIdMappingBatchApplyRequest
from services.market_data import factory, legacy_compat, provider_registry
from services.market_data.aggregator import AUTHORITATIVE_PROVIDER_RATE_LIMITED, MarketDataAggregator
from services.market_data.base import Bar, MarketDataProvider, ProductInfo
from services.market_data.exceptions import (
    AuthoritativeSymbolNotFound,
    ProviderOrderError,
    ProviderUnavailableError,
    RateLimitError,
    SymbolNotFound,
)
from services.market_data.providers.bloomberg_provider import (
    BLOOMBERG_SERVICE_UNAVAILABLE,
    BLOOMBERG_SESSION_UNAVAILABLE,
    BloombergProvider,
)
from services.openfigi_client import map_openfigi_exchange_code


class _Free(MarketDataProvider):
    name = "yfinance"

    def __init__(self):
        self.calls = 0

    def get_eod(self, symbol, on_date):
        self.calls += 1
        return Bar(symbol, on_date, Decimal(1), Decimal(1), Decimal(1), Decimal(1), "CHF", source="yfinance")

    def get_history(self, symbol, start, end):
        self.calls += 1
        return [Bar(symbol, start, Decimal(1), Decimal(1), Decimal(1), Decimal(1), "CHF", source="yfinance")]

    def lookup_isin(self, isin):
        self.calls += 1
        return ProductInfo(isin, "X", "X", source="yfinance")


class _AuthoritativeFake(_Free):
    name = "licensed"
    authoritative = True

    def __init__(self, exc):
        super().__init__()
        self._exc = exc

    def get_eod(self, symbol, on_date):
        raise self._exc

    def get_history(self, symbol, start, end):
        raise self._exc

    def lookup_isin(self, isin):
        raise self._exc


ARGS = {
    "get_eod": ("X", Date(2026, 10, 30)),
    "get_history": ("X", Date(2026, 1, 1), Date(2026, 10, 30)),
    "lookup_isin": ("CH0012005267",),
}


# --------------------------------------------------------------------------- #
# N-862-2
# --------------------------------------------------------------------------- #


def _install_hanging_blpapi(monkeypatch, *, hang_in: str, seconds: float = 2.0):
    options: list[tuple] = []

    class _Opts:
        def setServerHost(self, host):
            pass

        def setServerPort(self, port):
            pass

        def setConnectTimeout(self, ms):
            options.append(("connect_timeout_ms", ms))

        def setNumStartAttempts(self, n):
            options.append(("num_start_attempts", n))

    class _Session:
        def __init__(self, opts):
            pass

        def start(self):
            if hang_in == "start":
                time.sleep(seconds)
            return True

        def openService(self, name):
            if hang_in == "service":
                time.sleep(seconds)
            return True

        def stop(self):
            pass

    fake = types.ModuleType("blpapi")
    fake.SessionOptions = _Opts
    fake.Session = _Session
    monkeypatch.setitem(sys.modules, "blpapi", fake)
    return options


@pytest.mark.parametrize(
    "hang_in,code", [("start", BLOOMBERG_SESSION_UNAVAILABLE), ("service", BLOOMBERG_SERVICE_UNAVAILABLE)]
)
def test_hanging_session_step_is_cut_off_within_limit(monkeypatch, hang_in, code):
    options = _install_hanging_blpapi(monkeypatch, hang_in=hang_in)
    provider = BloombergProvider(start_timeout_seconds=0.2)
    started = time.monotonic()
    with pytest.raises(ProviderUnavailableError) as exc:
        provider.get_eod("SMI Index", Date(2026, 10, 30))
    assert time.monotonic() - started < 1.0
    assert exc.value.code == code
    assert ("num_start_attempts", 1) in options

    free = _Free()
    agg = MarketDataAggregator([BloombergProvider(start_timeout_seconds=0.2), free])
    started = time.monotonic()
    with pytest.raises(ProviderUnavailableError):
        agg.get_eod("SMI Index", Date(2026, 10, 30))
    assert time.monotonic() - started < 1.0
    assert free.calls == 0


def test_default_start_limit_is_short():
    provider = BloombergProvider()
    assert 0 < provider._start_timeout_seconds <= 10


# --------------------------------------------------------------------------- #
# N-862-3
# --------------------------------------------------------------------------- #


def test_authoritative_provider_must_come_first_in_aggregator():
    with pytest.raises(ProviderOrderError):
        MarketDataAggregator([_Free(), BloombergProvider()])
    MarketDataAggregator([BloombergProvider(), _Free()])  # Positivkontrolle
    MarketDataAggregator([_Free()])  # Gratis-Kaskade unveraendert


def test_authoritative_provider_must_come_first_in_registry(monkeypatch):
    monkeypatch.setattr(provider_registry, "_external_provider_map", lambda: {"bloomberg": BloombergProvider()})
    with pytest.raises(provider_registry.ProviderConfigurationError) as exc:
        provider_registry.resolve_providers(SimpleNamespace(market_data_providers="yfinance,bloomberg"))
    assert "an erster Stelle" in str(exc.value)
    ok = provider_registry.resolve_providers(SimpleNamespace(market_data_providers="bloomberg,yfinance"))
    assert [p.name for p in ok] == ["bloomberg", "yfinance"]


# --------------------------------------------------------------------------- #
# N-862-6
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", ["get_eod", "get_history", "lookup_isin"])
def test_symbol_not_found_of_authoritative_source_aborts_chain(method):
    free = _Free()
    agg = MarketDataAggregator([_AuthoritativeFake(SymbolNotFound("unbekannt")), free])
    with pytest.raises(AuthoritativeSymbolNotFound):
        getattr(agg, method)(*ARGS[method])
    assert free.calls == 0


def test_symbol_not_found_of_authoritative_source_with_policy_is_marked():
    free = _Free()
    agg = MarketDataAggregator(
        [_AuthoritativeFake(SymbolNotFound("unbekannt")), free], allow_fallback_from_authoritative=True
    )
    bar = agg.get_eod(*ARGS["get_eod"])
    assert bar.source == "yfinance" and "SYMBOL_NOT_FOUND" in bar.fallback_reason


@pytest.mark.parametrize("method", ["get_eod", "get_history", "lookup_isin"])
def test_rate_limit_of_authoritative_source_keeps_own_code(method):
    free = _Free()
    agg = MarketDataAggregator([_AuthoritativeFake(RateLimitError("limit")), free])
    with pytest.raises(ProviderUnavailableError) as exc:
        getattr(agg, method)(*ARGS[method])
    assert exc.value.code == AUTHORITATIVE_PROVIDER_RATE_LIMITED
    assert free.calls == 0


# --------------------------------------------------------------------------- #
# N-862-4
# --------------------------------------------------------------------------- #


def _product(pid: str, symbol: str) -> Product:
    return Product(
        id=pid, symbol=symbol, isin=None, product_name=f"Produkt {pid}", provider="Test",
        product_type="ETF", asset_class="Equities", currency="CHF", exchange_code="SW", is_active=1,
        created_at="2026-10-01T00:00:00.000Z", updated_at="2026-10-01T00:00:00.000Z",
    )


@pytest.fixture()
def stooq_calls(monkeypatch):
    calls: list[list[str]] = []

    def fake_stooq(symbols, product_by_symbol=None):
        calls.append(list(symbols))
        return {s: (Date.today().isoformat(), 1234500, "stooq") for s in symbols}, {}

    monkeypatch.setattr(price_updater, "_fetch_stooq_symbol_points", fake_stooq)
    monkeypatch.setattr(price_updater, "PRICE_SOURCE", "aggregator")
    monkeypatch.setattr(price_updater, "FALLBACK_PRICE_SOURCE", "stooq")
    return calls


def test_aggregator_primary_with_bloomberg_does_not_fall_back_to_stooq(monkeypatch, stooq_calls):
    monkeypatch.setitem(sys.modules, "blpapi", None)
    agg = MarketDataAggregator([BloombergProvider(), _Free()])
    monkeypatch.setattr(
        price_updater,
        "fetch_latest_prices_via_aggregator",
        lambda symbols: legacy_compat.fetch_latest_prices_via_aggregator(symbols, aggregator=agg),
    )
    points, failures = price_updater.fetch_latest_prices_batch([_product("p-1", "UBSG")])
    assert points == {}
    assert stooq_calls == []
    assert "kein Fallback" in failures["p-1"]["error"]
    assert failures["p-1"]["provider_code"] == "BLOOMBERG_NOT_INSTALLED"


def test_aggregator_primary_with_authoritative_symbol_not_found_does_not_fall_back(monkeypatch, stooq_calls):
    agg = MarketDataAggregator([_AuthoritativeFake(SymbolNotFound("unbekannt")), _Free()])
    monkeypatch.setattr(
        price_updater,
        "fetch_latest_prices_via_aggregator",
        lambda symbols: legacy_compat.fetch_latest_prices_via_aggregator(symbols, aggregator=agg),
    )
    points, failures = price_updater.fetch_latest_prices_batch([_product("p-1", "UBSG")])
    assert points == {} and stooq_calls == []
    assert "p-1" in failures


def test_aggregator_configuration_error_does_not_fall_back_to_stooq(monkeypatch, stooq_calls):
    def _broken(*args, **kwargs):
        raise factory.ProviderConfigurationError("bloomberg muss an erster Stelle stehen")

    monkeypatch.setattr(factory, "build_default_aggregator", _broken)
    monkeypatch.setattr(
        price_updater, "fetch_latest_prices_via_aggregator", legacy_compat.fetch_latest_prices_via_aggregator
    )
    points, failures = price_updater.fetch_latest_prices_batch([_product("p-1", "UBSG")])
    assert points == {} and stooq_calls == []
    assert failures["p-1"]["provider_code"] == "AGGREGATOR_CONFIGURATION_INVALID"


def test_aggregator_primary_free_chain_still_falls_back(monkeypatch, stooq_calls):
    """Positivkontrolle: freie Kette ohne massgebliche Quelle -> markierter stooq-Fallback."""
    monkeypatch.setattr(
        price_updater,
        "fetch_latest_prices_via_aggregator",
        lambda symbols: ({}, {s: "symbol-not-found: weg" for s in symbols}),
    )
    points, failures = price_updater.fetch_latest_prices_batch([_product("p-1", "UBSG")])
    assert failures == {}
    assert points["p-1"].source == "stooq" and points["p-1"].fallback_reason


# --------------------------------------------------------------------------- #
# N-862-5
# --------------------------------------------------------------------------- #


def test_hong_kong_is_not_guessed():
    """Yahoo erwartet fuehrende Nullen (0700.HK) [pruefen] -> keine Abbildung."""
    assert map_openfigi_exchange_code("HK") is None


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'n862.db'}", connect_args={"check_same_thread": False})
    factory_ = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory_
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize("exch", [None, "HK"])
def test_auto_apply_single_candidate_without_mapped_exchange_needs_review(session_factory, monkeypatch, exch):
    candidate = {"figi": "BBG000NOEX01", "ticker": "VWRL", "name": "X", "exch_code": exch}
    monkeypatch.setattr(
        review_router,
        "preview_openfigi_mapping",
        lambda **kwargs: {
            "source": "openfigi", "api_key_used": False, "request_job": {}, "resolved_from": {},
            "warning": None, "error": None, "candidates": [dict(candidate)],
        },
    )
    user = User(
        id="admin-n862", username="admin", password_hash="hash", full_name="Admin", role="admin",
        is_active=1, created_at="2026-10-01T00:00:00.000Z", updated_at="2026-10-01T00:00:00.000Z",
    )
    with session_factory() as session:
        session.add(Product(
            id="p-n862", isin="IE00B3RBWM25", symbol=None, product_name="P", provider="T",
            product_type="ETF", asset_class="Aktien", currency="CHF", is_active=1,
            created_at="2026-10-01T00:00:00.000Z", updated_at="2026-10-01T00:00:00.000Z",
        ))
        session.commit()
        result = auto_apply_product_id_mappings(
            body=ProductIdMappingBatchApplyRequest(limit=10, dry_run=False), db=session, current_user=user,
        )
        stored = session.query(Product).filter(Product.id == "p-n862").one()
    assert result["applied"] == 0
    assert result["items"][0]["status"] == "needs_review"
    assert stored.figi is None and stored.symbol is None
