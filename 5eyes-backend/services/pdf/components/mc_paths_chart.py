"""ReportLab Monte-Carlo wealth path chart for Advisory-Report Section 11.

Pure ReportLab implementation of the reporting frontend's SVG chart:
p5-p75 band, p50 median, compact CHF axis labels, sparse year ticks, and
goal markers coloured by the same achievability classification.
"""
from __future__ import annotations

from typing import Any

from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, PolyLine, String
from reportlab.lib import colors
from reportlab.lib.units import mm

from services.pdf.components.advisory_palette import (
    COLOR_INK,
    COLOR_INK_MUTED,
    COLOR_INK_SUBTLE,
    COLOR_RULE,
    COLOR_STATUS_GELB,
    COLOR_STATUS_GRUEN,
    COLOR_STATUS_NEUTRAL,
    COLOR_STATUS_ROT,
    FONT_MONO,
    FONT_SANS,
    FONT_SANS_BOLD,
)
from services.pdf.components.goal_classification import classify_goals


COLOR_BAND_FILL = colors.HexColor("#DDE8EA")
COLOR_P50 = colors.HexColor("#2E5477")

STATUS_COLOR = {
    "erreichbar": COLOR_STATUS_GRUEN,
    "knapp": COLOR_STATUS_GELB,
    "nicht_erreichbar": COLOR_STATUS_ROT,
    "past": COLOR_STATUS_NEUTRAL,
    "beyond_horizon": COLOR_STATUS_NEUTRAL,
    "unknown": COLOR_STATUS_NEUTRAL,
}


def build_mc_paths_drawing(
    paths: dict[str, Any] | None,
    goals: list[dict[str, Any]],
    *,
    width_mm: float = 180,
    height_mm: float = 85,
) -> Drawing | None:
    """Build a ReportLab Drawing for Monte-Carlo p5/p50/p75 paths.

    Returns None when data is pending or malformed, matching the frontend's
    defensive `return null` path.
    """
    if not paths or paths.get("data_pending"):
        return None

    time_axis = list(paths.get("time_axis") or [])
    p5 = [_as_float(v) for v in (paths.get("p5") or [])]
    p50 = [_as_float(v) for v in (paths.get("p50") or [])]
    p75 = [_as_float(v) for v in (paths.get("p75") or [])]
    n = len(time_axis)
    if n < 2 or len(p5) != n or len(p50) != n or len(p75) != n:
        return None
    if any(v is None for v in p5 + p50 + p75):
        return None

    width = float(width_mm) * mm
    height = float(height_mm) * mm
    pad_left = 17.5 * mm
    pad_right = 6 * mm
    pad_top = 9.5 * mm
    pad_bottom = 15 * mm
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    plot_bottom = pad_bottom
    plot_top = plot_bottom + plot_h

    max_value = max(1.0, max(float(v) for v in p75) * 1.05)
    min_value = 0.0
    value_range = max_value - min_value or 1.0

    def x_for(i: int) -> float:
        return pad_left + (i / (n - 1)) * plot_w

    def y_for(value: float) -> float:
        return plot_bottom + ((value - min_value) / value_range) * plot_h

    drawing = Drawing(width, height)

    y_tick_values = [round((max_value / 4) * k) for k in range(5)]
    for k, value in enumerate(y_tick_values):
        y = y_for(float(value))
        drawing.add(Line(
            pad_left, y, width - pad_right, y,
            strokeColor=COLOR_RULE,
            strokeWidth=1 if k == 0 else 0.5,
        ))
        drawing.add(String(
            pad_left - 3 * mm,
            y - 2,
            _format_compact_chf(value),
            textAnchor="end",
            fontName=FONT_MONO,
            fontSize=7,
            fillColor=COLOR_INK_SUBTLE,
        ))

    band_points: list[float] = []
    for i, value in enumerate(p75):
        band_points.extend([x_for(i), y_for(float(value))])
    for i, value in reversed(list(enumerate(p5))):
        band_points.extend([x_for(i), y_for(float(value))])
    drawing.add(Polygon(
        band_points,
        fillColor=COLOR_BAND_FILL,
        strokeColor=None,
    ))

    p50_points: list[float] = []
    for i, value in enumerate(p50):
        p50_points.extend([x_for(i), y_for(float(value))])
    drawing.add(PolyLine(
        p50_points,
        strokeColor=COLOR_P50,
        strokeWidth=1.8,
    ))

    classifications = classify_goals(goals, paths)
    goal_by_id = {str(g.get("goal_id") or ""): g for g in goals}
    for classification in classifications:
        t_index = classification.get("t_index")
        if t_index is None:
            continue
        goal = goal_by_id.get(str(classification.get("goal_id") or ""))
        if not goal:
            continue
        target_amount = _as_float(goal.get("target_amount_rappen"))
        if target_amount is None:
            continue
        status = str(classification.get("status") or "unknown")
        marker_color = STATUS_COLOR.get(status, COLOR_STATUS_NEUTRAL)
        x = x_for(int(t_index))
        y_target = y_for(min(max(float(target_amount), min_value), max_value))
        drawing.add(Line(
            x, plot_bottom, x, plot_top,
            strokeColor=marker_color,
            strokeWidth=0.8,
            strokeDashArray=[3, 3],
        ))
        drawing.add(Circle(x, y_target, 3.6, fillColor=marker_color, strokeColor=None))

        label = str(goal.get("label") or goal.get("goal_id") or "").strip()
        if label:
            text_anchor = "start"
            label_x = x + 2.5 * mm
            if label_x > width - pad_right - 18 * mm:
                label_x = x - 2.5 * mm
                text_anchor = "end"
            label_y = min(max(y_target + 2.5 * mm, plot_bottom + 4), plot_top - 4)
            drawing.add(String(
                label_x,
                label_y,
                _shorten(label, 30),
                textAnchor=text_anchor,
                fontName=FONT_SANS_BOLD,
                fontSize=7,
                fillColor=COLOR_INK,
            ))

    x_tick_indices = _spaced_indices(n, 6)
    for i in x_tick_indices:
        drawing.add(String(
            x_for(i),
            plot_bottom - 5 * mm,
            str(time_axis[i]),
            textAnchor="middle",
            fontName=FONT_MONO,
            fontSize=7,
            fillColor=COLOR_INK_SUBTLE,
        ))

    drawing.add(Line(
        pad_left, plot_bottom, pad_left, plot_top,
        strokeColor=COLOR_INK_MUTED,
        strokeWidth=1,
    ))
    drawing.add(Line(
        pad_left, plot_bottom, width - pad_right, plot_bottom,
        strokeColor=COLOR_INK_MUTED,
        strokeWidth=1,
    ))

    _draw_legend(drawing, pad_left, height - 5 * mm)
    return drawing


