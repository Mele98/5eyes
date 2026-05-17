"""Header-Komponente fuer 5eyes-PDFs: Titel + Mandant + Datum + optional Logo."""
from __future__ import annotations

from datetime import date

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors

from services.pdf.base import PDFContext
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_PRIMARY,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_BODY,
    FONT_SIZE_SMALL,
    FONT_SIZE_TITLE,
    make_paragraph_styles,
)


def make_document_header(title: str, ctx: PDFContext) -> list:
    """Erzeugt Flowables fuer den Dokument-Header.

    Layout (links-rechts):
    ┌─────────────────────────────┬────────────────────────┐
    │ <Titel>                     │            5eyes       │
    │ Mandant: <name>             │      <advisor_org>     │
    │ Datum: <date>               │     <advisor_name>     │
    └─────────────────────────────┴────────────────────────┘
    """
    styles = make_paragraph_styles()
    flowables = []

    # 2-Spalten-Header
    left_lines = [
        f'<font name="{FONT_BOLD}" size="{FONT_SIZE_TITLE}" color="#0B3D91">{_esc(title)}</font>',
        f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}">'
        f'<b>Mandant:</b> {_esc(ctx.mandate_name)}</font>',
        f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}">'
        f'<b>Datum:</b> {ctx.report_date.strftime("%d.%m.%Y")}</font>',
    ]
    right_lines = [
        f'<para align="right"><font name="{FONT_BOLD}" size="{FONT_SIZE_TITLE}" '
        f'color="#0B3D91">5eyes</font></para>',
    ]
    if ctx.advisor_org:
        right_lines.append(
            f'<para align="right"><font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}">'
            f'{_esc(ctx.advisor_org)}</font></para>'
        )
    right_lines.append(
        f'<para align="right"><font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}">'
        f'{_esc(ctx.advisor_name)}</font></para>'
    )

    left_para = [Paragraph(s, styles["body"]) for s in left_lines]
    right_para = [Paragraph(s, styles["body"]) for s in right_lines]

    # Padding bis beide gleich viele Zeilen
    max_lines = max(len(left_para), len(right_para))
    while len(left_para) < max_lines:
        left_para.append(Paragraph("", styles["body"]))
    while len(right_para) < max_lines:
        right_para.append(Paragraph("", styles["body"]))

    table_data = [[left_para[i], right_para[i]] for i in range(max_lines)]
    table = Table(table_data, colWidths=[110 * mm, 60 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    flowables.append(table)

    # Trennlinie
    flowables.append(Spacer(1, 3 * mm))
    flowables.append(_horizontal_line(COLOR_PRIMARY, thickness=1.5))
    flowables.append(Spacer(1, 5 * mm))

    return flowables


def _esc(s: str) -> str:
    """HTML-escape fuer ReportLab-Paragraph-XML."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _horizontal_line(color, thickness: float = 0.5):
    """Eine duenne horizontale Linie als Flowable."""
    from reportlab.platypus import HRFlowable
    return HRFlowable(width="100%", thickness=thickness, color=color, spaceBefore=0, spaceAfter=0)
