"""Tests fuer services/market_data/symbol_catalog.py (Phase 1).

Verifiziert:
- Catalog-Integritaet (alle 18 Sub-Assets vorhanden)
- Top-Level-Konsistenz mit existierenden Asset-Klassen
- Provider-Cascade-Order (fruehester Start zuerst)
- Daten-Konsistenz pro Sub-Asset (tr_start >= index_start, etc.)
- Helper-API funktioniert
- Schluessel-Konvention (Underscore-getrennt, mit Top-Level-Praefix)
"""
from __future__ import annotations

import pytest

from services.market_data.symbol_catalog import (
    SUB_ASSET_CATALOG,
    TOP_LEVEL_ASSET_CLASSES,
    ProviderSymbol,
    SubAssetClass,
    all_sub_asset_keys,
    get_sub_asset,
    price_only_symbols,
    provider_cascade,
    sub_assets_for_top_level,
    total_return_symbols,
)


# ============================================================
# Catalog-Konstanten
# ============================================================

def test_top_level_set_matches_existing_classes():
    """Top-Level muss mit DEFAULT_SYMBOL_MAP und _VALID_ASSET_CLASSES uebereinstimmen."""
    assert TOP_LEVEL_ASSET_CLASSES == frozenset({
        "Aktien", "Obligationen", "Immobilien", "Alternative", "Liquiditaet",
    })


def test_catalog_has_18_sub_assets():
    """Phase 1 Spec: 18 Sub-Assets (7 Aktien + 4 Bonds + 2 Immo + 3 Alt + 2 Liq)."""
    assert len(SUB_ASSET_CATALOG) == 18


def test_top_level_distribution():
    """Verteilung der Sub-Assets ueber Top-Level."""
    by_top = {}
    for sa in SUB_ASSET_CATALOG.values():
        by_top[sa.top_level] = by_top.get(sa.top_level, 0) + 1
    assert by_top == {
        "Aktien": 7,
        "Obligationen": 4,
        "Immobilien": 2,
        "Alternative": 3,
        "Liquiditaet": 2,
    }


def test_all_keys_have_top_level_prefix():
    """Schluessel muss mit Top-Level beginnen (z.B. 'Aktien_CH_Large')."""
    for key, sa in SUB_ASSET_CATALOG.items():
        assert key.startswith(sa.top_level + "_"), \
            f"Schluessel {key!r} startet nicht mit '{sa.top_level}_'"


def test_all_top_levels_are_valid():
    """Jedes Sub-Asset hat ein bekanntes Top-Level."""
    for sa in SUB_ASSET_CATALOG.values():
        assert sa.top_level in TOP_LEVEL_ASSET_CLASSES, \
            f"Unbekanntes Top-Level: {sa.top_level!r} bei {sa.key!r}"


def test_key_matches_dict_key():
    """SubAssetClass.key muss exakt mit dem Dict-Schluessel uebereinstimmen."""
    for dict_key, sa in SUB_ASSET_CATALOG.items():
        assert dict_key == sa.key


# ============================================================
# Daten-Plausibilitaet pro Sub-Asset
# ============================================================

@pytest.mark.parametrize("key", list(SUB_ASSET_CATALOG.keys()))
def test_sub_asset_has_provider_symbols(key):
    """Jeder Sub-Asset hat mindestens 1 Provider-Symbol."""
    sa = SUB_ASSET_CATALOG[key]
    assert len(sa.provider_symbols) >= 1


@pytest.mark.parametrize("key", list(SUB_ASSET_CATALOG.keys()))
def test_sub_asset_year_consistency(key):
    """tr_start_year muss >= index_start_year sein."""
    sa = SUB_ASSET_CATALOG[key]
    assert sa.tr_start_year >= sa.index_start_year, \
        f"{key}: tr_start_year {sa.tr_start_year} < index_start_year {sa.index_start_year}"


@pytest.mark.parametrize("key", list(SUB_ASSET_CATALOG.keys()))
def test_sub_asset_year_in_plausible_range(key):
    """index_start_year muss zwischen 1900 und 2025 liegen."""
    sa = SUB_ASSET_CATALOG[key]
    assert 1900 <= sa.index_start_year <= 2025


@pytest.mark.parametrize("key", list(SUB_ASSET_CATALOG.keys()))
def test_pre_tr_dividend_yield_in_range(key):
    """pre_tr_dividend_yield_bps zwischen 0 und 1000 (=10% p.a.)."""
    sa = SUB_ASSET_CATALOG[key]
    assert 0 <= sa.pre_tr_dividend_yield_bps <= 1000


@pytest.mark.parametrize("key", list(SUB_ASSET_CATALOG.keys()))
def test_sub_asset_currency_is_iso3(key):
    """Currency-Code ist 3-stellig (ISO-3)."""
    sa = SUB_ASSET_CATALOG[key]
    assert len(sa.currency) == 3 and sa.currency.isupper()


