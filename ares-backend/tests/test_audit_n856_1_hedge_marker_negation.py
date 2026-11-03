"""N-856-1 (Pruefrunde #856): Absicherungs-Erkennung aus dem Produktnamen.

Die erste PO-06-Fassung wertete jeden Namen mit "hedged"/"abgesichert"/
"waehrungsgesichert" als abgesichert in die HANDELSwaehrung. Das war in vier
Faellen falsch und nicht konservativ (Fremdwaehrung verschwand, der
Hedge-Vorschlag meldete "nicht empfohlen"):

    "Global Bond Index Unhedged"          CHF -> {CHF: 10000}
    "MSCI World nicht waehrungsgesichert" CHF -> {CHF: 10000}
    "MSCI World nicht abgesichert"        CHF -> {CHF: 10000}
    "S&P 500 EUR Hedged"                  CHF -> {CHF: 10000}  (richtig: EUR)

Jetzt: Negationen fallen auf den Proxy zurueck, die Absicherungswaehrung
kommt aus dem Namen (die Handelswaehrung zaehlt nicht), ein Marker ohne
erkennbare Waehrung faellt konservativ auf den Proxy. Ein kuenftiges
Stammdatenfeld ``is_hedged`` (True/False/None) hat Vorrang vor dem Namen.
"""
from __future__ import annotations

import json

import pytest

from services.product_exposures import currency_exposure_with_source, hedge_from_product_name

PROXY_WORLD_USD = 6500  # Sub-Klassen-Proxy "Aktien Global"


@pytest.mark.parametrize("name", [
    "Global Bond Index Unhedged",
    "MSCI World nicht waehrungsgesichert",
    "MSCI World nicht währungsgesichert",
    "MSCI World nicht abgesichert",
    "MSCI World ungesichert",
    "MSCI World un-hedged",
    "MSCI World not hedged",
    "MSCI World ohne Waehrungsabsicherung",
])
def test_negated_hedge_marker_keeps_foreign_currency_proxy(name):
    exposure, source = currency_exposure_with_source(
        None, "Aktien Global", product_currency="CHF", product_name=name,
    )
    assert source == "sub_klassen_proxy", (name, exposure, source)
    assert exposure["USD"] == PROXY_WORLD_USD


def test_hedge_currency_comes_from_the_name_not_the_trading_currency():
    exposure, source = currency_exposure_with_source(
        None, "Aktien Global", product_currency="CHF", product_name="S&P 500 EUR Hedged",
    )
    assert exposure == {"EUR": 10000}
    assert source == "produktname_absicherung"


@pytest.mark.parametrize("name,ccy", [
    ("Welt-Aktien ETF CHF Hedged", "CHF"),
    ("World Equity CHF-hedged", "CHF"),
    ("Bond Index hedged to CHF", "CHF"),
    ("Aktien Welt EUR abgesichert", "EUR"),
    ("Aktien Welt (CHF waehrungsgesichert)", "CHF"),
])
def test_positive_marker_with_currency(name, ccy):
    exposure, source = currency_exposure_with_source(
        None, "Aktien Global", product_currency="USD", product_name=name,
    )
    assert exposure == {ccy: 10000}, name
    assert source == "produktname_absicherung"


def test_marker_without_currency_falls_back_conservatively_to_proxy():
    exposure, source = currency_exposure_with_source(
        None, "Aktien Global", product_currency="CHF", product_name="MSCI World Hedged",
    )
    assert source == "sub_klassen_proxy"
    assert exposure["USD"] == PROXY_WORLD_USD


def test_hedge_fund_and_non_currency_words_are_not_hedges():
    assert hedge_from_product_name("Global Hedge Fund Index") == (None, None)
    # "ETF" ist ein dreibuchstabiges Wort, aber keine Waehrung
    assert hedge_from_product_name("Core ETF hedged") == (True, None)


def test_is_hedged_flag_has_priority_over_name():
    # Stammdaten sagen ungesichert -> Proxy, obwohl der Name einen Marker traegt.
    exposure, source = currency_exposure_with_source(
        None, "Aktien Global", product_currency="CHF",
        product_name="World CHF Hedged", is_hedged=False,
    )
    assert source == "sub_klassen_proxy"
    # Stammdaten sagen gesichert, Absicherungswaehrung aus den Stammdaten.
    exposure, source = currency_exposure_with_source(
        None, "Aktien Global", product_currency="USD",
        product_name="World", is_hedged=True, hedge_currency="chf",
    )
    assert (exposure, source) == ({"CHF": 10000}, "produktdaten_absicherung")
    # Gesichert ohne bekannte Waehrung -> Name, sonst konservativ Proxy.
    exposure, source = currency_exposure_with_source(
        None, "Aktien Global", product_currency="CHF", product_name="World", is_hedged=True,
    )
    assert source == "sub_klassen_proxy"
    # JSON bleibt oberste Quelle.
    exposure, source = currency_exposure_with_source(
        json.dumps({"USD": 10000}), "Aktien Global", product_currency="CHF",
        product_name="World CHF Hedged", is_hedged=True, hedge_currency="CHF",
    )
    assert (exposure, source) == ({"USD": 10000}, "produktdaten")
