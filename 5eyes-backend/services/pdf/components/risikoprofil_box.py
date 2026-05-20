"""Sprint 11: Risikoprofil-Box mit grossem Score + Detail-Metrics.

Frontend-Vorlage:
    [Score X / 10]   [Risikoprofil: <Label>]
                     [Anlagehorizont: X Jahre]
                     [Mandat: <Typ>]
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from services.pdf.components.header import _esc
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_METRIC_BG,
    COLOR_PRIMARY,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_HEADING,
    PAGE_SIZE,
    make_paragraph_styles,
)


def make_risikoprofil_box(
    *,
    score_x10: int | None,
    profile_label: str | None,
    horizon_years: int | None,
    mandate_type: str | None,
    is_overridden: bool = False,
    override_reason: str | None = None,
) -> list:
    """Returns Flowables: Section-Title + Risikoprofil-Box ohne interne Punkte."""
    if score_x10 is None and not profile_label:
        return []

    styles = make_paragraph_styles()
    flowables = [_section_title("Risikoprofil")]

    page_width, _ = PAGE_SIZE
    box_width = page_width - 24 * mm

    left_content = []
    if profile_label:
        left_content.append(Paragraph(
            f'<para align="center"><font name="{FONT_DEFAULT}" size="7" color="#64748b">'
            f'RISIKOPROFIL</font></para>',
            _para_size(7, after=2),
        ))
        left_content.append(Paragraph(
            f'<para align="center"><font name="{FONT_BOLD}" size="16" color="#0f172a">'
            f'{_esc(profile_label)}</font></para>',
            _para_size(16, after=0),
        ))
    else:
        left_content.append(Paragraph(
            '<para align="center"><font name="Helvetica-Bold" size="12" color="#64748b">'
            'Nicht definiert</font></para>',
            _para_size(12, after=0),
        ))

    right_content = []
    if horizon_years:
        right_content.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="7" color="#64748b">ANLAGEHORIZONT</font>',
            _para_size(7, after=1),
        ))
        right_content.append(Paragraph(
            f'<font name="{FONT_BOLD}" size="11" color="#0f172a">{horizon_years} Jahre</font>',
            _para_size(11, after=4),
        ))
    if mandate_type:
        right_content.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="7" color="#64748b">MANDAT</font>',
            _para_size(7, after=1),
        ))
        right_content.append(Paragraph(
            f'<font name="{FONT_BOLD}" size="11" color="#0f172a">{_esc(mandate_type)}</font>',
            _para_size(11, after=4 if is_overridden else 0),
        ))
    if is_overridden:
        reason = (override_reason or "").strip()
        note = "Das Risikoprofil wurde manuell uebersteuert."
        if reason:
            note += f" Begruendung: {reason}"
        right_content.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="7" color="#64748b">MANUELLE UEBERSTEUERUNG</font>',
            _para_size(7, after=1),
        ))
        right_content.append(Paragraph(
            f'<font name="{FONT_BOLD}" size="9" color="#92400e">{_esc(note)}</font>',
            _para_size(9, after=0),
        ))

    composite = Table(
        [[left_content, right_content]],
        colWidths=[58 * mm, box_width - 58 * mm],
    )
    composite.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_METRIC_BG),
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("LINEAFTER", (0, 0), (0, -1), 0.5, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    flowables.append(composite)
    return flowables


def _section_title(text: str):
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        f'<font color="#475569" size="9"><b>{_esc(text).upper()}</b></font>',
        style,
    )


def _para_style_compact(line_after: float = 0):
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "RpBoxLine",
        fontName=FONT_DEFAULT,
        fontSize=9,
        leading=11,
        spaceAfter=line_after,
    )


def _para_size(size: int, *, after: float = 0):
    """Sprint 14 Phase 3: leading=~1.25x fontSize sonst Overlap."""
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        f"RpBoxSize{size}",
        fontName=FONT_DEFAULT,
        fontSize=size,
        leading=max(size * 1.25, 9),
        spaceAfter=after,
    )
