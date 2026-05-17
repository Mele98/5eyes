"""Sprint 11: SAA-Tabelle mit Bar-Visualisierung (5 Spalten).

Frontend-Vorlage:
    Anlageklasse (Farb-Dot) | Soll % | Visualisierung (Balken) | Band Min-Max | Betrag CHF
    + Total-Zeile am Ende
"""
from __future__ import annotations

from typing import Mapping

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Rect, String

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
) -> list:
    """Returns Flowables: Section-Title + 5-Spalten-Tabelle."""
    flowables = [_section_title("Soll-Allokation & Toleranzbänder")]

    bands = dict(bucket_bands_bps or {})
    amounts = dict(bucket_amounts_rappen or {})

    # Header
    header = [
        "Anlageklasse",
        "Soll",
        "Visualisierung",
        "Band Min–Max",
        f"Betrag ({base_currency})",
    ]
    rows = [header]

    total_bps = 0
    total_amount = 0

    for bucket in BUCKET_ORDER:
        bps = int(allocation_bps.get(bucket, 0) or 0)
        if bps == 0:
            continue
        total_bps += bps
        amt = int(amounts.get(bucket, 0) or 0)
        total_amount += amt
        band = bands.get(bucket, (None, None))
        min_bps = band[0] if band and len(band) > 0 else None
        max_bps = band[1] if band and len(band) > 1 else None

        # Anlageklasse mit Farb-Dot via Paragraph
        color_hex = asset_class_color(bucket).hexval()[2:]  # '0x' prefix abschneiden
        label = asset_class_label(bucket)
        asset_cell = Paragraph(
            f'<font color="#{color_hex}">●</font> '
            f'<font name="{FONT_DEFAULT}">{_esc(label)}</font>',
            _para_style_table(),
        )

        # Bar-Visualisierung
        bar_drawing = _make_bar(bps, max_bps_max=10000, color=asset_class_color(bucket))

        # Band-Spalte
        if min_bps is not None and max_bps is not None:
            band_text = f"{min_bps/100:.0f}% – {max_bps/100:.0f}%"
        else:
            band_text = "—"

        # Betrag-Spalte
        if amt > 0:
            amount_text = _format_amount(amt, base_currency)
        elif advisory_wealth_rappen:
            # ableiten aus advisory_wealth * weight
            derived = int(advisory_wealth_rappen * bps / 10000)
            amount_text = _format_amount(derived, base_currency)
        else:
            amount_text = "—"

        rows.append([
            asset_cell,
            f"{bps/100:.1f}%",
            bar_drawing,
            band_text,
            amount_text,
        ])

    # Total-Zeile
    if advisory_wealth_rappen and total_amount == 0:
        total_amount = advisory_wealth_rappen
    rows.append([
        Paragraph(f'<b>Total Beratungsvermögen</b>', _para_style_table()),
        f"{total_bps/100:.1f}%",
        "",
        "",
        _format_amount(total_amount, base_currency) if total_amount > 0 else "—",
    ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    col_widths = [
        table_width * 0.30,  # Anlageklasse
        table_width * 0.10,  # Soll
        table_width * 0.30,  # Visualisierung
        table_width * 0.15,  # Band
        table_width * 0.15,  # Betrag
    ]

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
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("ALIGN", (4, 0), (4, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    table.setStyle(TableStyle(style_cmds))
    flowables.append(table)
    return flowables


def _make_bar(bps: int, max_bps_max: int = 10000, color=None) -> Drawing:
    """Liefert einen schmalen Horizontal-Balken proportional zu bps."""
    bar_width = 50 * mm
    bar_height = 5 * mm
    drawing = Drawing(bar_width, bar_height)
    # Hintergrund
    drawing.add(Rect(0, 1, bar_width, bar_height - 2,
                     fillColor=colors.HexColor("#e2e8f0"),
                     strokeColor=None))
    # Wert-Balken
    pct = max(0.0, min(1.0, bps / float(max_bps_max)))
    value_w = bar_width * pct
    if value_w > 0:
        drawing.add(Rect(0, 1, value_w, bar_height - 2,
                         fillColor=color or colors.HexColor("#1e4b8f"),
                         strokeColor=None))
    return drawing


def _format_amount(rappen: int, currency: str = "CHF") -> str:
    """CHF-Format mit Schweizer Tausender-Trenner."""
    try:
        if currency == "CHF":
            value = rappen / 100.0
        else:
            from services.currency.converter import convert_rappen
            value = convert_rappen(rappen, "CHF", currency) / 100.0
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
