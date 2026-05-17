"""SAA-Tabelle Komponente."""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Table, TableStyle

from services.pdf.styles import (
    BUCKET_COLORS,
    BUCKET_LABELS_DE,
    COLOR_BORDER,
    COLOR_TABLE_ALT_ROW,
    COLOR_TABLE_HEADER_BG,
    COLOR_TEXT,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_BODY,
)


def make_saa_table(allocation_bps: dict[str, int]) -> Table:
    """Erzeugt SAA-Tabelle aus Bucket→bps Dict.

    Spalten: Asset-Klasse, Anteil (%), Farb-Indikator
    """
    header = ["Asset-Klasse", "Anteil"]
    rows: list[list] = [header]

    for bucket in ("equities", "bonds", "real_estate", "alternatives", "liquidity"):
        bps = int(allocation_bps.get(bucket, 0) or 0)
        if bps == 0:
            continue
        pct = bps / 100.0
        rows.append([BUCKET_LABELS_DE.get(bucket, bucket), f"{pct:.1f} %"])

    # Summen-Zeile
    total_bps = sum(int(allocation_bps.get(b, 0) or 0) for b in BUCKET_LABELS_DE)
    rows.append(["Total", f"{total_bps / 100.0:.1f} %"])

    table = Table(rows, colWidths=[80 * mm, 30 * mm])
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), FONT_SIZE_BODY),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, -1), COLOR_TEXT),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, COLOR_BORDER),
        ("LINEABOVE", (0, -1), (-1, -1), 0.75, COLOR_BORDER),
        ("FONTNAME", (0, -1), (-1, -1), FONT_BOLD),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    # Alternating Row-Color
    for row_idx in range(1, len(rows) - 1):
        if row_idx % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, row_idx), (-1, row_idx), COLOR_TABLE_ALT_ROW))
    table.setStyle(TableStyle(style_cmds))
    return table
