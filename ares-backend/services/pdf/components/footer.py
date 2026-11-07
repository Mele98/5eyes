"""Sprint 11: FIDLEG-Footer fuer alle Beratungs-PDFs.

ReportLab onPage-Callback: 8px grauer Disclaimer + Seitenzahl + Audit-Hash.
Sprint 11 ersetzt Sprint-5-Default-Disclaimer durch FIDLEG-konformen Text.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from reportlab.pdfgen.canvas import Canvas

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


def make_footer_callback(ctx: PDFContext, disclaimer: str | None = None):
    """Returns onPage-Callback fuer ReportLab-Build.

    Footer-Layout:
        <FIDLEG-Disclaimer>                                 Seite N
    Audit: <hash kurz> · Erstellt am <DATUM>     Erzeugt: YYYY-MM-DD HH:MM
    """
    text = disclaimer if disclaimer is not None else default_documents().text(FOOTER_DISCLAIMER_KEY)
    audit_label = ctx.audit_hash[:12] if ctx.audit_hash else "n/a"
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_str = ctx.report_date.strftime("%d.%m.%Y")

    def _draw_footer(canvas: Canvas, doc):
        page_num = canvas.getPageNumber()
        page_width, _ = PAGE_SIZE

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

        # Zeile 2: Audit-Hash + Erzeugt-Zeit
        canvas.drawString(12 * mm, 3.5 * mm, f"Audit: {audit_label}")
        canvas.drawRightString(
            page_width - 12 * mm, 3.5 * mm, f"Erzeugt: {generated_at}"
        )

        canvas.restoreState()

    return _draw_footer
