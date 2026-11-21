"""Sprint 11: FIDLEG-Footer fuer alle Beratungs-PDFs.

ReportLab onPage-Callback: 8px grauer Disclaimer + Seitenzahl + Audit-Hash.
Sprint 11 ersetzt Sprint-5-Default-Disclaimer durch FIDLEG-konformen Text.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from reportlab.pdfgen.canvas import Canvas

from core.customer_terms import DECISION_NONE_TEXT, decision_footer_label  # noqa: F401 -- CCX P5
from jurisdictions.documents import default_documents
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TEXT_MUTED,
    FONT_DEFAULT,
    FONT_SIZE_FOOTER,
    PAGE_SIZE,
)
from reportlab.lib.units import mm

if TYPE_CHECKING:  # nur Typannotation; zur Laufzeit nicht benoetigt
    from services.pdf.base import PDFContext

# Laenderpaket X3: Der Fusszeilen-Disclaimer kommt aus dem DocumentSet
# (jurisdictions/ch/documents/de-CH/legal.yaml, Schluessel
# ``legal.footer.disclaimer``), byte-gleich zur frueheren Konstante.
# ``FIDLEG_DISCLAIMER`` bleibt als Name fuer bestehende Importe stehen.
FOOTER_DISCLAIMER_KEY = "legal.footer.disclaimer"
FIDLEG_DISCLAIMER = default_documents().text(FOOTER_DISCLAIMER_KEY)

# H7 N-884-03: Fusszeile passend zum Mandatstyp (konsistent mit dem
# Disclaimer je Mandatstyp in static_texts); unbekannt -> neutraler Text.
# Jurisdiktionsneutral formuliert (kein FIDLEG-Hinweis, gilt fuer CH und DE).
_FOOTER_KEYS_BY_MANDATE_TYPE = {
    "vermögensverwaltung": "legal.footer.disclaimer.vermoegensverwaltung",
    "vermoegensverwaltung": "legal.footer.disclaimer.vermoegensverwaltung",
    "anlageberatung": "legal.footer.disclaimer.anlageberatung",
    "finanzplanung": "legal.footer.disclaimer.finanzplanung",
    "reporting only": "legal.footer.disclaimer.reporting",
    # H8 N-890-07: die Kundeninformation (Art. 8/9 FIDLEG) ist ein eigenes,
    # vorvertragliches Dokument (ctx.mandate_type = Dokumenttyp).
    "kundeninformation": "legal.footer.disclaimer.kundeninformation",
}


def footer_disclaimer_key(mandate_type: str | None) -> str:
    key = str(mandate_type or "").strip().casefold()
    return _FOOTER_KEYS_BY_MANDATE_TYPE.get(key, FOOTER_DISCLAIMER_KEY)


# Platz rechts fuer "Seite N" und Obergrenze der Footer-Hoehe: der Rumpf
# endet bei MARGIN_BOTTOM + 12 mm = 24 mm (reportlab_renderer), die oberste
# Disclaimer-Zeile bleibt mit max. 3 Zeilen deutlich darunter.
_PAGE_NUMBER_RESERVE = 22 * mm
_MAX_FOOTER_LINES = 3


def _fit_disclaimer_lines(full_text: str, page_width: float) -> tuple[float, list[str]]:
    """Bricht den vollen Text um; verkleinert die Schrift nur, falls er sonst
    mehr als ``_MAX_FOOTER_LINES`` Zeilen braeuchte. Nie gekuerzt."""
    from reportlab.lib.utils import simpleSplit

    width = page_width - 24 * mm - _PAGE_NUMBER_RESERVE
    size = float(FONT_SIZE_FOOTER)
    lines = simpleSplit(full_text, FONT_DEFAULT, size, width)
    while len(lines) > _MAX_FOOTER_LINES and size > 5.0:
        size -= 0.5
        lines = simpleSplit(full_text, FONT_DEFAULT, size, width)
    return size, lines


# C-890-01 Nachtrag 4 (N-897-12): gleicher Text wie
# services/pdf/components/watermark.py::VORVERTRAG_TEXT (Test prueft Gleichheit).
VORVERTRAG_TEXT = "Entwurf – vor Vertragsabschluss (ohne KYC-Bestätigung)"
# CCX-P4: gleicher Text wie services/pdf/components/watermark.py::UNPUBLISHED_TEXT.
UNPUBLISHED_TEXT = "Entwurf – Soll-Allokation nicht publiziert"
# H-179 V-1: gleicher Text wie services/pdf/components/watermark.py::CONTRACT_DRAFT_TEXT.
CONTRACT_DRAFT_TEXT = "Entwurf – Vertragsvorlage nicht freigegeben"
# N-927-06: gleicher Text wie services/pdf/components/watermark.py::DEPOT_BANK_DRAFT_TEXT.
DEPOT_BANK_DRAFT_TEXT = "Entwurf – Angabe zu Zuwendungen der Depotbank fehlt"


def _draw_vorvertrag_mark(canvas: Canvas, page_width: float, page_height: float,
                          headline: str = VORVERTRAG_TEXT) -> None:
    """Kundenwirksamer Bericht ohne jede KYC-Bestaetigung: Zeile oben auf jeder
    Seite und diagonales ENTWURF (gedaempftes Rot, transparent)."""
    canvas.saveState()
    canvas.setFillColorRGB(0.725, 0.11, 0.11)
    canvas.setFont(FONT_DEFAULT, 10)
    canvas.drawCentredString(page_width / 2, page_height - 8 * mm, headline)
    try:
        canvas.setFillAlpha(0.15)
    except Exception:  # pragma: no cover - aeltere ReportLab-Versionen
        pass
    canvas.setFont(FONT_DEFAULT, 100)
    canvas.translate(page_width / 2, page_height / 2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, "ENTWURF")
    canvas.restoreState()


def make_footer_callback(ctx: PDFContext, disclaimer: str | None = None):
    """Returns onPage-Callback fuer ReportLab-Build.

    Footer-Layout:
        <FIDLEG-Disclaimer>                                 Seite N
    Audit: <hash kurz> · Erstellt am <DATUM>     Erzeugt: YYYY-MM-DD HH:MM
    """
    text = disclaimer if disclaimer is not None else default_documents().text(
        footer_disclaimer_key(getattr(ctx, "mandate_type", None)),
    )
    audit_label = ctx.audit_hash[:12] if ctx.audit_hash else "n/a"
    decision_label = decision_footer_label(getattr(ctx, "decision_ref", None))
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_str = ctx.report_date.strftime("%d.%m.%Y")

    def _draw_footer(canvas: Canvas, doc):
        page_num = canvas.getPageNumber()
        page_width, _ = PAGE_SIZE
        mode = getattr(ctx, "watermark_mode", "none") or "none"
        if mode == "vorvertrag":
            _draw_vorvertrag_mark(canvas, page_width, PAGE_SIZE[1])
        elif mode == "unpublished":
            _draw_vorvertrag_mark(canvas, page_width, PAGE_SIZE[1], UNPUBLISHED_TEXT)
        elif mode == "vertragsvorlage":
            _draw_vorvertrag_mark(canvas, page_width, PAGE_SIZE[1], CONTRACT_DRAFT_TEXT)
        elif mode == "depotbank":
            _draw_vorvertrag_mark(canvas, page_width, PAGE_SIZE[1], DEPOT_BANK_DRAFT_TEXT)

        canvas.saveState()
        canvas.setFont(FONT_DEFAULT, FONT_SIZE_FOOTER)
        canvas.setFillColor(COLOR_TEXT_MUTED)

        # Zeile(n) 1..n: FIDLEG-Disclaimer VOLLSTAENDIG (Pflichttext, nie
        # gekuerzt) + Erstelldatum, umgebrochen auf die Breite links neben der
        # Seitenzahl. Live-Test 2026-11: die fruehere 220-Zeichen-Kuerzung
        # schnitt den Satz "Vergangenheitswerte sind kein verlaesslicher
        # Indikator ..." und "Erstellt am" in jedem Kunden-PDF ab.
        font_size, lines = _fit_disclaimer_lines(
            text + f" Erstellt am {date_str}.", page_width,
        )
        leading = font_size + 1.2
        canvas.setFont(FONT_DEFAULT, font_size)
        base_y = 7 * mm
        for index, line in enumerate(lines):
            y = base_y + (len(lines) - 1 - index) * leading
            canvas.drawString(12 * mm, y, line)
        canvas.setFont(FONT_DEFAULT, FONT_SIZE_FOOTER)
        canvas.drawRightString(page_width - 12 * mm, base_y, f"Seite {page_num}")

        # Trennlinie ueber dem Footer (oberhalb der obersten Disclaimer-Zeile)
        top_y = base_y + (len(lines) - 1) * leading + font_size + 2
        canvas.setStrokeColor(COLOR_BORDER)
        canvas.setLineWidth(0.4)
        canvas.line(12 * mm, max(11 * mm, top_y), page_width - 12 * mm, max(11 * mm, top_y))

        # Zeile 2: Audit-Hash + Beratungsentscheid (CCX P5) + Erzeugt-Zeit
        canvas.drawString(12 * mm, 3.5 * mm, f"Audit: {audit_label}")
        if decision_label:
            canvas.drawCentredString(page_width / 2, 3.5 * mm, decision_label)
        canvas.drawRightString(
            page_width - 12 * mm, 3.5 * mm, f"Erzeugt: {generated_at}"
        )

        canvas.restoreState()

    return _draw_footer
