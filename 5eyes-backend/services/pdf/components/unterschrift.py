"""Sprint 11: Bestaetigung & Unterschrift (2-Spalten-Block).

Frontend-Vorlage:
- Links: "Ich bestaetige, die vorliegende Anlagestrategie besprochen und
  verstanden zu haben." + Unterschriftslinie + "Ort, Datum / Klient/in"
- Rechts: "Der Anlageberater bestaetigt, die Strategie besprochen und
  dokumentiert zu haben." + Unterschriftslinie + "Ort, Datum / Anlageberater"
"""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from services.pdf.components.header import _esc
from services.pdf.styles import (
    COLOR_BORDER_STRONG,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_DEFAULT,
    FONT_SIZE_BODY,
    FONT_SIZE_SMALL,
    PAGE_SIZE,
    make_paragraph_styles,
)


CLIENT_CONFIRM_TEXT = (
    "Ich bestätige, die vorliegende Anlagestrategie besprochen und verstanden zu haben."
)
ADVISOR_CONFIRM_TEXT = (
    "Der Anlageberater bestätigt, die Strategie besprochen und dokumentiert zu haben."
)


def make_unterschrift_section() -> list:
    """Returns Flowables: Section-Title + 2-Spalten-Unterschriftsblock."""
    styles = make_paragraph_styles()
    flowables = [_section_title("Bestätigung & Unterschrift")]

    # Pro Seite: Bestätigung-Text + Spacer für Unterschrift + Labels
    left_col = [
        Paragraph(
            f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#334155">'
            f'{_esc(CLIENT_CONFIRM_TEXT)}</font>',
            _para_compact(),
        ),
        Spacer(1, 16 * mm),  # Platz fuer Unterschrift
        _signature_line(),
        Paragraph(
            f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_SMALL}" color="#64748b">'
            'Ort, Datum / Klient/in</font>',
            _para_compact(after=0),
        ),
    ]
    right_col = [
        Paragraph(
            f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#334155">'
            f'{_esc(ADVISOR_CONFIRM_TEXT)}</font>',
            _para_compact(),
        ),
        Spacer(1, 16 * mm),
        _signature_line(),
        Paragraph(
            f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_SMALL}" color="#64748b">'
            'Ort, Datum / Anlageberater</font>',
            _para_compact(after=0),
        ),
    ]

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    composite = Table(
        [[left_col, right_col]],
        colWidths=[(table_width - 20 * mm) / 2, (table_width - 20 * mm) / 2],
    )
    composite.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 20 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flowables.append(composite)
    return flowables


def _signature_line():
    """Horizontale Linie als Platzhalter fuer Unterschrift."""
    from reportlab.platypus import HRFlowable
    return HRFlowable(
        width="100%",
        thickness=0.5,
        color=COLOR_BORDER_STRONG,
        spaceBefore=0,
        spaceAfter=2,
    )


def _section_title(text: str):
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        f'<font color="#475569" size="9"><b>{_esc(text).upper()}</b></font>',
        style,
    )


def _para_compact(after: float = 2):
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "SignCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_BODY,
        leading=12,
        spaceAfter=after,
    )
