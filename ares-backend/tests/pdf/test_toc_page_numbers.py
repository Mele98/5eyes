"""Sprint U-13 (2026-06-06): Tests fuer Estimated-Page-Numbers im TOC."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from reportlab.platypus import Table

from services.pdf.documents.advisory_report import _build_toc_flowables


def _styles() -> dict:
    from services.pdf.components.advisory_palette import make_advisory_styles
    return make_advisory_styles()


def _sample_toc() -> dict:
    return {
        "kapitel": [
            {"nr": 1, "title": "Cover"},
            {"nr": 2, "title": "Disclaimer"},
            {"nr": 3, "title": "Inhaltsverzeichnis"},
            {"nr": 4, "title": "Ausgangslage"},
            {"nr": 5, "title": "Positionen"},
        ],
    }


def _page_numbers_for(toc: dict) -> dict:
    """Two-Pass-Collector liefert {title: page}; hier deterministisch nachgebaut."""
    return {
        str(k["title"]): i
        for i, k in enumerate(toc.get("kapitel") or [], start=1)
    }


def test_toc_table_has_4_columns():
    # U-13 Two-Pass: TOC hat 4 Spalten (Nr, Titel, Dot-Leader, Seitenzahl).
    flowables = _build_toc_flowables(_sample_toc(), _styles())
    tables = [f for f in flowables if isinstance(f, Table)]
    # _hr() ist auch eine Table (1-zeilig); echte TOC-Tabelle hat >=1 Kapitel-Row + Spalten >=3
    main_table = next(t for t in tables if t._cellvalues and len(t._cellvalues[0]) >= 3)
    for row in main_table._cellvalues:
        assert len(row) == 4, f"TOC muss 4 Spalten haben, gefunden {len(row)}"


def test_toc_includes_page_numbers():
    # U-13: echte Seitenzahlen aus dem Two-Pass-Collector in der letzten Spalte (Index 3).
    toc = _sample_toc()
    flowables = _build_toc_flowables(
        toc, _styles(), page_numbers_by_title=_page_numbers_for(toc)
    )
    tables = [f for f in flowables if isinstance(f, Table)]
    # _hr() ist auch eine Table (1-zeilig); echte TOC-Tabelle hat >=1 Kapitel-Row + Spalten >=3
    main_table = next(t for t in tables if t._cellvalues and len(t._cellvalues[0]) >= 3)
    # 4. Spalte (Index 3) traegt die Seitenzahl als reine Zahl.
    for row in main_table._cellvalues:
        page_cell_text = getattr(row[3], "text", "")
        assert page_cell_text.strip().isdigit(), (
            f"Spalte 4 muss eine Seitenzahl tragen: {page_cell_text!r}"
        )


def test_toc_page_numbers_increase_monotonically():
    """Echte Seitenzahlen muessen monoton steigen."""
    toc = _sample_toc()
    flowables = _build_toc_flowables(
        toc, _styles(), page_numbers_by_title=_page_numbers_for(toc)
    )
    tables = [f for f in flowables if isinstance(f, Table)]
    # _hr() ist auch eine Table (1-zeilig); echte TOC-Tabelle hat >=1 Kapitel-Row + Spalten >=3
    main_table = next(t for t in tables if t._cellvalues and len(t._cellvalues[0]) >= 3)
    pages = []
    for row in main_table._cellvalues:
        page_cell_text = getattr(row[3], "text", "").strip()
        if page_cell_text.isdigit():
            pages.append(int(page_cell_text))
    assert len(pages) == len(toc["kapitel"]), f"Nicht alle Seiten gefunden: {pages}"
    assert pages == sorted(pages), f"Pages nicht monoton: {pages}"


def test_toc_page_numbers_missing_renders_empty():
    """Ohne Collector-Daten bleibt die Seitenspalte leer (kein Estimate-Fallback)."""
    flowables = _build_toc_flowables(_sample_toc(), _styles())
    tables = [f for f in flowables if isinstance(f, Table)]
    main_table = next(t for t in tables if t._cellvalues and len(t._cellvalues[0]) >= 3)
    for row in main_table._cellvalues:
        page_cell_text = getattr(row[3], "text", "")
        assert page_cell_text.strip() == "", (
            f"Ohne Collector darf keine Seitenzahl stehen: {page_cell_text!r}"
        )


def test_toc_empty_kapitel_no_crash():
    flowables = _build_toc_flowables({"kapitel": []}, _styles())
    # 1. Kicker 2. H1 3. Spacer 4. _hr 5. Spacer 6. 'Keine Kapitel'-Paragraph
    text = " | ".join(getattr(f, "text", "") for f in flowables)
    assert "Keine Kapitel" in text


def test_toc_all_kapitel_get_collected_page():
    """Bei 15 Kapiteln: alle bekommen ihre echte Collector-Seitenzahl."""
    toc = {"kapitel": [{"nr": i, "title": f"S{i}"} for i in range(1, 16)]}
    flowables = _build_toc_flowables(
        toc, _styles(), page_numbers_by_title=_page_numbers_for(toc)
    )
    tables = [f for f in flowables if isinstance(f, Table)]
    # _hr() ist auch eine Table (1-zeilig); echte TOC-Tabelle hat >=1 Kapitel-Row + Spalten >=3
    main_table = next(t for t in tables if t._cellvalues and len(t._cellvalues[0]) >= 3)
    pages_found = 0
    for row in main_table._cellvalues:
        text = getattr(row[3], "text", "").strip()
        if text.isdigit():
            pages_found += 1
    assert pages_found == 15, f"Expected 15 page numbers, found {pages_found}"


def test_first_section_page_starts_at_1():
    """Cover/Section 1 = Page 1 (aus dem Collector)."""
    toc = _sample_toc()
    flowables = _build_toc_flowables(
        toc, _styles(), page_numbers_by_title=_page_numbers_for(toc)
    )
    tables = [f for f in flowables if isinstance(f, Table)]
    # _hr() ist auch eine Table (1-zeilig); echte TOC-Tabelle hat >=1 Kapitel-Row + Spalten >=3
    main_table = next(t for t in tables if t._cellvalues and len(t._cellvalues[0]) >= 3)
    first_row = main_table._cellvalues[0]
    text = getattr(first_row[3], "text", "").strip()
    assert text.isdigit()
    assert int(text) == 1


def test_source_documents_u_13_marker():
    src = (
        BACKEND_ROOT / "services" / "pdf" / "documents" / "advisory_report.py"
    ).read_text(encoding="utf-8")
    assert "U-13" in src
    assert "Estimated-Page-Numbers" in src or "Two-Pass" in src
