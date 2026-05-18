"""Sprint 14 Phase 1: Cover-Seite + Trenn-Cover.

Repliziert Swiss-Life-Wealth-Vorlage Seite 1 und Seite 10.
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from services.pdf.base import PDFContext
from services.pdf.components.header import _esc
from services.pdf.components.static_texts import (
    COVER_TAGLINE,
    DEFAULT_ADVISOR_EMAIL,
    DEFAULT_ADVISOR_ORG,
    DEFAULT_ADVISOR_PHONE,
    DEFAULT_ADVISOR_POSTAL,
    DEFAULT_ADVISOR_STREET,
    DEFAULT_ADVISOR_WEBSITE,
)
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_HEADER_BG,
    COLOR_HEADER_SUB,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    PAGE_SIZE,
)


def make_cover_page(
    ctx: PDFContext,
    *,
    client_address_lines: list[str] | None = None,
    client_phone: str | None = None,
    advisor_org: str | None = None,
    advisor_advisor_name: str | None = None,
    advisor_address_lines: list[str] | None = None,
    advisor_phone: str | None = None,
    advisor_email: str | None = None,
    advisor_website: str | None = None,
) -> list:
    """Cover-Seite (Seite 1) wie Vorlage:
    - "Ihre persönliche Anlagestrategie" Titel
    - Links: Kontaktinformationen Berater-Firma
    - Rechts: Persönliche Daten Klient
    - Tagline + Datum
    """
    page_width, page_height = PAGE_SIZE
    table_width = page_width - 24 * mm

    flowables: list = []

    # ---- Titel Block ----
    flowables.append(Spacer(1, 8 * mm))
    flowables.append(Paragraph(
        f'<font name="{FONT_BOLD}" size="28" color="#0f172a">'
        f'Ihre persönliche Anlagestrategie</font>',
        _para_compact(after=8 * mm),
    ))
    flowables.append(_horizontal_line(thickness=1.2))
    flowables.append(Spacer(1, 8 * mm))

    # ---- Kontaktbloecke (2-spaltig) ----
    org = advisor_org or ctx.advisor_org or DEFAULT_ADVISOR_ORG
    advisor_name = advisor_advisor_name or ctx.advisor_name or "Berater"
    addr_lines = advisor_address_lines or [DEFAULT_ADVISOR_STREET, DEFAULT_ADVISOR_POSTAL]
    phone = advisor_phone or DEFAULT_ADVISOR_PHONE
    email = advisor_email or DEFAULT_ADVISOR_EMAIL
    website = advisor_website or DEFAULT_ADVISOR_WEBSITE

    left_lines = [
        f'<font name="{FONT_BOLD}" size="9" color="#64748b">'
        f'KONTAKTINFORMATIONEN</font>',
        f'<font name="{FONT_BOLD}" size="12" color="#0f172a">{_esc(org)}</font>',
        f'<font name="{FONT_DEFAULT}" size="10" color="#1f2937">{_esc(advisor_name)}</font>',
    ]
    for line in addr_lines:
        if line:
            left_lines.append(
                f'<font name="{FONT_DEFAULT}" size="10" color="#475569">{_esc(line)}</font>'
            )
    if phone:
        left_lines.append(
            f'<font name="{FONT_DEFAULT}" size="10" color="#475569">{_esc(phone)}</font>'
        )
    if email:
        left_lines.append(
            f'<font name="{FONT_DEFAULT}" size="10" color="#475569">{_esc(email)}</font>'
        )
    if website:
        left_lines.append(
            f'<font name="{FONT_DEFAULT}" size="10" color="#475569">{_esc(website)}</font>'
        )

    # Rechts: Persoenliche Daten Klient
    right_lines = [
        f'<font name="{FONT_BOLD}" size="9" color="#64748b">'
        f'PERSÖNLICHE DATEN</font>',
        f'<font name="{FONT_BOLD}" size="12" color="#0f172a">{_esc(ctx.mandate_name)}</font>',
    ]
    if client_address_lines:
        for line in client_address_lines:
            if line:
                right_lines.append(
                    f'<font name="{FONT_DEFAULT}" size="10" color="#475569">{_esc(line)}</font>'
                )
    if client_phone:
        right_lines.append(
            f'<font name="{FONT_DEFAULT}" size="10" color="#475569">{_esc(client_phone)}</font>'
        )

    # 2-Spalten Layout
    max_lines = max(len(left_lines), len(right_lines))
    while len(left_lines) < max_lines:
        left_lines.append("")
    while len(right_lines) < max_lines:
        right_lines.append("")

    rows = []
    for i in range(max_lines):
        rows.append([
            Paragraph(left_lines[i], _para_compact(after=3)),
            Paragraph(right_lines[i], _para_compact(after=3)),
        ])
    contact_table = Table(rows, colWidths=[table_width * 0.5, table_width * 0.5])
    contact_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    flowables.append(contact_table)

    # ---- Tagline + Datum unten ----
    flowables.append(Spacer(1, 20 * mm))
    flowables.append(_horizontal_line(thickness=0.5))
    flowables.append(Spacer(1, 5 * mm))
    flowables.append(Paragraph(
        f'<font name="{FONT_ITALIC_OR_DEFAULT()}" size="11" color="#475569">'
        f'{_esc(COVER_TAGLINE)}</font>',
        _para_compact(after=6 * mm),
    ))
    flowables.append(Paragraph(
        f'<font name="{FONT_BOLD}" size="11" color="#0f172a">'
        f'{ctx.report_date.strftime("%d.%m.%Y")}</font>',
        _para_compact(),
    ))
    return flowables


def make_section_cover(title: str) -> list:
    """Trenn-Cover-Seite (z.B. Seite 10: 'Ihre persoenliche Ausgangslage').

    Grosses Titel-Element, vertikal zentriert wirkend (durch Spacer).
    """
    flowables = []
    flowables.append(Spacer(1, 60 * mm))
    flowables.append(_horizontal_line(thickness=1.2))
    flowables.append(Spacer(1, 6 * mm))
    flowables.append(Paragraph(
        f'<font name="{FONT_BOLD}" size="28" color="#0f172a">{_esc(title)}</font>',
        _para_compact(after=2 * mm),
    ))
    flowables.append(_horizontal_line(thickness=1.2))
    flowables.append(Spacer(1, 60 * mm))
    return flowables


def _horizontal_line(thickness: float = 0.5, color=None):
    from reportlab.platypus import HRFlowable
    return HRFlowable(
        width="100%",
        thickness=thickness,
        color=color or colors.HexColor("#0f172a"),
        spaceBefore=0,
        spaceAfter=0,
    )


def FONT_ITALIC_OR_DEFAULT():
    """Helvetica-Oblique fuer Italic-Tagline."""
    return "Helvetica-Oblique"


def _para_compact(after: float = 2):
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "CoverLine",
        fontName=FONT_DEFAULT,
        fontSize=10,
        leading=13,
        spaceAfter=after,
    )
