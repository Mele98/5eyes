"""Disclaimer fuer isolierte Einzel-PDFs."""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer

from services.pdf.components.header import _esc
from services.pdf.styles import FONT_BOLD, FONT_DEFAULT, make_paragraph_styles


ASSET_ALLOCATION_DISCLAIMER = (
    "Diese Asset-Allocation-Uebersicht wurde auf Kundenwunsch als isolierte "
    "Entscheidungsgrundlage erstellt. Sie ersetzt nicht die vollstaendige "
    "Eignungspruefung, das Beratungsprotokoll oder eine unterzeichnete "
    "Vereinbarung. Die Angaben basieren auf den aktuell erfassten Kundendaten "
    "und Annahmen zum Erstellungszeitpunkt. Renditen, Risiken und "
    "Zielerreichung sind nicht garantiert. Entscheidungen oder Abweichungen, "
    "die der Kunde auf dieser Grundlage wuenscht, sind separat zu dokumentieren."
)

PORTFOLIO_DISCLAIMER = (
    "Diese Portfolio-Uebersicht wurde auf Kundenwunsch als isolierte "
    "Umsetzungsuebersicht erstellt. Sie stellt ohne vollstaendige "
    "Eignungspruefung, Beratungsprotokoll und ausdrueckliche "
    "Umsetzungsfreigabe keine verbindliche Transaktionsanweisung dar. "
    "Produktwerte, Kurse, Kosten und Gewichte koennen sich veraendern. "
    "Anlageentscheide, Abweichungen und Ausfuehrungsrisiken auf Kundenwunsch "
    "sind separat zu dokumentieren."
)


def make_single_report_disclaimer(text: str) -> list:
    styles = make_paragraph_styles()
    return [
        Spacer(1, 5 * mm),
        Paragraph(
            f'<font name="{FONT_BOLD}" size="8" color="#475569">Wichtiger Hinweis</font>',
            styles["body"],
        ),
        Paragraph(
            f'<font name="{FONT_DEFAULT}" size="8" color="#64748b">{_esc(text)}</font>',
            styles["small_muted"],
        ),
    ]
