"""Sprint U-91 (2026-06-06): PDF-Wasserzeichen 'Entwurf' / 'Vertraulich'.

Berater-Tool fuer:
  - **entwurf**: Vor-Druck-Review-Phase. Rotes Wasserzeichen diagonal
    quer ueber die Seite damit ein Druck als Entwurf erkennbar ist.
  - **vertraulich**: Klassifizierungs-Marker fuer FINMA-/Compliance-
    relevante Berichte. Graues horizontales Wasserzeichen am Seitenrand.

Modi:
  - 'entwurf' (rot, diagonal, gross, mittig)
  - 'vertraulich' (grau, horizontal, klein, am Rand)
  - 'none' (kein Wasserzeichen)
"""
from __future__ import annotations

from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas


from core.customer_terms import (  # noqa: F401 -- eine Quelle (H-193), Re-Export
    CONTRACT_DRAFT_TEXT,
    DEPOT_BANK_DRAFT_TEXT,
    FEE_AGREEMENT_DRAFT_TEXT,
    FINAL_MODE,
    READONLY_VIEW_MODE,
    READONLY_VIEW_TEXT,
    UNPUBLISHED_TEXT,
    VORVERTRAG_TEXT,
    WATERMARK_MODES,
    draft_headline,
    is_final_document,
    normalize_mode,
)


def _editorial_bold_font() -> str:
    """Late-binding: liefert den embedded Inter-SemiBold falls registriert,
    sonst Helvetica-Bold als Fallback (Defensive-Pattern wie U-15)."""
    try:
        from services.pdf.fonts import editorial_font_names
        return editorial_font_names().sans_bold
    except Exception:
        return "Helvetica-Bold"  # fallback wenn fonts noch nicht registriert

# Editorial-Tokens (keine knalligen Farben)
_ENTWURF_COLOR = HexColor("#B91C1C")  # gedaempftes Rot (Editorial-Disziplin)
_VERTRAULICH_COLOR = HexColor("#475569")  # gedaempftes Grau


def draw_watermark(
    canvas: Canvas,
    *,
    mode: str,
    page_width: float,
    page_height: float,
    view_reason: str | None = None,
) -> None:
    """Zeichnet das Wasserzeichen auf den Canvas.

    Pflicht canvas.saveState() vorher + canvas.restoreState() nachher
    falls der Caller andere Canvas-Operationen macht. Diese Funktion
    nutzt selbst saveState/restoreState intern.

    Args:
        canvas: ReportLab-Canvas (gilt nur fuer die aktuelle Seite)
        mode: 'none' (final) oder ein Nicht-Final-Modus; Unbekanntes wird gekennzeichnet
        page_width: in points
        page_height: in points
    """
    normalized = normalize_mode(mode)
    if normalized == FINAL_MODE:
        return

    canvas.saveState()
    try:
        if normalized == "entwurf":
            _draw_entwurf_watermark(canvas, page_width, page_height)
        elif normalized == "vertraulich":
            _draw_vertraulich_watermark(canvas, page_width, page_height)
        elif normalized == "vorvertrag":
            _draw_vorvertrag_watermark(canvas, page_width, page_height)
        else:
            _draw_headline_watermark(
                canvas, page_width, page_height, draft_headline(normalized, view_reason),
            )
    finally:
        canvas.restoreState()


def _draw_entwurf_watermark(
    canvas: Canvas, page_width: float, page_height: float,
) -> None:
    """ENTWURF: diagonal, gross, rot, in der Mitte der Seite."""
    canvas.setFillColor(_ENTWURF_COLOR)
    # Helvetica-Bold ist immer verfuegbar (ReportLab-Default)
    canvas.setFont(_editorial_bold_font(), 100)
    # Alpha-Channel fuer transparentes Wasserzeichen (15% Opazitaet)
    try:
        canvas.setFillAlpha(0.15)
    except Exception:
        # Bei aelteren ReportLab-Versionen ohne Alpha-Support: weiter
        pass
    canvas.translate(page_width / 2, page_height / 2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, "ENTWURF")


def _draw_vorvertrag_watermark(
    canvas: Canvas, page_width: float, page_height: float,
) -> None:
    """Entwurf vor Vertragsabschluss: Zeile oben auf jeder Seite + diagonales ENTWURF."""
    _draw_headline_watermark(canvas, page_width, page_height, VORVERTRAG_TEXT)


def _draw_headline_watermark(
    canvas: Canvas, page_width: float, page_height: float, headline: str,
) -> None:
    """Entwurf mit Grund: Zeile oben auf jeder Seite + diagonales ENTWURF."""
    canvas.saveState()
    canvas.setFillColor(_ENTWURF_COLOR)
    canvas.setFont(_editorial_bold_font(), 10)
    canvas.drawCentredString(page_width / 2, page_height - 8 * mm, headline)
    canvas.restoreState()
    _draw_entwurf_watermark(canvas, page_width, page_height)


def _draw_vertraulich_watermark(
    canvas: Canvas, page_width: float, page_height: float,
) -> None:
    """VERTRAULICH: horizontal, klein, grau, am oberen Rand."""
    canvas.setFillColor(_VERTRAULICH_COLOR)
    canvas.setFont(_editorial_bold_font(), 12)
    try:
        canvas.setFillAlpha(0.45)
    except Exception:
        pass
    canvas.drawCentredString(
        page_width / 2,
        page_height - 14 * mm,
        "VERTRAULICH · NICHT WEITERGEBEN",
    )
