"""Sprint U-P16 (2026-05-21): Generischer Exposure-Donut für Depot-Check.

Wiederverwendbar für Country-, Sector-, Currency-Exposure. Donut + Legende
in einer Tabelle, ähnlich saa_donut aber asset-class-agnostisch.
"""
from __future__ import annotations

from typing import Mapping

from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from services.pdf.components.header import _esc
from services.pdf.styles import (
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_SMALL,
    FONT_SIZE_TABLE,
)

# Default-Palette (10 Farben für maximal 10 Slices)
_PALETTE = [
    "#1e4b8f", "#78601a", "#166534", "#2c5080", "#4a6080",
    "#92400e", "#7f1d1d", "#365314", "#1e3a8a", "#581c87",
]


def make_exposure_donut(
    exposure_bps: Mapping[str, int],
    *,
    title: str,
    hhi: int | None = None,
    diameter_mm: float = 42.0,
    max_legend_entries: int = 10,
) -> Table:
    """Returns ReportLab Table mit Donut links + Legende rechts."""
    entries = [(k, int(v or 0)) for k, v in (exposure_bps or {}).items() if int(v or 0) > 0]
    entries.sort(key=lambda kv: -kv[1])

    donut = _make_donut_drawing(entries, diameter_mm)
    legend = _make_legend(entries, max_legend_entries)

    title_para = Paragraph(
        f'<font name="{FONT_BOLD}" size="9" color="#64748b">{_esc(title).upper()}</font>',
        _para_compact(),
    )
    hhi_text = ""
    if hhi is not None:
        if hhi > 5000:
            hhi_text = f'<font color="#7f1d1d" size="7.5"><b>HHI {hhi}</b> · hoch</font>'
        elif hhi > 2500:
            hhi_text = f'<font color="#92400e" size="7.5"><b>HHI {hhi}</b> · mittel</font>'
        else:
            hhi_text = f'<font color="#166534" size="7.5"><b>HHI {hhi}</b> · gering</font>'
    hhi_para = Paragraph(hhi_text, _para_compact()) if hhi_text else Paragraph("", _para_compact())

    composite = Table(
        [
            [title_para, hhi_para],
            [donut, legend],
        ],
        colWidths=[diameter_mm * mm + 3 * mm, None],
    )
    composite.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return composite


def _make_donut_drawing(entries: list[tuple[str, int]], diameter_mm: float) -> Drawing:
    size = diameter_mm * mm
    drawing = Drawing(size, size)

    if not entries:
        drawing.add(Rect(
            5, 5, size - 10, size - 10,
            fillColor=None, strokeColor=colors.HexColor("#e2e8f0"), strokeWidth=0.8,
        ))
        drawing.add(String(
            size / 2, size / 2 - 4, "Keine Daten",
            fontSize=7, fontName=FONT_DEFAULT, textAnchor="middle",
            fillColor=colors.HexColor("#94a3b8"),
        ))
        return drawing

    # Top-9 + "Andere" wenn mehr als 10
    display = entries[:9]
    rest_sum = sum(v for _, v in entries[9:])
    if rest_sum > 0:
        display = list(display) + [("Andere", rest_sum)]

    values = [v for _, v in display]
    palette = [colors.HexColor(_PALETTE[i % len(_PALETTE)]) for i in range(len(display))]

    pie = Pie()
    margin = 5
    pie.x = margin
    pie.y = margin
    pie.width = size - 2 * margin
    pie.height = size - 2 * margin
    pie.data = values
    pie.labels = None
    pie.slices.strokeColor = colors.white
    pie.slices.strokeWidth = 1.2
    for i, c in enumerate(palette):
        pie.slices[i].fillColor = c
    pie.innerRadiusFraction = 0.55
    drawing.add(pie)

    total_pct = sum(values) / 100.0
    drawing.add(String(
        size / 2, size / 2 + 1, f"{total_pct:.0f}%",
        fontSize=10, fontName=FONT_BOLD, textAnchor="middle",
        fillColor=colors.HexColor("#0f172a"),
    ))
    return drawing


def _make_legend(entries: list[tuple[str, int]], max_entries: int) -> Table:
    if not entries:
        return Table([[Paragraph(
            f'<font color="#94a3b8" size="{FONT_SIZE_SMALL}"><i>Keine Daten</i></font>',
            _para_compact(),
        )]])

    display = entries[:max_entries]
    rows = []
    for idx, (label, bps) in enumerate(display):
        color_hex = _PALETTE[idx % len(_PALETTE)]
        pct = bps / 100.0
        rows.append([
            Paragraph(
                f'<font color="{color_hex}" size="11">●</font> '
                f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_TABLE}">{_esc(label)}</font>',
                _para_compact(),
            ),
            Paragraph(
                f'<para align="right"><font name="{FONT_BOLD}" size="{FONT_SIZE_TABLE}">'
                f'{pct:.1f}%</font></para>',
                _para_compact(),
            ),
        ])
    if len(entries) > max_entries:
        rest_pct = sum(v for _, v in entries[max_entries:]) / 100.0
        rows.append([
            Paragraph(
                f'<font color="#94a3b8" size="{FONT_SIZE_SMALL}"><i>+{len(entries)-max_entries} weitere</i></font>',
                _para_compact(),
            ),
            Paragraph(
                f'<para align="right"><font color="#94a3b8" size="{FONT_SIZE_SMALL}"><i>'
                f'{rest_pct:.1f}%</i></font></para>',
                _para_compact(),
            ),
        ])
    legend = Table(rows, colWidths=[None, 18 * mm])
    legend.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    return legend


def _para_compact():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "ExposureLegend",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=11,
        spaceAfter=0,
    )
