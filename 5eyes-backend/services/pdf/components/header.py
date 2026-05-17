"""Sprint 11: WealthArchitekten-Dark-Header fuer Anlagestrategie-PDF.

Dark-Banner mit 2-spaltigem Layout:
- Links: "WealthArchitekten" Brand + "Anlagestrategie" Titel + Datum + Vertraulich
- Rechts: "Kundendossier" + "Mandat <Nr>" + "Beratungsvermoegen CHF <X>"
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from services.pdf.base import PDFContext
from services.pdf.styles import (
    COLOR_HEADER_BG,
    COLOR_HEADER_SUB,
    COLOR_HEADER_TEXT,
    FONT_BOLD,
    FONT_DEFAULT,
    PAGE_SIZE,
)


def _esc(s) -> str:
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def make_wealtharchitekten_header(
    ctx: PDFContext,
    *,
    mandate_number: str | None = None,
    advisory_wealth_label: str | None = None,
) -> list:
    """Dunkler Header-Banner (Voll-Breite, ueber Margins hinaus).

    Wird als KeepTogether-Block am Anfang des Documents eingefuegt.

    Da ReportLab Margins fix sind, simulieren wir den Voll-Breite-Banner
    durch eine Tabelle mit Hintergrund-Farbe, die die volle Page-Width
    minus minimaler Margins fuellt.
    """
    page_width, _ = PAGE_SIZE
    # Banner-Width: volle Page minus minimaler horizontaler Margin
    banner_width = page_width - 24 * mm

    # ---- Linke Spalte: Branding + Titel + Datum ----
    left_lines = [
        f'<para><font name="{FONT_BOLD}" size="9" color="#94a3b8">'
        f'WEALTHARCHITEKTEN</font></para>',
        f'<para><font name="{FONT_BOLD}" size="22" color="#ffffff">'
        f'Anlagestrategie</font></para>',
        f'<para><font name="{FONT_DEFAULT}" size="8" color="#94a3b8">'
        f'Vertraulich · Erstellt am {ctx.report_date.strftime("%d.%m.%Y")}</font></para>',
    ]
    left_paragraphs = [Paragraph(line, _para_style_blank()) for line in left_lines]

    # ---- Rechte Spalte: Kundendossier + Mandat + Vermoegen ----
    right_lines = [
        f'<para align="right"><font name="{FONT_DEFAULT}" size="8" color="#94a3b8">'
        f'KUNDENDOSSIER</font></para>',
        f'<para align="right"><font name="{FONT_BOLD}" size="11" color="#ffffff">'
        f'{_esc(ctx.mandate_name)}</font></para>',
    ]
    if mandate_number:
        right_lines.append(
            f'<para align="right"><font name="{FONT_DEFAULT}" size="8" color="#94a3b8">'
            f'Mandat {_esc(mandate_number)}</font></para>'
        )
    if advisory_wealth_label:
        right_lines.append(
            f'<para align="right"><font name="{FONT_DEFAULT}" size="8" color="#94a3b8">'
            f'Beratungsvermögen {_esc(advisory_wealth_label)}</font></para>'
        )
    right_paragraphs = [Paragraph(line, _para_style_blank()) for line in right_lines]

    # Padding bis beide Spalten gleich viele Zeilen
    max_lines = max(len(left_paragraphs), len(right_paragraphs))
    while len(left_paragraphs) < max_lines:
        left_paragraphs.append(Paragraph("", _para_style_blank()))
    while len(right_paragraphs) < max_lines:
        right_paragraphs.append(Paragraph("", _para_style_blank()))

    # 2-Spalten-Tabelle (jeweils 50%)
    rows = []
    for i in range(max_lines):
        rows.append([left_paragraphs[i], right_paragraphs[i]])

    table = Table(rows, colWidths=[banner_width * 0.65, banner_width * 0.35])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_HEADER_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 12 * mm),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 12 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
        # Aussen-Padding fuer 1. und letzte Zeile groesser
        ("TOPPADDING", (0, 0), (-1, 0), 5 * mm),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 5 * mm),
    ]))

    return [table, Spacer(1, 4 * mm)]


def _para_style_blank():
    """Minimal-Style fuer Paragraphen im Header (Color/Font kommt via XML inline)."""
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "WAHeaderInline",
        fontName=FONT_DEFAULT,
        fontSize=9,
        leading=11,
        spaceAfter=0,
    )


# Backwards-Compat: Sprint 5 hatte make_document_header(title, ctx). Behalten
# als duenne Wrapper, damit Risikoprofil-PDF nicht bricht.
def make_document_header(title: str, ctx: PDFContext) -> list:
    """Wrapper fuer Sprint-5-Risikoprofil-PDF. Sprint-11-Anlagestrategie
    nutzt make_wealtharchitekten_header() stattdessen."""
    return make_wealtharchitekten_header(ctx)
