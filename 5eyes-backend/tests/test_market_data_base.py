"""Phase 1 Tests: Provider-Adapter-Pattern.

Verifiziert dass Interface + Dataclasses + Exceptions korrekt anlegt sind.
Keine Provider-Aufrufe — reines Struktur-Test.
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.market_data import (
    Bar,
    MarketDataError,
    MarketDataProvider,
    ProductInfo,
    ProviderError,
    RateLimitError,
    SymbolNotFound,
)


# ============================================================================
# Dataclass-Struktur
# ============================================================================


def test_bar_is_frozen():
    bar = Bar(
        symbol="UBSG.SW", date=date(2026, 5, 9),
        open=Decimal("28.50"), high=Decimal("28.90"),
        low=Decimal("28.30"), close=Decimal("28.75"),
        currency="CHF",
    )
    with pytest.raises(Exception):
        bar.close = Decimal("99.99")  # type: ignore[misc]


def test_bar_optional_fields_default():
    bar = Bar(
        symbol="UBSG.SW", date=date(2026, 5, 9),
        open=Decimal("28.50"), high=Decimal("28.90"),
        low=Decimal("28.30"), close=Decimal("28.75"),
        currency="CHF",
    )
    assert bar.volume is None
    assert bar.adjusted_close is None
    assert bar.source == "unknown"


def test_product_info_optional_fields():
    info = ProductInfo(isin="CH0244767585", ticker="UBSG.SW", name="UBS Group AG")
    assert info.exchange is None
    assert info.figi is None
    assert info.source == "unknown"


def test_product_info_is_frozen():
    info = ProductInfo(isin="CH0244767585", ticker="UBSG.SW", name="UBS")
    with pytest.raises(Exception):
        info.ticker = "X"  # type: ignore[misc]


# ============================================================================
# Exception-Hierarchie
# ============================================================================


def test_provider_error_inherits_from_market_data_error():
    assert issubclass(ProviderError, MarketDataError)


def test_rate_limit_inherits_from_provider_error():
    assert issubclass(RateLimitError, ProviderError)
    assert issubclass(RateLimitError, MarketDataError)


def test_symbol_not_found_inherits_from_market_data_error():
    assert issubclass(SymbolNotFound, MarketDataError)


def test_exceptions_can_carry_message():
    e = SymbolNotFound("unbekannt: XXXX")
    assert "XXXX" in str(e)


# ============================================================================
# Abstract-Class
# ============================================================================


def test_abstract_provider_cannot_be_instantiated():
    with pytest.raises(TypeError):
        MarketDataProvider()  # type: ignore[abstract]


def test_minimal_concrete_provider_works():
    """Eine konkrete Implementierung mit allen drei abstract Methods muss
    instantiierbar sein."""
    class FakeProvider(MarketDataProvider):
        name = "fake"

        def get_eod(self, symbol, on_date):
            return Bar(
                symbol=symbol, date=on_date,
                open=Decimal("1"), high=Decimal("1"),
                low=Decimal("1"), close=Decimal("1"),
                currency="CHF", source=self.name,
            )

        def get_history(self, symbol, start, end):
            return []

        def lookup_isin(self, isin):
            raise SymbolNotFound(isin)

    fake = FakeProvider()
    assert fake.name == "fake"
    bar = fake.get_eod("X", date(2026, 5, 9))
    assert bar.source == "fake"
    assert fake.get_history("X", date(2026, 5, 1), date(2026, 5, 9)) == []
    with pytest.raises(SymbolNotFound):
        fake.lookup_isin("ZZ")


def test_default_is_healthy_returns_true():
    class FakeProvider(MarketDataProvider):
        name = "fake"

        def get_eod(self, symbol, on_date):
            raise SymbolNotFound(symbol)

        def get_history(self, symbol, start, end):
            return []

        def lookup_isin(self, isin):
            raise SymbolNotFound(isin)

    assert FakeProvider().is_healthy() is True


def test_provider_can_override_is_healthy():
    class UnhealthyProvider(MarketDataProvider):
        name = "down"

        def get_eod(self, symbol, on_date):
            raise SymbolNotFound(symbol)

        def get_history(self, symbol, start, end):
            return []

        def lookup_isin(self, isin):
            raise SymbolNotFound(isin)

        def is_healthy(self) -> bool:
            return False

    assert UnhealthyProvider().is_healthy() is False
