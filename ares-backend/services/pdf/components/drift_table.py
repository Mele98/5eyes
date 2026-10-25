"""Sprint U-P16: Bucket-Drift-Tabelle für Depot-Check-PDF.

IST vs SOLL mit Toleranzband + Status-Badge.
"""
from __future__ import annotations

from typing import Mapping

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
    asset_class_color,
)

BUCKET_ORDER = ("equities", "bonds", "real_estate", "alternatives", "liquidity")


def make_drift_table(buckets: Mapping[str, Mapping]) -> Table:
    """Returns Table mit Bucket | IST | SOLL | Drift | Band | Status."""
    rows = [["Bucket", "IST", "SOLL", "Drift", "Toleranzband", "Status"]]
    for bucket in BUCKET_ORDER:
        b = buckets.get(bucket) or {}
        ist_bps = int(b.get("ist_bps", 0) or 0)
        soll_bps = int(b.get("soll_bps", 0) or 0)
        drift_bps = int(b.get("drift_bps", 0) or 0)
        band_min = int(b.get("band_min_bps", 0) or 0)
        band_max = int(b.get("band_max_bps", 0) or 0)
        in_band = b.get("in_band")
        label = str(b.get("label", bucket))

        if in_band is True:
            status = '<font color="#166534"><b>im Band</b></font>'
        elif in_band is False:
            status = '<font color="#7f1d1d"><b>ausserhalb</b></font>'
        else:
            status = '<font color="#94a3b8">—</font>'

        band_text = f"{band_min/100:.1f}% – {band_max/100:.1f}%" if (band_min or band_max) else "—"
        drift_color = "#7f1d1d" if abs(drift_bps) > 200 else "#475569"
        drift_text = f'{drift_bps/100:+.1f}%'

        color_hex = asset_class_color(bucket).hexval()[2:]

        rows.append([
            Paragraph(
                f'<font color="#{color_hex}" size="11">●</font> '
                f'<font name="{FONT_BOLD}">{_esc(label)}</font>',
                _para_compact(),
            ),
            Paragraph(f'<para align="right"><b>{ist_bps/100:.1f}%</b></para>', _para_compact()),
            Paragraph(f'<para align="right">{soll_bps/100:.1f}%</para>', _para_compact()),
            Paragraph(
                f'<para align="right"><font color="{drift_color}">{drift_text}</font></para>',
                _para_compact(),
            ),
            Paragraph(
                f'<font size="9.5" color="#475569">{_esc(band_text)}</font>',
                _para_compact(),
            ),
            Paragraph(f'<para align="center">{status}</para>', _para_compact()),
        ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    table = Table(
        rows,
        colWidths=[
            table_width * 0.25,
            table_width * 0.10,
            table_width * 0.10,
            table_width * 0.10,
            table_width * 0.25,
            table_width * 0.20,
        ],
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
        ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE_TABLE),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _para_compact():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "DriftCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=11,
        spaceAfter=0,
    )
