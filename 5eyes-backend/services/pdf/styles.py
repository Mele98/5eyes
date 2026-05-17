"""5eyes-Designsystem fuer PDF-Dokumente.

Farben + Schriften + Spacings — konsistent ueber alle Dokumente.
Aenderungen hier wirken sich auf alle PDFs aus.
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm


# ---- Page Layout ----
PAGE_SIZE = A4
MARGIN_TOP = 25 * mm
MARGIN_BOTTOM = 25 * mm
MARGIN_LEFT = 20 * mm
MARGIN_RIGHT = 20 * mm

# ---- Colors (5eyes Brand) ----
COLOR_PRIMARY = colors.HexColor("#0B3D91")  # 5eyes-Blau
COLOR_SECONDARY = colors.HexColor("#1F77B4")
COLOR_ACCENT = colors.HexColor("#D67F00")  # Akzent-Orange (z.B. Warnungen)
COLOR_TEXT = colors.HexColor("#222222")
COLOR_TEXT_LIGHT = colors.HexColor("#666666")
COLOR_BORDER = colors.HexColor("#CCCCCC")
COLOR_TABLE_HEADER_BG = colors.HexColor("#F0F4FA")
COLOR_TABLE_ALT_ROW = colors.HexColor("#FAFAFA")

# Asset-Bucket-Farben (konsistent mit Frontend)
BUCKET_COLORS = {
    "equities": colors.HexColor("#1F77B4"),
    "bonds": colors.HexColor("#FF7F0E"),
    "real_estate": colors.HexColor("#2CA02C"),
    "alternatives": colors.HexColor("#9467BD"),
    "liquidity": colors.HexColor("#8C8C8C"),
}

BUCKET_LABELS_DE = {
    "equities": "Aktien",
    "bonds": "Anleihen",
    "real_estate": "Immobilien",
    "alternatives": "Alternative",
    "liquidity": "Liquiditaet",
}

# ---- Typography ----
FONT_DEFAULT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"

FONT_SIZE_TITLE = 18
FONT_SIZE_HEADING = 13
FONT_SIZE_SUBHEADING = 11
FONT_SIZE_BODY = 10
FONT_SIZE_SMALL = 8
FONT_SIZE_FOOTER = 7


def make_paragraph_styles():
    """Returns dict mit benannten Paragraph-Styles."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "5eyesTitle",
            parent=base["Title"],
            fontName=FONT_BOLD,
            fontSize=FONT_SIZE_TITLE,
            textColor=COLOR_PRIMARY,
            spaceAfter=8 * mm,
            alignment=0,  # left
        ),
        "heading": ParagraphStyle(
            "5eyesHeading",
            parent=base["Heading2"],
            fontName=FONT_BOLD,
            fontSize=FONT_SIZE_HEADING,
            textColor=COLOR_PRIMARY,
            spaceBefore=6 * mm,
            spaceAfter=3 * mm,
        ),
        "subheading": ParagraphStyle(
            "5eyesSubheading",
            parent=base["Heading3"],
            fontName=FONT_BOLD,
            fontSize=FONT_SIZE_SUBHEADING,
            textColor=COLOR_TEXT,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "5eyesBody",
            parent=base["BodyText"],
            fontName=FONT_DEFAULT,
            fontSize=FONT_SIZE_BODY,
            textColor=COLOR_TEXT,
            leading=14,
            spaceAfter=3 * mm,
        ),
        "small": ParagraphStyle(
            "5eyesSmall",
            parent=base["BodyText"],
            fontName=FONT_DEFAULT,
            fontSize=FONT_SIZE_SMALL,
            textColor=COLOR_TEXT_LIGHT,
            leading=10,
        ),
        "disclaimer": ParagraphStyle(
            "5eyesDisclaimer",
            parent=base["BodyText"],
            fontName=FONT_ITALIC,
            fontSize=FONT_SIZE_SMALL,
            textColor=COLOR_TEXT_LIGHT,
            leading=10,
            spaceBefore=4 * mm,
        ),
    }
