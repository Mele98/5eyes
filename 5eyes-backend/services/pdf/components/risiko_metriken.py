"""Sprint 11: 5 farbcodierte Metric-Boxes fuer Risiko-Indikatoren.

Frontend-Vorlage: "Risikoindiktatoren & Prognose (Monte Carlo)"
- Erwartete Rendite (p.a. langfristig)
- Median CAGR (geometrisch)
- Volatilitaet (p.a. annualisiert)
- Max. Drawdown (historisch) — orange Akzent
- VaR 95% (1-Jahres-Risiko) — rot Akzent
"""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from services.pdf.components.header import _esc
from services.pdf.components.produkte import _make_single_metric
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_BORDER_DANGER,
    COLOR_BORDER_WARN,
    PAGE_SIZE,
    make_paragraph_styles,
)


def make_risiko_metriken_section(
    *,
    expected_return_bps: int | None,
    median_cagr_bps: int | None,
    volatility_bps: int | None,
    max_drawdown_bps: int | None,
    var_95_bps: int | None,
) -> list:
    """5 Metric-Boxes in einer Tabellen-Zeile."""
    if not any([expected_return_bps, median_cagr_bps, volatility_bps,
                max_drawdown_bps, var_95_bps]):
        return []

    flowables = [_section_title("Risikoindiktatoren & Prognose (Monte Carlo)")]

    boxes = [
        ("Erwartete Rendite", _fmt_pct(expected_return_bps), "p.a. langfristig", COLOR_BORDER),
        ("Median CAGR", _fmt_pct(median_cagr_bps), "geometrisch", COLOR_BORDER),
        ("Volatilität", _fmt_pct(volatility_bps), "p.a. annualisiert", COLOR_BORDER),
        ("Max. Drawdown", _fmt_pct(max_drawdown_bps, neg=True), "historisch", COLOR_BORDER_WARN),
        ("VaR 95%", _fmt_pct(var_95_bps, neg=True), "1-Jahres-Risiko", COLOR_BORDER_DANGER),
    ]

    metric_widgets = []
    for label, value, subtitle, border_color in boxes:
        metric_widgets.append(_make_single_metric_with_sub(label, value, subtitle, border_color))

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    gap = 2 * mm
    n = len(metric_widgets)
    box_width = (table_width - (n - 1) * gap) / n

    metric_table = Table(
        [metric_widgets],
        colWidths=[box_width] * n,
    )
    metric_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), gap),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    flowables.append(metric_table)
    return flowables


def _make_single_metric_with_sub(label: str, value: str, subtitle: str, border_color):
    """Wie produkte._make_single_metric aber mit zusaetzlichem Subtitle."""
    from services.pdf.styles import (
        COLOR_METRIC_BG,
        FONT_BOLD,
        FONT_DEFAULT,
        FONT_SIZE_METRIC_LABEL,
        FONT_SIZE_METRIC_VALUE,
    )
    from reportlab.lib.styles import ParagraphStyle

    def _ps(after=0):
        return ParagraphStyle(
            "RiskMet",
            fontName=FONT_DEFAULT,
            fontSize=8,
            leading=10,
            spaceAfter=after,
        )

    content = [
        Paragraph(
            f'<font color="#64748b" size="{FONT_SIZE_METRIC_LABEL}"><b>'
            f'{_esc(label).upper()}</b></font>',
            _ps(),
        ),
        Paragraph(
            f'<font name="{FONT_BOLD}" size="{FONT_SIZE_METRIC_VALUE}" color="#0f172a">'
            f'{_esc(value)}</font>',
            _ps(after=2),
        ),
        Paragraph(
            f'<font color="#94a3b8" size="7"><i>{_esc(subtitle)}</i></font>',
            _ps(),
        ),
    ]
    inner = Table([[c] for c in content], colWidths=[None])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_METRIC_BG),
        ("BOX", (0, 0), (-1, -1), 0.8, border_color),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return inner


def _fmt_pct(bps: int | None, *, neg: bool = False) -> str:
    if bps is None or bps == 0:
        return "—"
    value = bps / 100.0
    if neg and value > 0:
        return f"−{value:.2f}%"
    return f"{value:.2f}%"


def _section_title(text: str):
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        f'<font color="#475569" size="9"><b>{_esc(text).upper()}</b></font>',
        style,
    )
