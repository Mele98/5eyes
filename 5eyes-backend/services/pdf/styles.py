"""WealthArchitekten-Designsystem fuer PDF-Dokumente (Sprint 11).

Sprint-11-Anpassung: Farben + Layout an Frontend-PDF-Vorlage
(buildAnlagestrategieDocHtml). A4 LANDSCAPE, dunkler Header, FIDLEG-Footer.
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm


# ---- Page Layout ----
# Sprint 11: A4 LANDSCAPE wie Frontend-Vorlage
PAGE_SIZE = landscape(A4)
MARGIN_TOP = 6 * mm   # weniger Abstand oben — Header ist Voll-Breite
MARGIN_BOTTOM = 12 * mm
MARGIN_LEFT = 12 * mm
MARGIN_RIGHT = 12 * mm

# ---- Colors (WealthArchitekten Brand, aus Frontend uebernommen) ----
COLOR_HEADER_BG = colors.HexColor("#0f172a")   # Dark Slate Header
COLOR_HEADER_TEXT = colors.HexColor("#ffffff")
COLOR_HEADER_SUB = colors.HexColor("#94a3b8")  # Light Gray Subtext

COLOR_PRIMARY = colors.HexColor("#0f172a")     # Identisch Header
COLOR_TEXT = colors.HexColor("#111827")        # Body-Text
COLOR_TEXT_LIGHT = colors.HexColor("#64748b")  # Sekundaer
COLOR_TEXT_MUTED = colors.HexColor("#94a3b8")
COLOR_BORDER = colors.HexColor("#e2e8f0")      # leicht
COLOR_BORDER_STRONG = colors.HexColor("#cbd5e1")
COLOR_TABLE_HEADER_BG = colors.HexColor("#f1f5f9")
COLOR_TABLE_ALT_ROW = colors.HexColor("#f8fafc")
COLOR_METRIC_BG = colors.HexColor("#f8fafc")

# Akzent-Border-Farben fuer Risiko-Metriken
COLOR_BORDER_WARN = colors.HexColor("#fde68a")  # Max DD orange
COLOR_BORDER_DANGER = colors.HexColor("#fecaca")  # VaR 95% rot

# Asset-Bucket-Farben (woertlich aus Frontend buildAnlagestrategieDocHtml)
BUCKET_COLORS = {
    "equities": colors.HexColor("#1e4b8f"),       # dunkelblau
    "bonds": colors.HexColor("#78601a"),          # braun
    "real_estate": colors.HexColor("#2c5080"),    # blaugrau
    "alternatives": colors.HexColor("#4a6080"),   # dunkelgrau
    "liquidity": colors.HexColor("#166534"),      # gruen
}

BUCKET_LABELS_DE = {
    "equities": "Aktien",
    "bonds": "Obligationen",       # Frontend-Wording, nicht 'Anleihen'
    "real_estate": "Immobilien",
    "alternatives": "Alternative",  # ohne 'n' wie Frontend
    "liquidity": "Liquidität",
}

# Goal-Score Farben (aus Frontend goalColor())
GOAL_COLOR_GREEN = colors.HexColor("#166534")    # >=70
GOAL_COLOR_ORANGE = colors.HexColor("#92400e")   # 45-69
GOAL_COLOR_RED = colors.HexColor("#991b1b")      # <45


def goal_color(score: float | int):
    """Returns Farbe basierend auf Score 0-100."""
    s = float(score or 0)
    if s >= 70:
        return GOAL_COLOR_GREEN
    if s >= 45:
        return GOAL_COLOR_ORANGE
    return GOAL_COLOR_RED


# ---- Typography ----
FONT_DEFAULT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"

# Frontend nutzt sehr kompakte Fonts in der Landscape-Variante
FONT_SIZE_TITLE = 24       # Cover-Title
FONT_SIZE_HEADING = 11     # Sektion-Titel (Frontend ~10-11 uppercase)
FONT_SIZE_SUBHEADING = 9.5
FONT_SIZE_BODY = 9.5
FONT_SIZE_TABLE = 8.5
FONT_SIZE_TABLE_HEADER = 7.5
FONT_SIZE_SMALL = 8
FONT_SIZE_METRIC_LABEL = 7.5
FONT_SIZE_METRIC_VALUE = 13
FONT_SIZE_FOOTER = 7


def make_paragraph_styles():
    """Returns dict mit benannten Paragraph-Styles fuer WA-Layout."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "WATitle",
            parent=base["Title"],
            fontName=FONT_BOLD,
            fontSize=FONT_SIZE_TITLE,
            textColor=COLOR_HEADER_TEXT,
            spaceAfter=2 * mm,
            alignment=0,
        ),
        "section_title": ParagraphStyle(
            "WASectionTitle",
            parent=base["Heading2"],
            fontName=FONT_BOLD,
            fontSize=FONT_SIZE_HEADING,
            textColor=COLOR_TEXT_LIGHT,
            spaceBefore=5 * mm,
            spaceAfter=2 * mm,
            # Frontend nutzt uppercase letter-spacing
        ),
        # Backwards-Compat (Sprint 5 nutzt 'heading' fuer Risikoprofil-PDF)
        "heading": ParagraphStyle(
            "WAHeading",
            parent=base["Heading2"],
            fontName=FONT_BOLD,
            fontSize=FONT_SIZE_HEADING,
            textColor=COLOR_PRIMARY,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        ),
        "subheading": ParagraphStyle(
            "WASubheading",
            parent=base["Heading3"],
            fontName=FONT_BOLD,
            fontSize=FONT_SIZE_SUBHEADING,
            textColor=COLOR_TEXT,
            spaceBefore=3 * mm,
            spaceAfter=1.5 * mm,
        ),
        "body": ParagraphStyle(
            "WABody",
            parent=base["BodyText"],
            fontName=FONT_DEFAULT,
            fontSize=FONT_SIZE_BODY,
            textColor=COLOR_TEXT,
            leading=12,
            spaceAfter=2 * mm,
        ),
        "small": ParagraphStyle(
            "WASmall",
            parent=base["BodyText"],
            fontName=FONT_DEFAULT,
            fontSize=FONT_SIZE_SMALL,
            textColor=COLOR_TEXT_LIGHT,
            leading=10,
        ),
        "small_muted": ParagraphStyle(
            "WASmallMuted",
            parent=base["BodyText"],
            fontName=FONT_DEFAULT,
            fontSize=FONT_SIZE_SMALL,
            textColor=COLOR_TEXT_MUTED,
            leading=10,
        ),
        "disclaimer": ParagraphStyle(
            "WADisclaimer",
            parent=base["BodyText"],
            fontName=FONT_DEFAULT,
            fontSize=FONT_SIZE_FOOTER,
            textColor=COLOR_TEXT_MUTED,
            leading=9,
        ),
    }


def asset_class_color(asset_class: str):
    """Returns Bucket-Farbe oder Default-Grau wenn nicht in BUCKET_COLORS."""
    key = str(asset_class or "").strip().lower()
    if key in BUCKET_COLORS:
        return BUCKET_COLORS[key]
    return colors.HexColor("#5a6878")


def asset_class_label(asset_class: str) -> str:
    """Returns deutschen Bucket-Label oder Original-String."""
    key = str(asset_class or "").strip().lower()
    return BUCKET_LABELS_DE.get(key, str(asset_class or ""))
