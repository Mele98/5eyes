"""N-856-8 (Delta-Pruefung #856): Negation/Teilabsicherung mit Waehrung dazwischen.

Die N-856-1-Fassung erkannte Negationen nur unmittelbar vor dem Marker.
Stand eine Waehrung dazwischen ("not CHF hedged", "nicht CHF-abgesichert")
oder war nur teilweise abgesichert ("partially CHF hedged"), galt das
Produkt als voll abgesichert -> 100 % CHF, Fremdwaehrung verschwand. Und
"USD Hedged to CHF" lieferte USD statt der Zielwaehrung CHF.

Ausserdem blieb die alte Testdatei auch mit ABGESCHALTETER Negation gruen
(Marker ohne Waehrung fiel ohnehin auf den Proxy). Deshalb hier zusaetzlich
direkte Asserts ``hedge_from_product_name(...)[0] is False``.
"""
from __future__ import annotations

import pytest

from services.product_exposures import currency_exposure_with_source, hedge_from_product_name

NEGATED = [
    "MSCI World not CHF hedged",
    "MSCI World non CHF hedged",
    "MSCI World nicht CHF-abgesichert",
    "MSCI World nicht in CHF abgesichert",
    "MSCI World ohne CHF Absicherung",
    "MSCI World unhedged",
    "MSCI World un-hedged",
    "MSCI World not hedged",
    "MSCI World nicht waehrungsgesichert",
    "MSCI World ungesichert",
]
PARTIAL = [
    "MSCI World partially CHF hedged",
    "MSCI World partial CHF hedged",
    "MSCI World teilweise CHF abgesichert",
    "MSCI World teil-abgesichert CHF",
]


@pytest.mark.parametrize("name", NEGATED + PARTIAL)
def test_negation_or_partial_hedge_is_not_a_full_hedge(name):
    assert hedge_from_product_name(name)[0] is False, name
    exposure, source = currency_exposure_with_source(
        None, "Aktien Global", product_currency="CHF", product_name=name,
    )
    assert source == "sub_klassen_proxy", (name, exposure)
    assert exposure.get("USD") == 6500


@pytest.mark.parametrize("name,ccy", [
    ("World Equity USD Hedged to CHF", "CHF"),
    ("World Equity USD-hedged into EUR", "EUR"),
    ("Bond Index hedged in GBP", "GBP"),
    ("Welt-Aktien ETF CHF Hedged", "CHF"),
    ("Aktien Welt (CHF waehrungsgesichert)", "CHF"),
])
def test_target_currency_after_hedged_to_wins(name, ccy):
    assert hedge_from_product_name(name) == (True, ccy), name


def test_negation_far_before_the_marker_does_not_count():
    # Negationswort mehr als 3 Woerter vor dem Marker gehoert nicht dazu.
    assert hedge_from_product_name("Not a fund of funds world equity CHF hedged") == (True, "CHF")
