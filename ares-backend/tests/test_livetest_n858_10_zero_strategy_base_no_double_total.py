"""Delta-Pruefrunde #858 N-858-10 -- Strategiebasis 0 doppelt ausgewiesen.

Befund: Ist die Strategiebasis 0 (Reserve = Beratungsvermoegen), fiel in
``saa_bar_table`` ein Bucket-Betrag 0 auf ``advisory * bps`` und ein Total 0
auf das volle Beratungsvermoegen zurueck: "Total Anlagestrategie CHF 20'000"
+ Reserve 20'000 = "Total Beratungsvermoegen 40'000". Dieselbe Rueckfall-
Klasse steckte in der AA-Subklassentabelle (Subklassenbetrag 0 ->
advisory * bps).

Soll: None (keine Betraege) = Rueckfall, 0 = Basis 0 -> Klassen 0, Total
Anlagestrategie 0, Reserve = Beratungsvermoegen, Total = Beratungsvermoegen.
"""
from __future__ import annotations

import re
from datetime import date
from io import BytesIO

from pypdf import PdfReader

from routers.pdf_reports import _strategy_presentation_amounts
from services.pdf.base import AnlagestrategieData, PDFContext
from services.pdf.reportlab_renderer import ReportLabRenderer

TARGET = {"equities": 5000, "bonds": 4000, "liquidity": 1000}
SUBS = [{"asset_class": "equities", "sub_asset_class": "Aktien Schweiz", "target_weight_bps": 5000},
        {"asset_class": "bonds", "sub_asset_class": "Obligationen CHF", "target_weight_bps": 4000},
        {"asset_class": "liquidity", "sub_asset_class": "Geldmarkt", "target_weight_bps": 1000}]
CTX = PDFContext(mandate_name="M", advisor_name="B", report_date=date(2026, 11, 4),
                 audit_hash="abc123def456789012345678", locale="de-CH")


def _data() -> AnlagestrategieData:
    amounts = _strategy_presentation_amounts(20_000_00, 0, TARGET, SUBS)
    assert amounts["external_reserve_rappen"] == 20_000_00
    return AnlagestrategieData(target_allocation_bps=TARGET, cma_expected_return_bps=300, cma_expected_vol_bps=500,
                               horizon_years=10, advisory_wealth_rappen=20_000_00,
                               strategy_basis_note="keine investierbare Strategiebasis", **amounts)


def _flat(pdf: bytes) -> str:
    return " ".join(" ".join((p.extract_text() or "").split()) for p in PdfReader(BytesIO(pdf)).pages)


def _amounts(text: str) -> list[int]:
    return [int(m.replace("'", "")) for m in re.findall(r"CHF ([0-9][0-9']*)", text)]


def test_strategy_pdf_soll_table_with_zero_base_has_no_double_total():
    text = _flat(ReportLabRenderer().render_anlagestrategie(CTX, _data()))
    assert "40'000" not in text, "Beratungsvermoegen doppelt ausgewiesen"
    start = text.index("SOLL-ALLOKATION")
    block = text[start:text.index("Total Beratungsvermögen", start) + 40]
    assert re.search(r"Total Anlagestrategie \(Strategiebasis\) 100\.0% CHF 0\b", block), block
    assert re.search(r"Liquiditätsreserve \(ausserhalb der Anlagestrategie\) – CHF 20'000", block), block
    assert re.search(r"Total Beratungsvermögen CHF 20'000", block), block
    # Klassen 0 (nicht 10'000/8'000/2'000 vom vollen Vermoegen)
    assert not {10_000, 8_000, 2_000} & set(_amounts(block)), block


def test_asset_allocation_pdf_subclasses_with_zero_base_are_zero():
    text = _flat(ReportLabRenderer().render_asset_allocation(CTX, _data()))
    assert "40'000" not in text
    sub = text[text.index("Aktien Total"):]
    assert not {10_000, 8_000, 2_000} & set(_amounts(sub)), sub[:400]
    assert "CHF 20'000" in sub
