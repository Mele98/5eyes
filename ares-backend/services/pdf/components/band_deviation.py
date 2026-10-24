"""BAND-DEVIATION-REASON-REQUIRED-001 (Produktentscheid 2026-10-14).

Kundendokument-Block "Abweichung vom Eignungsrahmen des Risikoprofils":
eine Mandatsbandbreite ausserhalb der Hausmatrix-Bandbreite des
Risikoprofils wird dem Kunden mit vereinbarter Bandbreite, Rahmen des
Risikoprofils und der dokumentierten Begruendung offengelegt. Geteilt von
Anlagestrategie-PDF und Beratungsentscheid (Contract-Sign-off), damit beide
Dokumente denselben Wortlaut tragen.
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from services.pdf.components.header import _esc
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    PAGE_SIZE,
)

BAND_DEVIATION_HEADING = "Abweichung vom Eignungsrahmen des Risikoprofils"
MISSING_REASON_TEXT = (
    "Keine Begründung dokumentiert. Ohne dokumentierte Begründung kann die "
    "Empfehlung nicht freigegeben werden."
)


def _pct(bps) -> str:
    return f"{int(bps or 0) / 100:.1f}%"


def _style(name: str, *, bold: bool = False, size: float = 8.5, color=COLOR_TEXT) -> ParagraphStyle:
    return ParagraphStyle(
        name,
        fontName=FONT_BOLD if bold else FONT_DEFAULT,
        fontSize=size,
        leading=size * 1.35,
        textColor=color,
        spaceAfter=0,
    )


def make_band_deviation_section(
    deviations: list | None,
    *,
    profile_label: str | None,
    reason: str | None,
    width: float | None = None,
) -> list:
    """Flowables fuer den Offenlegungsblock; leere Liste ohne Abweichung."""
    rows_in = [d for d in (deviations or []) if isinstance(d, dict)]
    if not rows_in:
        return []
    total_width = width or (PAGE_SIZE[0] - 24 * mm)
    profile = profile_label or "dokumentiertes Risikoprofil"

    title = Paragraph(_esc(BAND_DEVIATION_HEADING), _style("BandDevTitle", bold=True, size=10))
    intro = Paragraph(
        _esc(
            "Für folgende Anlageklassen wurde mit Ihnen eine Bandbreite vereinbart, "
            f"die den Rahmen Ihres Risikoprofils «{profile}» verlässt. Die Allokation "
            "kann sich damit ausserhalb des Eignungsrahmens Ihres Risikoprofils bewegen."
        ),
        _style("BandDevIntro", size=8.5, color=COLOR_TEXT_LIGHT),
    )

    table_rows = [["Anlageklasse", "Vereinbarte Bandbreite", "Rahmen des Risikoprofils"]]
    for deviation in rows_in:
        table_rows.append([
            str(deviation.get("bucket_label") or deviation.get("bucket") or "-"),
            f"{_pct(deviation.get('mandate_min_bps'))} bis {_pct(deviation.get('mandate_max_bps'))}",
            f"{_pct(deviation.get('house_min_bps'))} bis {_pct(deviation.get('house_max_bps'))}",
        ])
    table = Table(
        table_rows,
        colWidths=[(total_width - 20) * f for f in (0.34, 0.33, 0.33)],
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), FONT_DEFAULT),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, COLOR_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    reason_text = (reason or "").strip()
    reason_para = Paragraph(
        f'<font name="{FONT_BOLD}">Begründung: </font>'
        + _esc(reason_text or MISSING_REASON_TEXT),
        _style("BandDevReason", size=8.5),
    )

    panel = Table(
        [[title], [intro], [Spacer(1, 2 * mm)], [table], [Spacer(1, 2 * mm)], [reason_para]],
        colWidths=[total_width],
    )
    panel.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbf4df")),
        ("LINEBEFORE", (0, 0), (0, -1), 2.2, colors.HexColor("#8a6718")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return [Spacer(1, 4 * mm), KeepTogether([panel])]
