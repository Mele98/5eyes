"""2026-08-07 (CEO/CFO/CIO-Audit, MD-01): price_updater.py verwendet fuer
JEDES abgerufene PricePoint ausschliesslich product.currency (Stammdaten),
nie eine vom Provider tatsaechlich gemeldete Waehrung -- bei einem
Stammdaten-Tippfehler (z.B. "CHF" fuer einen an der XETRA notierten Titel)
waere der Kurs silent falsch etikettiert/bewertet.

Sicherer Fix OHNE zusaetzlichen Netzwerk-Call (kein Rate-Limit-Risiko fuer
den bestehenden Batch-Preis-Refresh-Job): rein lokaler Abgleich
exchange_code -> plausibel erwartete Waehrung, als Datenqualitaets-Warnung
im read-only Admin-Status-Endpoint. Bewusst NICHT in der Live-Preis-Pipeline
selbst (siehe services/product_market_data.py Docstring) -- die eigentliche
Preisabruf-Logik bleibt unveraendert, dies ist zusaetzliche Sichtbarkeit.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.product_market_data import (
    currency_mismatch_warning,
    expected_currency_for_exchange,
)


def _product(**kwargs):
    defaults = dict(
        product_name="Test", symbol="ABC", isin=None, currency="CHF",
        exchange_code=None, lookup_mode_override=None, lookup_symbol_override=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_expected_currency_known_exchanges():
    assert expected_currency_for_exchange("SW") == "CHF"
    assert expected_currency_for_exchange("DE") == "EUR"
    assert expected_currency_for_exchange("L") == "GBP"
    assert expected_currency_for_exchange("NASDAQ") == "USD"
    assert expected_currency_for_exchange(None) is None
    assert expected_currency_for_exchange("UNKNOWN_CODE") is None


def test_mismatch_detected_for_wrong_currency_on_xetra():
    """Stammdaten-Tippfehler: Produkt an der XETRA (DE, erwartet EUR), aber
    Stammdaten sagen faelschlich CHF."""
    product = _product(currency="CHF", exchange_code="DE")
    warning = currency_mismatch_warning(product)
    assert warning is not None
    assert "CHF" in warning and "EUR" in warning


def test_no_mismatch_when_currency_matches_exchange():
    product = _product(currency="EUR", exchange_code="DE")
    assert currency_mismatch_warning(product) is None


def test_no_mismatch_for_us_product_in_usd():
    product = _product(currency="USD", exchange_code="NASDAQ")
    assert currency_mismatch_warning(product) is None


def test_no_mismatch_when_no_exchange_code_resolvable():
    """Kein exchange_code -> nichts pruefbar, kein falscher Alarm."""
    product = _product(currency="CHF", exchange_code=None)
    assert currency_mismatch_warning(product) is None


def test_no_mismatch_for_proxy_lookup_mode():
    """Proxy-Lookups (z.B. 'Swisscanto Bond CHF' via US-ETF 'BND') sind
    bewusst ein andersartiges Stellvertreter-Wertpapier -- ein Waehrungs-
    Abgleich waere hier irrefuehrend, nicht ein echter Datenqualitaets-Fehler."""
    product = _product(
        product_name="Swisscanto Bond CHF", currency="CHF",
        symbol=None, isin=None, exchange_code=None,
    )
    assert currency_mismatch_warning(product) is None


def test_swiss_product_correctly_shows_no_mismatch():
    product = _product(currency="CHF", exchange_code="SW")
    assert currency_mismatch_warning(product) is None
