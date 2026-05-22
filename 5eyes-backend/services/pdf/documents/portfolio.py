"""Portfolio-PDF: nur konkrete Portfolio-Positionen."""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle

from services.pdf.base import PDFContext
from services.pdf.components.header import _esc, make_wealtharchitekten_header
from services.pdf.components.single_report_disclaimer import (
    make_single_report_cover,
    make_single_report_disclaimer,
)
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
    asset_class_label,
    make_paragraph_styles,
)

BUCKET_ORDER = ("equities", "bonds", "real_estate", "alternatives", "liquidity")


def build_portfolio_flowables(ctx: PDFContext, data) -> list:
    """Portfolio-PDF: Cover, Disclaimer, danach ausschliesslich Positionen."""
    flowables: list = []
    styles = make_paragraph_styles()

    advisory_label = None
    if getattr(data, "advisory_wealth_rappen", None):
        advisory_label = _format_amount(data.advisory_wealth_rappen, ctx.base_currency)
    flowables.extend(make_single_report_cover(
        ctx,
        title="Portfolio",
        subtitle="Portfolio-Positionen und Umsetzungsuebersicht",
        mandate_number=getattr(data, "mandate_number", None),
        advisory_wealth_label=advisory_label,
    ))
    flowables.append(PageBreak())
    flowables.extend(make_single_report_disclaimer(
        title="Wichtiger Hinweis",
        scope="Portfolio",
    ))
    flowables.append(PageBreak())
    flowables.extend(make_wealtharchitekten_header(
        ctx,
        mandate_number=getattr(data, "mandate_number", None),
        advisory_wealth_label=advisory_label,
        document_title="Portfolio",
    ))

    positions = list(getattr(data, "positions", []) or [])
    flowables.append(_section_title("Portfolio-Positionen"))
    if positions:
        flowables.extend(_make_position_group_flowables(positions, ctx.base_currency))
    else:
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="9" color="#94a3b8"><i>'
            f'Noch keine Portfolio-Positionen geladen.</i></font>',
            styles["small_muted"],
        ))

    return flowables


def _make_position_group_flowables(positions: list, currency: str) -> list:
    """Gruppiert Produktpositionen wie im Frontend-HUD nach Anlageklasse."""
    flowables: list = []
    total_amount = sum(_position_amount_rappen(p) for p in positions)
    for index, (bucket, bucket_positions) in enumerate(_group_positions(positions)):
        if index:
            flowables.append(Spacer(1, 3 * mm))
        group_amount = sum(_position_amount_rappen(p) for p in bucket_positions)
        group_weight = sum(_position_weight_bps(p, total_amount) for p in bucket_positions)
        if group_weight <= 0 and total_amount > 0 and group_amount > 0:
            group_weight = int(round(group_amount / total_amount * 10000))
        flowables.append(_make_group_header(bucket, group_amount, group_weight, currency))
        flowables.append(_make_group_positions_table(bucket_positions, currency, total_amount))
    return flowables


