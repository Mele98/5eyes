"""Sprint U-P26 PR A — Farbpalette + Paragraph-Styles für den Advisory-Report-PDF.

Eigene Datei statt `services/pdf/styles.py`, weil das Advisory-Report-PDF
einen **anderen Designstil** hat als die existierenden PDFs:
- Anlagestrategie/Depotcheck: A4 Landscape, dark Slate-Header (Cyan/Gray)
- Advisory-Report (dieser PR): A4 Portrait, Editorial Swiss Private
  Banking — Offwhite, tiefes Navy, mattes Petrol als Akzent

Tokens spiegeln 1:1 die Tailwind-Tokens der Reporting-Sub-App
(`5eyes-electron/frontend/reporting/tailwind.config.ts`), damit Berater
identische Anmutung Web vs. Print bekommt.

KEINE Dritt-Marken in Farben/Schriften (Memory-Regel).
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm

from services.pdf.fonts import editorial_font_names, register_editorial_fonts


register_editorial_fonts()
_FONTS = editorial_font_names()


# ---------------------------------------------------------------------------
# Page-Geometrie — A4 Portrait, editoriale Ränder
# ---------------------------------------------------------------------------
PAGE_SIZE = A4
MARGIN_TOP = 25 * mm
MARGIN_BOTTOM = 25 * mm
MARGIN_LEFT = 20 * mm
MARGIN_RIGHT = 20 * mm


# ---------------------------------------------------------------------------
# Farbpalette — identisch zu Tailwind-Tokens der Reporting-Sub-App
# ---------------------------------------------------------------------------
COLOR_CANVAS = colors.HexColor("#FAFAF6")          # Offwhite Body
COLOR_CANVAS_SUBTLE = colors.HexColor("#F4F3EE")   # Section-Background
COLOR_CANVAS_PANEL = colors.HexColor("#FFFFFF")    # Karten

COLOR_INK = colors.HexColor("#0F1C2E")             # tiefes Navy, Body
COLOR_INK_MUTED = colors.HexColor("#3B475A")
COLOR_INK_SUBTLE = colors.HexColor("#6F7A8A")

COLOR_ACCENT = colors.HexColor("#2C5F5F")          # Petrol
COLOR_ACCENT_SUBTLE = colors.HexColor("#7FA5A5")

COLOR_RULE = colors.HexColor("#E5E4DE")            # dünne Trenn-Linien
COLOR_RULE_STRONG = colors.HexColor("#C8C6BD")

COLOR_GOLD = colors.HexColor("#B39455")            # sparsamer Akzent
COLOR_GOLD_SUBTLE = colors.HexColor("#D9C79A")

COLOR_STATUS_GRUEN = colors.HexColor("#4E6F58")
COLOR_STATUS_GELB = colors.HexColor("#B59243")
COLOR_STATUS_ROT = colors.HexColor("#9E4747")
COLOR_STATUS_NEUTRAL = colors.HexColor("#7A8395")


# ---------------------------------------------------------------------------
# Typografie - Editorial-Fonts wie in der Reporting-Sub-App.
# Degraded mode bleibt in services.pdf.fonts zentral auf Stock-Fonts.
# ---------------------------------------------------------------------------
FONT_SERIF = _FONTS.serif
FONT_SERIF_BOLD = _FONTS.serif_bold
FONT_SERIF_ITALIC = _FONTS.serif_italic
FONT_SANS = _FONTS.sans
FONT_SANS_BOLD = _FONTS.sans_bold
FONT_MONO = _FONTS.mono


# Schriftgrößen (Druck-tauglich, editoriale Hierarchie)
FONT_SIZE_DISPLAY = 28
FONT_SIZE_H1 = 20
FONT_SIZE_H2 = 14
FONT_SIZE_H3 = 12
FONT_SIZE_BODY = 10
FONT_SIZE_CAPTION = 9
FONT_SIZE_MICRO = 7


def make_advisory_styles() -> dict[str, ParagraphStyle]:
    """Liefert benannte ParagraphStyles für die Advisory-Report-Sektionen.

    Konvention: alle Style-Namen mit `AR` prefixiert, damit sie nicht mit
    den existierenden `WA*`-Styles aus `pdf/styles.py` kollidieren.
    """
    base = getSampleStyleSheet()
    return {
        "display": ParagraphStyle(
            "ARDisplay",
            parent=base["Title"],
            fontName=FONT_SERIF_BOLD,
            fontSize=FONT_SIZE_DISPLAY,
            textColor=COLOR_INK,
            leading=FONT_SIZE_DISPLAY + 4,
            spaceAfter=4 * mm,
            alignment=0,  # left
        ),
        "h1": ParagraphStyle(
            "ARH1",
            parent=base["Heading1"],
            fontName=FONT_SERIF_BOLD,
            fontSize=FONT_SIZE_H1,
            textColor=COLOR_INK,
            leading=FONT_SIZE_H1 + 4,
            spaceBefore=8 * mm,
            spaceAfter=3 * mm,
        ),
        "h2": ParagraphStyle(
            "ARH2",
            parent=base["Heading2"],
            fontName=FONT_SERIF_BOLD,
            fontSize=FONT_SIZE_H2,
            textColor=COLOR_INK,
            leading=FONT_SIZE_H2 + 3,
            spaceBefore=5 * mm,
            spaceAfter=2 * mm,
        ),
        "h3": ParagraphStyle(
            "ARH3",
            parent=base["Heading3"],
            fontName=FONT_SERIF_ITALIC,
            fontSize=FONT_SIZE_H3,
            textColor=COLOR_INK_MUTED,
            leading=FONT_SIZE_H3 + 3,
            spaceBefore=3 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "ARBody",
            parent=base["BodyText"],
            fontName=FONT_SANS,
            fontSize=FONT_SIZE_BODY,
            textColor=COLOR_INK,
            leading=FONT_SIZE_BODY + 4,
            spaceAfter=2.5 * mm,
        ),
        "body_muted": ParagraphStyle(
            "ARBodyMuted",
            parent=base["BodyText"],
            fontName=FONT_SANS,
            fontSize=FONT_SIZE_BODY,
            textColor=COLOR_INK_MUTED,
            leading=FONT_SIZE_BODY + 4,
            spaceAfter=2.5 * mm,
        ),
        "caption": ParagraphStyle(
            "ARCaption",
            parent=base["BodyText"],
            fontName=FONT_SANS,
            fontSize=FONT_SIZE_CAPTION,
            textColor=COLOR_INK_MUTED,
            leading=FONT_SIZE_CAPTION + 2,
        ),
        "caption_mono": ParagraphStyle(
            "ARCaptionMono",
            parent=base["BodyText"],
            fontName=FONT_MONO,
            fontSize=FONT_SIZE_CAPTION,
            textColor=COLOR_INK_MUTED,
            leading=FONT_SIZE_CAPTION + 2,
        ),
        "micro": ParagraphStyle(
            "ARMicro",
            parent=base["BodyText"],
            fontName=FONT_SANS,
            fontSize=FONT_SIZE_MICRO,
            textColor=COLOR_INK_SUBTLE,
            leading=FONT_SIZE_MICRO + 2,
        ),
        "kicker": ParagraphStyle(
            "ARKicker",
            parent=base["BodyText"],
            fontName=FONT_SANS_BOLD,
            fontSize=FONT_SIZE_MICRO,
            textColor=COLOR_INK_SUBTLE,
            leading=FONT_SIZE_MICRO + 2,
            spaceAfter=2 * mm,
            # ReportLab kennt kein letter-spacing — Kicker mit Spaces
            # zwischen Buchstaben befüllen wenn gewünscht.
        ),
    }
