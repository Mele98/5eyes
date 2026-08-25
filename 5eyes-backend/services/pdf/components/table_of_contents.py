"""Advisory-Report table of contents with real page numbers and links.

U-13: ReportLab renders sequentially, so TOC page numbers are collected in
Pass 1 through invisible section anchors and rendered in Pass 2.

Roadmap #71/#72: the same section anchors also drop a named PDF bookmark
(`canvas.bookmarkPage`) and a PDF-outline/sidebar entry
(`canvas.addOutlineEntry`) at every section start. The TOC table wraps each
row's title/page cells in a ReportLab `<link href="#<section_id>">` tag,
which ReportLab turns into an internal `GoTo` annotation
(`Canvas.linkRect`) pointing at that bookmark — so the printed TOC is
clickable in any PDF viewer, in addition to showing the real page number.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Mapping

from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, Table, TableStyle

from services.pdf.components.advisory_palette import (
    COLOR_INK,
    COLOR_INK_SUBTLE,
    COLOR_RULE,
    FONT_MONO,
    FONT_SANS,
    FONT_SANS_BOLD,
    FONT_SIZE_MICRO,
)

DOT_LEADER = "." * 28


@dataclass(frozen=True)
class TocEntry:
    section_id: str
    title: str
    page_number: int


class TocCollector:
    """Collects the first page on which each top-level section appears."""

    def __init__(self) -> None:
        self._entries: list[TocEntry] = []
        self._seen: set[str] = set()

    @property
    def entries(self) -> tuple[TocEntry, ...]:
        return tuple(self._entries)

    def register(self, section_id: str, title: str, page_number: int) -> None:
        safe_id = str(section_id or "").strip()
        if not safe_id or safe_id in self._seen:
            return
        self._seen.add(safe_id)
        self._entries.append(TocEntry(
            section_id=safe_id,
            title=str(title or "").strip(),
            page_number=int(page_number),
        ))

    def page_numbers_by_title(self) -> dict[str, int]:
        return {entry.title: entry.page_number for entry in self._entries}

    def page_numbers_by_id(self) -> dict[str, int]:
        return {entry.section_id: entry.page_number for entry in self._entries}

    def section_ids_by_title(self) -> dict[str, str]:
        """Title → bookmark key, used by the TOC table to build internal
        hyperlinks that jump to the same anchor used for the page number."""
        return {entry.title: entry.section_id for entry in self._entries}


class TocSectionAnchor(Flowable):
    """Zero-height flowable that records the current page when drawn."""

    def __init__(self, collector: TocCollector | None, section_id: str, title: str) -> None:
        super().__init__()
        self.collector = collector
        self.section_id = section_id
        self.title = title
        self.width = 0
        self.height = 0

    def wrap(self, availWidth, availHeight):  # noqa: N802 - ReportLab API
        return 0, 0

    def draw(self) -> None:
        # Roadmap #71/#72: drop a named bookmark + PDF-outline entry at the
        # start of every section, independent of TOC collection — this is
        # what makes the TOC's `<link href="#section_id">` cells (see
        # `make_toc_table`) resolve to a real destination, and it also
        # gives the reader a native sidebar/outline navigation panel.
        # `getattr` guards keep this safe against minimal canvas doubles in
        # unit tests that only implement `getPageNumber()`.
        bookmark_page = getattr(self.canv, "bookmarkPage", None)
        if bookmark_page is not None:
            bookmark_page(self.section_id)
        add_outline_entry = getattr(self.canv, "addOutlineEntry", None)
        if add_outline_entry is not None:
            add_outline_entry(self.title or self.section_id, self.section_id, level=0, closed=0)

        if self.collector is None:
            return
        self.collector.register(
            self.section_id,
            self.title,
            int(self.canv.getPageNumber()),
        )


def make_toc_table(
    chapters: list[dict],
    styles: dict,
    *,
    inner_width: float,
    page_numbers_by_title: Mapping[str, int] | None = None,
    section_ids_by_title: Mapping[str, str] | None = None,
) -> Table:
    """Build a TOC table with real page numbers, dot leaders, and — when
    `section_ids_by_title` is given — clickable internal links.

    `section_ids_by_title` maps a section title (as collected by
    `TocCollector`) to the bookmark key that `TocSectionAnchor.draw()`
    registered via `canvas.bookmarkPage()` for that section. When present,
    the title/page cells become `<link href="#<section_id>">` so clicking
    the TOC entry jumps to the section in any PDF viewer. Without it (e.g.
    degraded-mode rendering with only estimated titles), rows render as
    plain text — unchanged behaviour.
    """
    rows = _toc_rows(chapters, page_numbers_by_title)
    section_ids = dict(section_ids_by_title or {})
    nr_col = 14 * mm
    page_col = 10 * mm
    dots_col = 28 * mm
    title_col = inner_width - nr_col - dots_col - page_col

    table_rows = []
    for row in rows:
        href = _resolve_section_id(row["title"], section_ids) if section_ids else None
        title_html = escape(row["title"])
        page_html = escape(row["page"])
        if href:
            title_html = f"<link href='#{href}'>{title_html}</link>"
            if page_html:
                page_html = f"<link href='#{href}'>{page_html}</link>"
        table_rows.append([
            Paragraph(
                (
                    f"<font face='{FONT_SANS}' size='{FONT_SIZE_MICRO}' "
                    f"color='#6F7A8A'>{escape(row['nr'])}</font>"
                ),
                styles["caption"],
            ),
            Paragraph(
                title_html,
                _paragraph_style(styles["body"], color=COLOR_INK),
            ),
            Paragraph(
                escape(row["leader"]),
                _paragraph_style(
                    styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_MONO,
                ),
            ),
            Paragraph(
                page_html,
                _paragraph_style(
                    styles["caption"], color=COLOR_INK, font=FONT_SANS_BOLD,
                ),
            ),
        ])

    table = Table(table_rows, colWidths=[nr_col, title_col, dots_col, page_col])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.2, COLOR_RULE),
    ]))
    return table


def resolve_toc_rows(
    chapters: list[dict],
    page_numbers_by_title: Mapping[str, int] | None = None,
) -> list[dict[str, str]]:
    """Pure helper for tests and degraded-mode contracts."""
    return _toc_rows(chapters, page_numbers_by_title)


def _toc_rows(
    chapters: list[dict],
    page_numbers_by_title: Mapping[str, int] | None,
) -> list[dict[str, str]]:
    page_numbers = dict(page_numbers_by_title or {})
    rows: list[dict[str, str]] = []
    for chapter in chapters:
        title = str(chapter.get("title") or "-").strip() or "-"
        page = _resolve_page_number(title, page_numbers)
        rows.append({
            "nr": _format_two_digits(chapter.get("nr")),
            "title": title,
            "leader": DOT_LEADER if page is not None else "",
            "page": str(page) if page is not None else "",
        })
    return rows


def _resolve_page_number(title: str, page_numbers_by_title: Mapping[str, int]) -> int | None:
    if title in page_numbers_by_title:
        return int(page_numbers_by_title[title])
    normalized = _norm(title)
    for collected_title, page in page_numbers_by_title.items():
        collected_norm = _norm(collected_title)
        if collected_norm == normalized:
            return int(page)
        if collected_norm.startswith(normalized) or normalized.startswith(collected_norm):
            return int(page)
    return None


def _resolve_section_id(title: str, section_ids_by_title: Mapping[str, str]) -> str | None:
    """Same fuzzy-matching contract as `_resolve_page_number`, so a TOC row
    links to the exact anchor whose page number it displays."""
    if title in section_ids_by_title:
        return str(section_ids_by_title[title])
    normalized = _norm(title)
    for collected_title, section_id in section_ids_by_title.items():
        collected_norm = _norm(collected_title)
        if collected_norm == normalized:
            return str(section_id)
        if collected_norm.startswith(normalized) or normalized.startswith(collected_norm):
            return str(section_id)
    return None


def _format_two_digits(value: Any) -> str:
    try:
        nr = int(value)
    except (TypeError, ValueError):
        nr = 0
    return f"{nr:02d}" if nr > 0 else "--"


def _norm(value: str) -> str:
    return (
        str(value or "")
        .casefold()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
        .replace("/", " ")
        .replace("-", " ")
        .strip()
    )


def _paragraph_style(
    base,
    *,
    font: str | None = None,
    color=None,
    size: float | None = None,
    leading: float | None = None,
):
    return ParagraphStyle(
        f"{base.name}TocVariant",
        parent=base,
        fontName=font or base.fontName,
        textColor=color or base.textColor,
        fontSize=size or base.fontSize,
        leading=leading or base.leading,
    )
