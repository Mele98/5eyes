"""N-856-10 (Delta-Pruefung #856 auf 612b510f): Kapitalschutz ist keine
Waehrungsabsicherung.

"gesichert" allein galt als Waehrungsmarker. "CHF Kapital gesichert Note" und
"Garantiezertifikat CHF gesichert" meinen Kapitalschutz, ergaben aber 100 %
CHF (nicht konservativ). Jetzt zaehlen nur eindeutige Formen (hedged,
abgesichert, waehrungsgesichert, waehrungsabgesichert,
[Waehrungs]Absicherung); in Kapital-/Garantie-/Schutz-Kontext gibt es keinen
Hedge-Treffer (Proxy).
"""
from __future__ import annotations

import pytest

from services.product_exposures import currency_exposure_with_source, hedge_from_product_name


@pytest.mark.parametrize("name", [
    "CHF Kapital gesichert Note",
    "Garantiezertifikat CHF gesichert",
    "Garantiezertifikat CHF abgesichert",
    "Kapitalschutz-Note CHF abgesichert",
    "Capital Protected Note CHF hedged",
    "World Equity Note 100% capital protected CHF",
    "Aktien Welt CHF garantiert gesichert",
])
def test_capital_protection_context_is_not_a_currency_hedge(name):
    assert hedge_from_product_name(name)[0] is not True, name
    exposure, source = currency_exposure_with_source(
        None, "Aktien Global", product_currency="CHF", product_name=name,
    )
    assert source == "sub_klassen_proxy", (name, exposure)


@pytest.mark.parametrize("name,ccy", [
    ("Aktien Welt CHF waehrungsgesichert", "CHF"),
    ("Aktien Welt CHF währungsabgesichert", "CHF"),
    ("Aktien Welt CHF-abgesichert", "CHF"),
    ("Aktien Welt EUR abgesichert", "EUR"),
])
def test_unambiguous_german_markers_still_hedge(name, ccy):
    assert hedge_from_product_name(name) == (True, ccy), name


def test_plain_gesichert_is_no_marker():
    assert hedge_from_product_name("Aktien Welt CHF gesichert") == (None, None)
