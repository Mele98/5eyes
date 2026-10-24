"""Sprint U-P26 PR D — IST/SOLL-Bar-Chart als reusable Component.

Editorialer Stil: dünne, gleichlange Bar-Spuren mit prozentualem Fill.
IST-Bar und SOLL-Bar pro Position untereinander, Drift rechts daneben.

Beispiel-Layout pro Position:

    Aktien
       IST   ████████░░░░░░░░░░░  25.0 %
       SOLL  ███████████░░░░░░░░  35.0 %
                                          Drift  −10.0 %

Wird in PDF-Sektionen 8 (Asset Allocation), 9 (Risikowährungen) und
10 (Branchen) wiederverwendet — die Daten-Strukturen sind dort identisch
(items mit label/ist_bps/soll_bps/drift_bps).
"""
from __future__ import annotations

from typing import Sequence

from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from services.pdf.components.advisory_palette import (
    COLOR_ACCENT,
    COLOR_ACCENT_SUBTLE,
    COLOR_CANVAS_SUBTLE,
    COLOR_INK,
    COLOR_INK_MUTED,
    COLOR_INK_SUBTLE,
    COLOR_RULE,
    COLOR_STATUS_GRUEN,
    COLOR_STATUS_NEUTRAL,
    COLOR_STATUS_ROT,
    FONT_MONO,
    FONT_SANS,
    FONT_SANS_BOLD,
    FONT_SIZE_BODY,
    FONT_SIZE_CAPTION,
    FONT_SIZE_MICRO,
)
from services.pdf.components.swiss_numbers import (
    format_bps_as_pct,
    format_bps_signed_pct,
)


# Höhen für die einzelnen Bar-Strips (in Punkten, ReportLab-Default-Unit)
_BAR_HEIGHT_PT = 5.0
_BAR_BG_FILL = colors.HexColor("#EFEEE8")  # leicht dunkler als canvas-subtle


def make_bar_chart_ist_soll(
    items: Sequence[dict],
    *,
    inner_width_pt: float,
    show_bands: bool = False,
    drift_threshold_bps: int = 1500,
) -> Table:
    """Erzeugt eine Tabelle mit IST/SOLL-Bars + Drift pro Item.

    Parameter
    ---------
    items
        Liste von Dicts mit Schlüsseln `label`, `ist_bps`, `soll_bps`,
        `drift_bps`. Optional `band_min_bps`/`band_max_bps` (wenn
        `show_bands=True` werden sie als hellere Schicht hinter SOLL
        gezeichnet — Indikator für die Toleranzbänder).
    inner_width_pt
        Innere Breite der Tabelle in Punkten — die Bars werden
        proportional in diese Breite eingezeichnet.
    drift_threshold_bps
        Drift-Wert in bps ab dem die Drift-Anzeige rot eingefärbt wird
        (Standard 1500 = 15 %, gleicher Default wie depot_check).
    """
    label_col = inner_width_pt * 0.18
    bars_col = inner_width_pt * 0.60
    drift_col = inner_width_pt - label_col - bars_col

    bar_max_width = bars_col - 12  # 6pt padding links/rechts

    rows = []
    for it in items:
        label = str(it.get("label") or "—")
        ist_bps = int(it.get("ist_bps", 0) or 0)
        soll_bps = int(it.get("soll_bps", 0) or 0)
        drift_bps = int(it.get("drift_bps", ist_bps - soll_bps))
        band_min = it.get("band_min_bps") if show_bands else None
        band_max = it.get("band_max_bps") if show_bands else None

        label_cell = _label_cell(label)
        bars_cell = _bars_cell(
            ist_bps=ist_bps,
            soll_bps=soll_bps,
            bar_max_width=bar_max_width,
            band_min_bps=band_min if isinstance(band_min, (int, float)) else None,
            band_max_bps=band_max if isinstance(band_max, (int, float)) else None,
        )
        drift_cell = _drift_cell(drift_bps, drift_threshold_bps)
        rows.append([label_cell, bars_cell, drift_cell])

    table = Table(rows, colWidths=[label_col, bars_col, drift_col])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.2, COLOR_RULE),
    ]))
    return table


def _label_cell(label: str) -> Paragraph:
    return Paragraph(
        _escape(label),
        _paragraph_style(
            "BarChartLabel",
            font=FONT_SANS_BOLD,
            size=FONT_SIZE_CAPTION,
            color=COLOR_INK,
            leading=FONT_SIZE_CAPTION + 2,
        ),
    )


