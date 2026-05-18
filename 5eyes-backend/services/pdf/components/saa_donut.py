"""Sprint 13: Asset-Allokation Donut-Chart + Sub-Klassen-Legende fuer PDF.

Repliziert das Frontend sl-donut + sl-pref-grid Layout. Donut wird via
ReportLab-graphics.Pie gezeichnet, Legende als kompakte Tabelle daneben.

Sub-Klassen werden aus den Recommendation-Positions gewonnen (jedes
Produkt hat asset_class + sub_asset_class). Beispiel-Output:

    Aktien · 40%
      • Equity CH         15%
      • Equity World      25%
    Obligationen · 30%
      • Bonds CHF IG      20%
      • Bonds Hedged      10%
"""
from __future__ import annotations

from typing import Iterable, Mapping

from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, String, Rect
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from services.pdf.components.header import _esc
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_SMALL,
    FONT_SIZE_TABLE,
    asset_class_color,
    asset_class_label,
)

BUCKET_ORDER = ("equities", "bonds", "real_estate", "alternatives", "liquidity")


def make_saa_donut_with_legend(
    allocation_bps: Mapping[str, int],
    *,
    products: Iterable[Mapping] | None = None,
    diameter_mm: float = 50.0,
):
    """Returns ReportLab-Flowable: Table mit Donut-Chart links + Legende rechts.

    allocation_bps: {'equities': 4000, ...}
    products: optionale Position-Liste fuer Sub-Klassen-Aufschluesselung
              Jedes dict braucht: asset_class, sub_asset_class, target_weight_bps
    """
    donut = _make_donut_drawing(allocation_bps, diameter_mm)
    legend = _make_class_legend(allocation_bps, products or [])

    composite = Table(
        [[donut, legend]],
        colWidths=[diameter_mm * mm + 5 * mm, None],
    )
    composite.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return composite


def _make_donut_drawing(allocation_bps: Mapping[str, int], diameter_mm: float) -> Drawing:
    """Donut-Chart (Pie mit Loch in der Mitte)."""
    size = diameter_mm * mm
    drawing = Drawing(size, size)

    # Werte vorbereiten
    items = [(b, int(allocation_bps.get(b, 0) or 0)) for b in BUCKET_ORDER]
    items = [(b, v) for b, v in items if v > 0]
    if not items:
        # Leer-State: nur Rahmen + Hinweis
        drawing.add(Rect(
            5, 5, size - 10, size - 10,
            fillColor=None, strokeColor=colors.HexColor("#e2e8f0"),
            strokeWidth=0.8,
        ))
        drawing.add(String(
            size / 2, size / 2 - 4, "Keine Daten",
            fontSize=8, fontName=FONT_DEFAULT, textAnchor="middle",
            fillColor=colors.HexColor("#94a3b8"),
        ))
        return drawing

    values = [v for _, v in items]
    palette = [asset_class_color(b) for b, _ in items]

    pie = Pie()
    margin = 6
    pie.x = margin
    pie.y = margin
    pie.width = size - 2 * margin
    pie.height = size - 2 * margin
    pie.data = values
    pie.labels = None
    pie.slices.strokeColor = colors.white
    pie.slices.strokeWidth = 1.5
    for i, c in enumerate(palette):
        pie.slices[i].fillColor = c
    pie.innerRadiusFraction = 0.55  # Donut-Loch
    drawing.add(pie)

    # Total-Label in der Mitte
    total_pct = sum(values) / 100.0
    drawing.add(String(
        size / 2, size / 2 + 1, f"{total_pct:.0f}%",
        fontSize=11, fontName=FONT_BOLD, textAnchor="middle",
        fillColor=colors.HexColor("#0f172a"),
    ))
    drawing.add(String(
        size / 2, size / 2 - 9, "Soll-Allokation",
        fontSize=5.5, fontName=FONT_DEFAULT, textAnchor="middle",
        fillColor=colors.HexColor("#64748b"),
    ))
    return drawing


def _make_class_legend(allocation_bps: Mapping[str, int], products: Iterable[Mapping]) -> Table:
    """Kompakte Hierarchie-Liste: Bucket-Farbpunkt + Name + Anteil
    + ggf. Sub-Klassen-Aufschluesselung."""
    products_list = list(products or [])

    # Sub-Klassen-Aggregation pro Bucket
    sub_by_bucket: dict[str, dict[str, int]] = {}
    for p in products_list:
        ac = str(p.get("asset_class", "") or "").lower()
        sub = str(p.get("sub_asset_class", "") or "")
        weight = int(p.get("target_weight_bps", 0) or 0)
        if not ac or not sub or weight == 0:
            continue
        sub_by_bucket.setdefault(ac, {})
        sub_by_bucket[ac][sub] = sub_by_bucket[ac].get(sub, 0) + weight

    rows = []
    for bucket in BUCKET_ORDER:
        bps = int(allocation_bps.get(bucket, 0) or 0)
        if bps == 0:
            continue
        color_hex = asset_class_color(bucket).hexval()[2:]
        label = asset_class_label(bucket)
        # Bucket-Zeile mit Farb-Dot
        rows.append([
            Paragraph(
                f'<font color="#{color_hex}" size="11">●</font> '
                f'<font name="{FONT_BOLD}" size="{FONT_SIZE_TABLE}">{_esc(label)}</font>',
                _para_compact(),
            ),
            Paragraph(
                f'<para align="right"><font name="{FONT_BOLD}" size="{FONT_SIZE_TABLE}">'
                f'{bps/100:.1f}%</font></para>',
                _para_compact(),
            ),
        ])
        # Sub-Klassen-Zeilen (eingerueckt)
        subs = sub_by_bucket.get(bucket, {})
        for sub, sub_bps in sorted(subs.items(), key=lambda kv: -kv[1]):
            rows.append([
                Paragraph(
                    f'<font color="#94a3b8" size="{FONT_SIZE_SMALL}">  ┗ {_esc(sub)}</font>',
                    _para_compact(),
                ),
                Paragraph(
                    f'<para align="right"><font color="#64748b" size="{FONT_SIZE_SMALL}">'
                    f'{sub_bps/100:.1f}%</font></para>',
                    _para_compact(),
                ),
            ])

    if not rows:
        rows = [[
            Paragraph(
                f'<font color="#94a3b8" size="{FONT_SIZE_SMALL}"><i>Noch keine Allokation berechnet.</i></font>',
                _para_compact(),
            ),
            "",
        ]]

    legend = Table(rows, colWidths=[None, 22 * mm])
    legend.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]))
    return legend


def _para_compact():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "DonutLegendCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=11,
        spaceAfter=0,
    )
