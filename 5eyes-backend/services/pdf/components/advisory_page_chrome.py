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
from zoneinfo import ZoneInfo

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from services.pdf.fonts import register_editorial_fonts

# Sprint U-27 (Roadmap-Punkt 27, 2026-05-31): Berater-Datum im PDF muss
# Europa/Zurich sein, nicht UTC. Vorher: `2026-05-26T14:32:00Z` ->
# `26.05.2026 14:32` (= UTC dargestellt als Schweizer-Format = falsch).
# Nachher: konvertiert via zoneinfo, im Sommer +2h, im Winter +1h.
# FINMA-relevant: Berater-Sichtbares Datum auf Berichts-Artefakten muss
# der lokalen Geschaeftszeit entsprechen, sonst Audit-Confusion.
SWISS_TZ = ZoneInfo("Europe/Zurich")

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
# Sprint U-91 (2026-06-06): Wasserzeichen-Helper
from services.pdf.components.watermark import draw_watermark


register_editorial_fonts()


class AdvisoryNumberedCanvas(Canvas):
    """Canvas that draws advisory chrome after the final page count is known."""

    def __init__(
        self,
        *args,
        mandate_number: str,
        generated_at_iso: str,
        watermark_mode: str = "none",
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, object]] = []
        self._advisory_mandate_number = str(mandate_number or "—")
        self._advisory_generated_at = _format_swiss_datetime(generated_at_iso)
        # Sprint U-91 (2026-06-06): Wasserzeichen-Modus
        self._advisory_watermark_mode = str(watermark_mode or "none").strip().lower()

    def showPage(self) -> None:  # noqa: N802 - ReportLab API name
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        saved_states = self._saved_page_states
        total_pages = len(saved_states)
        if total_pages <= 0:
            super().save()
            return

        for state in saved_states:
            self.__dict__.update(state)
            _draw_advisory_page_chrome(
                self,
                page_number=int(self.getPageNumber()),
                total_pages=total_pages,
                mandate_number=self._advisory_mandate_number,
                generated_at_pretty=self._advisory_generated_at,
            )
            # Sprint U-91 (2026-06-06): Wasserzeichen ueber alle Seiten
            # (auch Cover) — Berater erkennt Entwurf/Vertraulich auf jeder
            # ausgedruckten Seite.
            page_width, page_height = PAGE_SIZE
            draw_watermark(
                self,
                mode=self._advisory_watermark_mode,
                page_width=page_width,
                page_height=page_height,
            )
            Canvas.showPage(self)
        Canvas.save(self)


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
        Optional. Wenn None, schreiben wir nur „Seite x" ohne „/ N".
        Der Advisory-Report nutzt im Normalfall `AdvisoryNumberedCanvas`,
        damit die Gesamt-Seitenzahl ohne separaten Zähl-Render bekannt ist.
    """
    pretty_dt = _format_swiss_datetime(generated_at_iso)
    safe_mandate = str(mandate_number or "—")

    def draw(canvas: Canvas, doc) -> None:
        _draw_advisory_page_chrome(
            canvas,
            page_number=int(doc.page),
            total_pages=total_pages_hint,
            mandate_number=safe_mandate,
            generated_at_pretty=pretty_dt,
        )

    return draw


def _draw_advisory_page_chrome(
    canvas: Canvas,
    *,
    page_number: int,
    total_pages: int | None,
    mandate_number: str,
    generated_at_pretty: str,
) -> None:
    if page_number == 1:
        return

    page_width, page_height = PAGE_SIZE
    canvas.saveState()

    header_y = page_height - MARGIN_TOP + 8 * mm
    canvas.setFillColor(COLOR_INK)
    canvas.setFont(FONT_SANS_BOLD, FONT_SIZE_MICRO + 1)
    canvas.drawString(MARGIN_LEFT, header_y, "5eyes")

    canvas.setFillColor(COLOR_INK_SUBTLE)
    canvas.setFont(FONT_SANS, FONT_SIZE_MICRO)
    canvas.drawString(
        MARGIN_LEFT + 16 * mm,
        header_y,
        f"Wealth Architects  ·  Depotcheck  ·  {mandate_number}",
    )

    if total_pages:
        page_label = f"Seite {page_number} / {int(total_pages)}"
    else:
        page_label = f"Seite {page_number}"
    canvas.drawRightString(page_width - MARGIN_RIGHT, header_y, page_label)

    rule_y = page_height - MARGIN_TOP + 3 * mm
    canvas.setStrokeColor(COLOR_RULE)
    canvas.setLineWidth(0.3)
    canvas.line(
        MARGIN_LEFT,
        rule_y,
        page_width - MARGIN_RIGHT,
        rule_y,
    )

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
        f"Vertraulich  ·  Generiert {generated_at_pretty}",
    )
    canvas.drawRightString(
        page_width - MARGIN_RIGHT, footer_y, "5eyes Advisory Report"
    )

    canvas.restoreState()


def _format_swiss_datetime(iso: str) -> str:
    """Formatiert ISO-Timestamp → `26.05.2026 16:32` in Europa/Zurich.

    Beispiel (U-27 Bugfix):
      `2026-05-26T14:32:00.000Z` (UTC) → `26.05.2026 16:32` (CEST Sommerzeit)
      `2026-12-26T14:32:00.000Z` (UTC) → `26.12.2026 15:32` (CET Winterzeit)

    Aware Datetimes (mit Z oder +HH:MM) werden via zoneinfo auf
    Europa/Zurich umgerechnet. Naive Datetimes (kein TZ-Suffix) werden
    1:1 formatiert — Annahme: bereits lokal (Backwards-Compat zu
    Tests, die nackte ISO-Strings übergeben).

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
    if dt.tzinfo is not None:
        # Aware: konvertiere nach Europa/Zurich
        dt = dt.astimezone(SWISS_TZ)
    # Naive bleibt naive — wird 1:1 formatiert.
    return dt.strftime("%d.%m.%Y %H:%M")
