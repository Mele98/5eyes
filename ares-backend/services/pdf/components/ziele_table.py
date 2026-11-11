"""Sprint 11: Anlageziele & Zielerreichung — Tabelle mit Color-Coded Bars.

Frontend-Vorlage:
    Rang | Ziel | Zielerreichung (Bar+Score) | Zielgroesse
    Color: >=70 gruen, 45-69 orange, <45 rot
"""
from __future__ import annotations

import logging
import math
from typing import Iterable, Mapping

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Rect

from services.pdf.components.header import _esc
from core.presentation_rounding import format_amount_minor
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


logger = logging.getLogger(__name__)

ACHIEVEMENT_SEGMENTS = 8
# N-877-08: nur Rundungsartefakte um die Skalengrenzen werden geklemmt; alles
# darueber hinaus ist ein Datenfehler und wird nicht als 0 bzw. 100 gezeigt.
ACHIEVEMENT_ROUNDING_TOLERANCE = 0.5


def _half_up(value: float) -> int:
    """Kaufmaennisch runden (0.5 -> aufwaerts), nicht Pythons Banker's Rounding."""
    return int(math.floor(value + 0.5))


def normalize_achievement_score(score) -> int | None:
    """N-877-06/08: Zielerreichung als ganze Zahl 0..100 fuer Balken UND Label.

    None, NaN, unendlich oder nicht numerisch -> None ("nicht berechenbar",
    kein Balken). Werte ausserhalb [-0.5, 100.5] sind ein Datenfehler ->
    ebenfalls None plus Warnung im Log (ohne Kundendaten), statt still auf
    0/100 zu klemmen. Innerhalb der Toleranz kaufmaennisch gerundet
    (99.6 -> 100, 100.4 -> 100, 6.25 -> 6); Segmente und Beschriftung werden
    beide aus diesem einen Wert abgeleitet.
    """
    if score is None or isinstance(score, bool):
        return None
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if value < -ACHIEVEMENT_ROUNDING_TOLERANCE or value > 100 + ACHIEVEMENT_ROUNDING_TOLERANCE:
        logger.warning(
            "Zielerreichung ausserhalb 0..100 (%s): als 'nicht berechenbar' dargestellt",
            "ueber 100" if value > 100 else "unter 0",
        )
        return None
    return _half_up(min(100.0, max(0.0, value)))


def _achievement_segments(score_pct: int) -> int:
    """Gerundeter Score 0..100 -> gefuellte Segmente (je 12.5 %), half-up."""
    return max(0, min(ACHIEVEMENT_SEGMENTS, _half_up(score_pct / 12.5)))


def _make_achievement_segments(score_pct: int) -> Drawing:
    """N-877-01: Zielerreichung als gezeichnete 8-Segment-Leiste statt der
    Blockzeichen U+25B0/U+25B1 (in keinem eingebetteten Font enthalten).

    Barrierearm: gefuellte Segmente sind farbig gefuellt, leere nur weiss mit
    grauer Kontur -- der Fuellgrad ist auch ohne Farbwahrnehmung ablesbar;
    die Zahl ``NN/100`` steht zusaetzlich darunter.
    """
    seg_w, seg_h, gap = 4.5 * mm, 2.6 * mm, 0.8 * mm
    width = ACHIEVEMENT_SEGMENTS * seg_w + (ACHIEVEMENT_SEGMENTS - 1) * gap
    drawing = Drawing(width, seg_h + 1)
    filled = _achievement_segments(score_pct)
    fill = goal_color(score_pct)
    for i in range(ACHIEVEMENT_SEGMENTS):
        is_filled = i < filled
        drawing.add(Rect(
            i * (seg_w + gap), 0.5, seg_w, seg_h,
            fillColor=fill if is_filled else colors.white,
            strokeColor=fill if is_filled else colors.HexColor("#94a3b8"),
            strokeWidth=0.6,
        ))
    return drawing


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
        score_pct = normalize_achievement_score(g.get("achievement_score"))
        target_text = str(g.get("target_text", "") or "")
        shortfall_rappen = int(g.get("shortfall_rappen", 0) or 0)

        # Sprint 14 Phase 3 / N-877-01: gezeichnete Segmente in goal_color,
        # leere Segmente als Kontur, Score als Zahl darunter.
        if score_pct is None:
            achievement_cell = Paragraph(
                '<font color="#64748b" size="7">nicht berechenbar</font>', _para_compact())
        else:
            achievement_cell = [
                _make_achievement_segments(score_pct),
                Paragraph(f'<font color="#64748b" size="7">{score_pct}/100</font>', _para_compact()),
            ]

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
    return format_amount_minor(rappen, currency or "CHF")


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
