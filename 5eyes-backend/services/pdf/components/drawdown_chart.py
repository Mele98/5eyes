"""Sprint U-P17c (2026-05-22): Drawdown-Chart für Backtest-PDF.

ReportLab Drawing mit Area-Fill (Polygon zwischen Linie und Zero-Achse).
DD-Werte sind ≤ 0, Anzeige als negatives Prozent.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from reportlab.graphics.shapes import Drawing, Line, Polygon, PolyLine, String
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


def _fmt_neg_pct(bps: int) -> str:
    if bps == 0:
        return "0%"
    return f"-{abs(bps)/100:.0f}%"


def make_drawdown_chart(
    soll_dd: Sequence[Mapping],
    benchmark_dd: Sequence[Mapping] | None = None,
    *,
    width_mm: float | None = None,
    height_mm: float = 38.0,
    title: str | None = None,
) -> Drawing:
    """Drawdown-Chart als ReportLab Drawing.

    Args:
        soll_dd: [{"year": int, "drawdown_bps": int}, ...] — bps ≤ 0
        benchmark_dd: optional gleiches Format
    """
    page_width, _ = PAGE_SIZE
    inner_w_mm = (page_width - 24 * mm) / mm
    W = (width_mm if width_mm is not None else inner_w_mm) * mm
    H = height_mm * mm
    margin_left = 20 * mm
    margin_right = 6 * mm
    margin_top = (8 * mm) if title else (3 * mm)
    margin_bottom = 8 * mm
    inner_w = W - margin_left - margin_right
    inner_h = H - margin_top - margin_bottom

    drawing = Drawing(W, H)

    if not soll_dd:
        drawing.add(String(W / 2, H / 2, "Kein Drawdown-Pfad",
                           textAnchor="middle", fontName=FONT_DEFAULT, fontSize=9,
                           fillColor=COLOR_TEXT_LIGHT))
        return drawing

    if title:
        drawing.add(String(margin_left, H - margin_top + 2,
                           title, fontName=FONT_BOLD, fontSize=10,
                           fillColor=COLOR_TEXT))

    series: list[tuple[Sequence[Mapping], rl_colors.Color, str]] = [
        (soll_dd, SOLL_COLOR, "SOLL-Strategie"),
    ]
    if benchmark_dd:
        series.append((benchmark_dd, BENCHMARK_COLOR, "Benchmark"))

    all_x = [float(d["year"]) for path, _c, _l in series for d in path]
    all_bps = [int(d.get("drawdown_bps", 0) or 0) for path, _c, _l in series for d in path]
    x_min, x_max = min(all_x), max(all_x)
    if x_max == x_min:
        x_max = x_min + 1
    y_min = min(all_bps + [0])
    y_max = 0
    if y_min == y_max:
        y_min = -100  # 1% padding
    y_min -= int(abs(y_min) * 0.1)

    def x_px(year: float) -> float:
        return margin_left + (float(year) - x_min) / (x_max - x_min) * inner_w

    def y_px(bps: int) -> float:
        return margin_bottom + (bps - y_min) / (y_max - y_min) * inner_h

    # Gridlines (3 horizontal) + y-Labels
    n_grid = 3
    for i in range(n_grid + 1):
        bps_val = y_min + (y_max - y_min) * (i / n_grid)
        y = margin_bottom + (i / n_grid) * inner_h
        drawing.add(Line(margin_left, y, W - margin_right, y,
                         strokeColor=COLOR_BORDER, strokeWidth=0.4))
        drawing.add(String(margin_left - 3, y - 2.5,
                           _fmt_neg_pct(int(bps_val)),
                           textAnchor="end", fontName=FONT_DEFAULT, fontSize=7,
                           fillColor=COLOR_TEXT_LIGHT))

    # Zero-Linie betonen
    zero_y = y_px(0)
    drawing.add(Line(margin_left, zero_y, W - margin_right, zero_y,
                     strokeColor=COLOR_TEXT_LIGHT, strokeWidth=0.6, strokeDashArray=[2, 2]))

    # X-Labels: ganzzahlige Jahre aus numerischer Domäne (Annual + Daily)
    import math as _math
    year_lo, year_hi = int(_math.floor(x_min)), int(_math.ceil(x_max))
    tick_years = list(range(year_lo, year_hi + 1))
    stride = 1 if len(tick_years) <= 12 else max(1, len(tick_years) // 12)
    for idx, yr in enumerate(tick_years):
        if (idx % stride == 0 or idx == len(tick_years) - 1) and x_min <= yr <= x_max:
            xp = x_px(yr)
            drawing.add(String(xp, margin_bottom - 6, str(yr),
                               textAnchor="middle", fontName=FONT_DEFAULT, fontSize=7,
                               fillColor=COLOR_TEXT_LIGHT))

    # Area-Polygons + Linien
    for path, color, _label in series:
        sorted_path = sorted(path, key=lambda d: float(d["year"]))
        # Polygon-Punkte: erst Wertelinie, dann zurück auf 0 für Area-Fill
        coords: list[float] = []
        for d in sorted_path:
            coords.extend([x_px(float(d["year"])), y_px(int(d.get("drawdown_bps", 0) or 0))])
        if len(coords) >= 4:
            area_coords = list(coords)
            # close back along zero
            area_coords.extend([x_px(float(sorted_path[-1]["year"])), y_px(0)])
            area_coords.extend([x_px(float(sorted_path[0]["year"])), y_px(0)])
            drawing.add(Polygon(area_coords,
                                fillColor=color,
                                fillOpacity=0.10,
                                strokeColor=None))
            drawing.add(PolyLine(coords, strokeColor=color, strokeWidth=1.2))

    # Legende (oben rechts)
    legend_x = margin_left + 4
    legend_y = H - margin_top + 1 if not title else H - margin_top - 5
    for idx, (_path, color, label) in enumerate(series):
        yy = legend_y - idx * 5
        drawing.add(Line(legend_x, yy, legend_x + 8, yy,
                         strokeColor=color, strokeWidth=1.6))
        drawing.add(String(legend_x + 10, yy - 2,
                           label, fontName=FONT_DEFAULT, fontSize=8,
                           fillColor=COLOR_TEXT))

    return drawing
