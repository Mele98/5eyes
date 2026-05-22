"""Reines Asset-Allocation-PDF fuer die Asset-Allocation-Maske."""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, Spacer, Table, TableStyle

from services.pdf.base import AnlagestrategieData, PDFContext
from services.pdf.components.header import _esc
from services.pdf.components.header import make_wealtharchitekten_header
from services.pdf.components.saa_donut import make_saa_donut_with_legend
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


def build_asset_allocation_flowables(
    ctx: PDFContext,
    data: AnlagestrategieData,
) -> list:
    """Asset Allocation als Rubrik-PDF: Cover, Disclaimer, Kuchen, Subklassen."""
    styles = make_paragraph_styles()
    advisory_label = None
    if data.advisory_wealth_rappen:
        advisory_label = _format_amount(data.advisory_wealth_rappen, ctx.base_currency)

    flowables: list = []
    flowables.extend(make_single_report_cover(
        ctx,
        title="Asset Allocation",
        subtitle="Soll-Allokation und Subanlageklassen",
        mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
    ))
    flowables.append(PageBreak())
    flowables.extend(make_single_report_disclaimer(
        title="Wichtiger Hinweis",
        scope="Asset Allocation",
    ))
    flowables.append(PageBreak())
    flowables.extend(make_wealtharchitekten_header(
        ctx,
        mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
        document_title="Asset Allocation",
    ))

    if data.target_allocation_bps and sum(data.target_allocation_bps.values()) > 0:
        flowables.append(KeepTogether([
            _section_title("Soll-Allokation"),
            make_saa_donut_with_legend(
                data.target_allocation_bps,
                products=None,
                diameter_mm=60.0,
            ),
        ]))
        flowables.append(Spacer(1, 5 * mm))
        flowables.append(_section_title("Subanlageklassen"))
        flowables.append(_make_sub_asset_class_table(
            data.products,
            data.target_allocation_bps,
            base_currency=ctx.base_currency,
            advisory_wealth_rappen=data.advisory_wealth_rappen,
        ))
    else:
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="9" color="#94a3b8"><i>'
            f'Noch keine Asset Allocation berechnet.</i></font>',
            styles["small_muted"],
        ))

    return flowables


def _make_sub_asset_class_table(
    products: list,
    allocation_bps,
    *,
    base_currency: str,
    advisory_wealth_rappen: int | None,
) -> Table:
    rows = [["Anlageklasse / Subanlageklasse", "Gewicht", f"Betrag ({base_currency})"]]
    group_row_indexes: list[int] = []
    sub_rows: dict[tuple[str, str], dict[str, int]] = {}
    for product in products or []:
        bucket = str(product.get("asset_class", "") or "").lower()
        sub = str(product.get("sub_asset_class", "") or "")
        bps = int(product.get("target_weight_bps", 0) or 0)
        amount = int(product.get("target_amount_rappen", 0) or 0)
        if not bucket or not sub or bps == 0:
            continue
        key = (bucket, sub)
        existing = sub_rows.setdefault(key, {"bps": 0, "amount": 0})
        existing["bps"] += bps
        existing["amount"] += amount

    sub_by_bucket: dict[str, list[tuple[str, dict[str, int]]]] = {}
    for (bucket, sub), values in sub_rows.items():
        sub_by_bucket.setdefault(bucket, []).append((sub, values))

    for bucket in _ordered_buckets(allocation_bps):
        bucket_bps = int((allocation_bps or {}).get(bucket, 0) or 0)
        bucket_amount = int(advisory_wealth_rappen * bucket_bps / 10000) if advisory_wealth_rappen else 0
        group_row_indexes.append(len(rows))
        rows.append([
            f"{asset_class_label(bucket)} Total",
            _format_percent(bucket_bps),
            _format_amount(bucket_amount, base_currency) if bucket_amount > 0 else "-",
        ])

        children = sorted(
            sub_by_bucket.get(bucket, []),
            key=lambda item: (-int(item[1]["bps"] or 0), item[0]),
        )
        if not children and bucket_bps > 0:
            children = [(asset_class_label(bucket), {"bps": bucket_bps, "amount": bucket_amount})]
        for sub, values in children:
            amount = int(values["amount"] or 0)
            if amount <= 0 and advisory_wealth_rappen:
                amount = int(advisory_wealth_rappen * int(values["bps"] or 0) / 10000)
            rows.append([
                Paragraph(
                    f'<font color="#64748b">- {_esc(sub)}</font>',
                    _table_cell_style(),
                ),
                _format_percent(int(values["bps"] or 0)),
                _format_amount(amount, base_currency) if amount > 0 else "-",
            ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    table = Table(
        rows,
        colWidths=[
            table_width * 0.55,
            table_width * 0.18,
            table_width * 0.27,
        ],
    )
    style_commands = [
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
        ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE_TABLE),
        ("FONTNAME", (0, 1), (-1, -1), FONT_DEFAULT),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_TEXT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, COLOR_BORDER),
        ("ALIGN", (1, 0), (2, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    for row_index in group_row_indexes:
        style_commands.extend([
            ("FONTNAME", (0, row_index), (-1, row_index), FONT_BOLD),
            ("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#f8fafc")),
            ("LINEABOVE", (0, row_index), (-1, row_index), 0.45, COLOR_BORDER),
            ("TEXTCOLOR", (0, row_index), (-1, row_index), colors.HexColor("#0f172a")),
        ])
    table.setStyle(TableStyle(style_commands))
    return table


def _section_title(text: str):
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        f'<font color="#475569" size="9"><b>{_esc(text).upper()}</b></font>',
        style,
    )


def _ordered_buckets(allocation_bps) -> list[str]:
    buckets = [
        bucket for bucket, value in (allocation_bps or {}).items()
        if int(value or 0) > 0
    ]
    return sorted(
        buckets,
        key=lambda bucket: (
            -int((allocation_bps or {}).get(bucket, 0) or 0),
            BUCKET_ORDER.index(bucket) if bucket in BUCKET_ORDER else len(BUCKET_ORDER),
            bucket,
        ),
    )


def _format_percent(bps: int) -> str:
    pct = bps / 100.0
    if bps % 100 == 0:
        return f"{pct:.0f}%"
    return f"{pct:.1f}%"


def _table_cell_style():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "SubAssetClassCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=11,
        spaceAfter=0,
    )


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
