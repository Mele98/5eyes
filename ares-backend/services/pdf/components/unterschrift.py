"""Sprint 11: Bestaetigung & Unterschrift (2-Spalten-Block).

Frontend-Vorlage:
- Links: "Ich bestaetige, die vorliegende Anlagestrategie besprochen und
  verstanden zu haben." + Unterschriftslinie + "Ort, Datum / Klient/in"
- Rechts: "Der Anlageberater bestaetigt, die Strategie besprochen und
  dokumentiert zu haben." + Unterschriftslinie + "Ort, Datum / Anlageberater"
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from core.customer_terms import READONLY_VIEW_MODE, draft_headline, is_final_document, normalize_mode
from services.pdf.components.header import _esc
from services.pdf.styles import (
    COLOR_BORDER_STRONG,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_DEFAULT,
    FONT_SERIF_BOLD,
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


NOT_FOR_SIGNATURE_TEXT = "Nicht zur Unterzeichnung"
# N-910-01: bisheriger Wortlaut fuer die nicht publizierte Soll-Allokation.
_UNPUBLISHED_NOTICE = (
    "Entwurf – die Soll-Allokation ist nicht publiziert. Dieses Dokument dient "
    "der Besprechung; unterzeichnet wird erst die Fassung nach der Publikation."
)
_DRAFT_NOTICE = (
    "Dieses Dokument dient der Besprechung; unterzeichnet wird erst die finale Fassung."
)
_VIEW_NOTICE = (
    "Diese Fassung ist eine Ansicht und wurde nicht abgegeben; unterzeichnet wird "
    "nur die finale Fassung, die eine berechtigte Person abgibt."
)


def make_signature_block(ctx, **kwargs) -> list:
    """H-193 Fixrunde 1 (N-939-01): einziger Weg zum Unterschriftsblock in
    einem Kunden-PDF. Nur die finale Fassung (``is_final_document``) traegt
    Unterschriftsfelder; jede Nicht-Final-Fassung -- nicht publiziert, Ansicht
    durch "Lesend", Entwurf ohne Gebuehrenvereinbarung, ohne freigegebene
    Vertragsvorlage, vor Vertragsabschluss usw. -- bekommt stattdessen den
    Hinweis "Nicht zur Unterzeichnung" mit dem Grund."""
    mode = getattr(ctx, "watermark_mode", None)
    if is_final_document(mode):
        return make_unterschrift_section(**kwargs)
    return [not_for_signature_box(mode, getattr(ctx, "view_reason", None))]


def not_for_signature_notice(mode: str | None, view_reason: str | None = None) -> str:
    """Begruendung unter "Nicht zur Unterzeichnung" (reiner Text)."""
    normalized = normalize_mode(mode)
    if normalized == "unpublished":
        return _UNPUBLISHED_NOTICE
    headline = draft_headline(normalized, view_reason)
    if normalized == READONLY_VIEW_MODE:
        return f"{headline}. {_VIEW_NOTICE}"
    return f"{headline}. {_DRAFT_NOTICE}" if headline else f"Entwurf. {_DRAFT_NOTICE}"


def not_for_signature_box(mode: str | None, view_reason: str | None = None) -> Table:
    """Ersatz des Unterschriftsblocks fuer jede Nicht-Final-Fassung (N-910-01)."""
    text = (
        f'<font name="{FONT_SERIF_BOLD}" size="13" color="#B91C1C">{NOT_FOR_SIGNATURE_TEXT}</font><br/>'
        f'<font name="{FONT_DEFAULT}" size="9" color="#334155">'
        f"{not_for_signature_notice(mode, view_reason)}</font>"  # feste Texte, kein Markup
    )
    box = Table([[Paragraph(text, make_paragraph_styles()["body"])]], colWidths=[PAGE_SIZE[0] - 24 * mm])
    box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#B91C1C")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return box


def make_unterschrift_section(
    *,
    client_confirm_text: str = CLIENT_CONFIRM_TEXT,
    advisor_confirm_text: str = ADVISOR_CONFIRM_TEXT,
    signature_space_mm: float = 16,
) -> list:
    """Returns Flowables: Section-Title + 2-Spalten-Unterschriftsblock."""
    styles = make_paragraph_styles()
    flowables = [_section_title("Bestätigung & Unterschrift")]

    # Pro Seite: Bestätigung-Text + Spacer für Unterschrift + Labels
    left_col = [
        Paragraph(
            f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#334155">'
            f'{_esc(client_confirm_text)}</font>',
            _para_compact(),
        ),
        Spacer(1, signature_space_mm * mm),  # Platz fuer Unterschrift
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
            f'{_esc(advisor_confirm_text)}</font>',
            _para_compact(),
        ),
        Spacer(1, signature_space_mm * mm),
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
