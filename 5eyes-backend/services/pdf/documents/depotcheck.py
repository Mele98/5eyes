"""Sprint U-P16 (2026-05-21): Depot-Check-PDF.

4-Seiten-Composer: Cover → Drift+Exposures → Top-Positionen+Stress → Disclaimer.
"""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, Spacer, Table, TableStyle

from services.pdf.base import DepotCheckData, PDFContext
from services.pdf.components.cover import make_cover_page
from services.pdf.components.drift_table import make_drift_table
from services.pdf.components.exposure_donut import make_exposure_donut
from services.pdf.components.header import _esc, make_wealtharchitekten_header
from services.pdf.components.stress_table import make_stress_table
from services.pdf.components.text_sections import make_disclaimer_section
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TABLE_HEADER_BG,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_TABLE,
    FONT_SIZE_TABLE_HEADER,
    PAGE_SIZE,
    make_paragraph_styles,
)


def build_depotcheck_flowables(ctx: PDFContext, data: DepotCheckData) -> list:
    """Depot-Check-PDF mit 4 logischen Seiten.

    1. Cover (Mandanten-Daten + Brand)
    2. Drift-Tabelle + 3 Exposure-Donuts (Country/Sector/Currency)
    3. Top-Positionen + Stress-Replays + Liquiditätsprofil
    4. Warnings + Disclaimer
    """
    flowables: list = []
    styles = make_paragraph_styles()

    advisory_label = None
    if data.total_advisory_wealth_rappen:
        advisory_label = _format_amount(data.total_advisory_wealth_rappen, ctx.base_currency)

    # ============================================================
    # 1. COVER
    # ============================================================
    flowables.extend(make_cover_page(ctx))
    flowables.append(PageBreak())

    # ============================================================
    # 2. ÜBERSICHT — DRIFT + EXPOSURES
    # ============================================================
    flowables.extend(make_wealtharchitekten_header(
        ctx, mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
        document_title="Depot-Check",
    ))

    # Bucket-Drift-Tabelle
    flowables.append(_section_title("Asset-Klassen — IST vs. Soll-Allokation"))
    if data.buckets:
        flowables.append(make_drift_table(data.buckets))
    else:
        flowables.append(_fallback_text("Keine Soll-Allokation berechnet — Drift-Analyse nicht verfügbar."))
    flowables.append(Spacer(1, 5 * mm))

    # 3 Exposure-Donuts side-by-side
    flowables.append(_section_title("Diversifikations-Tiefe"))
    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    donut_table = Table(
        [[
            make_exposure_donut(
                data.country_exposure_bps,
                title="Länder",
                hhi=int(data.concentration_hhi.get("country", 0) or 0),
                diameter_mm=38,
            ),
            make_exposure_donut(
                data.sector_exposure_bps,
                title="Sektoren (GICS)",
                hhi=int(data.concentration_hhi.get("sector", 0) or 0),
                diameter_mm=38,
            ),
            make_exposure_donut(
                data.currency_exposure_bps,
                title="Währungen",
                hhi=int(data.concentration_hhi.get("currency", 0) or 0),
                diameter_mm=38,
            ),
        ]],
        colWidths=[table_width / 3] * 3,
    )
    donut_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    flowables.append(donut_table)
    flowables.append(Spacer(1, 4 * mm))

    # Fonds-Charakteristika 4 Boxen
    flowables.append(_make_fund_metrics_boxes(data))
    flowables.append(PageBreak())

    # ============================================================
    # 3. TOP-POSITIONEN + STRESS-REPLAYS + LIQUIDITÄTSPROFIL
    # ============================================================
    flowables.extend(make_wealtharchitekten_header(
        ctx, mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
        document_title="Depot-Check",
    ))

    flowables.append(_section_title("Top-Positionen (nach Betrag)"))
    if data.top_positions:
        flowables.append(_make_top_positions_table(data.top_positions, ctx.base_currency))
    else:
        flowables.append(_fallback_text("Noch keine Positionen erfasst."))
    flowables.append(Spacer(1, 5 * mm))

    flowables.append(_section_title("Liquiditätsprofil"))
    flowables.append(_make_liquidity_bar(data.liquidity_profile_bps))
    flowables.append(Spacer(1, 5 * mm))

    flowables.append(_section_title("Historische Stress-Szenarien (Replay auf aktueller Allokation)"))
    if data.stress_scenarios:
        flowables.append(make_stress_table(data.stress_scenarios))
        flowables.append(Spacer(1, 2 * mm))
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="8" color="#64748b">'
            f'<i>Stress-Replay wendet historische jährliche Returns je Asset-Klasse auf die '
            f'aktuelle Bucket-Gewichtung an. Modell zeigt, was passieren wäre, wenn die '
            f'heutige Strategie zu Beginn der jeweiligen Krise gehalten worden wäre.</i></font>',
            styles["small_muted"],
        ))
    else:
        flowables.append(_fallback_text("Stress-Replay nicht verfügbar — keine Target-Allocation gefunden."))
    flowables.append(PageBreak())

    # ============================================================
    # 4. WARNINGS + DISCLAIMER
    # ============================================================
    flowables.extend(make_wealtharchitekten_header(
        ctx, mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
        document_title="Depot-Check",
    ))

    flowables.append(_section_title("Hinweise & Risikobeobachtungen"))
    if data.warnings:
        for warn in data.warnings:
            flowables.append(Paragraph(
                f'<font name="{FONT_DEFAULT}" size="10" color="#7f1d1d">'
                f'⚠ {_esc(warn)}</font>',
                styles["body"],
            ))
    else:
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="10" color="#166534">'
            f'✓ Keine kritischen Konzentrationsrisiken oder Bandbreiten-Verstösse identifiziert.</font>',
            styles["body"],
        ))
    flowables.append(Spacer(1, 6 * mm))

    flowables.extend(make_disclaimer_section())
    return flowables


