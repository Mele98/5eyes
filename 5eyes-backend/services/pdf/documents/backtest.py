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
    flowables.extend(make_cover_page(
        ctx,
        document_title="Strategie-Backtest",
        document_subtitle="Historische Rendite- und Drawdown-Analyse",
    ))
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

    # Bug-#8b (2026-06-08): Brutto-vs-Netto-Vergleich wenn Fees gepflegt.
    # Berater-Aussage: 'Der Indexvergleich ist ohne Fees nicht investierbar;
    # nach Fee-Adjustierung liegt die Strategie naeher am realen Anlage-
    # ergebnis dran.' Wir rendern fuer SOLL und Benchmark je eine Mini-
    # Tabelle, die brutto vs. netto CAGR + Endwert + Drag aufzeigt.
    fee_block = _make_fee_comparison_block(data, styles)
    if fee_block:
        flowables.append(Spacer(1, 4 * mm))
        flowables.append(_section_title("Brutto vs. Netto (Bug-#8b)"))
        flowables.extend(fee_block)

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


def _make_fee_comparison_block(data, styles) -> list:
    """Bug-#8b (2026-06-08): Brutto-vs-Netto-Vergleich.

    Rendert NICHTS, wenn weder strategy_fee_bps noch benchmark_fee_bps > 0
    und die gross-Pfade leer sind. Sonst eine kompakte ASCII-Tabelle als
    Paragraph mit Endwerten und Performance-Drag (CHF p.a. und Gesamt-bps).
    """
    has_strat_fee = int(getattr(data, "strategy_fee_bps", 0) or 0) > 0
    has_bm_fee = int(getattr(data, "benchmark_fee_bps", 0) or 0) > 0
    if not (has_strat_fee or has_bm_fee):
        return []

    rows = []
    if has_strat_fee and getattr(data, "soll_gross_wealth_path_rappen", None):
        rows.append(_fee_row(
            label="Strategie (SOLL)",
            fee_bps=int(getattr(data, "strategy_fee_bps", 0) or 0),
            gross_path=getattr(data, "soll_gross_wealth_path_rappen", []),
            net_path=getattr(data, "soll_wealth_path_rappen", []),
        ))
    if has_bm_fee and getattr(data, "benchmark_gross_wealth_path_rappen", None):
        rows.append(_fee_row(
            label="Benchmark",
            fee_bps=int(getattr(data, "benchmark_fee_bps", 0) or 0),
            gross_path=getattr(data, "benchmark_gross_wealth_path_rappen", []),
            net_path=getattr(data, "benchmark_wealth_path_rappen", []),
        ))
    if not rows:
        return []

    header = (
        f'<font name="{FONT_BOLD}" size="9" color="#0f172a">'
        f'Pfad &nbsp;&middot;&nbsp; Fee p.a. &nbsp;&middot;&nbsp; Brutto-Endwert &nbsp;&middot;&nbsp; '
        f'Netto-Endwert &nbsp;&middot;&nbsp; Fee-Drag total</font>'
    )
    body_lines = [header] + rows
    paragraph = Paragraph(
        f'<font name="{FONT_DEFAULT}" size="9" color="#334155">'
        + "<br/>".join(body_lines)
        + '</font>',
        styles["body"],
    )
    note = Paragraph(
        f'<font name="{FONT_DEFAULT}" size="8" color="#64748b"><i>'
        f'Geometrischer Fee-Abzug pro Jahr nach Bucket-Update. Der Brutto-'
        f'Indexvergleich ist nicht direkt investierbar; die Netto-Reihe '
        f'spiegelt eine realistisch gefuehrte Strategie inkl. TER, Depot- '
        f'und Beratungsgebuehren.</i></font>',
        styles["small_muted"],
    )
    return [paragraph, Spacer(1, 2 * mm), note]


def _fee_row(*, label: str, fee_bps: int, gross_path, net_path) -> str:
    gross_end = _path_end_rappen(gross_path)
    net_end = _path_end_rappen(net_path)
    drag_rappen = max(0, gross_end - net_end)
    drag_pct = (drag_rappen / gross_end * 100.0) if gross_end > 0 else 0.0
    return (
        f"{_esc(label)} &nbsp;&middot;&nbsp; "
        f"{fee_bps/100.0:.2f}% &nbsp;&middot;&nbsp; "
        f"CHF {_format_thousands(gross_end)} &nbsp;&middot;&nbsp; "
        f"CHF {_format_thousands(net_end)} &nbsp;&middot;&nbsp; "
        f"CHF {_format_thousands(drag_rappen)} ({drag_pct:.1f}%)"
    )


def _path_end_rappen(path) -> int:
    if not path:
        return 0
    try:
        last = path[-1]
        # Tuples: (year, total_rappen)
        return int(last[1])
    except (IndexError, TypeError, ValueError):
        return 0


def _format_thousands(rappen: int) -> str:
    try:
        value = int(rappen or 0) / 100.0
        return f"{value:,.0f}".replace(",", "'")
    except Exception:
        return "0"


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
