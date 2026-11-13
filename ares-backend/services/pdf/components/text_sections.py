"""Sprint 14: Text-Sektionen — Investitionsansatz, Anlageuniversum,
Zusammenfassung, Kennzahlen-Erlaeuterungen, Disclaimer.

Erzeugt PageBreak-getrennte Sektionen mit den statischen Texten aus
static_texts.py (woertlich aus User-Vorlage).
"""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, Spacer

from services.pdf.components.header import _esc
from services.pdf.components.static_texts import (
    ANLAGEUNIVERSUM_BULLETS,
    ANLAGEUNIVERSUM_INTRO,
    ANLAGEUNIVERSUM_OUTRO,
    ANLAGEUNIVERSUM_TITLE,
    DISCLAIMER_TEXT,
    DISCLAIMER_TITLE,
    INVESTITIONSANSATZ_TEXT,
    INVESTITIONSANSATZ_TITLE,
    KENNZAHLEN_DEFINITIONS,
    KENNZAHLEN_TITLE,
    ZUSAMMENFASSUNG_TEXT,
    ZUSAMMENFASSUNG_TITLE,
)
from services.pdf.styles import (
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_BODY,
    make_paragraph_styles,
)


def make_investitionsansatz_section() -> list:
    return _make_text_section(INVESTITIONSANSATZ_TITLE, INVESTITIONSANSATZ_TEXT)


def make_anlageuniversum_section(currency: str = "CHF") -> list:
    # N-894-10: Referenzwaehrung = Mandatswaehrung (Dokument reicht ctx.base_currency).
    ccy = str(currency or "CHF").upper().strip() or "CHF"
    styles = make_paragraph_styles()
    flowables = [_section_heading(ANLAGEUNIVERSUM_TITLE)]

    # Intro-Absatz
    flowables.append(Paragraph(
        _body_xml(ANLAGEUNIVERSUM_INTRO),
        styles["body"],
    ))
    flowables.append(Spacer(1, 2 * mm))

    # Bullets
    for bullet in ANLAGEUNIVERSUM_BULLETS:
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#334155">'
            f'• {_esc(bullet)}</font>',
            styles["body"],
        ))

    flowables.append(Spacer(1, 2 * mm))

    # Outro-Absaetze
    for para in ANLAGEUNIVERSUM_OUTRO:
        flowables.append(Paragraph(_body_xml(para.replace("{currency}", ccy)), styles["body"]))

    return flowables


def make_zusammenfassung_section() -> list:
    return _make_text_section(ZUSAMMENFASSUNG_TITLE, ZUSAMMENFASSUNG_TEXT)


def make_kennzahlen_erlaeuterungen_section() -> list:
    """7 Definitionen — kompakte Beschreibungs-Liste."""
    styles = make_paragraph_styles()
    flowables = [_section_heading(KENNZAHLEN_TITLE)]
    for label, definition in KENNZAHLEN_DEFINITIONS:
        flowables.append(KeepTogether([
            Paragraph(
                f'<font name="{FONT_BOLD}" size="{FONT_SIZE_BODY}" color="#0f172a">'
                f'{_esc(label)}:</font>',
                styles["body"],
            ),
            Paragraph(_body_xml(definition), styles["body"]),
            Spacer(1, 2 * mm),
        ]))
    return flowables


def make_disclaimer_section() -> list:
    return _make_text_section(DISCLAIMER_TITLE, DISCLAIMER_TEXT, small=True)


# ---- Helpers ----

def _make_text_section(title: str, paragraphs: list[str], *, small: bool = False) -> list:
    styles = make_paragraph_styles()
    flowables = [_section_heading(title)]
    style_name = "small" if small else "body"
    for para in paragraphs:
        flowables.append(Paragraph(_body_xml(para, small=small), styles[style_name]))
    return flowables


def _section_heading(text: str):
    """N-877-01: Abschnittstitel nur als Text -- Emoji (U+2139+FE0F) sind in
    keinem eingebetteten Font enthalten und erschienen als leere Kaesten."""
    style = make_paragraph_styles()["section_title"]
    # Plus etwas mehr Space oben damit Sektion sichtbar getrennt
    return Paragraph(
        f'<font name="{FONT_BOLD}" size="13" color="#0f172a">'
        f'{_esc(text)}</font>',
        style,
    )


def _body_xml(text: str, *, small: bool = False) -> str:
    size = 8 if small else FONT_SIZE_BODY
    color = "#475569" if small else "#334155"
    return (
        f'<font name="{FONT_DEFAULT}" size="{size}" color="{color}">'
        f'{_esc(text)}</font>'
    )
