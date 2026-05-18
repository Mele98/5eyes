"""Sprint 13: 'Effektives Portfolio' Sektion — IST-Bestand pro Position.

Frontend-Wording: 'Effektives Portfolio' = aktuelle Bestaende des Kunden
(im Gegensatz zu Soll-Allokation = Empfehlung).

Layout:
- 5 Spalten: Produkt + ISIN | Subklasse | IST-Anteil | IST-Wert | TER
- Sortiert nach IST-Wert absteigend
- Falls keine IST-Daten: Fallback-Text
"""
from __future__ import annotations

from typing import Iterable, Mapping

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
    FONT_SIZE_SMALL,
    FONT_SIZE_TABLE,
    FONT_SIZE_TABLE_HEADER,
    PAGE_SIZE,
    make_paragraph_styles,
)


def make_effektives_portfolio_section(
    positions: Iterable[Mapping],
    *,
    base_currency: str = "CHF",
) -> list:
    """Returns Flowables: Section-Title + Tabelle (oder Fallback-Text)."""
    flowables = [_section_title("Effektives Portfolio (IST-Bestand)")]
    pos_list = list(positions or [])

    # Nur Positionen mit IST-Bestand (current_amount > 0 ODER current_weight > 0)
    ist_positions = [
        p for p in pos_list
        if int(p.get("current_amount_rappen", 0) or 0) > 0
        or int(p.get("current_weight_bps", 0) or 0) > 0
    ]

    if not ist_positions:
        styles = make_paragraph_styles()
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="9" color="#94a3b8"><i>'
            f'Noch keine effektiven Bestaende erfasst. Die IST-Werte werden '
            f'bei Portfolio-Umsetzung oder via Kursdaten-Import aktualisiert.'
            f'</i></font>',
            styles["small_muted"],
        ))
        return flowables

    # Sortieren nach IST-Wert (groesste zuerst)
    ist_positions.sort(
        key=lambda p: int(p.get("current_amount_rappen", 0) or 0),
        reverse=True,
    )

    total_amount = sum(int(p.get("current_amount_rappen", 0) or 0) for p in ist_positions)

    rows = [["Produkt", "Subklasse", "IST-Anteil", f"IST-Wert ({base_currency})", "TER"]]
    for p in ist_positions:
        name = str(p.get("name", "—") or "—")
        isin = str(p.get("isin", "") or "")
        provider = str(p.get("provider", "") or "")
        sub = str(p.get("sub_asset_class", "") or "")
        current_bps = int(p.get("current_weight_bps", 0) or 0)
        current_amount = int(p.get("current_amount_rappen", 0) or 0)
        ter = int(p.get("ter_bps", 0) or 0)
        ccy = str(p.get("currency", "CHF") or "CHF")

        # Wenn current_weight_bps fehlt aber wir Total haben, ableiten
        if current_bps == 0 and total_amount > 0 and current_amount > 0:
            current_bps = int(round(current_amount / total_amount * 10000))

        product_cell_parts = [f'<font name="{FONT_BOLD}">{_esc(name)}</font>']
        if isin:
            extra = f' · {_esc(provider)}' if provider else ''
            product_cell_parts.append(
                f'<font color="#64748b" size="{FONT_SIZE_SMALL}">'
                f'ISIN {_esc(isin)}{extra}</font>'
            )
        product_para = Paragraph(
            "<br/>".join(product_cell_parts),
            _para_compact(),
        )

        rows.append([
            product_para,
            _esc(sub) if sub else "—",
            f"{current_bps/100:.1f}%" if current_bps > 0 else "—",
            _format_amount(current_amount, ccy) if current_amount > 0 else "—",
            f"{ter/100:.2f}%" if ter > 0 else "—",
        ])

    # Total-Zeile
    rows.append([
        Paragraph('<b>Total IST-Bestand</b>', _para_compact()),
        "",
        "100.0%" if total_amount > 0 else "—",
        _format_amount(total_amount, base_currency) if total_amount > 0 else "—",
        "",
    ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    col_widths = [
        table_width * 0.35,
        table_width * 0.20,
        table_width * 0.12,
        table_width * 0.22,
        table_width * 0.11,
    ]
    table = Table(rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
        ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE_TABLE),
        ("FONTNAME", (0, 1), (-1, -2), FONT_DEFAULT),
        ("FONTNAME", (0, -1), (-1, -1), FONT_BOLD),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_TEXT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, COLOR_BORDER),
        ("ALIGN", (2, 0), (4, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    flowables.append(table)
    return flowables


def _format_amount(rappen: int, currency: str = "CHF") -> str:
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


def _para_compact():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "EpCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=11,
        spaceAfter=0,
    )
