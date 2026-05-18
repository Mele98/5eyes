"""Sprint 12: Vertrags-PDF (ContractDocument).

Druckt einen einzelnen Vertrag (Anlagestrategie-Vertrag, Beratungsvertrag,
etc.) mit Praeambel, Haftungsklausel, Sondervereinbarungen und Unterschrift.

Inhalte stammen aus ContractDocument.content_json (per Frontend-Modal
m-contract-edit gepflegt).
"""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from services.pdf.base import PDFContext
from services.pdf.components.header import _esc, make_wealtharchitekten_header
from services.pdf.components.unterschrift import make_unterschrift_section
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_BODY,
    FONT_SIZE_HEADING,
    PAGE_SIZE,
    make_paragraph_styles,
)


def build_vertrag_flowables(ctx: PDFContext, data) -> list:
    """Vertrags-PDF Komposition.

    data ist VertragData mit:
    - document_title (str)
    - praeambel (str)
    - haftungsklausel (str)
    - sondervereinbarungen (str | None)
    - ort_unterzeichnung (str)
    - vereinbarungs_datum (str ISO yyyy-mm-dd oder dd.mm.yyyy)
    - mandate_number (str | None)
    - advisory_wealth_rappen (int | None)
    - document_type (str | None) — z.B. 'Anlagestrategie', 'Beratungsvertrag'
    """
    flowables: list = []
    styles = make_paragraph_styles()

    # ---- Header (WealthArchitekten-Banner) ----
    advisory_label = None
    if getattr(data, "advisory_wealth_rappen", None):
        advisory_label = _format_amount(data.advisory_wealth_rappen, ctx.base_currency)
    flowables.extend(make_wealtharchitekten_header(
        ctx,
        mandate_number=getattr(data, "mandate_number", None),
        advisory_wealth_label=advisory_label,
    ))

    # ---- Dokument-Titel ----
    doc_title = str(getattr(data, "document_title", "") or "Beratungsdokument")
    doc_type = str(getattr(data, "document_type", "") or "")
    flowables.append(Paragraph(
        f'<font name="{FONT_BOLD}" size="16" color="#0f172a">{_esc(doc_title)}</font>',
        _para_compact(after=2),
    ))
    if doc_type:
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="9" color="#64748b">'
            f'Dokument-Typ: {_esc(doc_type)}</font>',
            _para_compact(after=4),
        ))
    flowables.append(Spacer(1, 4 * mm))

    # ---- Praeambel ----
    praeambel = str(getattr(data, "praeambel", "") or "")
    if praeambel:
        flowables.append(_section_title("Präambel"))
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#334155">'
            f'{_esc(praeambel)}</font>',
            styles["body"],
        ))
        flowables.append(Spacer(1, 3 * mm))

    # ---- Vertragsgegenstand (Mandate-Daten als Kontext) ----
    flowables.append(_section_title("Vertragsgegenstand"))
    kontext_lines = []
    if getattr(data, "mandate_number", None):
        kontext_lines.append(("Mandat-Nummer", data.mandate_number))
    if getattr(data, "advisory_wealth_rappen", None):
        kontext_lines.append((
            "Beratungsvermögen",
            _format_amount(data.advisory_wealth_rappen, ctx.base_currency),
        ))
    kontext_lines.append(("Beratungsdatum", _format_date(getattr(data, "vereinbarungs_datum", ""))))
    kontext_lines.append((
        "Beratungsort",
        str(getattr(data, "ort_unterzeichnung", "Zürich") or "Zürich"),
    ))

    if kontext_lines:
        kontext_rows = [
            [
                Paragraph(f'<font color="#64748b" size="8"><b>{_esc(label).upper()}</b></font>',
                          _para_compact(after=0)),
                Paragraph(f'<font name="{FONT_BOLD}" size="10">{_esc(value)}</font>',
                          _para_compact(after=0)),
            ]
            for label, value in kontext_lines
        ]
        page_width, _ = PAGE_SIZE
        table_w = page_width - 24 * mm
        ktbl = Table(kontext_rows, colWidths=[table_w * 0.30, table_w * 0.70])
        ktbl.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        flowables.append(ktbl)
    flowables.append(Spacer(1, 4 * mm))

    # ---- Haftungsklausel ----
    haftung = str(getattr(data, "haftungsklausel", "") or "")
    if haftung:
        flowables.append(_section_title("Beratungshinweis & Haftung"))
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#334155">'
            f'{_esc(haftung)}</font>',
            styles["body"],
        ))
        flowables.append(Spacer(1, 3 * mm))

    # ---- Sondervereinbarungen ----
    sonder = str(getattr(data, "sondervereinbarungen", "") or "")
    if sonder:
        flowables.append(_section_title("Sondervereinbarungen"))
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#334155">'
            f'{_esc(sonder)}</font>',
            styles["body"],
        ))
        flowables.append(Spacer(1, 4 * mm))

    # ---- Bestätigung & Unterschrift (Standard-Komponente) ----
    flowables.extend(make_unterschrift_section())

    return flowables


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


def _format_date(raw: str) -> str:
    """ISO yyyy-mm-dd → dd.mm.yyyy. Sonst Original."""
    if not raw:
        return "—"
    s = str(raw).strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return f"{s[8:10]}.{s[5:7]}.{s[0:4]}"
    return s


def _section_title(text: str):
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        f'<font color="#475569" size="9"><b>{_esc(text).upper()}</b></font>',
        style,
    )


def _para_compact(after: float = 2):
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "VertCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_BODY,
        leading=12,
        spaceAfter=after,
    )
