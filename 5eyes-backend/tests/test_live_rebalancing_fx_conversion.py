"""Mega-Audit (2026-08-04), Marktdaten-Dimension: Live-Rebalancing rechnete
nie eine FX-Konvertierung fuer Fremdwaehrungspositionen. Preise aus
PriceHistory sind in product.currency notiert (z.B. USD fuer einen US-ETF);
_value_from_units_milli multiplizierte units_milli direkt mit dem
unkonvertierten price_rappen. Live reproduziertes Audit-Beispiel: 200 Stueck
eines USD-ETF (XLE) bei Kurs USD 88.00 zeigte CHF 17'600.00 statt dem
tatsaechlichen CHF-Gegenwert (~CHF 15'312 bei Kurs 0.87, +14.9% Ueberzeichnung).

Diese Tests sperren den Fix: _convert_price_rappen_to_target_currency() wird
jetzt auf latest_price_rappen/reference_price_rappen angewendet, BEVOR sie in
_value_from_units_milli einfliessen -- holding.market_value_rappen/
avg_cost_price_rappen (manuelle, CHF-angenommene Berater-Eingabe laut
Frontend-Formular) bleiben bewusst unkonvertiert.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.currency.fx_rates import FXRateSource
from services.portfolio_engine_live_rebalancing import (
    _build_live_rebalancing_entry,
    _convert_price_rappen_to_target_currency,
    _value_from_units_milli,
)


# ===========================================================================
# 1. _convert_price_rappen_to_target_currency — Helper-Ebene
# ===========================================================================


def test_convert_price_rappen_applies_cross_rate():
    fx = FXRateSource()  # DEFAULT_FX_RATES: USD=0.88, CHF=1.0
    result = _convert_price_rappen_to_target_currency(8800, "USD", fx, "CHF")
    assert result == 7744  # 8800 * 0.88


def test_convert_price_rappen_none_fx_source_is_noop():
    """Backwards-Compat: kein fx_source uebergeben -> unveraendert (alle
    Aufrufer, die diesen Parameter noch nicht kennen, bleiben unveraendert)."""
    result = _convert_price_rappen_to_target_currency(8800, "USD", None, "CHF")
    assert result == 8800


def test_convert_price_rappen_same_currency_is_noop():
    fx = FXRateSource()
    result = _convert_price_rappen_to_target_currency(8800, "CHF", fx, "CHF")
    assert result == 8800


def test_convert_price_rappen_none_price_passthrough():
    fx = FXRateSource()
    assert _convert_price_rappen_to_target_currency(None, "USD", fx, "CHF") is None


# ===========================================================================
# 2. _build_live_rebalancing_entry — volles Audit-Reproduktions-Szenario
# ===========================================================================


def _make_product(currency="CHF"):
    return SimpleNamespace(
        id="prod-xle",
        product_name="Energy Select Sector ETF",
        asset_class="Aktien",
        sub_asset_class="Aktien Global",
        currency=currency,
    )


def _make_position():
    return SimpleNamespace(id="pos-1", reference_lookup_mode="direct")


def _make_price(price_rappen, price_date="2026-08-01", source="yfinance"):
    return SimpleNamespace(
        price_rappen=price_rappen, price_date=price_date, source=source, fetched_at=None,
    )


def _make_holding(units_milli):
    return SimpleNamespace(
        units_milli=units_milli, market_value_rappen=0, avg_cost_price_rappen=0,
        source="manual", as_of_date="2026-08-01", depot_bank=None,
        custody_account_number=None, notes=None,
    )


def test_usd_etf_holding_is_no_longer_overstated_without_fx_conversion():
    """Der Bug VOR dem Fix: ohne fx_source (Default-Parameter) bleibt das
    alte Verhalten erhalten -- 200 Einheiten * USD 88.00 = CHF 17600.00
    (unkonvertiert, ueberzeichnet). Das ist die Backwards-Compat-Baseline,
    gegen die Test 2 (MIT Konvertierung) kontrastiert wird."""
    product = _make_product(currency="USD")
    position = _make_position()
    holding = _make_holding(units_milli=200_000)  # 200 Stueck
    latest_price = _make_price(8800)  # USD 88.00

    entry, _stats = _build_live_rebalancing_entry(
        position=position, product=product, holding=holding,
        latest_price=latest_price, reference_price=None,
        reference_recalibrated=False, target_amount_rappen=1_700_000,
        target_weight_bps=1000, stale_after_days=5,
        today=__import__("datetime").date(2026, 8, 3),
        fx_source=None, target_currency="CHF",
    )
    assert entry["current_market_value_rappen"] == 1_760_000  # CHF 17'600.00, unkonvertiert
    assert entry["fx_converted"] is False


def test_usd_etf_holding_correctly_converted_to_chf_with_fx_source():
    """Der Fix: MIT fx_source wird der USD-Kurs vor der Bewertung auf CHF
    umgerechnet. DEFAULT_FX_RATES: USD=0.88 -> 8800*0.88=7744 Rappen/Einheit
    -> 200'000 milli-Einheiten * 7744 / 1000 = 1'548'800 Rappen = CHF 15'488."""
    product = _make_product(currency="USD")
    position = _make_position()
    holding = _make_holding(units_milli=200_000)
    latest_price = _make_price(8800)
    fx = FXRateSource()

    entry, stats = _build_live_rebalancing_entry(
        position=position, product=product, holding=holding,
        latest_price=latest_price, reference_price=None,
        reference_recalibrated=False, target_amount_rappen=1_700_000,
        target_weight_bps=1000, stale_after_days=5,
        today=__import__("datetime").date(2026, 8, 3),
        fx_source=fx, target_currency="CHF",
    )
    assert entry["current_market_value_rappen"] == 1_548_800
    assert entry["fx_converted"] is True
    assert entry["product_currency"] == "USD"
    # Die Ueberzeichnung aus dem unkonvertierten Fall (1'760'000) ist behoben --
    # der konvertierte Wert muss niedriger sein (USD schwaecher als CHF).
    assert entry["current_market_value_rappen"] < 1_760_000


def test_chf_product_is_never_marked_as_fx_converted():
    """Ein CHF-Produkt (Regelfall, Schweizer Portfolio) darf durch den Fix
    nicht veraendert werden -- Regressionsschutz fuer den Hauptfall."""
    product = _make_product(currency="CHF")
    position = _make_position()
    holding = _make_holding(units_milli=100_000)
    latest_price = _make_price(10000)  # CHF 100.00
    fx = FXRateSource()

    entry, _stats = _build_live_rebalancing_entry(
        position=position, product=product, holding=holding,
        latest_price=latest_price, reference_price=None,
        reference_recalibrated=False, target_amount_rappen=100_000,
        target_weight_bps=1000, stale_after_days=5,
        today=__import__("datetime").date(2026, 8, 3),
        fx_source=fx, target_currency="CHF",
    )
    assert entry["current_market_value_rappen"] == 1_000_000  # unveraendert
    assert entry["fx_converted"] is False


def test_reference_price_from_price_history_is_also_converted():
    """reference_price_rappen (wenn aus PriceHistory, nicht aus
    holding.avg_cost_price_rappen) muss ebenfalls konvertiert werden --
    sonst wuerde price_change_bps zwei inkonsistent bewertete Preise
    vergleichen."""
    product = _make_product(currency="USD")
    position = _make_position()
    latest_price = _make_price(8800, price_date="2026-08-01")
    reference_price = _make_price(8000, price_date="2026-01-01")  # USD 80.00 zum Run-Anker
    fx = FXRateSource()

    entry, _stats = _build_live_rebalancing_entry(
        position=position, product=product, holding=None,
        latest_price=latest_price, reference_price=reference_price,
        reference_recalibrated=False, target_amount_rappen=1_700_000,
        target_weight_bps=1000, stale_after_days=5,
        today=__import__("datetime").date(2026, 8, 3),
        fx_source=fx, target_currency="CHF",
    )
    # 8000 * 0.88 = 7040
    assert entry["reference_price_rappen"] == 7040
    # 8800 * 0.88 = 7744
    assert entry["latest_price_rappen"] == 7744


def test_holding_manual_market_value_entry_is_not_fx_converted():
    """holding.market_value_rappen/avg_cost_price_rappen (manuelle Berater-
    Eingabe, laut Frontend-Formular in CHF angenommen) bleiben bewusst
    unkonvertiert -- nur PriceHistory-Preise werden umgerechnet."""
    product = _make_product(currency="USD")
    position = _make_position()
    holding = SimpleNamespace(
        units_milli=0, market_value_rappen=1_500_000, avg_cost_price_rappen=7000,
        source="manual", as_of_date="2026-08-01", depot_bank=None,
        custody_account_number=None, notes=None,
    )
    latest_price = _make_price(8800)
    fx = FXRateSource()

    entry, _stats = _build_live_rebalancing_entry(
        position=position, product=product, holding=holding,
        latest_price=latest_price, reference_price=None,
        reference_recalibrated=False, target_amount_rappen=1_700_000,
        target_weight_bps=1000, stale_after_days=5,
        today=__import__("datetime").date(2026, 8, 3),
        fx_source=fx, target_currency="CHF",
    )
    # avg_cost_price_rappen ueberschreibt reference_price_rappen NACH der
    # Konvertierung -- der manuelle CHF-Wert bleibt unveraendert bei 7000.
    assert entry["reference_price_rappen"] == 7000
    assert entry["holding_market_value_rappen"] == 1_500_000


# ===========================================================================
# 3. Backwards-Compat: _value_from_units_milli selbst bleibt unveraendert
# ===========================================================================


def test_value_from_units_milli_unchanged():
    """_value_from_units_milli selbst ist bewusst NICHT geaendert (bleibt
    currency-neutral) -- die Konvertierung passiert VORHER auf der
    price_rappen-Ebene, nicht in dieser Funktion."""
    assert _value_from_units_milli(200_000, 7744) == 1_548_800
    assert _value_from_units_milli(None, 7744, fallback_amount_rappen=500) == 500
