"""N-856-12 (Delta-Pruefung #856 auf afb495e6): Kapitalschutz-Filter eingeengt.

N-856-10 filterte ueber Wortanfaenge im ganzen Namen (kapital, garant,
capital, protect, schutz, guarant) und verschluckte damit echte Hedges, vor
allem "Capitalisation CHF Hedged Acc" (Standardbezeichnung thesaurierender
Lux-Anteilsklassen). Jetzt zaehlen nur eindeutige Kapitalschutz-Formen:
kapitalschutz, kapitalgeschuetzt, "kapital gesichert", "capital protected",
"capital guaranteed", "capital protection", garantiezertifikat sowie
garantiert/guaranteed direkt vor oder nach capital/kapital. "No Load" mit
Leerzeichen wird wie "No-Load" behandelt.
"""
from __future__ import annotations

import pytest

from services.product_exposures import currency_exposure_with_source, hedge_from_product_name


@pytest.mark.parametrize("prefix", [
    "Capitalisation", "Capital Group", "Kapitalmarkt", "Kapitalanlage", "Kapitalertrag",
    "Protect Fund", "Schutz Aktien", "Garant Fonds", "Guaranteed Income", "No Load",
])
def test_real_hedges_are_not_swallowed(prefix):
    name = f"{prefix} World Equity CHF Hedged Acc"
    assert hedge_from_product_name(name) == (True, "CHF"), name


@pytest.mark.parametrize("name", [
    "CHF Kapital gesichert Note",
    "Capital Protected Note CHF hedged",
    "Garantiezertifikat CHF abgesichert",
    "Kapitalschutz-Note CHF abgesichert",
    "Kapitalgeschützte Anlage CHF hedged",
    "Note capital guaranteed CHF hedged",
    "Garantiert Kapital Note CHF hedged",
    "Capital protection Note CHF hedged",
])
def test_unambiguous_capital_protection_still_falls_back_to_proxy(name):
    assert hedge_from_product_name(name)[0] is not True, name
    exposure, source = currency_exposure_with_source(
        None, "Aktien Global", product_currency="CHF", product_name=name,
    )
    assert source == "sub_klassen_proxy", (name, exposure)
