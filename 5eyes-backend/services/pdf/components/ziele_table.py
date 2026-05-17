"""Sprint 11: Anlageziele & Zielerreichung — Tabelle mit Color-Coded Bars.

Frontend-Vorlage:
    Rang | Ziel | Zielerreichung (Bar+Score) | Zielgroesse
    Color: >=70 gruen, 45-69 orange, <45 rot
"""
from __future__ import annotations

from typing import Iterable, Mapping

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Rect

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
    goal_color,
    make_paragraph_styles,
)


def make_ziele_section(goals: Iterable[Mapping]) -> list:
    """Returns Flowables: Section-Title + Tabelle."""
    goals_list = list(goals or [])
    if not goals_list:
        return []

    flowables = [_section_title("Anlageziele & Zielerreichung")]

    rows = [["Rang", "Ziel", "Zielerreichung", "Zielgrösse"]]
    for g in goals_list:
        rank = int(g.get("rank", 0) or 0)
        label = str(g.get("label", "—") or "—")
        score = float(g.get("achievement_score", 0) or 0)
        target_text = str(g.get("target_text", "") or "")

        # Bar mit Score
        bar_drawing = _make_goal_bar(score)
        score_text = Paragraph(
            f'<font name="{FONT_BOLD}">{int(score)}/100</font>',
            _para_compact(),
        )
        ze_cell = Table(
            [[bar_drawing], [score_text]],
            colWidths=[None],
        )
        ze_cell.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))

        rows.append([
            Paragraph(f'<b>RANG {rank}</b>', _para_compact()),
            Paragraph(_esc(label), _para_compact()),
            ze_cell,
            Paragraph(_esc(target_text), _para_compact()),
        ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    col_widths = [
        table_width * 0.10,
        table_width * 0.35,
        table_width * 0.30,
        table_width * 0.25,
    ]
    table = Table(rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
        ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE_TABLE),
        ("FONTNAME", (0, 1), (-1, -1), FONT_DEFAULT),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_TEXT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    flowables.append(table)
    return flowables


def _make_goal_bar(score: float) -> Drawing:
    bar_width = 50 * mm
    bar_height = 4 * mm
    drawing = Drawing(bar_width, bar_height)
    drawing.add(Rect(0, 0, bar_width, bar_height,
                     fillColor=colors.HexColor("#e2e8f0"),
                     strokeColor=None))
    pct = max(0.0, min(1.0, score / 100.0))
    if pct > 0:
        drawing.add(Rect(0, 0, bar_width * pct, bar_height,
                         fillColor=goal_color(score),
                         strokeColor=None))
    return drawing


def _section_title(text: str):
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        f'<font color="#475569" size="9"><b>{_esc(text).upper()}</b></font>',
        style,
    )


def _para_compact():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "GoalCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=11,
        spaceAfter=0,
    )
