"""Sprint U-P26 PR A — Seitenrahmen für den Advisory-Report-PDF.

Liefert einen ReportLab-Page-Callback (`make_advisory_page_chrome`), der
für jede Seite **außer dem Cover** den editorialen Page-Header und
Page-Footer zeichnet:

  Header oben:  „5eyes  ·  Wealth Architects   ·   Depotcheck · MX-XYZ"
                                                              „Seite x / 15"
  Footer unten: „Vertraulich · Generiert dd.mm.yyyy hh:mm    „5eyes v…"

Cover (Seite 1) wird über `cover_only_callback` gesondert ohne Header
gerendert, damit das Titelblatt ungestört bleibt.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from services.pdf.components.advisory_palette import (
    COLOR_INK,
    COLOR_INK_SUBTLE,
    COLOR_RULE,
    FONT_SANS,
    FONT_SANS_BOLD,
    FONT_SIZE_MICRO,
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    PAGE_SIZE,
)


def make_advisory_page_chrome(
    *,
    mandate_number: str,
    generated_at_iso: str,
    total_pages_hint: int | None = None,
) -> Callable[[Canvas, object], None]:
    """Liefert einen Page-Callback (signature: canvas, doc) für ReportLab.

    Parameter
    ---------
    mandate_number
        Mandat-Identifikator für den Header (z. B. `MX-FOUNDATION-01`).
    generated_at_iso
        ISO-Zeitstempel `YYYY-MM-DDTHH:MM:SS.SSSZ`, kommt aus dem Aggregator.
    total_pages_hint
        Optional. Wenn None, schreiben wir nur „Seite x" ohne „/ N",
        weil ReportLab in einem Pass die Gesamt-Seitenzahl noch nicht
        kennt (würde Two-Pass-Build verlangen — TODO Folge-PR).
    """
    page_width, page_height = PAGE_SIZE
    pretty_dt = _format_swiss_datetime(generated_at_iso)
    safe_mandate = str(mandate_number or "—")

    def draw(canvas: Canvas, doc) -> None:
        # Cover-Seite ist Seite 1 → kein Header/Footer dort
        if int(doc.page) == 1:
            return

        canvas.saveState()

        # Header — oben editorial mit dünner Trenn-Linie
        header_y = page_height - MARGIN_TOP + 8 * mm
        canvas.setFillColor(COLOR_INK)
        canvas.setFont(FONT_SANS_BOLD, FONT_SIZE_MICRO + 1)
        canvas.drawString(MARGIN_LEFT, header_y, "5eyes")

        canvas.setFillColor(COLOR_INK_SUBTLE)
        canvas.setFont(FONT_SANS, FONT_SIZE_MICRO)
        canvas.drawString(
            MARGIN_LEFT + 16 * mm,
            header_y,
            f"Wealth Architects  ·  Depotcheck  ·  {safe_mandate}",
        )

        # Seitenzahl rechts
        if total_pages_hint:
            page_label = f"Seite {int(doc.page)} / {int(total_pages_hint)}"
        else:
            page_label = f"Seite {int(doc.page)}"
        canvas.drawRightString(page_width - MARGIN_RIGHT, header_y, page_label)

        # dünne Trenn-Linie unter Header
        rule_y = page_height - MARGIN_TOP + 3 * mm
        canvas.setStrokeColor(COLOR_RULE)
        canvas.setLineWidth(0.3)
        canvas.line(
            MARGIN_LEFT,
            rule_y,
            page_width - MARGIN_RIGHT,
            rule_y,
        )

        # Footer — unten mit Trenn-Linie + zwei Texten
        footer_y = MARGIN_BOTTOM - 8 * mm
        canvas.setStrokeColor(COLOR_RULE)
        canvas.line(
            MARGIN_LEFT,
            MARGIN_BOTTOM - 4 * mm,
            page_width - MARGIN_RIGHT,
            MARGIN_BOTTOM - 4 * mm,
        )
        canvas.setFillColor(COLOR_INK_SUBTLE)
        canvas.setFont(FONT_SANS, FONT_SIZE_MICRO)
        canvas.drawString(
            MARGIN_LEFT,
            footer_y,
            f"Vertraulich  ·  Generiert {pretty_dt}",
        )
        canvas.drawRightString(
            page_width - MARGIN_RIGHT, footer_y, "5eyes Advisory Report"
        )

        canvas.restoreState()

    return draw


def _format_swiss_datetime(iso: str) -> str:
    """Formatiert `2026-05-26T14:32:00.000Z` → `26.05.2026 14:32` (CH-Format).

    Robust gegen unerwartete Formate — Fallback ist ein 'Datum unbekannt'.
    """
    if not iso:
        return "—"
    try:
        # ISO mit Z → fromisoformat braucht +00:00
        normalized = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return iso
    return dt.strftime("%d.%m.%Y %H:%M")
