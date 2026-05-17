"""Sprint 11: FIDLEG-Footer fuer alle WealthArchitekten-PDFs.

ReportLab onPage-Callback: 8px grauer Disclaimer + Seitenzahl + Audit-Hash.
Sprint 11 ersetzt Sprint-5-Default-Disclaimer durch FIDLEG-konformen Text.
"""
from __future__ import annotations

from datetime import datetime

from reportlab.pdfgen.canvas import Canvas

from services.pdf.base import PDFContext
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TEXT_MUTED,
    FONT_DEFAULT,
    FONT_SIZE_FOOTER,
    PAGE_SIZE,
)
from reportlab.lib.units import mm

# Sprint 11: FIDLEG-Disclaimer (woertlich aus Frontend-Vorlage)
FIDLEG_DISCLAIMER = (
    "Dieses Dokument wurde in Übereinstimmung mit dem Bundesgesetz über die "
    "Finanzdienstleistungen (FIDLEG) erstellt. Es dient der Dokumentation der "
    "Anlageberatung und stellt keine Garantie für Anlageergebnisse dar. "
    "Vergangenheitswerte sind kein verlässlicher Indikator für zukünftige Ergebnisse."
)


def make_footer_callback(ctx: PDFContext, disclaimer: str | None = None):
    """Returns onPage-Callback fuer ReportLab-Build.

    Footer-Layout:
        <FIDLEG-Disclaimer>                                 Seite N
    Audit: <hash kurz> · Erstellt am <DATUM>     Erzeugt: YYYY-MM-DD HH:MM
    """
    text = disclaimer if disclaimer is not None else FIDLEG_DISCLAIMER
    audit_label = ctx.audit_hash[:12] if ctx.audit_hash else "n/a"
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_str = ctx.report_date.strftime("%d.%m.%Y")

    def _draw_footer(canvas: Canvas, doc):
        page_num = canvas.getPageNumber()
        page_width, _ = PAGE_SIZE

        canvas.saveState()
        canvas.setFont(FONT_DEFAULT, FONT_SIZE_FOOTER)
        canvas.setFillColor(COLOR_TEXT_MUTED)

        # Trennlinie ueber dem Footer
        canvas.setStrokeColor(COLOR_BORDER)
        canvas.setLineWidth(0.4)
        canvas.line(12 * mm, 11 * mm, page_width - 12 * mm, 11 * mm)

        # Zeile 1: FIDLEG-Disclaimer (links, max 80% Breite) + Seitenzahl (rechts)
        max_chars = 220
        disclaimer_line = text + f" Erstellt am {date_str}."
        if len(disclaimer_line) > max_chars:
            disclaimer_line = disclaimer_line[:max_chars - 3] + "..."
        canvas.drawString(12 * mm, 7 * mm, disclaimer_line)
        canvas.drawRightString(page_width - 12 * mm, 7 * mm, f"Seite {page_num}")

        # Zeile 2: Audit-Hash + Erzeugt-Zeit
        canvas.drawString(12 * mm, 3.5 * mm, f"Audit: {audit_label}")
        canvas.drawRightString(
            page_width - 12 * mm, 3.5 * mm, f"Erzeugt: {generated_at}"
        )

        canvas.restoreState()

    return _draw_footer
