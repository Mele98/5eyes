"""U-13: echte Seitenzahlen im Advisory-Report-TOC."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from reportlab.lib.units import mm

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.pdf.components.table_of_contents import (  # noqa: E402
    DOT_LEADER,
    TocCollector,
    TocSectionAnchor,
    make_toc_table,
    resolve_toc_rows,
)
from services.pdf.documents.advisory_report import (  # noqa: E402
    render_advisory_report_pdf_from_payload,
)
from test_advisory_report_pdf import _make_minimal_payload  # noqa: E402


def test_toc_collector_records_section_once():
    collector = TocCollector()
    collector.register("ausgangslage", "Ausgangslage", 4)
    collector.register("ausgangslage", "Ausgangslage", 5)
    collector.register("positionen", "Übersicht Ihrer Positionen", 5)

    assert len(collector.entries) == 2
    assert collector.page_numbers_by_title()["Ausgangslage"] == 4
    assert collector.page_numbers_by_id()["positionen"] == 5


def test_toc_section_anchor_registers_current_canvas_page():
    class DummyCanvas:
        def getPageNumber(self):
            return 7

    collector = TocCollector()
    anchor = TocSectionAnchor(collector, "goals", "Zielbasierte Optimierung")
    anchor.canv = DummyCanvas()

    anchor.draw()

    assert collector.entries[0].section_id == "goals"
    assert collector.entries[0].page_number == 7


def test_toc_rows_degrade_without_collector_entries():
    rows = resolve_toc_rows([
        {"nr": 1, "title": "Ausgangslage"},
        {"nr": 2, "title": "Übersicht Ihrer Positionen"},
    ])

    assert rows == [
        {"nr": "01", "title": "Ausgangslage", "leader": "", "page": ""},
        {
            "nr": "02",
            "title": "Übersicht Ihrer Positionen",
            "leader": "",
            "page": "",
        },
    ]


def test_toc_rows_use_dot_leaders_and_page_numbers():
    rows = resolve_toc_rows(
        [{"nr": 1, "title": "Ausgangslage"}],
        {"Ausgangslage": 4},
    )

    assert rows[0]["leader"] == DOT_LEADER
    assert rows[0]["page"] == "4"


def test_toc_rows_resolve_prefix_titles():
    rows = resolve_toc_rows(
        [{"nr": 11, "title": "Building Blocks"}],
        {"Building Blocks / iSAA": 13},
    )

    assert rows[0]["page"] == "13"


def test_toc_table_has_right_aligned_page_column():
    from services.pdf.components.advisory_palette import make_advisory_styles

    styles = make_advisory_styles()
    table = make_toc_table(
        [{"nr": 1, "title": "Ausgangslage"}],
        styles,
        inner_width=180 * mm,
        page_numbers_by_title={"Ausgangslage": 4},
    )

    assert table._colWidths[-1] == 10 * mm


def test_rendered_pdf_toc_contains_real_page_numbers():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()

    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    toc_text = reader.pages[2].extract_text() or ""

    assert "Inhaltsverzeichnis" in toc_text
    for title, page in (
        ("Ausgangslage", "4"),
        ("Übersicht Ihrer Positionen", "5"),
        ("Was wir im Depotcheck prüfen", "6"),
    ):
        pos = toc_text.find(title)
        assert pos >= 0, f"TOC-Titel fehlt: {title}"
        assert page in toc_text[pos:pos + 120], (
            f"Seitenzahl {page} fehlt nahe TOC-Titel {title!r}. "
            f"TOC-Auszug: {toc_text[pos:pos + 120]!r}"
        )
