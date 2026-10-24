"""SAA-Tabelle mit Bar-Visualisierung.

Standardfall: Anlageklasse | Soll | Visualisierung | Betrag.
Individuelle Bandbreiten werden nur angezeigt, wenn sie explizit
angefordert werden.
"""
from __future__ import annotations

from typing import Mapping

from reportlab.graphics.shapes import Drawing, Rect
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
    asset_class_color,
    asset_class_label,
    make_paragraph_styles,
)

BUCKET_ORDER = ("equities", "bonds", "real_estate", "alternatives", "liquidity")


def make_saa_bar_table(
    allocation_bps: Mapping[str, int],
    *,
    bucket_bands_bps: Mapping[str, tuple] | None = None,
    bucket_amounts_rappen: Mapping[str, int] | None = None,
    base_currency: str = "CHF",
    advisory_wealth_rappen: int | None = None,
    show_bands: bool = False,
) -> list:
    """Returns Flowables: Section-Title + Allokations-Tabelle."""
    title = "Soll-Allokation & individuelle Bandbreiten" if show_bands else "Soll-Allokation"
    flowables = [_section_title(title)]

    bands = dict(bucket_bands_bps or {})
    amounts = dict(bucket_amounts_rappen or {})

    header = ["Anlageklasse", "Soll", "Visualisierung", f"Betrag ({base_currency})"]
    if show_bands:
        header.insert(3, "Band Min-Max")
    rows = [header]

    total_bps = 0
    total_amount = 0

    for bucket in _ordered_buckets(allocation_bps):
        bps = int(allocation_bps.get(bucket, 0) or 0)
        total_bps += bps
        amt = int(amounts.get(bucket, 0) or 0)
        total_amount += amt
        band = bands.get(bucket, (None, None))
        min_bps = band[0] if band and len(band) > 0 else None
        max_bps = band[1] if band and len(band) > 1 else None

        color_hex = asset_class_color(bucket).hexval()[2:]
        label = asset_class_label(bucket)
        asset_cell = Paragraph(
            f'<font color="#{color_hex}">&#9679;</font> '
            f'<font name="{FONT_DEFAULT}">{_esc(label)}</font>',
            _para_style_table(),
        )
        bar_drawing = _make_bar(bps, max_bps_max=10000, color=asset_class_color(bucket))

        if amt > 0:
            amount_text = _format_amount(amt, base_currency)
        elif advisory_wealth_rappen:
            derived = int(advisory_wealth_rappen * bps / 10000)
            amount_text = _format_amount(derived, base_currency)
        else:
            amount_text = "-"

        row = [asset_cell, f"{bps/100:.1f}%", bar_drawing, amount_text]
        if show_bands:
            if min_bps is not None and max_bps is not None:
                band_text = f"{min_bps/100:.0f}% - {max_bps/100:.0f}%"
            else:
                band_text = "-"
            row.insert(3, band_text)
        rows.append(row)

    if advisory_wealth_rappen and total_amount == 0:
        total_amount = advisory_wealth_rappen
    total_row = [
        Paragraph("<b>Total Beratungsvermoegen</b>", _para_style_table()),
        f"{total_bps/100:.1f}%",
        "",
        _format_amount(total_amount, base_currency) if total_amount > 0 else "-",
    ]
    if show_bands:
        total_row.insert(3, "")
    rows.append(total_row)

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    if show_bands:
        col_widths = [
            table_width * 0.30,
            table_width * 0.10,
            table_width * 0.30,
            table_width * 0.15,
            table_width * 0.15,
        ]
        amount_col = 4
    else:
        col_widths = [
            table_width * 0.34,
            table_width * 0.12,
            table_width * 0.34,
            table_width * 0.20,
        ]
        amount_col = 3

    table = Table(rows, colWidths=col_widths)
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
        ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE_TABLE),
        ("FONTNAME", (0, 1), (-1, -1), FONT_DEFAULT),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_TEXT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEABOVE", (0, -1), (-1, -1), 1.0, COLOR_BORDER),
        ("FONTNAME", (0, -1), (-1, -1), FONT_BOLD),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (amount_col, 0), (amount_col, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    if show_bands:
        style_cmds.append(("ALIGN", (3, 0), (3, -1), "RIGHT"))
    table.setStyle(TableStyle(style_cmds))
    flowables.append(table)
    return flowables


def _ordered_buckets(allocation_bps: Mapping[str, int]) -> list[str]:
    """High-level classes: first by size, then stable bucket order."""
    return sorted(
        [
            bucket for bucket in BUCKET_ORDER
            if int(allocation_bps.get(bucket, 0) or 0) > 0
        ],
        key=lambda bucket: (
            -int(allocation_bps.get(bucket, 0) or 0),
            BUCKET_ORDER.index(bucket),
        ),
    )


def _make_bar(bps: int, max_bps_max: int = 10000, color=None) -> Drawing:
    """Liefert einen schmalen Horizontal-Balken proportional zu bps."""
    bar_width = 50 * mm
    bar_height = 5 * mm
    drawing = Drawing(bar_width, bar_height)
    drawing.add(Rect(
        0,
        1,
        bar_width,
        bar_height - 2,
        fillColor=colors.HexColor("#e2e8f0"),
        strokeColor=None,
    ))
    pct = max(0.0, min(1.0, bps / float(max_bps_max)))
    value_w = bar_width * pct
    if value_w > 0:
        drawing.add(Rect(
            0,
            1,
            value_w,
            bar_height - 2,
            fillColor=color or colors.HexColor("#1e4b8f"),
            strokeColor=None,
        ))
    return drawing


def _format_amount(rappen: int, currency: str = "CHF") -> str:
    """CHF-Format mit Schweizer Tausender-Trenner.

    Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): rappen ist bereits in
    mandate.base_currency (siehe portfolio_engine._load_allocation_inputs).
    Kein zweites convert_rappen("CHF"->currency) -- sonst doppelte FX-Konvertierung.
    """
    try:
        value = rappen / 100.0
        return f"{currency} {value:,.0f}".replace(",", "'")
    except Exception:
        return f"CHF {rappen/100.0:,.0f}".replace(",", "'")


def _section_title(text: str):
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        f'<font color="#475569" size="9"><b>{_esc(text).upper()}</b></font>',
        style,
    )


def _para_style_table():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "SaaTableCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=11,
        spaceAfter=0,
    )
