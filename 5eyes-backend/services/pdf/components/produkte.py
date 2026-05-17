"""Sprint 11: Umsetzung in Produkte (ISIN-Tabelle + Metric-Boxes).

Frontend-Vorlage:
- 4 Metric-Boxes oben: Produkte (Count), Zielvolumen, Gewichtete TER, Waehrungen
- 6-Spalten-Tabelle: Produkt+ISIN, Subklasse, Soll%, Zielwert, CCY, TER
- Fallback-Text wenn keine Produkte
"""
from __future__ import annotations

from typing import Iterable, Mapping

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from services.pdf.components.header import _esc
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_METRIC_BG,
    COLOR_TABLE_HEADER_BG,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_METRIC_LABEL,
    FONT_SIZE_METRIC_VALUE,
    FONT_SIZE_SMALL,
    FONT_SIZE_TABLE,
    FONT_SIZE_TABLE_HEADER,
    PAGE_SIZE,
    make_paragraph_styles,
)

FALLBACK_TEXT = (
    "Noch kein Produktrezept im aktuellen App-Zustand geladen. Sobald das "
    "Portfolio generiert wurde, erscheint hier die Produktliste mit ISIN, "
    "Zielgewicht, Zielwert, Währung und TER."
)


def make_produkte_section(
    products: Iterable[Mapping],
    *,
    base_currency: str = "CHF",
) -> list:
    """Returns Flowables: Section-Title + 4 Metric-Boxes + Tabelle ODER Fallback."""
    products_list = list(products or [])
    flowables = [_section_title("Umsetzung in Produkte (ISIN)")]

    # Beschreibungs-Paragraph
    flowables.append(Paragraph(
        '<font name="' + FONT_DEFAULT + '" size="8.5" color="#475569">'
        'Das Portfolio ist die konkrete Umsetzung der Soll-Allokation in '
        'Produktbausteine. Detailbestände und spätere Live-Drift werden im '
        'Review nachgeführt.'
        '</font>',
        make_paragraph_styles()["body"],
    ))

    if not products_list:
        flowables.append(Spacer(1, 3 * mm))
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="9" color="#94a3b8"><i>{_esc(FALLBACK_TEXT)}</i></font>',
            make_paragraph_styles()["small_muted"],
        ))
        return flowables

    # ---- Metric-Boxes ----
    flowables.append(_make_metric_boxes(products_list, base_currency))
    flowables.append(Spacer(1, 3 * mm))

    # ---- ISIN-Tabelle ----
    flowables.append(_make_isin_table(products_list, base_currency))
    return flowables


def _make_metric_boxes(products: list, base_currency: str):
    count = len(products)
    total_amount = sum(int(p.get("target_amount_rappen", 0) or 0) for p in products)
    # Weighted TER
    ter_sum_weighted = 0
    weight_sum = 0
    for p in products:
        w = int(p.get("target_weight_bps", 0) or 0)
        t = int(p.get("ter_bps", 0) or 0)
        if w > 0 and t > 0:
            ter_sum_weighted += w * t
            weight_sum += w
    avg_ter_bps = (ter_sum_weighted / weight_sum) if weight_sum > 0 else 0
    currencies = sorted({str(p.get("currency", "CHF") or "CHF") for p in products if p.get("currency")})

    boxes_data = [
        ("Produkte", str(count)),
        ("Zielvolumen", _format_amount(total_amount, base_currency)),
        ("Gewichtete TER", f"{avg_ter_bps/100.0:.2f}%"),
        ("Währungen", ", ".join(currencies) if currencies else "—"),
    ]

    # 4 Boxen in einer Tabellen-Zeile
    box_paragraphs = []
    for label, value in boxes_data:
        box_paragraphs.append(_make_single_metric(label, value))

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    box_width = (table_width - 3 * 3 * mm) / 4  # 3 Gaps von 3mm
    metric_table = Table(
        [box_paragraphs],
        colWidths=[box_width] * 4,
    )
    metric_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return metric_table


def _make_single_metric(label: str, value: str, border_color=None):
    """Eine Metric-Box mit Border, Label oben, Value gross unten."""
    content = [
        Paragraph(
            f'<font color="#64748b" size="{FONT_SIZE_METRIC_LABEL}">'
            f'<b>{_esc(label).upper()}</b></font>',
            _para_compact(),
        ),
        Paragraph(
            f'<font name="{FONT_BOLD}" size="{FONT_SIZE_METRIC_VALUE}" color="#0f172a">'
            f'{_esc(value)}</font>',
            _para_compact(line_after=0),
        ),
    ]
    inner = Table([[c] for c in content], colWidths=[None])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_METRIC_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, border_color or COLOR_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return inner


def _make_isin_table(products: list, base_currency: str):
    rows = [["Produkt", "Subklasse", "Soll", "Zielwert", "CCY", "TER"]]
    for p in products:
        name = str(p.get("name", "—") or "—")
        isin = str(p.get("isin", "") or "")
        sub = str(p.get("sub_asset_class", "") or "")
        weight_bps = int(p.get("target_weight_bps", 0) or 0)
        amount = int(p.get("target_amount_rappen", 0) or 0)
        ccy = str(p.get("currency", "CHF") or "CHF")
        ter = int(p.get("ter_bps", 0) or 0)
        provider = str(p.get("provider", "") or "")

        product_cell_parts = [f'<font name="{FONT_BOLD}">{_esc(name)}</font>']
        if isin:
            product_cell_parts.append(
                f'<font color="#64748b" size="{FONT_SIZE_SMALL}">'
                f'ISIN {_esc(isin)}{(" · "+_esc(provider)) if provider else ""}</font>'
            )
        product_para = Paragraph(
            "<br/>".join(product_cell_parts),
            _para_compact(),
        )

        rows.append([
            product_para,
            _esc(sub) if sub else "—",
            f"{weight_bps/100:.1f}%" if weight_bps > 0 else "—",
            _format_amount(amount, ccy) if amount > 0 else "—",
            ccy,
            f"{ter/100:.2f}%" if ter > 0 else "—",
        ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    col_widths = [
        table_width * 0.35,  # Produkt
        table_width * 0.20,  # Subklasse
        table_width * 0.10,  # Soll
        table_width * 0.15,  # Zielwert
        table_width * 0.08,  # CCY
        table_width * 0.12,  # TER
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
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("ALIGN", (5, 0), (5, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


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


def _para_compact(line_after: float = 0):
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "ProdCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=10,
        spaceAfter=line_after,
    )
