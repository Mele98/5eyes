"""SAA-Tortendiagramm via ReportLab-graphics."""
from __future__ import annotations

from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm

from services.pdf.styles import (
    BUCKET_COLORS,
    BUCKET_LABELS_DE,
    FONT_DEFAULT,
    FONT_SIZE_SMALL,
)


def make_saa_pie_chart(
    allocation_bps: dict[str, int],
    width_mm: float = 70.0,
    height_mm: float = 70.0,
) -> Drawing:
    """SAA-Torte mit Legende. Returns ReportLab Drawing."""
    width = width_mm * mm
    height = height_mm * mm
    drawing = Drawing(width, height)

    # Filter: nur Buckets > 0
    items = [
        (BUCKET_LABELS_DE.get(b, b), int(allocation_bps.get(b, 0) or 0), BUCKET_COLORS.get(b))
        for b in ("equities", "bonds", "real_estate", "alternatives", "liquidity")
        if int(allocation_bps.get(b, 0) or 0) > 0
    ]
    if not items:
        return drawing  # leer wenn keine Daten

    labels = [it[0] for it in items]
    values = [it[1] for it in items]
    colors_list = [it[2] for it in items]

    pie = Pie()
    pie.x = 10
    pie.y = height * 0.25
    pie.width = height * 0.55
    pie.height = height * 0.55
    pie.data = values
    pie.labels = None  # Labels via Legende, nicht im Chart selbst
    pie.slices.strokeWidth = 0.5
    for i, color in enumerate(colors_list):
        if color is not None:
            pie.slices[i].fillColor = color
    drawing.add(pie)

    # Legende rechts
    legend = Legend()
    legend.x = width * 0.55
    legend.y = height * 0.6
    legend.alignment = "right"
    legend.fontName = FONT_DEFAULT
    legend.fontSize = FONT_SIZE_SMALL
    legend.colorNamePairs = [
        (colors_list[i] if colors_list[i] else None, f"{labels[i]} ({values[i]/100:.1f}%)")
        for i in range(len(items))
    ]
    legend.columnMaximum = len(items)
    legend.yGap = 4
    legend.deltay = 12
    drawing.add(legend)

    return drawing