# ===== Helpers =====

def _make_fund_metrics_boxes(data: DepotCheckData):
    """4 Metric-Boxen: TER, Duration, ESG, Top-Positions-HHI."""
    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    box_width = (table_width - 3 * 3 * mm) / 4

    boxes = [
        _make_metric_box("Gewichtete TER",
                         f'{data.weighted_ter_bps/100:.2f}%' if data.weighted_ter_bps else '—'),
        _make_metric_box("Duration (Bonds)",
                         f'{data.weighted_duration_years_x10/10:.1f} J' if data.weighted_duration_years_x10 else '—'),
        _make_metric_box("ESG-Score",
                         f'{data.weighted_esg_score_x10/10:.1f} / 100' if data.weighted_esg_score_x10 else '—'),
        _make_metric_box("Top-Positions-HHI",
                         str(int(data.concentration_hhi.get("top_positions", 0) or 0))),
    ]
    metric_table = Table([boxes], colWidths=[box_width] * 4)
    metric_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return metric_table


def _make_metric_box(label: str, value: str):
    from services.pdf.styles import COLOR_METRIC_BG
    styles = make_paragraph_styles()
    label_para = Paragraph(
        f'<font color="#64748b" size="7.5"><b>{_esc(label).upper()}</b></font>',
        styles["small"],
    )
    value_para = Paragraph(
        f'<font name="{FONT_BOLD}" size="13" color="#0f172a">{_esc(value)}</font>',
        styles["body"],
    )
    inner = Table([[label_para], [value_para]], colWidths=[None])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_METRIC_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return inner


