"""Sprint U-P17c (2026-05-22): Kennzahlen-Tabelle für Backtest-PDF.

Spalten: 1 (nur SOLL) oder 2 (SOLL + Benchmark). Zeilen: Total-Return,
CAGR, Vol, Sharpe, Max-Drawdown, Best/Worst Year (mit Year-Label),
Win-Rate, Start-/Endwert.
"""
from __future__ import annotations

from typing import Mapping

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
    FONT_SIZE_TABLE,
    FONT_SIZE_TABLE_HEADER,
    PAGE_SIZE,
)


def _fmt_pct_bps(bps: int, decimals: int = 1) -> str:
    return f"{int(bps or 0) / 100:.{decimals}f}%"


def _fmt_signed_pct_bps(bps: int, decimals: int = 1) -> str:
    v = int(bps or 0) / 100
    return f"{'+' if v >= 0 else ''}{v:.{decimals}f}%"


def _fmt_chf(rappen: int) -> str:
    value = int(rappen or 0) / 100
    return f"CHF {value:,.0f}".replace(",", "'")


def make_backtest_metrics_table(
    soll_metrics: Mapping,
    benchmark_metrics: Mapping | None = None,
) -> Table:
    """Returns Table mit Backtest-Kennzahlen.

    Layout: Linke Spalte = Label, weitere = SOLL (+ Benchmark).
    """
    cols = [("SOLL-Strategie", soll_metrics)]
    if benchmark_metrics:
        cols.append(("Benchmark", benchmark_metrics))

    # Header
    header = [Paragraph(f'<font name="{FONT_BOLD}">Kennzahl</font>', _cell_style())]
    for label, _m in cols:
        header.append(Paragraph(
            f'<para align="right"><font name="{FONT_BOLD}">{_esc(label)}</font></para>',
            _cell_style(),
        ))

    rows: list[list] = [header]

    def add_row(label: str, render_fn, *, bold: bool = False, neg_color: bool = False):
        cells = [Paragraph(
            f'<font name="{FONT_BOLD}">{_esc(label)}</font>' if bold
            else f'{_esc(label)}',
            _cell_style(),
        )]
        for _lbl, m in cols:
            val = render_fn(m)
            style = '<para align="right">'
            if neg_color:
                style += '<font color="#7f1d1d">'
            if bold:
                style += '<b>'
            style += _esc(str(val))
            if bold:
                style += '</b>'
            if neg_color:
                style += '</font>'
            style += '</para>'
            cells.append(Paragraph(style, _cell_style()))
        rows.append(cells)

    add_row("Total-Return",
            lambda m: _fmt_signed_pct_bps(int(m.get("total_return_bps", 0) or 0)))
    add_row("CAGR (annualisiert)",
            lambda m: _fmt_signed_pct_bps(int(m.get("cagr_bps", 0) or 0), decimals=2))
    add_row("Volatilität (annualisiert)",
            lambda m: _fmt_pct_bps(int(m.get("vol_bps", 0) or 0), decimals=2))
    add_row("Sharpe-Ratio",
            lambda m: f'{int(m.get("sharpe_x100", 0) or 0) / 100:.2f}')
    add_row("Max Drawdown",
            lambda m: "-" + _fmt_pct_bps(int(m.get("max_drawdown_bps", 0) or 0)),
            neg_color=True)
    add_row("Bestes Jahr",
            lambda m: _fmt_signed_pct_bps(int(m.get("best_year_bps", 0) or 0))
                       + (f' ({m["best_year_label"]})' if m.get("best_year_label") else ""))
    add_row("Schlechtestes Jahr",
            lambda m: _fmt_signed_pct_bps(int(m.get("worst_year_bps", 0) or 0))
                       + (f' ({m["worst_year_label"]})' if m.get("worst_year_label") else ""))
    add_row("Win-Rate (positive Jahre)",
            lambda m: _fmt_pct_bps(int(m.get("win_rate_x100", 0) or 0), decimals=0)
                       + f' ({int(m.get("positive_years", 0) or 0)}/{int(m.get("years_count", 0) or 0)})')
    add_row("Startwert",
            lambda m: _fmt_chf(int(m.get("start_value_rappen", 0) or 0)))
    add_row("Endwert",
            lambda m: _fmt_chf(int(m.get("end_value_rappen", 0) or 0)),
            bold=True)

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    if benchmark_metrics:
        col_widths = [table_width * 0.40, table_width * 0.30, table_width * 0.30]
    else:
        col_widths = [table_width * 0.55, table_width * 0.45]

    table = Table(rows, colWidths=col_widths, repeatRows=1)
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
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _cell_style():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "BTMetricCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=11,
        spaceAfter=0,
    )
