"""Roadmap #57/#58 (Standpunkt 2026-08-07): SOLL/IST-Vergleich + Risiko-
Kennzahlen ins gedruckte Beratungsprotokoll.

Im Frontend laengst da (Roadmap #35-38: Sharpe/P90/P10/Zielerreichung SOLL
vs IST in der Kennzahlen-Tabelle des Asset-Allocation-Popups) -- im PDF
fehlte die entsprechende Sektion, obwohl dieselben Zahlen bereits in
engine_payload["monte_carlo"] berechnet werden (siehe routers/pdf_reports.py
::_build_anlagestrategie_data). Dieses Modul repliziert exakt die Frontend-
Berechnung (aaShowProjection() in 5eyes_v2.html), damit Bildschirm und
Papier-Dokument dieselben Zahlen zeigen.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from services.pdf.components.header import _esc
from services.pdf.components.swiss_numbers import format_bps_as_pct, format_chf_rappen
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


def _sharpe_ratio(cagr_bps: int | None, vol_bps: int | None, risk_free_bps: int) -> float | None:
    """(Median-Rendite - risikofrei) / Volatilitaet.

    Identisch zur Frontend-Formel (5eyes_v2.html, aaShowProjection()
    `_sharpe`) -- gleiche Konvention (risk_free_bps=80 Default =
    liquidity_return_bps), damit Bildschirm und PDF nicht divergieren.
    """
    if cagr_bps is None or vol_bps is None or vol_bps <= 0:
        return None
    return (cagr_bps - risk_free_bps) / vol_bps


def _fmt_sharpe(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _fmt_chf_pair_row(label: str, soll_rappen: int | None, ist_rappen: int | None, currency: str) -> list:
    cell_style = make_paragraph_styles().get("small_muted") or make_paragraph_styles().get("body")
    return [
        Paragraph(_esc(label), cell_style),
        Paragraph(_esc(format_chf_rappen(soll_rappen, currency=currency)), cell_style),
        Paragraph(_esc(format_chf_rappen(ist_rappen, currency=currency)), cell_style),
    ]


def make_sollist_kennzahlen_table(
    *,
    target_median_end_rappen: int | None,
    target_p90_end_rappen: int | None,
    target_p10_end_rappen: int | None,
    current_median_end_rappen: int | None,
    current_p90_end_rappen: int | None,
    current_p10_end_rappen: int | None,
    target_cagr_bps: int | None,
    current_cagr_bps: int | None,
    target_volatility_1y_bps: int | None,
    current_volatility_1y_bps: int | None,
    risk_free_bps: int = 80,
    currency: str = "CHF",
) -> list:
    """SOLL/IST-Kennzahlentabelle: Endwerte, Volatilitaet, Rendite, Sharpe.

    Leere Liste (kein Render) wenn weder SOLL- noch IST-Monte-Carlo-Werte
    vorliegen -- z.B. bevor 'Anlagestrategie berechnen' je gelaufen ist.
    """
    has_any = any([
        target_median_end_rappen, current_median_end_rappen,
        target_cagr_bps, current_cagr_bps,
    ])
    if not has_any:
        return []

    sharpe_target = _sharpe_ratio(target_cagr_bps, target_volatility_1y_bps, risk_free_bps)
    sharpe_current = _sharpe_ratio(current_cagr_bps, current_volatility_1y_bps, risk_free_bps)

    header_style = make_paragraph_styles().get("small_muted") or make_paragraph_styles().get("body")
    rows = [[
        Paragraph("<b>Kennzahl</b>", header_style),
        Paragraph("<b>SOLL-Strategie</b>", header_style),
        Paragraph("<b>IST-Portfolio (heute)</b>", header_style),
    ]]
    rows.append(_fmt_chf_pair_row(
        "Erwartetes Endvermögen (Median)",
        target_median_end_rappen, current_median_end_rappen, currency,
    ))
    rows.append(_fmt_chf_pair_row(
        "Endvermögen optimistisch (P90)",
        target_p90_end_rappen, current_p90_end_rappen, currency,
    ))
    rows.append(_fmt_chf_pair_row(
        "Endvermögen pessimistisch (P10)",
        target_p10_end_rappen, current_p10_end_rappen, currency,
    ))
    cell_style = make_paragraph_styles().get("small_muted") or make_paragraph_styles().get("body")
    rows.append([
        Paragraph(_esc("Rendite p.a. (Median)"), cell_style),
        Paragraph(_esc(format_bps_as_pct(target_cagr_bps, decimals=2)), cell_style),
        Paragraph(_esc(format_bps_as_pct(current_cagr_bps, decimals=2)), cell_style),
    ])
    rows.append([
        Paragraph(_esc("Volatilität (1 Jahr)"), cell_style),
        Paragraph(_esc(format_bps_as_pct(target_volatility_1y_bps, decimals=2)), cell_style),
        Paragraph(_esc(format_bps_as_pct(current_volatility_1y_bps, decimals=2)), cell_style),
    ])
    rows.append([
        Paragraph(
            f'<font color="#475569">Rendite/Risiko (Sharpe, risikofrei '
            f'{risk_free_bps / 100:.1f}%)</font>', cell_style,
        ),
        Paragraph(_esc(_fmt_sharpe(sharpe_target)), cell_style),
        Paragraph(_esc(_fmt_sharpe(sharpe_current)), cell_style),
    ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    table = Table(
        rows,
        colWidths=[table_width * 0.46, table_width * 0.27, table_width * 0.27],
    )
    table.setStyle(TableStyle([
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
    ]))
    return [table]


def make_sollist_goal_comparison_table(
    goal_analysis: Sequence[Mapping],
    current_goal_analysis: Sequence[Mapping],
) -> list:
    """Pro Ziel: Median-Zielerreichung SOLL vs. IST (Roadmap #36-Pendant im PDF).

    Matched ueber goal_id. Ziele, die nur auf einer Seite vorkommen
    (z.B. IST-Simulation lieferte kein Ergebnis), werden mit '—' fuer die
    fehlende Seite angezeigt statt uebersprungen -- Vollstaendigkeit vor
    Kompaktheit fuer ein FIDLEG-Dokument.
    """
    if not goal_analysis and not current_goal_analysis:
        return []

    current_by_id = {
        str(item.get("goal_id")): item
        for item in current_goal_analysis
        if item.get("goal_id")
    }
    seen_ids: set[str] = set()
    cell_style = make_paragraph_styles().get("small_muted") or make_paragraph_styles().get("body")
    header_style = cell_style
    rows = [[
        Paragraph("<b>Ziel</b>", header_style),
        Paragraph("<b>Erreichung SOLL</b>", header_style),
        Paragraph("<b>Erreichung IST</b>", header_style),
    ]]

    def _pct_cell(item: Mapping | None) -> str:
        if not item:
            return "—"
        try:
            return f"{int(item.get('median_achievement_pct') or 0)}%"
        except (TypeError, ValueError):
            return "—"

    for goal in goal_analysis:
        goal_id = str(goal.get("goal_id") or "")
        seen_ids.add(goal_id)
        label = str(goal.get("label") or goal_id or "—")
        current_item = current_by_id.get(goal_id)
        rows.append([
            Paragraph(_esc(label), cell_style),
            Paragraph(_esc(_pct_cell(goal)), cell_style),
            Paragraph(_esc(_pct_cell(current_item)), cell_style),
        ])

    # IST-nur-Ziele (sollte selten sein, aber Vollstaendigkeit vor Kompaktheit).
    for goal_id, current_item in current_by_id.items():
        if goal_id in seen_ids:
            continue
        label = str(current_item.get("label") or goal_id or "—")
        rows.append([
            Paragraph(_esc(label), cell_style),
            Paragraph("—", cell_style),
            Paragraph(_esc(_pct_cell(current_item)), cell_style),
        ])

    if len(rows) == 1:
        return []

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    table = Table(
        rows,
        colWidths=[table_width * 0.5, table_width * 0.25, table_width * 0.25],
    )
    table.setStyle(TableStyle([
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
    ]))
    return [table]


def make_sollist_section_title() -> Paragraph:
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        '<font color="#475569" size="9"><b>SOLL/IST-VERGLEICH</b></font>',
        style,
    )
