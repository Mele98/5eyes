"""2026-08-07 (CEO/CFO/CIO-Audit): _format_amount()/_format_chf() in 13
PDF-Dateien nahmen an, ihr `rappen`-Argument sei intern IMMER CHF, und
riefen bei currency != "CHF" zusaetzlich convert_rappen(rappen, "CHF",
currency) auf. Tatsaechlich liefert die Engine (siehe
portfolio_engine._load_allocation_inputs, target_currency=mandate.
base_currency) advisory_wealth_rappen/bucket_amounts_rappen/etc. bereits
in mandate.base_currency -- die zweite Konvertierung verzerrte den im
FIDLEG-Pflichtdokument angezeigten Betrag (z.B. EUR-Mandat: +~5.3%,
USD-Mandat: +~13.6%, mit den hardcodierten DEFAULT_FX_RATES).

Diese Tests pruefen: bei currency="EUR" muss der Rappen-Wert 1:1 (nur
Cent->Einheit) ausgegeben werden, NICHT durch eine FX-Rate multipliziert.
"""
from __future__ import annotations

import services.pdf.components.cashflows_ziele as cashflows_ziele_mod
import services.pdf.components.effektives_portfolio as effektiv_mod
import services.pdf.components.produkte as produkte_mod
import services.pdf.components.saa_bar_table as saa_bar_mod
import services.pdf.components.vermoegensuebersicht as vermoegen_mod
import services.pdf.components.ziele_table as ziele_table_mod
import services.pdf.documents.anlagestrategie as anlagestrategie_mod
import services.pdf.documents.asset_allocation as asset_allocation_mod
import services.pdf.documents.backtest as backtest_mod
import services.pdf.documents.cost_disclosure as cost_disclosure_mod
import services.pdf.documents.portfolio as portfolio_mod
import services.pdf.documents.protokoll as protokoll_mod
import services.pdf.documents.vertrag as vertrag_mod

RAPPEN = 5_000_000  # 50'000.00 in der jeweiligen Waehrung


def _assert_no_fx_inflation(formatted: str, expected_units: str = "50'000") -> None:
    # Mit dem alten Bug haette EUR ~52'631, USD ~56'818 angezeigt (Division
    # durch die DEFAULT_FX_RATE statt reiner 1:1-Anzeige).
    assert expected_units in formatted, f"unerwarteter Betrag: {formatted}"
    assert "52'631" not in formatted and "56'818" not in formatted


def test_anlagestrategie_format_amount_no_double_conversion():
    _assert_no_fx_inflation(anlagestrategie_mod._format_amount(RAPPEN, "EUR"))


def test_vertrag_format_amount_no_double_conversion():
    _assert_no_fx_inflation(vertrag_mod._format_amount(RAPPEN, "EUR"))


def test_protokoll_format_amount_no_double_conversion():
    _assert_no_fx_inflation(protokoll_mod._format_amount(RAPPEN, "EUR"))


def test_asset_allocation_format_amount_no_double_conversion():
    _assert_no_fx_inflation(asset_allocation_mod._format_amount(RAPPEN, "EUR"))


def test_portfolio_format_amount_no_double_conversion():
    _assert_no_fx_inflation(portfolio_mod._format_amount(RAPPEN, "EUR"))


def test_produkte_format_amount_no_double_conversion():
    _assert_no_fx_inflation(produkte_mod._format_amount(RAPPEN, "EUR"))


def test_effektives_portfolio_format_amount_no_double_conversion():
    _assert_no_fx_inflation(effektiv_mod._format_amount(RAPPEN, "EUR"))


def test_saa_bar_table_format_amount_no_double_conversion():
    _assert_no_fx_inflation(saa_bar_mod._format_amount(RAPPEN, "EUR"))


def test_vermoegensuebersicht_format_amount_no_double_conversion():
    # Diese Variante gibt keinen Waehrungs-Praefix aus -- nur die Zahl.
    _assert_no_fx_inflation(vermoegen_mod._format_amount(RAPPEN, "EUR"))


def test_ziele_table_format_amount_no_double_conversion():
    _assert_no_fx_inflation(ziele_table_mod._format_amount(RAPPEN, "EUR"))


def test_cashflows_ziele_format_amount_no_double_conversion():
    _assert_no_fx_inflation(cashflows_ziele_mod._format_amount(RAPPEN, "EUR"))


def test_backtest_format_chf_no_double_conversion():
    _assert_no_fx_inflation(backtest_mod._format_chf(RAPPEN, "EUR"))


def test_cost_disclosure_pdf_format_amount_no_double_conversion():
    _assert_no_fx_inflation(cost_disclosure_mod._format_amount(RAPPEN, "EUR"))


def test_usd_also_not_inflated():
    # Mit dem alten Bug: RAPPEN / 0.88 ~= 56'818 statt 50'000.
    for mod, fn_name in (
        (anlagestrategie_mod, "_format_amount"),
        (vertrag_mod, "_format_amount"),
        (produkte_mod, "_format_amount"),
    ):
        formatted = getattr(mod, fn_name)(RAPPEN, "USD")
        assert "50'000" in formatted, f"{mod.__name__}: {formatted}"
        assert "56'818" not in formatted
