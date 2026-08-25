"""PDF: Pro-Position-Betraege in base_currency (CHF), nicht in Produkt-Waehrung.

target_amount_rappen / current_amount_rappen sind CHF-Rappen. Frueher rendered die
Produkt-/IST-Zeile den Betrag via convert_rappen in die Produkt-CCY (z.B. USD),
waehrend Subtotal/Total/Spaltenkopf ("IST-Wert (CHF)") CHF blieben -> die Zeilen
summierten nicht auf, und ein FX-falscher, falsch etikettierter Betrag stand in
einem unterschriebenen Kundendokument.
"""
from __future__ import annotations

import services.pdf.components.produkte as produkte_mod
import services.pdf.components.effektives_portfolio as effektiv_mod


def _spy_format_amount(mod, monkeypatch):
    calls = []
    orig = mod._format_amount

    def spy(rappen, currency="CHF"):
        calls.append(currency)
        return orig(rappen, currency)

    monkeypatch.setattr(mod, "_format_amount", spy)
    return calls


def test_produkte_amount_uses_base_currency(monkeypatch):
    calls = _spy_format_amount(produkte_mod, monkeypatch)
    products = [{
        "asset_class": "equities", "name": "World ETF", "isin": "IE00B4L5Y983",
        "sub_asset_class": "Aktien Welt", "target_weight_bps": 10000,
        "target_amount_rappen": 5_000_000, "currency": "USD", "ter_bps": 20,
    }]
    produkte_mod._make_isin_table(products, base_currency="CHF")
    assert calls, "kein _format_amount-Aufruf"
    # Produktzeile + Subtotal + Grand-Total: jeder Betrag in base_currency, nie USD.
    assert all(c == "CHF" for c in calls), f"Betrag nicht in base_currency: {calls}"
    assert "USD" not in calls


def test_effektives_portfolio_amount_uses_base_currency(monkeypatch):
    calls = _spy_format_amount(effektiv_mod, monkeypatch)
    positions = [{
        "name": "World ETF", "sub_asset_class": "Aktien Welt",
        "current_weight_bps": 10000, "current_amount_rappen": 5_000_000,
        "currency": "USD", "ter_bps": 20,
    }]
    effektiv_mod.make_effektives_portfolio_section(positions, base_currency="CHF")
    assert calls, "kein _format_amount-Aufruf"
    assert all(c == "CHF" for c in calls), f"Betrag nicht in base_currency: {calls}"
    assert "USD" not in calls