@pytest.mark.parametrize("key", list(SUB_ASSET_CATALOG.keys()))
def test_provider_symbols_have_known_provider(key):
    """Provider-Name aus bekannter Menge (matched MarketDataProvider.name)."""
    known = {"yfinance", "stooq", "alphavantage", "twelvedata", "openfigi", "bloomberg"}
    sa = SUB_ASSET_CATALOG[key]
    for ps in sa.provider_symbols:
        assert ps.provider in known, f"{key}: unbekannter Provider {ps.provider!r}"


# ============================================================
# SMI-Spezialfall (das Kern-User-Beispiel)
# ============================================================

def test_smi_data_starts_1988():
    """SMI als Aktien_CH_Large muss ab 1988 verfuegbar sein."""
    sa = get_sub_asset("Aktien_CH_Large")
    assert sa.index_start_year == 1988
    # Mindestens ein Provider liefert ab 1988 oder frueher
    assert any(
        (ps.data_starts is not None and ps.data_starts <= 1988)
        for ps in sa.provider_symbols
    )


def test_smi_pre_tr_dividend_yield_documented():
    """SMI Price-Index 1988-1998 braucht Dividenden-Schaetzung."""
    sa = get_sub_asset("Aktien_CH_Large")
    assert sa.tr_start_year > sa.index_start_year, \
        "SMI braucht TR-Start-Year > Index-Start (SMIC ab 1999)"
    assert sa.pre_tr_dividend_yield_bps > 0, \
        "Pre-TR-Periode braucht Dividenden-Schaetzung"


def test_smi_stooq_provider_present():
    """Stooq als Daten-Cascade fuer 1988-1989 (yfinance erst ab 1990)."""
    sa = get_sub_asset("Aktien_CH_Large")
    stooq = [ps for ps in sa.provider_symbols if ps.provider == "stooq"]
    assert len(stooq) >= 1
    assert any(ps.data_starts is not None and ps.data_starts <= 1988 for ps in stooq)


# ============================================================
# Helper-API
# ============================================================

def test_get_sub_asset_returns_correct_class():
    sa = get_sub_asset("Aktien_US_Large")
    assert isinstance(sa, SubAssetClass)
    assert sa.top_level == "Aktien"


def test_get_sub_asset_unknown_key_raises():
    with pytest.raises(KeyError) as exc:
        get_sub_asset("UNKNOWN_KEY")
    assert "Unbekannter Sub-Asset" in str(exc.value)


def test_all_sub_asset_keys_deterministic():
    """all_sub_asset_keys liefert sortierte Liste."""
    keys = all_sub_asset_keys()
    assert list(keys) == sorted(keys)
    assert len(keys) == 18


def test_sub_assets_for_top_level_returns_correct_count():
    aktien = sub_assets_for_top_level("Aktien")
    assert len(aktien) == 7
    assert all(sa.top_level == "Aktien" for sa in aktien)


def test_sub_assets_for_top_level_unknown_returns_empty():
    """Unbekanntes Top-Level liefert leeres Tuple (kein Crash)."""
    result = sub_assets_for_top_level("UNKNOWN")
    assert result == ()


def test_provider_cascade_sorted_by_data_starts():
    """Cascade ordnet fruehester Daten-Start zuerst."""
    cascade = provider_cascade("Aktien_CH_Large")
    starts = [ps.data_starts or 9999 for ps in cascade]
    assert starts == sorted(starts)


def test_total_return_symbols_filters_correctly():
    tr_only = total_return_symbols("Aktien_US_Large")
    assert all(ps.is_total_return for ps in tr_only)


def test_price_only_symbols_filters_correctly():
    price_only = price_only_symbols("Aktien_CH_Large")
    assert all(not ps.is_total_return for ps in price_only)


# ============================================================
# Frozen-Dataclass-Garantien
# ============================================================

def test_sub_asset_class_is_frozen():
    sa = get_sub_asset("Aktien_CH_Large")
    with pytest.raises((AttributeError, Exception)):
        sa.key = "modified"  # type: ignore


def test_provider_symbol_is_frozen():
    sa = get_sub_asset("Aktien_CH_Large")
    ps = sa.provider_symbols[0]
    with pytest.raises((AttributeError, Exception)):
        ps.symbol = "modified"  # type: ignore


# ============================================================
# Schema-Konsistenz: Bloomberg-Marker
# ============================================================

def test_bloomberg_provider_present_for_zukunftssicherheit():
    """Mindestens 50% der Sub-Assets haben einen bloomberg-Symbol-Eintrag.

    Phase 5 (BloombergProvider) wird das aktivieren — heute nur Catalog-
    Hinweis fuer externe pip-Pakete und spaetere Codebase-Erweiterungen.
    """
    bloomberg_count = sum(
        1 for sa in SUB_ASSET_CATALOG.values()
        if any(ps.provider == "bloomberg" for ps in sa.provider_symbols)
    )
    assert bloomberg_count >= len(SUB_ASSET_CATALOG) // 2