def _make_top_positions_table(positions: list, base_currency: str):
    rows = [["#", "Produkt", "Asset-Klasse", "Betrag", "Anteil", "TER"]]
    for idx, p in enumerate(positions, start=1):
        name = str(p.get("product_name", "—") or "—")
        isin = str(p.get("isin", "") or "")
        asset_class = str(p.get("asset_class", "") or "")
        sub_class = str(p.get("sub_asset_class", "") or "")
        amount = int(p.get("amount_rappen", 0) or 0)
        weight_bps = int(p.get("weight_bps", 0) or 0)
        ter_bps = int(p.get("ter_bps", 0) or 0)

        prod_parts = [f'<font name="{FONT_BOLD}">{_esc(name)}</font>']
        if isin:
            prod_parts.append(f'<font color="#64748b" size="8">ISIN {_esc(isin)}</font>')

        rows.append([
            str(idx),
            Paragraph("<br/>".join(prod_parts), _para_cell()),
            Paragraph(
                f'<font size="9.5">{_esc(asset_class)}{(" · "+_esc(sub_class)) if sub_class else ""}</font>',
                _para_cell(),
            ),
            Paragraph(f'<para align="right">{_format_amount(amount, base_currency)}</para>', _para_cell()),
            Paragraph(f'<para align="right"><b>{weight_bps/100:.1f}%</b></para>', _para_cell()),
            Paragraph(
                f'<para align="right">{ter_bps/100:.2f}%</para>' if ter_bps else '<para align="right">—</para>',
                _para_cell(),
            ),
        ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    table = Table(
        rows,
        colWidths=[
            table_width * 0.04,
            table_width * 0.35,
            table_width * 0.25,
            table_width * 0.15,
            table_width * 0.11,
            table_width * 0.10,
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
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _make_liquidity_bar(lp):
    """Liquiditäts-Profil als horizontaler Stacked-Bar (Drawing)."""
    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.lib import colors as rl_colors
    page_width, _ = PAGE_SIZE
    bar_width = (page_width - 24 * mm)
    bar_height = 9 * mm
    drawing = Drawing(bar_width, bar_height + 5 * mm)

    tiers = [
        ("daily_bps", "Daily", "#166534"),
        ("weekly_bps", "Weekly", "#1e4b8f"),
        ("monthly_bps", "Monthly", "#92400e"),
        ("illiquid_bps", "Illiquid", "#7f1d1d"),
        ("unknown_bps", "Unbekannt", "#94a3b8"),
    ]
    total_bps = sum(int(lp.get(key, 0) or 0) for key, _, _ in tiers)
    if total_bps <= 0:
        drawing.add(Rect(
            0, 0, bar_width, bar_height,
            fillColor=rl_colors.HexColor("#e2e8f0"), strokeColor=rl_colors.HexColor("#cbd5e1"),
        ))
        drawing.add(String(
            bar_width / 2, bar_height / 2 - 3, "Keine Liquiditäts-Daten",
            fontSize=8, fontName=FONT_DEFAULT, textAnchor="middle",
            fillColor=rl_colors.HexColor("#94a3b8"),
        ))
        return drawing

    x_offset = 0.0
    for key, label, color_hex in tiers:
        bps = int(lp.get(key, 0) or 0)
        if bps <= 0:
            continue
        width = bar_width * bps / total_bps
        drawing.add(Rect(
            x_offset, 0, width, bar_height,
            fillColor=rl_colors.HexColor(color_hex), strokeColor=rl_colors.white,
            strokeWidth=0.5,
        ))
        if width > 30:  # nur Label wenn genug Platz
            drawing.add(String(
                x_offset + width / 2, bar_height / 2 - 3, f"{label} {bps/100:.0f}%",
                fontSize=8, fontName=FONT_BOLD, textAnchor="middle",
                fillColor=rl_colors.white,
            ))
        x_offset += width

    return drawing


def _section_title(text: str):
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        f'<font name="{FONT_BOLD}" size="12" color="#0f172a">{_esc(text)}</font>',
        style,
    )


def _fallback_text(text: str):
    styles = make_paragraph_styles()
    return Paragraph(
        f'<font name="{FONT_DEFAULT}" size="9" color="#94a3b8"><i>{_esc(text)}</i></font>',
        styles["small_muted"],
    )


def _para_cell():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "DCCell",
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
