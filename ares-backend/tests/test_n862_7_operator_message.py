"""N-862-7 (Dok. 86, Pruefrunde #862 Delta): Betreibermeldung bei ungueltiger
Aggregator-Konfiguration.

Vorher begann die Meldung mit dem internen Steuermarker
``[AUTHORITATIVE_SOURCE_FAILED]`` und endete mit "massgebliche bzw. nicht
freigegebene Primaerquelle aggregator", obwohl gar keine massgebliche Quelle
konfiguriert war (``foo``, Duplikat). Der Marker steuert nur den
Fallback-Entscheid und bleibt dort wirksam (kein stooq-Abruf).
"""
from __future__ import annotations

from datetime import date as Date
from types import SimpleNamespace

import pytest

import price_updater
from models.review import Product
from services.market_data import factory, legacy_compat
from services.market_data.legacy_compat import AUTHORITATIVE_FAILURE_MARKER


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
    monkeypatch.setattr(
        price_updater, "fetch_latest_prices_via_aggregator", legacy_compat.fetch_latest_prices_via_aggregator
    )
    return calls


@pytest.mark.parametrize(
    "configured",
    ["foo", "yfinance,yfinance"],
    ids=["unbekannter-provider", "duplikat"],
)
def test_invalid_configuration_message_names_the_configuration(monkeypatch, stooq_calls, configured):
    original_build = factory.build_default_aggregator
    settings = SimpleNamespace(market_data_providers=configured)
    monkeypatch.setattr(factory, "build_default_aggregator", lambda *a, **k: original_build(settings))
    points, failures = price_updater.fetch_latest_prices_batch([_product("p-1", "UBSG")])
    assert points == {} and stooq_calls == []
    failure = failures["p-1"]
    assert failure["provider_code"] == "AGGREGATOR_CONFIGURATION_INVALID"
    error = failure["error"]
    assert AUTHORITATIVE_FAILURE_MARKER not in error
    assert "massgebliche bzw. nicht freigegebene Primaerquelle" not in error
    assert "Marktdaten-Konfiguration ungueltig, bitte MARKET_DATA_PROVIDERS korrigieren" in error
    assert "MARKET_DATA_PROVIDERS" in error.split("(kein Fallback")[0]
