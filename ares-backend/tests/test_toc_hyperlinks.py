"""Roadmap #71/#72: PDF-Outline (Sidebar-Bookmarks) + klickbare interne
TOC-Links im Advisory-Report.

U-13 hat bereits echte Seitenzahlen im Two-Pass-Collector gebaut (siehe
`tests/test_toc_page_numbers.py`). Dieses Modul deckt den fehlenden Teil
ab: `TocSectionAnchor` setzt jetzt zusaetzlich `canvas.bookmarkPage()` +
`canvas.addOutlineEntry()`, und `make_toc_table()` verlinkt Titel/Seite
jeder Zeile via `<link href="#section_id">` auf denselben Anker.

Test-Strategie identisch zu `test_advisory_report_pdf.py`: Inline-Payload,
kein DB-Setup, strukturelle Assertions über `pypdf` (Outline + Link-
Annotationen), keine Pixel-Vergleiche.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from reportlab.lib.units import mm

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.pdf.components.table_of_contents import (  # noqa: E402
    TocCollector,
    TocSectionAnchor,
    make_toc_table,
)
from services.pdf.documents.advisory_report import (  # noqa: E402
    render_advisory_report_pdf_from_payload,
)
from test_advisory_report_pdf import _make_minimal_payload  # noqa: E402


# ---------------------------------------------------------------------------
# 1) TocSectionAnchor — bookmarkPage + addOutlineEntry
# ---------------------------------------------------------------------------

class _RecordingCanvas:
    """Minimal Canvas-Double das bookmarkPage/addOutlineEntry aufzeichnet,
    zusaetzlich zur bereits vorher unterstuetzten getPageNumber()."""

    def __init__(self, page_number: int) -> None:
        self._page_number = page_number
        self.bookmark_calls: list[str] = []
        self.outline_calls: list[tuple[str, str, int, int | None]] = []

    def getPageNumber(self) -> int:  # noqa: N802 - ReportLab API name
        return self._page_number

    def bookmarkPage(self, key: str) -> None:  # noqa: N802
        self.bookmark_calls.append(key)

    def addOutlineEntry(  # noqa: N802
        self, title: str, key: str, level: int = 0, closed: int | None = None,
    ) -> None:
        self.outline_calls.append((title, key, level, closed))


def test_toc_section_anchor_bookmarks_its_page():
    collector = TocCollector()
    anchor = TocSectionAnchor(collector, "goals", "Zielbasierte Optimierung")
    canv = _RecordingCanvas(page_number=11)
    anchor.canv = canv

    anchor.draw()

    assert canv.bookmark_calls == ["goals"]


def test_toc_section_anchor_adds_top_level_outline_entry():
    collector = TocCollector()
    anchor = TocSectionAnchor(collector, "positionen", "Übersicht Ihrer Positionen")
    canv = _RecordingCanvas(page_number=5)
    anchor.canv = canv

    anchor.draw()

    assert canv.outline_calls == [
        ("Übersicht Ihrer Positionen", "positionen", 0, 0),
    ]


def test_toc_section_anchor_still_registers_page_number_with_collector():
    """Bookmark/Outline duerfen die bestehende U-13-Seitenzahl-Sammlung
    nicht veraendern."""
    collector = TocCollector()
    anchor = TocSectionAnchor(collector, "goals", "Zielbasierte Optimierung")
    canv = _RecordingCanvas(page_number=11)
    anchor.canv = canv

    anchor.draw()

    assert collector.entries[0].section_id == "goals"
    assert collector.entries[0].page_number == 11


def test_toc_section_anchor_tolerates_canvas_without_bookmark_support():
    """Rueckwaerts-kompatibel zu minimalen Canvas-Doubles (nur
    getPageNumber), z. B. in aelteren Tests — kein AttributeError."""
    class BareCanvas:
        def getPageNumber(self):
            return 3

    collector = TocCollector()
    anchor = TocSectionAnchor(collector, "toc", "Inhaltsverzeichnis")
    anchor.canv = BareCanvas()

    anchor.draw()  # muss nicht crashen

    assert collector.entries[0].page_number == 3


def test_toc_collector_exposes_section_ids_by_title():
    collector = TocCollector()
    collector.register("ausgangslage", "Ausgangslage", 4)
    collector.register("positionen", "Übersicht Ihrer Positionen", 5)

    ids = collector.section_ids_by_title()
    assert ids["Ausgangslage"] == "ausgangslage"
    assert ids["Übersicht Ihrer Positionen"] == "positionen"


# ---------------------------------------------------------------------------
# 2) make_toc_table — <link> Markup je Zeile
# ---------------------------------------------------------------------------

def _styles():
    from services.pdf.components.advisory_palette import make_advisory_styles
    return make_advisory_styles()


def test_toc_table_wraps_title_and_page_in_link_when_section_id_known():
    table = make_toc_table(
        [{"nr": 1, "title": "Ausgangslage"}],
        _styles(),
        inner_width=180 * mm,
        page_numbers_by_title={"Ausgangslage": 4},
        section_ids_by_title={"Ausgangslage": "ausgangslage"},
    )
    title_cell = table._cellvalues[0][1]
    page_cell = table._cellvalues[0][3]
    assert "<link href='#ausgangslage'>" in title_cell.text
    assert "<link href='#ausgangslage'>" in page_cell.text


def test_toc_table_resolves_section_id_via_prefix_match():
    """Gleiche Fuzzy-Matching-Regel wie bei Seitenzahlen (U-13): ein
    Kapitel-Titel darf ein Praefix des gesammelten Anker-Titels sein."""
    table = make_toc_table(
        [{"nr": 11, "title": "Building Blocks"}],
        _styles(),
        inner_width=180 * mm,
        page_numbers_by_title={"Building Blocks / iSAA": 13},
        section_ids_by_title={"Building Blocks / iSAA": "building_blocks"},
    )
    title_cell = table._cellvalues[0][1]
    assert "<link href='#building_blocks'>" in title_cell.text


def test_toc_table_has_no_link_markup_without_section_ids():
    """Degraded-Mode-Kontrakt bleibt unveraendert: ohne section_ids_by_title
    keine Links — nur Text + Seitenzahl (wie vor #71/#72)."""
    table = make_toc_table(
        [{"nr": 1, "title": "Ausgangslage"}],
        _styles(),
        inner_width=180 * mm,
        page_numbers_by_title={"Ausgangslage": 4},
    )
    title_cell = table._cellvalues[0][1]
    assert "<link" not in title_cell.text


def test_toc_table_skips_link_on_page_cell_when_page_unresolved():
    """Wenn ein Kapitel keine gesammelte Seitenzahl hat, gibt es auch
    keinen Link auf eine leere Seiten-Zelle."""
    table = make_toc_table(
        [{"nr": 1, "title": "Unbekanntes Kapitel"}],
        _styles(),
        inner_width=180 * mm,
        page_numbers_by_title={},
        section_ids_by_title={"Unbekanntes Kapitel": "unknown"},
    )
    page_cell = table._cellvalues[0][3]
    assert "<link" not in page_cell.text


# ---------------------------------------------------------------------------
# 3) End-to-End — echtes PDF via pypdf: Outline + Link-Annotationen
# ---------------------------------------------------------------------------

def test_pdf_has_outline_with_section_entries():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(io.BytesIO(pdf))

    outline = reader.outline
    assert outline, "PDF-Outline (Sidebar-Bookmarks) ist leer"
    titles = [item.title for item in outline if not isinstance(item, list)]
    assert "Inhaltsverzeichnis" in titles
    assert "Ausgangslage" in titles


def test_pdf_outline_entries_point_to_matching_page_numbers():
    """Die Outline-Sprungziele muessen dieselben Seiten treffen, die im
    TOC-Text als Seitenzahl gedruckt werden (U-13-Konsistenz)."""
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(io.BytesIO(pdf))

    outline_by_title = {
        item.title: reader.get_destination_page_number(item) + 1
        for item in reader.outline
        if not isinstance(item, list)
    }
    assert outline_by_title["Ausgangslage"] == 4
    assert outline_by_title["Übersicht Ihrer Positionen"] == 5
    assert outline_by_title["Was wir im Depotcheck prüfen"] == 6


def test_toc_page_has_clickable_link_annotations():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(io.BytesIO(pdf))

    toc_page = reader.pages[2]  # Cover=0, Disclaimer=1, TOC=2
    annots = toc_page.get("/Annots") or []
    link_annots = [a for a in annots if a.get_object().get("/Subtype") == "/Link"]
    # 3 Kapitel im Minimal-Payload x 2 verlinkte Zellen (Titel + Seite)
    assert len(link_annots) == 6, (
        f"Erwartet 6 Link-Annotationen (3 Kapitel x Titel+Seite), "
        f"gefunden: {len(link_annots)}"
    )


def test_toc_links_navigate_to_the_correct_section_pages():
    """Jeder TOC-Link muss auf dieselbe Seite zeigen, die als Seitenzahl
    neben dem Kapitel-Titel gedruckt ist — nicht nur irgendeine Seite."""
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(io.BytesIO(pdf))

    toc_page = reader.pages[2]
    annots = toc_page.get("/Annots") or []
    link_annots = [a for a in annots if a.get_object().get("/Subtype") == "/Link"]

    target_pages: set[int] = set()
    for annot in link_annots:
        dest = annot.get_object().get("/Dest")
        target_ref = dest[0]
        page_num = None
        for idx, page in enumerate(reader.pages):
            if (
                page.indirect_reference is not None
                and page.indirect_reference.idnum == target_ref.idnum
            ):
                page_num = idx + 1
                break
        assert page_num is not None, "Link-Ziel zeigt auf keine bekannte Seite"
        target_pages.add(page_num)

    # Ausgangslage(4) / Positionen(5) / Pruefpunkte(6) aus _make_minimal_payload
    assert target_pages == {4, 5, 6}
