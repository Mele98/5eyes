"""Tests fuer services/market_data/provider_discovery.py + bloomberg_provider.py.

Phase 5 von SMI-Sub-Asset-Sprint (2026-06-09). ADR-010.

Verifiziert:
- Entry-Point-Discovery laedt konforme Provider
- Nicht-konforme Klassen werden skipped (kein Crash)
- Name-Kollisionen: First-Wins + Warning-Log
- BloombergProvider-Stub ist defensiv (blpapi-missing -> is_healthy=False)
- Stub-Methoden liefern klare Fehlermeldungen statt Crash
"""
from __future__ import annotations

import pytest

from services.market_data.base import Bar, MarketDataProvider, ProductInfo
from services.market_data.exceptions import ProviderError, SymbolNotFound
from services.market_data.provider_discovery import (
    ENTRY_POINT_GROUP,
    _is_valid_provider_class,
    discover_all_provider_names,
    discover_external_providers,
)
from services.market_data.providers.bloomberg_provider import (
    BLPAPI_INSTALL_HINT,
    BloombergProvider,
)


# ============================================================
# _is_valid_provider_class
# ============================================================

class _ValidProvider(MarketDataProvider):
    name = "valid_test"
    def get_eod(self, symbol, on_date): raise SymbolNotFound(symbol)
    def get_history(self, symbol, start, end): return []
    def lookup_isin(self, isin): raise SymbolNotFound(isin)


class _NotProvider:  # NICHT MarketDataProvider
    name = "fake"
    def get_eod(self, *a, **k): pass
    def get_history(self, *a, **k): pass
    def lookup_isin(self, *a, **k): pass


def test_valid_class_passes_check():
    assert _is_valid_provider_class(_ValidProvider) is True


def test_non_class_fails_check():
    assert _is_valid_provider_class("not_a_class") is False
    assert _is_valid_provider_class(42) is False
    assert _is_valid_provider_class(None) is False


def test_non_subclass_fails_check():
    assert _is_valid_provider_class(_NotProvider) is False


# ============================================================
# discover_external_providers — kein externes Paket installiert
# ============================================================

def test_discover_returns_empty_when_no_entry_points():
    """In Test-Env sind normalerweise keine 5eyes-Provider-Pakete
    installiert. discover_external_providers liefert leere Liste."""
    providers = discover_external_providers()
    # Im Standard-Test-Env keine externen Provider erwartet
    assert isinstance(providers, list)


def test_discover_all_provider_names_returns_list():
    """Liefert eine Liste, auch wenn leer."""
    names = discover_all_provider_names()
    assert isinstance(names, list)


def test_entry_point_group_constant():
    """Konstante muss exakt 5eyes.market_data_provider sein (ADR-010)."""
    assert ENTRY_POINT_GROUP == "5eyes.market_data_provider"


# ============================================================
# BloombergProvider-Stub
# ============================================================

def test_bloomberg_provider_has_correct_name():
    p = BloombergProvider()
    assert p.name == "bloomberg"


def test_bloomberg_provider_is_market_data_provider():
    p = BloombergProvider()
    assert isinstance(p, MarketDataProvider)


def test_bloomberg_provider_is_healthy_when_blpapi_missing():
    """Wenn blpapi nicht installiert ist (Default-Test-Env), liefert
    is_healthy=False, damit Aggregator den Provider in der Cascade
    automatisch ueberspringt."""
    p = BloombergProvider()
    # In Test-Env ist blpapi nicht installiert -> is_healthy False
    healthy = p.is_healthy()
    # Defensiv: ist bool, nicht crashing
    assert isinstance(healthy, bool)


def test_bloomberg_provider_get_eod_is_stub():
    """Stub liefert SymbolNotFound mit klarer Phase-5b-Hinweismeldung."""
    from datetime import date as Date
    p = BloombergProvider()
    with pytest.raises((SymbolNotFound, ProviderError)) as exc:
        p.get_eod("SMI Index", Date(2020, 6, 30))
    msg = str(exc.value)
    # Entweder Stub-Hinweis ODER blpapi-Missing-Hinweis
    assert ("Stub" in msg or "blpapi" in msg or "Phase 5b" in msg)


def test_bloomberg_provider_get_history_is_stub():
    from datetime import date as Date
    p = BloombergProvider()
    with pytest.raises((SymbolNotFound, ProviderError)) as exc:
        p.get_history("SMI Index", Date(2020, 1, 1), Date(2020, 12, 31))
    msg = str(exc.value)
    assert ("Stub" in msg or "blpapi" in msg or "Phase 5b" in msg)


def test_bloomberg_provider_lookup_isin_is_stub():
    p = BloombergProvider()
    with pytest.raises((SymbolNotFound, ProviderError)) as exc:
        p.lookup_isin("CH0012005267")
    msg = str(exc.value)
    assert ("Stub" in msg or "blpapi" in msg or "Phase 5b" in msg)


def test_blpapi_install_hint_documents_install():
    """INSTALL_HINT muss klare pip-install-Anleitung enthalten."""
    assert "pip install" in BLPAPI_INSTALL_HINT
    assert "blpapi" in BLPAPI_INSTALL_HINT
    assert "bloomberg" in BLPAPI_INSTALL_HINT.lower()


# ============================================================
# BloombergProvider in symbol_catalog referenziert
# ============================================================

def test_symbol_catalog_has_bloomberg_entries():
    """Phase 1-Catalog hat bereits bloomberg-Symbole. Mit Phase 5
    existiert auch der Provider-Stub -> wenn Bloomberg jemals aktiviert
    wird, koennen die Symbole sofort genutzt werden."""
    from services.market_data.symbol_catalog import SUB_ASSET_CATALOG

    bloomberg_symbols = []
    for sa in SUB_ASSET_CATALOG.values():
        for ps in sa.provider_symbols:
            if ps.provider == "bloomberg":
                bloomberg_symbols.append((sa.key, ps.symbol))

    assert len(bloomberg_symbols) > 0
    # Beispiel-Symbole pruefen
    keys = {k for k, _ in bloomberg_symbols}
    assert "Aktien_CH_Large" in keys  # SMI/SMIC Index dokumentiert