def _draw_legend(drawing: Drawing, x: float, y: float) -> None:
    drawing.add(Polygon(
        [x, y - 3, x + 9, y - 3, x + 9, y + 3, x, y + 3],
        fillColor=COLOR_BAND_FILL,
        strokeColor=COLOR_P50,
        strokeWidth=0.4,
    ))
    drawing.add(String(
        x + 12, y - 2, "Band p5-p75",
        fontName=FONT_SANS,
        fontSize=7,
        fillColor=COLOR_INK_SUBTLE,
    ))
    line_x = x + 45 * mm
    drawing.add(Line(
        line_x, y, line_x + 10, y,
        strokeColor=COLOR_P50,
        strokeWidth=1.8,
    ))
    drawing.add(String(
        line_x + 13, y - 2, "Median p50",
        fontName=FONT_SANS,
        fontSize=7,
        fillColor=COLOR_INK_SUBTLE,
    ))


def _format_compact_chf(rappen: int | float) -> str:
    if rappen == 0:
        return "CHF 0"
    value = round(float(rappen) / 100)
    abs_value = abs(value)
    if abs_value >= 1_000_000:
        return f"CHF {value / 1_000_000:.1f} M"
    if abs_value >= 1_000:
        return f"CHF {value / 1_000:.0f} k"
    return f"CHF {value:.0f}"


def _spaced_indices(length: int, n_max: int) -> list[int]:
    if length <= n_max:
        return list(range(length))
    step = (length - 1) / (n_max - 1)
    return sorted({round(k * step) for k in range(n_max)})


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _shorten(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return value[: max_len - 3].rstrip() + "..."


__all__ = ["build_mc_paths_drawing"]
