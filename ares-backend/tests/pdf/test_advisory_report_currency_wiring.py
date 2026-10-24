"""2026-08-07 (CEO/CFO/CIO-Audit): Betrag-Beschriftung im Advisory-Report-
PDF (15-Sektionen-Dokument) und im Kostenausweis-Component war hartcodiert
"CHF", unabhaengig von mandate.base_currency. Diese Tests pruefen die
konkrete Verdrahtung: services.advisory_report liefert jetzt ein
top-level "mandate_currency"-Feld, und die betroffenen PDF-Bausteine
nehmen einen currency-Parameter an statt "CHF" fest zu verdrahten.
"""
from __future__ import annotations

from services.pdf.components.advisory_palette import make_advisory_styles
from services.pdf.components.kostenausweis import build_kostenausweis_flowables
from services.pdf.components.swiss_numbers import format_chf_rappen
from services.pdf.documents.advisory_report import (
    _build_client_info_block,
    _build_wealth_summary_block,
    _goals_table,
)


def _render_text(flowable) -> str:
    """Extrahiert sichtbaren Text aus einer ReportLab-Table/Paragraph-
    Struktur (rekursiv), fuer einfache String-Assertions in Tests."""
    parts: list[str] = []

    def _walk(node):
        text = getattr(node, "text", None)
        if isinstance(text, str):
            parts.append(text)
        rows = getattr(node, "_cellvalues", None)
        if rows:
            for row in rows:
                for cell in row:
                    if isinstance(cell, list):
                        for item in cell:
                            _walk(item)
                    else:
                        _walk(cell)

    _walk(flowable)
    return " ".join(parts)


def test_format_chf_rappen_defaults_to_chf_but_accepts_override():
    assert format_chf_rappen(500000) == "CHF 5'000"
    assert format_chf_rappen(500000, currency="EUR") == "EUR 5'000"
    assert format_chf_rappen(500000, currency="usd") == "USD 5'000"


def test_client_info_block_uses_given_currency_not_chf():
    styles = make_advisory_styles()
    table = _build_client_info_block(
        {"liquiditaetsbedarf_rappen": 1_000_000},
        styles,
        currency="EUR",
    )
    text = _render_text(table)
    assert "EUR 10'000" in text
    assert "CHF 10'000" not in text


def test_wealth_summary_block_uses_given_currency_not_chf():
    styles = make_advisory_styles()
    table = _build_wealth_summary_block(
        {"gesamtvermoegen_rappen": 2_000_000},
        styles,
        currency="EUR",
    )
    text = _render_text(table)
    assert "EUR 20'000" in text
    assert "CHF 20'000" not in text


def test_goals_table_uses_given_currency_not_chf():
    styles = make_advisory_styles()
    goals = [{
        "label": "Hauskauf", "goal_type": "einmalig", "hardness": "hart",
        "target_date": "2035", "target_amount_rappen": 8_000_000,
        "status": "on_track", "probability_bps": 7000, "goal_id": "g1",
    }]
    table = _goals_table(goals, styles, [], currency="EUR")
    text = _render_text(table)
    assert "EUR 80'000" in text
    assert "CHF 80'000" not in text


def test_kostenausweis_flowables_use_data_currency_not_hardcoded_chf():
    styles = make_advisory_styles()
    data = {
        "advisory_wealth_rappen": 100_000_000,
        "currency": "EUR",
        "totals": {
            "one_time_rappen": 1_000_000,
            "annual_rappen": 500_000,
            "first_year_rappen": 1_500_000,
            "one_time_bps": 100,
            "annual_bps": 50,
            "first_year_bps": 150,
        },
        "cost_items": [],
    }
    flowables = build_kostenausweis_flowables(data, styles)
    text = " ".join(_render_text(f) for f in flowables)
    assert "EUR 1'000'000" in text  # ANLAGEBASIS
    assert "CHF 1'000'000" not in text
