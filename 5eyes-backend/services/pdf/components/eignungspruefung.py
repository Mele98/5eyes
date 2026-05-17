"""Sprint 11: Eignungspruefung-Tabelle (Kenntnisse Finanzdienstleistungen
+ Finanzinstrumente). FIDLEG W305-konform.
"""
from __future__ import annotations

from typing import Mapping

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from services.pdf.components.header import _esc
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TABLE_HEADER_BG,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_TABLE,
    FONT_SIZE_TABLE_HEADER,
    PAGE_SIZE,
    make_paragraph_styles,
)


def make_eignungspruefung_section(
    services_knowledge: Mapping[str, bool],
    instruments_knowledge: Mapping[str, bool],
) -> list:
    """Returns Flowables: Section-Title + 2-Spalten-Tabelle.

    Frontend-Wording: "Kenntnisse & Erfahrungen (Eignungspruefung)"
    Spalten: 'Finanzdienstleistungen' und 'Finanzinstrumente'.
    """
    if not services_knowledge and not instruments_knowledge:
        return []

    styles = make_paragraph_styles()
    flowables = [_section_title("Kenntnisse & Erfahrungen (Eignungsprüfung)")]

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm

    # Pro Spalte eine Sub-Tabelle, dann nebeneinander
    services_table = _make_knowledge_subtable(services_knowledge, "Finanzdienstleistungen")
    instruments_table = _make_knowledge_subtable(instruments_knowledge, "Finanzinstrumente")

    composite = Table(
        [[services_table, instruments_table]],
        colWidths=[table_width / 2, table_width / 2],
    )
    composite.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    flowables.append(composite)
    return flowables


def _make_knowledge_subtable(items: Mapping[str, bool], header_label: str) -> Table:
    """Sub-Tabelle mit Label + Bool-Marker (Ja/Nein)."""
    rows = [[header_label, "Kenntnis"]]
    if not items:
        rows.append(["Keine Angaben", "—"])
    else:
        for key, value in items.items():
            rows.append([_esc(str(key)), "Ja" if value else "Nein"])

    table = Table(rows, colWidths=[None, 22 * mm])
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
        ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE_TABLE),
        ("FONTNAME", (0, 1), (-1, -1), FONT_DEFAULT),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_TEXT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, COLOR_BORDER),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    table.setStyle(TableStyle(style_cmds))
    return table


def _section_title(text: str):
    """Helper: kleiner uppercase Section-Title wie Frontend sl-section-title."""
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        f'<font color="#475569" size="9"><b>{_esc(text).upper()}</b></font>',
        style,
    )
