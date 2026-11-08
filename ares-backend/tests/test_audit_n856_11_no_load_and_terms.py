"""N-856-11 (Delta-Pruefung #856 auf 612b510f, kosmetisch): "No-Load" ist
keine Negation; "hedged in USD terms" nennt keine Zielwaehrung.
"""
from __future__ import annotations

from services.product_exposures import hedge_from_product_name


def test_no_load_is_not_a_negation():
    assert hedge_from_product_name("Global Equity No-Load CHF Hedged") == (True, "CHF")
    assert hedge_from_product_name("Global Equity no-load CHF hedged") == (True, "CHF")


def test_hedged_in_currency_terms_is_not_a_target_currency():
    # Zielwaehrung darf nicht aus "in USD terms" gelesen werden; die Waehrung
    # vor dem Marker (CHF) bleibt massgeblich.
    assert hedge_from_product_name("World CHF hedged in USD terms") == (True, "CHF")
    assert hedge_from_product_name("World hedged in USD terms") == (True, None)
    assert hedge_from_product_name("World hedged in CHF") == (True, "CHF")