def _drift_cell(drift_bps: int, threshold_bps: int) -> Paragraph:
    """Mono-Font, Vorzeichen, Threshold-basierte Farbe."""
    if abs(drift_bps) >= threshold_bps:
        col = COLOR_STATUS_ROT
    elif abs(drift_bps) >= threshold_bps // 2:
        col = COLOR_STATUS_NEUTRAL
    else:
        col = COLOR_STATUS_GRUEN
    return Paragraph(
        format_bps_signed_pct(drift_bps),
        _paragraph_style(
            "BarChartDrift",
            font=FONT_MONO,
            size=FONT_SIZE_CAPTION,
            color=col,
        ),
    )


def _bars_cell(
    *,
    ist_bps: int,
    soll_bps: int,
    bar_max_width: float,
    band_min_bps: float | None = None,
    band_max_bps: float | None = None,
) -> Drawing:
    """Zwei Bar-Spuren mit Annotationen, gezeichnet als ReportLab-Drawing.

    Layout (von oben nach unten):
      IST  [filled bar]  N.N %
      SOLL [filled bar]  N.N %  (mit Band als hellere Schicht falls vorhanden)
    """
    # Höhe = 2 Bars × 5pt + 4pt padding zwischen ihnen + label-text-height
    total_height = (_BAR_HEIGHT_PT * 2) + 4 + 12
    drawing = Drawing(bar_max_width + 50, total_height)

    # IST-Bar (oben)
    ist_y = total_height - 12 - _BAR_HEIGHT_PT
    _draw_bar(
        drawing, y=ist_y, width=bar_max_width, fill_bps=ist_bps,
        fill_color=COLOR_ACCENT,
        label_text=f"IST  {format_bps_as_pct(ist_bps)}",
        label_y_offset=ist_y + _BAR_HEIGHT_PT + 1,
        text_color=COLOR_INK_MUTED,
    )
    # SOLL-Bar (unten)
    soll_y = ist_y - 2 - _BAR_HEIGHT_PT
    if band_min_bps is not None and band_max_bps is not None:
        _draw_band_overlay(
            drawing, y=soll_y, width=bar_max_width,
            min_bps=int(band_min_bps), max_bps=int(band_max_bps),
        )
    _draw_bar(
        drawing, y=soll_y, width=bar_max_width, fill_bps=soll_bps,
        fill_color=COLOR_ACCENT_SUBTLE,
        label_text=f"SOLL {format_bps_as_pct(soll_bps)}",
        label_y_offset=soll_y - 10,
        text_color=COLOR_INK_SUBTLE,
    )
    return drawing


def _draw_bar(
    drawing: Drawing,
    *,
    y: float,
    width: float,
    fill_bps: int,
    fill_color,
    label_text: str | None,
    label_y_offset: float | None,
    text_color,
) -> None:
    """Zeichnet einen leeren Track + farbig gefüllten Bereich."""
    # Track (Hintergrund)
    drawing.add(Rect(
        0, y, width, _BAR_HEIGHT_PT,
        fillColor=_BAR_BG_FILL,
        strokeColor=None,
    ))
    # Fill (Wert)
    fill_w = max(0.0, min(1.0, fill_bps / 10000.0)) * width
    if fill_w > 0:
        drawing.add(Rect(
            0, y, fill_w, _BAR_HEIGHT_PT,
            fillColor=fill_color,
            strokeColor=None,
        ))
    # Label-Text
    if label_text and label_y_offset is not None:
        _draw_text(drawing, label_text, x=0, y=label_y_offset, color=text_color)


def _draw_band_overlay(
    drawing: Drawing,
    *,
    y: float,
    width: float,
    min_bps: int,
    max_bps: int,
) -> None:
    """Zeichnet die Toleranzband-Schicht hinter dem SOLL-Bar (heller)."""
    if max_bps <= min_bps:
        return
    x_start = max(0.0, min(1.0, min_bps / 10000.0)) * width
    x_end = max(0.0, min(1.0, max_bps / 10000.0)) * width
    band_width = max(0.0, x_end - x_start)
    if band_width <= 0:
        return
    # Heller Akzent — Gold-Subtle, sehr leise
    drawing.add(Rect(
        x_start, y - 1, band_width, _BAR_HEIGHT_PT + 2,
        fillColor=colors.HexColor("#F5EFDC"),
        strokeColor=colors.HexColor("#E1D6B5"),
        strokeWidth=0.3,
    ))


def _draw_text(drawing: Drawing, text: str, *, x: float, y: float, color) -> None:
    """Mini-Text-Annotation auf einer Drawing-Bar."""
    from reportlab.graphics.shapes import String

    drawing.add(String(
        x, y, text,
        fontName=FONT_SANS, fontSize=FONT_SIZE_MICRO, fillColor=color,
    ))


def _paragraph_style(
    name: str, *, font: str, size: float, color, leading: float | None = None,
):
    from reportlab.lib.styles import ParagraphStyle

    return ParagraphStyle(
        name,
        fontName=font, fontSize=size,
        textColor=color, leading=leading or size + 1,
    )


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
