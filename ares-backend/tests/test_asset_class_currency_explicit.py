"""Market-Data: Notierungswaehrung je Asset-Klasse-Proxy explizit statt geraten.

stooq_currency() raet die Waehrung aus dem Symbol-Suffix und liefert fuer nicht-US-
Symbole (z.B. '.SW'/'^SSMI'/'^STOXX') faelschlich USD. Da die gespeicherte currency
im Backtest die FX-Ueberlagerung steuert, wird sie fuer die (durchweg USD-)Proxies
explizit gesetzt; ein Ersatz durch ein nicht-USD-Symbol erzwingt so eine bewusste
Waehrungs-Pflege statt einer stillen Fehl-Etikettierung.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.market_data.annual_returns_backfill import DEFAULT_SYMBOL_MAP
from services.market_data.asset_class_price_backfill import (
    DEFAULT_CURRENCY_MAP,
    _resolve_currency,
)


def test_explicit_currency_overrides_provider_guess():
    # Selbst wenn der Provider fuer 'Aktien' faelschlich GBP raet, gewinnt die
    # explizite (korrekte) USD-Angabe.
    assert _resolve_currency("Aktien", "GBP") == "USD"
    assert _resolve_currency("Liquiditaet", None) == "USD"


def test_unknown_asset_class_falls_back_to_provider():
    assert _resolve_currency("Exotisch", "eur") == "EUR"
    assert _resolve_currency("Exotisch", None) is None


def test_every_proxy_has_explicit_currency():
    # Jede Asset-Klasse mit einem Proxy-Symbol muss eine explizite Waehrung haben,
    # damit keine geratene Waehrung in den Backtest gelangt.
    missing = set(DEFAULT_SYMBOL_MAP) - set(DEFAULT_CURRENCY_MAP)
    assert not missing, f"Proxy-Klassen ohne explizite Waehrung: {missing}"
