"""Sprint U-P17c (2026-05-22): Wealth-Index-Chart für Backtest-PDF.

ReportLab Drawing mit Polyline + Gitter + Achsen + Legende. Eine oder
zwei Linien (SOLL + optional Benchmark). Inline-SVG-freier Ansatz, der
identisch funktioniert wie das Frontend-SVG aber als ReportLab-Drawing.
"""
from __future__ import annotations

from typing import Sequence

from reportlab.graphics.shapes import Drawing, Line, Polygon, PolyLine, Rect, String
from reportlab.lib import colors as rl_colors
from reportlab.lib.units import mm

from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    PAGE_SIZE,
)

SOLL_COLOR = rl_colors.HexColor("#1e4b8f")
BENCHMARK_COLOR = rl_colors.HexColor("#92400e")


def _format_chf(rappen: int) -> str:
    value = int(rappen) / 100
    return f"CHF {value:,.0f}".replace(",", "'")


def make_wealth_chart(
    soll_path: Sequence[Sequence],
    benchmark_path: Sequence[Sequence] | None = None,
    *,
    width_mm: float | None = None,
    height_mm: float = 70.0,
    title: str | None = None,
) -> Drawing:
    """Wealth-Index-Chart als ReportLab Drawing.

    Args:
        soll_path: [(year, rappen), ...] inkl. Initial-Eintrag
        benchmark_path: [(year, rappen), ...] optional
        width_mm: Drawing-Breite, default = Page-Innenbreite
        height_mm: Drawing-Höhe
        title: optionaler Chart-Titel (nicht der Section-Header)
    """
    page_width, _ = PAGE_SIZE
    inner_w_mm = (page_width - 24 * mm) / mm
    W = (width_mm if width_mm is not None else inner_w_mm) * mm
    H = height_mm * mm
    margin_left = 20 * mm
    margin_right = 6 * mm
    margin_top = (10 * mm) if title else (4 * mm)
    margin_bottom = 10 * mm
    inner_w = W - margin_left - margin_right
    inner_h = H - margin_top - margin_bottom

    drawing = Drawing(W, H)

    if not soll_path:
        drawing.add(String(W / 2, H / 2, "Keine Wealth-Daten",
                           textAnchor="middle", fontName=FONT_DEFAULT, fontSize=9,
                           fillColor=COLOR_TEXT_LIGHT))
        return drawing

    if title:
        drawing.add(String(margin_left, H - margin_top + 4,
                           title, fontName=FONT_BOLD, fontSize=10,
                           fillColor=COLOR_TEXT))

    series: list[tuple[Sequence[Sequence], rl_colors.Color, str]] = [
        (soll_path, SOLL_COLOR, "SOLL-Strategie"),
    ]
    if benchmark_path:
        series.append((benchmark_path, BENCHMARK_COLOR, "Benchmark"))

    # x-Domain (Years)
    all_years = [int(pt[0]) for path, _c, _l in series for pt in path]
    all_vals = [int(pt[1]) for path, _c, _l in series for pt in path]
    x_min, x_max = min(all_years), max(all_years)
    if x_max == x_min:
        x_max = x_min + 1

    # y-Domain mit 5% Padding
    y_min_raw = min(all_vals)
    y_max_raw = max(all_vals)
    y_pad = max(1, int((y_max_raw - y_min_raw) * 0.05))
    y_min = y_min_raw - y_pad
    y_max = y_max_raw + y_pad
    if y_max == y_min:
        y_max = y_min + 1

    def x_px(year: int) -> float:
        return margin_left + (year - x_min) / (x_max - x_min) * inner_w

    def y_px(val: int) -> float:
        # 0 = bottom, h = top
        return margin_bottom + (val - y_min) / (y_max - y_min) * inner_h

    # Gridlines (5 horizontal) + y-Labels
    n_grid = 5
    for i in range(n_grid + 1):
        y_val = y_min + (y_max - y_min) * (i / n_grid)
        y = margin_bottom + (i / n_grid) * inner_h
        drawing.add(Line(margin_left, y, W - margin_right, y,
                         strokeColor=COLOR_BORDER, strokeWidth=0.4))
        drawing.add(String(margin_left - 3, y - 2.5,
                           _format_chf(y_val),
                           textAnchor="end", fontName=FONT_DEFAULT, fontSize=7,
                           fillColor=COLOR_TEXT_LIGHT))

    # x-Labels: alle Jahre wenn ≤ 12, sonst jeden N-ten
    unique_years = sorted(set(all_years))
    stride = 1 if len(unique_years) <= 12 else max(1, len(unique_years) // 12)
    for idx, yr in enumerate(unique_years):
        if idx % stride == 0 or idx == len(unique_years) - 1:
            xp = x_px(yr)
            drawing.add(String(xp, margin_bottom - 7, str(yr),
                               textAnchor="middle", fontName=FONT_DEFAULT, fontSize=7,
                               fillColor=COLOR_TEXT_LIGHT))

    # Polylines
    for path, color, _label in series:
        coords: list[float] = []
        for pt in path:
            coords.extend([x_px(int(pt[0])), y_px(int(pt[1]))])
        drawing.add(PolyLine(coords, strokeColor=color, strokeWidth=1.4))

    # Legende oben rechts (oder unter Titel)
    legend_x = margin_left + 4
    legend_y = H - margin_top + 1 if not title else H - margin_top - 6
    for idx, (_path, color, label) in enumerate(series):
        yy = legend_y - idx * 5
        drawing.add(Line(legend_x, yy, legend_x + 8, yy,
                         strokeColor=color, strokeWidth=1.8))
        drawing.add(String(legend_x + 10, yy - 2,
                           label, fontName=FONT_DEFAULT, fontSize=8,
                           fillColor=COLOR_TEXT))

    return drawing
