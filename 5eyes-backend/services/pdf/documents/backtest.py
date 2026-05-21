"""Sprint U-P17c (2026-05-22): Strategie-Backtest-PDF.

3-Seiten-Composer im A4-Landscape WealthArchitekten-Layout:
1. Cover (Brand)
2. Hauptseite: Header + Meta-Zeile + Wealth-Chart + Drawdown-Chart +
   Kennzahlen-Tabelle (1 oder 2 Spalten)
3. Disclaimer + Warnings
"""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, Spacer

from services.pdf.base import BacktestData, PDFContext
from services.pdf.components.backtest_metrics import make_backtest_metrics_table
from services.pdf.components.cover import make_cover_page
from services.pdf.components.drawdown_chart import make_drawdown_chart
from services.pdf.components.header import _esc, make_wealtharchitekten_header
from services.pdf.components.text_sections import make_disclaimer_section
from services.pdf.components.wealth_chart import make_wealth_chart
from services.pdf.styles import (
    BUCKET_LABELS_DE,
    FONT_BOLD,
    FONT_DEFAULT,
    make_paragraph_styles,
)

BUCKET_ORDER = ("equities", "bonds", "real_estate", "alternatives", "liquidity")


def build_backtest_flowables(ctx: PDFContext, data: BacktestData) -> list:
    """Strategie-Backtest-PDF mit 3 logischen Seiten."""
    flowables: list = []
    styles = make_paragraph_styles()

    advisory_label = None
    if data.initial_value_rappen:
        advisory_label = _format_chf(data.initial_value_rappen, ctx.base_currency)

    # ============================================================
    # 1. COVER
    # ============================================================
    flowables.extend(make_cover_page(ctx))
    flowables.append(PageBreak())

    # ============================================================
    # 2. HAUPTSEITE — META + CHARTS + KENNZAHLEN
    # ============================================================
    flowables.extend(make_wealtharchitekten_header(
        ctx,
        mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
        document_title="Strategie-Backtest",
    ))

    # Meta-Zeile: Zeitraum + SOLL-Allokation
    weights_summary = _weights_summary(data.soll_weights_bps)
    bm_summary = _weights_summary(data.benchmark_weights_bps) if data.benchmark_weights_bps else None
    meta_parts = [
        f'<font name="{FONT_BOLD}">Zeitraum:</font> {data.start_year}–{data.end_year}',
        f'<font name="{FONT_BOLD}">Startkapital:</font> {_format_chf(data.initial_value_rappen, ctx.base_currency)}',
        f'<font name="{FONT_BOLD}">SOLL:</font> {_esc(weights_summary)}',
    ]
    if bm_summary:
        meta_parts.append(f'<font name="{FONT_BOLD}">Benchmark:</font> {_esc(bm_summary)}')
    flowables.append(Paragraph(
        f'<font name="{FONT_DEFAULT}" size="9" color="#475569">'
        + ' &nbsp;&middot;&nbsp; '.join(meta_parts)
        + '</font>',
        styles["small_muted"],
    ))
    flowables.append(Spacer(1, 3 * mm))

    # Wealth-Index-Chart
    flowables.append(_section_title("Wealth-Index"))
    if data.soll_wealth_path_rappen:
        flowables.append(make_wealth_chart(
            data.soll_wealth_path_rappen,
            data.benchmark_wealth_path_rappen if data.benchmark_wealth_path_rappen else None,
            height_mm=72.0,
        ))
    else:
        flowables.append(_fallback_text("Kein Wealth-Pfad verfügbar."))
    flowables.append(Spacer(1, 3 * mm))

    # Drawdown-Chart
    flowables.append(_section_title("Drawdown-Verlauf"))
    if data.soll_drawdown_path_bps:
        flowables.append(make_drawdown_chart(
            data.soll_drawdown_path_bps,
            data.benchmark_drawdown_path_bps if data.benchmark_drawdown_path_bps else None,
            height_mm=38.0,
        ))
    else:
        flowables.append(_fallback_text("Kein Drawdown-Pfad verfügbar."))
    flowables.append(Spacer(1, 4 * mm))

    # Kennzahlen-Tabelle
    flowables.append(_section_title("Kennzahlen"))
    if data.soll_metrics:
        flowables.append(make_backtest_metrics_table(
            data.soll_metrics,
            data.benchmark_metrics if data.benchmark_metrics else None,
        ))
    else:
        flowables.append(_fallback_text("Keine Kennzahlen verfügbar."))

    flowables.append(PageBreak())

    # ============================================================
    # 3. WARNINGS + DISCLAIMER
    # ============================================================
    flowables.extend(make_wealtharchitekten_header(
        ctx,
        mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
        document_title="Strategie-Backtest",
    ))

    flowables.append(_section_title("Methodik & Hinweise"))
    method_para = (
        f'<font name="{FONT_DEFAULT}" size="9.5" color="#334155">'
        f'Der Backtest wendet die SOLL-Strategie (Bucket-Gewichte aus der aktuellen '
        f'TargetAllocation) auf historische Jahresrenditen pro Asset-Klasse an. '
        f'Datenquelle: <i>asset_class_annual_returns</i>; Anchor-Indizes (USD-'
        f'Total-Return) für die Standard-Buckets sind via Marktdaten-Aggregator '
        f'(yfinance/stooq) eingespeist. Das Initial-Kapital entspricht dem '
        f'Beratungsvermögen-Snapshot der TargetAllocation. Pfad-Berechnung: '
        f'Buy-and-Hold mit jährlichem Rebalancing zur SOLL-Quote (Year-End-'
        f'Snapshot). Cashflows, Spar- und Bezugspläne werden nicht berücksichtigt — '
        f'der Backtest zeigt die reine Strategie-Performance.</font>'
    )
    flowables.append(Paragraph(method_para, styles["body"]))
    flowables.append(Spacer(1, 4 * mm))

    if data.warnings:
        flowables.append(_section_title("Hinweise"))
        for warn in data.warnings:
            flowables.append(Paragraph(
                f'<font name="{FONT_DEFAULT}" size="10" color="#7f1d1d">'
                f'⚠ {_esc(str(warn))}</font>',
                styles["body"],
            ))
        flowables.append(Spacer(1, 4 * mm))

    flowables.extend(make_disclaimer_section())
    return flowables


# ===== Helpers =====


def _weights_summary(weights_bps) -> str:
    if not weights_bps:
        return "—"
    parts = []
    for bucket in BUCKET_ORDER:
        bps = int((weights_bps or {}).get(bucket, 0) or 0)
        if bps <= 0:
            continue
        parts.append(f"{BUCKET_LABELS_DE.get(bucket, bucket)} {bps/100:.0f}%")
    return " · ".join(parts) if parts else "—"


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


def _format_chf(rappen: int, currency: str = "CHF") -> str:
    try:
        if currency == "CHF":
            value = int(rappen or 0) / 100.0
        else:
            from services.currency.converter import convert_rappen
            value = convert_rappen(int(rappen or 0), "CHF", currency) / 100.0
        return f"{currency} {value:,.0f}".replace(",", "'")
    except Exception:
        return f"CHF {int(rappen or 0) / 100.0:,.0f}".replace(",", "'")
