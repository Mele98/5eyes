"""OF-1 / Audit 2026-11/06 O5: OpenFIGI-Boersencodes -> Provider-Symbolik.

Befund vor dem Fix: OpenFIGI liefert Bloomberg-Boersencodes (``LN``, ``GY``,
``FP``, ``NA``, ``IM`` ...). Der Client machte daraus ``VWRL.LN``/``SAP.GY``
bzw. uebernahm ``exch_code`` roh ins Produkt. Diese Codes sind keine
Yahoo-/stooq-Suffixe: Ausserhalb der Schweiz entstand ein Symbol, das kein
Preisprovider aufloest, oder (bei rohem ``exchange_code='LN'``) das blanke
US-Symbol ``VWRL`` -- ein falsches Listing. Nur ``SW`` war zufaellig richtig.

Nach dem Fix: explizite, getestete Tabelle Bloomberg-Code -> interner
Boersencode; das Produkt speichert das blanke Symbol plus internen Code, die
Provider-Symbolik (``.L``, ``.DE`` ...) entsteht erst im Lookup. Unbekannte
Codes -> kein geratenes Suffix, sondern Markierung bzw. Fehler.
"""
from __future__ import annotations

import json

import pytest

import services.openfigi_client as openfigi_client
from models.review import Product
from services.openfigi_client import OPENFIGI_EXCHANGE_CODE_MAP, map_openfigi_exchange_code
from services.product_market_data import lookup_symbol_for_provider, resolve_market_profile


def _fake_openfigi(monkeypatch, data: list[dict]):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps([{"data": data}]).encode("utf-8")

    monkeypatch.setattr(openfigi_client, "urlopen", lambda request, timeout=15: FakeResponse())


def _product(**overrides) -> Product:
    values = dict(
        id="p-of1",
        symbol=None,
        isin="IE00B3RBWM25",
        product_name="OF1 Produkt",
        provider="Test",
        product_type="ETF",
        asset_class="Aktien",
        currency="GBP",
        is_active=1,
        created_at="2026-10-01T00:00:00.000Z",
        updated_at="2026-10-01T00:00:00.000Z",
    )
    values.update(overrides)
    return Product(**values)


# (OpenFIGI-Ticker, exchCode, erwartet yfinance, erwartet stooq)
CASES = [
    ("VWRL", "LN", "VWRL.L", "vwrl.uk"),
    ("VWRL LN", "LN", "VWRL.L", "vwrl.uk"),
    ("SAP", "GY", "SAP.DE", "sap.de"),
    ("UBSG", "SW", "UBSG.SW", "ubsg.sw"),
    ("UBSG SW", "SW", "UBSG.SW", "ubsg.sw"),
    ("NESN", "SE", "NESN.SW", "nesn.sw"),
    ("AIR", "FP", "AIR.PA", "air.fr"),
    ("ASML", "NA", "ASML.AS", "asml.nl"),
    ("ENI", "IM", "ENI.MI", "eni.it"),
    ("IBM", "UN", "IBM", "IBM"),
    ("AAPL", "US", "AAPL", "AAPL"),
]


@pytest.mark.parametrize("ticker,exch,yf_expected,stooq_expected", CASES)
def test_openfigi_candidate_resolves_to_provider_symbol(monkeypatch, ticker, exch, yf_expected, stooq_expected):
    from routers.review import _apply_openfigi_candidate

    _fake_openfigi(monkeypatch, [{"figi": "BBG000TEST01", "ticker": ticker, "exchCode": exch, "name": "X"}])
    candidate = openfigi_client.preview_openfigi_mapping(isin="IE00B3RBWM25")["candidates"][0]

    assert " " not in candidate["ticker"] and "." not in candidate["ticker"]
    assert candidate["exch_code"] == exch  # Rohcode bleibt sichtbar
    assert candidate["exchange_code_status"] == "mapped"

    product = _product()
    _apply_openfigi_candidate(product=product, candidate=candidate, now="2026-11-03T00:00:00.000Z", overwrite_symbol=False)
    profile = resolve_market_profile(product)
    assert lookup_symbol_for_provider(profile, "yfinance") == yf_expected
    assert lookup_symbol_for_provider(profile, "stooq") == stooq_expected


def test_mapping_table_is_explicit_and_targets_known_internal_codes():
    from services.product_market_data import (
        STOOQ_SUFFIX_BY_EXCHANGE,
        US_EXCHANGE_CODES,
        YFINANCE_SUFFIX_BY_EXCHANGE,
    )

    expected_core = {"LN": "L", "GY": "DE", "SW": "SW", "FP": "PA", "NA": "AS", "IM": "MI"}
    for code, internal in expected_core.items():
        assert OPENFIGI_EXCHANGE_CODE_MAP[code] == internal
    for code, internal in OPENFIGI_EXCHANGE_CODE_MAP.items():
        assert internal in US_EXCHANGE_CODES or (
            internal in YFINANCE_SUFFIX_BY_EXCHANGE and internal in STOOQ_SUFFIX_BY_EXCHANGE
        ), f"{code}->{internal} hat keine Provider-Symbolik"


@pytest.mark.parametrize("code", ["XX", "GR", "ZZ"])
def test_unknown_code_is_not_guessed(code):
    assert map_openfigi_exchange_code(code) is None


def test_unknown_code_candidate_is_marked_and_apply_refuses(monkeypatch):
    from routers.review import OpenFigiExchangeCodeUnmapped, _apply_openfigi_candidate

    _fake_openfigi(monkeypatch, [{"figi": "BBG000TEST02", "ticker": "ABC XX", "exchCode": "XX", "name": "X"}])
    candidate = openfigi_client.preview_openfigi_mapping(isin="IE00B3RBWM25")["candidates"][0]
    assert candidate["ticker"] == "ABC"
    assert candidate["exchange_code"] is None
    assert candidate["exchange_code_status"] == "unknown"

    product = _product(symbol=None, exchange_code=None)
    with pytest.raises(OpenFigiExchangeCodeUnmapped):
        _apply_openfigi_candidate(product=product, candidate=candidate, now="2026-11-03T00:00:00.000Z", overwrite_symbol=True)
    assert product.symbol is None and product.exchange_code is None and product.figi is None