def _make_group_header(bucket: str, amount_rappen: int, weight_bps: int, currency: str):
    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    label = _display_asset_class(bucket)
    summary_parts = []
    if amount_rappen > 0:
        summary_parts.append(_format_amount(amount_rappen, currency))
    if weight_bps > 0:
        summary_parts.append(_format_percent(weight_bps))
    summary = " / ".join(summary_parts) if summary_parts else "-"
    table = Table(
        [[
            Paragraph(f'<font name="{FONT_BOLD}">{_esc(label)}:</font>', _para_compact(size=9)),
            Paragraph(f'<font color="#64748b">{_esc(summary)}</font>', _para_compact(size=8, alignment=2)),
        ]],
        colWidths=[table_width * 0.62, table_width * 0.38],
    )
    table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _make_group_positions_table(positions: list, currency: str, total_amount: int):
    rows = [["Produkt", "Subklasse", "Soll", "Zielwert", "Waehrung", "TER"]]
    for p in positions:
        name = str(p.get("name", p.get("product_name", "-")) or "-")
        isin = str(p.get("isin", "") or "")
        sub = str(p.get("sub_asset_class", "") or "")
        target_bps = _position_weight_bps(p, total_amount)
        amount = _position_amount_rappen(p)
        ter = int(p.get("ter_bps", 0) or 0)
        provider = str(p.get("provider", p.get("issuer", "")) or "")
        product_currency = str(p.get("currency", currency) or currency)

        product_parts = [f'<font name="{FONT_BOLD}">{_esc(name)}</font>']
        if isin:
            isin_extra = f' / {_esc(provider)}' if provider else ''
            product_parts.append(
                f'<font color="#64748b" size="7">ISIN {_esc(isin)}{isin_extra}</font>'
            )
        product_para = Paragraph("<br/>".join(product_parts), _para_compact())

        rows.append([
            product_para,
            _esc(_display_sub_asset_class(sub)) if sub else "-",
            _format_percent(target_bps) if target_bps > 0 else "-",
            _format_amount(amount, currency) if amount > 0 else "-",
            _esc(product_currency),
            f"{ter/100:.2f}%" if ter > 0 else "-",
        ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    col_widths = [
        table_width * 0.36,
        table_width * 0.22,
        table_width * 0.10,
        table_width * 0.16,
        table_width * 0.08,
        table_width * 0.08,
    ]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
        ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE_TABLE),
        ("FONTNAME", (0, 1), (-1, -1), FONT_DEFAULT),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_TEXT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEBELOW", (0, 1), (-1, -1), 0.35, colors.HexColor("#f1f5f9")),
        ("ALIGN", (2, 0), (3, -1), "RIGHT"),
        ("ALIGN", (4, 0), (4, -1), "CENTER"),
        ("ALIGN", (5, 0), (5, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _group_positions(positions: list) -> list[tuple[str, list]]:
    grouped: dict[str, list] = {}
    for p in positions:
        bucket = _normalise_asset_class(p.get("asset_class"))
        if bucket == "Portfolio":
            bucket = _normalise_asset_class(p.get("sub_asset_class"))
        grouped.setdefault(bucket, []).append(p)

    ordered_keys = [key for key in BUCKET_ORDER if key in grouped]
    ordered_keys.extend(sorted(key for key in grouped if key not in BUCKET_ORDER))
    return [(key, grouped[key]) for key in ordered_keys]


def _normalise_asset_class(value) -> str:
    raw = str(value or "").strip()
    key = raw.lower().replace("-", "_")
    aliases = {
        "aktien": "equities",
        "equity": "equities",
        "equities": "equities",
        "stocks": "equities",
        "obligationen": "bonds",
        "anleihen": "bonds",
        "bonds": "bonds",
        "immobilien": "real_estate",
        "real estate": "real_estate",
        "real_estate": "real_estate",
        "alternative": "alternatives",
        "alternativen": "alternatives",
        "alternatives": "alternatives",
        "gold": "alternatives",
        "liquiditaet": "liquidity",
        "liquidität": "liquidity",
        "cash": "liquidity",
        "liquidity": "liquidity",
        "portfolio": "Portfolio",
    }
    if key in aliases:
        return aliases[key]
    if "aktien" in key or "equity" in key or "stock" in key:
        return "equities"
    if "obligation" in key or "bond" in key or "anleihe" in key:
        return "bonds"
    if "immobil" in key or "real_estate" in key or "real estate" in key:
        return "real_estate"
    if "alternative" in key or "gold" in key or "rohstoff" in key:
        return "alternatives"
    if "cash" in key or "liquid" in key:
        return "liquidity"
    return raw or "Portfolio"


def _display_asset_class(value) -> str:
    key = _normalise_asset_class(value)
    if key in BUCKET_ORDER:
        return asset_class_label(key)
    return str(value or key or "Portfolio")


def _display_sub_asset_class(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "-"
    key = raw.lower().replace("-", "_")
    if key in BUCKET_ORDER:
        return asset_class_label(key)
    return raw


def _position_amount_rappen(position: dict) -> int:
    target = int(position.get("target_amount_rappen", 0) or 0)
    if target > 0:
        return target
    return (
        int(position.get("current_amount_rappen", 0) or 0)
        or int(position.get("market_value_rappen", 0) or 0)
        or int(position.get("current_market_value_rappen", 0) or 0)
    )


def _position_weight_bps(position: dict, total_amount: int) -> int:
    bps = int(position.get("target_weight_bps", 0) or 0)
    if bps > 0:
        return bps
    amount = _position_amount_rappen(position)
    return int(round(amount / total_amount * 10000)) if total_amount > 0 and amount > 0 else 0


def _format_percent(bps: int) -> str:
    if bps <= 0:
        return "-"
    pct = bps / 100.0
    return f"{pct:.0f}%" if bps % 100 == 0 else f"{pct:.1f}%"


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


def _para_compact(size: float | None = None, alignment: int = 0):
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "PortCell",
        fontName=FONT_DEFAULT,
        fontSize=size or FONT_SIZE_TABLE,
        leading=11,
        alignment=alignment,
        spaceAfter=0,
    )
