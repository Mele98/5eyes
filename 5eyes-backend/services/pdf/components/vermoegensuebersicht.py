"""Sprint 14 Phase 2: Vermoegensuebersicht (Beratungsvermoegen + Anderes).

Hierarchische Tabelle mit Asset-Class-Gruppen + Subtotale + Total.
Vorlage-Seite 11 der User-Referenz.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

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
    asset_class_label,
    make_paragraph_styles,
)

BUCKET_ORDER = ("liquidity", "bonds", "equities", "real_estate", "alternatives")
BUCKET_TOTAL_LABELS = {
    "liquidity": "Total Liquidität",
    "bonds": "Total Obligationen",
    "equities": "Total Aktien",
    "real_estate": "Total Immobilien",
    "alternatives": "Total Alternative Anlagen",
}


def make_vermoegensuebersicht_section(
    advisory_positions: Iterable[Mapping],
    other_wealth_positions: Iterable[Mapping] | None = None,
    *,
    base_currency: str = "CHF",
) -> list:
    """Returns Flowables: Section-Title + Beratungsvermoegen-Tabelle +
    optional Anderes-Vermoegen-Tabelle.

    advisory_positions: List of {asset_class, sub_asset_class, current_amount_rappen}
    other_wealth_positions: List of {label, amount_rappen, kind}
    """
    flowables: list = []
    styles = make_paragraph_styles()

    flowables.append(_section_title("💰  Vermögensübersicht"))

    pos_list = list(advisory_positions or [])
    other_list = list(other_wealth_positions or [])

    if not pos_list:
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="9" color="#94a3b8"><i>'
            f'Noch keine Vermögenspositionen erfasst.</i></font>',
            styles["small_muted"],
        ))
        return flowables

    flowables.append(_make_advisory_table(pos_list, base_currency))

    if other_list:
        # Sprint 14 Phase 3 Fix B8: KeepTogether sonst splittet sich Total-Zeile
        flowables.append(Spacer(1, 4 * mm))
        flowables.append(KeepTogether([
            Paragraph(
                f'<font name="{FONT_BOLD}" size="10" color="#0f172a">Anderes Vermögen</font>',
                styles["body"],
            ),
            _make_other_wealth_table(other_list, base_currency),
        ]))

    return flowables


def _make_advisory_table(positions: list, currency: str):
    """Hierarchische Tabelle: pro Bucket Sub-Klassen + Subtotal, am Ende Grand-Total."""
    # Aggregation
    by_bucket: dict[str, dict[str, int]] = {}
    grand_total = 0
    for p in positions:
        ac = str(p.get("asset_class", "") or "").lower()
        sub = str(p.get("sub_asset_class", "") or ac or "—")
        amt = int(p.get("current_amount_rappen", 0) or 0)
        if amt == 0:
            continue
        by_bucket.setdefault(ac, {})
        by_bucket[ac][sub] = by_bucket[ac].get(sub, 0) + amt
        grand_total += amt

    rows = [["Beratungsvermögen", f"Betrag ({currency})", "Anteil"]]

    for bucket in BUCKET_ORDER:
        subs = by_bucket.get(bucket, {})
        if not subs:
            continue
        bucket_total = sum(subs.values())
        # Sub-Zeilen
        for sub, amt in sorted(subs.items(), key=lambda kv: -kv[1]):
            pct = (amt / grand_total * 100) if grand_total > 0 else 0
            rows.append([
                Paragraph(
                    f'<font color="#475569">  {_esc(sub)}</font>',
                    _para_cell(),
                ),
                _format_amount(amt, currency),
                f"{pct:.2f} %",
            ])
        # Subtotal-Zeile
        bucket_pct = (bucket_total / grand_total * 100) if grand_total > 0 else 0
        rows.append([
            Paragraph(
                f'<font name="{FONT_BOLD}">{_esc(BUCKET_TOTAL_LABELS.get(bucket, asset_class_label(bucket)))}</font>',
                _para_cell(),
            ),
            Paragraph(f'<b>{_format_amount(bucket_total, currency)}</b>', _para_cell()),
            Paragraph(f'<b>{bucket_pct:.2f} %</b>', _para_cell()),
        ])

    # Grand Total
    rows.append([
        Paragraph(f'<font name="{FONT_BOLD}">Total Beratungsvermögen</font>', _para_cell()),
        Paragraph(f'<b>{_format_amount(grand_total, currency)}</b>', _para_cell()),
        Paragraph('<b>100.00 %</b>', _para_cell()),
    ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    table = Table(rows, colWidths=[table_width * 0.55, table_width * 0.25, table_width * 0.20], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
        ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE_TABLE),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEABOVE", (0, -1), (-1, -1), 1.0, COLOR_BORDER),
        ("BACKGROUND", (0, -1), (-1, -1), COLOR_TABLE_HEADER_BG),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _make_other_wealth_table(positions: list, currency: str):
    rows = [["Anderes Vermögen", f"Betrag ({currency})"]]
    total = 0
    for p in positions:
        label = str(p.get("label", "—") or "—")
        amt = int(p.get("amount_rappen", 0) or 0)
        if amt == 0:
            continue
        total += amt
        rows.append([_esc(label), _format_amount(amt, currency)])
    rows.append([
        Paragraph(f'<font name="{FONT_BOLD}">Total Anderes Vermögen</font>', _para_cell()),
        Paragraph(f'<b>{_format_amount(total, currency)}</b>', _para_cell()),
    ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    table = Table(rows, colWidths=[table_width * 0.65, table_width * 0.35])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), FONT_SIZE_TABLE),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, COLOR_BORDER),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, COLOR_BORDER),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _format_amount(rappen: int, currency: str = "CHF") -> str:
    try:
        if currency == "CHF":
            value = rappen / 100.0
        else:
            from services.currency.converter import convert_rappen
            value = convert_rappen(rappen, "CHF", currency) / 100.0
        return f"{value:,.0f}".replace(",", "'")
    except Exception:
        return f"{rappen/100.0:,.0f}".replace(",", "'")


def _section_title(text: str):
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        f'<font name="{FONT_BOLD}" size="12" color="#0f172a">{_esc(text)}</font>',
        style,
    )


def _para_cell():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "VermCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=11,
        spaceAfter=0,
    )
