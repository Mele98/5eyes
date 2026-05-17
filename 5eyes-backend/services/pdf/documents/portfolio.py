"""Sprint 11 Phase 6: Portfolio-PDF — Fokus auf konkrete Positionen + Drift.

Eigenes Dokument (nicht im Anlagestrategie-PDF eingebettet) — Berater
will Portfolio separat drucken koennen mit Soll-vs-IST + Trade-Empfehlungen.

Sektionen:
1. Header (WealthArchitekten)
2. Portfolio-Uebersicht (Metric-Boxes: Total-IST, Positionen, Drift, TER)
3. Positionen-Tabelle (ISIN, Name, Soll%, IST%, Drift, Wert)
4. Unterschrift + FIDLEG-Footer
"""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from services.pdf.base import PDFContext
from services.pdf.components.header import _esc, make_wealtharchitekten_header
from services.pdf.components.unterschrift import make_unterschrift_section
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
    make_paragraph_styles,
)


def build_portfolio_flowables(ctx: PDFContext, data) -> list:
    """Portfolio-PDF: Positionen, Drift, Trades.

    data ist ein PortfolioData-dataclass oder dict mit:
    - mandate_number, advisory_wealth_rappen
    - positions: list[dict] mit name, isin, target_weight_bps,
      current_weight_bps, target_amount_rappen, current_amount_rappen,
      drift_bps, currency, ter_bps, provider
    """
    flowables: list = []
    styles = make_paragraph_styles()

    # ---- 1. Header ----
    advisory_label = None
    if getattr(data, "advisory_wealth_rappen", None):
        advisory_label = _format_amount(data.advisory_wealth_rappen, ctx.base_currency)
    flowables.extend(make_wealtharchitekten_header(
        ctx,
        mandate_number=getattr(data, "mandate_number", None),
        advisory_wealth_label=advisory_label,
    ))

    positions = list(getattr(data, "positions", []) or [])

    # ---- 2. Portfolio-Uebersicht (Metric-Boxes) ----
    flowables.append(_section_title("Portfolio-Übersicht"))
    if positions:
        flowables.append(_make_overview_boxes(positions, ctx.base_currency))
    else:
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="9" color="#94a3b8"><i>'
            f'Noch keine Positionen geladen. Bitte im Portfolio-Tab eine '
            f'Empfehlung generieren.</i></font>',
            styles["small_muted"],
        ))
    flowables.append(Spacer(1, 4 * mm))

    # ---- 3. Positionen-Tabelle ----
    flowables.append(_section_title("Positionen (Soll vs. IST)"))
    if positions:
        flowables.append(_make_positions_table(positions, ctx.base_currency))
    else:
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="9" color="#94a3b8"><i>'
            f'Keine Positions-Daten verfuegbar. Sobald die Anlagestrategie '
            f'in Produkte umgesetzt wird, erscheint hier die Detailliste.'
            f'</i></font>',
            styles["small_muted"],
        ))
    flowables.append(Spacer(1, 6 * mm))

    # ---- 4. Unterschrift ----
    flowables.extend(make_unterschrift_section())

    return flowables


def _make_overview_boxes(positions: list, currency: str):
    """4 Metric-Boxes: Total-Wert, Positionen-Count, max Drift, Gewichtete TER."""
    from services.pdf.components.produkte import _make_single_metric

    total_amount = sum(int(p.get("current_amount_rappen", 0) or 0) for p in positions)
    if total_amount == 0:
        total_amount = sum(int(p.get("target_amount_rappen", 0) or 0) for p in positions)
    count = len(positions)
    max_drift_bps = max(
        (abs(int(p.get("drift_bps", 0) or 0)) for p in positions),
        default=0,
    )
    # Weighted TER
    ter_sum_weighted = 0
    weight_sum = 0
    for p in positions:
        w = int(p.get("current_weight_bps", 0) or 0) or int(p.get("target_weight_bps", 0) or 0)
        t = int(p.get("ter_bps", 0) or 0)
        if w > 0 and t > 0:
            ter_sum_weighted += w * t
            weight_sum += w
    avg_ter_bps = (ter_sum_weighted / weight_sum) if weight_sum > 0 else 0

    boxes_data = [
        ("Total Wert", _format_amount(total_amount, currency)),
        ("Positionen", str(count)),
        ("Max. Drift", f"{max_drift_bps/100:.1f}%" if max_drift_bps > 0 else "—"),
        ("Gewichtete TER", f"{avg_ter_bps/100:.2f}%" if avg_ter_bps > 0 else "—"),
    ]
    metrics = [_make_single_metric(label, value) for label, value in boxes_data]

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    box_w = (table_width - 3 * 3 * mm) / 4
    metric_table = Table(
        [metrics],
        colWidths=[box_w] * 4,
    )
    metric_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return metric_table


def _make_positions_table(positions: list, currency: str):
    """7-Spalten-Tabelle: Produkt+ISIN | Subklasse | Soll% | IST% | Drift | Wert | TER."""
    rows = [["Produkt", "Subklasse", "Soll", "IST", "Drift", f"Wert ({currency})", "TER"]]
    for p in positions:
        name = str(p.get("name", "—") or "—")
        isin = str(p.get("isin", "") or "")
        sub = str(p.get("sub_asset_class", "") or "")
        target_bps = int(p.get("target_weight_bps", 0) or 0)
        current_bps = int(p.get("current_weight_bps", 0) or 0)
        drift_bps = int(p.get("drift_bps", current_bps - target_bps) or 0)
        amount = int(p.get("current_amount_rappen", 0) or 0) or int(p.get("target_amount_rappen", 0) or 0)
        ter = int(p.get("ter_bps", 0) or 0)
        provider = str(p.get("provider", "") or "")

        product_parts = [f'<font name="{FONT_BOLD}">{_esc(name)}</font>']
        if isin:
            isin_extra = f' · {_esc(provider)}' if provider else ''
            product_parts.append(
                f'<font color="#64748b" size="7">ISIN {_esc(isin)}{isin_extra}</font>'
            )
        product_para = Paragraph(
            "<br/>".join(product_parts),
            _para_compact(),
        )

        # Drift mit Farb-Marker
        drift_color = "#16a34a" if abs(drift_bps) <= 100 else ("#f59e0b" if abs(drift_bps) <= 300 else "#dc2626")
        drift_sign = "+" if drift_bps > 0 else ""
        drift_para = Paragraph(
            f'<font color="{drift_color}"><b>{drift_sign}{drift_bps/100:.1f}%</b></font>',
            _para_compact(),
        )

        rows.append([
            product_para,
            _esc(sub) if sub else "—",
            f"{target_bps/100:.1f}%" if target_bps > 0 else "—",
            f"{current_bps/100:.1f}%" if current_bps > 0 else "—",
            drift_para,
            _format_amount(amount, currency) if amount > 0 else "—",
            f"{ter/100:.2f}%" if ter > 0 else "—",
        ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    col_widths = [
        table_width * 0.28,  # Produkt
        table_width * 0.18,  # Subklasse
        table_width * 0.08,  # Soll
        table_width * 0.08,  # IST
        table_width * 0.10,  # Drift
        table_width * 0.16,  # Wert
        table_width * 0.08,  # TER
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
        ("ALIGN", (2, 0), (4, -1), "RIGHT"),
        ("ALIGN", (5, 0), (5, -1), "RIGHT"),
        ("ALIGN", (6, 0), (6, -1), "RIGHT"),
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


def _para_compact():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "PortCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=11,
        spaceAfter=0,
    )
