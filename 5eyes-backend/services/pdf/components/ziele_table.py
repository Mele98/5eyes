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


def _achievement_bars(score: float) -> str:
    """Score 0-100 → 8-stufige ▰▱-Balken-Visualisierung wie Vorlage.

    Skala (Vorlage): jeder Balken = 12.5%, Color per goal_color helper.
    """
    n_filled = max(0, min(8, int(round(score / 12.5))))
    filled = "▰" * n_filled
    empty = "▱" * (8 - n_filled)
    return filled + empty


def make_ziele_section(goals: Iterable[Mapping], *, base_currency: str = "CHF") -> list:
    """Returns Flowables: Section-Title + Tabelle mit Balken + Fehlbetrag."""
    goals_list = list(goals or [])
    if not goals_list:
        return []

    flowables = [_section_title("Anlageziele & Zielerreichung")]

    rows = [["Rang", "Ziel", "Zielerreichung", f"Fehlbetrag ({base_currency})", "Zielgrösse"]]
    for g in goals_list:
        rank = int(g.get("rank", 0) or 0)
        label = str(g.get("label", "—") or "—")
        score = float(g.get("achievement_score", 0) or 0)
        target_text = str(g.get("target_text", "") or "")
        shortfall_rappen = int(g.get("shortfall_rappen", 0) or 0)

        # Sprint 14 Phase 3: filled-Balken in goal_color, empty-Balken grau
        color_hex = goal_color(score).hexval()[2:]
        n_filled = max(0, min(8, int(round(score / 12.5))))
        filled = "▰" * n_filled
        empty = "▱" * (8 - n_filled)
        achievement_cell = Paragraph(
            f'<font color="#{color_hex}" size="12"><b>{filled}</b></font>'
            f'<font color="#cbd5e1" size="12">{empty}</font>'
            f'<br/><font color="#64748b" size="7">{int(score)}/100</font>',
            _para_compact(),
        )

        # Fehlbetrag-Anzeige
        if shortfall_rappen > 0:
            shortfall_text = _format_amount(shortfall_rappen, base_currency)
        else:
            shortfall_text = "—"

        rows.append([
            Paragraph(f'<b>RANG {rank}</b>', _para_compact()),
            Paragraph(_esc(label), _para_compact()),
            achievement_cell,
            shortfall_text,
            Paragraph(_esc(target_text), _para_compact()),
        ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    col_widths = [
        table_width * 0.08,
        table_width * 0.30,
        table_width * 0.27,
        table_width * 0.15,
        table_width * 0.20,
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


def _format_amount(rappen: int, currency: str = "CHF") -> str:
    # Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): rappen ist bereits in
    # mandate.base_currency (siehe portfolio_engine._load_allocation_inputs).
    # Kein zweites convert_rappen("CHF"->currency) -- sonst doppelte FX-Konvertierung.
    try:
        value = rappen / 100.0
        return f"{currency} {value:,.0f}".replace(",", "'")
    except Exception:
        return f"CHF {rappen/100.0:,.0f}".replace(",", "'")


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
