"""Sprint U-P16: Stress-Replay-Tabelle für Depot-Check-PDF.

Pro Szenario: Label | Zeitraum | Cumul-Return | Max-Drawdown | Recovery.
"""
from __future__ import annotations

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


def make_stress_table(scenarios: list) -> Table:
    """Returns Table mit Szenario | Zeitraum | Cumul | MaxDD | Recovery."""
    rows = [["Szenario", "Zeitraum", "Cumul. Return", "Max-Drawdown", "Recovery"]]
    for s in scenarios:
        label = str(s.get("label", "—") or "—")
        period = str(s.get("period", "") or "—")
        cumul_bps = int(s.get("cumulative_return_bps", 0) or 0)
        max_dd_bps = int(s.get("max_drawdown_bps", 0) or 0)
        recovery = int(s.get("recovery_months", 0) or 0)

        cumul_color = "#166534" if cumul_bps >= 0 else "#7f1d1d"
        cumul_sign = "+" if cumul_bps >= 0 else ""
        recovery_text = f"{recovery} Mt." if recovery > 0 else "—"

        rows.append([
            Paragraph(f'<font name="{FONT_BOLD}">{_esc(label)}</font>', _para_compact()),
            Paragraph(f'<font color="#475569" size="9.5">{_esc(period)}</font>', _para_compact()),
            Paragraph(
                f'<para align="right"><font color="{cumul_color}"><b>{cumul_sign}{cumul_bps/100:.1f}%</b></font></para>',
                _para_compact(),
            ),
            Paragraph(
                f'<para align="right"><font color="#7f1d1d"><b>-{max_dd_bps/100:.1f}%</b></font></para>',
                _para_compact(),
            ),
            Paragraph(
                f'<para align="right"><font color="#475569">{recovery_text}</font></para>',
                _para_compact(),
            ),
        ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    table = Table(
        rows,
        colWidths=[
            table_width * 0.32,
            table_width * 0.30,
            table_width * 0.13,
            table_width * 0.13,
            table_width * 0.12,
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
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _para_compact():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "StressCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=11,
        spaceAfter=0,
    )
