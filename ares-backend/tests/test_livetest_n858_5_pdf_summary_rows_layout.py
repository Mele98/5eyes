"""Pruefrunde #858 N-858-5 (kosmetisch).

- AA-PDF: die drei Summenzeilen (Strategiebasis, Reserve, Total) standen nach
  einem Seitenumbruch allein auf der Folgeseite -> mit der letzten Klasse
  zusammenhalten (NOSPLIT).
- Vermoegensuebersicht: Betraege der Total-Zeilen (Paragraph-Zellen) waren
  nicht rechtsbuendig, die Spalte sonst schon.
- Bezeichnung der Reserve in App und PDF identisch.
"""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer

from services.pdf.components.vermoegensuebersicht import make_vermoegensuebersicht_section
from services.pdf.documents.asset_allocation import RESERVE_ROW_LABEL, _make_main_allocation_table
from tests.livetest_monolith_js import html

TARGET = {"equities": 4780, "bonds": 3900, "real_estate": 500, "alternatives": 500, "liquidity": 320}
AMOUNTS = {"equities": 67_398_00, "bonds": 54_990_00, "real_estate": 7_050_00, "alternatives": 7_050_00, "liquidity": 4_512_00}


def _pages_with_table_near_page_end(lead_mm: float) -> list[str]:
    table = _make_main_allocation_table(TARGET, {}, base_currency="CHF", advisory_wealth_rappen=150_000_00,
                                        bucket_amounts_rappen=AMOUNTS, external_reserve_rappen=9_000_00)
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, topMargin=10 * mm, bottomMargin=10 * mm)
    doc.build([Spacer(1, lead_mm * mm), table])
    return [p.extract_text() or "" for p in PdfReader(BytesIO(buf.getvalue())).pages]


def test_summary_rows_never_alone_on_next_page():
    # Vorlauf so waehlen, dass Kopf + Klassen passen, die Summenzeilen aber nicht.
    classes = {"Aktien", "Obligationen", "Immobilien", "Alternative", "Liquidität"}
    summary = ("Total Anlagestrategie", "Liquiditätsreserve (ausserhalb", "Total Beratungsvermögen")
    split_seen = False
    for lead in range(200, 250, 2):
        pages = _pages_with_table_near_page_end(lead)
        split_seen = split_seen or len(pages) > 1
        for page in pages:
            lines = {line.strip() for line in page.splitlines()}
            if any(marker in page for marker in summary):
                assert lines & classes, (lead, page)
    assert split_seen, "Szenario erzeugt keinen Seitenumbruch"


def _cells(flowables):
    tables = [f for f in flowables if hasattr(f, "_cellvalues")]
    for kt in flowables:
        for inner in getattr(kt, "_content", []) or []:
            if hasattr(inner, "_cellvalues"):
                tables.append(inner)
    return tables


def test_total_amount_cells_are_right_aligned():
    flow = make_vermoegensuebersicht_section(
        [{"asset_class": "liquidity", "sub_asset_class": "Konto", "current_amount_rappen": 150_000_00}],
        [{"label": "ETW", "amount_rappen": 500_000_00, "is_liability": False},
         {"label": "Hypo", "amount_rappen": 300_000_00, "is_liability": True}],
    )
    tables = _cells(flow)
    assert len(tables) == 2
    for table in tables:
        amount = table._cellvalues[-1][1]
        assert getattr(amount, "style", None) is not None and amount.style.alignment == TA_RIGHT


def test_reserve_label_identical_in_app_and_pdf():
    assert RESERVE_ROW_LABEL == "Liquiditätsreserve (ausserhalb der Anlagestrategie)"
    src = html()
    assert "ausserhalb der Strategie" not in src
    assert src.count("Liquiditätsreserve (ausserhalb der Anlagestrategie)") >= 1
