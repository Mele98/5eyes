"""Advisory-Report table of contents with real page numbers.

U-13: ReportLab renders sequentially, so TOC page numbers are collected in
Pass 1 through invisible section anchors and rendered in Pass 2.
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
) -> Table:
    """Build a TOC table with optional page numbers and dot leaders."""
    rows = _toc_rows(chapters, page_numbers_by_title)
    nr_col = 14 * mm
    page_col = 10 * mm
    dots_col = 28 * mm
    title_col = inner_width - nr_col - dots_col - page_col

    table_rows = []
    for row in rows:
        table_rows.append([
            Paragraph(
                (
                    f"<font face='{FONT_SANS}' size='{FONT_SIZE_MICRO}' "
                    f"color='#6F7A8A'>{escape(row['nr'])}</font>"
                ),
                styles["caption"],
            ),
            Paragraph(
                escape(row["title"]),
                _paragraph_style(styles["body"], color=COLOR_INK),
            ),
            Paragraph(
                escape(row["leader"]),
                _paragraph_style(
                    styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_MONO,
                ),
            ),
            Paragraph(
                escape(row["page"]),
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
