"""Footer-Komponente fuer 5eyes-PDFs.

ReportLab nutzt onPage-Callbacks fuer Header/Footer auf JEDER Seite.
make_footer_callback liefert eine Funktion die als doc.build(onLaterPages=...)
benutzt wird.
"""
from __future__ import annotations

from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from services.pdf.base import PDFContext
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TEXT_LIGHT,
    FONT_DEFAULT,
    FONT_SIZE_FOOTER,
    PAGE_SIZE,
)


def make_footer_callback(ctx: PDFContext, disclaimer: str | None = None):
    """Returns onPage-Callback fuer ReportLab-Build.

    Footer-Layout (3-spaltig):
        <disclaimer>                                   Seite N / M
    Audit: <hash kurz>                          Erzeugt: YYYY-MM-DD HH:MM
    """
    default_disclaimer = (
        "Schaetzwerte fuer Planungszwecke. Keine Steuer- oder Anlageberatung."
    )
    text = disclaimer if disclaimer is not None else default_disclaimer
    audit_label = ctx.audit_hash[:12] if ctx.audit_hash else "n/a"
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    def _draw_footer(canvas: Canvas, doc):
        page_num = canvas.getPageNumber()
        page_width, _ = PAGE_SIZE

        canvas.saveState()
        canvas.setFont(FONT_DEFAULT, FONT_SIZE_FOOTER)
        canvas.setFillColor(COLOR_TEXT_LIGHT)

        # Trennlinie ueber dem Footer
        canvas.setStrokeColor(COLOR_BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(20 * mm, 18 * mm, page_width - 20 * mm, 18 * mm)

        # Zeile 1: Disclaimer (links) + Seitenzahl (rechts)
        canvas.drawString(20 * mm, 13 * mm, text[:120])
        canvas.drawRightString(
            page_width - 20 * mm, 13 * mm, f"Seite {page_num}"
        )

        # Zeile 2: Audit-Hash (links) + Erzeugungs-Zeit (rechts)
        canvas.drawString(20 * mm, 8 * mm, f"Audit: {audit_label}")
        canvas.drawRightString(
            page_width - 20 * mm, 8 * mm, f"Erzeugt: {generated_at}"
        )

        canvas.restoreState()

    return _draw_footer
